# Cordis v2 DP5

DP5 delivers the event surface and effective-descriptor resolution on the DP1–DP4 Cordis v2 kernel: listener production registration, `dispatch`/`listener_call` with the five dispatch modes, overlay/intercept effective descriptors, and the design G4 event refinement evidence. The authority is `docs/designs/cordis-plugin-system-2026-10-25.md`; the implementation plan is `docs/plans/v24-cordis-dp5-events-resolution-plan-2026-10-28.md`.

## Current status

**W1, W2 and W3 are implemented, verified and locally committed.** W1 is `c3ddd94`; W2 is `20599f6`; W3 is the local commit on top of `20599f6`. W3 adds the atomic event closure: `44_events.sql`, the p4 `fiber.activated` producer, flat dispatch successors, typed event ops, virtual receipts, synchronous `in_db` execution, host claim/receipt, `ready_effects`/`execution`, parent/child ownership and IDs, source/provider P6 fences, independent validators/applier/postconditions, and `CDP5-D` D1–D12. W4 (R5–R7 and explicit deviations) and W5 (`CDP5-B` and full closeout) remain.

## W3 scope

W3 delivers:

- optional p4 producer for `fiber.activated` only; source/ancestor-scope active listeners plus the source's own virtual-active episode; descendant and sibling scopes excluded;
- dispatch creation only from the p4 reconcile branch. The existing run_start successor is retained first, then one dispatch per non-empty mode group in `emit/parallel/serial/bail/waterfall` order;
- deterministic snapshot ordering `priority DESC, seq ASC, fiber_id, episode_id, contribution_id`, and dispatch IDs from the existing `successor_effect_id(actor,p4_effect,ordinal,'dispatch')` ABI;
- exact dispatch and listener_call inputs; parent owner = source fiber/episode, child owner = provider fiber/episode, both `run_id=NULL`; child ID = `successor_effect_id(dispatch.request_actor,dispatch_id,ordinal,'listener_call')`;
- four typed domain ops `dispatch_open`, `listener_append`, `listener_settle`, `dispatch_settle`, applied after flat successors; no cursor/acc/dispatch-state column;
- virtual current receipt derivation: planner and independent validator overlay the in-flight receipt over DB siblings and fold only settled children; `unknown` is not joined and freezes sequential continuation/sealing;
- `in_db` execution as a predeployed `IMMUTABLE` SQL operator (`const`/`acc`/`append`/`fail`); each listener runs at most once per advance, no dynamic SQL/RAISE/table read/outbound call; `invalid_acc` is a legal internal failure;
- host listeners remain `ready`; `advance` claim exposes the frozen input and `execution:{descriptor,descriptor_digest}`; terminal `success`/`failure`/`unknown` receipts are authorized only for the owning host contract; in_db/dispatch external claim/settlement is `unauthorized`;
- emit settles its parent immediately and only reports `generated`; parallel seals when every trusted child is terminal and no unknown remains; serial/bail create only the active next and short-circuit only on a success whose `result.value.bail` is the JSON boolean `true`; waterfall passes the projection/error as the next `acc` and does not claim synchronous `next` control;
- one `dispatch_progress` bookkeeping event per successful/failed host receipt, `entity_type='effect'`, `entity_id=dispatch_id`, and payload tied to the virtual post-state; unknown writes no event;
- created-effect budget `run_start + dispatch groups + children ≤16`; snapshot children ≤16; a 16-listener parallel/emit dispatch plus its parent is rejected rather than truncated; input body/key/depth guards refuse over-budget listener inputs before creation;
- closure includes the p4 scope chain/candidate providers and listener settlement's parent/siblings/snapshot providers/installs/pins; `settlement_seed` expands only `listener_call`; old kinds keep their DP4 seed bytes;
- source P6 reports `blocked_unknown` when a non-emit dispatch owned by the source has an unknown provider child; created listener_call children participate in the provider's existing ready/claimed/unknown P6 barrier; withdrawn/closing providers drain frozen calls, released/disposed/closed providers reject with `dependency_unresolved`;
- command request replay is the cached final response including `emitted`/`ready_effects`; host terminal replay returns `disposition=replay` with both arrays empty and no new writes; request cache insertion happens after the event phase and final response-set verification;
- independent `validate_event_domain`/`validate_activation_event`, typed applier and `event_apply_postconditions`; `assert_delta_applied` continues to check the pre-event domain and the event-stage postcondition checks the four ops.

