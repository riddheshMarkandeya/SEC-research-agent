# Review: CRM fiscal-year-lookup fix

Plan: `C:\Users\riddh\.claude\plans\snug-jingling-pumpkin.md` (session-local
plan-mode scratch file; durable record is
`docs/decisions/2026-09-16-crm-fiscal-year-lookup-fix.md`). Adds a
`_resolved_fiscal_year()` helper to `xbrl_facts.py`, used in `_pick_entry`'s
matching and `get_metric`'s return dict, plus a `filed`-based tiebreak in
`_pick_entry`. Test suite after this diff: 676 passing (up from 669).

## Independent plan review (before implementation)

Per `design-before-building`, a freshly-spawned subagent reviewed the
plan against the actual codebase and cached SEC data before any code was
written. It confirmed the chosen fix and caught two real issues in the
plan draft: the root-cause narrative overstated "CRM-specific, since
2019" when the actual per-filing data showed a different, more general
pattern (also present in NVDA's own old filings); and the broadened
annual-matching criterion introduces a same-`end`-date tie risk (real,
confirmed in CRM's own restated historical data) the original draft's
plain `max()` didn't handle. Both were fixed in the plan before
`ExitPlanMode`, so neither reached the implementation stage as a bug.

## Pass 1 — correctness and CLAUDE.md compliance (self, medium effort)

Diff reviewed against the approved plan and the actual `_pick_entry`/
`get_metric`/`get_yoy_growth` control flow. Matches the plan exactly;
no findings. `[Verified, no fix needed]`.

## Pass 2 — architecture, design, performance, refactoring + documentation/comment hygiene (fresh subagent, no memory of the implementation session)

Independently re-ran the full test suite (676 passing, confirmed), traced
`_resolved_fiscal_year`/`_pick_entry`/`get_metric` by hand against the
new fixtures (confirmed the annual end-date-year match, the `filed`
tiebreak, and the `get_yoy_growth` chaining fix all resolve as claimed,
and that the intermediate "`_pick_entry`-only" state genuinely fails the
chaining test), re-ran `ruff`/`pyright` on all four changed files and
cross-checked every hit against `git diff` ranges (all new-in-diff
findings fixed; remaining hits are pre-existing or match this project's
own documented single-line-fixture-dict E501 exception), confirmed the
`BACKLOG.md` edit didn't corrupt an adjacent bullet (the exact mistake
made once already this session, checked for deliberately), confirmed
`PROJECT_INDEX.md`'s new entry is correctly positioned, and spot-checked
the actual live eval result JSON on disk to confirm the "3/3 passed"
claim is real, not asserted from memory. It also independently pulled
the real cached XBRL data and confirmed the root-cause generalization
claim (CRM mismatched 2010-2014 and 2026; NVDA mismatched 2011-2014).

Two findings, both documentation-accuracy nits, neither affecting
runtime correctness:

1. `xbrl_facts.py`'s `_resolved_fiscal_year` docstring and the new
   manual script's module docstring both said the mismatch "appears in
   both CRM's and NVDA's own 2011-2014 filings" — inaccurate for CRM,
   which also mismatches in 2010 (the decision file itself had the
   correct, more precise year ranges; only these two artifacts had
   flattened them into one range). `[Fixed]` — both now say "CRM's own
   2010-2014 filings and NVDA's own 2011-2014 filings."
2. The decision file's "Related" section claimed "two new backlog items
   filed from this fix's own review process," but only one new item was
   actually filed in that `BACKLOG.md` section — the second thing named
   (the 3+-company routing item being unaffected) is an older, untouched
   item merely confirmed as out of scope, not something newly filed.
   `[Fixed]` — reworded to distinguish the one new item from the
   separate, pre-existing item it references.

## Live verification

`tests/manual/verify_crm_fiscal_year_lookup.py` (new), run against the
real cached CRM data: before the fix, `[BUG]` on all `fiscal_year=2026`
lookups (raw metric, both ratios, the tool entry point) and the chaining
check; after, `[FIXED]` on all four, including the `get_yoy_growth`
self-consistency check (chaining now lands on CRM's real FY2025 revenue,
$37.895B, not a 2-years-back value).

Live eval spot-check (`eval_harness.py --backend gemini`, the 3 ranking
questions): **3/3 passed**, all with a citation marker and zero
unverified citations — confirmed for real against the on-disk eval
result JSON, not just the printed summary.

## Outcome

Shipped: `_resolved_fiscal_year`, the `_pick_entry` matching/tiebreak
changes, and `get_metric`'s return-dict fix in `xbrl_facts.py`; new
tests in `tests/test_xbrl_facts.py`/`tests/test_formulas.py`; new
`tests/manual/verify_crm_fiscal_year_lookup.py`. The review loop closed
clean after one round (two doc-accuracy fixes, no second round needed).
One residual open item filed to `BACKLOG.md`: the historical pre-2015
CRM/NVDA restated-value tiebreak isn't exhaustively audited beyond the
currently-reachable current-year case. Final test-suite count: 676
passing.
