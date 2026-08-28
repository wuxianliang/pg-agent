# v6 DuckDB 2.0 feasibility note (measured)

**Investigation item:** v6 DuckDB temporary analysis workbench, DuckDB 2.0 feasibility

**Date checked:** 2026-08-28

**Scope:** Investigation note only. It does not implement v6, change `pgembed`, or modify v1–v5.

**Evidence class:** runtime measurements against an installed Python wheel, plus official DuckDB posts for *what was announced*. Design claims below prefer the runtime result when the two disagree.

## Executive decision

DuckDB is a credible worker-side temporary analysis engine for v6. The measured artifact is **not DuckDB 2.0.0**. It is:

| Field | Measured value |
|---|---|
| Python package | `duckdb==1.6.0.dev365` (PyPI pre-release, 2026-08-20) |
| Wheel | `cp312-cp312-macosx_11_0_arm64` |
| Install location | `pg-agent/.venv` (CPython 3.12.13, macOS arm64) |
| `SELECT version()` | `v2.0.0-alpha38615` |
| `PRAGMA version` | `v2.0.0-alpha38615`, git `16980de6d3`, codename `Cyanoptera` |
| Official 2.0.0 | still upcoming; **out of scope**. v6 is locked to this pre-release. |
| Platform | **macOS arm64 only**. No Linux/Windows matrix. |

On **this** engine, the v6 MVP should be built from capabilities that actually executed, not from the August 17/20 blog list:

1. Worker-owned in-memory connection per `run_id`.
2. Snapshot ingress through Python (`CREATE TABLE` + `executemany`) on a query session that **never** `LOAD postgres`.
3. Named artifacts via explicit `view_name` and generated `CREATE TEMP VIEW ... AS <query>`.
4. A validator that uses `extract_statements` for statement count and outer type, **and** a conservative token scan because DML/COPY inside a CTE still classify as `SELECT`.
5. Session hardening: disable autoload/autoinstall, then `SET enable_external_access=false`.
6. DuckDB core extension `postgres` (`INSTALL postgres`): **consider as optional sidecar copy only**. Live-tested against pgembed 18.4. Do not ATTACH it into the workbench session. Do not use `pg_duckdb`. See main report §4.5.1.

Do **not** depend on: pipe `|>`, trailing `AS view_name` as materialization, advertised `CONNECT 'postgres://...'` remote routing, or a custom grammar-extension package. Those either parse as something else or fail on this wheel.

`pgembed` change default: **none**.

## 1. What was installed

Command used in the pg-agent uv environment:

```text
uv pip install --prerelease=allow duckdb==1.6.0.dev365
```

PyPI simple (`https://pypi.org/simple/duckdb/`) and the project page list `1.6.0.dev365` as a pre-release. Official preview install for Python v2.0-dev is `pip install duckdb --pre --upgrade`. The stable PyPI line remains 1.5.5.

**Version/platform lock:** v6 uses only `duckdb==1.6.0.dev365` on macOS arm64. Implementation should pin that exact spec in `pyproject.toml`; this note still does not edit the file. Other CPython / OS wheels are out of scope.

Repro scripts in this directory:

- `_probe_duckdb160dev365.py`
- `_probe_duckdb160dev365_b.py`
- `_probe_duckdb160dev365_c.py`
- `_probe_duckdb160dev365_d.py`

## 2. Announced 2.0 features vs measured behavior

Official posts used only as the checklist (not as proof the feature works):

- 2026-08-17 “A Preview of DuckDB v2.0”
- 2026-08-20 PEG parser post
- 2026-08-18 JSON patch post
- preview install page

