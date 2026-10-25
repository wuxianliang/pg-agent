# v24 S3 six verbs — run state machine and read projections

Authority: [S3 plan](../../docs/plans/v24-s3-verbs-2026-10-23.md). S3 implements `start`, `poll`, `wait_check`, `cancel`, `steer`, and `respond`, plus the run state machine and start-time run pins. W1–W7 verification is complete: the six frozen commands were rerun serially on 2026-10-24 and all exited 0; G3b-1…5 passed.

## Layout and load

```text
00_schema → 10_schema → 20_triggers → 30_advance → 40_interpreters
→ 45_capability → 47_verbs → 50_permissions
```

`47_verbs.sql` defines internal read helpers `run_owner` / `run_projection`, the public `poll` / `wait_check` read surface, and public write wrappers for `start` / `cancel` / `steer` / `respond`. The SQL is registered in `v24/load.py`’s `SQL_LOAD_ORDER`. Advance dispatch/applier behavior lives in `30_advance.sql` and `40_interpreters.sql`.

## Contracts

- `start` creates a run (`revision=1`), initial run pins for `input.requires`, and exactly one ready `model_call` effect. The returned handle is `emitted[0]` plus `registration_generation=1`. Ownerless runs require an empty dependency list. Omitting `wall_ms` defaults the remaining wall budget to 86400000 ms.
- Claim boundary (S3.1): until S4 adds model/tool settlement, only `host_prepare` and `host_release` effects are claimable; every other kind returns W0 `invalid_args` with zero writes.
- Run revision starts at 1 and increments on visible-state changes through advance. `poll` is a bounded projection read keyed by revision. `wait_check` is a short transaction read keyed by registration, epoch, and event sequence; it does not block or loop. Both are stable, zero-write read functions.
- `cancel` seals the run and revokes publication. Ready effects become cancelled; claimed effects remain claimed with `cancel_requested=true`. A run pin is released only when no effect references it.
- `steer` advances epoch/driving generation; without an old claimed business effect it immediately creates a successor model call, otherwise it records `pending_steer`. The applier updates effects before inserting the successor to satisfy `u_effects_model_call`.
- `respond` consumes an already waiting interaction, advances generation, and creates the next model call. S3 tests seed the interaction; model outcomes produce interactions in S4.

## ACL

The `SECURITY DEFINER` allowlist is exactly `advance`, `resolve`, `run_owner`, `run_projection`, `poll`, and `wait_check`, all with `search_path=pg_catalog, v24`; read DEFINER functions are stable and contain no DML or advisory lock. `run_owner` and `run_projection` are internal helpers and have no protocol-role EXECUTE grants. `resolve` was INVOKER in S2 and is corrected to DEFINER in S3 W1 because service/operator/admin protocol roles have no table privileges. Public verb wrappers are INVOKER and granted to the protocol roles. The three protocol roles retain zero table privileges.

## Verification and boundaries

The six frozen commands were run serially in `.claude/worktrees/v99` on branch `v24`:

| command | exit code |
|---|---:|
| `uv run python v24/load.py` | 0 |
| `uv run python v24/s1/setup_db.py --self-check` | 0 |
| `uv run python v24/s1/test_ddl.py` | 0 |
| `uv run python v24/s1/test_g1.py` | 0 |
| `uv run python v24/s2/test_g3a.py` | 0 |
| `uv run python v24/s3/test_g2.py` | 0 |

`test_g2.py` reports G2a-0…8/10/11 and G3b-1…5 passed. G2a-9 is covered by the per-verb receipt/replay and zero-write read assertions. G2 parent: **部分（G2a 绿；G2b 保留 S4）**. G3 parent: **完成（G3a+G3b）**. G3b-4 proves two committed sequential scenarios; G3b-5 uses two connections, an advisory-lock barrier, `pg_blocking_pids()`, and `pg_locks` to prove start/off serialization.

G3b-2’s complete claimed/unknown settlement release is **未验证 / S4**; only pin retention on cancel is claimed. There are 21 produced error codes and 2 unproduced codes: `blocked_unknown` (S4), `cleanup_cycle` (S5). Interaction production, model/tool execution, and pending-steer consumption remain S4. Owner cascade, scope close, and full dispose closure remain S5.
