"""
Measures retrieval offline against hand-checked gold chunks: no LLM call and
no Gemini quota. Every search_filings query logged in the trace file is
re-run through the checked-out retrieval code, and each labelled figure's
gold chunks are located in its results.

Gold (eval/retrieval_gold.jsonl) names a filing accession and a short
verbatim anchor, not a chunk ID, so labels survive re-chunking. A chunk is
gold when its accession matches and its text contains the anchor, compared
with whitespace collapsed. One figure can sit in several chunks; each is
ranked, and a part is scored on its best one.

Per (query, part) the report gives, for each gold chunk:
  - its BM25 and exact vector ranks over the whole ticker (or corpus),
    how many same-ticker chunks from other filings outrank it, and its
    rank within its own filing;
  - whether it reaches the fused candidate pool the reranker sees;
  - its final rank in the top 5 the agent receives.
A part hits when its best gold chunk is in the top 5. A question is covered
when each of its parts is hit by at least one of its queries. A miss is
classed (see classify()) so the cause of a miss can be read off the report.

Variants aren't built into this tool. Save a base report on today's code,
edit retrieval.py (uncommitted), then run with --compare BASE: it replays
the base report's own query list and exits 1 when any (query, part) hit or
question coverage is lost.

A full run re-ranks every query on the CPU: about 40 minutes with an empty
cross-encoder score cache (var/rerank_cache/, shared with
analyze_gate_replay; --no-rerank-cache turns it off) and about 3 minutes
warm, as for a --fused-floor variant, which re-scores the same pools. A
retrieval change that alters a pool or its windowing scores those queries
afresh, at full cost; iterate with --qid first.

Usage:
  python -m sec_agent.devtools.retrieval_replay --qid msft-three-segments-revenue-q3fy2026
  python -m sec_agent.devtools.retrieval_replay --out var/retrieval_replay/base-v0.json
  python -m sec_agent.devtools.retrieval_replay --compare var/retrieval_replay/base-v0.json
  python -m sec_agent.devtools.retrieval_replay --propose-gold var/retrieval_replay/proposed.jsonl
"""

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sec_agent import config, tracing
from sec_agent.agent import dispatch
from sec_agent.devtools import rerank_cache, trace_query
from sec_agent.eval import eval_harness
from sec_agent.retrieval import retrieval
from sec_agent.sources import companies, period_labels

GOLD_PATH = config.PROJECT_ROOT / "eval" / "retrieval_gold.jsonl"
_GOLD_FIELDS = ("qid", "part", "accession", "report_date", "anchor", "own_period", "note")
_SEARCH = "search_filings"
# A filing holds about 120 chunks, so a gold chunk ranked in its filing's
# top 10 is one the query clearly describes; past that it's lost among its
# own filing's other chunks.
_OWN_FILING_THRESHOLD = 10
_SNIPPET_CHARS = 200
_PROGRESS_EVERY = 25


# ---------------------------------------------------------------------------
# Query set
# ---------------------------------------------------------------------------
def search_key(record: dict) -> tuple | None:
    """A search_filings span's (query, ticker), or None for any other record."""
    if record.get("as_type") != "tool" or record.get("name") != _SEARCH:
        return None
    return trace_query.get(record, "input.query") or "", trace_query.get(record, "input.ticker")


def build_query_set(records: list[dict], ids: dict, gold_qids: set[str]) -> tuple[list[dict], dict]:
    """The logged search queries, deduplicated on (query, ticker) in
    first-seen order, each with the sorted qids it was logged under. Spans
    whose run has no known question, or whose question has no gold, are
    counted in `dropped` rather than silently skipped."""
    by_key: dict[tuple, set[str]] = {}
    dropped = {"unjoined": 0, "no_gold": 0}
    for r in records:
        key = search_key(r)
        if key is None:
            continue
        qid = ids.get(r.get("run_id"), "?")
        if qid == "?":
            dropped["unjoined"] += 1
            continue
        if qid not in gold_qids:
            dropped["no_gold"] += 1
            continue
        by_key.setdefault(key, set()).add(qid)
    queries = [{"query": q, "ticker": t, "qids": sorted(qids)} for (q, t), qids in by_key.items()]
    return queries, dropped


