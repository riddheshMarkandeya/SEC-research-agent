"""
Unit tests for scripts/check_docs_health.py, the pre-commit check that every
docs file has an index entry and every entry has a file. The pure functions
are tested directly. `main()` runs against real throwaway git repos in
tmp_path: real git is local and deterministic, and a stub would hide exactly
the staged-tree and decoding behavior this script depends on.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_docs_health
from scripts.check_docs_health import (
    blocking_message,
    dangling_entries,
    recent_cap_warning,
    recent_entry_count,
    unindexed_docs,
)

SCRIPT_PATH = Path(check_docs_health.__file__).resolve()


# unindexed_docs


def test_unindexed_docs_passes_file_indexed_by_backticked_path():
    index = "- 2026-09-23 [plan] x → `docs/plans/2026-09-23-x.md`"
    assert unindexed_docs(["docs/plans/2026-09-23-x.md"], [index]) == []


def test_unindexed_docs_flags_file_missing_from_index():
    assert unindexed_docs(["docs/plans/2026-09-23-x.md"], ["nothing here"]) == [
        "docs/plans/2026-09-23-x.md"
    ]


def test_unindexed_docs_skips_template():
    assert unindexed_docs(["docs/plans/TEMPLATE.md"], [""]) == []


def test_unindexed_docs_accepts_entry_found_only_in_archive():
    archive = "- 2026-08-01 [decision] y → `docs/decisions/2026-08-01-y.md`"
    assert unindexed_docs(["docs/decisions/2026-08-01-y.md"], ["", archive]) == []


@pytest.mark.parametrize("mention", ["docs/plans/2026-09-23-x.md", "`docs/plans/2026-09-23-x.md`"])
def test_unindexed_docs_flags_path_mentioned_only_in_prose(mention):
    # Only the backticked path after an entry's trailing `→` is that entry's own.
    index = f"- 2026-09-23 [decision] amends {mention} → `docs/decisions/z.md`"
    assert unindexed_docs(["docs/plans/2026-09-23-x.md"], [index]) == [
        "docs/plans/2026-09-23-x.md"
    ]


def test_unindexed_docs_ignores_arrow_in_prose_line():
    # Only a top-level `- ` bullet is an entry; wrapped prose can end in an arrow too.
    index = "the `a.py` → `docs/plans/x.md`\n  - nested → `docs/plans/x.md`"
    assert unindexed_docs(["docs/plans/x.md"], [index]) == ["docs/plans/x.md"]


def test_unindexed_docs_ignores_non_docs_and_nested_files():
    paths = ["README.md", "docs/plans/notes.txt", "docs/plans/sub/x.md", "docs/other/y.md"]
    assert unindexed_docs(paths, [""]) == []


def test_unindexed_docs_returns_sorted():
    result = unindexed_docs(["docs/plans/b.md", "docs/decisions/a.md"], [""])
    assert result == ["docs/decisions/a.md", "docs/plans/b.md"]


# dangling_entries


def test_dangling_entries_flags_entry_without_file():
    index = "- 2026-09-23 [plan] gone → `docs/plans/gone.md`"
    assert dangling_entries([], [index]) == ["docs/plans/gone.md"]


def test_dangling_entries_flags_archive_entry_without_file():
    archive = "- 2026-08-01 [plan] old → `docs/plans/old.md`"
    assert dangling_entries([], ["", archive]) == ["docs/plans/old.md"]


def test_dangling_entries_passes_entry_whose_file_exists():
    index = "- 2026-09-23 [plan] x → `docs/plans/x.md`"
    assert dangling_entries(["docs/plans/x.md"], [index]) == []


def test_dangling_entries_ignores_arrow_in_prose_line():
    index = "Overview: `chunk_documents.py` → `index_chunks.py`\n"
    assert dangling_entries([], [index]) == []


def test_dangling_entries_returns_sorted():
    index = "- a → `docs/plans/b.md`\n- b → `docs/decisions/a.md`\n"
    assert dangling_entries([], [index]) == ["docs/decisions/a.md", "docs/plans/b.md"]


# recent_entry_count


def _index_with_entries(count: int) -> str:
    entries = "\n".join(f"- 2026-09-01 [plan] entry {i} → `docs/plans/{i}.md`" for i in range(count))
    return f"# Index\n\n- overview bullet, not counted\n\n## Recent\n\n{entries}\n"


def test_recent_entry_count_counts_entries_under_recent_only():
    assert recent_entry_count(_index_with_entries(50)) == 50


def test_recent_entry_count_returns_none_without_recent_header():
    assert recent_entry_count("# Index\n\n- a\n- b\n") is None


def test_recent_entry_count_ignores_trailing_prose_and_nested_bullets():
    text = (
        "## Recent\n\n- one\n- two\n  - nested detail, not an entry\n\n"
        "One line per file ... **Capped at 50 entries**: cut back to 40.\n"
    )
    assert recent_entry_count(text) == 2


def test_recent_entry_count_counts_entries_on_both_sides_of_a_prose_paragraph():
    text = "## Recent\n\n- new one\n- new two\n\nExplanatory paragraph.\n\n- old one\n"
    assert recent_entry_count(text) == 3


def test_recent_entry_count_stops_at_next_section():
    assert recent_entry_count("## Recent\n\n- one\n\n## Other\n\n- not counted\n") == 1


# blocking_message / recent_cap_warning


def test_blocking_message_returns_none_when_clean():
    assert blocking_message([], []) is None


def test_blocking_message_lists_unindexed_files():
    message = blocking_message(["docs/plans/a.md", "docs/reviews/b.md"], [])
    assert message is not None
    assert "docs/plans/a.md" in message
    assert "docs/reviews/b.md" in message
    assert "## Recent" in message
    assert "whole staged tree" in message


def test_blocking_message_lists_dangling_entries():
    message = blocking_message([], ["docs/plans/gone.md"])
    assert message is not None
    assert "docs/plans/gone.md" in message
    assert "no such file" in message


def test_blocking_message_combines_both_findings():
    message = blocking_message(["docs/plans/a.md"], ["docs/plans/gone.md"])
    assert message is not None
    assert "docs/plans/a.md" in message
    assert "docs/plans/gone.md" in message


@pytest.mark.parametrize("count", [0, 50])
def test_recent_cap_warning_returns_none_within_cap(count):
    assert recent_cap_warning(count) is None


def test_recent_cap_warning_states_trim_rule_over_cap():
    warning = recent_cap_warning(51)
    assert warning is not None
    assert "51 entries" in warning
    assert "cap is 50" in warning
    assert "trim to 40" in warning
    assert "PROJECT_INDEX_ARCHIVE.md" in warning


def test_recent_cap_warning_flags_missing_recent_section():
    warning = recent_cap_warning(None)
    assert warning is not None
    assert "no `## Recent` section" in warning


# main() -- against a real throwaway git repo.


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # A pytest run started from inside a git hook would otherwise point these
    # tmp-repo git calls at the real repo's index.
    for var in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE"):
        monkeypatch.delenv(var, raising=False)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "core.autocrlf", "false")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _stage(root: Path, rel: str, text: str) -> None:
    _write(root, rel, text)
    _git(root, "add", rel)


def _index(*rel_paths: str) -> str:
    entries = "\n".join(f"- 2026-09-23 [plan] entry → `{rel}`" for rel in rel_paths)
    return f"# Index\n\n## Recent\n\n{entries}\n"


def _run_main(capsys):
    exit_code = check_docs_health.main()
    return exit_code, capsys.readouterr().err


def test_main_is_silent_when_docs_and_entries_match(repo, capsys):
    # Also guards decoding: text-mode subprocess output uses the locale
    # codepage on Windows, which garbles `→` so no entry would match.
    _stage(repo, "PROJECT_INDEX.md", _index("docs/plans/a.md"))
    _stage(repo, "docs/plans/a.md", "x")
    _stage(repo, "docs/plans/TEMPLATE.md", "x")
    assert _run_main(capsys) == (0, "")


def test_main_blocks_staged_doc_without_entry(repo, capsys):
    _stage(repo, "PROJECT_INDEX.md", _index())
    _stage(repo, "docs/reviews/r.md", "x")
    exit_code, err = _run_main(capsys)
    assert exit_code == 1
    assert "docs/reviews/r.md" in err


def test_main_reads_non_ascii_doc_paths_unquoted(repo, capsys):
    # git quotes non-ASCII paths in ls-files output unless -z is used.
    _stage(repo, "PROJECT_INDEX.md", _index("docs/plans/café.md"))
    _stage(repo, "docs/plans/café.md", "x")
    assert _run_main(capsys) == (0, "")


def test_main_reads_staged_index_not_working_copy(repo, capsys):
    _stage(repo, "PROJECT_INDEX.md", _index())
    _stage(repo, "docs/plans/a.md", "x")
    _write(repo, "PROJECT_INDEX.md", _index("docs/plans/a.md"))
    exit_code, err = _run_main(capsys)
    assert exit_code == 1
    assert "docs/plans/a.md" in err


def test_main_ignores_untracked_docs(repo, capsys):
    _stage(repo, "PROJECT_INDEX.md", _index())
    _write(repo, "docs/plans/wip.md", "x")
    assert _run_main(capsys) == (0, "")


def test_main_blocks_entry_whose_doc_deletion_is_staged(repo, capsys):
    _stage(repo, "PROJECT_INDEX.md", _index("docs/plans/a.md"))
    _stage(repo, "docs/plans/a.md", "x")
    _git(repo, "commit", "-q", "--no-verify", "-m", "init")
    _git(repo, "rm", "-q", "docs/plans/a.md")
    exit_code, err = _run_main(capsys)
    assert exit_code == 1
    assert "docs/plans/a.md" in err


def test_main_warns_but_passes_when_recent_over_cap(repo, capsys):
    paths = [f"docs/plans/{i}.md" for i in range(51)]
    _stage(repo, "PROJECT_INDEX.md", _index(*paths))
    for rel in paths:
        _write(repo, rel, "x")
    _git(repo, "add", "docs")
    exit_code, err = _run_main(capsys)
    assert exit_code == 0
    assert "51 entries" in err


def test_main_accepts_entry_found_only_in_staged_archive(repo, capsys):
    _stage(repo, "PROJECT_INDEX.md", _index())
    _stage(repo, "PROJECT_INDEX_ARCHIVE.md", "## Archive\n\n- old → `docs/plans/old.md`\n")
    _stage(repo, "docs/plans/old.md", "x")
    assert _run_main(capsys) == (0, "")


def test_main_accepts_entry_naming_existing_non_docs_file(repo, capsys):
    _stage(repo, "PROJECT_INDEX.md", _index("scripts/tool.py"))
    _stage(repo, "scripts/tool.py", "x")
    assert _run_main(capsys) == (0, "")


def test_main_ignores_docs_in_nested_folders(repo, capsys):
    _stage(repo, "PROJECT_INDEX.md", _index())
    _stage(repo, "docs/plans/assets/notes.md", "x")
    assert _run_main(capsys) == (0, "")


def test_main_skips_with_warning_when_index_not_staged(repo, capsys):
    _stage(repo, "docs/plans/a.md", "x")
    exit_code, err = _run_main(capsys)
    assert exit_code == 0
    assert "docs-index check skipped" in err
    assert "PROJECT_INDEX.md" in err


def test_main_skips_with_warning_on_non_utf8_index(repo, capsys):
    (repo / "PROJECT_INDEX.md").write_bytes(b"\x81")
    _git(repo, "add", "PROJECT_INDEX.md")
    exit_code, err = _run_main(capsys)
    assert exit_code == 0
    assert "docs-index check skipped" in err


def test_main_skips_with_warning_outside_a_git_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    exit_code, err = _run_main(capsys)
    assert exit_code == 0
    assert "docs-index check skipped" in err


def test_main_skips_with_warning_when_git_is_missing(repo, monkeypatch, capsys):
    def no_git(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(check_docs_health.subprocess, "run", no_git)
    exit_code, err = _run_main(capsys)
    assert exit_code == 0
    assert "docs-index check skipped" in err


def test_partial_commit_is_checked_against_what_git_commits(repo):
    # `git commit <paths>` builds a temporary index from HEAD plus those paths;
    # the hook must judge that index, not the regular staging area.
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "{SCRIPT_PATH.as_posix()}"\n')
    hook.chmod(0o755)
    _stage(repo, "PROJECT_INDEX.md", _index())
    _git(repo, "commit", "-q", "--no-verify", "-m", "init")
    _stage(repo, "docs/plans/b.md", "x")
    _write(repo, "PROJECT_INDEX.md", _index("docs/plans/b.md"))

    doc_only = subprocess.run(
        ["git", "-c", "core.hooksPath=.git/hooks", "commit", "-q", "-m", "doc only", "docs/plans/b.md"],
        cwd=repo,
        capture_output=True,
    )
    assert doc_only.returncode != 0
    assert b"docs/plans/b.md" in doc_only.stderr

    with_index = subprocess.run(
        ["git", "-c", "core.hooksPath=.git/hooks", "commit", "-q", "-m", "doc and index",
         "docs/plans/b.md", "PROJECT_INDEX.md"],
        cwd=repo,
        capture_output=True,
    )
    assert with_index.returncode == 0, with_index.stderr
