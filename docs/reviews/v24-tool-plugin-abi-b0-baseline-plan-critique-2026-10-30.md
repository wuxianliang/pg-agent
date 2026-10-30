# v24 Tool/Plugin ABI B0 baseline plan critique

## Scope and assessment

Reviewed `docs/plans/v24-tool-plugin-abi-b0-baseline-2026-10-30.md` (`PLAN`) and only the three **Generated Plan** responses in `prompt-exports/oracle-plan-2026-10-30-094701-b0-deep-plan-v1-c264-ec41.md:121-1411` (`EXPORT`). The composed prompt, selection dump, and post-group metadata were not treated as baseline plan text.

The current `PLAN` is still the 37-line draft, not an executable Deep Plan. The export supplies much of the missing implementation detail, but its three lanes are independent and sometimes contradictory; they cannot be concatenated or silently merged. The findings below are limited to the requested B0 omissions, seams, incorrect claims/refs, ownership and testability constraints, and material order/scope decisions. This was a static review: no gates, provider calls, or probes were run.

### 1. B0 has no operational completion, gate-evidence, or source-identity contract

**High — the draft cannot distinguish a verified B0 candidate from a partially run or differently sourced one.**

`PLAN:3-26` has a goal, background, and open questions, but omits the export's Done-when conditions, work-item dependencies, exact runbook, execution-record fields, failure states, file allowlist, and final audit (`EXPORT:180-188,449-493,558-566,673-679,839-859,1016-1026,1292-1316`). In particular:

- Enumerate the 11 closeout commands from `docs/reviews/v24-conformance-matrix-2026-10-23.md:112-124`, then G9, G10, Node, and multilingual smoke from `v24/s10/README.md:8-22` and `v24/s11/README.md:7-31`, followed by the two B0 checks. Run them serially on the final candidate tree; historical passes are not B0 evidence. Node/multilingual exit 2 is unverified and blocks completion.
- Do not copy the export's blanket “exit 0 plus `[passed]`” rule to every artifact (`EXPORT:480-484` contradicts its own exit-0-only rows). Use each command's documented success marker: the inherited Python gates print `[passed]`, the scope-diff check requires exit 0 with empty output, and an actual exit 2/`[SKIP]` is unverified. Record the real command, timestamp with zone, exit code, actual last line, and log digest.
- A HEAD SHA alone does not identify this dirty tree. Record HEAD, status, environment versions, and a sorted per-file hash manifest for the executed host/SQL/test and B0 files. A post-commit `git diff --exit-code` is also not proof that the committed candidate matches the pre-commit baseline: compare tracked host/SQL content against the recorded base (for example, `git diff HEAD` before commit and the recorded base afterward), and account for untracked files through status/hash inventory.
- Preserve the existing gate implementations. G10/Node/multilingual and raw plugin-stdout goldens use real local echo subprocesses with a scripted provider; substituting a Fake tool would weaken the inherited proof. The D-MP-1 local-subprocess deviation is documented at `v24/s11/README.md:113-119`; the network prohibition remains (`v24/s11/test_g10.py:666-691`).

### 2. Golden coverage and capture/check ownership are still unspecified, and one exported schema is not representable

**High — “freeze descriptor/frame/request/message” can shrink to a few self-generated hashes unless the case matrix and update lifecycle are fixed.**

`PLAN:20-26` leaves the central golden decisions open. The export's implementation-bearing requirements that need an explicit decision are:

- **Coverage:** all four v1 request operations; Python and Node raw success/known-error stdout as separate cases; parser classifications for missing LF, CRLF, extra frames, malformed/non-object results, non-UTF-8, EOF, and U+2028/U+2029 behavior; initial and continuation provider bodies; success and exit-3 tool messages; and the F6 structural invariants (journal event set, tool-message/payload shape, fixed lease and transport bounds, and current v2 rejection). See `EXPORT:331-399` and the design's v1 regression matrix at `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:888-898`. “Frame” in `PLAN:5` must not silently become request-only.
- **Deterministic inputs:** fix reservation, args, realm where it enters manifest bytes, token budget/reserve, model script, and provider tool-call ID; exclude random UUIDs, wall time, PIDs, and Authorization headers. Provider `max_tokens` is derived from the reserve and canonical body estimate (`v24/host/deepseek.py:205-229`), so the budget is a golden input, not incidental fixture state.
- **Authority:** fixed expected hex is authoritative; length and SHA-256 check vector integrity, not implementation correctness. Capture candidates twice into a non-committed location, review them, and make verification read-only with no `--force`/re-bless path in a gate. Vectors and checker must become available together. Descriptor text, including the design's fixed V1/V2/`{}` canonical vectors, additionally checks against PostgreSQL `v24.canonical_json`; this is an independent fixed-byte oracle, not a comparison of two self-generated hashes (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:477-499`). These are the stronger capture rules in `EXPORT:1109-1135`, not the in-place overwrite lifecycle in `EXPORT:323-329`.
- **Domains:** distinguish `registry.pg_jsonb_text` for descriptor digest bytes, `deepseek._canonical` for actual provider bodies, `journal.canonical_json` for tool-message content/digests, `line_json._canonical` plus LF for request frames, and un-reserialized plugin stdout. The latter three compact serializers have similar shapes but are separate capture/ownership seams (`v24/host/deepseek.py:383-392`; `v24/host/journal.py:64-73`; `v24/host/line_json.py:72-86`). Do not reduce all of them to one journal authority.
- **Container contradiction:** the proposed mandatory `text` field must equal decoded bytes (`EXPORT:290-303`), but the same lane includes a deliberately non-UTF-8 parser input (`EXPORT:369`). Make `text` optional/null for binary cases, or place non-UTF-8 inputs in a binary-only case shape; keep hex authoritative. Do not require invalid UTF-8 to decode.

