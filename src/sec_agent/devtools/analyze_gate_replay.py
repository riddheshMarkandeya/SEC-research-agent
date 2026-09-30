"""
Replays traced agent runs through the current citation gate, offline: no
LLM call and no Gemini quota. Each run's logged tool calls rebuild the
sources it had, through the agent's own dispatch code, and its final
submit_answer is re-gated with agent.submission_warnings(). The model's
decisions are held fixed, so the only thing that can change a verdict is
the code.

Two uses:
  - A code-only gate change (verify_claims, table_grounding, numeric_utils):
    replay on master, then replay the branch with --compare. The output lists
    refusals recovered and new refusals created, graded offline for numeric
    and comparison questions. A recovered answer graded wrong is a true
    positive lost.
  - A pure refactor: --compare must exit 0. Every verdict, warning message
    and tool-result hash (the exact text the model would receive) must match.
    A run that fails to replay with the same error in both reports is listed
    but doesn't count as a difference.

Without --compare, verdicts are compared with the ones logged at run time.
A run whose rebuilt tool outputs differ from its logged ones (a found flag,
a value, a result count) is marked drifted: the corpus or an XBRL fact
changed since, so its verdict is low-confidence. search_filings calls
rejected at validation write no span, so they aren't replayed or hashed;
they added nothing to the run's sources either. A run whose final
answer doesn't come from a submit is skipped: in older traces that's the
prose-checker fallback, in newer ones a no-submission refusal -- either
way there's no submission to re-gate.

XBRL lookups read var/xbrl_cache/ (anchored to the project root, so any
working directory works). A cache miss fetches live SEC data and writes the cache;
new cache files are listed in the summary because newer data can shift a
verdict.

A full replay takes about 18 minutes, almost all of it in the search
rerank. While iterating, replay a slice (--qid, repeatable, or a recent
--since); run the full replay and --compare only as the final check.

Usage:
  python -m sec_agent.devtools.analyze_gate_replay --qid nvda-revenue-fy26 --qid aapl-ai-risk
  python -m sec_agent.devtools.analyze_gate_replay --since 2026-09-19T03:12
  python -m sec_agent.devtools.analyze_gate_replay --out base.json            (on master)
  python -m sec_agent.devtools.analyze_gate_replay --compare base.json        (on the branch)
"""

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sec_agent.agent import agent
from sec_agent import config
from sec_agent.eval import eval_harness
from sec_agent.devtools import trace_query
from sec_agent import tracing
from sec_agent.sources import xbrl_facts

_SEARCH = "search_filings"
_SUBMIT = "submit_answer"
# The span output fields each dispatch body logs (agent._dispatch_*), which
# are what a replayed call is checked against.
_OBSERVED_FIELDS = {
    _SEARCH: ("result_count",),
    "get_financial_fact": ("found", "value"),
    "calculate": ("found", "value"),
    "compare_financial_metric": ("found", "companies"),
}
_LIST_CAP = 20
_PROGRESS_EVERY = 25

# Every record the agent's tracing would have written during a replayed
# call lands here instead of on disk, see install_trace_capture().
_CAPTURED: list[dict] = []


@dataclass
class RunTrace:
    run_id: str
    ts: str
    qid: str
    question: str
    tool_spans: list[dict]
    final_submit: dict
    logged_refused: bool
    logged_checks: dict | None
    logged_result_count: int | None


def _collect_spans(records: list[dict]) -> tuple[dict[str, list[dict]], dict[str, str | None]]:
    """Spans by run, and each refused run's withheld answer (logged on its
    refusal event, not on a span)."""
    by_run: dict[str, list[dict]] = {}
    withheld: dict[str, str | None] = {}
    for r in records:
        if not r.get("run_id"):
            continue
        if "as_type" in r:
            by_run.setdefault(r["run_id"], []).append(r)
        elif r.get("category") == "citation_gate_refused":
            withheld[r["run_id"]] = r.get("withheld_answer")
    return by_run, withheld


def _in_window(ts: str, since: str | None, until: str | None) -> bool:
    return not ((since and ts < since) or (until and ts >= until))


