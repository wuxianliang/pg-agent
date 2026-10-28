# Cordis v2 DP5

DP5 delivers the event surface and effective-descriptor resolution on the DP1–DP4 Cordis v2 kernel: listener production registration, `dispatch`/`listener_call` with the five dispatch modes, overlay/intercept effective descriptors, and the design G4 event refinement evidence. The authority is `docs/designs/cordis-plugin-system-2026-10-25.md`; the implementation plan is `docs/plans/v24-cordis-dp5-events-resolution-plan-2026-10-28.md`.

## Current status

**W1, W2, W3 and W4 are implemented and verified.** W1 is `c3ddd94`; W2 is `20599f6`; W3 is `184938e`; W4 is the local commit on top of `184938e`. W3 added the atomic event closure (`44_events.sql`, the p4 `fiber.activated` producer, typed event ops, virtual receipts, in_db/host execution and `CDP5-D` D1–D12). W4 completes `CDP5-R` R5–R7: the pure `listener_exec` dependency proof and read-table probe, an independent Python reference for all five modes, mixed-generation activation, host conditional evidence, and the no-config DP4 digest recomputation. W5 (`CDP5-B` and full closeout) remains.

## W4 scope

W4 is refinement and explicit-deviation evidence, not a new event path:

- **R5 purity.** `listener_exec` is `IMMUTABLE STRICT BEGIN ATOMIC`; its transitive `pg_depend` closure has no `pg_class` and no parsed-body gap; a deliberately table-reading `BEGIN ATOMIC` probe is detected by the same closure; the pure helper set contains no dynamic SQL, outbound primitive or `RAISE`.
- **R6 reference.** An independent Python implementation sorts by `priority DESC`, applies event filters, executes the four `in_db` operators and folds each mode. It is compared with the production snapshot and persisted child rows, not with `event_delta` or the SQL planner:
  - `emit` compares `generated`;
  - `parallel`/`serial`/`bail` compare `acc`, `joined` and the actual called multiset;
  - `serial`/`bail` short-circuit only on a success whose `result.value.bail` is the JSON boolean `true`;
  - cross-provider duplicate `listener_id`s are compared as a multiset;
  - `waterfall` compares only the narrowed `acc` chain and the final `acc`, never a synchronous `next` choice;
  - the empty-set identity is asserted separately for all five modes.
- **R6b mixed generation.** A provider that is closed, drained and reactivated with the same listener id contributes only its current-generation contribution; the released generation is absent from the new dispatch snapshot.
- **R7 host premises.** The host path proves generation (`ready` child), claim (`execution:{descriptor,descriptor_digest}`), settlement (one progress event, parent sealed) and withdrawal (closing provider drains). It does not assert timing equivalence, fair scheduling or external isolation. P7.1/P7.3 and E1–E3 remain host premises; `sync_reads=false` is a declaration, not a proof.
- **R3b DP4 digest.** The no-config run keeps the DP4 claim shape; policy, schema and raw toolset digests are rehashed independently in Python.

W4 also records the named deviations rather than silently widening them:

- only p4 `fiber.activated` has a producer;
- `emit` guarantees that all children were generated, not that a host ran them;
- `waterfall` passes `acc`/error but has no synchronous `next` call stack;
- `sync_reads=false` does not prove host external isolation;
- unknown external reconciliation remains DP6.

## W3 scope (historical)

W3 delivered:

- optional p4 producer for `fiber.activated` only; source/ancestor-scope active listeners plus the source's own virtual-active episode; descendant and sibling scopes excluded;
- dispatch creation only from the p4 reconcile branch. The existing run_start successor is retained first, then one dispatch per non-empty mode group in `emit/parallel/serial/bail/waterfall` order;
- deterministic snapshot ordering `priority DESC, seq ASC, fiber_id, episode_id, contribution_id`, and dispatch IDs from `successor_effect_id(actor,p4_effect,ordinal,'dispatch')`;
- exact dispatch and listener_call inputs; parent owner = source fiber/episode, child owner = provider fiber/episode, both `run_id=NULL`;
- four typed domain ops `dispatch_open`, `listener_append`, `listener_settle`, `dispatch_settle`, applied after flat successors; no cursor/acc/dispatch-state column;
- virtual current receipt derivation; `unknown` not joined and freezes sequential continuation/sealing;
- `in_db` execution as a predeployed SQL operator; host listeners remain `ready`; one `dispatch_progress` event per successful/failed host receipt;
- created-effect budget `run_start + dispatch groups + children ≤16`; snapshot children ≤16; no truncation;
- source/provider P6 fences, independent validators/applier/postconditions and command/host replay separation.

## Capacity

W4 changes one function body form (`listener_exec` to `IMMUTABLE STRICT BEGIN ATOMIC`) with **no net line change**; no helper, table, DDL, loader entry or public function was added. The measured final tree is **5500** physical helper lines (40=1685, 41=1473, 42=1020, 43=700, 44=622), **R=0** against the user-authorized 5500 cap. DDL is **465≤900**, manifest **19**, ten domain tables, **162** private functions, unique `SECURITY DEFINER=advance`, public EXECUTE 0. The budget predicate admits exactly 5500 and rejects 5501.

