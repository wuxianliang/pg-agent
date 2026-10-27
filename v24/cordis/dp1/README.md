# Cordis v2 DP1

DP1 creates an isolated `v24_cordis` schema and protocol/data foundation on branch v24. Product behavior is specified by `docs/designs/cordis-plugin-system-2026-10-25.md`; this README records implementation and real gate outcomes.

## Commands

```bash
uv run python v24/cordis/load.py
uv run python v24/cordis/dp1/setup_db.py --self-check
uv run python v24/cordis/dp1/test_environment.py
uv run python v24/cordis/dp1/test_ddl.py
uv run python v24/cordis/dp1/test_kernel.py
```

## Status

W1 complete: loader, fixture self-check and environment gate actually ran with exit 0. Python 3.12.11, psycopg2 2.9.12, PostgreSQL 18.4; P0 eleven closeout commands and separate s9 23-case gate also exit 0. W2 complete: the final DDL gate passed 97 zero-write negatives, positive cases, and actual deferred-FK COMMIT failures. W3 complete: all five current DP1 gates exit 0; kernel gate passed 66 committed zero-write assertions, including catalog-shadow authentication rejection, G-before-target lock evidence, claim/replay contracts, and cross-connection durable receipts. Eight domain tables plus two bookkeeping tables; DDL budget is 350/900 physical lines and `40_advance.sql` remains below 1200 lines. Production lifecycle interpreters still raise `0A000`. W4 complete: all 11 v24 closeout commands and the separate s9 extension gate exit 0; all 12 frozen baseline SQL hashes match P0 and v24 loader/stages/frozen SQL diffs are empty. All five DP1 gates were rerun successfully. DP1 is complete at its specified foundation boundary. As of DP2 W3, production reconcile `on`/`advance` executes P0–P4; `off`/`retry`, dispose and settlement remain `0A000`. Do not infer DDL, kernel, or complete DP1 behavior from the environment gate. Each milestone records actual command exit codes in `docs/reviews/cordis-v2-dp1-conformance-matrix-2026-10-25.md`. See the plan at `docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md`.

## DP2 W1 cross-milestone note (2026-10-26)

DP2 W1 extends the same `v24_cordis` schema without changing the fifteen-file manifest. The terminal effect guard in `30_triggers.sql` now rejects terminal reopen/outcome/settled/attempt/fence/claim/lease edits with `55000` (113 zero-write DDL probes, up from 97); `40_advance.sql` has the reserved continuation identity, typed delta validator/applier, P0→P1 generation precheck and terminal receipt settlement. DP1's production `interpret_command` contract changed only for malformed/missing command payloads, which now return `invalid_args` instead of a blanket `0A000`; all spec-valid lifecycle payloads still raise `0A000` in production. CDP1-D and CDP1-K still exit 0 (66 kernel assertions), and the new DP2 CDP2-K gate exits 0. Physical budgets: `40_advance.sql` 1196/1200 (4 lines remaining); DDL prefix 360/900. The four remaining advance lines cannot accommodate the planned W2–W4 additions; that requires an explicit budget/layout decision.

## DP3 pointer (2026-10-27)

DP3 teardown is specified in `docs/plans/v24-cordis-dp3-teardown-plan-2026-10-27.md` and is not part of the DP1 acceptance record above. The W1-era note that four advance lines remained under a 1200-line file cap is historical. On 2026-10-27 the user set the total advance-plus-helper budget at 5000 physical lines. DP3 B0 reran the five DP1 commands inside the serial 21-command sequence; exits and prints are in `docs/reviews/cordis-v2-dp3-conformance-matrix-2026-10-27.md`. That rerun does not rewrite DP1 history. DP3 W1 later migrated `test_kernel.py` and the DP2 boundary asserts from a single-file 1200 cap to a 40–49 total ≤5000. The proof calls shared `assert_helper_budget` on temporary 40/41/42 trees of exactly 5000 lines (accepted) and 5001 lines (rejected). The W1 exits and line counts are in the DP3 matrix W1 section. That migration does not rewrite the DP1 acceptance record above.
