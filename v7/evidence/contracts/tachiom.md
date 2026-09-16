# tachiom + duckdb-tachiom contract (Phase 0 WI-3)

Evidence level: **E1** static (crate source, SQL tests, Makefile, Cargo.lock, existing build artifacts listed but not re-run). **Not E2** on duckdb-pgagent `a1f0ab1911`.

Related backend: **multi-vector is BLOCKED**. duckdb-tachiom is built against DuckDB **v1.5.4** unstable C API; v7 target is duckdb-pgagent `a1f0ab1911` / tag `duckdb-special-20260829-g1`. ABI compatibility is unproven. Do not rebuild/install into duckdb-pgagent from this freeze.

Plan §4.5: if duckdb-tachiom needs a fix for the target DuckDB ABI, that fix is a **separate gate** with a fixed artifact hash. Do not reimplement tachiom inside Flock.

## What was read

| Path | Git / identity |
|---|---|
| `/Users/wxl/Projects/tachiom` | checkout HEAD `69f6f3dc2eef3b543983eb71227bb65590e498a8` `main`; describe `v0.3.4-2-g69f6f3d` (**not** the v7 build identity) |
| `/Users/wxl/Projects/tachiom/docs/PythonUsage.md` | Python API |
| `/Users/wxl/Projects/tachiom/Cargo.toml` | crate `tachiom` version `0.3.4` |
| `/Users/wxl/Projects/tachiom/src/python.rs` | PyO3 search/build defaults |
| `/Users/wxl/Projects/tachiom/src/bin/tachiom_build.rs`, `tachiom_search.rs` | CLI bins (source present; release bins not found under `target/release/`) |
| `/Users/wxl/Projects/duckdb-tachiom` | `5c91f3cb5c4091cb70735449e546446a09136a04` `main`; untracked `examples/native_bench.rs`, `prompt-exports/`, `testing/` |
| `duckdb-tachiom/src/{lib,build,admin,search,matcher,envelope,registry}.rs` | SQL surface |
| `duckdb-tachiom/test/sql/{build_files,admin,search,match}.test` | Actual SQL names |
| `duckdb-tachiom/Makefile` | `TARGET_DUCKDB_VERSION=v1.5.4` |
| `duckdb-tachiom/Cargo.toml` / `Cargo.lock` | `duckdb` crate `1.10504.0`; `tachiom` git tag `v0.3.4` |
| `duckdb-tachiom/configure/venv` | `import duckdb` → version `1.5.4` |
| Existing artifacts | `build/release/duckdb_tachiom.duckdb_extension`, `libduckdb_tachiom.dylib` (not executed) |

**Build identity (pin):** Cargo-resolved `tachiom` git tag `v0.3.4` commit `2d1b2050d60eb28462f9d9c451c2fe7653cc4aa9` (`duckdb-tachiom/Cargo.lock` `source = git+https://github.com/TusKANNy/tachiom.git?tag=v0.3.4#2d1b2050d60eb28462f9d9c451c2fe7653cc4aa9`). This is `VERSION_MANIFEST.json` `tachiom_commit`.

Local tachiom checkout HEAD is **two documentation commits** past that tag (`69f6f3dc2eef3b543983eb71227bb65590e498a8`, describe `v0.3.4-2-g69f6f3d`): “Update README.md…” and “Update logo”. Checkout is recorded separately and is **not** the build identity. duckdb-tachiom depends on **git tag `v0.3.4`**, not local HEAD.

## Frozen SQL function names (from tests + `lib.rs:70-78`)

| SQL name | Kind | Provenance |
|---|---|---|
| `tachiom_build_files` | table function | `build_files.test`, `lib.rs:70` |
| `tachiom_load` | table function | `admin.test`, `lib.rs:71` |
| `tachiom_unload` | table function | `admin.test`, `lib.rs:72` |
| `tachiom_index_info` | table function | `admin.test`, `lib.rs:73` |
| `tachiom_search` | table function | `search.test`, `lib.rs:76` |
| `tachiom_search_flat` | table function | `search.test`, `lib.rs:77` |
| `tachiom_match` | scalar | `match.test`, `lib.rs:78` |

Extension require name in tests: `require duckdb_tachiom`.

### `tachiom_build_files`

Positional (`build.rs:269-270`, `build_files.test:13-20`):

```text
tachiom_build_files(name, vectors_path, token_ids_path, doclens_path
  [, doc_keys_path := ..., output_path := ..., total_centroids := 'auto'|int,
     normalize := false, center_dataset := false])
```

Status row columns (`build.rs:260-265`, `build_files.test:12-22`): `name, n_docs, n_tokens, dim, n_centroids, path`.

Defaults that **differ from PythonUsage.md**:

- duckdb-tachiom `normalize` default **false** (`build.rs:283`; `build_files.test:31-35`)
- Python API `normalize=True` (`PythonUsage.md:45`)

Do not silently adopt the Python default inside SQL.

PQ minimum: corpus must have enough tokens for PQ codebook (`build.rs` error “corpus has only {n_tokens} token(s), but PQ codebook”; tests use 256 tokens = 8 docs × 32 tokens). `python.rs` `PQ_KSUB = 256`.

