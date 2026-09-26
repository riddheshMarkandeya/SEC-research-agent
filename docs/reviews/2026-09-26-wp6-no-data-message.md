# Review: WP6, no-data period and "finds no data" wording (commits 1e1491b, ca6cace)

Plan: `docs/plans/2026-09-25-wp6-no-data-message.md`.
- **6a** makes `get_financial_fact`'s no-data reply name the period the lookup used. It adds
  `_no_fact_period` and four `NO_FACT_PERIOD_*` constants, and hardens `_never_tagged_hint`
  against non-str input.
- **6b** rewords "not available" / "Returns null" to "finds no data" in SYSTEM_PROMPT and
  `FACT_TOOL_SCHEMA`.

Suite before review: 930 passed. The diff `a3c3eb8..ca6cace` touches blast-radius paths
(`agent.py`, `prompts/`), so it classified as Substantial. That superseded the plan's
"light" review depth.

## Round 1

Passes: `/code-review` high, `arch-reviewer` (opus), `security-reviewer`, `/simplify`
(reuse, simplification, efficiency, altitude).

1. **Low** (code-review, arch): `_never_tagged_hint` was still typed `str | None` while
   guarding list and other non-str input from raw tool args. `[Fixed]` (`b16c64c`): both
   parameters are now `object`.
2. **Low** (code-review, arch, simplify reuse, simplification and altitude):
   `_no_fact_period` hand-copies `call_get_financial_fact` / `xbrl_facts.get_metric`'s
   period precedence and the `"FY"` default, and its docstring claimed "actually used" even
   for rejected calls. `[Fixed]`, docstring only: it now says the order must mirror the
   lookup and covers rejected calls.
   - Arch and altitude both checked every branch against the lookup code, and they match.
   - A shared resolver stays out of scope. It would reach into `get_metric` (critical core,
     untouched here), which is disproportionate for a two-function mirror.
3. **Med** (code-review): a yoy no-data reply names the anchor period even when the
   prior year is the missing one. `[Verified, no fix needed]`: already WP7's BACKLOG item (a).
4. **Med** (code-review): the Q4 hint still fires when a date or multi-year lookup ignored
   `fiscal_period`. `[Verified, no fix needed]`: a plan decision (S1), pinned by a test.
5. **Med** (code-review): a call rejected at the boundary (partial multi-year range, yoy +
   multi-year) reads as "no structured data found … try search_filings", not "fix this
   argument". `[Deferred → BACKLOG]`: this predates 6a (6a only makes the rejected range
   visible), and it belongs with WP7's argument-rejection wording. Added as WP7 item (d).
6. **Low** (code-review): the only multi-year snapshot scenario is the partial range.
   `[Verified, no fix needed]`: a plan decision (S4). The template constant is itself
   fingerprinted, and the full range is unit-tested.
7. **Nit** (simplify, simplification): the new tests could be one parametrized table.
   `[Verified, no fix needed]`: `test_agent.py` has no parametrized tests anywhere, and each
   test carries a one-line reason that a table row would lose.
8. **Nit** (simplify, efficiency): repeated `args.get` lookups on the no-data path; it also
   suggested moving the `isinstance` check after the membership test.
   `[Verified, no fix needed]`: the lookups are negligible on an error path, and the reorder
   would bring back the list-ticker `TypeError` that 6a fixed.
9. **Nit** (simplify, reuse): a second inline `isinstance`-before-`in` ticker guard
   (the other is in `_dispatch_tool_call`). `[Verified, no fix needed]`: two call sites don't
   justify a shared helper.
10. Security: no findings. Model-supplied period values are echoed with `!r` into the same
    model's own tool result, as `fiscal_year` / `fiscal_period` already were. `repr` can't
    raise on JSON types, and lookups still validate their inputs separately.

`/simplify` made no edits.

## Round 2

Delta: `git diff HEAD` over `ca6cace` (items 1 and 2). Passes: `/code-review` low. No security
pass: the delta changes no runtime behaviour. No findings. The `agent` fingerprint was
unchanged at `e073094f18b9`.

## Live verification

The panel screen, 3 runs of 13 questions: 31/39 → 35/39, no REGRESSED flag. One date-shaped
no-data reply ("period ending '2027-04-26'") was followed by a corrected fact call and a
passing answer. Figures and the trace check are in `docs/decisions/2026-09-26-wp6-no-data-message.md`.

## Outcome

6a, 6b and the review fixes shipped. Open in BACKLOG: WP7 [bug, Med, Standard], now with item
(d). Suite: 930 passed. The review closed clean after 2 rounds with no escalation.
