"""
Eval harness: runs every question in eval_questions.jsonl through
agent.run_agent() and grades the result, so changes to retrieval/
prompting/agent behavior can be measured against a fixed baseline
instead of eyeballed.

Six grading strategies, chosen per-question by its "type" field
(eval/questions.py holds the schema each question is checked against):
  - "numeric": exact-match. The question has one verifiable ground-truth
    number (e.g. "$72.4 billion"); grading extracts every number-like
    token from the generated answer and checks whether any of them,
    once unit-normalized, is within tolerance of the expected value.
    Deterministic and free — no LLM call needed to grade these.
  - "comparison": like "numeric", but for questions spanning multiple
    companies — requires EVERY entity in the question's "expected" list
    to have its value found in the answer, not just any one of them.
  - "judged": LLM-as-judge. For qualitative questions ("what risks does
    X describe...") or refusal questions (no ground-truth number exists
    to match), a second LLM call grades PASS/FAIL against a short
    criteria string, since there's no single correct string to diff
    against.
  - "text": a non-numeric fact (an auditor, a date). Passes when the
    answer contains one of the question's "accepted" variants, compared
    after date and punctuation normalization, and cites a source.
  - "refusal" / "clarify": judged like "judged", against a fixed template
    for the question's refusal kind or its list of readings.

v2 questions (those with a "category") also fail a comparison whose
values are attributed to the wrong company, and any answer that
attributes a listed trap value to the asked company.

Usage:
    python -m sec_agent.eval.eval_harness
    python -m sec_agent.eval.eval_harness --questions custom_questions.jsonl
    python -m sec_agent.eval.eval_harness --ids q1,q2 --verbose
    python -m sec_agent.eval.eval_harness --summarize eval/eval_results/<UTC>.json

Output is one line per question plus a summary table; the saved JSON
report keeps every detail. --verbose prints each question and its full
grading detail. --summarize reprints a saved report's summary without
running anything.
"""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from transformers.utils import logging as hf_logging

from sec_agent.agent.agent import run_agent
from sec_agent.agent.citations import ANY_CITATION_BRACKET, value_is_citation_verified
from sec_agent.eval.grading import judge_criteria_for, text_matches
from sec_agent.eval.questions import validate_questions
from sec_agent.sources.companies import COMPANIES_PATH
from sec_agent.config import (
    CHROMA_DIR,
    CHUNKS_DIR,
    DEFAULT_BACKEND,
    EMBED_MODEL_NAME,
    GEMINI_MODEL_NAME,
    PROJECT_ROOT,
    QUESTIONS_PATH,
    RERANK_MODEL_NAME,
    RESULTS_DIR,
)

# GEMINI_MODEL_NAME records which specific model actually answered/judged
# a report (see save_report()'s own docstring).
# complete() is llm_backends.py's one-shot, tool-free completion helper
# that lets grade_judged() honor --judge-backend.
from sec_agent.llm.llm_backends import BACKENDS, complete, require_backend
from sec_agent.retrieval.index_chunks import STALE_INDEX_NOTE, corpus_provenance
from sec_agent.tracing import flush, log_event
from sec_agent.verification.numeric_utils import extract_numbers, match_tolerance, normalize
from sec_agent.prompts import SNAPSHOT_PATH, prompt_fingerprint
from sec_agent.prompts.judge import JUDGE_SYSTEM_PROMPT, JUDGE_USER_TEMPLATE

# "[1]" and the multi-source "[1, 6]" both count as a citation.
CITATION_PATTERN = ANY_CITATION_BRACKET

# ---------------------------------------------------------------------------
# Numeric grading
# ---------------------------------------------------------------------------
# extract_numbers()/normalize() live in numeric_utils.py, shared with
# citations.py's citation checks -- see numeric_utils.py's docstring for why.


def grade_numeric(
    answer_text: str,
    expected_value: float,
    expected_unit: str,
    all_results: list[dict] | None = None,
    tolerance: float | None = None,
) -> tuple[bool, str]:
    """`tolerance` is relative; None means the default 1%."""
    expected_category, expected_norm = normalize(expected_value, expected_unit)
    limit = match_tolerance(expected_norm, tolerance)

    for value, unit in extract_numbers(answer_text):
        category, norm = normalize(value, unit)
        if category != expected_category:
            continue
        if abs(norm - expected_norm) <= limit:
            # A plain-text match isn't enough on its own: the value must
            # also be grounded wherever it's cited. all_results is optional
            # (None skips this) for callers with no citation context. The
            # same tolerance picks which claims count as this value.
            if all_results is not None and not value_is_citation_verified(
                expected_value, expected_unit, answer_text, all_results, tolerance
            ):
                return False, (
                    f"found matching value: {value} ({unit}) but its citation isn't actually "
                    "supported by the source (likely self-computed or misattributed)"
                )
            return True, f"found matching value: {value} ({unit})"

    return False, f"no value matching {expected_value} {expected_unit} found in answer"


