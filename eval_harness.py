"""
Eval harness: runs every question in eval_questions.jsonl through
agent.run_agent() and grades the result, so changes to retrieval/
prompting/agent behavior can be measured against a fixed baseline
instead of eyeballed. See
docs/decisions/2026-08-13-eval-harness-scaffolding-and-early-bug-hunts.md.

Three grading strategies, chosen per-question by its "type" field:
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

Usage:
    python eval_harness.py
    python eval_harness.py --questions custom_questions.jsonl
"""

import argparse
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent import run_agent, value_is_citation_verified
from config import (
    CHROMA_DIR,
    DEFAULT_BACKEND,
    EMBED_MODEL_NAME,
    GEMINI_MODEL_NAME,
    RERANK_MODEL_NAME,
)

# GEMINI_MODEL_NAME records which specific model actually answered/judged
# a report (see save_report()'s own docstring).
# complete() is llm_backends.py's one-shot, tool-free completion helper
# that lets grade_judged() honor --judge-backend. See
# docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md.
from llm_backends import BACKENDS, complete
from tracing import flush, log_event
from numeric_utils import extract_numbers, normalize
from prompts import prompt_fingerprint
from prompts.judge import JUDGE_SYSTEM_PROMPT, JUDGE_USER_TEMPLATE

QUESTIONS_PATH = Path("./eval/eval_questions.jsonl")
# Anchored to this file, matching compare_prompt_versions.py, which reads it.
RESULTS_DIR = Path(__file__).resolve().parent / "eval" / "eval_results"

CITATION_PATTERN = re.compile(r"\[\d+\]")

# ---------------------------------------------------------------------------
# Numeric grading
# ---------------------------------------------------------------------------
# extract_numbers()/normalize() live in numeric_utils.py, shared with
# agent.py's verify_citations() -- see that module's docstring for why.


def grade_numeric(
    answer_text: str, expected_value: float, expected_unit: str, all_results: list[dict] | None = None
) -> tuple[bool, str]:
    expected_category, expected_norm = normalize(expected_value, expected_unit)
    tolerance = max(0.01 * abs(expected_norm), 0.05)  # 1% relative, with a small floor

    for value, unit in extract_numbers(answer_text):
        category, norm = normalize(value, unit)
        if category != expected_category:
            continue
        if abs(norm - expected_norm) <= tolerance:
            # A plain-text match isn't enough on its own -- all_results
            # is optional (None skips this) so existing/simple callers
            # that don't have citation context keep working unchanged.
            # See docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md.
            if all_results is not None and not value_is_citation_verified(
                expected_value, expected_unit, answer_text, all_results
            ):
                return False, (
                    f"found matching value: {value} ({unit}) but its citation isn't actually "
                    "supported by the source (likely self-computed or misattributed)"
                )
            return True, f"found matching value: {value} ({unit})"

    return False, f"no value matching {expected_value} {expected_unit} found in answer"