W3 does **not** claim:

- W4's independent Python five-mode reference, purity dependency closure, host assumption ledger, or R5–R7;
- W5's `CDP5-B`, final all-gate closeout, or the full G4 completion;
- a general event producer other than p4 `fiber.activated`; other declared events are registerable but have no producer;
- fair scanner/recovery, external unknown reconciliation, upgrade/HMR, cancel/steer/respond, spawn/child runs, multi-host, cell/reservation writers, realm ACL, `thisArg`, synchronous disposer chains, or synchronous waterfall `next` control;
- any push; the remote target is still left to orchestration.

## Capacity

W3 adds `44_events.sql` and the loader 19-entry/ five-file budget tree. The measured W3 tree is **5500** physical helper lines (40=1685, 41=1473, 42=1020, 43=700, 44=622), **R=0** against the user-authorized 5500 cap; DDL is **465≤900**, manifest **19**, ten domain tables, **162** private functions, unique `SECURITY DEFINER=advance`, public EXECUTE 0. No validator, mode, limit or test was removed to fit. The budget predicate admits exactly 5500 and rejects 5501 on a temporary five-file tree; the real tree is exactly at the cap.

| Item | B0 | W1 | W2 | W3 |
|---|---:|---:|---:|---:|
| `40_advance.sql` | 1549 | 1567 | 1589 | **1685** |
| `41_lifecycle.sql` | 1197 | 1354 | 1473 | **1473** |
| `42_teardown.sql` | 1000 | 1007 | 1015 | **1020** |
| `43_loop.sql` | 592 | 668 | 668 | **700** |
| `44_events.sql` | — | — | — | **622** |
| Helper total | 4338 | 4596 | 4745 | **5500** |
| `R = 5500 − total` | 1162 | 904 | 755 | **0** |
| DDL prefix | 461 | 465 | 465 | **465** |
| Manifest entries | 18 | 18 | 18 | **19** |
| Private functions | 129 | 138 | 144 | **162** |
| Domain tables | 10 | 10 | 10 | **10** |
| `SECURITY DEFINER` / public EXECUTE | `advance` / 0 | `advance` / 0 | `advance` / 0 | **`advance` / 0** |

The twelve frozen `v24/sql` hashes and the `57e2c1e` frozen diff are unchanged. `v24/load.py` and `v24/s1`–`s12` remain untouched; only the Cordis line's `v24/cordis/load.py` gained `44_events.sql`.

## W3 verification

The full inherited 31 commands, then `CDP5-R`, `CDP5-E` and `CDP5-D`, ran one process at a time, serially, on the final tree: **34/34 exit 0 in 173 s**. The 31 inherited commands preserve the B0 order (s8 before s7). Per-command logs: `/tmp/dp5-w3-gates/gate-01..34.log`; summary `/tmp/dp5-w3-gates/gates.tsv`.

```bash
uv run python v24/cordis/dp5/test_resolution.py
uv run python v24/cordis/dp5/test_listeners.py
uv run python v24/cordis/dp5/test_dispatch.py
```

`CDP5-D` prints:

```text
[CDP5-D1] emit generated all children, in_db ran in-advance, host stayed ready; source closed while the provider-owned child remained fenced; parent never changed
[CDP5-D2] parallel out-of-order receipts, concurrent last-receipt race, one seal; acc/joined/called match the ordinal fold and the virtual current receipt counted once
[CDP5-D3] serial creates one active next; JSON true bails, string true does not; forged ordinal 5 is invalid_outcome with zero write
[CDP5-D3b] a not-yet-created serial snapshot item whose provider is released becomes a trusted listener_unavailable failure, without rebinding or host call
[CDP5-D4] bail returns the first hit value, null without a hit, and does not short-circuit on failure or a non-boolean bail field
[CDP5-D5] waterfall folds params/const/append/acc and carries failure/invalid_acc as the next acc; no synchronous next control is claimed
[CDP5-D6] dispatch/in_db external settlement is unauthorized; forged receipt and released-provider drain are zero-write; child identity is dispatch+ordinal only
[CDP5-D7] unknown is a legal receipt with no event/append/seal; ready siblings remain claimable, replay is empty, and source/provider P6 both report blocked_unknown
[CDP5-D8] command replay is byte-identical with emitted/ready_effects; host replay has both arrays empty; a post-event fault rolls back rows, event and request cache
[CDP5-D9] emit generated does not mean called; a delayed host child is ready while the parent result stays byte-identical; sync_reads=false is a declaration only
[CDP5-D10] claim COMMIT exposes execution descriptor/digest; wrong token is stale; the created host call drains after provider closing with the frozen snapshot
[CDP5-D11] source/mid/root listeners are routed by the scope chain; descendant and sibling listeners are excluded; priority/seq/UUID ordering matches the independent SQL sort
[CDP5-D12] 15 listeners+dispatch=16 passes, 16 rejects; run_start+14+dispatch=16 passes, run_start+15 rejects; discover_closure admits 512 and refuses 513
[passed] CDP5-D (W3: D1-D12 atomic producer, five modes, host path, fences, limits)
```

