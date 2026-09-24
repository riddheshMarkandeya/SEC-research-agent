"""
Unit tests for scripts/check_docs_health.py, the SessionStart hook that
audits the docs index. `unindexed_docs`, `recent_entry_count` and
`build_report` are pure and tested directly. `main()` runs against a real
temporary repo layout (via CLAUDE_PROJECT_DIR) so the file-reading and
output-shape paths are covered end to end without a live Claude session.
"""

import json

import pytest

from scripts import check_docs_health
from scripts.check_docs_health import build_report, recent_entry_count, unindexed_docs


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


def test_unindexed_docs_normalizes_backslash_paths():
    index = "→ `docs/reviews/2026-09-23-r.md`"
    assert unindexed_docs(["docs\\reviews\\2026-09-23-r.md"], [index]) == []


def test_unindexed_docs_returns_sorted_posix_paths():
    result = unindexed_docs(["docs\\plans\\b.md", "docs/decisions/a.md"], [""])
    assert result == ["docs/decisions/a.md", "docs/plans/b.md"]


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
    # Entries prepended above the section's explanatory paragraph still count.
    text = "## Recent\n\n- new one\n- new two\n\nExplanatory paragraph.\n\n- old one\n"
    assert recent_entry_count(text) == 3


def test_recent_entry_count_stops_at_next_section():
    assert recent_entry_count("## Recent\n\n- one\n\n## Other\n\n- not counted\n") == 1


# build_report


def test_build_report_returns_none_when_clean():
    assert build_report([], 50) is None


def test_build_report_flags_recent_over_cap_with_trim_rule():
    report = build_report([], 51)
    assert report is not None
    assert report.startswith("Docs health at session start:")
    assert "51 entries" in report
    assert "cap is 50" in report
    assert "trim to 40" in report
    assert "PROJECT_INDEX_ARCHIVE.md" in report


def test_build_report_lists_unindexed_files():
    report = build_report(["docs/plans/a.md", "docs/reviews/b.md"], 10)
    assert report is not None
    assert "2 docs file(s)" in report
    assert "docs/plans/a.md" in report
    assert "docs/reviews/b.md" in report


def test_build_report_combines_both_findings():
    report = build_report(["docs/plans/a.md"], 60)
    assert report is not None
    assert "docs/plans/a.md" in report
    assert "60 entries" in report


def test_build_report_flags_missing_recent_section():
    report = build_report([], None)
    assert report is not None
    assert "no `## Recent` section" in report


# main() -- run against a temporary repo layout pointed to by CLAUDE_PROJECT_DIR.


def _make_repo(tmp_path, index_text, archive_text: str | None = "", docs=()):
    (tmp_path / "PROJECT_INDEX.md").write_text(index_text, encoding="utf-8")
    if archive_text is not None:
        (tmp_path / "PROJECT_INDEX_ARCHIVE.md").write_text(archive_text, encoding="utf-8")
    for rel in docs:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return tmp_path


def _run_main(monkeypatch, capsys, root):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    exit_code = check_docs_health.main()
    return exit_code, capsys.readouterr().out


def _context(out):
    return json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_main_prints_nothing_when_docs_are_healthy(tmp_path, monkeypatch, capsys):
    index = "## Recent\n\n- 2026-09-23 [plan] x → `docs/plans/2026-09-23-x.md`\n"
    root = _make_repo(tmp_path, index, docs=["docs/plans/2026-09-23-x.md", "docs/plans/TEMPLATE.md"])
    exit_code, out = _run_main(monkeypatch, capsys, root)
    assert exit_code == 0
    assert out == ""


def test_main_emits_session_start_json_on_findings(tmp_path, monkeypatch, capsys):
    root = _make_repo(tmp_path, _index_with_entries(51), docs=["docs/decisions/2026-09-23-new.md"])
    exit_code, out = _run_main(monkeypatch, capsys, root)
    assert exit_code == 0
    payload = json.loads(out)
    assert set(payload) == {"hookSpecificOutput"}
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    context = _context(out)
    assert "docs/decisions/2026-09-23-new.md" in context
    assert "51 entries" in context


def test_main_reports_missing_index_instead_of_failing(tmp_path, monkeypatch, capsys):
    exit_code, out = _run_main(monkeypatch, capsys, tmp_path)
    assert exit_code == 0
    assert "PROJECT_INDEX.md not found; docs audit skipped" in _context(out)


def test_main_treats_missing_archive_as_empty(tmp_path, monkeypatch, capsys):
    index = "## Recent\n\n- x → `docs/plans/a.md`\n"
    root = _make_repo(tmp_path, index, archive_text=None, docs=["docs/plans/a.md"])
    exit_code, out = _run_main(monkeypatch, capsys, root)
    assert exit_code == 0
    assert out == ""


def test_main_reports_audit_failure_as_context(tmp_path, monkeypatch, capsys):
    def boom(_root):
        raise OSError("disk unavailable")

    monkeypatch.setattr(check_docs_health, "_list_docs", boom)
    root = _make_repo(tmp_path, "## Recent\n")
    exit_code, out = _run_main(monkeypatch, capsys, root)
    assert exit_code == 0
    context = _context(out)
    assert "could not run" in context
    assert "disk unavailable" in context


def test_main_reports_non_utf8_index_as_context(tmp_path, monkeypatch, capsys):
    root = _make_repo(tmp_path, "")
    (root / "PROJECT_INDEX.md").write_bytes(b"\x81")
    exit_code, out = _run_main(monkeypatch, capsys, root)
    assert exit_code == 0
    assert "could not run" in _context(out)


@pytest.mark.parametrize("env_value", [None, ""])
def test_repo_root_falls_back_to_script_location(monkeypatch, env_value):
    if env_value is None:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", env_value)
    root = check_docs_health._repo_root()
    assert (root / "scripts" / "check_docs_health.py").exists()
