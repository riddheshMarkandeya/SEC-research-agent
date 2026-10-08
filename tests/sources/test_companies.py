"""
Unit tests for companies.py — the shared ticker/company registry that
replaced the two separately-hardcoded COMPANIES dicts previously
duplicated (with different shapes) across edgar_ingest.py and agent.py.
"""

import pytest

from sec_agent.sources.companies import _validate, load_companies


def test_load_companies_tickers_and_fiscal_year_end_months():
    # Pinned by hand on purpose, and not copied from SEC's submissions
    # `fiscalYearEnd`, which is the last 52/53-week period end date: JNJ
    # reports "0103" (month 1 would mislabel every JNJ quarter) and TGT
    # "0201". TGT is 2, not its nominal January: its years and quarters end
    # on Saturdays that fall either side of a month boundary (2024-02-03,
    # 2026-01-31; 2023-04-29, 2024-05-04), and only month 2 puts each in
    # the right fiscal year and quarter, named by the calendar year the
    # period ends in.
    companies = load_companies()
    months = {t: info["fiscal_year_end_month"] for t, info in companies.items()}
    assert months == {
        "AAPL": 9, "MSFT": 6, "NVDA": 1, "CRM": 1, "PLTR": 12,
        "JPM": 12, "BAC": 12, "TGT": 2, "WMT": 1, "XOM": 12, "JNJ": 12, "CAT": 12,
    }


def test_load_companies_entries_have_name_and_cik():
    companies = load_companies()
    for ticker, info in companies.items():
        assert "name" in info and info["name"], f"{ticker} missing a name"
        assert "cik" in info and info["cik"], f"{ticker} missing a cik"


def test_load_companies_ciks_are_ten_digit_zero_padded():
    # edgar_ingest.py's URLs assume this exact format (CIK{cik}.json) —
    # a malformed CIK here would silently 404 rather than error clearly.
    companies = load_companies()
    for ticker, info in companies.items():
        cik = info["cik"]
        assert len(cik) == 10 and cik.isdigit(), f"{ticker} has a malformed CIK: {cik!r}"


# ---------------------------------------------------------------------------
# _validate -- schema check on companies.json's shape. Real gap it
# closes: every downstream reader (agent.py, xbrl_facts.py,
# period_labels.py, edgar_ingest.py) does raw info["name"]/info["cik"]/
# info["fiscal_year_end_month"] indexing with no defensive check of its
# own, so a malformed entry used to surface as a confusing KeyError three
# layers down in some unrelated ticker/metric lookup instead of one clear
# error at load time. See
# docs/decisions/2026-09-09-schema-driven-arg-validation.md.
# ---------------------------------------------------------------------------
def test_validate_accepts_the_real_companies_json():
    # Regression guard against the schema itself being wrong -- the real
    # file must still load cleanly through the same check load_companies()
    # runs on every call.
    _validate(load_companies())


def test_validate_rejects_entry_missing_cik():
    with pytest.raises(ValueError, match="companies.json is malformed"):
        _validate({"AAPL": {"name": "Apple Inc.", "fiscal_year_end_month": 9}})


def test_validate_rejects_wrong_typed_fiscal_year_end_month():
    with pytest.raises(ValueError, match="companies.json is malformed"):
        _validate({"AAPL": {"name": "Apple Inc.", "cik": "0000320193", "fiscal_year_end_month": "9"}})


def test_validate_rejects_unexpected_extra_key():
    with pytest.raises(ValueError, match="companies.json is malformed"):
        _validate(
            {
                "AAPL": {
                    "name": "Apple Inc.",
                    "cik": "0000320193",
                    "fiscal_year_end_month": 9,
                    "ticker_symbol": "AAPL",
                }
            }
        )


def test_validate_accepts_a_well_formed_entry():
    _validate({"AAPL": {"name": "Apple Inc.", "cik": "0000320193", "fiscal_year_end_month": 9}})
