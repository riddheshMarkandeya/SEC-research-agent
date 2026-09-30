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


# PLR0913: a test-fixture builder called almost exclusively with
# keyword args for a subset of fields -- the same "idiomatic test
# pattern, not a real finding" this project's pyproject.toml already
# applies to PLR2004 in tests/*. Bundling these into a dict would
# force-touch every one of the agent tests' many call sites for zero
# behavioral benefit.
def _fake_result(  # noqa: PLR0913
    ticker="CRM", form="10-K", reportDate="2026-01-31", text="Some chunk text.",
    filingDate="2026-03-02", accessionNumber="0001108524-26-000060", chunk_index: int | str = 95
):
    return {
        "text": text,
        "metadata": {
            "ticker": ticker,
            "form": form,
            "reportDate": reportDate,
            "filingDate": filingDate,
            "accessionNumber": accessionNumber,
            "chunk_index": chunk_index,
        },
    }


def _valid_submitted_claim(**overrides):
    claim = {
        "value": 100.0,
        "unit": "raw",
        "citation_index": 1,
        "quote": "the reported value for the period was exactly 100",
    }
    claim.update(overrides)
    return claim
