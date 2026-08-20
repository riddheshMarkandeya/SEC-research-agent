"""
SPIKE — same agent, cloud model (Gemini) instead of local Ollama
------------------------------------------------------------------
Throwaway, not production code: tests whether qwen2.5:7b-instruct's
capability is the bottleneck behind the recurring citation-
misattribution and comparison-question flakiness documented in
PROJECT_CONTEXT.md, by running the exact same system prompt, tool
schemas, and tool-dispatch logic (all imported from agent.py, not
copied) against Gemini instead of Ollama. If this proves worthwhile, a
real integration would need a proper swappable-backend design, not
this script -- some duplication of run_eval()'s body below is accepted
for that reason, not an oversight.

Setup: GEMINI_API_KEY in .env (free tier via aistudio.google.com, no
credit card). pip install google-genai (not added to requirements.txt
-- spike-only dependency).

Usage:
    python spike_gemini_eval.py "question" [--verbose]
    python spike_gemini_eval.py --eval
"""

import argparse
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from agent import (
    CHUNKS_PER_SEARCH,
    COMPARE_TOOL_SCHEMA,
    FACT_TOOL_SCHEMA,
    SEARCH_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    _call_compare_financial_metric,
    _call_get_financial_fact,
    _comparison_as_results,
    _fact_as_result,
    _format_citation_key,
    _format_results_block,
    _resolve_search_args,
    verify_citations,
)
from retrieval import hybrid_search

GEMINI_MODEL = "gemini-flash-lite-latest"
MAX_TOOL_ITERATIONS = 6
RETRY_DELAY_SECONDS = 15  # free-tier rate limits are generous but not infinite

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def _to_gemini_tool(schema: dict) -> types.FunctionDeclaration:
    """agent.py's tool schemas are already plain, lowercase JSON-schema
    dicts (OpenAI/Ollama wire-format style) -- verified live that
    Gemini's SDK accepts that shape directly for `parameters`, so this
    just unwraps the {"function": {...}} envelope rather than
    re-describing each tool a second time in a different format."""
    fn = schema["function"]
    return types.FunctionDeclaration(name=fn["name"], description=fn["description"], parameters=fn["parameters"])


_TOOLS = types.Tool(
    function_declarations=[_to_gemini_tool(s) for s in (FACT_TOOL_SCHEMA, COMPARE_TOOL_SCHEMA, SEARCH_TOOL_SCHEMA)]
)


def _send_with_retry(chat, message):
    """Retries on transient errors -- free-tier rate limits (429) and,
    found live on the first real run, plain server overload (503,
    "experiencing high demand") -- with a short linear backoff. Not
    worth a fuller backoff strategy for a throwaway spike."""
    for attempt in range(4):
        try:
            return chat.send_message(message)
        except (genai_errors.ClientError, genai_errors.ServerError) as e:
            code = getattr(e, "code", None)
            if code not in (429, 503) or attempt == 3:
                raise
            time.sleep(RETRY_DELAY_SECONDS * (attempt + 1))


