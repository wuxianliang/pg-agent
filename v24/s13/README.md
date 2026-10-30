# v24/s13 — Tool/Plugin ABI W1 vectors and W2 host contracts

This stage establishes the W1 contract and fixed vectors for ABI design §10 M1, and adds the W2 pure host contract components. It contains reviewed data, independent Python/Node reference functions, and DB-free production host modules. It does not change runtime wiring and does not prove production validation, rendering, dispatch, or filesystem-tool behavior. The W1 inventory and vector format are pinned in [`vectors/README.md`](vectors/README.md) and [`vectors/design_conformance.json`](vectors/design_conformance.json).

## W1 vectors

W1 format: `v24-tool-plugin-abi-w1-vectors-1`, with 10 suites and 71 fixed case IDs. B0 golden vectors/checker and the frozen v24 closeout remain separate; closeout is still 11/11. Descriptor bytes use PostgreSQL `jsonb::text`; request frames, renderers, manifests, and model text each use their own ABI serialization rule. The three renderer digests are frozen as `provisional_w2_pending`; W2 reproduces them byte-for-byte without editing the frozen labels. Artifact digest and timing evidence remain M3-pending; replay behavior remains M4-pending.

Run the read-only checks from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_contracts.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_vectors.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_vectors.py --node
```

## W2 host contracts

W2 adds five pure modules under `v24/host/`: `canonical.py` (PostgreSQL canonical text, `J`, strict JSON, deep-freeze), `tool_schema.py` (closed schema subset), `renderers.py` (three host renderers, immutable registry, embedded goldens), `descriptor.py` (descriptor v2 validation), and `tool_results.py` (v2 envelopes, model text, budget measurement, frame classification). All five are synchronous, deterministic, and free of file/database/network/clock access.

Run the four W2 gates from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_descriptor.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_schema.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_renderers.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_results.py
```

Exit 0 with the command-specific `[passed]` marker is passed; exit 2/`[SKIP]` is unverified and blocks W2 completion; exit 1 or a missing marker is failed. W2 covers four of the nine s13 gates; `test_registry.py`, `test_line_json.py`, `test_tools.py`, `test_lifecycle.py`, and `test_node.py` remain W3/W4.

W2 reproduces 40 W2-domain cases from production code: descriptor 16 (including 9 canonical byte cases), schema 9, renderers 7 (including 21 inner golden cases and three digest pairs), and results 8. The three `m4_pending` result/lifecycle cases are asserted to remain unexecuted. The s13 checks are extension evidence; closeout remains 11/11 and s13 is not a twelfth closeout item. W2 does not prove M2 completion, W3 registry/line-json v2 behavior, W4 dispatcher/worker/provider wiring, filesystem tool semantics, or replay.

## Execution

Capture is candidate generation, not a gate. It requires two fresh external destinations and byte comparison before promotion. Checkers are read-only, have no re-bless mode, and do not execute production tools.

2026-10-30 W1 execution: both independent captures matched byte-for-byte; contract inventory passed (10 suites/71 cases); Python/PostgreSQL/Node fixed-vector comparison passed (9 canonical cases); all 20 final serial W1/B0/inherited checks passed, recorded in the [`W1 execution record`](../../docs/reviews/v24-tool-plugin-abi-w1-execution-2026-10-30.md). No provider call or real filesystem tool execution was performed.

2026-10-30 W2 execution: the four W2 gates plus all 20 inherited W1/B0/closeout/G9/G10/Node/multilingual commands exited 0 with no exit 2/SKIP; evidence is recorded in the [`W2 execution record`](../../docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md). No provider call or real filesystem tool execution was performed.