The actual capture points support this scope: `ScriptedTransport` stores the original body at `v24/s11/plugin_fixtures.py:197-214`, `Invocation.stdout` remains raw at `v24/host/line_json.py:172-205`, and the worker persists the exact tool message at `v24/host/worker.py:1064-1077`.

### 3. The multi-provides probe needs concrete DB-only ownership and dependency corrections

**High — reusing the apparent high-level harness would violate the probe boundary, while a supposed pin-shape unknown is already answered by code.**

`PLAN:15-16` states the desired proof but not the fixture/helper and failure seams developed at `EXPORT:401-447,765-784,1137-1198`.

- Do **not** instantiate `PluginHarness` for the DB-only probe. Its constructor creates both `PluginDispatcher` and `HostWorker` (`v24/s11/plugin_fixtures.py:274-287`). Reuse the DB fixture, descriptor/manifest builders, and s2/s4/s5 command helpers with direct `HostDB` claim/settle and owner evidence reads instead. G4-D's prepare settlement is success with result `{}` (`v24/s5/test_g4.py:160-171,1843-1867`), not a dispatcher-produced resource receipt.
- `host_run_pins` does return `key`, `slot_id`, `provider_fiber_id`, `provider_episode_id`, `provider_install_id`, `descriptor`, hex `descriptor_digest`, and release fields (`v24/sql/49_host_reads.sql:480-547`). Therefore the export's unresolved S19/`49_host_reads.sql` follow-up (`EXPORT:230-231,650-656`) is already resolved by inspection. Add this file to `PLAN:28-37`; the probe should assert the public shape rather than rediscover or owner-update it.
- Enforce zero spawn at the callable actually used by the protocol: `line_json.py:37` imports `run_process` into its own module binding, so patch `v24.host.line_json.run_process` (and optionally the lower-level binding), plus network guards. Assert no dispatcher/worker construction and a zero call count in `finally`. Owner reads remain evidence-only; no direct slot/pin writes.
- Keep the realm negative's scope explicit. Existing G3a-A3 already proves leaf-first routing with no cross-realm fallback (`v24/s2/test_g3a.py:203-220`), so `PLAN:16` can keep this control optional rather than silently making it a new completion gate. If retained, use an isolated fixture and assert `dependency_unresolved`, no new run/pins, and the W1 failed-command/request receipt only; do not assert ten-table zero writes. The W1 distinction is already exercised at `v24/s3/test_g2.py:457-498`, and `interpret_start` returns its W1 error at `v24/sql/40_interpreters.sql:2851-2852`.

### 4. Q3 is not yet a consumable contract: the export disagrees on byte accounting and leaves renderer ownership unresolved

**High — a downstream implementer would get different offset, meta-budget, and pagination behavior depending on which lane is followed.**

`PLAN:24` correctly identifies the questions but supplies none of the required adjudication. The correction is not to copy one whole lane:

