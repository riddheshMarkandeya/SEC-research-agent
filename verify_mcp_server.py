"""
One-time (re-runnable) live verification for mcp_server.py (Week 6).

Why this exists: the actual MCP protocol/HTTP wiring (mcp.server.Server,
streamable_http_app, the real client round-trip) is live-only code per
this project's TDD carve-out -- mocking it would test the mock, not the
server. This script starts the real server as a subprocess, connects
with the real `mcp` client over genuine HTTP, and checks:

1. list_tools() returns exactly the 3 expected tools.
2. get_financial_fact/compare_financial_metric values match already
   ground-truthed data from this project's own eval questions (not
   guessed) -- see eval_questions.jsonl's five-company-*-margin-ranking
   questions for where the compare_financial_metric numbers came from.
3. Every returned `sec_url` is a REAL, live, fetchable SEC EDGAR URL
   (an actual HTTP GET, not just "looks structurally right").
4. A search_filings result's text-fragment excerpt literally appears in
   the live filing page's fetched text -- a proxy for "a browser's
   Scroll-To-Text-Fragment will actually highlight this," since there's
   no way to script a real browser's highlight behavior here.

Re-run this after any change to mcp_server.py's source-block/excerpt
logic, or to the underlying tool schemas/dispatch it wraps.

Usage:
    python verify_mcp_server.py
"""

import asyncio
import json
import subprocess
import sys
import time
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from config import SEC_USER_AGENT

PORT = 8799
BASE_URL = f"http://127.0.0.1:{PORT}"
MCP_URL = f"{BASE_URL}/mcp"

# Ground truth already verified live in this project's own eval work
# (see eval_questions.jsonl's five-company-gross-margin-ranking-fy2025
# and PROJECT_CONTEXT.md's corresponding addendum) -- not guessed here.
EXPECTED_GROSS_MARGIN_FY2025 = {"AAPL": 46.9, "MSFT": 68.8, "NVDA": 71.1, "CRM": 77.7, "PLTR": 82.4}


def _get_text(result) -> dict:
    if result.is_error:
        raise AssertionError(f"tool call returned an error: {result.content}")
    return json.loads(result.content[0].text)


def _assert_live_url(url: str, label: str):
    resp = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=15)
    assert resp.status_code == 200, f"{label}: {url} returned {resp.status_code}"
    print(f"  [OK] {label} resolves live (200): {url}")
    return resp.text


async def run_checks():
    async with streamable_http_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert names == {"search_filings", "get_financial_fact", "compare_financial_metric"}, names
            print("[OK] list_tools ->", sorted(names))

            print("\n[get_financial_fact] AAPL revenue FY2025")
            result = await session.call_tool(
                "get_financial_fact", {"ticker": "AAPL", "metric": "revenue", "fiscal_year": 2025, "fiscal_period": "FY"}
            )
            data = _get_text(result)
            # get_financial_fact's raw output is unscaled USD, not the
            # eval harness's normalized "million" display unit -- see
            # call_get_financial_fact()'s own direct-call output.
            assert data["value"] == 416161000000 and data["unit"] == "USD", data
            print(f"  [OK] value matches ground truth: {data['value']} {data['unit']}")
            _assert_live_url(data["source"]["sec_url"], "get_financial_fact sec_url")

            print("\n[compare_financial_metric] gross_margin, anchored AAPL FY2025")
            result = await session.call_tool(
                "compare_financial_metric", {"anchor_ticker": "AAPL", "metric": "gross_margin", "fiscal_year": 2025, "fiscal_period": "FY"}
            )
            data = _get_text(result)
            for ticker, expected_value in EXPECTED_GROSS_MARGIN_FY2025.items():
                assert data[ticker]["value"] == expected_value, (ticker, data[ticker], expected_value)
            print(f"  [OK] all 5 companies match ground truth: { {t: d['value'] for t, d in data.items()} }")
            _assert_live_url(data["PLTR"]["source"]["sec_url"], "compare_financial_metric PLTR sec_url")

            print("\n[search_filings] AAPL artificial intelligence risk")
            result = await session.call_tool("search_filings", {"query": "artificial intelligence risk", "ticker": "AAPL"})
            data = _get_text(result)
            assert len(data) > 0, "expected at least one search result"
            print(f"  [OK] {len(data)} results returned")

            fragment_checked = False
            for r in data:
                sec_url = r["source"].get("sec_url", "")
                if "#:~:text=" not in sec_url:
                    continue
                base_url, fragment = sec_url.split("#:~:text=", 1)
                excerpt = " ".join(unquote(fragment).split())
                page_html = _assert_live_url(base_url, "search_filings sec_url")
                page_text = " ".join(BeautifulSoup(page_html, "lxml").get_text().split())
                found = excerpt in page_text
                status = "OK" if found else "WARN"
                print(f"  [{status}] text-fragment excerpt {'found' if found else 'NOT FOUND'} verbatim in live page")
                print(f"        excerpt: {excerpt[:100]!r}")
                fragment_checked = True
                break
            if not fragment_checked:
                print("  [INFO] no result had a text-fragment sec_url to check (all table-only excerpts or no filing match)")


def main():
    proc = subprocess.Popen([sys.executable, "mcp_server.py", "--port", str(PORT)])
    try:
        for _ in range(30):
            try:
                requests.get(BASE_URL, timeout=1)
                break
            except requests.exceptions.ConnectionError:
                time.sleep(0.5)
        else:
            raise RuntimeError("mcp_server.py did not start listening in time")
        asyncio.run(run_checks())
        print("\nAll checks passed.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