def filter_qids(queries: list[dict], qids: list[str] | None) -> list[dict]:
    """The queries logged under any of `qids`, each trimmed to those qids.
    All queries when `qids` is None."""
    if not qids:
        return queries
    wanted = set(qids)
    kept = [{**q, "qids": [x for x in q["qids"] if x in wanted]} for q in queries]
    return [q for q in kept if q["qids"]]


def queries_from_report(report: dict) -> list[dict]:
    """A base report's own query list, so --compare measures the same
    queries even though the trace file has grown since."""
    return [{"query": q["query"], "ticker": q["ticker"], "qids": list(q["qids"])} for q in report["queries"]]


# ---------------------------------------------------------------------------
# Gold
# ---------------------------------------------------------------------------
def load_gold(path: Path) -> list[dict]:
    """Every row of the gold file. A row missing a field is a labelling
    error, so it raises rather than being skipped."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            missing = [k for k in _GOLD_FIELDS if k not in row]
            if missing:
                raise ValueError(f"{path} line {n}: missing {', '.join(missing)}")
            rows.append(row)
    return rows


def _normalize(text: str) -> str:
    return " ".join(text.split())


def gold_matches(chunk_text: str, metadata: dict, gold_rows: list[dict]) -> list[dict]:
    """The gold rows this chunk satisfies: same accession, and the anchor
    in its text with whitespace collapsed."""
    text = _normalize(chunk_text)
    return [
        row
        for row in gold_rows
        if row["accession"] == metadata.get("accessionNumber") and _normalize(row["anchor"]) in text
    ]


def index_gold(chunks: list[dict], gold_rows: list[dict]) -> tuple[dict, list[dict]]:
    """(qid, part) -> its gold chunks as {chunk, ticker, own_period, report_date}, in corpus
    order, plus the rows no chunk matched (a mistyped anchor or a
    re-chunked table)."""
    index: dict[tuple[str, str], list[dict]] = {}
    matched: set[int] = set()
    for chunk in chunks:
        for row in gold_matches(chunk["text"], chunk["metadata"], gold_rows):
            matched.add(id(row))
            entries = index.setdefault((row["qid"], row["part"]), [])
            doc_id = retrieval._make_id(chunk["metadata"])
            if all(e["chunk"] != doc_id for e in entries):
                entries.append({"chunk": doc_id, "ticker": chunk["metadata"].get("ticker"),
                                "own_period": bool(row["own_period"]),
                                "report_date": chunk["metadata"].get("reportDate")})
    return index, [row for row in gold_rows if id(row) not in matched]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Per-chunk ranks and miss classes
# ---------------------------------------------------------------------------
def rank_stats(order: list[tuple], doc_id: str) -> dict | None:
    """A chunk's 1-based rank in a retriever's full ordering of
    (doc_id, accession, ticker), its rank among its own filing's chunks,
    and how many chunks outrank it from the same ticker's other filings
    and from other tickers. None when the retriever doesn't rank it.
    Counts per filing and per ticker are kept as it goes, since the
    target's own filing and ticker are known only once it's reached."""
    by_filing: dict[str, int] = {}
    by_ticker: dict[str, int] = {}
    for rank, (d, acc, tick) in enumerate(order, start=1):
        if d == doc_id:
            own = by_filing.get(acc, 0)
            same_ticker = by_ticker.get(tick, 0)
            return {"rank": rank, "own_filing_rank": own + 1, "other_filing_ahead": same_ticker - own,
                    "other_ticker_ahead": rank - 1 - same_ticker}
        by_filing[acc] = by_filing.get(acc, 0) + 1
        by_ticker[tick] = by_ticker.get(tick, 0) + 1
    return None


def gold_chunk_record(doc_id: str, lists: dict, report_date: str | None = None) -> dict:
    """One gold chunk's diagnostic ranks, its 1-based position in the fused
    pool, its rank in the cross-encoder's own ordering of that pool, and its
    final rank, each None when absent; and whether the search's period
    scope (lists["scope_dates"], None when unscoped) left out its filing,
    which the unscoped diagnostic ranks can't show."""
    pool, final, ce, scope_dates = lists["pool"], lists["final"], lists["ce"], lists["scope_dates"]
    return {
        "chunk": doc_id,
        "bm25": rank_stats(lists["bm25"], doc_id),
        "vector": rank_stats(lists["vector"], doc_id),
        "pool_pos": pool.index(doc_id) + 1 if doc_id in pool else None,
        "final_rank": final.index(doc_id) + 1 if doc_id in final else None,
        "ce_rank": ce.index(doc_id) + 1 if doc_id in ce else None,
        "scope_excluded": scope_dates is not None and report_date is not None and report_date not in scope_dates,
    }


