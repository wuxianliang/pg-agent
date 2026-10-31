# v24/s13 — Tool/Plugin ABI W1 vectors, W2 contracts and W3 registry/transport

This stage establishes the W1 contract and fixed vectors for ABI design §10 M1, adds the W2 pure host contract components, and implements W3 registry approval and independent line-json v2 transport. It contains reviewed data, independent Python/Node reference functions, and production host modules. W3 gates use process stubs; dispatcher/worker/provider wiring and filesystem-tool behavior remain downstream work. The W1 inventory and vector format are pinned in [`vectors/README.md`](vectors/README.md) and [`vectors/design_conformance.json`](vectors/design_conformance.json).

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

Exit 0 with the command-specific `[passed]` marker is passed; exit 2/`[SKIP]` is unverified and blocks W2 completion; exit 1 or a missing marker is failed. W2 covers four of the nine s13 gates; W3 adds `test_registry.py` and `test_line_json.py` below; `test_tools.py`, `test_lifecycle.py`, and `test_node.py` remain downstream.

W2 reproduces 40 W2-domain cases from production code: descriptor 16 (including 9 canonical byte cases), schema 9, renderers 7 (including 21 inner golden cases and three digest pairs), and results 8. The three `m4_pending` result/lifecycle cases are asserted to remain unexecuted. A post-review hardening pass adds internal probes for decoder normalization, the `J` value domain, deep finite values, `ToolDispatchResult` outer-shape checks, renderer exception precedence, and object-shaped schemas; it does not change any vector case ID, status, owner, or expected value. The s13 checks are extension evidence; closeout remains 11/11 and s13 is not a twelfth closeout item. W2 does not prove M2 completion, W3 registry/line-json v2 behavior, W4 dispatcher/worker/provider wiring, filesystem tool semantics, or replay.

## W3 registry approval and line-json v2

W3 adds `ApprovedTool`, `ToolBinding`, `ApprovedPlugin.from_manifest()`, union registry matching, and an independent v2 frame builder/parser selected by the approved entry's protocol. The v1 approval fields and byte behavior remain covered by B0 and W3 compatibility probes.

Run the two W3 gates from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_registry.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_line_json.py
```

Exit 0 plus the command-specific `[passed]` last line is passed; exit 2/`[SKIP]` is unverified and blocks W3 completion; exit 1 or a missing marker is failed. Registry coverage is 17 cases, three manifest byte cases, 14 construction reasons and six zero-spawn match paths. Transport coverage is 10 cases, seven frame byte cases, all 55 parse rows (46 invalid + nine whitespace), five preflight rejections and four unknown outcomes; the marker also confirms `v1_bytes_unchanged=true`. The final registry gate additionally checks noncanonical bytes/UTF-8 str manifest identity and successful `ApprovedTool` closure recompilation; the transport gate preserves and exercises the v1 `run(adapter=...)` keyword interface. The two gates use stubs and do not open database/network/Node connections or prove real subprocess lifecycle behavior.

The measured 26-command serial run passed every command, including all inherited checks. Evidence and limitations are in the [W3 execution record](../../docs/reviews/v24-tool-plugin-abi-w3-execution-2026-10-31.md). Frozen vector labels remain unchanged (`frames_v2` stays `m2_pending`; artifact evidence stays `m3_pending`). W3 is extension evidence and **does not prove M2 completion**. Closeout remains **11/11**, and s13 is not a twelfth closeout item. Dispatcher/worker/provider wiring, filesystem semantics, pagination, 12-second timing, artifact digest computation and replay remain downstream.

## W4a dispatcher, worker and provider wiring (M2)

W4a wires the W3 approval model and line-json v2 transport into the live paths: `tool_pages.validate_page` enforces the §5.6 success-page relations before rendering, `plugins._tool_v2` follows the fixed thirteen-step order, `worker._execute_tool` uses the handler-provided `model_text`, `deepseek._tools` accepts v2 descriptors, and `registry._ApprovedEntry.environment()` injects the approved `V24_WORKSPACE_ROOT` when the allowlist names it. `w4_stub_plugin.py` is a test asset only; `plugins/fs_read.py` and `plugins/fs_tools.js` remain W4b.

Run the two new gates from the repository root:

```bash
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_pages.py
env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1 uv run python v24/s13/test_wiring.py
```

Exit 0 plus the command-specific `[passed]` last line is passed; exit 2/`[SKIP]` is unverified and blocks W4a; exit 1 or a missing marker is failed. `test_pages` is DB-free (5417 page cases, 4281 oracle differentials, two documented reference gaps excluded one-sided). `test_wiring` uses PostgreSQL and local stub subprocesses only; it covers provider projection bytes, handler normalization, six pre-spawn zero-spawn paths (sentinel + `--spawn-log`), eleven end-to-end v2 scenarios, per-tool timeouts, lease using the tool timeout, and the 11-byte model-text vector. It prints `[scope] passed base=c8c4bd0 checks=6` before its marker.

The measured 29-command serial run on base `c8c4bd0` passed every command; rows 14–24 are the eleven frozen closeout commands, so closeout remains **11/11** and s13 is not a twelfth closeout item. **M2 is complete** after W4a: the four M2 gates (`test_descriptor`, `test_registry`, `test_line_json` plus the W4a wiring gate) are green, G9/G10/Node and v1 golden bytes are unchanged, and no real provider was called.

This completion does **not** mean real filesystem tools, pagination convergence, mixed batch, crash/restart, replay, or the 12-second budget are verified. W4b (filesystem read/list/search) and W4c (lifecycle/replay/Node) remain downstream. Evidence, command times, last lines and hashes are in the [W4a execution record](../../docs/reviews/v24-tool-plugin-abi-w4-execution-2026-10-31.md); evidence directory `/tmp/w4a-20261031T025906/`.

## Execution

Capture is candidate generation, not a gate. It requires two fresh external destinations and byte comparison before promotion. Checkers are read-only, have no re-bless mode, and do not execute production tools.

2026-10-30 W1 execution: both independent captures matched byte-for-byte; contract inventory passed (10 suites/71 cases); Python/PostgreSQL/Node fixed-vector comparison passed (9 canonical cases); all 20 final serial W1/B0/inherited checks passed, recorded in the [`W1 execution record`](../../docs/reviews/v24-tool-plugin-abi-w1-execution-2026-10-30.md). No provider call or real filesystem tool execution was performed.

2026-10-30 W2 execution: the four W2 gates plus all 20 inherited W1/B0/closeout/G9/G10/Node/multilingual commands exited 0 with no exit 2/SKIP; evidence is recorded in the [`W2 execution record`](../../docs/reviews/v24-tool-plugin-abi-w2-execution-2026-10-30.md). No provider call or real filesystem tool execution was performed.