def run_agent_gemini(question: str, verbose: bool = False) -> tuple[str, list[dict], list[str]]:
    """Gemini counterpart to agent.py's run_agent() -- same tool-dispatch
    branches (reused directly, not reimplemented), same
    MAX_TOOL_ITERATIONS budget, same citation-verification return
    value. Differs only in the wire format: Gemini's chat session
    handles multi-turn tool-call bookkeeping (including its
    thought_signature continuity) internally, so this doesn't manage a
    `messages` list by hand the way agent.py's Ollama loop does."""
    chat = _client.chats.create(
        model=GEMINI_MODEL,
        config=types.GenerateContentConfig(tools=[_TOOLS], system_instruction=SYSTEM_PROMPT, temperature=0.1),
    )
    all_results: list[dict] = []
    searched_tickers: set[str | None] = set()

    message = question
    for _ in range(MAX_TOOL_ITERATIONS):
        resp = _send_with_retry(chat, message)
        parts = resp.candidates[0].content.parts or []
        function_calls = [p.function_call for p in parts if p.function_call]

        if not function_calls:
            answer = resp.text or ""
            return answer, all_results, verify_citations(answer, all_results)

        function_response_parts = []
        for fc in function_calls:
            name = fc.name
            args = dict(fc.args or {})

            if name == "get_financial_fact":
                if verbose:
                    print(f"  [tool call] get_financial_fact({args!r})")
                fact = _call_get_financial_fact(args)
                if fact is None:
                    content = (
                        f"(no structured data found for metric={args.get('metric')!r} "
                        f"ticker={args.get('ticker')!r} -- try search_filings instead)"
                    )
                else:
                    start_index = len(all_results) + 1
                    result = _fact_as_result(fact, args)
                    all_results.append(result)
                    content = _format_results_block([result], start_index)

            elif name == "compare_financial_metric":
                if verbose:
                    print(f"  [tool call] compare_financial_metric({args!r})")
                data = _call_compare_financial_metric(args)
                if not data:
                    content = (
                        f"(no structured data found for metric={args.get('metric')!r} "
                        "across companies for this period -- try search_filings per company instead)"
                    )
                else:
                    start_index = len(all_results) + 1
                    results = _comparison_as_results(data, args.get("metric", ""))
                    all_results.extend(results)
                    content = _format_results_block(results, start_index)

            else:  # search_filings
                query, ticker = _resolve_search_args(args, fallback_query=question, searched_tickers=searched_tickers)
                searched_tickers.add(ticker)
                if verbose:
                    print(f"  [tool call] search_filings(query={query!r}, ticker={ticker!r})")
                results = hybrid_search(query, ticker=ticker, top_k=CHUNKS_PER_SEARCH)
                start_index = len(all_results) + 1
                all_results.extend(results)
                content = _format_results_block(results, start_index)

            function_response_parts.append(types.Part.from_function_response(name=name, response={"result": content}))

        message = function_response_parts

    return (
        "I wasn't able to finish answering within the allotted number of searches. "
        "Try asking a more specific or narrower question.",
        all_results,
        [],
    )


def run_eval_gemini(questions_path):
    """Mirrors eval_harness.py's run_eval()/print_summary(), swapping
    only run_agent -> run_agent_gemini -- grading (including the
    judge, which stays on local Ollama) is unchanged, so the only
    variable being tested is which model answers the question."""
    from eval_harness import CITATION_PATTERN, grade_comparison, grade_judged, grade_numeric, load_questions

    questions = load_questions(questions_path)
    results = []

    for q in questions:
        print(f"[{q['id']}] {q['question']}")
        answer_text, retrieved, citation_warnings = run_agent_gemini(q["question"])
        has_citation = bool(CITATION_PATTERN.search(answer_text))

        if q["type"] == "numeric":
            passed, detail = grade_numeric(answer_text, q["expected_value"], q["expected_unit"], retrieved)
        elif q["type"] == "comparison":
            passed, detail = grade_comparison(answer_text, q["expected"], retrieved)
        elif q["type"] == "judged":
            passed, detail = grade_judged(q["question"], answer_text, q["criteria"])
        else:
            raise ValueError(f"Unknown question type: {q['type']!r} in question {q['id']!r}")

        status = "PASS" if passed else "FAIL"
        print(f"  -> {status} ({detail})")
        if not has_citation:
            print("  -> WARNING: answer has no [n] citation marker at all")
        for w in citation_warnings:
            print(f"  -> CITATION WARNING: {w}")

        results.append(
            {
                "id": q["id"],
                "type": q["type"],
                "passed": passed,
                "detail": detail,
                "has_citation": has_citation,
                "citation_warnings": citation_warnings,
                "answer": answer_text,
            }
        )
        time.sleep(2)  # stay comfortably under free-tier RPM

    total = len(results)
    passed = sum(r["passed"] for r in results)
    cited = sum(r["has_citation"] for r in results)
    print(f"\n{'=' * 60}")
    print(f"Results ({GEMINI_MODEL}): {passed}/{total} passed, {cited}/{total} included a citation marker")
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] {r['id']} ({r['type']})")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", help="single question to ask")
    parser.add_argument("--eval", action="store_true", help="run the full eval_questions.jsonl set")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.eval:
        run_eval_gemini(Path("eval_questions.jsonl"))
        return

    if not args.question:
        parser.error("provide a question, or pass --eval")

    answer, results, warnings = run_agent_gemini(args.question, verbose=args.verbose)
    print(f"\nQ: {args.question}\n")
    print(answer)
    if results:
        print("\nSources:")
        print(_format_citation_key(results))
    if warnings:
        print("\nCitation warnings:")
        for w in warnings:
            print(f"  {w}")


if __name__ == "__main__":
    main()
