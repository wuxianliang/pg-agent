# mdenseon dense embedding contract (Phase 0 WI-3)

Evidence level: **E1** for harness / fixture / lock / prior evidence record. **E0** for live weights on disk this session.

Related backend: **dense / mdenseon adapter is BLOCKED** until `model.safetensors` and `tokenizer.json` are present and match the lock digests. Do not invent a SHA. Do not implement a fake embedder.

This session did **not** re-run `p16_mdenseon.py`. `/Users/wxl/Projects/repoprompt-ce-agno/docs/investigations/duckrag-wi1/p16.json` is a prior completed evidence record (2026-08-05), inspected as source, not re-executed.

## What was read

| Path | Role |
|---|---|
| `/Users/wxl/Projects/repoprompt-ce-agno/benchmarks/duckrag_wi1/p16_mdenseon.py` | Parent harness |
| `.../p16_worker.py` | Isolated encode worker |
| `.../fixtures/p16-mdenseon.json` | Golden invariant fixture |
| `.../locks/mdenseon-a5fdb000.lock.json` | Model file manifest |
| `.../locks/p16-cpython312.lock.json` | Wheel closure (opened; not copied) |
| `.../docs/investigations/duckrag-wi1/p16.json` | Prior run record |

Repo at inspection: `0c6ad30b000ac8ef532947b7b997933b6f28feb0`.

Live model dir from that record (`/Users/wxl/.cache/duckrag-wi1-phase3/models/mdenseon-a5fdb000f7a21da96c3bddde3a782ef777316df3/model.safetensors`): **absent** this session (`WEIGHTS_ABSENT`). HuggingFace hub cache `models--lightonai--mDenseOn`: **absent**.

## Frozen fields (from SOURCE, not invented)

### Model identity (lock)

`locks/mdenseon-a5fdb000.lock.json`:

- `model_id`: `lightonai/mDenseOn`
- `revision`: `a5fdb000f7a21da96c3bddde3a782ef777316df3`
- `source`: `https://huggingface.co/lightonai/mDenseOn`
- `library_name`: `sentence-transformers`
- `license`: `apache-2.0`
- `lock_format`: `duckrag-wi1-upstream-model/1`

Locked files (path / size / identity):

| path | size | identity |
|---|---:|---|
| `.gitattributes` | 1570 | git_blob_oid `52373fe24473b1aa44333d318f578ae6bf04b49b` |
| `1_Pooling/config.json` | 89 | git_blob_oid `2236c262f1f83c50f7c304e98a8d1413980280df` |
| `README.md` | 19955 | git_blob_oid `5421dd3ed82e77b9d4a0ae12c5dec71cb84f60fa` |
| `config.json` | 1932 | git_blob_oid `b41719e26d9888f68bdf1b737d8fac6a7b5f3de1` |
| `config_sentence_transformers.json` | 299 | git_blob_oid `fbcfddf0e2a560bd5bff0eca3ea4b699f762e85d` |
| `model.safetensors` | 1227771776 | **lfs_sha256** `a336c49fc679aeb23969114b12fb7317804da3cc7d8bc214818009dea39d545c` |
| `modules.json` | 277 | git_blob_oid `45d2436b717b3a70d63c0df4ab2c49d5cdb02c5b` |
| `sentence_bert_config.json` | 241 | git_blob_oid `d2cd15826913bba6e43310063d75883bb0b7b842` |
| `tokenizer.json` | 34363287 | **lfs_sha256** `a086e6a7efb90bbab8e379a63f3463fb13e6256ebec3343c1f1612cab693935b` |
| `tokenizer_config.json` | 662 | git_blob_oid `91e01d28d92a58ab0571e5f1ba7f8dd336e48b15` |

`p16_mdenseon.py:44` `EXPECTED_DIMENSION = 768`.

`p16_mdenseon.py:41` `MODEL_LOCK = benchmarks/duckrag_wi1/locks/mdenseon-a5fdb000.lock.json`.