- For empty read/list and completed search, make the boundary explicit: `offset_out_of_range` iff `(total > 0 and offset > total) or (total == 0 and offset > 1)`. Thus `offset=1,total=0` is a successful empty page; incomplete search retains the design's separate empty-page rule. This resolves, rather than repeats, the contradictory generic `offset > total` wording at `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:774-775,804,830`.
- Include `max_args_bytes`, which `PLAN:24` omits but the export addresses (`EXPORT:1224-1236`): measure the standalone compact args object, excluding invoke envelope/LF, with no host default injection. For semantic output budgets, name the host canonical normalization authority; for the full frame, measure the plugin's actual serialized bytes.
- Resolve the export's direct meta conflict before downstream use: Lane 2 counts absent meta as zero (`EXPORT:792`), Lane 3 counts `{}` as two bytes (`EXPORT:1228-1231`). Design §5.2 says absent meta is treated as `{}` (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:597-600`), so under normalized-component accounting the exact result is two bytes. Raw-wire accounting would be a different rule and would require explicit design adjudication.
- Preserve the ownership blocker identified only in Lane 2 (`EXPORT:793,797`). The plugin owns `value` and the pre-send full-frame budget; the host-owned renderer creates `content/meta` afterward (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:639-667,730-739`). If the plugin must pre-budget rendered content, the descriptor/render projection must define how it predicts those bytes and guarantees cursor progress. Otherwise record an M3/W5 design blocker; do not invent host truncation, a new RPC, or a host-driven cursor in B0.
- Mark all of these rules `contract-frozen / behavior-unverified` for W5/W6. Lane 2's requirement to edit the ABI design during B0 (`EXPORT:797,853-855`) conflicts with the other lanes and `PLAN`'s plan-only boundary. Register the erratum for design review; do not silently rewrite the design or claim v2 pagination was tested.

### 5. Q4/Q5 omit the failure-window and shared-handler constraints that determine whether W4 is safe

**High — the current facts are listed, but the future ownership, failure, restart, and regression contracts are incomplete.**

For **lease** (`PLAN:14,25`), the exact future-only boundary is:

- The v2 dispatcher performs the pre-spawn check using the already-claimed `effect["lease_until"]` and local `HostDB.remaining_lease_ms`, requiring `remaining >= descriptor_timeout_ms + 5000`; insufficiency is ordinary failure `lease_insufficient`, with the fixed 30-second tool lease and v1 branch unchanged (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:390-413`; `v24/host/db.py:203-215`).
- `dispatch_started` is written before `tool_handler` runs (`v24/host/worker.py:1037-1056`), so a pre-spawn lease failure still has that event. This is accepted current behavior, not a reason to move the event or add the deferred `tool_preflight` hook in B0 (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:971-975`). G12-H must prove zero spawn with a process sentinel/count, never with journal-event absence.

For **`model_text`** (`PLAN:13,26`):

- The dispatcher owns rendering; the worker owns persistence into the existing `dispatch_finished.payload.tool_message.content`. Do not add an event type or payload key, and do not change settled `result.output`. Restart replays the persisted tool message without rendering again (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:669-691`; `v24/host/worker.py:1200-1231`).
- `_call_tool_handler` is also used by `_execute_resource` (`v24/host/worker.py:1100-1108,1302-1308`). W4 must preserve the resource handler's `(class,result)` behavior and receipt shape while supporting the three design return forms; changing the shared helper's arity without handling this caller is a regression. The current F5/F6 goldens should pin v1 `canonical_json(output)` bytes and the existing tool-message shape, while restart/no-rerender and resource compatibility remain explicit W4 tests.

### 6. Execution order and scope need one adjudicated choice, not three incompatible ones

**Medium — ordering determines whether a structural SQL blocker is found before expensive capture/gate work, and scope determines which files may change.**

`PLAN` has no work-item order. The export variously runs the probe first (`EXPORT:623-633`), all inherited gates first (`EXPORT:880-887`), or goldens first (`EXPORT:1374-1396`). Preserve the fail-fast admission order: source/scope preflight → multi-provides structural probe → golden capture and read-only verification → Q1–Q5 boundary recording → all inherited and B0 checks on the final tree → file/source audit. A confirmed SQL structural mismatch stops later work and returns to design; ordinary gate failure blocks completion without a production fix in B0. Golden vectors and their checker land together.

Keep the file boundary to B0 test/vector/README/evidence/plan artifacts. Do not import Lane 2's design edits or any host/SQL/s10/s11/s13 runtime changes. The ABI design and B0 plan are currently untracked; `PLAN:30` therefore has a real document-ownership dependency. Decide explicitly which line owns and commits the design prerequisite rather than silently adding it to the B0 allowlist. Finally, do not copy Lane 1's “default to a new branch” publication rule (`EXPORT:637-644`): the repository's `AGENTS.md` requires path-scoped staging and, after a genuinely completed/tested milestone, commit followed by `git push origin main`. That future publication rule does not authorize committing during this plan-only review.

### 7. Two reference omissions/errors would send implementation to the wrong seam

**Low — localized corrections.**

- `PLAN:12` cites `v24/s11/plugin_fixtures.py:208-218` as the `ScriptedTransport` body-capture evidence, but the actual class and `calls.append({"url","body","headers"})` are at `v24/s11/plugin_fixtures.py:197-214`, especially `:205-206`; `:217-222` is the adapter factory. The same stale range is repeated throughout `EXPORT` and should not be propagated.
- `PLAN:28-37` omits files needed by its own future-boundary conclusions: `v24/host/plugins.py:40-84` for install/pin/key/artifact dispatch and the v2 lease branch, `v24/host/process_io.py:18-21,56-79` for transport constants/validation, `v24/sql/49_host_reads.sql:480-547` for pin reads, and `v24/host/plugin_smoke.py:166-188` for multilingual exit behavior. Add these as dependencies, not as permission to modify them in B0.