Coverage maps to the plan:

| Item | W3 evidence |
|---|---|
| D1/D9 | Provider-host emit child stays ready while the parent immediately reports only `generated`; in_db runs in the same advance; source can close while the provider-owned child remains fenced; parent never changes after the child settles |
| D2 | Three host providers, out-of-order receipts, two connections racing the last receipt, one seal, ordinal acc/joined/called, three progress events |
| D3/D3b | Serial one-active-next; JSON true vs string true; forged ordinal 5 rejected; released not-yet-created provider becomes internal `listener_unavailable` and the fold continues |
| D4 | Bail first-hit value, null without a hit, failure/non-boolean not short-circuiting |
| D5 | Waterfall const/append/acc chain, failure projection continues, `invalid_acc` is a legal failure, no next control |
| D6 | Dispatch/in_db external settlement unauthorized; forged receipt and released provider zero-write; child identity is dispatch+ordinal |
| D7 | Unknown receipt/no event/no seal; ready siblings claimable; replay empty; source/provider P6 blocked_unknown |
| D8 | Command replay byte-identical with emitted/ready_effects; host replay empty; post-event rollback restores all ten tables and no request cache |
| D10 | Claim exposes frozen execution descriptor/digest; stale token zero-write; created host call drains after provider closing |
| D11 | Scope-chain routing, descendant/sibling exclusion, same-priority/seq UUID tiebreak, no run_start ordinal 0 |
| D12 | 15+dispatch=16 and run_start+14+dispatch=16 pass; 16-listener and run_start+15 reject; closure 512/513 |

The W2 script remains E1–E7 registration/revocation evidence. Its helper-only assertions were updated for the W3 producer: a listener activation now creates a dispatch, so E2's final four emitted effects are the dispatch plus three in_db children, E5's 16-listener declaration registers but p4 rejects the 17-created budget, and E7 now sees the real dispatch/listener effects created by W3 rather than the old "no producer" state. No registration/revocation assertion was weakened.

## Earlier milestones

- W1 `c3ddd94`: overlay/intercept exact ABI, effective descriptor/digest through resolve/check/view/run claim, old-run drain, scope UPDATE guard, R1–R4/R8.
- W2 `20599f6`: optional five-key manifest and eight-key listener declarations, `registration_plan`, cross-32 iterator, P4 totality, listener overlay, production P5/P6 withdrawal/release, E1–E7.
- B0 re-adjudication at `ba66776`: 5500 capacity admission, 31/31 inherited commands, frozen surfaces.
- DP4 handoff: `348b9b8` W5, `f119429` acceptance correction, `73973d1` settlement hardening, `ba66776` helper split.

## Artifacts

- `docs/plans/v24-cordis-dp5-events-resolution-plan-2026-10-28.md` — §9 W3 Result and status.
- `docs/reviews/cordis-v2-dp5-conformance-matrix-2026-10-28.md` — W3 scope, capacity, 34-command regression and D evidence.
- `docs/reviews/cordis-v2-dp5-deviation-ledger-2026-10-28.md` — W3 treatments and remaining unclaimed scope.
- This README — W3 status, capacity and next action.

## Next action

W4: independent Python five-mode/reference comparison, purity dependency closure and read-table probe, host assumption ledger, emit/waterfall named deviations, mixed-generation regressions and the no-config DP4 digest evidence; R5–R7 plus the W4 refinements. W5 then adds `CDP5-B` and reruns every old and new gate.

## Publication

`AGENTS.md` says push `origin main`, but this worktree is branch `v24` tracking `origin/v24`; the plan leaves the target to orchestration or a user-named remote/branch. W3 is committed locally; no push was performed. If the target is `origin/v24`, fetch first and use an ordinary fast-forward push; if it is `main` or another ref, name it explicitly.
