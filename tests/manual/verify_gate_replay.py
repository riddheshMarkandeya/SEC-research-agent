"""
Live verification of analyze_gate_replay.py's rebuild step, the part unit
tests can't cover: replaying real traced runs against the real Chroma
index and XBRL cache. Informational, not an assert-and-exit gate.

For each named run it prints the verdict then and now, whether the rebuilt
tool outputs match the logged ones (drift), and any replay error. It
includes a budget-exhausted run (tool calls after its last submit), the
shape whose logged verdict has to come from run_agent rather than the
submit span. It also lists xbrl_cache/ files the replay created, which
would mean a live SEC fetch.

Usage (from the repo root):
    python tests/manual/verify_gate_replay.py
    python tests/manual/verify_gate_replay.py <run_id> [<run_id> ...]
"""

import sys
from pathlib import Path

from sec_agent import config
from sec_agent.eval import eval_harness
from tools import analyze_gate_replay as replay
from tools import trace_query

# da3be66608ff: budget exhausted after a retry, tool spans after the last
# submit. 981513aa83f1: a recent clean pass with search, fact and calculate.
DEFAULT_RUN_IDS = ["da3be66608ff", "981513aa83f1"]
QUESTIONS = config.QUESTIONS_PATH


def main() -> None:
    run_ids = set(sys.argv[1:] or DEFAULT_RUN_IDS)
    records, _ = trace_query.load(Path(config.TRACE_LOG_PATH))
    ids = trace_query.question_ids(records, QUESTIONS)
    questions = {q["id"]: q for q in eval_harness.load_questions(QUESTIONS)}
    runs, _ = replay.group_runs(records, ids, replay.RunFilter(run_ids=run_ids))
    missing = run_ids - {r.run_id for r in runs}
    if missing:
        print(f"not found as agent runs with a submit: {sorted(missing)}")

    replay.install_trace_capture()
    search = replay.install_live_search()
    cache_before = replay.cache_listing()
    for run in runs:
        record = replay.replay_run(run, search, questions)
        print(f"\n{run.run_id} {run.qid} ({len(run.tool_spans)} tool calls)")
        print(f"  refused then: {record['logged_refused']} {record['logged_checks']}")
        print(f"  refused now:  {record['now_refused']} {record['now_checks']}")
        print(f"  correct: {record['correct']}  error: {record['replay_error']}")
        for line in record["drift"] or ["no drift"]:
            print(f"  {line}")
    print(f"\nnew xbrl_cache files: {sorted(replay.cache_listing() - cache_before)}")


if __name__ == "__main__":
    main()