| Announced 2.0 surface | Measured on `v2.0.0-alpha38615` | v6 design consequence |
|---|---|---|
| PEG parser / FROM-first / bare expression | `FROM t`, `FROM t SELECT x`, `1 + 2` all execute. `extract_statements` types them as `SELECT`. | Dialect prompt may teach FROM-first. Validator treats them as SELECT. |
| Pipe syntax `|>` (grammar-extension demo) | `ParserException` at `|>`. `INSTALL pipe` → HTTP 404 for `v2.0.0-alpha38615/osx_arm64/pipe.duckdb_extension.gz`. | Not available. No MVP syntax, no spike on this wheel. |
| Runtime grammar-extension API | Setting `allow_parser_override_extension` accepts only `DEFAULT` and `FALLBACK`. `true`/`false` rejected. No loadable pipe extension. | Grammar spike remains blocked until a real extension artifact exists. |
| Trailing `AS named_out` as view materialization | `SELECT x FROM t AS named_out` succeeds, creates **no** view and **no** table named `named_out`. It is a table alias. | InfiniSQL-style trailing AS is **not** this engine. MVP uses explicit `view_name`. |
| `$x` after `SET VARIABLE` | Works in expressions and `WHERE`. `$rel` cannot be used as an identifier (`SELECT * FROM $rel` → parser error). | Bind values with `$x` / `$1` / named `$parameter`. Compose identifiers in Python. |
| Positional `$1` and named `$parameter` | `execute(sql, [2])` and `execute(sql, {"parameter": 7})` work. | Worker parameter binding is available now. |
| `CONNECT 'postgres://...'` remote pushdown | After `LOAD postgres`, still `Cannot open file "postgres://..."`. String form is a **filesystem path**. | Not an ingress candidate on this wheel. |
| `CONNECT ident` / `DISCONNECT` | `CONNECT postgres` → database not attached. `CONNECT mem_other` on in-memory ATTACH → “does not support CONNECT”. `DISCONNECT` → “no active CONNECT (already on LOCAL)”. | CONNECT exists as session routing to a *CONNECT-capable attached database*, not as “open a postgres URI”. Local memory DBs are not CONNECT-capable. |
| Postgres extension `ATTACH` / scan | `INSTALL postgres` + `LOAD postgres` succeed. Functions present: `postgres_attach`, `postgres_scan`, `postgres_scan_pushdown`, `postgres_query`, `postgres_execute`, `postgres_configure_pool`. `ATTACH ... (TYPE postgres, READ_ONLY)` attempts a real libpq connection (dummy host → connection refused). | Syntax is real. Live round-trip against pgembed was **not** run. `postgres_execute` means writes exist — never model-facing. |
| `postgres_scan` vs `enable_external_access=false` | If `LOAD postgres` happens **before** the lock, `postgres_scan` still attempts TCP. `ATTACH` after the lock is denied. If the lock happens first, `LOAD`/`INSTALL` are denied. | MVP session: never load postgres; lock external access at open. Validator must still reject `postgres_scan`/`ATTACH`/`CONNECT`. Live-scan needs a different session profile, not a runtime toggle. |
| VARIANT + `variant_*` | `::VARIANT`, `variant_type`, `variant_keys`, `variant_contains`, `'{"a":1}'::JSON::VARIANT` all work. | Optional analysis type. Not required for MVP register/query. |
| Statement triggers (`REFERENCING OLD/NEW TABLE`, `FOR EACH STATEMENT`) | After-update statement trigger from the 2026-08-17 post **works** (audit rows `(1,10,100), (2,20,200)`). SQLite `BEGIN ... END` trigger syntax fails. `BEFORE FOR EACH ROW` → not implemented. | Engine has 2.0 statement triggers. Workbench SQL must reject `CREATE TRIGGER`. |
| DML inside CTEs | `INSERT`/`UPDATE` in CTE + outer `SELECT` execute and mutate. `DELETE ... RETURNING` in CTE + outer `INSERT` executes. `COPY ... TO` in CTE + outer `SELECT` executes. | “Starts with WITH ⇒ read-only” is false. See validator section. |
| Nested schemas | `CREATE SCHEMA s1; CREATE SCHEMA s1.s2; CREATE TABLE s1.s2.n` works. | Dialect fact. Do not expose schema-creating statements on the model surface. |
| MERGE | `MERGE INTO ... WHEN MATCHED/NOT MATCHED` works. `extract_statements` type = `MERGE_INTO`. | Reject as DML. |
| `COPY ... PARTITION BY` | Works when external access is on (writes `p=x` / `p=y` dirs). | Reject. Filesystem write. |
| JSON 2.0 functions | `json_normalize`, `json_merge_patch_diff`, `json_deep_merge`, `json_strip_nulls`, `json_set`, `json_remove` work. `json_insert`/`json_replace` exist and need JSON-typed arguments. | Analysis dialect OK; not an architecture dependency. |
| Recursive CTE + `USING KEY` | Works (`(1, 2.5)` as in the blog). | Allow in read-only SELECT. |
| `FETCH FIRST`, `OVERLAY`, `AT TIME ZONE`, `COLLATE de` | Work. | Allow in read-only SELECT. |
| `APPROX NEAREST` join | Works. | Allow; not required. |
| `SELECT * EXCLUDE`, `QUALIFY`, `PIVOT`, `ASOF JOIN`, `CREATE MACRO` | Work. `CREATE MACRO` is a session mutation — reject on the query tool (not a read-only SELECT). | Prompt may mention EXCLUDE/QUALIFY/PIVOT/ASOF. Reject MACRO/PIVOT-as-DDL as needed by statement type. |
| Async I/O / storage v2.0 | Not separately microbenchmarked. Engine reports 2.0 alpha; default `memory_limit` was `12.7 GiB` on this machine. | Irrelevant to MVP contract. Set `memory_limit` explicitly. |
| Quack / DuckDB-as-server | `INSTALL quack` succeeds. `CALL quack_serve(token := 't')` → token must be ≥ 4 chars (function exists). | Out of scope. Do not start a server from the v6 worker. |
| `CREATE EXTENSION REPOSITORY` | `ParserException` at `EXTENSION`. | Not on this wheel. |
| `extract_statements` / `interrupt` / `fetchmany` | All present. Interrupt of `range(1e9)` raises `InterruptException`. `fetchmany(2)` then `fetchall()` works. | Use these APIs. |
| `get_table_names` | Works for `SELECT * FROM t`, comma join, `FROM t`. `JOIN ... USING (x)` raised `BinderException` in this session. | Lineage helper, not a complete catalog. |