def _or_inf(value: int | None) -> float:
    return math.inf if value is None else value


def _better_retriever(record: dict) -> dict | None:
    ranked = [s for s in (record["bm25"], record["vector"]) if s is not None]
    return min(ranked, key=lambda s: s["rank"]) if ranked else None


def best_gold(records: list[dict]) -> dict:
    """The gold chunk that did best: final rank, then pool position, then
    one the period scope searched over one it left out, then the better
    diagnostic rank."""

    def key(r: dict) -> tuple:
        better = _better_retriever(r)
        return (_or_inf(r["final_rank"]), _or_inf(r["pool_pos"]), r["scope_excluded"],
                _or_inf(better["rank"] if better else None))

    return min(records, key=key)


def classify(record: dict) -> str:
    """Why a gold chunk did or didn't reach the top 5, judged on the better
    of the two retrievers:
      hit              in the top 5
      rerank           in the fused pool, cut at rerank
      scope_excluded   not in the pool; the query's period scope left its
                       filing out of the search
      index_recall     not in the pool, though its exact vector rank is
                       within the vector search's candidate count: the
                       approximate index skipped it
      dilution         not in the pool; lost among its own filing's chunks
      period_confusion not in the pool; near the top of its own filing, but
                       other filings' chunks (another period) outrank it
                       at least as often as other tickers' chunks do
      other_ticker     not in the pool; mostly other tickers' chunks
                       outrank it (a query with no ticker filter)
      unranked         neither retriever ranks it"""
    if record["final_rank"] is not None:
        return "hit"
    if record["pool_pos"] is not None:
        return "rerank"
    if record["scope_excluded"]:
        return "scope_excluded"
    return _pool_miss_class(record)


def _pool_miss_class(record: dict) -> str:
    """classify's verdict on a gold chunk the period scope didn't exclude
    but that never reached the pool."""
    better = _better_retriever(record)
    if better is None:
        return "unranked"
    vector = record["vector"]
    if vector is not None and vector["rank"] <= retrieval.CANDIDATE_POOL_SIZE:
        return "index_recall"
    if better["own_filing_rank"] > _OWN_FILING_THRESHOLD:
        return "dilution"
    ahead = better["other_filing_ahead"]
    return "period_confusion" if ahead >= max(better["other_ticker_ahead"], 1) else "other_ticker"


def rerank_cause(record: dict, lists: dict) -> str:
    """Why a gold chunk in the pool was cut at rerank. The cross-encoder
    order, the order before the table rescue and the rescue-qualifying
    tables all come from retrieval itself (search_details), so only the
    rescue's fused-rank threshold is restated here.
      rescue            it made the top 5 before the table rescue, which
                        swapped it out for a table
      fusion            the cross-encoder ranks it in its top 5, but the fused
                        floor (top fused ranks keep the better of their two
                        ranks) let other chunks outrank it
      rescue_threshold  the cross-encoder ranks it lower, it's a table the
                        rescue would accept, no table made the top 5, and only
                        its fused rank (past half the pool) blocked the rescue
      model             otherwise: the cross-encoder itself scores it low"""
    top_n = len(lists["final"])
    if record["chunk"] in lists["combined"][:top_n]:
        return "rescue"  # in the pre-rescue top 5 and not in the final one
    if record["ce_rank"] is not None and record["ce_rank"] <= top_n:
        return "fusion"
    no_table_in_final = not set(lists["final"]) & lists["tables"]
    past_threshold = record["pool_pos"] > len(lists["pool"]) // 2
    if record["chunk"] in lists["rescuable"] and no_table_in_final and past_threshold:
        return "rescue_threshold"
    return "model"