def _final_submit(submits: list[dict], output: dict, withheld: str | None) -> dict | None:
    """The submit the run's final answer came from: the last one whose text
    is the answer it returned (or withheld, when refused). None when no
    submit matches, meaning the run ended on a text answer. A refused run
    logged before refusal events carried the withheld answer has nothing to
    match against, so it falls back to the last submit. A logged
    no_submission check means the run ended on text, whatever the text
    happens to match."""
    if (output.get("citation_checks") or {}).get(agent._NO_SUBMISSION_WARNING.check):
        return None
    final = withheld if output.get("citation_warnings") else output.get("answer")
    if final is None:
        return submits[-1]
    return next((s for s in reversed(submits) if ((s.get("input") or {}).get("answer_text") or "") == final), None)


@dataclass(frozen=True)
class RunFilter:
    since: str | None = None
    until: str | None = None
    qids: list[str] | None = None
    run_ids: set[str] | None = None


def group_runs(records: list[dict], ids: dict, f: RunFilter = RunFilter()) -> tuple[list[RunTrace], dict[str, int]]:
    """One RunTrace per agent run in the window, in file order, plus counts
    of what was left out. A run is an agent run only if it has a run_agent
    span (MCP tool calls are root spans without one). The window and qid
    filters apply to the run_agent span, written when the run ends.

    The logged verdict comes from run_agent's output, not the last submit
    span: when the budget runs out after a retry, the agent re-gates the
    cached submission against more sources than that span saw."""
    counts = {"non_agent_runs": 0, "skipped_no_submit": 0, "skipped_no_output": 0, "skipped_prose_final": 0}
    runs = []
    by_run, withheld = _collect_spans(records)
    for run_id, spans in by_run.items():
        root = next((s for s in spans if s["name"] == "run_agent"), None)
        qid = ids.get(run_id, "?")
        if f.run_ids is not None and run_id not in f.run_ids:
            continue
        if not _in_window((root or spans[0]).get("timestamp", ""), f.since, f.until) or (f.qids and qid not in f.qids):
            continue
        if root is None:
            counts["non_agent_runs"] += 1
            continue
        output = root.get("output")
        if not output:
            counts["skipped_no_output"] += 1
            continue
        submits = [s for s in spans if s["name"] == _SUBMIT]
        if not submits:
            counts["skipped_no_submit"] += 1
            continue
        final_submit = _final_submit(submits, output, withheld.get(run_id))
        if final_submit is None:
            counts["skipped_prose_final"] += 1
            continue
        runs.append(
            RunTrace(
                run_id=run_id,
                ts=root["timestamp"],
                qid=qid,
                question=(root.get("input") or {}).get("question") or "",
                tool_spans=[s for s in spans if s.get("as_type") == "tool" and s["name"] != _SUBMIT],
                final_submit=final_submit,
                logged_refused=bool(output.get("citation_warnings")),
                logged_checks=output.get("citation_checks"),
                logged_result_count=output.get("result_count"),
            )
        )
    return runs, counts


def install_trace_capture() -> None:
    """Routes the agent's tracing into _CAPTURED: a replay must never append
    to the trace log it is reading, or send spans to Langfuse. Patched at
    the module level because traced_span and log_event look both names up
    at call time."""
    tracing.TRACING_ENABLED = False
    tracing._write_local_log = _CAPTURED.append


def _replay_call(name: str, args: dict, question: str, all_results: list[dict], search) -> tuple[str, dict]:
    """The content one call returns to the model, and the output fields its
    span logs. A search span logs the args after resolution, so it goes
    straight to the search step, not back through validation. The other
    tools go through the agent's own router, which only reads
    searched_tickers for searches."""
    _CAPTURED.clear()
    if name == _SEARCH:
        content, count = search(args.get("query") or "", args.get("ticker"), all_results)
        return content, {"result_count": count}
    if name not in _OBSERVED_FIELDS:
        raise ValueError(f"no replay route for tool {name!r}")
    content = agent._dispatch_tool_call({"name": name, "args": args}, question, all_results, set(), False)
    span_output = next((r.get("output") for r in reversed(_CAPTURED) if r.get("name") == name), None) or {}
    return content, {key: span_output.get(key) for key in _OBSERVED_FIELDS[name]}


