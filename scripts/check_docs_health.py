"""SessionStart hook: audit the docs index and report problems to Claude as
session context.

Two checks: every docs/{decisions,plans,reviews}/*.md file (TEMPLATE.md
excluded) must have an entry, a line ending in "→ `<repo path>`", in
PROJECT_INDEX.md or PROJECT_INDEX_ARCHIVE.md; and PROJECT_INDEX.md's
`## Recent` section must stay within its entry cap. This catches an index entry missed by any commit
path, including a chained `git add && git commit` that the commit-time
check sees before staging happens.

Prints nothing when both checks pass, so a clean session costs no context.
Never blocks: always exits 0. A SessionStart hook's stderr only reaches the
debug log, so any degraded state is reported inside the context text instead.
"""

import json
import os
import re
import sys
from pathlib import Path

DOCS_DIRS = ("docs/decisions", "docs/plans", "docs/reviews")
TEMPLATE_NAME = "TEMPLATE.md"
INDEX_FILE = "PROJECT_INDEX.md"
ARCHIVE_FILE = "PROJECT_INDEX_ARCHIVE.md"
RECENT_HEADER = "## Recent"
RECENT_CAP = 50
RECENT_TRIM_TARGET = 40
REPORT_PREFIX = "Docs health at session start:"
ENTRY_PATH_RE = re.compile(r"→ `([^`]+)`\s*$", re.MULTILINE)


def unindexed_docs(rel_paths: list[str], index_texts: list[str]) -> list[str]:
    """Docs files (as sorted POSIX paths) with no entry in `index_texts`.
    An entry's own path is the backticked one after its trailing `→`, so a
    path mentioned in another entry's prose, backticked or not, doesn't
    count as indexed."""
    indexed = {path for text in index_texts for path in ENTRY_PATH_RE.findall(text)}
    posix_paths = (rel_path.replace("\\", "/") for rel_path in rel_paths)
    return sorted(
        path for path in posix_paths if path.rsplit("/", 1)[-1] != TEMPLATE_NAME and path not in indexed
    )


def recent_entry_count(index_text: str) -> int | None:
    """Number of top-level `- ` entries between `## Recent` and the next
    `## ` heading (or end of file); None when there is no `## Recent`.
    Indented bullets and prose paragraphs aren't entries."""
    lines = index_text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == RECENT_HEADER), None)
    if start is None:
        return None
    count = 0
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            count += 1
    return count


def build_report(unindexed: list[str], recent_count: int | None) -> str | None:
    """Context text stating each finding as a fact, or None when clean."""
    findings = []
    if unindexed:
        findings.append(
            f"{len(unindexed)} docs file(s) have no entry in {INDEX_FILE} or "
            f"{ARCHIVE_FILE}: {', '.join(unindexed)}."
        )
    if recent_count is None:
        findings.append(f"{INDEX_FILE} has no `{RECENT_HEADER}` section.")
    elif recent_count > RECENT_CAP:
        findings.append(
            f"{INDEX_FILE}'s `{RECENT_HEADER}` section has {recent_count} entries; its cap "
            f"is {RECENT_CAP} (trim to {RECENT_TRIM_TARGET}, moving the oldest entries "
            f"verbatim to the top of {ARCHIVE_FILE})."
        )
    if not findings:
        return None
    return f"{REPORT_PREFIX} " + " ".join(findings)


def _repo_root() -> Path:
    # The hook's working directory follows Claude's current directory, which
    # can drift from the repo root, so resolve the root explicitly.
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[1]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _list_docs(root: Path) -> list[str]:
    return [
        path.relative_to(root).as_posix()
        for docs_dir in DOCS_DIRS
        for path in (root / docs_dir).glob("*.md")
    ]


def audit(root: Path) -> str | None:
    index_text = _read_text(root / INDEX_FILE)
    if index_text is None:
        return f"{REPORT_PREFIX} {INDEX_FILE} not found; docs audit skipped."
    archive_text = _read_text(root / ARCHIVE_FILE) or ""
    unindexed = unindexed_docs(_list_docs(root), [index_text, archive_text])
    return build_report(unindexed, recent_entry_count(index_text))


def main() -> int:
    try:
        report = audit(_repo_root())
    # A non-UTF-8 index (e.g. saved by PowerShell's Set-Content) raises
    # UnicodeDecodeError, which isn't an OSError but must degrade the same way.
    except (OSError, UnicodeDecodeError) as exc:
        report = f"{REPORT_PREFIX} audit could not run ({exc})."
    if report:
        output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": report}}
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