def grade_comparison(
    answer_text: str, expected: list[dict], all_results: list[dict] | None = None, tolerance: float | None = None
) -> tuple[bool, str]:
    """Like grade_numeric, but for questions spanning multiple companies:
    passes only if EVERY entry in `expected` (each a {"ticker",
    "expected_value", "expected_unit"} dict) has its value found in the
    answer — not just any one of them. Reuses grade_numeric per entity
    rather than duplicating the extraction/tolerance logic, including
    its citation-verification check when `all_results` is given.

    Known limitation: this doesn't check that a found number is
    correctly *attributed* to the right entity in the general case (e.g.
    it would still pass if the answer accidentally swapped which
    company a number was reported for while still citing SOME source for
    it) — only that both numbers appear somewhere in the text and, if
    `all_results` is given, that each is backed by an actual citation
    somewhere. Good enough to catch "dropped an entity entirely" and
    "cited a value that isn't actually in any source," the two failure
    modes this type has concretely hit; a full entity-swap check would
    need a smarter (likely LLM-judge-based) check layered on top.
    v2 questions get a lexical attribution check on top, in
    _grade_by_type().
    """
    missing = []
    for entry in expected:
        passed, _ = grade_numeric(answer_text, entry["expected_value"], entry["expected_unit"], all_results, tolerance)
        if not passed:
            missing.append(f"{entry['ticker']} ({entry['expected_value']} {entry['expected_unit']})")

    if missing:
        return False, f"missing or wrong value(s) for: {', '.join(missing)}"
    return True, f"found matching values for all {len(expected)} entities"


# ---------------------------------------------------------------------------
# LLM-as-judge grading
# ---------------------------------------------------------------------------
def grade_judged(question: str, answer_text: str, criteria: str, backend: str = "gemini") -> tuple[bool, str]:
    """Routes through llm_backends.complete() so `backend` (--judge-
    backend) picks which one actually grades, at the same temperature=0.0
    (stricter than generation's 0.1) and no tool_schemas -- grading never
    calls tools. complete() reuses each backend's existing retry/backoff/
    log_event machinery, so that guarantee holds here too.

    Injects the real wall-clock date (same datetime.now(timezone.utc)
    pattern as save_report()'s timestamp) so the judge isn't relying on
    its own stale training-cutoff sense of "now" -- without this, a judge
    model trained before a filing's real date reflexively calls a
    correctly-cited current filing "hypothetical future data". This
    assumes grading happens contemporaneously with generation -- true for
    every call site today (grade_judged only ever runs synchronously
    inside _run_one, right after the answer is generated); would need
    revisiting if a regrade-from-saved-report tool is ever added.

    Output whose first line isn't exactly PASS or FAIL is graded exactly
    as before, but its reason is prefixed so reports show how often the
    judge strays from the format -- and whether a lenient reading would
    have graded it differently."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_prompt = JUDGE_USER_TEMPLATE.format(today=today, question=question, criteria=criteria, answer=answer_text)
    verdict_text = complete(backend, JUDGE_SYSTEM_PROMPT, user_prompt, temperature=0.0)

    first_line = verdict_text.splitlines()[0].strip().upper() if verdict_text else ""
    passed = first_line.startswith("PASS")
    reason = verdict_text.splitlines()[1].strip() if len(verdict_text.splitlines()) > 1 else verdict_text
    prefix = _nonstandard_output_prefix(verdict_text, first_line, passed)
    if prefix is not None:
        log_event("judge_nonstandard_output", prefix=prefix, passed=passed)
        reason = f"{prefix} {reason}"
    return passed, reason


def _lenient_verdict(verdict_text: str) -> bool | None:
    """PASS or FAIL read as a whole word from the first line naming
    either, so a reason line mentioning the other word doesn't cancel it.
    None when no line names one, or that line names both."""
    for line in verdict_text.upper().splitlines():
        words = set(re.findall(r"\b(PASS|FAIL)\b", line))
        if words:
            return words == {"PASS"} if len(words) == 1 else None
    return None


def _nonstandard_output_prefix(verdict_text: str, first_line: str, passed: bool) -> str | None:
    """None for the expected format (a first line of exactly PASS or
    FAIL). Otherwise a prefix quoting the first line; "lenient parse
    disagrees" marks output a whole-word reading would have graded the
    other way (e.g. "**PASS**", which the startswith check grades FAIL)."""
    if first_line in ("PASS", "FAIL"):
        return None
    evidence = repr(first_line)[:60]
    lenient = _lenient_verdict(verdict_text)
    if lenient is not None and lenient != passed:
        return f"[nonstandard judge output; lenient parse disagrees: {evidence}]"
    return f"[nonstandard judge output: {evidence}]"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def load_questions(path: Path) -> list[dict]:
    questions = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    # Before any question runs: a malformed one would otherwise fail
    # mid-run, after quota has been spent on the ones before it.
    validate_questions(questions)
    return questions


def _select_questions(questions: list[dict], ids: list[str] | None, include_skipped: bool) -> list[dict]:
    """Applies --ids / skip-flag filtering, kept separate from
    run_eval()'s live agent loop so it's testable without network/LLM
    calls. Explicit `ids` always wins over a question's own `skip` flag
    -- asking for a question by ID directly is a stronger signal than
    the file's default, and is how you'd re-run a skip-flagged question
    on demand without editing eval_questions.jsonl. Result follows the
    file's own order, not the order `ids` were given in."""
    if ids is not None:
        wanted = set(ids)
        selected = [q for q in questions if q["id"] in wanted]
        missing = wanted - {q["id"] for q in selected}
        if missing:
            raise ValueError(f"Unknown question id(s): {sorted(missing)}")
        return selected
    if include_skipped:
        return questions
    return [q for q in questions if not q.get("skip")]


