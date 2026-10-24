# v24 S4 native agent loop — final

Authority: [S4 plan](../../docs/plans/v24-s4-agent-loop-2026-10-24.md) §4 (C17–C23), §5, §7, §10.2. **S4 is complete: W1–W6 implemented, all seven gates exit 0, closeout artifacts present.** The local milestone commit uses `v24: close S4 agent loop (G2b)` and is not pushed.

## Layout and load

```text
00_schema → 10_schema → 20_triggers → 30_advance → 40_interpreters
→ 45_capability → 47_verbs → 48_loop → 50_permissions
```

`48_loop.sql` holds fourteen `SECURITY INVOKER` helpers: `loop_policy`, `model_reserve`, `model_digests`, `model_effect_id`, `tool_effect_id`, `continuation_effect_id`, `claimable_kinds`, `loop_sealable`, `run_pin_release_set`, `steer_model_effect_id`, `steer_consumable`, `interpret_model_settlement`, `interpret_tool_settlement`, `validate_and_apply_loop_delta`. It adds no tables, columns, indexes, grants, or `SECURITY DEFINER`; `advance` remains the only writable DEFINER. `50_permissions.sql` stays last.

## Contracts C17–C23

| Contract | Frozen behavior |
|---|---|
| C17 `model_call` envelope | `request` carries `v`, `cause` (`start`/`steer`/`respond`/`continuation`), `run_id`, `epoch_no`, `generation`, `reserve:{tokens}` and `digests:{policy,schema,toolset}` plus cause-specific keys. Claim and settlement independently recompute the digests; the toolset digest is derived from live run pins. |
| C18 claim allowlist | The single source of truth is `v24.claimable_kinds()` = `host_prepare`, `host_release`, `model_call`, `tool_call`. Every non-member is W0 `invalid_args` with ten tables byte-equal. Claim repeats the full request structure gate before the host executes. |
| C19 settlement matrix | Structural failures are W0 `invalid_outcome` (effect stays `claimed`, no outcome, no event). Semantic violations settle as `unknown` with the original receipt preserved; they are never an error return. |
| C20 batch barrier | A model effect admits at most 16 tool children, ordinals `0..15`, ids `md5(model||':tool_call:'||ordinal)`. The batch digest is SHA-256 over tool ids ordered by ordinal. Exactly one continuation is published by the last settling sibling; its parent is the max-ordinal tool, independent of settlement order. |
| C21 `pending_steer` | Five consumption conditions: pending exists; settling effect is old-generation; no other old-generation ready/claimed business effect remains; class ≠ unknown; run not terminal. Latest write wins; consumption creates exactly one `cause='steer'` model call and clears pending. |
| C22 run-pin release | Terminal settlements (`completed`/`failed`/`cancelled`/`blocked_unknown`) release run pins whose referenced effects are neither ready/claimed nor unknown-with-`resource_quiesced_at IS NULL`. Order is effects → run → pins. |
| C23 turn / budget / seal | `turn_no` increments only on a committed business settlement. Admission pre-debits steps and tokens (`reserve = LEAST(remaining,4096)`); settlement refunds `reserve − usage` for success/failure, never for unknown/semantic. `tool_calls` is debited when the batch is admitted. `loop_sealable` forbids sealing with ready/claimed business effects, pending steer, interaction, or unquiesced unknown. |

## Claim allowlist

| Kind | S4 | Evidence |
|---|---|---|
| `host_prepare`, `host_release` | claimable (unchanged S1) | `G2b-U` |
| `model_call` | opened in W1 | `G2b-B` |
| `tool_call` | opened in W2 | `G2b-D` |
| `inspect_resource` | **closed until S5** | `G2b-C`, `G2b-T-1` |
| `command_*`, `fiber_reconcile` | never claimable | `G2b-C` |

Expired `model_call`/`tool_call` leases return W0 `stale_claim`; S4 does not make a second attempt (D-S4-1). Host kinds keep the S1 reclaim semantics.

## Settlement classes

| Input | Effect | Run | Successors | Pins |
|---|---|---|---|---|
| structural invalid | stays `claimed`; no outcome/event | unchanged | 0 | unchanged |
| model/tool success | `succeeded`, receipt, `resource_quiesced_at=now()` | turn+1, refund, running/waiting/completed | tools, one continuation, or 0 | release only on terminal |
| model/tool failure | `failed`, receipt, quiesced | turn+1, refund | 0 | release only on terminal |
| model/tool unknown | `unknown`, original receipt, `resource_quiesced_at=NULL` | `blocked_unknown`, turn+1, no token refund | 0 | own pin retained |
| semantic unknown (model) | `unknown` + original success receipt | `blocked_unknown`, turn+1, no refund | 0 | retained |
| cancel-late success/failure/unknown | fact + cost only; effect settled | `cancelled` seal preserved byte-for-byte | 0 | own pin retained; others per C22 |

`failed` is produced only by `close_intent.kind='abort'`; structural invalid never becomes `failed`. Unknown and semantic settlements clear `pending_steer`/`interaction`. `interaction_mismatch` is **W1**: domain zero-write plus one failed `command_respond` effect and its request receipt (`G2b-I`).

## Batch barrier and continuation