def grade_comparison(
    answer_text: str, expected: list[dict], all_results: list[dict] | None = None
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
    """
    missing = []
    for entry in expected:
        passed, _ = grade_numeric(answer_text, entry["expected_value"], entry["expected_unit"], all_results)
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
    inside run_eval, right after the answer is generated); would need
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


def _grade_by_type(q: dict, answer_text: str, retrieved: list[dict] | None) -> tuple[bool, str]:
    """Numeric/comparison type dispatch shared between _grade() below
    (the real pass/fail verdict) and _citation_gate_evidence() (the
    "would this have passed" check on the withheld text) -- both need
    the same two calls, so this avoids updating two places in sync for a
    signature change or a third gradeable type. Caller is responsible
    for confirming q["type"] is one of these two first."""
    if q["type"] == "numeric":
        return grade_numeric(answer_text, q["expected_value"], q["expected_unit"], retrieved)
    return grade_comparison(answer_text, q["expected"], retrieved)


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
    Judged questions are deliberately NOT short-circuited here: some are
    written to expect a refusal, and grade_judged() already evaluates
    the actual answer text against its own criteria, which is the
    correct way to check whether refusing was the right call.

    `judge_backend` is passed straight through to grade_judged() -- see
    run_eval()'s docstring for why it isn't just reused from `backend`."""
    if citation_warnings and q["type"] in ("numeric", "comparison"):
        return False, "agent refused to answer (hard-gated on unverified citation(s)) -- no value to grade"
    if q["type"] in ("numeric", "comparison"):
        return _grade_by_type(q, answer_text, retrieved)
    if q["type"] == "judged":
        return grade_judged(q["question"], answer_text, q["criteria"], judge_backend)
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

    Only populated when the gate actually refused a numeric/comparison
    question -- a judged question has no ground-truth number to re-grade
    against, and a passing row has nothing withheld to re-grade in the
    first place. `gate_withheld_would_have_passed` re-runs the SAME
    grade_numeric()/grade_comparison() (via _grade_by_type(), shared with
    _grade()'s real verdict) the real verdict would have used.

    `citation_warning_details` is passed straight through from
    `AgentResult.citation_warning_details` (the caller already has it)
    rather than re-derived by calling collect_citation_warnings() a
    second time -- that re-derivation can't see a structured-path
    (quote_not_found/value_not_in_quote/etc.) refusal at all, since those
    only ever come from verify_claims(). Passing the real field through
    keeps analyze_citation_gate.py's false_positive_by_check breakdown
    accurate for both checkers. See
    docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md."""
    if withheld_answer is None or q["type"] not in ("numeric", "comparison"):
        return _empty_citation_gate_evidence()

    would_pass, would_detail = _grade_by_type(q, withheld_answer, retrieved)

    return {
        "withheld_answer": withheld_answer,
        "gate_withheld_would_have_passed": would_pass,
        "gate_withheld_detail": would_detail,
        "citation_warning_details": citation_warning_details,
    }


def run_eval(
    questions_path: Path,
    ids: list[str] | None = None,
    include_skipped: bool = False,
    backend: str | None = None,
    judge_backend: str | None = None,
) -> list[dict]:
    """`backend=None` resolves to config.DEFAULT_BACKEND, resolved HERE
    rather than via a literal `= DEFAULT_BACKEND` parameter default -- a
    parameter default is bound once at module-import time and would
    silently freeze in whatever DEFAULT_BACKEND was at that moment,
    ignoring any later change (same reasoning as agent.run_agent()'s
    matching fix).

    `judge_backend` then defaults to `backend` itself, so a run answers
    and judges with the same backend unless --judge-backend says
    otherwise."""
    backend = backend or DEFAULT_BACKEND
    judge_backend = judge_backend or backend
    questions = load_questions(questions_path)
    questions = _select_questions(questions, ids, include_skipped)
    results = []

    for q in questions:
        print(f"[{q['id']}] {q['question']}")
        try:
            result = run_agent(q["question"], backend=backend)
            answer_text, retrieved, citation_warnings = result.answer, result.results, result.citation_warnings
            # Excludes hard-gated refusals: agent.py's _format_refusal_message()
            # echoes each warning's own "[n] claims ..." text verbatim, which
            # still matches CITATION_PATTERN, so a refusal would otherwise get
            # has_citation=True -- a real answer's citation and a refusal's
            # description of a FAILED citation shouldn't count the same way in
            # this stat.
            has_citation = not citation_warnings and bool(CITATION_PATTERN.search(answer_text))

            passed, detail = _grade(q, answer_text, citation_warnings, retrieved, judge_backend)
            gate_fields = _citation_gate_evidence(
                q, retrieved, result.withheld_answer, result.citation_warning_details
            )
        except Exception as e:
            # Broad on purpose: a network error, exhausted retries, or an
            # unexpected bug in run_agent()/_grade() should all fail just
            # THIS question the same way, not silently discard every
            # already-graded result in the batch before it (no partial
            # report, no flush) -- this is a boundary where many
            # different failure types should all degrade identically.
            # See docs/decisions/2026-09-06-full-codebase-review.md.
            print(f"  -> ERROR: {type(e).__name__}: {e}")
            results.append(
                {
                    "id": q["id"],
                    "ticker": q.get("ticker") or q.get("tickers"),
                    "question": q["question"],
                    "type": q["type"],
                    "passed": False,
                    "detail": f"{type(e).__name__}: {e}",
                    "has_citation": False,
                    "citation_warnings": [],
                    "answer": None,
                    "n_chunks_retrieved": 0,
                    **_empty_citation_gate_evidence(),
                }
            )
            continue

        status = "PASS" if passed else "FAIL"
        print(f"  -> {status} ({detail})")
        if not has_citation:
            print("  -> WARNING: answer has no [n] citation marker at all")
        for w in citation_warnings:
            print(f"  -> CITATION WARNING: {w}")

        results.append(
            {
                "id": q["id"],
                "ticker": q.get("ticker") or q.get("tickers"),
                "question": q["question"],
                "type": q["type"],
                "passed": passed,
                "detail": detail,
                "has_citation": has_citation,
                "citation_warnings": citation_warnings,
                "answer": answer_text,
                "n_chunks_retrieved": len(retrieved),
                **gate_fields,
            }
        )

    flush()
    return results


def print_summary(results: list[dict]) -> None:
    total = len(results)
    passed = sum(r["passed"] for r in results)
    cited = sum(r["has_citation"] for r in results)
    unverified = sum(bool(r["citation_warnings"]) for r in results)

    print(f"\n{'=' * 60}")
    print(
        f"Results: {passed}/{total} passed, {cited}/{total} included a citation marker, "
        f"{unverified}/{total} had at least one unverified numeric citation"
    )
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        cite = "" if r["has_citation"] else "  [no citation]"
        unverified_flag = "  [unverified citation]" if r["citation_warnings"] else ""
        print(f"  [{mark}] {r['id']} ({r['type']}){cite}{unverified_flag}")


def _model_name_for(backend: str) -> str:
    # Gemini is the only backend; this stays a function so a new backend
    # adds its model setting here.
    return GEMINI_MODEL_NAME


# ---------------------------------------------------------------------------
# Provenance -- what a report needs to be tied to the exact code and prompt
# version that produced it. Collected before any quota is spent, and never
# allowed to raise: a provenance failure must not cost the eval run.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
# Uncommitted edits to these make a report's git SHA misleading: code,
# prompt text and its snapshot, the company list rendered into the
# prompt, and the questions. `*.py` matches at any depth, so a tests-only
# edit, or a stray untracked script anywhere not gitignored, counts as
# dirty too: the safe side, and the files are named in dirty_files.
PROVENANCE_PATHSPECS = ("*.py", "prompts", "companies.json", "eval/eval_questions.jsonl")
SNAPSHOT_TEST = "tests/test_model_input_snapshot.py::test_model_input_matches_committed_snapshot"
# The check normally takes about 20s; a hang (a locked model cache, a
# stuck import) must not stop the eval from starting.
SNAPSHOT_CHECK_TIMEOUT = 300


class GitError(Exception):
    """A git command exited non-zero."""


def _git(*args: str) -> str:
    # Binary mode plus an explicit UTF-8 decode: text mode would decode
    # with the Windows code page and garble non-ASCII paths.
    result = subprocess.run(["git", *args], capture_output=True, check=False, cwd=REPO_ROOT)
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


def _git_state() -> dict:
    """The HEAD SHA and any uncommitted changes to PROVENANCE_PATHSPECS.
    A failed git call gives git_sha "unknown" or git_dirty None; never
    raises."""
    sha = _try_git("rev-parse", "--short", "HEAD")
    # Untracked files count: a new module that code imports but nobody
    # `git add`ed would otherwise leave the tree looking clean while the
    # SHA can't reproduce the run.
    status = _try_git(
        "--no-optional-locks", "status", "--porcelain", "-z", "--untracked-files=all", "--", *PROVENANCE_PATHSPECS
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
        command, capture_output=True, check=False, cwd=REPO_ROOT, env=env, timeout=SNAPSHOT_CHECK_TIMEOUT
    )
    return run.returncode


def _snapshot_verified() -> bool | None:
    """Whether prompts/model_input_snapshot.json matches what the current
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
        "chroma_dir": CHROMA_DIR,
        **versions,
    }


def _collect_provenance() -> dict:
    """{git_sha, git_dirty, dirty_files, snapshot_verified, config,
    prompts}. Never raises: each part degrades to a marker value."""
    provenance = {**_git_state(), "snapshot_verified": _snapshot_verified(), "config": _run_config()}
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
    compare_prompt_versions leaves the report out of comparisons (plus a
    failed fingerprint), so a run that will be excluded says so when it
    starts."""
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
            "prompts/model_input_snapshot.json isn't verified against the current code "
            f"(snapshot_verified={provenance.get('snapshot_verified')}), so the prompt fingerprint may be wrong"
        )
    if provenance.get("prompts") == "error":
        warnings.append("the prompt fingerprint couldn't be computed")
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
    RESULTS_DIR.mkdir(exist_ok=True)
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
    args = parser.parse_args()
    # Before run_eval, so it records the code as it was when the run
    # started and costs nothing if it fails.
    provenance = _collect_provenance()
    for warning in _provenance_warnings(provenance):
        print(f"WARNING: {warning}")

    ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
    results = run_eval(
        args.questions,
        ids=ids,
        include_skipped=args.include_skipped,
        backend=args.backend,
        judge_backend=args.judge_backend,
    )
    print_summary(results)
    out_path = save_report(results, backend=args.backend, judge_backend=args.judge_backend, provenance=provenance)
    print(f"\nFull report saved to {out_path}")
    # A print, not an import -- analyze_citation_gate.py stays a
    # standalone reader of the report file, not coupled to this module.
    print(f"Citation-gate FP/FN breakdown: python analyze_citation_gate.py {out_path}")


if __name__ == "__main__":
    main()