# Graded without an LLM, so a stored answer can be re-graded offline.
DETERMINISTIC_TYPES = ("numeric", "comparison", "text")


def grade_text(answer_text: str, accepted: list[str]) -> tuple[bool, str]:
    if not text_matches(answer_text, accepted):
        return False, f"none of the accepted answers found: {', '.join(accepted)}"
    if not CITATION_PATTERN.search(answer_text):
        return False, "found accepted text, but the answer has no citation marker"
    return True, "found accepted text"


def _grade_by_type(q: dict, answer_text: str, retrieved: list[dict] | None) -> tuple[bool, str]:
    """The deterministic grade of a DETERMINISTIC_TYPES question, shared by
    _grade() (the real verdict), _citation_gate_evidence() (would the
    withheld text have passed) and the offline gate replay, so all three
    agree. Caller confirms the type first.

    A value or text match is checked first; on a pass, an `accepted`
    list on a numeric or comparison question must also match (an
    ambiguous question's answer has to name which reading it took).
    Which company a value belongs to, and `forbidden_values`, aren't
    graded yet: that check is to come from the agent's submitted claims
    and the ticker of the source each one cites, not from the prose."""
    tolerance = q.get("tolerance")
    if q["type"] == "numeric":
        passed, detail = grade_numeric(answer_text, q["expected_value"], q["expected_unit"], retrieved, tolerance)
    elif q["type"] == "comparison":
        passed, detail = grade_comparison(answer_text, q["expected"], retrieved, tolerance)
    else:
        passed, detail = grade_text(answer_text, q["accepted"])
    if not passed:
        return passed, detail
    if q["type"] != "text" and "accepted" in q and not text_matches(answer_text, q["accepted"]):
        return False, f"{detail}, but none of the accepted answers found: {', '.join(q['accepted'])}"
    return True, detail


def _grade(
    q: dict, answer_text: str, citation_warnings: list[str], retrieved: list[dict], judge_backend: str = "gemini"
) -> tuple[bool, str]:
    """Dispatches to the right grading strategy for question type
    q["type"], kept separate from run_eval()'s live agent loop so it's
    testable without network/LLM calls (same rationale as
    _select_questions() above).

    Numeric/comparison questions short-circuit to FAIL when the agent
    hard-gate-refused (non-empty citation_warnings) instead of calling
    grade_numeric()/grade_comparison() on the refusal text -- a refusal
    message necessarily repeats the claimed value it's rejecting, which
    a plain text scan could otherwise match as if it were a real,
    verified answer.
    Judged, refusal and clarify questions are deliberately NOT
    short-circuited here: some expect a refusal, and grade_judged()
    checks the actual answer text against its criteria, which is the
    correct way to check whether refusing was the right call.

    `judge_backend` is passed straight through to grade_judged() -- see
    run_eval()'s docstring for why it isn't just reused from `backend`."""
    if citation_warnings and q["type"] in DETERMINISTIC_TYPES:
        return False, "agent refused to answer (hard-gated on unverified citation(s)) -- no value to grade"
    if q["type"] in DETERMINISTIC_TYPES:
        return _grade_by_type(q, answer_text, retrieved)
    if q["type"] == "judged":
        return grade_judged(q["question"], answer_text, q["criteria"], judge_backend)
    if q["type"] in ("refusal", "clarify"):
        return grade_judged(q["question"], answer_text, judge_criteria_for(q), judge_backend)
    raise ValueError(f"Unknown question type: {q['type']!r} in question {q['id']!r}")