def _part_rerank_cause(chunks: list[dict], lists: dict) -> str:
    """"rescue" when the table rescue swapped out one of the part's gold
    chunks: the part had made the top 5 until then. Otherwise the rerank
    cause of its pooled gold chunk the cross-encoder ranked best: the one
    rerank came closest to keeping."""
    pooled = [c for c in chunks if c["pool_pos"] is not None]
    if any(rerank_cause(c, lists) == "rescue" for c in pooled):
        return "rescue"
    return rerank_cause(min(pooled, key=lambda c: _or_inf(c["ce_rank"])), lists)


def evaluate_query(entry: dict, lists: dict, gold_index: dict) -> dict:
    """The query's result for every gold part of every qid it was logged
    under, sorted by (qid, part). A part none of whose gold chunks pass the
    query's ticker filter (the other company of a comparison) can't be
    retrieved by this query at all, so it's listed as out of scope rather
    than scored as a miss. The final top 5 is kept so a miss can be read
    against the chunks that displaced its gold."""
    parts = []
    out_of_scope = []
    for qid, part in sorted(k for k in gold_index if k[0] in entry["qids"]):
        gold = gold_index[(qid, part)]
        if entry["ticker"] and all(g["ticker"] != entry["ticker"] for g in gold):
            out_of_scope.append([qid, part])
            continue
        chunks = [gold_chunk_record(g["chunk"], lists, g["report_date"]) for g in gold]
        best = best_gold(chunks)
        own_period = next(g["own_period"] for g in gold if g["chunk"] == best["chunk"])
        cls = classify(best)
        cause = _part_rerank_cause(chunks, lists) if cls == "rerank" else None
        parts.append({"qid": qid, "part": part, "hit": cls == "hit", "class": cls, "rerank_cause": cause,
                      "own_period": own_period, "best": best, "chunks": chunks})
    return {**entry, "parts": parts, "out_of_scope": out_of_scope, "final": lists["final"]}


# ---------------------------------------------------------------------------
# Summary and compare
# ---------------------------------------------------------------------------
def _part_rows(results: list[dict]):
    for r in results:
        for p in r["parts"]:
            yield r, p


def _coverage(results: list[dict]) -> dict[str, bool]:
    """qid -> whether every one of its parts is hit by some query. A part
    that only ever appeared out of scope was never reachable, so it counts
    as not hit instead of dropping out of the check."""
    hit_parts: dict[str, dict[str, bool]] = {}
    for r in results:
        for qid, part in r.get("out_of_scope", []):
            hit_parts.setdefault(qid, {}).setdefault(part, False)
    for _, p in _part_rows(results):
        parts = hit_parts.setdefault(p["qid"], {})
        parts[p["part"]] = parts.get(p["part"], False) or p["hit"]
    return {qid: all(parts.values()) for qid, parts in sorted(hit_parts.items())}


def summarize(results: list[dict]) -> dict:
    """hit@5 and pool reach over every (query, part), miss-class counts
    overall and split by own/other-period gold, and question coverage."""
    rows = [p for _, p in _part_rows(results)]
    n = len(rows)
    hits = sum(p["hit"] for p in rows)
    reached = sum(p["best"]["pool_pos"] is not None for p in rows)
    by_period = {"own": Counter(), "other": Counter()}
    for p in rows:
        by_period["own" if p["own_period"] else "other"][p["class"]] += 1
    coverage = _coverage(results)
    return {
        "parts": n,
        "hits": hits,
        "reached": reached,
        "hit_at_5": hits / n if n else 0.0,
        "reach": reached / n if n else 0.0,
        "classes": dict(Counter(p["class"] for p in rows)),
        "by_period": {k: dict(v) for k, v in by_period.items()},
        "coverage": coverage,
        "covered": sum(coverage.values()),
        "questions": len(coverage),
        "out_of_scope": sum(len(r.get("out_of_scope", [])) for r in results),
        "rerank_causes": dict(Counter(p["rerank_cause"] for p in rows if p.get("rerank_cause"))),
    }


