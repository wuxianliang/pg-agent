# v24/s13 — Tool/Plugin ABI W1 vector contract

This stage establishes the W1 contract and fixed vectors for ABI design §10 M1. It contains reviewed data and independent Python/Node reference functions; it does not change production code or prove production validation, rendering, dispatch, or filesystem-tool behavior. The W1 inventory and vector format are pinned in [`vectors/README.md`](vectors/README.md) and [`vectors/design_conformance.json`](vectors/design_conformance.json).

W1 format: `v24-tool-plugin-abi-w1-vectors-1`, with 10 suites and 71 fixed case IDs. B0 golden vectors/checker and the frozen v24 closeout remain separate; closeout is still 11/11. Descriptor bytes use PostgreSQL `jsonb::text`; request frames, renderers, manifests, and model text each use their own ABI serialization rule. The three renderer digests are provisional and remain W2-pending. Artifact digest and timing evidence remain M3-pending; replay behavior remains M4-pending.

Run the read-only checks from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_contracts.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_vectors.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_vectors.py --node
```

Capture is candidate generation, not a gate. It requires two fresh external destinations and byte comparison before promotion. Checkers are read-only, have no re-bless mode, and do not execute production tools. Exit 0 with the command-specific `[passed]` marker is passed; exit 2/SKIP is unverified and blocks W1 completion.

2026-10-30 execution: both independent captures matched byte-for-byte; contract inventory passed (10 suites/71 cases); Python/PostgreSQL/Node fixed-vector comparison passed (9 canonical cases); all 20 final serial W1/B0/inherited checks passed, recorded in [`W1 execution record`](../../docs/reviews/v24-tool-plugin-abi-w1-execution-2026-10-30.md). No provider call or real filesystem tool execution was performed.
