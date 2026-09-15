"""PreToolUse hook: block a `git commit` that stages a new
docs/decisions/*.md file without also staging PROJECT_INDEX.md. Mechanical
safety net for the documentation-backlog-hygiene skill's same-step index
rule. See docs/decisions/2026-09-15-claude-md-restructure.md.
"""

import json
import re
import subprocess
import sys

SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;|]")
COMMIT_SEGMENT_RE = re.compile(r"^\s*git\s+commit\b")
DECISIONS_PREFIX = "docs/decisions/"
INDEX_FILE = "PROJECT_INDEX.md"


def is_commit_command(command: str) -> bool:
    """True only when `git commit` is an actually-invoked segment of the
    command (split on &&/||/;/|), not merely substring text anywhere in
    it — a plain substring search false-positives on commands that just
    mention "git commit" as data, e.g. an echoed JSON payload."""
    return any(COMMIT_SEGMENT_RE.match(segment) for segment in SEGMENT_SPLIT_RE.split(command))


def new_decisions_missing_index(staged_files: list[str]) -> list[str]:
    """Staged docs/decisions/*.md files (excluding TEMPLATE.md) when
    PROJECT_INDEX.md isn't staged alongside them."""
    if INDEX_FILE in staged_files:
        return []
    return [
        f
        for f in staged_files
        if f.startswith(DECISIONS_PREFIX) and f.endswith(".md") and not f.endswith("TEMPLATE.md")
    ]


def _staged_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    if not is_commit_command(command):
        return 0

    missing = new_decisions_missing_index(_staged_files())
    if missing:
        names = ", ".join(missing)
        print(
            f"Blocked: {names} is staged but {INDEX_FILE} is not. Add its "
            f"index entry and stage {INDEX_FILE} before committing (per the "
            "documentation-backlog-hygiene skill's same-step rule).",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
