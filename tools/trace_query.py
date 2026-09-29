"""
Query trace_logs/traces.jsonl: filter records, pick fields, count, or list
each run's tool sequence, with capped output.

Records come in two shapes. A span (tracing.traced_span) has `as_type` and
`name`: a tool call (`name` is the tool, `input` the raw args the model
sent), `run_agent` (`input.question`), or `unmet_metric_request`. An event
(tracing.log_event) has `category` instead: `tool_call_rejected`,
`tool_arg_coerced`, `llm_retry`, `citation_gate_refused` and so on. The
`--kind` filter takes either a span name or an event category.

The subcommand comes first. Every command prints at most --limit result
lines (default 50), then a total line saying what was cut.

Examples:
  python trace_query.py counts --since 2026-09-26T08:53 --until 2026-09-26T09:04
  python trace_query.py counts --kind tool_call_rejected --by qid,reason --since 2026-09-26
  python trace_query.py records --kind unmet_metric_request --fields timestamp,qid,input.metric
  python trace_query.py runs --qid nvda-rd-expense-q4fy26-refusal --since 2026-09-26T08:53
"""

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sec_agent import config


def kind(record: dict) -> str:
    """A span's name, or an event's category."""
    return record["name"] if "as_type" in record else record.get("category", "?")


def get(record: dict, key: str):
    """A field by name: top-level first, then under `input` (span args),
    then under `args` (a rejection event's args), so one key finds the
    same field in every record shape. A dotted key is a path from the top.
    None when absent."""
    if "." in key:
        value = record
        for part in key.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value
    for container in (record, record.get("input"), record.get("args")):
        if isinstance(container, dict) and key in container:
            return container[key]
    return None


def load(path: Path) -> tuple[list[dict], int]:
    """Every record in the file, and how many non-blank lines weren't a
    JSON object (a crash mid-write can leave one)."""
    records, malformed = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(record, dict):
                records.append(record)
            else:
                malformed += 1
    return records, malformed