The model result's `tool_calls` are admitted as ready tool effects with pin bindings and one shared `batch_digest`. A tool settlement first observes whether any sibling is still `ready`/`claimed`; only the closing settlement publishes the continuation. The continuation id is `md5(model||':continuation')`; `u_effects_successor` and the applier's duplicate checks keep `(parent, ordinal)` unique. `u_effects_model_call` keeps at most one in-flight model per run; the loop applier's "second model" check is defensive and unreachable through the public API (D-S4-10). No partial batch is published.

## Interaction and respond

A model success carrying `interaction` writes the six-field `runs.interaction` object (`interaction_id = origin_effect_id = model effect_id`), sets `status='waiting'`, emits `interaction_created`, and publishes 0 successors. `respond` consumes it: clears interaction, increments `driving_generation`, writes exactly one `cause='respond'` model call, and emits `interaction_responded`. A second key gets W1 `interaction_mismatch`. A token-0 respond consumes the interaction and writes a budget seal rather than leaving a waiting run with no effect.

## Pending steer

`steer` against a claimed business effect writes/overwrites `pending_steer` and publishes no model. When the last old-generation effect settles successfully, the interpreter consumes the latest pending value and publishes exactly one `cause='steer'` model with the frozen epoch/generation/instruction/input/reserve/digests. Consumption id: `md5(run||':steer_model:'||epoch||':'||generation||':'||md5(instruction))`. Unknown clears pending without a successor; cancel wins and clears pending. A second steer before consumption overwrites the first (latest wins).

## Pin release

`v24.run_pin_release_set(run, effect, status, by_effect)` is recomputed by the applier, so a delta can neither under- nor over-release. Pins are released only when the run becomes terminal, with one exception: an `unknown` effect whose `resource_quiesced_at IS NULL` keeps its own pin until S5 inspect. The closing tool settlement and the final model settlement release pins in the same advance that seals the run (`G2b-R`, `G2b-S`). Cancel keeps the pre-existing cancel pin predicate.

## ACL

`advance` remains the only writable `SECURITY DEFINER`, with the S3 read-only DEFINER allowlist (`resolve`, `poll`, `wait_check`, `run_owner`, `run_projection`) unchanged. All fourteen new loop helpers are `SECURITY INVOKER`, owned by `v24_owner`, with fixed `search_path=pg_catalog, v24`; none is granted to a protocol role. The three protocol roles still hold zero table privileges; `G1-A`/`G1-P` still pass. `48_loop.sql` introduces no `GRANT` and no `prosecdef=true`.

## Actual verification — 2026-10-24

Run from `/Users/wxl/Projects/pg-agent/.claude/worktrees/v99` on branch `v24` (PostgreSQL 18.4, psycopg2 2.9.12), seven commands serially:

| command | exit code |
|---|---:|
| `uv run python v24/load.py` | 0 |
| `uv run python v24/s1/setup_db.py --self-check` | 0 |
| `uv run python v24/s1/test_ddl.py` | 0 |
| `uv run python v24/s1/test_g1.py` | 0 |
| `uv run python v24/s2/test_g3a.py` | 0 |
| `uv run python v24/s3/test_g2.py` | 0 |
| `uv run python v24/s4/test_g2b.py` | 0 |

`test_g2b.py` reports `[passed] v24 S4 W1-W6`, including G2b-A…V and the ten named `G2b-T-1…T-10` negatives. Historical failures and review blockers (W1–W5, including the W4 Oracle BLOCK on cancel-late tool unknown) are recorded in the ledger §4; no assertion was deleted or weakened.

## Implementation disclosures

- `FakeLLM` and `FakeTool` both live in `fake_llm.py`; no separate `fake_tool.py` was created (fixture consolidation).
- The three legacy `[G2b-T-1/2/3]` labels were renamed `[G2b-V/unknown-wall]`, `[G2b-V/replay]`, `[G2b-V/receipt-conflict]`; the plan's `T-1…T-10` now denote the ten zero-write negatives.
- `G2b-T-5` (duplicate ordinal) reaches the loop applier's defensive precheck directly with a real interpreted delta; `G2b-T-9` probes `loop_sealable`. Neither is a public-API path, and neither changes product semantics.
- `G2b-M` deliberately writes `close_intent={kind:'final'}` when a final arrives with a ready effect; the seal is not performed and no terminal row is written.
- Full deviation list: [ledger](../../docs/reviews/v24-deviation-ledger-2026-10-23.md) D-S4-1…10.

## Boundaries (not covered by S4)

- `inspect_resource` convergence, owner cascade, scope close, and the full dispose closure are S5; S4 keeps `inspect_resource` unclaimable.
- Crash recovery, lease reclaim, and automatic inspect are S6; S4 explicitly leaves an abandoned effect `claimed` and does not promise recovery.
- The full three-plane concurrency matrix is S7. S4 proves G2b-E/F/O with two connections plus `pg_blocking_pids()`/`pg_locks`; G3b-4 remains sequential evidence.
- `agent.spawn` / child runs are not implemented; unmodeled intent/result keys are rejected before any child row is created.
- FakeLLM/FakeTool/FakeHost are in-process and are not transport proofs; real provider/network IO is outside the gates.
