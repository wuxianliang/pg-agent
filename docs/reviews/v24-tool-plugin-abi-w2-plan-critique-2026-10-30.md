# v24 Tool/Plugin ABI W2 plan critique — 2026-10-30

Baseline: only completed export lanes 2 and 3. `P` = `docs/plans/v24-tool-plugin-abi-w2-host-contracts-2026-10-30.md`; `E` = `prompt-exports/oracle-plan-2026-10-30-224833-w2-deep-plan-pure-ho-f664.md`.

## Highest-impact findings

1. **Descriptor validation can leak exceptions outside its four-reason ABI.** `P:251-253,268-290` does not translate `SchemaError` from steps 6–7, and step 14 calls legacy `pg_jsonb_text` before the full safety walk; that legacy code can raise raw `TypeError` or `ValueError` (`v24/host/registry.py:116-137`). Lane 3 explicitly requires normalization (`E:1753-1761`). Catch schema/canonicalization/encoding failures as `DescriptorError("invalid_descriptor")`; perform the safe-JSON walk before size serialization or catch around it, and test that no other exception type escapes.

2. **The `render.id` constraint is missing.** `P:264` specifies the key regex but only render version/digest; step 8's bare “id” (`P:277`) is not implementable precisely. Restore the lane-3 identifier regex `^[a-z][a-z0-9_.-]{0,127}$` (`E:1714`). The frozen rows rejecting `"X"` and a 129-character id prove this is required (`v24/s13/vectors/descriptor_v2.json:1094-1108`).

3. **The fail-closed renderer default introduces an unscheduled dependency and an unspecified bypass.** `descriptor.py` now depends on `renderers.RENDERERS` (`P:256-257,288,497`), yet W2-3 depends only on W2-1/W2-2 (`P:415,425-428`). Also, unconditional step 17 gives no meaning to explicit `render_registry=None`, while the descriptor gate requires a no-registry path (`P:286,401`). Specify the bypass and make W2-4 precede W2-3, or deliberately change the interface/test requirement before implementation.

4. **The schema public API diverges from both lanes without a recorded reason.** Both lanes use `validate(schema, instance)` and require explicit `kind` for `compile_schema` (`E:689-695,1589-1595`); `P:212-213` reverses the validate arguments and defaults `kind="output_schema"`. The default can silently skip the parameters-root closed-world check. Restore the lane API, or explicitly justify and migrate every caller; require `kind` so parameter compilation cannot accidentally use output semantics.

5. **The process-global validator cache is unnecessary and weakens ownership.** `P:233` mandates bounded `lru_cache` but gives no bound, lifecycle owner, or consumer. Lane 3's simpler design fully replaces it: return a closure capturing a deep-frozen schema and let W3 store that closure on its approved tool (`E:1631-1640`). The planned test only reuses a returned validator (`P:402`), which does not require global caching. Adopt the closure design; standalone `validate` self-checks, while the compiled closure avoids repeated self-checking.

6. **Schema semantics were generalized past the implementable lane contract.** Restore these lane-3 rules (`E:1603-1627`): type-specific keywords without `type` apply only to matching instance types; keywords tied to an impossible declared type are unsupported; do not invent cross-bound checks such as `minimum <= maximum`; enum payload arrays/objects do not count as schema nodes/depth. The nullable object/array union is explicitly accepted (`v24/s13/vectors/schema_v2.json:574-584`), and descriptor depth cases nest arrays inside `enum` (`v24/s13/vectors/descriptor_v2.json:1590-1652`), so these distinctions change acceptance and error precedence.

7. **Result failure behavior is under-specified even after combining both lanes.** `P:340-341` names three `ToolResultError` reasons but never assigns them per constructor/validator, especially malformed envelope versus content versus usage. Define that mapping and normalization of `TypeError`/`CanonicalError`; otherwise callers cannot rely on the closed vocabulary. Also make `assert_usage` require exactly `{wall_ms}` with a non-bool safe nonnegative integer, not merely “only allows” that key (`P:371`). Add negative envelope probes, since the vectors mainly prove positive envelopes.