## 3. Named view syntax: measured, not hoped

### Trailing `AS view_name` — not InfiniSQL materialization

```sql
SELECT x FROM t AS named_out
```

returns rows, and afterwards `duckdb_views()` / `duckdb_tables()` contain no `named_out`. Design must not parse a trailing alias as a session artifact.

### Grammar-extension pipe — absent

No `|>` parse, no `pipe` extension binary for this alpha. `allow_parser_override_extension` cannot be turned into a boolean “on”. A custom trailing-AS extension is not a thing we can load today.

### Explicit `view_name` + `CREATE TEMP VIEW` — works

```sql
CREATE TEMP VIEW v1 AS SELECT * FROM t WHERE x >= 2;
CREATE TEMP VIEW v2 AS SELECT x, y * 2 AS y2 FROM v1;
SELECT * FROM v2 ORDER BY x
-- [(2, 40), (3, 60)]
```

Also measured:

- `CREATE OR REPLACE TEMP VIEW` succeeds and replaces the definition.
- Duplicate `CREATE TEMP VIEW` without replace → `Catalog Error: View with name "v_or" already exists!`
- `CREATE TEMP VIEW vf AS FROM t SELECT x` works (FROM-first as view body).
- `BEGIN; CREATE TEMP VIEW tv AS SELECT * FROM base; SELECT * FROM tv; ROLLBACK;` → view is gone.
- Same with `COMMIT` → view remains.

**MVP recommendation (now a measurement, not a guess):** Candidate B. Worker generates:

```sql
CREATE TEMP VIEW "v_sales" AS
<single validated SELECT>
```

inside a DuckDB transaction; preview; `COMMIT` or `ROLLBACK`. Duplicate policy is v6-controlled (`replace_view=false` → fail on exists; `replace_view=true` still needs an implementation probe of `CREATE OR REPLACE` inside a transaction before relying on rollback-to-old-definition).

If a future 2.0.0 grammar extension can parse trailing `AS view_name`, it may only translate into this same operation.

## 4. PostgreSQL ingress: measured split

### 4.1 Snapshot copy through Python — default, and the only fully exercised path

Measured: `CREATE TABLE` + `executemany("INSERT ... VALUES (?, ?)", rows)` + `SELECT` round-trip works without pandas/pyarrow.

`con.register("py_t", [{"a": 1}])` **fails** unless the object is a pandas DataFrame, DuckDB relation, pyarrow table/dataset/scanner, or supported NumPy arrays. MVP must not assume those extras.

`CREATE TEMP TABLE snap AS SELECT * FROM t` works for intra-DuckDB copies.

Recommended flow (unchanged semantically, now with a known API):

1. Resolve opaque `source_id` in worker config.
2. Read-only PostgreSQL transaction; identifier-safe allowlist.
3. Create the DuckDB table; insert bounded batches via `executemany` (or Arrow later if the extra is pinned and tested).
4. Materialize only after the copy succeeds; never silently truncate.
5. Store identity/schema/ingest_mode/columns/hash in PostgreSQL, not the rows.

### 4.2 Advertised `CONNECT 'postgres://...'` — not this wheel