def rebuild_results(run: RunTrace, search) -> tuple[list[dict], list[dict], str | None]:
    """Replays every tool call in the run, in order, including any after the
    final submit (see group_runs). Returns the rebuilt sources, one record
    per call, and the first error (the replay of that run stops there)."""
    all_results: list[dict] = []
    calls: list[dict] = []
    for span in run.tool_spans:
        name = span["name"]
        try:
            content, observed = _replay_call(name, span.get("input") or {}, run.question, all_results, search)
        except Exception as e:
            # Deliberately broad: a historical record can fail in ways today's
            # code never sees live (an old arg shape, a missing cache file),
            # and one bad run must not abort a replay of hundreds.
            return all_results, calls, f"{name}: {type(e).__name__}: {e}"
        logged = span.get("output") or {}
        calls.append(
            {
                "tool": name,
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "observed": observed,
                "logged": {key: logged.get(key) for key in _OBSERVED_FIELDS[name]},
            }
        )
    return all_results, calls, None


def fidelity(calls: list[dict], logged_result_count: int | None, rebuilt_count: int) -> list[str]:
    """Where the rebuilt sources differ from what the run saw live."""
    drift = [
        f"call {i} {c['tool']}: logged {c['logged']}, replayed {c['observed']}"
        for i, c in enumerate(calls, start=1)
        if c["observed"] != c["logged"]
    ]
    if logged_result_count is not None and logged_result_count != rebuilt_count:
        drift.append(f"result_count: logged {logged_result_count}, replayed {rebuilt_count}")
    return drift


def grade(q: dict | None, answer_text: str, all_results: list[dict]) -> bool | None:
    """The eval grader's verdict on the submitted text as if the gate let it
    through. None for judged or unknown questions, which need an LLM judge."""
    if q is None or q.get("type") not in ("numeric", "comparison"):
        return None
    return eval_harness._grade_by_type(q, answer_text, all_results)[0]


def replay_run(run: RunTrace, search, questions: dict[str, dict]) -> dict:
    all_results, calls, error = rebuild_results(run, search)
    record = {
        "run_id": run.run_id,
        "ts": run.ts,
        "qid": run.qid,
        "logged_refused": run.logged_refused,
        "logged_checks": run.logged_checks,
        "now_refused": None,
        "now_checks": None,
        "now_messages": None,
        "correct": None,
        "drift": fidelity(calls, run.logged_result_count, len(all_results)),
        "replay_error": error,
        "calls": calls,
    }
    if error is not None:
        return record
    answer_text, warnings = agent.submission_warnings(run.final_submit.get("input") or {}, all_results, run.question)
    record.update(
        now_refused=bool(warnings),
        now_checks=agent._count_citation_checks(warnings),
        now_messages=[w.message for w in warnings],
        correct=grade(questions.get(run.qid), answer_text, all_results),
    )
    return record


def _label(record: dict) -> str:
    return f"{record['qid']} ({record['run_id']})"


def _grade_key(correct: bool | None) -> str:
    return {True: "correct", False: "wrong", None: "ungraded"}[correct]


def _new_summary() -> dict:
    return {
        "replayed": 0,
        "refused_then": 0,
        "refused_now": 0,
        "recovered": {"correct": [], "wrong": [], "ungraded": []},
        "newly_refused": {"correct": [], "wrong": [], "ungraded": []},
        "check_changes": [],
        "drifted": [],
        "drifted_changes": [],
        "errored": [],
        "errored_unchanged": [],
        "tool_drift": [],
        "only_in_base": [],
        "only_in_candidate": [],
    }


def _tally_against_base(record: dict, base: dict | None, s: dict) -> None:
    """Adds one record's differences from its baseline replay to the
    buckets: a missing baseline run, changed tool results, errors, then the
    verdict itself."""
    label = _label(record)
    if base is None:
        s["only_in_candidate"].append(label)
        return
    if [c["content_sha256"] for c in base["calls"]] != [c["content_sha256"] for c in record["calls"]]:
        s["tool_drift"].append(label)
    if record["replay_error"] is not None or base["replay_error"] is not None:
        same = record["replay_error"] == base["replay_error"]
        s["errored_unchanged" if same else "errored"].append(label)
        return
    then = (base["now_refused"], base["now_checks"], base["now_messages"])
    _tally(record, then, s, against_logged=False)


