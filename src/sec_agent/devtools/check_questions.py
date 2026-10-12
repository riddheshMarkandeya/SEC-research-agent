"""
The authoring check a batch of eval questions passes before the user
reviews it. Offline except one cached SEC call (companyfacts, for the
XBRL cross-check); it spends no Gemini quota. It reads the chunk files,
not the index.

Per question it checks that:
  1. every gold figure has a verbatim anchor, found in its own company's
     chunk files and showing the figure;
  2. every derived value recomputes, with the `calculate` tool's own
     arithmetic, to the expected value, and that rounding in the inputs
     stays inside the grading band (or the question's tolerance);
  3. each anchored figure is cross-checked against the company's XBRL
     facts from the same filing (INFO only: a match names the tag);
  4. a never-disclosed refusal's absence terms appear nowhere in the
     company's chunks;
  5. a question with something to grade names covered companies only;
  6. a multi-company question's non-ticker entries list their companies;
  7. no trap value sits in a gold chunk beside the answer (WARN);
  8. no id repeats one from the v1 file.

Authoring checklist:
  - Draft from the chunk files and the filings, never through the
    agent's tools.
  - Give each figure gold rows with a short verbatim anchor.
  - Pick trap values that a correct answer has no reason to state and
    cite. Not the comparative column printed beside the answer: a claim
    that states the trap value for the asked company fails the answer.
  - On a multi-company question, list `companies` on each non-ticker
    entry.
  - Record a `derivation` for every derived value, with its inputs
    anchored. Write each input as the filing prints it (1.2 billion, not
    1200 million): its last digit sets the rounding spread.
  - Give an absence term in its shortest form, and list spelling
    variants the search can't equate (noninterest, non-interest).
  - Record `absence_terms` for every never-disclosed refusal.
  - Set a `tolerance` only when this script reports a spread that needs
    one, and record that spread in `tolerance_note`.
  - The batch passes this script before the user reviews it.

Exit status: 0 with no errors, 1 on any error, 2 on a usage or read
failure.

Usage (from a worktree, PYTHONPATH=src so the worktree's code runs):
  python -m sec_agent.devtools.check_questions --questions eval/eval_questions_v2.jsonl
  python -m sec_agent.devtools.check_questions --questions FILE --ids a,b --chunks-dir DIR --xbrl-cache-dir DIR
"""

import argparse
import math
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import partial
from itertools import product
from pathlib import Path

import requests

from sec_agent import config
from sec_agent.agent.calculate import _apply_calculate_operation
from sec_agent.devtools.discover_tags import fetch_company_facts
from sec_agent.devtools.retrieval_replay import GOLD_PATH, _decimals, figure_matches, gold_matches, load_gold
from sec_agent.eval.eval_harness import load_questions
from sec_agent.eval.grading import entry_companies, text_matches, value_matcher
from sec_agent.eval.questions import question_tickers, single_ticker
from sec_agent.retrieval.index_chunks import CHUNK_FILE_GLOB, load_chunks
from sec_agent.sources.companies import COMPANIES
from sec_agent.verification.numeric_utils import UNIT_MULTIPLIERS, match_tolerance, normalize, normalize_for_match

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"
# A company's XBRL facts by filing accession: (taxonomy, tag, unit, entry).
FactIndex = dict[str, list[tuple[str, str, str, dict]]]


@dataclass(frozen=True)
class Finding:
    level: str
    message: str


@dataclass(frozen=True)
class Part:
    """One figure a question's gold rows anchor: a value and unit, or for
    a text question its accepted variants."""

    name: str
    companies: frozenset[str]
    value: float | None = None
    unit: str | None = None
    accepted: tuple[str, ...] = ()

    def describe(self) -> str:
        return " / ".join(self.accepted) if self.accepted else f"{self.value:g} {self.unit}"