def _empty_citation_gate_evidence() -> dict:
    """A fresh dict on every call -- deliberately NOT a module-level
    constant. `citation_warning_details` is a list; a shared constant
    would hand every row in a batch the SAME list object via a shallow
    `dict(...)`/`**` copy -- harmless today since nothing mutates it in
    place, but a silent corrupt-every-other-row trap waiting for the
    next edit that does. See
    docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md."""
    return {
        "withheld_answer": None,
        "gate_withheld_would_have_passed": None,
        "gate_withheld_detail": None,
        "citation_warning_details": [],
    }


def _citation_gate_evidence(
    q: dict, retrieved: list[dict], withheld_answer: str | None, citation_warning_details: list[dict]
) -> dict:
    """The 4 additive report fields the citation-gate FP/FN measurement
    work needs. `_grade()`'s own short-circuit still scores a hard-gated
    numeric/comparison question as FAIL -- that user-facing verdict is
    untouched here. This is purely additional evidence: what the model
    actually said before the hard gate withheld it, and whether that
    text would have passed the existing grader if the gate hadn't fired.

    Only populated when the gate actually refused a DETERMINISTIC_TYPES
    question -- a judged one has no ground truth to re-grade against,
    and a passing row has nothing withheld to re-grade in the
    first place. `gate_withheld_would_have_passed` re-runs the SAME
    grade_numeric()/grade_comparison() (via _grade_by_type(), shared with
    _grade()'s real verdict) the real verdict would have used.

    `citation_warning_details` is passed straight through from
    `AgentResult.citation_warning_details` (the caller already has it)
    rather than re-derived from the answer text, so
    analyze_citation_gate.py's false_positive_by_check breakdown names
    the checks that actually refused it."""
    if withheld_answer is None or q["type"] not in DETERMINISTIC_TYPES:
        return _empty_citation_gate_evidence()

    would_pass, would_detail = _grade_by_type(q, withheld_answer, retrieved)

    return {
        "withheld_answer": withheld_answer,
        "gate_withheld_would_have_passed": would_pass,
        "gate_withheld_detail": would_detail,
        "citation_warning_details": citation_warning_details,
    }


def run_eval(
    questions: list[dict],
    backend: str | None = None,
    judge_backend: str | None = None,
    verbose: bool = False,
) -> list[dict]:
    """`backend=None` resolves to config.DEFAULT_BACKEND, resolved HERE
    rather than via a literal `= DEFAULT_BACKEND` parameter default -- a
    parameter default is bound once at module-import time and would
    silently freeze in whatever DEFAULT_BACKEND was at that moment,
    ignoring any later change (same reasoning as agent.run_agent()'s
    matching fix).

    `judge_backend` then defaults to `backend` itself, so a run answers
    and judges with the same backend unless --judge-backend says
    otherwise. Both are checked before the first question: argparse
    doesn't check a default against `choices`, and per question a bad
    name would only be caught by _run_one()'s isolation and saved as an
    all-failed report.

    Prints one compact line per question, its id before the run and its
    outcome after, so a slow or stuck question is named on screen.
    `verbose` prints the question text instead and the full detail."""
    backend = backend or DEFAULT_BACKEND
    judge_backend = judge_backend or backend
    require_backend(backend)
    require_backend(judge_backend)
    results = []

    for index, q in enumerate(questions, start=1):
        if verbose:
            print(f"[{q['id']}] {q['question']}")
        else:
            print(_question_prefix(q, index, len(questions)), end="", flush=True)
        row = _run_one(q, backend, judge_backend)
        print("\n".join(_progress_lines(row, verbose)))
        results.append(row)

    flush()
    return results


def _row_identity(q: dict) -> dict:
    """The question fields a report row repeats. v2's category and trap
    are copied when present, so a saved report can be summarized by
    category without its question file."""
    row = {
        "id": q["id"],
        "ticker": q.get("ticker") or q.get("tickers"),
        "question": q["question"],
        "type": q["type"],
    }
    row.update({key: q[key] for key in ("category", "trap") if key in q})
    return row