def _tally(record: dict, then: tuple[bool, dict | None, list[str] | None], s: dict, *, against_logged: bool) -> None:
    """Adds one record's verdict change to the buckets. `then` is the
    refusal, check counts and messages compared against; a None part isn't
    compared. Against the logged verdict, a change on a drifted run goes to
    its own bucket: the run's sources changed, so the change can't be
    pinned on the code. Against a baseline, both sides rebuilt the same
    sources, so it counts normally."""
    then_refused, then_checks, then_messages = then
    now_refused = record["now_refused"]
    label = _label(record)
    s["replayed"] += 1
    s["refused_then"] += then_refused
    s["refused_now"] += now_refused
    if record["drift"]:
        s["drifted"].append(label)
    changed = (
        then_refused != now_refused
        or (then_refused and then_checks is not None and then_checks != record["now_checks"])
        or (then_messages is not None and then_messages != record["now_messages"])
    )
    if not changed:
        return
    if against_logged and record["drift"]:
        s["drifted_changes"].append(label)
    elif then_refused and not now_refused:
        s["recovered"][_grade_key(record["correct"])].append(label)
    elif now_refused and not then_refused:
        s["newly_refused"][_grade_key(record["correct"])].append(label)
    else:
        s["check_changes"].append(label)


def summarize(records: list[dict], base: list[dict] | None = None) -> dict:
    """Verdict changes of `records` against their logged verdicts, or
    against a baseline replay of the same runs when `base` is given."""
    s = _new_summary()
    base_by_id = {r["run_id"]: r for r in base} if base is not None else None
    for record in records:
        if base_by_id is not None:
            _tally_against_base(record, base_by_id.get(record["run_id"]), s)
        elif record["replay_error"] is not None:
            s["errored"].append(_label(record))
        else:
            _tally(record, (record["logged_refused"], record["logged_checks"], None), s, against_logged=True)
    if base is not None:
        seen = {r["run_id"] for r in records}
        s["only_in_base"] = [_label(r) for r in base if r["run_id"] not in seen]
    return s


def compare_failed(s: dict) -> bool:
    """True when anything differs: any flip, check or message change, hash
    drift, new or changed error, or unmatched run."""
    flips = [*s["recovered"].values(), *s["newly_refused"].values()]
    others = [s["check_changes"], s["errored"], s["tool_drift"], s["only_in_base"], s["only_in_candidate"]]
    return any(flips) or any(others)


def _listed(title: str, labels: list[str]) -> list[str]:
    if not labels:
        return []
    shown = ", ".join(labels[:_LIST_CAP])
    more = f" (+{len(labels) - _LIST_CAP} more)" if len(labels) > _LIST_CAP else ""
    return [f"  {title}: {shown}{more}"]


def _bucket_line(title: str, bucket: dict) -> list[str]:
    total = sum(len(v) for v in bucket.values())
    lines = [
        f"{title}: {total} ({len(bucket['correct'])} correct, {len(bucket['wrong'])} wrong, "
        f"{len(bucket['ungraded'])} ungraded)"
    ]
    for key in ("correct", "wrong", "ungraded"):
        lines += _listed(key, bucket[key])
    return lines


def format_summary(s: dict, counts: dict) -> str:
    lines = [
        f"Replayed: {s['replayed']} runs (errored {len(s['errored'])}, drifted {len(s['drifted'])}; "
        f"skipped: non-agent {counts['non_agent_runs']}, no submit {counts['skipped_no_submit']}, "
        f"no output {counts['skipped_no_output']}, prose final {counts['skipped_prose_final']})",
        f"Refused: {s['refused_then']} then, {s['refused_now']} now",
        *_bucket_line("Recovered (refused -> passed)", s["recovered"]),
        *_bucket_line("Newly refused (passed -> refused)", s["newly_refused"]),
        f"Check changes (same outcome, different checks or messages): {len(s['check_changes'])}",
        *_listed("runs", s["check_changes"]),
        f"Tool-result drift: {len(s['tool_drift'])}",
        *_listed("runs", s["tool_drift"]),
        *_listed("Only in baseline", s["only_in_base"]),
        *_listed("Only in this replay", s["only_in_candidate"]),
        *_listed("Errored", s["errored"]),
        *_listed("Errored the same way in both", s["errored_unchanged"]),
        f"Verdict changes on drifted runs (sources changed since the run, not attributable): "
        f"{len(s['drifted_changes'])}",
        *_listed("runs", s["drifted_changes"]),
        *_listed("Drifted (low-confidence verdicts)", s["drifted"]),
    ]
    if counts.get("new_cache_files"):
        lines.append(f"New xbrl_cache files (live SEC fetches): {len(counts['new_cache_files'])}")
    return "\n".join(lines)


