# Critique: v6 DuckDB grammar-extension bootstrap plan vs Oracle export baseline

Date: 2026-08-29
Plan: `docs/plans/v6-duckdb-grammar-extension-bootstrap-2026-08-29.md`
Baseline: `prompt-exports/oracle-plan-2026-08-29-180628-v6-grammar-bootstrap-17c1.md` (generated plan only, from `# 1. Summary`)

Spot-checks performed (all confirmed): `worker.py:212` `_invoke_llm` (no callers), `worker.py:315-337` inline LLM retry loop with two `payload["messages"]` uses; `duckdb_runtime.py:132-145` static `_open_connection` with dev365/`SELECT version()` gate; `DuckSession` dataclass with `lock`/`closed` set in `__post_init__`; `duckdb_processor.py:25` `self.sessions = DuckSessionManager(...)`; all nine constructor sites; `duckdb_validation.py:63-66` fallback `duckdb.connect()`; `prepare_llm_request` (`v3/pg_agent_pgmq.sql:355-383`) puts `run_id` in the `llm_requests` payload, so the D4 seam `payload.get("run_id")` is valid.

## 1. Implementation-bearing content missing or weakened in the plan

1. **SHA-256 format validation dropped.** Export §3.1 ("When enabled"): the hash "must match exactly 64 hexadecimal characters, compared case-insensitively" — i.e. a format check that fails fast at startup. The plan's env table for `PG_AGENT_DUCKDB_GRAMMAR_EXTENSION_SHA256` only says "缺省则用源码常量"; the comparison rule ("hex 大小写不敏感") appears under hash lifecycle but the 64-hex format gate is gone. The prototype already has `_SHA256 = re.compile(r"[0-9a-f]{64}", re.I)` (`duckdb_grammar.py:22`), so this is a spec regression, not new work. Consequence of omission: a malformed hash env value silently becomes a digest mismatch at startup hash time instead of a configuration error at `validate()`. Restore the format check in `validate()` (enabled mode only).

2. **W7 accepted-error-types broadening dropped.** Export file-impact for `test_dialect_guardrails.py`: "Expand the accepted expected error types to include `DUCK_ARGUMENT_ERROR`." The plan's W7 row keeps the `con=None` test and the static-recipe assertion but omits this. If any existing W7 assertion enumerates expected error types, removing the fallback changes what `con=None` raises and the test update must land with the validator change (W6), not later. Reinstate the sentence in the W7 row (or in W6) so the error-type expectation change is tracked.

3. **Fake-connector injection mechanism weakened.** Export specifies the fake is installed "by temporarily replacing the `duckdb` module binding used by `v6.session_durability.duckdb_grammar`, using `unittest.mock` or equivalent." The plan says only "fake `duckdb` 注入". Given `duckdb_grammar.py` does `import duckdb` at module top, patch target matters (`v6.session_durability.duckdb_grammar.duckdb`, not the global `duckdb`); keep the export's explicit binding instruction to avoid the classic wrong-target patch.

## 2. Under-specified seams, contradictions, incorrect references

4. **Contradiction: "无路径的 CI 只能跑 fake default-off" is impossible.** Both docs claim CI without the local artifact paths can still run default-off fake tests. But W2 makes `duckdb` resolve to a `[tool.uv.sources]` **local wheel path** (`../duckdb-python-pgagent/dist-special-g1/...whl`). On any machine lacking that sibling checkout, `uv sync --locked` fails before any test runs — there is no "CI without the wheel" mode at all. The plan must either (a) state plainly that every v6 runner needs the wheel file present (extension optional), or (b) use a conditional/non-path source strategy. As written, the portability risk section describes a configuration that cannot exist.

5. **Bootstrap failure vs queue semantics unspecified.** `get_or_open` bootstrap failure is wrapped as `DUCK_GRAMMAR_BOOTSTRAP_FAILED`, but neither doc says what `DuckDBWorkerProcessor.process()` / `AgentWorker` do with it: is the `duck_heavy_requests` message a terminal structured failure (fail the run, no retry), or does it follow the normal exception path into visibility-timeout retry and eventually DLQ? A deterministic config error (hash mismatch, missing file) retried N times and DLQ'd is wasted work and noisy; a transient `LOAD` error arguably deserves retry. Pick one and record it — this changes `_open_connection` error wrapping (deterministic config/identity/hash errors should probably be terminal; `duckdb.Error` from `connect`/`LOAD` maybe not).

6. **Wrapping scope of `DUCK_GRAMMAR_BOOTSTRAP_FAILED` unspecified.** Plan says "GrammarExtensionError 在 `_open_connection` 包成" session error. But bootstrap can also raise raw `duckdb.Error`/`OSError` (connect failure, unreadable file at rehash time). Do non-`GrammarExtensionError` exceptions get wrapped too, or propagate raw? Both docs silent; the fake tests should pin whichever is chosen.