def _run_one(q: dict, backend: str, judge_backend: str) -> dict:
    """Answers and grades one question, returning its report row."""
    row_id = _row_identity(q)
    try:
        result = run_agent(q["question"], backend=backend)
        answer_text, retrieved, citation_warnings = result.answer, result.results, result.citation_warnings
        # Excludes hard-gated refusals: submission.py's _format_refusal_message()
        # echoes each warning's own "[n] claims ..." text verbatim, which
        # still matches CITATION_PATTERN, so a refusal would otherwise get
        # has_citation=True -- a real answer's citation and a refusal's
        # description of a FAILED citation shouldn't count the same way in
        # this stat.
        has_citation = not citation_warnings and bool(CITATION_PATTERN.search(answer_text))

        passed, detail = _grade(q, answer_text, citation_warnings, retrieved, judge_backend)
        gate_fields = _citation_gate_evidence(q, retrieved, result.withheld_answer, result.citation_warning_details)
    except Exception as e:
        # Broad on purpose: a network error, exhausted retries, or an
        # unexpected bug in run_agent()/_grade() should all fail just
        # THIS question the same way, not silently discard every
        # already-graded result in the batch before it (no partial
        # report, no flush) -- this is a boundary where many
        # different failure types should all degrade identically.
        return {
            **row_id,
            "passed": False,
            "detail": f"{type(e).__name__}: {e}",
            "has_citation": False,
            "citation_warnings": [],
            "answer": None,
            "n_chunks_retrieved": 0,
            **_empty_citation_gate_evidence(),
        }

    return {
        **row_id,
        "passed": passed,
        "detail": detail,
        "has_citation": has_citation,
        "citation_warnings": citation_warnings,
        "answer": answer_text,
        "n_chunks_retrieved": len(retrieved),
        **gate_fields,
    }


def _is_error(row: dict) -> bool:
    """True for a row from _run_one()'s exception branch: every graded
    row has a real answer string, even a refusal."""
    return row.get("answer") is None