8. **The error-message safety predicate was weakened into prose.** “No traceback/stack marker” and “no absolute path” (`P:370`) leave case sensitivity and matching boundaries unresolved. Restore the exact lane/reference predicate: markers `Traceback (`, `stack trace`, `DEEPSEEK_API_KEY=`, `OPENAI_API_KEY=`, NUL, and regex `(?:^|\s)(?:/\S*|[A-Za-z]:[\\/]|\\\\)` (`E:1928-1931`; `v24/s13/w1_reference.py:146-149`). Add non-vector positive/negative probes rather than relying on implementation-specific interpretations.

9. **Renderer lookup does not say whether digest participates, and its public reason lacks coverage.** Lane 3 distinguishes `by_id` (ignore digest so descriptor validation can report mismatch) from `lookup` (require complete id/version/digest, otherwise `renderer_not_approved`) (`E:1795-1803`). `P:312-323` only says “absent.” Pin that distinction and add internal probes for unknown id, unknown version, and wrong digest; no frozen descriptor row produces `renderer_not_approved` (`v24/s13/vectors/descriptor_v2.json:1081-1146`).

10. **Lane 3's unknown-result model-text rule was dropped.** `P:343-360,375` defines the record and success/failure joining but not unknown construction. Preserve the lane rule without wiring worker: success/failure use joined content; unknown has empty `model_text` and never creates a model continuation (`E:1935-1943`). If this belongs to W4 instead, move the whole construction contract there explicitly rather than leaving a partially specified W2 record.

11. **Renderer raw-text behavior needs the lane's explicit rule.** `P:327-331` gives formats but omits that text/context/LF/CR/NUL/quotes/slashes/Unicode separators are concatenated without secondary escaping or truncation (`E:1856`). Restore that sentence; the control-bearing search golden makes secondary escaping observably wrong (`v24/s13/vectors/renderers.json:605-652`).

12. **Chosen behavior lacks the negative tests needed to make it contractual.** Add non-vector probes for multi-fault precedence across the 17 descriptor steps (the vectors intentionally do not discriminate it), duplicate keys at depth, `NaN`/±`Infinity`, malformed UTF-8, non-object descriptor input, and compact-JSON non-string keys/floats/unsafe integers/lone surrogates. Do not edit frozen vectors; these are internal contract tests absent from both lanes' detailed gate matrices.

## Factual and reference corrections

- `P:50` cites `descriptor_digest` as `registry.py:131-136`; the function is at `v24/host/registry.py:140-144`. `P:152` cites the design SHA constant at `test_contracts.py:15`; it is at `v24/s13/test_contracts.py:10`, with full-file verification at `:42-43` and span verification at `:53-60`.
- `P:46` says registry imports only `hashlib/json/os/stat`; `dataclasses` and `pathlib.Path` also occur at `v24/host/registry.py:27-28`. Say “no host-module imports,” and remove only imports made unused by extraction.
- `P:507` says six moved definitions, but D1 moves seven when `RegistryError` is included (`P:107-116`). Enumerate them or correct the count so the old exception body is not left behind.
- `P:569` misreports lane 2 as requiring a PostgreSQL connection in `test_descriptor.py`. Lane 2 explicitly requires DB-free and assigns PostgreSQL proof to inherited `test_vectors.py` (`E:1127-1134`), agreeing with lane 3. Correct the Oracle record; the DB-free decision itself is sound.

## Decisions that materially affect implementation order

1. Is explicit `render_registry=None` a supported test-only bypass? If yes, document it and schedule W2-4 before W2-3; if no, remove the no-registry gate requirement. An injection-only alternative must be chosen before descriptor imports are written.
2. Is process-global compiled-validator reuse an actual W3 requirement, or only reuse of a returned closure? This determines W2-2 state ownership and whether W3 must add storage/lifecycle policy.
3. Does W2 own `ToolDispatchResult` construction semantics or only its dataclass? The answer determines whether unknown-result behavior and tests land in W2-5 or are explicitly deferred to W4.