def memoized(search_fn):
    """hybrid_search, cached per (query, ticker, top_k) for one replay. The
    cross-encoder rerank dominates replay time, and many runs repeat the
    same search (the question verbatim). Returns copies, since callers own
    and extend what they get back."""
    cache: dict[tuple, list[dict]] = {}

    def cached(query, ticker=None, top_k=agent.CHUNKS_PER_SEARCH):
        key = (query, ticker, top_k)
        if key not in cache:
            cache[key] = search_fn(query, ticker=ticker, top_k=top_k)
        return copy.deepcopy(cache[key])

    return cached


def install_live_search():  # pragma: no cover - binds the real Chroma search
    agent.hybrid_search = memoized(agent.hybrid_search)
    return agent.run_search


def cache_listing() -> set[str]:
    cache_dir = xbrl_facts.CACHE_DIR
    return {p.name for p in cache_dir.iterdir()} if cache_dir.is_dir() else set()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=Path(config.TRACE_LOG_PATH))
    parser.add_argument("--questions", type=Path, default=config.QUESTIONS_PATH)
    parser.add_argument("--since", type=trace_query._iso_prefix, help="ISO UTC prefix, inclusive")
    parser.add_argument("--until", type=trace_query._iso_prefix, help="ISO UTC prefix, exclusive")
    parser.add_argument("--qid", action="append", help="eval question ID (repeatable)")
    parser.add_argument("--out", type=Path, help="report path (default: var/trace_logs/replay-<UTC time>.json)")
    parser.add_argument(
        "--compare",
        type=Path,
        help="a baseline report; replays exactly its runs and exits 1 on any difference",
    )
    return parser


def _select_runs(args, records: list[dict], ids: dict, base: dict | None):
    if base is None:
        return group_runs(records, ids, RunFilter(since=args.since, until=args.until, qids=args.qid))
    return group_runs(records, ids, RunFilter(run_ids={r["run_id"] for r in base["runs"]}))


def _replay_all(runs: list[RunTrace], questions: dict[str, dict]) -> list[dict]:
    search = install_live_search()
    records = []
    for i, run in enumerate(runs, start=1):
        records.append(replay_run(run, search, questions))
        if i % _PROGRESS_EVERY == 0:
            print(f"[replay] {i}/{len(runs)}", file=sys.stderr)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.compare and (args.since or args.until or args.qid):
        parser.error("--compare replays the baseline's runs; drop --since/--until/--qid")
    stamp = datetime.now(timezone.utc)
    out = args.out or Path(config.TRACE_LOG_PATH).parent / f"replay-{stamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    # Checked up front: a full replay takes many minutes, and its results
    # would be lost if the write failed at the end.
    if not out.parent.is_dir():
        parser.error(f"--out directory does not exist: {out.parent}")
    base = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    records, malformed = trace_query.load(args.file)
    ids = trace_query.question_ids(records, args.questions)
    questions = {q["id"]: q for q in eval_harness.load_questions(args.questions)}
    runs, counts = _select_runs(args, records, ids, base)

    install_trace_capture()
    cache_before = cache_listing()
    replayed = _replay_all(runs, questions)
    report_counts = {**counts, "new_cache_files": sorted(cache_listing() - cache_before), "malformed_lines": malformed}

    summary = summarize(replayed, base["runs"] if base else None)
    header = {
        "created": stamp.isoformat(),
        "git_sha": eval_harness._try_git("rev-parse", "HEAD"),
        "trace_file": str(args.file),
        "since": args.since,
        "until": args.until,
        "qids": args.qid,
        "baseline": str(args.compare) if args.compare else None,
    }
    report = {"header": header, "counts": report_counts, "runs": replayed}
    print(format_summary(summary, report_counts))
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"Wrote {out}")
    return 1 if base is not None and compare_failed(summary) else 0


if __name__ == "__main__":
    sys.exit(main())
