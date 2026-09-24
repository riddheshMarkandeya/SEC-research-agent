"""Pre-commit check: the docs index and the docs folders must agree, both ways.

Blocks the commit (exit 1) when a docs/{decisions,plans,reviews}/*.md file
(TEMPLATE.md excluded) has no entry, meaning a line ending in "→ `<repo
path>`", in PROJECT_INDEX.md or PROJECT_INDEX_ARCHIVE.md, or when an entry
names a file that doesn't exist. Warns without blocking when
PROJECT_INDEX.md's `## Recent` section is over its entry cap.

Everything is read from the staged tree via git, not the working copy, so
the check judges exactly what is being committed (including the temporary
index git builds for `commit -a` and `commit <paths>`) and ignores untracked
work in progress. It checks the whole staged tree, not just this commit's
diff, so a miss that slipped in by a path that skips pre-commit (merge,
rebase, --no-verify) is caught by the next ordinary commit.

Fails open: if git or the index can't be read, it warns and exits 0, since
a tooling fault in a housekeeping check shouldn't block every commit.
"""

import re
import subprocess
import sys

DOCS_DIRS = ("docs/decisions", "docs/plans", "docs/reviews")
TEMPLATE_NAME = "TEMPLATE.md"
INDEX_FILE = "PROJECT_INDEX.md"
ARCHIVE_FILE = "PROJECT_INDEX_ARCHIVE.md"
RECENT_HEADER = "## Recent"
RECENT_CAP = 50
RECENT_TRIM_TARGET = 40
# An entry is a top-level bullet; its path is the backticked one after its
# trailing arrow. Prose or nested bullets ending in an arrow aren't entries.
ENTRY_PATH_RE = re.compile(r"^- .*→ `([^`]+)`\s*$", re.MULTILINE)


class GitError(Exception):
    pass


def _entry_paths(index_texts: list[str]) -> set[str]:
    return {path for text in index_texts for path in ENTRY_PATH_RE.findall(text)}


def _is_doc(rel_path: str) -> bool:
    """A `.md` file other than TEMPLATE.md directly inside one of DOCS_DIRS
    (subfolders don't count)."""
    folder, _, name = rel_path.rpartition("/")
    return folder in DOCS_DIRS and name.endswith(".md") and name != TEMPLATE_NAME


def unindexed_docs(rel_paths: list[str], index_texts: list[str]) -> list[str]:
    """Docs files among `rel_paths` (sorted) with no entry in `index_texts`.
    An entry's own path is the backticked one after its trailing `→`, so a
    path mentioned in another entry's prose, backticked or not, doesn't
    count as indexed."""
    docs = {path for path in rel_paths if _is_doc(path)}
    return sorted(docs - _entry_paths(index_texts))


def dangling_entries(rel_paths: list[str], index_texts: list[str]) -> list[str]:
    """Entry paths in `index_texts` (sorted) that name no file in `rel_paths`,
    e.g. a doc renamed or deleted without its index line being updated."""
    return sorted(_entry_paths(index_texts) - set(rel_paths))


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


def blocking_message(unindexed: list[str], dangling: list[str]) -> str | None:
    """Why the commit is blocked, or None when the index and docs agree."""
    # ASCII only: a Windows console's codepage can't show the entry arrow.
    problems = []
    if unindexed:
        problems.append(
            f"No index entry for: {', '.join(unindexed)}. Add one under "
            f"{INDEX_FILE}'s `{RECENT_HEADER}`, in the same format as the others."
        )
    if dangling:
        problems.append(
            f"Index entries name no such file: {', '.join(dangling)}. Fix or "
            f"remove those lines in {INDEX_FILE} or {ARCHIVE_FILE}."
        )
    if not problems:
        return None
    return (
        "Commit blocked by the docs-index check (it checks the whole staged tree, "
        "not just this commit). " + " ".join(problems)
    )


def recent_cap_warning(recent_count: int | None) -> str | None:
    """Housekeeping warning about `## Recent`'s size, or None when within cap."""
    if recent_count is None:
        return f"Warning: {INDEX_FILE} has no `{RECENT_HEADER}` section."
    if recent_count > RECENT_CAP:
        return (
            f"Warning: {INDEX_FILE}'s `{RECENT_HEADER}` section has {recent_count} "
            f"entries; its cap is {RECENT_CAP} (trim to {RECENT_TRIM_TARGET}, moving "
            f"the oldest entries verbatim to the top of {ARCHIVE_FILE})."
        )
    return None


def _git(*args: str) -> str:
    # Decode explicitly: text mode would use the locale codepage (cp1252 on
    # Windows), garbling the `→` every index entry depends on.
    result = subprocess.run(["git", *args], capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {stderr}")
    return result.stdout.decode("utf-8")


def _staged_files() -> list[str]:
    # -z: without it git quotes and escapes non-ASCII paths.
    return [path for path in _git("ls-files", "--cached", "-z").split("\0") if path]


def check() -> tuple[str | None, str | None]:
    """(blocking message, warning) for the staged tree."""
    staged = _staged_files()
    if INDEX_FILE not in staged:
        return None, f"docs-index check skipped: {INDEX_FILE} is not in the staged tree."
    index_text = _git("show", f":{INDEX_FILE}")
    archive_text = _git("show", f":{ARCHIVE_FILE}") if ARCHIVE_FILE in staged else ""
    index_texts = [index_text, archive_text]
    return (
        blocking_message(unindexed_docs(staged, index_texts), dangling_entries(staged, index_texts)),
        recent_cap_warning(recent_entry_count(index_text)),
    )


def main() -> int:
    try:
        blocking, warning = check()
    except (GitError, OSError, UnicodeDecodeError) as exc:
        blocking, warning = None, f"docs-index check skipped: {exc}"
    if warning:
        print(warning, file=sys.stderr)
    if blocking:
        print(blocking, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