`Tachiom<32>` means **PQ subspaces M=32**, not embedding dim 32 (`python.rs:27-29`; `lib.rs:8`). Test fixtures happen to use **token vector dim 32**. Production token dim is whatever the multi-vector encoder emits (mdenseon is 768 **dense**; multi-vector token dim is a separate unfrozen encoder).

### `tachiom_load` / `unload` / `index_info`

`tachiom_load(name, path)` → `(name, n_docs, dim, source)` where `source` is `envelope` or `native` (`admin.test:26-30`).

Envelope magic `b"\x93DBTACHIOM"` (`envelope.rs:66`); `ENVELOPE_VERSION = 1` (`envelope.rs:50`). Envelope = bincode **1.3**. Native tachiom files = bincode **2.x** via `Tachiom::load_index`. Native load reports `n_tokens=0` (`admin.test:72-76`).

`tachiom_unload(name)` → `(name, bool)` ; missing name returns `false`, not error (`admin.test:51-55`).

`tachiom_index_info(name)` columns used in tests: `name, dim, n_docs, n_tokens, n_centroids, normalize, center_dataset, centroids_hnsw_bytes, inverted_lists_bytes, offsets_bytes, residuals_bytes, total_bytes`.

### Search

`tachiom_search(name, query LIST(LIST(FLOAT)) [, k, k_centroids, k_docs_to_score, ef_search, alpha, beta, lambda])` → rows `(rank BIGINT, doc_key BIGINT, score FLOAT)` best first (`search.rs:6-19`, `search.test:22-28`).

`tachiom_search_flat(name, query LIST(FLOAT), n_tokens := N, ...)`.

`tachiom_match` returns `LIST(STRUCT(rank, doc_key, score))`; unnest equals `tachiom_search` (`match.test:1-2`).

Defaults (`search.rs:72-76`, `python.rs:489-495`):

| param | default |
|---|---|
| `k` | 10 |
| `k_centroids` | 20 |
| `k_docs_to_score` | 500 |
| `ef_search` | `k_centroids * 3 / 2` (30 when k_centroids=20) |
| `alpha` | `0.45` (Some) |
| `beta` | None |
| `lambda` | None |
| `MAX_K` | 10_000 (`search.rs:70`) |

`rank` in the golden `search.test:26-28` is **0-based** (`0  1000  85.38252`). Higher score is better (self-hit). Scores are **not** proven cosine-in-[0,1]; Flock must still normalize to “higher is better” at the RAG boundary (plan §3.8).

Query dtype in SQL is `FLOAT` (f32). Python/native build inputs: `vectors.npy` `[N, dim]` **f16** (`PythonUsage.md:21`).

### Python/native build (tachiom crate)

`Tachiom.build(...)` kwargs from `PythonUsage.md:36-49` / `python.rs`: `total_centroids`, `tac_n_iter=10`, `pq_sample_size`, `pq_n_iter=10`, `normalize=True`, `pq_seed=42`, `hnsw_m=32`, `ef_construction=1500`, `pq_subspaces=32` (only 32 supported).

`search(query[n_tokens, dim] f32)` → `(scores f32, doc_ids u32)` with sentinels `−∞` / `u32::MAX`.

`batch_search(..., num_threads=0)`: 0 = all cores.

Index type is `Send + Sync` (`lib.rs:63`).

## ABI blocker vs duckdb-pgagent

| | duckdb-tachiom (this freeze) | v7 target |
|---|---|---|
| Makefile | `TARGET_DUCKDB_VERSION=v1.5.4` (`Makefile:12`) | duckdb-pgagent `a1f0ab191185c0852b162adc6feb206822dc9daa` |
| C API | `USE_UNSTABLE_C_API=1` (`Makefile:9`); `#[duckdb_entrypoint_c_api]` (`lib.rs:67`) | fork tag `duckdb-special-20260829-g1` |
| Python venv | `duckdb-1.5.4` | v7 Python binding not this freeze |
| rustc | `nightly-2026-07-20` (`rust-toolchain.toml`) | n/a |

duckdb-pgagent `duckdb.h` comments mention stable C API **v1.5.6** for several symbols. That is **not** a proof the loadable extension built for v1.5.4 unstable C API loads into `a1f0ab1911`. Treat as blocker.

Existing `build/release/*.duckdb_extension` were **not** executed against duckdb-pgagent (would risk mutating the other fork). Static E1 only.

## Open unknowns

- Token-vector dim for the v7 multi-vector path (test dim 32 ≠ mdenseon 768 dense).
- Transaction / writer vs reader visibility of the in-memory registry (connection-local vs process-global): not E2.
- Update/delete in-place: tests rebuild/replace by name; no incremental delete API in the SQL surface.
- Artifact SHA-256 of `duckdb_tachiom.duckdb_extension` **not computed** this session (do not invent).

## Backend gate

Until duckdb-tachiom is rebuilt **for** duckdb-pgagent `a1f0ab1911` and search tests pass on that binary: return `RAG_MULTI_VECTOR_UNAVAILABLE`. BM25/dense may ship independently (plan §3.8).
