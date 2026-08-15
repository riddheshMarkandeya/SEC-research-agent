"""
Unit tests for companies.py — the shared ticker/company registry that
replaced the two separately-hardcoded COMPANIES dicts previously
duplicated (with different shapes) across edgar_ingest.py and agent.py.
"""

from companies import load_companies


def test_load_companies_returns_expected_tickers():
    companies = load_companies()
    assert set(companies.keys()) == {"AAPL", "MSFT", "NVDA", "CRM", "PLTR"}


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