def question_ids(records: list[dict], questions_path: Path) -> dict:
    """run_id -> eval question ID, from each run's `run_agent` span
    ("?" when its question isn't in the suite). Built from every record,
    not a time-filtered subset: the root span is written when the run
    ends, so a run crossing a window edge would otherwise lose its ID."""
    with open(questions_path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    by_text = {str(q.get("question", "")).strip(): q.get("id", "?") for q in rows if isinstance(q, dict)}
    ids = {}
    for r in records:
        if r.get("name") == "run_agent" and "as_type" in r:
            question = get(r, "input.question")
            ids[r.get("run_id")] = by_text.get(str(question or "").strip(), "?")
    return ids


def field(record: dict, key: str, ids: dict):
    """`get`, plus two computed fields: `qid` (the run's eval question
    ID, "?" when unknown) and `kind`."""
    if key == "qid":
        return ids.get(record.get("run_id"), "?")
    if key == "kind":
        return kind(record)
    return get(record, key)


@dataclass(frozen=True)
class Filters:
    """Every filter is optional and they are ANDed. since/until are ISO
    prefixes compared as strings (every timestamp is UTC in one format),
    since inclusive, until exclusive. Each `where` is a (key, value) pair,
    compared as str() so 2025 and "2025" both match "2025" (and "None"
    matches an absent field as well as a null one)."""

    since: str | None = None
    until: str | None = None
    runs: list[str] | None = None
    qids: list[str] | None = None
    kinds: list[str] | None = None
    where: list[tuple[str, str]] | None = None


def _matches(r: dict, ids: dict, f: Filters) -> bool:
    ts = r.get("timestamp", "")
    return not (
        (f.since and ts < f.since)
        or (f.until and ts >= f.until)
        or (f.runs and r.get("run_id") not in f.runs)
        or (f.qids and field(r, "qid", ids) not in f.qids)
        or (f.kinds and kind(r) not in f.kinds)
        or any(str(field(r, key, ids)) != value for key, value in f.where or [])
    )


def select(records: list[dict], ids: dict, filters: Filters) -> list[dict]:
    """The records matching `filters`, in file order."""
    return [r for r in records if _matches(r, ids, filters)]


def _clip(value, max_chars: int):
    """The value itself, or its JSON cut to max_chars plus "..." when longer."""
    text = json.dumps(value, ensure_ascii=True, default=str)
    return value if len(text) <= max_chars else text[:max_chars] + "..."


def record_lines(
    records: list[dict], ids: dict, fields: list[str] | None = None, max_chars: int = 200, limit: int = 50
) -> list[str]:
    """One ASCII JSON line per record (the chosen fields, or the whole
    record plus its qid), at most `limit` lines, then a total line."""
    lines = []
    for r in records[:limit]:
        picked = {key: field(r, key, ids) for key in fields} if fields else {"qid": field(r, "qid", ids), **r}
        lines.append(json.dumps({k: _clip(v, max_chars) for k, v in picked.items()}, ensure_ascii=True, default=str))
    lines.append(f"-- {len(lines)} of {len(records)} records")
    return lines


def _safe(text: str) -> str:
    """The text with every non-printable or non-ASCII character escaped,
    so model-written strings can't send terminal control sequences."""
    return "".join(c if c.isascii() and c.isprintable() else ascii(c)[1:-1] for c in text)


def count_lines(records: list[dict], ids: dict, by: list[str], limit: int = 50) -> list[str]:
    """Record counts grouped by the `by` fields, most common first, at most
    `limit` groups, then how many groups were shown and the record total."""
    counts = Counter(tuple(str(field(r, key, ids)) for key in by) for r in records)
    lines = [_safe(f"{n}  {' | '.join(group)}") for group, n in counts.most_common(limit)]
    return [*lines, f"-- {len(lines)} of {len(counts)} groups, {len(records)} records"]


# Arguments shown in a run's tool sequence: which company and metric, then
# the period (with short labels), then the yoy flag.
_NAME_ARGS = ("ticker", "anchor_ticker", "metric")
_PERIOD_ARGS = {
    "fiscal_year": "fy",
    "fiscal_period": "fp",
    "period_end_date": "end",
    "start_fiscal_year": "start",
    "end_fiscal_year": "stop",
}


def _step(span: dict) -> str:
    """One tool call: its name, its company/metric, its period args
    (ascii(), so '2025' and 2025 differ), `yoy` when set, then [nodata]
    for a fact lookup that found nothing and [err] for a call that raised."""
    args = span.get("input")
    if not isinstance(args, dict):
        args = {}
    shown = [str(args[key]) for key in _NAME_ARGS if key in args]
    shown += [f"{label}={ascii(args[key])}" for key, label in _PERIOD_ARGS.items() if key in args]
    if args.get("yoy_growth"):
        shown.append("yoy")
    step = span["name"] + (f"({','.join(shown)})" if shown else "")
    output = span.get("output")
    if isinstance(output, dict) and output.get("found") is False:
        step += "[nodata]"
    if span.get("error"):
        step += "[err]"
    return step


def run_lines(records: list[dict], ids: dict, limit: int = 50) -> list[str]:
    """One line per run, at most `limit`, then a total line. Runs are
    ordered by their first record, whose MM-DDTHH:MM:SS the line starts
    with (spans are stamped when they close, so this is when the first
    call finished, not when the run began). Then run_id, qid, the tool
    calls in time order, and a count of the run's other records (events
    and unmet-metric spans). Events logged outside any run are grouped
    under "(no run)"."""
    by_run: dict = {}
    for r in records:
        by_run.setdefault(r.get("run_id"), []).append(r)
    ordered = sorted(by_run.items(), key=lambda item: min(r.get("timestamp", "") for r in item[1]))
    lines = []
    for run_id, rs in ordered[:limit]:
        rs = sorted(rs, key=lambda r: r.get("timestamp", ""))
        steps = [_step(r) for r in rs if r.get("as_type") == "tool"]
        others = Counter(kind(r) for r in rs if r.get("as_type") not in ("tool", "agent"))
        parts = [" > ".join(steps)] if steps else []
        if others:
            parts.append("[+" + ", ".join(f"{k} x{n}" for k, n in sorted(others.items())) + "]")
        head = f"{rs[0].get('timestamp', '')[5:19]} {run_id or '(no run)'} {ids.get(run_id, '?')}:"
        lines.append(_safe(" ".join([head, *parts])))
    return [*lines, f"-- {len(lines)} of {len(ordered)} runs"]


# The trace timestamps' own format, cut anywhere after the year: a prefix
# in another form ("2026-09-26 08:53", a trailing "Z") would compare
# wrongly as a string and silently select the wrong window.
_ISO_PREFIX = re.compile(r"\d{4}(-\d{2}(-\d{2}(T\d{2}(:\d{2}(:\d{2}(\.\d{1,6})?)?)?)?)?)?")


def _iso_prefix(text: str) -> str:
    if not _ISO_PREFIX.fullmatch(text):
        raise argparse.ArgumentTypeError(f"expected an ISO UTC prefix like 2026-09-26T08:53, got {text!r}")
    return text


def _where(text: str) -> tuple[str, str]:
    key, sep, value = text.partition("=")
    if not sep:
        raise argparse.ArgumentTypeError(f"expected key=value, got {text!r}")
    return key.strip(), value.strip()


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected a positive number, got {text}")
    return value


def _names(text: str) -> list[str]:
    return [name.strip() for name in text.split(",") if name.strip()]


def _parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--file", type=Path, default=Path(config.TRACE_LOG_PATH))
    common.add_argument("--questions", type=Path, default=config.PROJECT_ROOT / "eval" / "eval_questions.jsonl")
    common.add_argument("--since", type=_iso_prefix, help="ISO UTC prefix, inclusive (e.g. 2026-09-26T08:53)")
    common.add_argument("--until", type=_iso_prefix, help="ISO UTC prefix, exclusive")
    common.add_argument("--run", action="append", help="run_id (repeatable)")
    common.add_argument("--qid", action="append", help="eval question ID (repeatable)")
    common.add_argument("--kind", action="append", help="span name or event category (repeatable)")
    common.add_argument("--where", action="append", type=_where, help="key=value on any field (repeatable)")
    common.add_argument("--limit", type=_positive, default=50, help="most lines to print (default 50)")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    records = commands.add_parser("records", parents=[common], help="matching records as JSON lines")
    records.add_argument("--fields", type=_names, help="comma-separated fields, e.g. timestamp,qid,input.metric")
    records.add_argument("--max-chars", type=_positive, default=200, help="truncate each value's JSON to this")
    counts = commands.add_parser("counts", parents=[common], help="counts grouped by fields")
    counts.add_argument("--by", type=_names, default=["kind"], help="comma-separated fields (default: kind)")
    commands.add_parser("runs", parents=[common], help="one line per run: its tool sequence")
    return parser


def _read_questions(records: list[dict], questions_path: Path) -> dict:
    """question_ids, or an empty map (every qid "?") with a warning when
    the questions file can't be read: the other fields are still useful."""
    try:
        return question_ids(records, questions_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"trace_query: cannot read {questions_path} ({e}); every qid shows as ?", file=sys.stderr)
        return {}


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        records, malformed = load(args.file)
    except (OSError, UnicodeDecodeError) as e:
        print(f"trace_query: cannot read {args.file} ({e})", file=sys.stderr)
        raise SystemExit(1) from e
    ids = _read_questions(records, args.questions)
    picked = select(records, ids, Filters(args.since, args.until, args.run, args.qid, args.kind, args.where))
    if args.command == "records":
        lines = record_lines(picked, ids, args.fields, args.max_chars, args.limit)
    elif args.command == "counts":
        lines = count_lines(picked, ids, args.by, args.limit)
    else:
        lines = run_lines(picked, ids, args.limit)
    print("\n".join(lines))
    if malformed:
        print(f"trace_query: skipped {malformed} malformed line(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