The August 17 post shows:

```sql
CONNECT 'postgres://localhost/mydb';
SELECT count(*) FROM orders; -- runs on the PostgreSQL server
```

On `v2.0.0-alpha38615`, that string is opened as a **file path**, with or without `LOAD postgres`. Do not design v6 ingress around this statement. This project is locked to `1.6.0.dev365`; there is no “wait for another wheel” path.

### 4.3 `ATTACH ... (TYPE postgres)` / `postgres_scan` — live against pgembed 18.4

Earlier dummy-host probes showed TCP attempts. The live probe (`_probe_duckdb_postgres_ext.py`) then attached via unix socket.

**Live pgembed 18.4 (unix socket) on this wheel:** `ATTACH ... READ_ONLY` works; filter pushdown shows `Postgres Scan` + `Filters`; `CREATE TABLE snap AS SELECT *` is a true snapshot; attached tables see later `UPDATE`s; READ_ONLY blocks INSERT and `postgres_execute` writes; **`postgres_scan` still works after DETACH + `enable_external_access=false`**; `UNLOAD postgres` is not valid SQL; JSONB arrives as `VARCHAR`.

**Plugin decision:** keep the query session extension-free. Optional later: a throwaway DuckDB connection uses `INSTALL postgres` only to copy, then the locked query session never loads it. Never `pg_duckdb`. Never model-facing `ATTACH` / `postgres_*`.

**Do not expose `CONNECT`, `ATTACH`, `INSTALL`, `LOAD`, `postgres_scan`, or `postgres_execute` on the model-facing query surface.**

## 5. Session hardening that actually exists

Default on a fresh `duckdb.connect()` in this process:

```text
enable_external_access          true
autoinstall_known_extensions    true
autoload_known_extensions       true
allow_unsigned_extensions       false
memory_limit / max_memory       12.7 GiB   (machine-dependent)
threads                         8
lock_configuration              false
```

Measured knobs:

| Action | Result |
|---|---|
| `SET memory_limit = '256MB'` | Becomes `244.1 MiB` |
| `SET autoinstall_known_extensions=false` / `autoload_known_extensions=false` | Stick |
| `SET enable_external_access=false` | Blocks `read_csv`/`read_parquet`/`read_json`/`glob`/`COPY TO`/`INSTALL`/`CREATE SECRET`/loading extensions |
| Re-enable `enable_external_access` on a running DB | `Cannot enable external access while database is running` |
| Lock first, then `LOAD postgres` | Denied |
| `LOAD postgres` first, then lock | Filesystem denied; `postgres_scan` still does TCP; `ATTACH` postgres denied |

**MVP `DuckSession` open sequence (fact-based):**

```text
con = duckdb.connect()                    # :memory:
SET autoinstall_known_extensions = false
SET autoload_known_extensions = false
SET enable_external_access = false
SET memory_limit = '<run budget>'
-- do not INSTALL/LOAD postgres
-- do not INSTALL quack
```

Policy is per-connection and one-way on external access. A later live-scan mode is a different connection constructor, not `SET` after the fact.

`interrupt()` is a real cancellation seam (measured `InterruptException`).

## 6. Validator: what the Python API can and cannot see

`con.extract_statements(sql)` returns objects with `type`, `query`, `named_parameters`.

| SQL | `StatementType` |
|---|---|
| `SELECT ...` / `WITH q AS (SELECT ...) SELECT ...` / `FROM t` / `1 + 2` | `SELECT` |
| `WITH ins AS (INSERT ... RETURNING *) SELECT * FROM ins` | **`SELECT`** |
| `WITH c AS (COPY ... TO file) SELECT 1` | **`SELECT`** |
| `WITH moved AS (DELETE ... RETURNING *) INSERT INTO archive SELECT * FROM moved` | `INSERT` |
| `CREATE TEMP VIEW ...` | `CREATE` |
| `COPY t TO ...` | `COPY` |
| `ATTACH ...` | `ATTACH` |
| `SET VARIABLE ...` | `SET` |
| `MERGE INTO ...` | `MERGE_INTO` |
| `INSTALL postgres` | `LOAD` |
| `SELECT 1; SELECT 2` | two `SELECT`s; `execute` returns the last result |

Comments (`--`, `/* */`) execute. Semicolon inside a string stays one statement.

**Design rule:**

