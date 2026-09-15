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

from dotenv import load_dotenv

load_dotenv()

# SEC EDGAR requires a descriptive, real-looking User-Agent header on
# every request (edgar_ingest.py, xbrl_facts.py) or it will reject the
# request — SEC checks that the email at least looks like a real one.
SEC_USER_AGENT_NAME = os.getenv("SEC_USER_AGENT_NAME", "Rid")
SEC_USER_AGENT_EMAIL = os.getenv("SEC_USER_AGENT_EMAIL", "riddhesh2307@gmail.com")
SEC_USER_AGENT = f"{SEC_USER_AGENT_NAME} {SEC_USER_AGENT_EMAIL}"

# Local Ollama server (agent.py, eval_harness.py).
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "qwen2.5:7b-instruct")

# Which LLM backend agent.py/eval_harness.py use when --backend isn't
# passed explicitly (llm_backends.py's BACKENDS dict has the full list).
# Gemini since 2026-09-10 -- Ollama remains fully supported (the only
# backend needing no API key) but demoted from default; pass
# --backend ollama explicitly to use it. See
# docs/decisions/2026-09-10-citation-gate-measurement-instrumentation.md.
DEFAULT_BACKEND = os.getenv("DEFAULT_BACKEND", "gemini")

# Gemini (free tier, api key from aistudio.google.com) -- llm_backends.py.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-flash-lite-latest")

# Persistent Chroma vector store path (index_chunks.py, retrieval.py,
# query_chunks.py) — must be the SAME path in all three, or querying
# silently hits an empty or unrelated store instead of erroring.
CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma_db")

# Embedding + reranking models (index_chunks.py, retrieval.py,
# query_chunks.py) — the embedding model in particular must be
# identical between indexing and querying, since vectors produced by
# two different models aren't comparable to each other.
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
TRACE_LOG_PATH = os.getenv("TRACE_LOG_PATH", "./trace_logs/traces.jsonl")
