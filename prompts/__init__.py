"""Every piece of static text a model reads -- the agent model, the eval
judge and MCP clients -- one module per surface. Dynamic data (chunk
text, questions, values) and logic stay with their callers.

prompt_fingerprint() hashes it all so an eval report can name the exact
prompt version that produced it."""

import hashlib
import json
from importlib import import_module
from pathlib import Path

SNAPSHOT_PATH = Path(__file__).with_name("model_input_snapshot.json")

_AGENT_SURFACES = ("agent_system", "agent_tools", "agent_messages")
_SURFACES = (*_AGENT_SURFACES, "judge", "mcp")


def _hash(value, sort_keys: bool) -> str:
    # No `default=`: a value JSON can't represent raises instead of being
    # hashed through its repr, which can vary between runs.
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=sort_keys)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _surface_hash(name: str) -> str:
    # Key order is part of what a model receives (a tool schema's
    # properties arrive in this order), so constants are hashed as-is.
    module = import_module(f"prompts.{name}")
    return _hash([getattr(module, n) for n in module.FINGERPRINTED], sort_keys=False)


def prompt_fingerprint(snapshot_path: Path = SNAPSHOT_PATH) -> dict[str, str]:
    """{surface: hash} for each prompts/ module, plus "agent", the key
    agent-prompt comparisons group by.

    The consumer keys -- agent, judge, mcp -- also hash their section of
    the committed model-input snapshot, which catches code changes that
    alter what a model reads without touching any constant here. Sections
    are parsed and re-serialised with sorted keys, so git's line-ending
    conversion of the file can't change the result. Raises OSError or
    ValueError if the snapshot is missing or malformed."""
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    surfaces = {name: _surface_hash(name) for name in _SURFACES}
    sections = {name: _hash(snapshot[name], sort_keys=True) for name in ("agent", "judge", "mcp")}
    return {
        "agent_system": surfaces["agent_system"],
        "agent_tools": surfaces["agent_tools"],
        "agent_messages": surfaces["agent_messages"],
        "judge": _hash([surfaces["judge"], sections["judge"]], sort_keys=False),
        "mcp": _hash([surfaces["mcp"], sections["mcp"]], sort_keys=False),
        "agent": _hash([*(surfaces[s] for s in _AGENT_SURFACES), sections["agent"]], sort_keys=False),
    }