| Item | B0 | W1 | W2 | W3 | W4 |
|---|---:|---:|---:|---:|---:|
| `40_advance.sql` | 1549 | 1567 | 1589 | 1685 | **1685** |
| `41_lifecycle.sql` | 1197 | 1354 | 1473 | 1473 | **1473** |
| `42_teardown.sql` | 1000 | 1007 | 1015 | 1020 | **1020** |
| `43_loop.sql` | 592 | 668 | 668 | 700 | **700** |
| `44_events.sql` | — | — | — | 622 | **622** |
| Helper total | 4338 | 4596 | 4745 | 5500 | **5500** |
| `R = 5500 − total` | 1162 | 904 | 755 | 0 | **0** |
| DDL prefix | 461 | 465 | 465 | 465 | **465** |
| Manifest entries | 18 | 18 | 18 | 19 | **19** |
| Private functions | 129 | 138 | 144 | 162 | **162** |
| Domain tables | 10 | 10 | 10 | 10 | **10** |
| `SECURITY DEFINER` / public EXECUTE | `advance` / 0 | `advance` / 0 | `advance` / 0 | `advance` / 0 | **`advance` / 0** |

The twelve frozen `v24/sql` hashes and the `57e2c1e` frozen diff are unchanged. `v24/load.py` and `v24/s1`–`s12` remain untouched; only the Cordis line's `v24/cordis/load.py` contains `44_events.sql`.

## W4 verification

The full inherited 31 commands, then `CDP5-R`, `CDP5-E` and `CDP5-D`, ran one process at a time, serially, on the final tree: **34/34 exit 0 in 177 s**. The refined `CDP5-R` gate then ran again as the final-tree confirmation: **exit 0**. Logs: `/tmp/dp5-w4-gates/gate-01..34.log`; summary `/tmp/dp5-w4-gates/gates.tsv`.

```bash
uv run python v24/cordis/dp5/test_resolution.py
uv run python v24/cordis/dp5/test_listeners.py
uv run python v24/cordis/dp5/test_dispatch.py
```

`CDP5-R` prints:

```text
[CDP5-R1] overlay recursive merge, array/scalar/null replacement, protected identity, unknown target, dual namespace, depth 4/5 and wrapper boundary
[CDP5-R2] nearest replace/reject, realm-first matching, depth 4/5, forged digest and resolve-time contract rejection; production scope_create path
[CDP5-R3] check view/run input/toolset/claim execution all use the effective descriptor; empty configuration keeps the legacy claim shape
[CDP5-R3b] no-config run keeps the DP4 claim shape and raw digest/toolset; policy/schema/toolset rehashed independently in Python
[CDP5-R4] withdrawn provider pins still drain with the frozen effective config; frozen contract drift and released pins reject without rebinding
[CDP5-R5] listener_exec is IMMUTABLE STRICT BEGIN ATOMIC; its pg_depend closure has no pg_class or parsed-body gap; the read-table probe is detected; pure helpers have no dynamic SQL/outbound/RAISE
[CDP5-R6] independent Python sort/filter/exec/fold matches emit generated, parallel/serial/bail/waterfall acc/joined/called; serial and bail short-circuit; duplicate listener_id across providers is a multiset; empty-set identity matches
[CDP5-R6b] a reactivated provider contributes only its current-generation listener; the released generation is excluded from the mixed-generation snapshot
[CDP5-R7] host proves generation/claim/settlement/withdrawal only; P7.1/P7.3 and E1-E3 remain external premises; sync_reads=false is not isolation
[CDP5-R8] scope realm/intercept UPDATE guard, close tombstone, install overlay immutability and private helper ACL
[passed] CDP5-R (W4: R1-R8, five-mode reference, purity and host premises)
```

## Earlier milestones

- W1 `c3ddd94`: overlay/intercept exact ABI, effective descriptor/digest through resolve/check/view/run claim, old-run drain, scope UPDATE guard, R1–R4/R8.
- W2 `20599f6`: optional five-key manifest and eight-key listener declarations, `registration_plan`, cross-32 iterator, P4 totality, listener overlay, production P5/P6 withdrawal/release, E1–E7.
- W3 `184938e`: atomic p4 producer, five-mode dispatch closure, `44_events.sql`, loader 19, D1–D12.
- B0 re-adjudication at `ba66776`: 5500 capacity admission, 31/31 inherited commands, frozen surfaces.
- DP4 handoff: `348b9b8` W5, `f119429` acceptance correction, `73973d1` settlement hardening, `ba66776` helper split.

## Next action

W5: add `v24/cordis/dp5/test_boundaries.py` (`CDP5-B`), rerun every old and new gate serially, and record the final all-boundary/frozen-hash/ACL/manifest/push-ready result. W4 does not claim B or the final closeout.

## Publication

`AGENTS.md` says push `origin main`, but this worktree is branch `v24` tracking `origin/v24`; the plan leaves the target to orchestration or a user-named remote/branch. W1–W3 are local commits; W4 is committed locally after its own verification. No push was performed. If the target is `origin/v24`, fetch first and use an ordinary fast-forward push; if it is `main` or another ref, name it explicitly.