def _hits_by_key(results: list[dict]) -> dict[tuple, bool]:
    return {(r["query"], r["ticker"], p["qid"], p["part"]): p["hit"] for r, p in _part_rows(results)}


def compare(base: list[dict], new: list[dict]) -> dict:
    """Part hits and question coverage lost and gained against the base,
    plus class-count and rate deltas. A part missing from the new results
    counts as not hit."""
    base_hits, new_hits = _hits_by_key(base), _hits_by_key(new)
    base_s, new_s = summarize(base), summarize(new)
    classes = set(base_s["classes"]) | set(new_s["classes"])
    deltas = {c: new_s["classes"].get(c, 0) - base_s["classes"].get(c, 0) for c in sorted(classes)}
    base_cov, new_cov = base_s["coverage"], new_s["coverage"]
    return {
        "lost": [list(k) for k, hit in base_hits.items() if hit and not new_hits.get(k, False)],
        "gained": [list(k) for k, hit in new_hits.items() if hit and not base_hits.get(k, False)],
        "coverage_lost": [q for q, ok in base_cov.items() if ok and not new_cov.get(q, False)],
        "coverage_gained": [q for q, ok in new_cov.items() if ok and not base_cov.get(q, False)],
        "class_deltas": {c: d for c, d in deltas.items() if d},
        "hit_at_5_delta": new_s["hit_at_5"] - base_s["hit_at_5"],
        "reach_delta": new_s["reach"] - base_s["reach"],
    }


def compare_failed(diff: dict) -> bool:
    return bool(diff["lost"] or diff["coverage_lost"])


def check_base(base: dict, gold_sha256: str) -> None:
    """Refuses a base report measured against different gold: its hits
    would not be comparable."""
    if base["header"].get("gold_sha256") != gold_sha256:
        raise ValueError("the base report was measured against a different gold file; re-run the base")


def _part_label(key: list) -> str:
    query, ticker, qid, part = key
    return f"{qid}/{part} [{ticker}] {trace_query._safe(query)[:100]}"