1. Reject `len(extract_statements) != 1`.
2. Require outer type `SELECT` for `wb_duck_query` bodies (FROM-first included).
3. **Additionally** scan the statement text (outside string literals and comments) for `INSERT`/`UPDATE`/`DELETE`/`MERGE`/`COPY`/`ATTACH`/`CONNECT`/`DISCONNECT`/`INSTALL`/`LOAD`/`CREATE SECRET`/`CREATE MACRO`/`CREATE TRIGGER`/`CREATE SCHEMA`/`CALL`/`PIVOT` as a statement / `SET` / `USE`. Outer type `SELECT` is not a sandbox.
4. Do not use `extract_statements.type == SELECT` as proof of read-only.
5. Do not use “starts with WITH” as proof of read-only.
6. Worker generates `CREATE TEMP VIEW` itself; the model does not send that DDL.
7. Identifier names are validated in Python, never via `$variable`.

`get_table_names` can help record dependencies for simple FROM lists. It is not reliable for every join shape (`JOIN USING` failed here). Fallback: conservative name scan against known artifacts.

## 7. Mapping to v5/v4 and InfiniSQL function

Unchanged process invariants: v1–v5 frozen; per-stage DBs; version-local worker; no SQL-side LLM HTTP; PostgreSQL owns durable state; DuckDB is temporary and per-run.

Functional loop, implemented with measured SQL:

```text
wb_duck_register(source_id, relation_name)
  → Python snapshot into DuckDB table/view
  → wb_duck_query(view_name, read_only_query)
       worker: BEGIN; CREATE TEMP VIEW "name" AS <query>; preview; COMMIT
  → wb_duck_query(next_view, query_using_prior_view)
  → wb_duck_brief_query(view_name, limit)
```

DuckDB TEMP VIEWs are connection-scoped, like v4 sticky TEMP, but they live in the worker process, not in `pg_my_temp_schema()`. PostgreSQL TEMP and DuckDB TEMP remain mutually invisible.

## 8. `pgembed` change default: none

No new measurement requires shipping DuckDB inside pgembed, running DuckDB in PostgreSQL, or adding PL/sh / `pg_net` / `pgsql-http`. DuckDB runs in the pg-agent worker. Source data stays in PostgreSQL (pgembed 18.4 or an operator-configured external database).

A live `ATTACH`/`postgres_scan` spike talks to PostgreSQL as a **client**. That still does not require a pgembed patch.

## 9. Gates, updated after the wheel

| Gate | Status after this probe |
|---|---|
| G2 pin `1.6.0.dev365` on macOS arm64 | **Closed.** Other platforms/versions out of scope. |
| G3 core runtime on this alpha | **Closed for the measured subset:** isolated `connect()`, TEMP VIEW chain, transactional CREATE TEMP VIEW, `$x`/`$1`/named params, `memory_limit`, `interrupt`, `extract_statements`, `fetchmany`, `enable_external_access` lock, `executemany` snapshot analog. |
| G4 snapshot vs live pgembed types | **Open.** Python insert path works in isolation; type mapping against PG 18.4 was not run. |
| G5 live Postgres extension | **Decision closed.** Live pgembed 18.4 works. Query session must not LOAD it. Sidecar copy optional. `pg_duckdb` rejected. CONNECT-URI is a file path. |
| G6 grammar / trailing AS | **Closed-fail on this wheel.** Pipe 404; trailing AS is alias; parser override is DEFAULT/FALLBACK only. |
| G7 explicit `view_name` + `CREATE TEMP VIEW` | **Ready to implement against this engine.** |
| Product pin | **Locked:** `duckdb==1.6.0.dev365` on macOS arm64. Implementation writes pyproject; no 1.5.5, no 2.0.0 GA wait. |

## Sources

Runtime:

- Installed package in `pg-agent/.venv`: `duckdb==1.6.0.dev365`
- Scripts: `_probe_duckdb160dev365.py`, `_b.py`, `_c.py`, `_d.py`, `_probe_duckdb_postgres_ext.py`

Official (checklist / packaging, 2026-08-28):

1. <https://duckdb.org/2026/08/17/duckdb-20-highlights>
2. <https://duckdb.org/2026/08/20/duckdb-20-peg-parser>
3. <https://duckdb.org/2026/08/18/reconciling-json.html>
4. <https://duckdb.org/install/preview.html>
5. <https://duckdb.org/release_calendar>
6. <https://pypi.org/simple/duckdb/>
7. <https://pypi.org/project/duckdb/1.6.0.dev365/>
