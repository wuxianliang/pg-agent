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

W1 complete: loader, fixture self-check and environment gate actually ran with exit 0. Python 3.12.11, psycopg2 2.9.12, PostgreSQL 18.4; P0 eleven closeout commands and separate s9 23-case gate also exit 0. W2 complete: all four current DP1 commands exit 0, with 88 zero-write DDL negative probes, positive cases and actual deferred-FK COMMIT failures. Eight domain tables plus two bookkeeping tables; DDL budget 325/900 physical lines. W3/W4 not yet complete. Do not infer DDL, kernel, or complete DP1 behavior from the environment gate. Each milestone records actual command exit codes in `docs/reviews/cordis-v2-dp1-conformance-matrix-2026-10-25.md`. See the plan at `docs/plans/v24-cordis-dp1-foundation-plan-2026-10-25.md`.