def format_summary(summary: dict, diff: dict | None = None) -> str:
    s = summary
    lines = [
        f"parts: {s['parts']}  hit@5: {s['hits']} ({s['hit_at_5']:.1%})  reach: {s['reached']} ({s['reach']:.1%})",
        f"questions covered: {s['covered']}/{s['questions']}  out-of-scope parts skipped: {s['out_of_scope']}",
        "classes: " + ", ".join(f"{c} {n}" for c, n in sorted(s["classes"].items())),
        "own-period: " + ", ".join(f"{c} {n}" for c, n in sorted(s["by_period"]["own"].items())),
        "other-period: " + ", ".join(f"{c} {n}" for c, n in sorted(s["by_period"]["other"].items())),
        "rerank causes: " + (", ".join(f"{c} {n}" for c, n in sorted(s["rerank_causes"].items())) or "none"),
        "uncovered: " + (", ".join(q for q, ok in s["coverage"].items() if not ok) or "none"),
    ]
    if diff is not None:
        lines.append(f"hit@5 delta: {diff['hit_at_5_delta']:+.1%}  reach delta: {diff['reach_delta']:+.1%}")
        lines.append("class deltas: " + (", ".join(f"{c} {d:+d}" for c, d in diff["class_deltas"].items()) or "none"))
        lines += [f"LOST {_part_label(k)}" for k in diff["lost"]]
        lines += [f"gained {_part_label(k)}" for k in diff["gained"]]
        lines += [f"COVERAGE LOST {q}" for q in diff["coverage_lost"]]
        lines += [f"coverage gained {q}" for q in diff["coverage_gained"]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# --propose-gold: candidate chunks for hand labelling
# ---------------------------------------------------------------------------
# A whole number as written in a filing: comma-grouped or plain, optional
# decimals, optionally in parentheses (a negative). The lookarounds stop a
# match inside a longer number.
_NUMBER = re.compile(r"(?<![\d.,])(?:\((\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\)|(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?)(?![\d])")
_UNIT_SCALE = {"million": 1e6, "billion": 1e9}
# The scales a money figure is written at: thousands tables, millions
# tables, billions in prose.
_MONEY_SCALES = (1e3, 1e6, 1e9)


def _decimals(value: float) -> int:
    """Decimal places as the question wrote the value: 72.4 -> 1, 38.0 -> 1, 20 -> 0."""
    text = str(value)
    return len(text.split(".")[1]) if "." in text else 0


def figure_matches(text: str, value: float, unit: str) -> list[re.Match]:
    """Every number in `text` that could be the expected figure, as written:
    at any money scale for million/billion, else as-is. A number matches when
    it rounds to the expected value at the expected value's own precision;
    parentheses (negatives) are compared on magnitude."""
    scale = _UNIT_SCALE.get(unit, 1.0)
    target = abs(value) * scale
    tolerance = 0.5 * 10 ** -_decimals(value) * scale + 1e-9 * target
    scales = _MONEY_SCALES if unit in _UNIT_SCALE else (1.0,)
    found = []
    for m in _NUMBER.finditer(text):
        digits = (m.group(1) or m.group(3)).replace(",", "")
        number = float(digits + (m.group(2) or m.group(4) or ""))
        if any(abs(number * s - target) <= tolerance for s in scales):
            found.append(m)
    return found


def question_parts(question: dict) -> list[tuple]:
    """(part, ticker, expected value, unit) for each figure a numeric or
    comparison question expects. A comparison part's label (MSFT-PBP) keeps
    its suffix; its ticker is the prefix. Judged questions are labelled by
    hand."""
    if question.get("type") == "numeric":
        return [("value", question["ticker"], question["expected_value"], question["expected_unit"])]
    if question.get("type") == "comparison":
        return [
            (e["ticker"], e["ticker"].split("-")[0], e["expected_value"], e["expected_unit"])
            for e in question["expected"]
        ]
    return []


def _snippet(text: str, start: int, end: int) -> str:
    pad = (_SNIPPET_CHARS - (end - start)) // 2
    lo = max(0, start - pad)
    return " ".join(text[lo : lo + _SNIPPET_CHARS].split())


def propose_gold(questions: list[dict], chunks: list[dict]) -> list[dict]:
    """One row per (question part, chunk, matching number) among the part's
    ticker's chunks, for hand review into the gold file."""
    rows = []
    for q in questions:
        for part, ticker, value, unit in question_parts(q):
            for chunk in chunks:
                meta = chunk["metadata"]
                if meta.get("ticker") != ticker:
                    continue
                text = chunk["text"]
                for m in figure_matches(text, value, unit):
                    rows.append({
                        "qid": q["id"], "part": part, "accession": meta["accessionNumber"],
                        "report_date": meta.get("reportDate"), "form": meta.get("form"),
                        "chunk_index": meta["chunk_index"], "token": m.group(0),
                        "snippet": _snippet(text, m.start(), m.end()),
                    })
    return rows


# ---------------------------------------------------------------------------
# Live measurement: the real BM25 index, Chroma collection and hybrid_search
# ---------------------------------------------------------------------------
def _load_corpus() -> list[dict]:  # pragma: no cover -- reads the real chunk files, live-only
    """The chunks BM25 indexes, which are the ones Chroma holds."""
    retrieval._load_bm25_index()
    assert retrieval._bm25_records is not None  # _load_bm25_index() always sets it
    return retrieval._bm25_records


def _vector_orderer():  # pragma: no cover -- reads every embedding from the real Chroma collection, live-only
    """A function ranking every chunk (or one ticker's) by exact cosine
    similarity to a query, embedded the way vector_search embeds it. Exact
    rather than a large-k filtered HNSW query, whose completeness is
    unverified."""
    import numpy as np

    got = retrieval._get_chroma_collection().get(include=["embeddings", "metadatas"])
    metadatas = got["metadatas"]
    assert got["embeddings"] is not None and metadatas is not None  # both requested in include=
    matrix = np.asarray(got["embeddings"], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    entries = [(retrieval._make_id(m), m["accessionNumber"], m["ticker"]) for m in metadatas]
    model = retrieval._get_embed_model()

    def order(query: str, ticker: str | None) -> list[tuple]:
        vector = model.encode(retrieval.QUERY_INSTRUCTION + query, normalize_embeddings=True)
        ranked = np.argsort(-(matrix @ vector), kind="stable")
        return [entries[i] for i in ranked if ticker is None or entries[i][2] == ticker]

    return order


def _live_retriever(corpus: list[dict], fused_floor: int | None):  # pragma: no cover -- real retrieval stack
    """A function returning one query's lists: the full BM25 and vector
    orderings (diagnostic, unscoped), then from one retrieval.search_details
    call, as run_search asks for it: the fused pool the reranker sees, the
    final top 5, the cross-encoder's order of the pool, the order before
    the table rescue, the pool's table and rescue-qualifying chunk ids, and
    the report dates the search was limited to (None when it wasn't). A
    change in retrieval is measured as is.
    fused_floor None runs retrieval's own floor."""
    vector_order = _vector_orderer()

    def retrieve(query: str, ticker: str | None) -> dict:
        bm25 = retrieval.bm25_search(query, len(corpus), ticker=ticker)
        details = retrieval.search_details(
            query, ticker=ticker, top_k=dispatch.CHUNKS_PER_SEARCH, fused_floor=fused_floor
        )
        return {
            "bm25": [(d, m["accessionNumber"], m["ticker"]) for d, _, m in bm25],
            "vector": vector_order(query, ticker),
            "pool": details["pool"],
            "final": [retrieval._make_id(r["metadata"]) for r in details["results"]],
            "ce": details["ce"],
            "combined": details["combined"],
            "scope_dates": details["scope"]["report_dates"] if details["scope"]["label"] == "dates" else None,
            "tables": details["tables"],
            "rescuable": details["rescuable"],
        }

    return retrieve


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def run_all(queries: list[dict], gold_index: dict, retrieve) -> list[dict]:
    results = []
    for i, entry in enumerate(queries, start=1):
        results.append(evaluate_query(entry, retrieve(entry["query"], entry["ticker"]), gold_index))
        if i % _PROGRESS_EVERY == 0:
            print(f"[retrieval_replay] {i}/{len(queries)}", file=sys.stderr)
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=Path(config.TRACE_LOG_PATH))
    parser.add_argument("--questions", type=Path, default=config.QUESTIONS_PATH)
    parser.add_argument("--gold", type=Path, default=GOLD_PATH)
    parser.add_argument("--qid", action="append", help="eval question ID (repeatable)")
    parser.add_argument("--out", type=Path, help="report path (default: var/retrieval_replay/replay-<UTC time>.json)")
    parser.add_argument(
        "--compare", type=Path, help="a base report; replays its queries and exits 1 on any lost hit or coverage"
    )
    parser.add_argument("--propose-gold", type=Path, help="write candidate gold chunks for hand review, then stop")
    parser.add_argument(
        "--since", type=trace_query._iso_prefix, help="only queries logged at or after this ISO UTC prefix"
    )
    parser.add_argument(
        "--fused-floor", type=int, help="fused ranks that keep the better of both ranks (default: retrieval's own)"
    )
    parser.add_argument("--no-rerank-cache", action="store_true", help="rerank every query afresh")
    return parser


def records_since(records: list[dict], since: str | None) -> list[dict]:
    """The records logged at or after the ISO prefix `since` (all when None)."""
    return records if since is None else [r for r in records if r.get("timestamp", "") >= since]


def _propose(args) -> int:
    questions = eval_harness.load_questions(args.questions)
    if args.qid:
        questions = [q for q in questions if q["id"] in args.qid]
    rows = propose_gold(questions, _load_corpus())
    args.propose_gold.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"Wrote {len(rows)} candidate rows to {args.propose_gold}")
    return 0


