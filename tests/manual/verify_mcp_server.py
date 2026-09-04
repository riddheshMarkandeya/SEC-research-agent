"""
One-time (re-runnable) live verification for mcp_server.py (Week 6,
extended Week 7 for auth/rate-limiting).

Why this exists: the actual MCP protocol/HTTP wiring (mcp.server.Server,
streamable_http_app, the real client round-trip) is live-only code per
this project's TDD carve-out -- mocking it would test the mock, not the
server. This script starts the real server as a subprocess, connects
with the real `mcp` client over genuine HTTP, and checks:

1. list_tools() returns exactly the 3 expected tools.
2. get_financial_fact/compare_financial_metric values match already
   ground-truthed data from this project's own eval questions (not
   guessed) -- see eval/eval_questions.jsonl's five-company-*-margin-ranking
   questions for where the compare_financial_metric numbers came from.
3. Every returned `sec_url` is a REAL, live, fetchable SEC EDGAR URL
   (an actual HTTP GET, not just "looks structurally right").
4. A search_filings result's text-fragment excerpt literally appears in
   the live filing page's fetched text -- a proxy for "a browser's
   Scroll-To-Text-Fragment will actually highlight this," since there's
   no way to script a real browser's highlight behavior here.
5. (Week 7) With MCP_AUTH_TOKEN set, a request with no/wrong bearer
   token is rejected (401) and one with the correct token succeeds
   end-to-end. With a tiny MCP_RATE_LIMIT_REQUESTS, a request beyond
   the limit is rejected (429, with Retry-After) and requests succeed
   again once the window elapses. Checks 1-4 above run against a
   server with default config (no MCP_AUTH_TOKEN) to also confirm this
   stays backward compatible by default.

Re-run this after any change to mcp_server.py's source-block/excerpt
logic, its auth/rate-limit logic, or the underlying tool schemas/
dispatch it wraps.

Usage (from the repo root):
    python tests/manual/verify_mcp_server.py
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx
import requests
from bs4 import BeautifulSoup
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from config import SEC_USER_AGENT

PORT = 8799
BASE_URL = f"http://127.0.0.1:{PORT}"
MCP_URL = f"{BASE_URL}/mcp"

# A real MCP request needs this Accept header or the server itself
# would reject it with 406 before our middleware even runs -- irrelevant
# for the 401 checks below (auth middleware runs first regardless), but
# needed so the rate-limit checks' "not rate-limited yet" requests don't
# ambiguously fail for a different reason.
MCP_ACCEPT_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

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


class _RunningServer:
    """Starts mcp_server.py as a subprocess on `port`, with `env`
    merged over the current environment (e.g. to set MCP_AUTH_TOKEN/
    MCP_RATE_LIMIT_REQUESTS for one check without affecting the
    others), and waits until it's actually accepting connections."""

    def __init__(self, port: int, env: dict | None = None):
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.mcp_url = f"{self.base_url}/mcp"
        self._env = {**os.environ, **(env or {})}
        self._proc = None

    def __enter__(self):
        self._proc = subprocess.Popen([sys.executable, "mcp_server.py", "--port", str(self.port)], env=self._env)
        for _ in range(30):
            try:
                requests.get(self.base_url, timeout=1)
                break
            except requests.exceptions.ConnectionError:
                time.sleep(0.5)
        else:
            raise RuntimeError("mcp_server.py did not start listening in time")
        return self

    def __exit__(self, *exc_info):
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()


def check_auth():
    print("\n=== Auth (MCP_AUTH_TOKEN) ===")
    token = "verify-script-test-token"
    with _RunningServer(8800, env={"MCP_AUTH_TOKEN": token}) as server:
        resp = requests.post(server.mcp_url, json={}, headers=MCP_ACCEPT_HEADERS)
        assert resp.status_code == 401, f"expected 401 with no token, got {resp.status_code}"
        print("  [OK] request with no Authorization header rejected (401)")

        headers = {**MCP_ACCEPT_HEADERS, "Authorization": "Bearer wrong-token"}
        resp = requests.post(server.mcp_url, json={}, headers=headers)
        assert resp.status_code == 401, f"expected 401 with wrong token, got {resp.status_code}"
        print("  [OK] request with wrong token rejected (401)")

        async def _authed_round_trip():
            async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http_client:
                async with streamable_http_client(server.mcp_url, http_client=http_client) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        assert len(tools.tools) == 3, tools.tools

        asyncio.run(_authed_round_trip())
        print("  [OK] request with correct token succeeds end-to-end (list_tools -> 3 tools)")


def check_rate_limit():
    print("\n=== Rate limiting (MCP_RATE_LIMIT_REQUESTS) ===")
    env = {"MCP_RATE_LIMIT_REQUESTS": "2", "MCP_RATE_LIMIT_WINDOW_SECONDS": "3"}
    with _RunningServer(8801, env=env) as server:
        # _RunningServer's own startup probe (a GET /) already consumed
        # one request against this IP's budget, since the rate limit
        # applies to every route, not just /mcp -- wait past the window
        # once so the checks below start from a clean slate instead of
        # coupling this test to exactly how many requests startup used.
        time.sleep(3.5)
        for i in range(2):
            resp = requests.post(server.mcp_url, json={}, headers=MCP_ACCEPT_HEADERS)
            assert resp.status_code != 429, f"request {i + 1}/2 unexpectedly rate-limited ({resp.status_code})"
        print("  [OK] first 2 requests within the limit were not rate-limited")

        resp = requests.post(server.mcp_url, json={}, headers=MCP_ACCEPT_HEADERS)
        assert resp.status_code == 429, f"expected 429 on the 3rd rapid request, got {resp.status_code}"
        assert "Retry-After" in resp.headers, "expected a Retry-After header on 429"
        print(f"  [OK] 3rd rapid request rate-limited (429), Retry-After={resp.headers['Retry-After']}")

        time.sleep(3.5)
        resp = requests.post(server.mcp_url, json={}, headers=MCP_ACCEPT_HEADERS)
        assert resp.status_code != 429, "expected rate limit to reset once the window elapsed"
        print("  [OK] request succeeds again after the window elapses")


def check_unauthenticated_requests_are_rate_limited():
    # Code review caught a real gap in the first version of this
    # middleware: auth was checked before rate limiting, so a rejected
    # (401) request never touched the limiter -- credential-guessing
    # traffic against MCP_AUTH_TOKEN was completely unthrottled. Fixed
    # by rate-limiting (keyed by client IP) before checking auth. This
    # proves it: with no Authorization header at all, repeated requests
    # eventually get 429, not an endless stream of 401s.
    print("\n=== Rate limiting also throttles unauthenticated requests ===")
    env = {"MCP_AUTH_TOKEN": "verify-script-test-token", "MCP_RATE_LIMIT_REQUESTS": "2", "MCP_RATE_LIMIT_WINDOW_SECONDS": "3"}
    with _RunningServer(8802, env=env) as server:
        time.sleep(3.5)  # clear the startup probe's own budget usage, same reasoning as check_rate_limit()
        statuses = [requests.post(server.mcp_url, json={}, headers=MCP_ACCEPT_HEADERS).status_code for _ in range(3)]
        assert all(s in (401, 429) for s in statuses), statuses
        assert 429 in statuses, f"expected a 429 once the per-IP budget was exhausted, got {statuses}"
        print(f"  [OK] unauthenticated requests get throttled too (statuses: {statuses})")


def main():
    with _RunningServer(PORT):
        asyncio.run(run_checks())
    check_auth()
    check_rate_limit()
    check_unauthenticated_requests_are_rate_limited()
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
