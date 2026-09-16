# MinerU identity freeze (Phase 0 PR3)

**Verdict: fixtures imported + generated; not live MinerU.** PDF golden is copied from DuckRAG P19-S. Code and legacy legs are tiny generated origin-shape files. This is **not** a live MinerU parse, not a 15GB snapshot recalculation, and **does not** mark `phase0_baseline_status.json` item `kohaku_mineru_range_trio` E2 (that is PR4).

| Item | Evidence |
|---|---|
| PDF `page_bbox` golden | **imported** — `v7/tests/fixtures/range_trio/pdf/p19-mineru-offline.pdf` size 672 sha256 `163c9ac8f7f857904793b01fa9f031cebbe83f186b9cfc3510b9a371e464922c`; canonical `content_list` two objects from `p19_mineru_process.py` |
| Code `source_line` | **generated** — `v7/tests/fixtures/range_trio/code/sample.py` (explicit Python; not Kohaku markdown) |
| Legacy `legacy_flat` | **synthetic** — `v7/tests/fixtures/range_trio/legacy/flat.txt`; not live `byzerai_store_duckdb.db` |
| Wheel identity | lock **field** `pypi_artifacts[0].sha256` `d4d678539782a7683d998e2914a52d96b5720676ce65658b29666b1f4d9dfd13` in `v7/evidence/locks/mineru/mineru-3.4.4.lock.json` (no `.whl` bytes in tree) |
| Snapshot identity | `profile.json` `pipeline_model.manifest_sha256` `8c4a6a53815e2a8f410d71350128d0db1276579ac9f50cd1dee56b165e4a4df6` (**not** the wheel lock). 187 files / 15GB **absent**; hash not recalculated this freeze |
| P19-S record | byte-identical `v7/evidence/duckrag/p19-s.json` size 19125 sha256 `ae77a11045b4ce9a26705b0665ee54d11f67f26e37b72755253f46c92b0dff55` |
| Live MinerU runtime | **still missing** — cache `$HOME/.cache/duckrag-wi1` not required for `--check` |

## Claimed

- In-tree PDF + `content_list` match DuckRAG P19-S / harness expected (sha/size verified 2026-08-30).
- Trio golden has three `range_origin`s: `page_bbox`, `source_line`, `legacy_flat`.
- PDF `line_start` / `line_end` are JSON `null`; `catalog_page=1`; bboxes in-page on 612×792.
- `not_live_mineru_runtime`, `not_live_kohaku_service`, `not_live_legacy_cache` are all true.
- Identity copies: `profile.json` (snapshot pin), wheel lock (wheel sha field), `uv.lock`, `requirements-arm64.txt` (84 hashes), `p19-cpython312-arm64.lock.json`, `p19-s.json`.

## Not claimed

- Live MinerU execution this freeze (`mineru_invoked_this_freeze: false`; historical `temp_and_output_removed: true`).
- Live Kohaku service or LanceDB index.
- Live `byzerai_store_duckdb.db` rows (legacy text is synthetic; `doc_alpha_0` is compatibility intent only).
- Recaclulated 187-file snapshot manifest (files absent).
- Recaclulated MinerU wheel bytes (lock field only).
- P19-E2E / production adapter (`p19_e2e_resolved: false`).
- Plan §3.14 diversity corpus (large PDF / multipage / table). Origin-shape only.
- `phase0_pass`, baseline item E2, evaluator changes, `canonical_mineru_contract_version`.
- OCI container digest / single-file weights (N/A identity; not this PR).

## Command

```sh
# Verify the committed golden and identity copies (does not write, does not import mineru):
uv run python v7/migration/range_trio_fixture.py --check
uv run python v7/tests/test_range_trio_fixture.py

# Regeneration is explicit and separate. Review git diff after --write:
# uv run python v7/migration/range_trio_fixture.py --write
```

`--write` and `--check` are mutually exclusive. **There is no `--live-parse` flag.** `--check` after `--write` in the same process would only compare the file it just overwrote. `--check` must not import `mineru` or read the 15GB snapshot cache.

DuckRAG copy source (HEAD at copy `0c6ad30b000ac8ef532947b7b997933b6f28feb0`): `/Users/wxl/Projects/repoprompt-ce-agno`.

## Operator re-run (optional; not this generator; not CI)

Historical P19-S is **not** this-freeze live E2. Re-provision stays in DuckRAG. Do **not** add `--live-parse` to `range_trio_fixture.py`. Do **not** copy `/Users/wxl/mineru.json`, wheelhouse, venv, or snapshot weights into pg-agent.

```bash
# DuckRAG tree, not pg-agent:
cd /Users/wxl/Projects/repoprompt-ce-agno
export DUCKRAG_P19_ROOT="$HOME/.cache/duckrag-wi1/p19-mineru-3.4.4"
export DUCKRAG_P19_WHEELHOUSE="$DUCKRAG_P19_ROOT/wheelhouse-pipeline"
export DUCKRAG_P19_VENV="$DUCKRAG_P19_ROOT/venv"
export DUCKRAG_P19_MODEL_CACHE="$DUCKRAG_P19_ROOT/model-cache"
export DUCKRAG_P19_WORK_ROOT="$DUCKRAG_P19_ROOT/work"

python -m benchmarks.duckrag_wi1.mineru_environment verify-contract --profile pipeline
python -m benchmarks.duckrag_wi1.mineru_environment verify-installed --profile pipeline
python -m benchmarks.duckrag_wi1.p19_mineru_process --profile pipeline
```

TLS CA belongs to the DuckRAG environment contract (`docs/local-environment.md`). pg-agent Phase 0 does not pin Proxyman. Live E2 promotion still requires recalculating the 187-file snapshot, verifying the 84-wheel closure, and a **this-freeze** parse of the in-tree PDF whose `content_list` matches the committed golden. Until then `live_runtime_missing` stays true.

## Frozen files

- `v7/tests/fixtures/range_trio/golden.v1.json` (`schema_version=flock-rag-range-trio-fixture/1`)
- `v7/tests/fixtures/range_trio/pdf/p19-mineru-offline.pdf`
- `v7/tests/fixtures/range_trio/pdf/content_list.json`
- `v7/tests/fixtures/range_trio/code/sample.py`
- `v7/tests/fixtures/range_trio/legacy/flat.txt`
- `v7/evidence/locks/mineru/profile.json`
- `v7/evidence/locks/mineru/mineru-3.4.4.lock.json`
- `v7/evidence/locks/mineru/uv.lock`
- `v7/evidence/locks/mineru/requirements-arm64.txt`
- `v7/evidence/locks/mineru/p19-cpython312-arm64.lock.json`
- `v7/evidence/duckrag/p19-s.json`

Do not treat this as live corpus E2 for MinerU runtime, Kohaku service, or legacy cache.