@dataclass
class Context:
    """What the checks read: the corpus chunks, every gold row, a
    companyfacts fetch by ticker, and the ids the other question file uses."""

    chunks: list[dict]
    gold: list[dict]
    fetch_facts: Callable[[str], dict]
    other_ids: frozenset[str] = frozenset()
    by_accession: dict[str, list[dict]] = field(init=False, default_factory=dict)
    gold_by_qid: dict[str, list[dict]] = field(init=False, default_factory=dict)
    _matched: dict[int, list[dict]] = field(init=False, default_factory=dict)
    _facts: dict[str, FactIndex | str] = field(init=False, default_factory=dict)
    _folded: dict[int, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        for chunk in self.chunks:
            self.by_accession.setdefault(chunk["metadata"]["accessionNumber"], []).append(chunk)
        for row in self.gold:
            self.gold_by_qid.setdefault(row["qid"], []).append(row)

    def matched_chunks(self, row: dict) -> list[dict]:
        """The chunks of the row's filing that hold its anchor."""
        if id(row) not in self._matched:
            candidates = self.by_accession.get(row["accession"], [])
            self._matched[id(row)] = [c for c in candidates if gold_matches(c["text"], c["metadata"], [row])]
        return self._matched[id(row)]

    def folded(self, chunk: dict) -> str:
        """The chunk's text lower-cased with whitespace collapsed, for the
        absence search."""
        if id(chunk) not in self._folded:
            self._folded[id(chunk)] = _fold(chunk["text"])
        return self._folded[id(chunk)]

    def facts(self, ticker: str) -> FactIndex | str:
        """The ticker's companyfacts by filing accession, or why they
        couldn't be read. Fetched once per run, failures included, so a dead
        network costs one timeout per ticker rather than one per question."""
        if ticker not in self._facts:
            try:
                self._facts[ticker] = _index_facts(self.fetch_facts(ticker))
            except (requests.RequestException, OSError, ValueError) as e:
                self._facts[ticker] = str(e)
        return self._facts[ticker]


# ---------------------------------------------------------------------------
# Gold parts
# ---------------------------------------------------------------------------
def _anchored_inputs(derivation: dict) -> list[dict]:
    """A derivation's inputs that carry a `part`, at any depth."""
    inputs = []
    for side in (derivation["a"], derivation["b"]):
        if "derivation" in side:
            inputs += _anchored_inputs(side["derivation"])
        elif "part" in side:
            inputs.append(side)
    return inputs


def _figure_parts(name: str, figure: dict, companies: frozenset[str]) -> list[Part]:
    """An expected figure's own part, or its inputs' when it's derived: a
    derived value is often printed nowhere."""
    if "derivation" in figure:
        return [Part(i["part"], companies, i["value"], i["unit"]) for i in _anchored_inputs(figure["derivation"])]
    return [Part(name, companies, figure["expected_value"], figure["expected_unit"])]


def _part_list(question: dict) -> list[Part] | None:
    """Every part the question's figures need, a name possibly repeated.
    None for a judged question, whose parts are labelled by hand."""
    tickers = question_tickers(question)
    qtype = question["type"]
    if qtype == "judged":
        return None
    parts: list[Part] = []
    if qtype == "numeric":
        parts = _figure_parts("value", question, frozenset(tickers))
    elif qtype == "comparison":
        for entry in question["expected"]:
            companies = frozenset(entry_companies(entry, tickers))
            parts += _figure_parts(entry["ticker"], entry, companies)
    elif qtype == "text":
        parts = [Part("value", frozenset(tickers), accepted=tuple(question["accepted"]))]
    return parts


def _part_clashes(parts: list[Part]) -> list[Finding]:
    """A part name given to two different figures, or to one figure of
    different companies: only one of them would ever be checked."""
    first: dict[str, Part] = {}
    findings = []
    for part in parts:
        seen = first.setdefault(part.name, part)
        if seen == part:
            continue
        if seen.describe() != part.describe():
            clash = f"names two figures: {seen.describe()} and {part.describe()}"
        else:
            clash = f"is used for {'/'.join(sorted(seen.companies))} and {'/'.join(sorted(part.companies))}"
        findings.append(Finding(ERROR, f"part {part.name!r} {clash}"))
    return findings


# ---------------------------------------------------------------------------
# 1. Anchors
# ---------------------------------------------------------------------------
def _anchor_shows(part: Part, anchor: str) -> bool:
    if part.accepted:
        return text_matches(anchor, list(part.accepted))
    assert part.value is not None and part.unit is not None
    return bool(figure_matches(anchor, part.value, part.unit))


def _check_part(part: Part, rows: list[dict], ctx: Context) -> list[Finding]:
    if not rows:
        return [Finding(ERROR, f"part {part.name!r}: no gold rows")]
    findings = []
    for row in rows:
        for ticker in sorted({c["metadata"]["ticker"] for c in ctx.matched_chunks(row)} - part.companies):
            owners = ", ".join(sorted(part.companies))
            findings.append(Finding(ERROR, f"gold row {part.name!r} ({row['accession']}): its chunk is {ticker}'s, "
                                           f"not {owners}'s"))
    if not any(_anchor_shows(part, row["anchor"]) for row in rows):
        findings.append(Finding(ERROR, f"part {part.name!r}: no anchor shows {part.describe()}"))
    return findings


def check_anchors(question: dict, ctx: Context) -> list[Finding]:
    """Every gold row is found in a chunk of its filing; each gold part
    has rows, in its own companies' filings, one of whose anchors shows
    the figure; and no row names a part the question doesn't have."""
    rows = ctx.gold_by_qid.get(question["id"], [])
    findings = [
        Finding(ERROR, f"gold row {row['part']!r} ({row['accession']}): anchor {row['anchor']!r} "
                       "is in no chunk of its filing")
        for row in rows
        if not ctx.matched_chunks(row)
    ]
    part_list = _part_list(question)
    if part_list is None:
        return findings
    findings += _part_clashes(part_list)
    parts = {p.name: p for p in part_list}
    for name in sorted({row["part"] for row in rows} - parts.keys()):
        findings.append(Finding(ERROR, f"gold row part {name!r} is not one of this question's parts "
                                       f"({', '.join(sorted(parts))})"))
    for part in parts.values():
        findings += _check_part(part, [row for row in rows if row["part"] == part.name], ctx)
    return findings


# ---------------------------------------------------------------------------
# 2. Derivations
# ---------------------------------------------------------------------------
class DerivationError(ValueError):
    """A step the `calculate` tool would refuse."""


_DIVISOR_OPERATIONS = ("divide", "percent_of", "percent_change")
_EXACT_OPERATIONS: dict[str, Callable[[float, float], float]] = {
    "add": lambda a, b: a + b,
    "subtract": lambda a, b: a - b,
    "multiply": lambda a, b: a * b,
    "divide": lambda a, b: a / b,
    "percent_of": lambda a, b: a / b * 100,
    "percent_change": lambda a, b: (a - b) / b * 100,
}


def _compute(derivation: dict, shifts: dict[int, float], rounded: bool) -> tuple[str, float]:
    """A derivation's normalized result. `rounded` uses the tool's own
    arithmetic and rounding; otherwise the result is exact, with each
    input shifted by shifts[id(input)]."""
    sides = []
    for side in (derivation["a"], derivation["b"]):
        if "derivation" in side:
            sides.append(_compute(side["derivation"], shifts, rounded))
        else:
            sides.append(normalize(side["value"] + shifts.get(id(side), 0.0), side["unit"]))
    (category_a, norm_a), (category_b, norm_b) = sides
    operation = derivation["operation"]
    # The guards call_calculate applies before its arithmetic.
    if category_a != category_b:
        raise DerivationError(f"{operation} mixes a {category_a} and a {category_b} operand, which calculate refuses")
    if operation in _DIVISOR_OPERATIONS and norm_b == 0:
        raise DerivationError(f"{operation} by zero, which calculate refuses")
    value, unit = _apply_calculate_operation(operation, category_a, norm_a, norm_b)
    if not rounded:
        value = _EXACT_OPERATIONS[operation](norm_a, norm_b)
    return normalize(value, unit)


def rounding_spread(derivation: dict) -> float:
    """Half the width of the range the exact result spans when each
    anchored input is anywhere within half a unit of its printed last
    digit; constants are exact. Infinite when a corner divides by zero."""
    inputs = _anchored_inputs(derivation)
    results = []
    for signs in product((-1, 1), repeat=len(inputs)):
        shifts = {id(i): sign * 0.5 * 10 ** -_decimals(i["value"]) for i, sign in zip(inputs, signs)}
        try:
            results.append(_compute(derivation, shifts, rounded=False)[1])
        except DerivationError:
            return math.inf
    return (max(results) - min(results)) / 2


def _in_unit(norm: float, unit: str) -> float:
    return norm if unit == "percent" else norm / UNIT_MULTIPLIERS.get(unit, 1.0)


def _derived_figures(question: dict) -> list[tuple[str, dict]]:
    """(label, figure) for every expected figure with a derivation."""
    figures = [("derivation", question)] if "derivation" in question else []
    return figures + [
        (f"expected {entry['ticker']!r} derivation", entry)
        for entry in question.get("expected", [])
        if "derivation" in entry
    ]


def _check_spread(where: str, spread: float, figure: dict, tolerance: float | None) -> list[Finding]:
    unit = figure["expected_unit"]
    expected_norm = normalize(figure["expected_value"], unit)[1]
    default_band = match_tolerance(expected_norm)
    band = match_tolerance(expected_norm, tolerance)
    shown = f"+/-{_in_unit(spread, unit):.3g} {unit}"
    relative = f"{spread / abs(expected_norm):.2%} of expected" if expected_norm else "expected is zero"
    findings = [Finding(INFO, f"{where}: rounding spread {shown} ({relative}); "
                              f"default band +/-{_in_unit(default_band, unit):.3g}")]
    if spread > band and tolerance is None:
        findings.append(Finding(ERROR, f"{where}: needs a tolerance (spread {shown}, {relative})"))
    elif spread > band:
        findings.append(Finding(ERROR, f"{where}: spread {shown} exceeds the tolerance {tolerance:g} "
                                       f"(band +/-{_in_unit(band, unit):.3g})"))
    return findings


def _check_derivation(where: str, figure: dict, tolerance: float | None) -> tuple[list[Finding], bool | None]:
    """One derivation's findings, and whether its spread fits the default
    band (None when the spread couldn't be assessed)."""
    findings = []
    if not _anchored_inputs(figure["derivation"]):
        findings.append(Finding(ERROR, f"{where}: no input is anchored, so nothing ties it to a filing"))
    try:
        category, result = _compute(figure["derivation"], {}, rounded=True)
    except DerivationError as e:
        return [*findings, Finding(ERROR, f"{where}: {e}")], None
    unit = figure["expected_unit"]
    expected_category, expected_norm = normalize(figure["expected_value"], unit)
    # A normalized result is in raw units unless it's a percentage.
    result_unit = "percent" if category == "percent" else "raw"
    if not value_matcher(figure["expected_value"], unit, tolerance)(result, result_unit):
        shown = f"{_in_unit(result, unit):g} {unit}" if category == expected_category else f"{result:g} {category}"
        findings.append(Finding(ERROR, f"{where}: recomputes to {shown}, outside the grading band of the "
                                       f"expected {figure['expected_value']:g} {unit}"))
    if category != expected_category:
        return findings, None  # a spread in another unit than the band's means nothing
    spread = rounding_spread(figure["derivation"])
    return findings + _check_spread(where, spread, figure, tolerance), spread <= match_tolerance(expected_norm)


def check_derivations(question: dict, ctx: Context) -> list[Finding]:
    """Each derivation recomputes, as the tool would, to within the
    grading band of its expected value, and its inputs' rounding spread
    fits the band the question grades with."""
    tolerance = question.get("tolerance")
    findings: list[Finding] = []
    fits: list[bool | None] = []
    for where, figure in _derived_figures(question):
        figure_findings, fits_default = _check_derivation(where, figure, tolerance)
        findings += figure_findings
        fits.append(fits_default)
    if tolerance is not None and fits and all(fit is True for fit in fits):
        findings.append(Finding(WARN, f"tolerance {tolerance:g} is unneeded: the default band covers every "
                                      "derivation's spread"))
    return findings


# ---------------------------------------------------------------------------
# 3. XBRL cross-check
# ---------------------------------------------------------------------------
_MAX_XBRL_MATCHES = 5


def _iter_facts(facts: dict) -> Iterator[tuple[str, str, str, dict]]:
    """(taxonomy, tag, unit, entry) for every fact in a companyfacts payload."""
    for taxonomy, tags in facts.get("facts", {}).items():
        for tag, data in tags.items():
            for unit, entries in data.get("units", {}).items():
                for entry in entries:
                    yield taxonomy, tag, unit, entry


def _index_facts(facts: dict) -> FactIndex:
    """(taxonomy, tag, unit, entry) by accession: a part looks only at its
    own filings' facts, a small share of a company's."""
    index: FactIndex = {}
    for fact in _iter_facts(facts):
        index.setdefault(fact[3].get("accn", ""), []).append(fact)
    return index


def _xbrl_matches(part: Part, accessions: set[str], facts: FactIndex) -> list[str]:
    """The facts from the part's filings whose value is the part's figure
    at its printed precision, described for the author to check by eye."""
    assert part.value is not None and part.unit is not None
    target = abs(normalize(part.value, part.unit)[1])
    # Half a unit of the last printed digit, plus a float-error allowance.
    precision = 0.5 * 10 ** -_decimals(part.value) * UNIT_MULTIPLIERS.get(part.unit, 1.0) + 1e-9 * target
    found = set()
    for taxonomy, tag, unit, entry in (fact for accession in accessions for fact in facts.get(accession, [])):
        if abs(abs(entry["val"]) - target) <= precision:
            period = f"{entry['start']}..{entry['end']}" if "start" in entry else entry["end"]
            found.add(f"{taxonomy}:{tag} = {entry['val']} {unit} ({period}, {entry.get('form', '?')})")
    return sorted(found)


def check_xbrl(question: dict, ctx: Context) -> list[Finding]:
    """For each anchored figure other than a percentage, the XBRL facts of
    its anchors' filings with the same value. Information only: a 10-K
    holds hundreds of facts, so a match can be unrelated."""
    rows = ctx.gold_by_qid.get(question["id"], [])
    findings: list[Finding] = []
    failures: set[str] = set()
    for part in {p.name: p for p in _part_list(question) or []}.values():
        if part.accepted or part.unit == "percent":
            continue
        part_rows = [row for row in rows if row["part"] == part.name]
        accessions = {row["accession"] for row in part_rows}
        matches, searched = [], False
        for ticker in sorted({c["metadata"]["ticker"] for row in part_rows for c in ctx.matched_chunks(row)}):
            facts = ctx.facts(ticker)
            if isinstance(facts, str):
                failures.add(f"XBRL cross-check skipped for {ticker}: {facts}")
                continue
            searched = True
            matches += _xbrl_matches(part, accessions, facts)
        if matches:
            more = f" (+{len(matches) - _MAX_XBRL_MATCHES} more)" if len(matches) > _MAX_XBRL_MATCHES else ""
            findings.append(Finding(INFO, f"part {part.name!r}: XBRL {'; '.join(matches[:_MAX_XBRL_MATCHES])}{more}"))
        elif searched:
            findings.append(Finding(INFO, f"part {part.name!r}: no XBRL fact matched (text-only or untagged)"))
    return findings + [Finding(WARN, message) for message in sorted(failures)]


# ---------------------------------------------------------------------------
# 4. Absence
# ---------------------------------------------------------------------------
_SNIPPET_CONTEXT = 60


def _fold(text: str) -> str:
    """Lower-cased words, with every run of punctuation or whitespace one
    space: a term and the filing's text may differ in hyphens, quotes or
    spacing, and a missed variant would pass as absent."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", normalize_for_match(text)).split())


def _snippet(folded: str, needle: str) -> str:
    at = folded.index(needle)
    return folded[max(0, at - _SNIPPET_CONTEXT):at + len(needle) + _SNIPPET_CONTEXT]


def check_absence(question: dict, ctx: Context) -> list[Finding]:
    """Each absence term appears in none of the question's companies'
    chunks, across all their filings (case-insensitive; punctuation and
    whitespace ignored). There is no override: a hit means the term is
    wrong or the value is disclosed after all."""
    if "absence_terms" not in question:
        return []
    tickers = question_tickers(question)
    own = [c for c in ctx.chunks if c["metadata"]["ticker"] in tickers]
    if not own:
        return [Finding(ERROR, f"absence: no chunks for {', '.join(tickers)}, so nothing was searched")]
    names = "/".join(tickers)
    filings = len({c["metadata"]["accessionNumber"] for c in own})
    findings = []
    for term in question["absence_terms"]:
        needle = _fold(term)
        hits = [c for c in own if needle in ctx.folded(c)]
        if hits:
            first = hits[0]
            where = f"{first['metadata']['accessionNumber']}#{first['metadata']['chunk_index']}"
            findings.append(Finding(ERROR, f"absence term {term!r}: found in {len(hits)} {names} chunks, e.g. "
                                           f"{where}: {ascii(_snippet(ctx.folded(first), needle))}"))
        else:
            others = sum(needle in ctx.folded(c) for c in ctx.chunks if c["metadata"]["ticker"] not in tickers)
            findings.append(Finding(INFO, f"absence term {term!r}: in none of {len(own)} {names} chunks "
                                          f"({filings} filings); {others} hits in other companies' chunks"))
    return findings


# ---------------------------------------------------------------------------
# 5-8. Tickers, entry companies, traps beside the answer, id collisions
# ---------------------------------------------------------------------------
_GRADED_FIELDS = ("expected", "expected_value", "accepted", "forbidden_values")


def check_tickers(question: dict, ctx: Context) -> list[Finding]:
    """A question with something to grade asks about covered companies
    only. A refusal may name an uncovered one: that's its point."""
    if not any(key in question for key in _GRADED_FIELDS):
        return []
    return [
        Finding(ERROR, f"ticker {ticker} is not in companies.json, so no filing can ground its answer")
        for ticker in question_tickers(question)
        if ticker not in COMPANIES
    ]


def check_entry_companies(question: dict, ctx: Context) -> list[Finding]:
    """On a multi-company question, an entry labelled other than by a
    ticker lists its companies. Without the list it's charged to all of
    them, which is wrong for a per-company figure."""
    tickers = question_tickers(question)
    if len(tickers) <= 1:
        return []
    return [
        Finding(ERROR, f"expected {entry['ticker']!r}: its label isn't a ticker and it lists no companies, "
                       f"so a claim of it must cite all of {', '.join(tickers)}")
        for entry in question.get("expected", [])
        if entry["ticker"] not in COMPANIES and "companies" not in entry
    ]


def check_traps_beside_answer(question: dict, ctx: Context) -> list[Finding]:
    """A trap value printed in a chunk holding a gold anchor is a figure a
    correct answer may well state for context, and stating it fails. Only
    the trap's own company's chunks count: a value claimed from another
    company's source is no hit."""
    gold_chunks = [c for row in ctx.gold_by_qid.get(question["id"], []) for c in ctx.matched_chunks(row)]
    findings = []
    for trap in question.get("forbidden_values", []):
        company = trap.get("ticker", single_ticker(question))
        beside = next((c for c in gold_chunks if c["metadata"]["ticker"] == company
                       and figure_matches(c["text"], trap["value"], trap["unit"])), None)
        if beside is not None:
            where = f"{beside['metadata']['accessionNumber']}#{beside['metadata']['chunk_index']}"
            findings.append(Finding(WARN, f"trap {trap['value']:g} {trap['unit']} is printed in gold chunk {where}: "
                                          "a correct answer may state it for context and fail"))
    return findings


def check_id_collision(question: dict, ctx: Context) -> list[Finding]:
    """Gold rows are keyed by question id and shared between the files, so
    an id may not repeat one from the v1 file."""
    if question["id"] in ctx.other_ids:
        return [Finding(ERROR, f"id {question['id']!r} is already used in the v1 question file, "
                               "and gold rows are keyed by id")]
    return []


CHECKS: tuple[Callable[[dict, Context], list[Finding]], ...] = (
    check_anchors, check_derivations, check_xbrl, check_absence,
    check_tickers, check_entry_companies, check_traps_beside_answer, check_id_collision,
)


def check_question(question: dict, ctx: Context) -> list[Finding]:
    return [finding for check in CHECKS for finding in check(question, ctx)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", type=Path, required=True, help="the question file to check")
    parser.add_argument("--ids", help="comma-separated question ids to check (default: all)")
    parser.add_argument("--gold", type=Path, default=GOLD_PATH, help="the gold row file")
    parser.add_argument("--chunks-dir", type=Path, default=config.CHUNKS_DIR, help="the chunk files' directory")
    parser.add_argument("--xbrl-cache-dir", type=Path, default=config.XBRL_CACHE_DIR,
                        help="where companyfacts are cached (fetched from SEC when missing)")
    return parser


def _select(questions: list[dict], ids: str | None) -> list[dict]:
    if not ids:
        return questions
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    unknown = sorted(set(wanted) - {q["id"] for q in questions})
    if unknown:
        raise ValueError(f"unknown question id {', '.join(unknown)}")
    return [q for q in questions if q["id"] in wanted]


def _other_ids(questions_path: Path) -> frozenset[str]:
    """The v1 file's ids, when the file being checked is another one."""
    if questions_path.resolve() == config.QUESTIONS_PATH.resolve():
        return frozenset()
    return frozenset(q["id"] for q in load_questions(config.QUESTIONS_PATH))


def _report(questions: list[dict], ctx: Context) -> int:
    counts = {ERROR: 0, WARN: 0, INFO: 0}
    for question in questions:
        for finding in check_question(question, ctx):
            counts[finding.level] += 1
            print(f"{finding.level:<5} {question['id']}: {finding.message}")
    print(f"\n{len(questions)} questions checked: {counts[ERROR]} errors, {counts[WARN]} warnings")
    return 1 if counts[ERROR] else 0


def main(argv: list[str] | None = None, fetch_facts: Callable[[str], dict] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        questions = _select(load_questions(args.questions), args.ids)
        other_ids = _other_ids(args.questions)
        gold = load_gold(args.gold)
        chunk_files = sorted(args.chunks_dir.glob(CHUNK_FILE_GLOB))
        if not chunk_files:
            raise ValueError(f"no chunk files under {args.chunks_dir}")
        chunks = load_chunks(chunk_files)
    except (OSError, ValueError) as e:  # JSONDecodeError and schema failures are ValueErrors
        print(f"error: {e}", file=sys.stderr)
        return 2
    if fetch_facts is None:
        fetch_facts = partial(fetch_company_facts, cache_dir=args.xbrl_cache_dir)  # pragma: no cover
    return _report(questions, Context(chunks=chunks, gold=gold, fetch_facts=fetch_facts, other_ids=other_ids))


if __name__ == "__main__":
    sys.exit(main())