def _truncate(text: str, limit: int = 150) -> str:
    """Also flattens whitespace: an exception message can span lines."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _citation_flags(row: dict) -> str:
    flags = "" if row.get("has_citation") else "  [no citation]"
    return flags + ("  [unverified citation]" if row.get("citation_warnings") else "")


def _question_prefix(q: dict, index: int, total: int) -> str:
    return f"[{index:>{len(str(total))}}/{total}] {q['id']} ({q['type']})  "


def _progress_lines(row: dict, verbose: bool) -> list[str]:
    """The stdout for one finished question. Compact mode gives only the
    outcome, ending the line _question_prefix() started, and leaves the
    detail to the saved report; an error still shows the start of its
    detail, so a quota error is visible mid-run."""
    if verbose:
        if _is_error(row):
            return [f"  -> ERROR: {row['detail']}"]
        lines = [f"  -> {'PASS' if row['passed'] else 'FAIL'} ({row['detail']})"]
        if not row["has_citation"]:
            lines.append("  -> WARNING: answer has no [n] citation marker at all")
        lines.extend(f"  -> CITATION WARNING: {w}" for w in row["citation_warnings"])
        return lines

    if _is_error(row):
        return [f"ERROR  {_truncate(row['detail'], 80)}"]
    return [("PASS" if row["passed"] else "FAIL") + _citation_flags(row)]


def _breakdown_table(results: list[dict], key: str) -> list[str]:
    """Counts per value of row[key] (type, or v2's category), in
    first-seen order; rows without the key are left out. The label column
    fits the longest value. An error row counts under errors only, not
    no-cite: it never produced an answer."""
    groups = dict.fromkeys(r[key] for r in results if key in r)
    width = max([10, *(len(g) for g in groups)])
    lines = [f"{key:<{width}}{'passed':>8}{'no-cite':>9}{'unverified':>12}{'errors':>8}"]
    for group in groups:
        rows = [r for r in results if r.get(key) == group]
        passed = sum(r["passed"] for r in rows)
        errors = sum(_is_error(r) for r in rows)
        no_cite = sum(not _is_error(r) and not r.get("has_citation", False) for r in rows)
        unverified = sum(bool(r.get("citation_warnings")) for r in rows)
        lines.append(f"{group:<{width}}{f'{passed}/{len(rows)}':>8}{no_cite:>9}{unverified:>12}{errors:>8}")
    return lines


def format_summary(results: list[dict]) -> str:
    """Reads the citation fields with defaults so reports written before
    they existed still summarize."""
    total = len(results)
    passed = sum(r["passed"] for r in results)
    cited = sum(bool(r.get("has_citation")) for r in results)
    unverified = sum(bool(r.get("citation_warnings")) for r in results)

    lines = [
        "=" * 60,
        f"Results: {passed}/{total} passed, {cited}/{total} included a citation marker, "
        f"{unverified}/{total} had at least one unverified numeric citation",
        *_breakdown_table(results, "type"),
        *(_breakdown_table(results, "category") if any("category" in r for r in results) else []),
    ]
    failed = [r for r in results if not r["passed"]]
    if failed:
        lines.append(f"Not passed ({len(failed)}):")
        for r in failed:
            label = f"{r['id']} ({r['type']})"
            separator = " ERROR:" if _is_error(r) else ":"
            lines.append(f"  {label}{separator} {_truncate(r['detail'])}")
    flagged = [r for r in results if r["passed"] and _citation_flags(r)]
    if flagged:
        lines.append(f"Passed with citation flags ({len(flagged)}):")
        lines.extend(f"  {r['id']} ({r['type']}){_citation_flags(r)}" for r in flagged)
    return "\n".join(lines)


def print_summary(results: list[dict]) -> None:
    print("\n" + format_summary(results))


def _model_name_for(backend: str) -> str:
    # Gemini is the only backend; this stays a function so a new backend
    # adds its model setting here.
    return GEMINI_MODEL_NAME


# ---------------------------------------------------------------------------
# Provenance -- what a report needs to be tied to the exact code and prompt
# version that produced it. Collected before any quota is spent, and never
# allowed to raise: a provenance failure must not cost the eval run.
# ---------------------------------------------------------------------------
# Uncommitted edits to these make a report's git SHA misleading: code,
# prompt text and its snapshot, the company list rendered into the
# prompt, and the questions. `*.py` matches at any depth, so a tests-only
# edit, or a stray untracked script anywhere not gitignored, counts as
# dirty too: the safe side, and the files are named in dirty_files.
PROVENANCE_PATHSPECS = (
    "*.py",
    *(
        path.resolve().relative_to(PROJECT_ROOT).as_posix()
        for path in (SNAPSHOT_PATH.parent, COMPANIES_PATH, QUESTIONS_PATH)
    ),
)
SNAPSHOT_TEST = "tests/prompts/test_model_input_snapshot.py::test_model_input_matches_committed_snapshot"
# The check normally takes about 20s; a hang (a locked model cache, a
# stuck import) must not stop the eval from starting.
SNAPSHOT_CHECK_TIMEOUT = 300


class GitError(Exception):
    """A git command exited non-zero."""


def _git(*args: str) -> str:
    # Binary mode plus an explicit UTF-8 decode: text mode would decode
    # with the Windows code page and garble non-ASCII paths.
    result = subprocess.run(["git", *args], capture_output=True, check=False, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {stderr}")
    return result.stdout.decode("utf-8")


def _porcelain_paths(output: str) -> set[str]:
    """Paths from `git status --porcelain -z` output. A rename or copy
    entry is followed by a separate entry holding the original path,
    which is skipped."""
    paths = set()
    entries = iter(output.split("\0"))
    for entry in entries:
        if not entry:
            continue
        paths.add(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            next(entries, None)
    return paths


def _try_git(*args: str) -> str | None:
    """_git's output, or None (logged) if git failed."""
    try:
        return _git(*args)
    except (OSError, GitError, UnicodeDecodeError) as e:
        log_event("eval_provenance_git_failed", error=f"{type(e).__name__}: {e}")
        return None


def _git_state(extra: tuple[str, ...] = ()) -> dict:
    """The HEAD SHA and any uncommitted changes to PROVENANCE_PATHSPECS
    plus `extra` (a non-default question file). A failed git call gives
    git_sha "unknown" or git_dirty None; never raises."""
    sha = _try_git("rev-parse", "--short", "HEAD")
    # Untracked files count: a new module that code imports but nobody
    # `git add`ed would otherwise leave the tree looking clean while the
    # SHA can't reproduce the run.
    status = _try_git(
        "--no-optional-locks",
        "status",
        "--porcelain",
        "-z",
        "--untracked-files=all",
        "--",
        *PROVENANCE_PATHSPECS,
        *extra,
    )
    dirty = None if status is None else sorted(_porcelain_paths(status))
    return {
        "git_sha": "unknown" if sha is None else sha.strip(),
        "git_dirty": None if dirty is None else bool(dirty),
        "dirty_files": dirty or [],
    }


def _run_snapshot_check() -> int:
    """Runs the model-input snapshot comparison in a subprocess, keeping
    its fake backend and monkeypatching out of this process, and returns
    pytest's exit code. UPDATE_SNAPSHOT is removed so the check can only
    compare, never rewrite the committed file."""
    env = {k: v for k, v in os.environ.items() if k != "UPDATE_SNAPSHOT"}
    command = [sys.executable, "-m", "pytest", SNAPSHOT_TEST, "-q", "-p", "no:cacheprovider"]
    run = subprocess.run(
        command, capture_output=True, check=False, cwd=PROJECT_ROOT, env=env, timeout=SNAPSHOT_CHECK_TIMEOUT
    )
    return run.returncode


def _snapshot_verified() -> bool | None:
    """Whether src/sec_agent/prompts/model_input_snapshot.json matches what the current
    code sends a model. The fingerprint hashes that committed file, so a
    stale one would mislabel this run. True or False when the check ran;
    None when it couldn't (pytest missing, or the run errored or hung)."""
    if importlib.util.find_spec("pytest") is None:
        return None
    try:
        returncode = _run_snapshot_check()
    except (OSError, subprocess.TimeoutExpired) as e:
        log_event("eval_provenance_snapshot_check_failed", error=f"{type(e).__name__}: {e}")
        return None
    if returncode in (0, 1):
        return returncode == 0
    log_event("eval_provenance_snapshot_check_failed", returncode=returncode)
    return None


def _root_relative(path: str) -> str:
    # Reports are committed: keep a machine-specific checkout prefix out.
    resolved = Path(path)
    return resolved.relative_to(PROJECT_ROOT).as_posix() if resolved.is_relative_to(PROJECT_ROOT) else path


def _run_config() -> dict:
    """Settings that change what the model sees but that git can't
    record: .env values (untracked) and the versions of the libraries
    that build its requests."""
    versions = {}
    for key, distribution in (("google_genai", "google-genai"), ("mcp", "mcp")):
        try:
            versions[key] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[key] = None
    return {
        "gemini_model": GEMINI_MODEL_NAME,
        "embed_model": EMBED_MODEL_NAME,
        "rerank_model": RERANK_MODEL_NAME,
        "chroma_dir": _root_relative(CHROMA_DIR),
        **versions,
    }


def _questions_provenance(path: Path) -> dict:
    """{path, sha256} of the question file a run used. The hash is of the
    text with CRLF normalized to LF, so git's line-ending conversion on
    checkout can't make one file look like two. sha256 is None (logged)
    when the file can't be read; never raises."""
    try:
        digest = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]
    except OSError as e:
        log_event("eval_provenance_questions_failed", path=str(path), error=f"{type(e).__name__}: {e}")
        digest = None
    return {"path": _root_relative(str(path.resolve())), "sha256": digest}


