"""
Central configuration — environment-driven settings shared across
multiple modules.

Existed because several of these values were previously copy-pasted as
module-level constants in 3+ files each with no single source of truth
— e.g. CHROMA_DIR was independently defined in index_chunks.py,
retrieval.py, AND query_chunks.py, and the embedding model name the
same way (as MODEL_NAME in two of them, EMBED_MODEL_NAME in the third —
already-diverged naming, a warning sign of exactly the kind of
"two-copies-of-the-truth" drift companies.py's own docstring flags for
ticker/CIK data). If the Chroma path or embedding model ever needed to
change, that used to mean hunting down and editing every copy in sync;
missing one wouldn't error, it would silently query an empty store or
compare vectors from two different embedding models.

Loads `.env` (see `.env.example` for the full list, with comments) via
python-dotenv. Every setting below has a fallback equal to what was
previously hardcoded, so nothing breaks without a `.env` file — it's
for overriding a default (e.g. your own email for the SEC User-Agent),
not required for the code to run.
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

# Local Ollama server (answer.py, agent.py, eval_harness.py).
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "qwen2.5:7b-instruct")

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