7. **`PG_AGENT_DUCKDB_GRAMMAR_ENABLE_EXTERNAL_ACCESS` boolean parse set undefined.** The ENABLED row enumerates the accepted tokens; the external-access row says only "缺省 false, true 始终拒绝". Is `"maybe"` an error or false? The plan's file-impact row says "严格布尔解析" (export: "strict boolean parsing for the two boolean environment variables"), which implies same token set — say so in the env table so the disabled-mode rejection test has a contract to assert.

8. **`_open_connection` staticmethod call-site check.** Converting `@staticmethod _open_connection()` to an instance method is safe only if nothing calls it on the class. Plan/export assume sole caller is `get_or_open` (`duckdb_runtime.py:148-183`). Grep confirms no other caller in v6 today, but the W11 audit list only covers `duckdb.connect(` / `validate_read_query(`; add `_open_connection(` to the final audit grep so a late-added caller can't bypass bootstrap.

## 3. Details disproven by code / unnecessary

9. **Export's `test_v6.py` hedge is disproven; plan is right.** Export: "If the file only invokes the production worker entry point, no code change is required." Code shows `v6/integration/test_v6.py:26` constructs `DuckDBWorkerProcessor(uri,resolver=resolver)` directly, so injection is required — the plan's correction stands; no action beyond keeping it.

10. **Plan line references slightly stale but harmless.** `duckdb_runtime.py:139-141` gate is actually ~137-141; `duckdb_probe/test_duckdb_probe.py:12-13` constants are at 11-12. Not worth churn; no correction needed.

11. **Nothing in the plan is disproven as unnecessary.** The measured hashes, D3/D4/D10 resolutions, and constructor-site list all match the code. In particular, keeping both `_invoke_llm` and the inline `process_message` loop updated is correct: `_invoke_llm` exists and takes `payload` (worker.py:212-213), so leaving it un-augmented would be a real latent bug.

## 4. Absent from both export and plan

12. **Bootstrap is outside `interrupt()`/timeout coverage.** Both docs say "现有 interrupt() 超时不变", but bootstrap (startup hash of an 8.6 MB file + `LOAD` of unsigned native code) runs synchronously inside `get_or_open` under `_manager_lock`, before any session exists — the existing query-timeout/interrupt machinery by definition cannot cover it. A hanging `LOAD` blocks the worker thread holding the manager lock, freezing all runs on that manager. At minimum, document this; ideally note whether DuckDB `LOAD` is interruptible and whether any bound is acceptable. This is a genuine failure-behavior hole, not scope creep: the plan introduces a new blocking native call on the queue-processing path.

13. **PG status OPEN vs hydrate failure ordering.** Plan preserves "bootstrap → insert dict → PG OPEN → hydrate". For the new failure mode (run_schema definitions with `|>` + disabled worker), the session row is already stamped OPEN in PG before hydrate fails. Both docs say "走现有 degraded 路径" — fine if the existing path closes the session and stamps a non-OPEN status, but neither doc names that path or its PG end-state. One sentence citing the existing degraded-status transition would close the lifecycle question (who closes the in-memory session, what status the row ends in, whether retry re-bootstraps).

14. **Prompt-fragment caching vs retry payload logging.** `_messages_for_llm` copies payload messages; the plan notes the same payload "may be retried or logged". Neither doc says whether the augmented list is what gets logged for the LLM call — if logs are meant to reflect what the model saw, log the augmented copy, not the payload. Testability: the W8 unit tests should assert which object is passed to `llm_fn`/`call_llm` (identity check), not just content.

15. **Capabilities on `DuckSession` vs `__post_init__` defaults.** `DuckSession` sets `lock`/`closed` in `__post_init__`; adding required `capabilities` is fine, but any test constructing `DuckSession(...)` directly (bypassing the manager) will break. Neither doc calls for a grep of direct `DuckSession(` construction in tests; add to W11 audit (cheap, same class of sweep as the constructor-site search).

## 5. Questions that would change design or order

16. **Terminal vs retry for bootstrap failures (see #5).** If terminal, `DuckDBWorkerProcessor.process` needs a catch-and-fail-run path, which is a W4/W5 design point and should land before W8 prompt work; if retry/DLQ, the fake tests need a retry-behavior case. Answer first.

17. **Is `LOAD` of an unsigned extension interruptible/cancellable on the fork?** If yes, should bootstrap wire into the existing interrupt path? If no, is an unbounded synchronous `LOAD` under `_manager_lock` acceptable for a demo-only opt-in? The answer decides whether #12 is documentation-only or requires a design change.

18. **Does any consumer construct `DuckSession` directly (tests, demo)?** If yes, "required field, no default" (D7) forces edits beyond the listed files; if the answer is manager-only, D7 stands as-is.

## Verdict

The plan preserves the export faithfully; the known corrections are consistent with the code. The only true contradictions are #4 (impossible CI claim) and the missing queue-semantics decision (#5/#16); the only clear spec regressions vs the export are #1 and #2. Everything else is under-specification worth one decision each, not rework.
