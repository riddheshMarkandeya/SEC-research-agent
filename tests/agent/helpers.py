"""
Helpers shared by the tests/agent/ test modules.
"""

import importlib
import pkgutil

import sec_agent.agent


def capture_events(monkeypatch, sink: list) -> None:
    """Patch log_event in every sec_agent.agent module that imports it, so
    each (category, fields) event lands in `sink` whichever module emits
    it. A per-module patch would silently miss events from a sibling module
    and let a "nothing was logged" assertion pass without checking."""
    for info in pkgutil.iter_modules(sec_agent.agent.__path__):
        module = importlib.import_module(f"sec_agent.agent.{info.name}")
        if hasattr(module, "log_event"):
            monkeypatch.setattr(module, "log_event", lambda category, **fields: sink.append((category, fields)))


def _valid_calculate_args(**overrides):
    args = {
        "operation": "percent_of",
        "operand_a": 34550.0,
        "citation_index_a": 1,
        "unit_a": "million",
        "operand_b": 195201.0,
        "citation_index_b": 2,
        "unit_b": "million",
    }
    args.update(overrides)
    return args
