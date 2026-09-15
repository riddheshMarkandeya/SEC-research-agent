"""
Unit tests for scripts/check_docs_sync.py — the PreToolUse hook that
blocks a `git commit` staging a new docs/decisions/ file without
PROJECT_INDEX.md. `is_commit_command`/`new_decisions_missing_index` are
pure and get full TDD; `main()`'s stdin/subprocess glue is exercised here
too via monkeypatched stdin and a stubbed `_staged_files`, rather than
relying only on a live git repo, so the exit-code paths are covered by
something other than the one-off manual hook trigger test recorded in
docs/decisions/2026-09-15-claude-md-restructure.md.
"""

import io
import json

import pytest

from scripts import check_docs_sync
from scripts.check_docs_sync import is_commit_command, new_decisions_missing_index


def test_is_commit_command_true_for_plain_commit():
    assert is_commit_command("git commit -m 'msg'")


def test_is_commit_command_true_for_chained_add_and_commit():
    assert is_commit_command("git add -A && git commit -m 'msg'")


def test_is_commit_command_false_for_other_git_subcommands():
    assert not is_commit_command("git status")
    assert not is_commit_command("git log --oneline")
    assert not is_commit_command("git diff --cached --name-only")


def test_is_commit_command_false_when_text_only_mentions_commit():
    # Regression: a naive substring search on "git commit" false-positives
    # on a command that merely contains that text as data (e.g. an echoed
    # JSON payload), rather than actually invoking it as a command. Found
    # live during this hook's own manual trigger test, which had
    # mislabeled the false block as a successful validation.
    command = 'echo \'{"tool_input": {"command": "git commit -m x"}}\''
    assert not is_commit_command(command)


def test_new_decisions_missing_index_flags_unaccompanied_decision_file():
    staged = ["docs/decisions/2026-09-15-x.md"]
    assert new_decisions_missing_index(staged) == staged


def test_new_decisions_missing_index_clears_when_index_staged_too():
    staged = ["docs/decisions/2026-09-15-x.md", "PROJECT_INDEX.md"]
    assert new_decisions_missing_index(staged) == []


def test_new_decisions_missing_index_ignores_template():
    assert new_decisions_missing_index(["docs/decisions/TEMPLATE.md"]) == []


def test_new_decisions_missing_index_ignores_other_directories():
    assert new_decisions_missing_index(["docs/reviews/2026-09-15-x.md"]) == []


def test_new_decisions_missing_index_handles_no_staged_files():
    assert new_decisions_missing_index([]) == []


# ---------------------------------------------------------------------------
# main() -- stdin/subprocess glue, exercised with a monkeypatched stdin and
# a stubbed _staged_files rather than a real git repo.
# ---------------------------------------------------------------------------


def _run_main(monkeypatch, payload, staged_files=()):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(check_docs_sync, "_staged_files", lambda: list(staged_files))
    return check_docs_sync.main()


def test_main_allows_non_bash_tool(monkeypatch):
    assert _run_main(monkeypatch, {"tool_name": "Read", "tool_input": {}}) == 0


def test_main_allows_malformed_json(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert check_docs_sync.main() == 0


def test_main_allows_null_tool_input(monkeypatch):
    # Regression: payload.get("tool_input", {}) only falls back to {} when
    # the key is *absent* -- an explicit `"tool_input": null` used to raise
    # AttributeError on the subsequent .get("command", "").
    assert _run_main(monkeypatch, {"tool_name": "Bash", "tool_input": None}) == 0


def test_main_allows_non_commit_bash_command(monkeypatch):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
    assert _run_main(monkeypatch, payload) == 0


def test_main_blocks_commit_missing_index(monkeypatch, capsys):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}
    exit_code = _run_main(monkeypatch, payload, staged_files=["docs/decisions/2026-09-15-x.md"])
    assert exit_code == 2
    assert "PROJECT_INDEX.md" in capsys.readouterr().err


def test_main_allows_commit_with_index_staged(monkeypatch):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}
    staged = ["docs/decisions/2026-09-15-x.md", "PROJECT_INDEX.md"]
    assert _run_main(monkeypatch, payload, staged_files=staged) == 0


def test_main_does_not_false_positive_on_embedded_commit_text(monkeypatch):
    # Full-pipeline regression for the same bug as
    # test_is_commit_command_false_when_text_only_mentions_commit: even
    # with a real mismatch staged, a command that only *mentions* "git
    # commit" as text must not be blocked.
    command = 'echo \'{"tool_input": {"command": "git commit -m x"}}\''
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    assert _run_main(monkeypatch, payload, staged_files=["docs/decisions/2026-09-15-x.md"]) == 0


@pytest.mark.parametrize("missing_key", ["tool_name", "tool_input"])
def test_main_allows_payload_missing_keys(monkeypatch, missing_key):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}
    del payload[missing_key]
    assert _run_main(monkeypatch, payload, staged_files=["docs/decisions/2026-09-15-x.md"]) == 0