def _query_set(args, base: dict | None, gold_index: dict) -> tuple[list[dict], dict]:
    if base is not None:
        return queries_from_report(base), base["header"]["dropped"]
    records, malformed = trace_query.load(args.file)
    # Question ids come from every record: a run whose agent span was logged
    # before --since still owns the searches it logged after it.
    ids = trace_query.question_ids(records, args.questions)
    queries, dropped = build_query_set(records_since(records, args.since), ids, {qid for qid, _ in gold_index})
    return filter_qids(queries, args.qid), {**dropped, "malformed_lines": malformed}


def _query_source(args, base: dict | None, gold_index: dict, queries: list[dict]) -> dict:
    """Where the query set came from. A compare run replays the base's
    queries, so it inherits the base's description of them."""
    if base is not None:
        return {k: base["header"][k] for k in ("trace_file", "qids", "gold_questions_without_queries")}
    queried = {qid for q in queries for qid in q["qids"]}
    without = sorted({qid for qid, _ in gold_index} - queried) if not args.qid else []
    return {"trace_file": str(args.file), "qids": args.qid, "gold_questions_without_queries": without}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.compare and (args.qid or args.since):
        parser.error("--compare replays the base report's queries; drop --qid and --since")
    if args.propose_gold:
        return _propose(args)
    started = time.monotonic()
    stamp = datetime.now(timezone.utc)
    out = args.out or config.VAR_DIR / "retrieval_replay" / f"replay-{stamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    if args.out is None:
        out.parent.mkdir(parents=True, exist_ok=True)
    # Checked up front: a full run takes many minutes, and its results would
    # be lost if the write failed at the end.
    if not out.parent.is_dir():
        parser.error(f"--out directory does not exist: {out.parent}")

    # Captured before the run: an edit to retrieval or a commit while a
    # long run is in progress must not be attributed to its results. Period
    # scoping also reads the fiscal-period labels and companies' fiscal
    # year ends, so those files count as retrieval too.
    retrieval_files = [*sorted(Path(retrieval.__file__).parent.glob("*.py")), Path(period_labels.__file__),
                       companies.COMPANIES_PATH]
    provenance = {
        **eval_harness._git_state(),
        "retrieval_sha256": {p.name: file_sha256(p) for p in retrieval_files},
    }
    try:
        gold_hash = file_sha256(args.gold)
        gold_rows = load_gold(args.gold)
        base = json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
        if base is not None:
            check_base(base, gold_hash)
    except (OSError, ValueError) as e:  # json.JSONDecodeError is a ValueError
        print(f"retrieval_replay: {e}", file=sys.stderr)
        return 2
    unknown = sorted(set(args.qid or ()) - {row["qid"] for row in gold_rows})
    if unknown:
        parser.error(f"--qid has no gold rows: {', '.join(unknown)}")
    corpus = _load_corpus()
    gold_index, unmatched = index_gold(corpus, gold_rows)
    if unmatched:
        for row in unmatched:
            print(f"retrieval_replay: gold row matches no chunk: {json.dumps(row)}", file=sys.stderr)
        return 2
    queries, dropped = _query_set(args, base, gold_index)
    reranker = rerank_cache.install(not args.no_rerank_cache)
    # Retrieval logs an event per search; a run's ~900 would land in the
    # trace log this tool reads its queries from.
    write_local_log = tracing._write_local_log
    tracing._write_local_log = lambda record: None
    try:
        results = run_all(queries, gold_index, _live_retriever(corpus, args.fused_floor))
    finally:
        tracing._write_local_log = write_local_log

    summary = summarize(results)
    diff = compare(base["results"], results) if base is not None else None
    header = {
        "created": stamp.isoformat(),
        **provenance,
        "gold_sha256": gold_hash,
        **_query_source(args, base, gold_index, queries),
        "baseline": str(args.compare) if args.compare else None,
        "since": args.since,
        "fused_floor": retrieval._FUSED_FLOOR_RANKS if args.fused_floor is None else args.fused_floor,
        "dropped": dropped,
        "runtime_s": round(time.monotonic() - started, 1),
        "rerank_cache": rerank_cache.stats(reranker),
    }
    report = {"header": header, "summary": summary, "diff": diff, "queries": queries, "results": results}
    print(format_summary(summary, diff))
    print(rerank_cache.summary_line(header["rerank_cache"]))
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"Wrote {out}")
    return 1 if diff is not None and compare_failed(diff) else 0


if __name__ == "__main__":
    sys.exit(main())
