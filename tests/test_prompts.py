"""prompts.prompt_fingerprint(): a per-surface hash of every model-facing
constant, with each consumer key (agent, judge, mcp) also covering its
section of the committed model-input snapshot. Eval reports carry it so a
result can be tied to the exact prompt version that produced it."""

import ast
import json
import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest

import prompts

REPO_ROOT = Path(__file__).resolve().parent.parent
SURFACES = ("agent_system", "agent_tools", "agent_messages", "judge", "mcp")
AGENT_SURFACES = ("agent_system", "agent_tools", "agent_messages")
# The consumer key each surface's text reaches.
CONSUMER_KEY = {
    "agent_system": "agent",
    "agent_tools": "agent",
    "agent_messages": "agent",
    "judge": "judge",
    "mcp": "mcp",
}


def _changed_keys(before: dict, after: dict) -> set[str]:
    return {k for k in before if before[k] != after[k]}


def _altered(value):
    """A JSON-serialisable value guaranteed to differ from `value`."""
    return value + "x" if isinstance(value, str) else [value, "x"]


def test_fingerprint_has_one_key_per_surface_plus_the_agent_key():
    fp = prompts.prompt_fingerprint()
    assert set(fp) == {*SURFACES, "agent"}
    assert all(isinstance(v, str) and len(v) == 12 for v in fp.values())


def test_fingerprint_is_stable_within_a_process():
    assert prompts.prompt_fingerprint() == prompts.prompt_fingerprint()


def test_fingerprint_is_identical_across_hash_seeds():
    script = "import json, prompts; print(json.dumps(prompts.prompt_fingerprint(), sort_keys=True))"
    outputs = set()
    for seed in ("1", "2"):
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=False,
        )
        assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
        outputs.add(proc.stdout)
    assert len(outputs) == 1


@pytest.mark.parametrize("surface", SURFACES)
def test_changing_a_fingerprinted_constant_changes_its_surface_and_consumer_key(monkeypatch, surface):
    module = import_module(f"prompts.{surface}")
    before = prompts.prompt_fingerprint()
    for name in module.FINGERPRINTED:
        with monkeypatch.context() as mp:
            mp.setattr(module, name, _altered(getattr(module, name)))
            changed = _changed_keys(before, prompts.prompt_fingerprint())
        assert changed == {surface, CONSUMER_KEY[surface]}, (surface, name, changed)


@pytest.mark.parametrize("surface", SURFACES)
def test_changing_a_not_fingerprinted_name_changes_nothing(monkeypatch, surface):
    module = import_module(f"prompts.{surface}")
    before = prompts.prompt_fingerprint()
    for name in module.NOT_FINGERPRINTED:
        with monkeypatch.context() as mp:
            mp.setattr(module, name, _altered(getattr(module, name)))
            assert prompts.prompt_fingerprint() == before, name


def _top_level_uppercase_assignments(path: Path) -> set[str]:
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        names |= {t.id for t in targets if isinstance(t, ast.Name) and t.id.isupper()}
    return names - {"FINGERPRINTED", "NOT_FINGERPRINTED"}


@pytest.mark.parametrize("surface", SURFACES)
def test_every_constant_is_classified_exactly_once(surface):
    # A new constant that is in neither tuple would silently fall out of
    # the fingerprint, so every one has to be classified.
    module = import_module(f"prompts.{surface}")
    fingerprinted, not_fingerprinted = set(module.FINGERPRINTED), set(module.NOT_FINGERPRINTED)
    assert not fingerprinted & not_fingerprinted
    assert len(module.FINGERPRINTED) == len(fingerprinted)
    assert fingerprinted | not_fingerprinted == _top_level_uppercase_assignments(
        REPO_ROOT / "prompts" / f"{surface}.py"
    )


@pytest.mark.parametrize("surface", SURFACES)
def test_every_fingerprinted_value_is_strict_json(surface):
    # No `default=` fallback when hashing: a value JSON can't represent
    # must fail here rather than be hashed through a seed-dependent repr.
    module = import_module(f"prompts.{surface}")
    for name in module.FINGERPRINTED:
        json.dumps(getattr(module, name), ensure_ascii=False, allow_nan=False)


def _snapshot_copy(tmp_path: Path, edit=None, newline="\n") -> Path:
    data = json.loads(prompts.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if edit is not None:
        edit(data)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline=newline)
    return path


@pytest.mark.parametrize("section", ["agent", "judge", "mcp"])
def test_changing_one_snapshot_section_changes_only_its_consumer_key(tmp_path, section):
    before = prompts.prompt_fingerprint(_snapshot_copy(tmp_path))

    def edit(data):
        data[section]["added_scenario"] = "x"

    after = prompts.prompt_fingerprint(_snapshot_copy(tmp_path, edit))
    assert _changed_keys(before, after) == {section}


def test_snapshot_line_endings_and_key_order_do_not_change_the_fingerprint(tmp_path):
    # git's autocrlf rewrites the committed file's line endings on checkout.
    lf = prompts.prompt_fingerprint(_snapshot_copy(tmp_path))
    crlf = prompts.prompt_fingerprint(_snapshot_copy(tmp_path, newline="\r\n"))
    assert lf == crlf == prompts.prompt_fingerprint()


def test_missing_snapshot_raises(tmp_path):
    with pytest.raises(OSError):
        prompts.prompt_fingerprint(tmp_path / "absent.json")


def test_malformed_snapshot_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        prompts.prompt_fingerprint(bad)