### Fixture invariants (`fixtures/p16-mdenseon.json`)

- `golden_version`: `duckrag-mdenseon-invariant/1`
- `schema_version`: `1`
- `normalization.algorithm`: `float32-l2/1`
- `normalization.norm_tolerance`: `0.00001`
- `normalization.zero_norm_policy`: `reject`
- `same_role_cosine_max_exclusive`: `0.999999`
- `safety_allowance_tokens`: query `0`, document `0`
- `boundary_generator.version`: `duckrag-token-boundary/1`

Worker L2 (`p16_worker.py:26-33`): `float32` array; if norm non-finite or `== 0.0` → `ValueError`; divide by pre-norm; reject zero-norm **before** provider reuse.

Empty/whitespace rejected **pre-provider** (`p16_worker.py:102-106`, `:132`).

### Encode API (worker)

`SentenceTransformer.encode` (`p16_worker.py:167-175`):

- `prompt_name` in `{query, document}`
- `batch_size` as passed
- `precision="float32"`
- `convert_to_numpy=True`
- `normalize_embeddings=False` (application L2, not provider L2)

Prompts asserted by harness (`p16_mdenseon.py:447`): `query: ` and `document: `.

Device: `cpu` (`p16_worker.py:220-224`). `torch.set_num_threads(min(4, os.cpu_count() or 1))` (`p16_worker.py:213`). Parent env `OMP_NUM_THREADS=4`, `MKL_NUM_THREADS=4`, `TOKENIZERS_PARALLELISM=false` (`p16_mdenseon.py:262-264`). Determinism: `torch.use_deterministic_algorithms(True)`, `torch.manual_seed(0)` (`p16_worker.py:214-215`).

Calibration batch sizes exercised: `1, 4, 8` (`p16_worker.py:446`). This is a harness measurement grid, **not** a frozen production batch size. Production must still pin an explicit batch.

### Prior evidence record (not re-run)

`p16.json` (inspected) recorded, among other things:

- observed dimension `768`
- `config_model_type` `modernbert`; class `SentenceTransformer` / `ModernBertModel`
- `runtime_max_seq_length` `8192`; effective query/document budget `8187` (8192 − 3 prompt tokens − 2 specials − 0 safety)
- `backend_tokenizer_json_sha256` `3fbb5d99acfcf5b33b01c59a8fd2eeb2529137e38a7f20713252c40b173357f6`
- provider truncation: untruncated 8193 → provider 8192
- lock `model.safetensors` sha256 matched `a336c49f…` in that run
- dependency versions: numpy `2.5.1`, sentence-transformers `5.4.1`, tokenizers `0.22.2`, torch `2.6.0`, transformers `5.6.2`
- CPython `3.12.13` arm64; `execution_backend` `cpu_float32`

Those numbers are **cited from the evidence file**, not re-measured here. Reuse requires a new E2 on the target v7 runtime with the same lock.

Same-role text must **not** produce identical query vs document vectors (`p16_mdenseon.py:453`).

## Open unknowns

- Live weights/tokenizer files: **missing** this session. E0 for “weights present”.
- Thread-safety of `SentenceTransformer` across connections: not proven beyond the single-process worker.
- Production batch size / multi-thread pool for Flock adapter: not frozen (harness used batch 1 for golden encode, 1/4/8 for calibration).
- GPU/MPS path: out of contract (`device=cpu` only).

## Backend gate

Do not enter Phase 1/3 dense implementation until:

1. `model.safetensors` sha256 `a336c49fc679aeb23969114b12fb7317804da3cc7d8bc214818009dea39d545c`
2. `tokenizer.json` sha256 `a086e6a7efb90bbab8e379a63f3463fb13e6256ebec3343c1f1612cab693935b`
3. remaining lock files match size + git_blob_oid
4. encode shape `[N, 768]` float32; application L2; zero-norm reject

Mismatch → `RAG_VECTOR_DIMENSION_MISMATCH` / `RAG_DENSE_UNAVAILABLE`. No pad/truncate/reshape.
