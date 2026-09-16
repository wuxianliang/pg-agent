# Legacy cache live path (Phase 0 WI-4)

**Verdict: E0 / blocker** — no live auto-coder DuckDB cache was found.

Searched 2026-08-29 for `byzerai_store_duckdb.db` (and `*.wal`) under `/Users/wxl/Projects`, with extra focus on `infinisynapse`, `auto_coder*`, `rag`, `.auto-coder`, and `.cache`.

Commands (bounded, all empty of live DB files):

- `find /Users/wxl/Projects -name 'byzerai_store_duckdb.db' -o -name 'byzerai_store_duckdb.db.wal'`
- `find /Users/wxl/Projects/infinisynapse /Users/wxl/Projects/auto_coder-3.0.74 /Users/wxl/Projects/rag /Users/wxl/Projects/newrag /Users/wxl/Projects/planrag /Users/wxl/.auto-coder /Users/wxl/.cache /Users/wxl/Projects/pg-agent -iname '*byzerai*' -o -iname '*store_duckdb*'`
- `mdfind -onlyin /Users/wxl/Projects 'byzerai_store_duckdb.db'` — hits were source/docs mentions only, not a database file.

`infinisynapse/.auto-coder` contains only `logs/`. No project `.cache/byzerai_store_duckdb.db`.

## Golden

`v7/tests/fixtures/legacy_cache/golden.v1.json` is labeled `synthetic_from_source_schema`.

| Item | Evidence |
|---|---|
| Live corpus schema/rows/retrieval | **E0** — file missing; not fabricated |
| Probe machinery vs synthetic fixture | **E2** — `uv run python v7/tests/test_legacy_cache_probe.py` |
| Source defaults (similarity 0.1, top_k 10000, dim 1024, hybrid false, table `rag_duckdb`) | **E1** — `auto_coder-3.0.74` `LocalDuckDBStorageCache` + `AutoCoderArgs` |

Phase 2 canonical import against a production cache remains blocked until an operator provides a readable live `persist_dir/.cache/byzerai_store_duckdb.db`.