def _collect_provenance(questions_path: Path = QUESTIONS_PATH) -> dict:
    """{git_sha, git_dirty, dirty_files, snapshot_verified, config,
    index_matches_chunks, prompts}. Never raises: each part degrades to a
    marker value. The corpus identity goes in config, since a different
    corpus makes two runs incomparable; whether the index matches it sits
    outside config, so a rebuild of the same corpus doesn't read as a
    config change. The question file is in config too, so v1 and v2 runs
    are never pooled."""
    corpus = corpus_provenance(CHUNKS_DIR, CHROMA_DIR)
    questions = _questions_provenance(questions_path)
    # A file outside the checkout has no git status; its hash still names it.
    in_repo = not Path(questions["path"]).is_absolute()
    provenance = {
        **_git_state((questions["path"],) if in_repo else ()),
        "snapshot_verified": _snapshot_verified(),
        "config": {**_run_config(), "corpus": corpus["corpus"], "questions": questions},
        "index_matches_chunks": corpus["index_matches_chunks"],
    }
    try:
        provenance["prompts"] = prompt_fingerprint()
    except Exception as e:
        # Broad on purpose: whatever breaks the fingerprint (a missing or
        # malformed snapshot, a new non-JSON constant), the run should go
        # ahead with the failure recorded rather than stop before it starts.
        log_event("eval_provenance_fingerprint_failed", error=f"{type(e).__name__}: {e}")
        provenance["prompts"] = "error"
    return provenance


def _provenance_warnings(provenance: dict) -> list[str]:
    """One line per reason this run's report can't be trusted to describe
    the committed code and prompts. Covers every condition under which
    compare_prompt_versions leaves the report out of comparisons, so a run
    that will be excluded says so when it starts (plus a failed
    fingerprint)."""
    warnings = []
    sha = provenance.get("git_sha")
    if not sha or sha == "unknown":
        warnings.append("git state unknown, so the report records no commit")
    dirty = provenance.get("git_dirty")
    if dirty is None:
        warnings.append("git status unknown, so the tree can't be shown to be clean")
    elif dirty:
        files = ", ".join(provenance.get("dirty_files", []))
        warnings.append(f"uncommitted changes, so the git SHA doesn't describe this run: {files}")
    if provenance.get("snapshot_verified") is not True:
        warnings.append(
            "src/sec_agent/prompts/model_input_snapshot.json isn't verified against the current code "
            f"(snapshot_verified={provenance.get('snapshot_verified')}), so the prompt fingerprint may be wrong"
        )
    if provenance.get("prompts") == "error":
        warnings.append("the prompt fingerprint couldn't be computed")
    if provenance.get("index_matches_chunks") is False:
        warnings.append(STALE_INDEX_NOTE)
    return warnings


