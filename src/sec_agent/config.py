"""
Central configuration — environment-driven settings shared across
multiple modules. See
docs/decisions/2026-08-17-centralized-env-config.md.

Loads `.env` (see `.env.example` for the full list, with comments) via
python-dotenv. Every setting below has a fallback, so nothing breaks
without a `.env` file — it's for overriding a default (e.g. your own
email for the SEC User-Agent), not required for the code to run.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# The checkout root (this file is src/sec_agent/config.py). Valid only for
# the supported editable install, which runs the code in place.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


def project_path(value: str) -> str:
    """A relative path resolved against PROJECT_ROOT instead of the
    working directory; absolute paths pass through, and "" stays "" (an
    empty setting means disabled)."""
    if not value:
        return value
    return str(PROJECT_ROOT / value)


def env_path(name: str, default: str) -> str:
    return project_path(os.getenv(name, default))


# Generated, regenerable data (edgar_ingest -> chunk_documents ->
# index_chunks, plus caches and logs), all under one gitignored dir.
VAR_DIR = PROJECT_ROOT / "var"
DATA_DIR = VAR_DIR / "data"
CHUNKS_DIR = VAR_DIR / "chunks"
XBRL_CACHE_DIR = VAR_DIR / "xbrl_cache"

# Committed eval inputs and reports (not regenerable, so not under var/).
QUESTIONS_PATH = PROJECT_ROOT / "eval" / "eval_questions.jsonl"
RESULTS_DIR = PROJECT_ROOT / "eval" / "eval_results"

# SEC EDGAR requires a descriptive, real-looking User-Agent header on
# every request (edgar_ingest.py, xbrl_facts.py) or it will reject the
# request — SEC checks that the email at least looks like a real one.
SEC_USER_AGENT_NAME = os.getenv("SEC_USER_AGENT_NAME", "Rid")
SEC_USER_AGENT_EMAIL = os.getenv("SEC_USER_AGENT_EMAIL", "riddhesh2307@gmail.com")
SEC_USER_AGENT = f"{SEC_USER_AGENT_NAME} {SEC_USER_AGENT_EMAIL}"
# Every SEC request passes this; without one a stalled response hangs the
# caller (an agent tool call, or an ingest run) indefinitely.
SEC_REQUEST_TIMEOUT_SECONDS = 30

# Which LLM backend agent.py/eval_harness.py use when --backend isn't
# passed explicitly (llm_backends.py's BACKENDS dict has the full list;
# today that's only "gemini").
DEFAULT_BACKEND = os.getenv("DEFAULT_BACKEND", "gemini")

# Gemini (free tier, api key from aistudio.google.com) -- llm_backends.py.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-flash-lite-latest")

# Persistent Chroma vector store path (index_chunks.py, retrieval.py)
# — must be the SAME path in both, or querying silently hits an empty
# or unrelated store instead of erroring.
CHROMA_DIR = env_path("CHROMA_DIR", "var/chroma_db")

# Embedding + reranking models (index_chunks.py, retrieval.py) — the
# embedding model in particular must be identical between indexing and
# querying, since vectors produced by two different models aren't
# comparable to each other.
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-small-en-v1.5")
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL_NAME", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# mcp_server.py auth/rate limiting (Week 7 guardrails). Empty token
# means auth is disabled (matches every other .env-optional setting
# here) -- set it before exposing the server beyond localhost. Set
# MCP_RATE_LIMIT_REQUESTS=0 to disable rate limiting.
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")
MCP_RATE_LIMIT_REQUESTS = int(os.getenv("MCP_RATE_LIMIT_REQUESTS", "60"))
MCP_RATE_LIMIT_WINDOW_SECONDS = float(os.getenv("MCP_RATE_LIMIT_WINDOW_SECONDS", "60"))

# Langfuse tracing (tracing.py, Week 7 guardrails). Empty keys mean
# tracing is disabled entirely (matches every other .env-optional
# setting here) -- sign up free at langfuse.com to get keys.
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

# Local JSONL trace log (tracing.py) -- always-on backup of the same
# spans/events sent to Langfuse, independent of whether Langfuse is
# configured (Langfuse's free tier caps at 50k observations/month with
# only 30-day retention; this has neither limit). Empty string disables
# it -- unlike the other tracing settings above, this one is ON by
# default, since "always-on local backup" is the point.
TRACE_LOG_PATH = env_path("TRACE_LOG_PATH", "var/trace_logs/traces.jsonl")