def save_report(
    results: list[dict], backend: str, judge_backend: str | None = None, provenance: dict | None = None
) -> Path:
    """`backend` ("gemini") alone doesn't say which specific model
    answered -- GEMINI_MODEL_NAME is configurable via .env and can change over time, which would make an
    old report ambiguous about what actually produced it. `answer_model`
    records whichever one actually ran; `judge_model` records whichever
    backend actually judged -- `judge_backend` defaults to `backend`
    itself, same reasoning as run_eval()'s own default (see that
    function's docstring). `provenance` (see _collect_provenance()) is
    written only when given."""
    judge_backend = judge_backend or backend
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{timestamp}.json"
    report: dict = {
        "backend": backend,
        "answer_model": _model_name_for(backend),
        "judge_model": _model_name_for(judge_backend),
    }
    if provenance is not None:
        report["provenance"] = provenance
    report["results"] = results
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return out_path


def load_report(path: Path) -> dict:
    """A saved report as {"results": [...], ...}. Reports written before
    the dict wrapper existed are a bare list of rows. Raises ValueError
    for JSON of any other shape."""
    with path.open(encoding="utf-8") as f:
        report = json.load(f)
    if isinstance(report, list):
        report = {"results": report}
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        raise ValueError("not an eval report: expected a list of rows or a dict with a 'results' list")
    return report


def format_report_header(name: str, report: dict) -> str:
    """`prompts` is _collect_provenance()'s per-module fingerprint dict, or
    "error" when it couldn't be computed; the agent and judge entries are
    the ones reports are compared by."""
    provenance = report.get("provenance", {})
    git = provenance.get("git_sha", "?") + (" (dirty)" if provenance.get("git_dirty") else "")
    prompts = provenance.get("prompts", "?")
    if isinstance(prompts, dict):
        agent, judge = prompts.get("agent", "?"), prompts.get("judge", "?")
    else:
        agent = judge = prompts
    return (
        f"Report {name}: backend={report.get('backend', '?')} answer_model={report.get('answer_model', '?')} "
        f"git={git} agent_prompts={agent} judge_prompts={judge}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        help="comma-separated question IDs to run (default: all, minus any skip: true questions)",
    )
    parser.add_argument(
        "--include-skipped",
        action="store_true",
        help="also run questions marked skip: true (ignored if --ids is given)",
    )
    parser.add_argument(
        "--backend", choices=list(BACKENDS), default=DEFAULT_BACKEND, help="which LLM backend to use"
    )
    parser.add_argument(
        "--judge-backend",
        choices=list(BACKENDS),
        default=None,
        help="which LLM backend grades judged-type questions (default: same as --backend)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="print each question and its full grading detail as it runs"
    )
    parser.add_argument(
        "--summarize",
        type=Path,
        metavar="REPORT",
        help="print the summary of a saved report and exit, running nothing (other options are ignored)",
    )
    args = parser.parse_args()

    if args.summarize:
        try:
            report = load_report(args.summarize)
        except (OSError, ValueError) as e:
            parser.error(f"can't read report {args.summarize}: {e}")
        print(format_report_header(args.summarize.name, report))
        print(format_summary(report["results"]))
        return

    # Before provenance, whose snapshot check can take minutes, so a bad
    # --ids or --questions fails at once.
    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
    try:
        questions = _select_questions(load_questions(args.questions), ids, args.include_skipped)
    except (OSError, ValueError) as e:
        parser.error(str(e))

    # Before run_eval, so it records the code as it was when the run
    # started and costs nothing if it fails.
    provenance = _collect_provenance(args.questions)
    for warning in _provenance_warnings(provenance):
        print(f"WARNING: {warning}")

    # transformers reads its progress-bar switch once at import, which has
    # already happened through run_agent's imports, so an environment
    # variable set now would be too late. This also turns off the
    # huggingface_hub bars.
    hf_logging.disable_progress_bar()
    results = run_eval(questions, backend=args.backend, judge_backend=args.judge_backend, verbose=args.verbose)
    print_summary(results)
    out_path = save_report(results, backend=args.backend, judge_backend=args.judge_backend, provenance=provenance)
    print(f"\nFull report saved to {out_path}")
    # A print, not an import -- analyze_citation_gate.py stays a
    # standalone reader of the report file, not coupled to this module.
    print(f"Citation-gate FP/FN breakdown: python -m sec_agent.devtools.analyze_citation_gate {out_path}")


if __name__ == "__main__":
    main()
