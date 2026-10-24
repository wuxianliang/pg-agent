# v24 S9 — G8 host read / closure / lease / recovery extension check

Status: **M-H complete / G8 green** (2026-10-24). The no-argument
`uv run python v24/s9/test_g8.py` selects all **23/23 IDs** (13 read-surface
cases, 2 closure measurements, 3 lease cases, 1 recovery sweep, 3 debt
closures, 1 worker-precondition case) and exits 0. This is an **extension
check**, not a replacement for the frozen closeout count: the historical
closeout remains **11/11** (10 existing gates + G6).

Plan: `docs/plans/v24-closeout-real-provider-multilingual-2026-10-24.md`
M-H, execution rows M-H-1…M-H-3.

## Run

```bash
# gate: no argument, all 23 IDs
uv run python v24/s9/test_g8.py

# subset/debug only; never a closeout claim
uv run python v24/s9/test_g8.py --only G8-H10
```

Run from the repository root. The script has no `setup_db.py` of its own: it
imports the shared `v24/s1` fixture, creates one disposable pgembed database,
uses `admin`/`service`/`operator` LOGIN roles plus a direct `v24_owner`
connection, and drops the fixture on exit.

## What the 23 IDs prove

| ID | Assertion |
|---|---|
| `G8-H1` | `host_scopes`: owner sees only its scopes, admin sees all; explicit foreign scope is `not_found_or_denied`; closing/closed rows remain discoverable; UUID cursor, `limit=0`, negative and `>64` behavior, empty set. |
| `G8-H2` | `host_runs`: each item is byte-equal to `run_projection(run_id)`; strict `(created_at,run_id)` order; no cross-page duplicates; foreign service denied; empty scope is an empty list. |
| `G8-H3` | `host_effects`: only ready/claimed rows of the five external kinds; raw `request` is byte-equal to the owner fixture; command and settled history never leak; claim token, lease and cancel flag are exact. |
| `G8-H4` | `host_run_effects`: full model/tool history including settled rows; deterministic batch order; another run is invisible; missing/foreign run uses the error envelope. |
| `G8-H5` | `host_effect`: a second committed connection reads the same claim token/request after claim; absent/foreign/non-external kind are indistinguishable; a settled outcome is readable. |
| `G8-H6` | `host_scope_installs`: every install state, manifest bytes, `requires`/`provides`, lowercase hex for all three digests, dispose fields, UUID cursor, non-owner denial. |
| `G8-H7` | `host_install_fibers`: `fiber_id/control_seq/current_episode_id` match the committed state after public `fiber_control(on)`; non-owner denied. |
| `G8-H8` | `host_run_pins`: slot descriptor, pin digest, derived `provider_install_id`, released pin still readable but identifiable, non-owner denied. |
| `G8-H9` | `host_request`: base64 decodes to the canonical request bytes, digest is lowercase hex, response equals the first response, another principal is denied, replay adds no request row. |
| `G8-H10` | ACL/read-only common surface: exactly 17 DEFINER names sorted by `proname`, 27 `GRANT EXECUTE` statements, per-role EXECUTE sets **admin 26 / service 27 / operator 27**, no grant on `host_scope_allowed`, admin still denied `install`, every function STABLE with fixed `search_path`, no PUBLIC EXECUTE, protocol roles have zero table rights, the same forbidden-word regexp is applied directly to `pg_proc.prosrc`, every scoped reader rejects a non-owner service, ten-table fingerprint is unchanged, the reader takes no advisory lock and is not in `pg_blocking_pids`. |
| `G8-H11` | With another transaction holding G and carrying an uncommitted scope change, all nine reads finish in ~5 ms and see only the committed snapshot; a concurrent `advance(claim)` still blocks on G (`pg_blocking_pids` + ungranted advisory `pg_locks`) until the holder rolls back, then commits. |
| `G8-H12` | A 7-row scan with `limit=2` returns 2/2/2/1 with no omission or duplicate; a concurrently inserted row older than the cursor is found by the next full scan; a row moved behind an open cursor is observed **2x** (`duplicates=1`), and worker-style dedup by `effect_id` leaves the complete unique 8-row set. |
| `G8-H13` | 64 `model_call` items each with a ~1 MiB `input` request produce a **67,107,712-byte (64.00 MiB)** page; the 64 cap is not raised and the request is not redacted; a real lease=1 claim/settle on a separate `host_prepare` is accepted. |
| `G8-C1` | Closure slope: measured `B=C(0)=3`; `H=0,1,2,4,8,16,32` gives `C=3,4,5,7,11,19,35`; each adjacent pair's `C` increment equals its `H` increment, i.e. exactly **1 entity per added history effect** (H deltas `1,1,2,4,8,16`, C deltas `1,1,2,4,8,16`); every sample uses a real `advance(claim)` then rollback and returns a committed token. |
| `G8-C2` | Exact kernel boundary: `H_ok=509` gives `C=512` and a normal committed claim; `H_bad=510` gives `C=513` and `retry_with_closure` with no token, a byte-equal ten-table snapshot, and the same rejection on retry. |
| `G8-L1` | `lease_ms=1` and `300000` claim; `0`, `-1`, `300001`, `"1"` are `invalid_args` with ten-table byte-equality and attempt/fence still 0. |
| `G8-L2` | A live lease re-claim is `deferred` with `claim:null`; an expired `host_prepare` re-claim bumps attempt/fence to 2/2 and invalidates the old token; expired model/tool claims are `stale_claim` with attempt/fence unchanged. |
| `G8-L3` | An expired but not-yet-swept host claim still accepts its original token; after `command_recover` turns a model claim into `unknown`, a late receipt is `receipt_conflict` and the run stays `blocked_unknown` with no successor. |
| `G8-R1` | Without a command, 18 expired claims stay `claimed`; one sweep applies at most 16, reports `manual_debt=1` and `has_more=true`; the next sweep applies only the 17th; the `manual` row is untouched; there is no queue/job/cursor relation. |
| `G8-D1a` | **D-S6-12 closure**: a closed scope plus a real expired/claimed/non-manual candidate yields exactly one `settle_unknown` with reason `install_not_preparing`; scope/install/fiber/run are not revived. |
| `G8-D1b` | After a public install and public close, a synthetic `closed_at` plus a no-candidate recovery records only the recovery command/request; scope/install/fiber/run stay byte-equal. This is explicitly a synthetic fixture, not a claim that the public API always produces it. |
| `G8-D2` | **D-S8-7 closure**: two spawns, spawn+normal tool, spawn+`final`, and spawn+`interaction` all return `invalid_outcome`, write zero rows, and leave the claim unchanged; a later legal spawn with the same key commits and returns one child handle. |
| `G8-W1` | Both connections use READ COMMITTED with `statement_timeout=30s`, `lock_timeout=5s`, `idle_in_transaction_session_timeout=5s`; after claim commit both are IDLE; a live claim is not a recovery candidate; with in-flight work the worker policy skips the sweep and no row changes without a command. |

## Closure measurement

The probe is option **(a)** from the plan: a fixture-only PL/pgSQL function
`v24_fake.closure_probe(p_effect_id uuid, v_class text, v_body jsonb)` declares
`v_closure`, embeds the **complete recursive CTE extracted verbatim** from
`30_advance.sql` (`WITH RECURSIVE closure…` through
`) SELECT jsonb_object_agg(entity_type, ids) INTO v_closure FROM grouped;`),
and returns `v_closure`. The CTE text is not rewritten and the public SQL is
not extended with a measurement function.

Source guard: `CLOSURE_SHA256` is
`e9b15387dd41fd1621ec2aaec964e70c900cea8a0468b03242fd8b46528efba5`. A
kernel change changes the extracted bytes, fails the hash, and requires a
deliberate probe update; the installed function body is also checked to
contain the frozen block.

Measured this run:

```text
B = C(0) = 3
H:       0   1   2   4   8   16   32
C(H):    3   4   5   7   11  19   35
C slope: 1   1   2   4   8   16  (adjacent samples; H increments are identical)
H_ok = 512 - B = 509  -> C = 512, ordinary claim committed
H_bad = 513 - B = 510 -> C = 513, retry_with_closure, zero writes, retry still rejects
margin at H=32: 512 - 35 = 477
```

These are the actual small-fixture numbers; do **not** read them as "512 host
effects". The 512/513 construction exists only in the isolated C2 fixture.
The R/P stop ladder is 128 / 384 / 448 / 512 per the plan; G8 asserts the
kernel facts, not the stop policy.

## Public-path growth (evidence, not a gate)

A real service `install` (declaration with one provided key) plus its
`host_prepare` settle, then 32 public `fiber_control` on/off commands:

| after command | effects | host effects | reconcile effects | episodes | pins | latest-effect closure |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4 | 1 | 1 | 1 | 0 | 7 |
| 8 | 18 | 1 | 8 | 4 | 0 | 12 |
| 16 | 34 | 1 | 16 | 8 | 0 | 20 |
| 32 | 66 | 1 | 32 | 16 | 0 | 36 |

Every one of the 32 lifecycle commands also has its closure recorded; the
observed values range from 6 to 38, and adjacent differences are not claimed
monotonic because each probe targets the latest effect of a different shape.
The prepare effect's closure is 4 before and 4 after settlement. No pin was
created because this declaration has no tool pins.

The plan's "existing unknown -> new-key inspect" branch is **not generated**:
M-H adds no host worker and this fixture deliberately does not use owner
inserts to fabricate a public inspect history. Actual return recorded:
`inspect branch not generated in M-H (no unknown host effect), actual return=[]`.
This is a not-run boundary, not a pass claim. The public-path numbers above
are evidence only; no owner-inserted row is presented as public-path evidence.

## Harness and guards

- Only shared fixtures/helpers from `s1/s2/s4/s5/s6/s8`; no new `setup_db.py`.
- Static pre-scan of `v24/s9/*.py` rejects forbidden imports (`http`, `socket`,
  `urllib`, `requests`, etc.) and sleeps; the test uses
  `socket = __import__("socket")` only to monkeypatch and restore
  `socket.socket.connect` / `socket.create_connection` around the run.
- `49_host_reads.sql` is scanned for `http|dblink|pg_sleep|socket` and DDL
  keywords; the catalog check still requires exactly ten tables, no views and
  no extensions.
- All writes in fixtures go through public wrappers except explicitly labelled
  owner seeds. The owner connection is used only to build state and read
  evidence; it is not a protocol path.
- No `sleep`; held-G ordering uses threads, a `queue.Queue`, and
  `pg_blocking_pids`/`pg_locks` polling.

## Boundaries

- **No starvation/fairness proof.** D-S7-2 remains open exactly as in S7; this
  README makes no liveness claim.
- **No host worker.** `G8-W1` proves the SQL/session preconditions available at
  M-H (timeouts, IDLE-before-IO, no sweep while in flight). The actual worker
  loop, journal and real-provider behavior are M-R.
- **No real provider/network.** All fixtures are in-process; the only socket
  API touched is the monkeypatched deny/restore pair.
- **No 512-page-cap change.** H13 measured 64.00 MiB for a 64-item page; the
  cap and unredacted request stay as designed.
- **No kernel edit.** The nine frozen SQL files remain byte-identical; only
  `49_host_reads.sql` (new), `50_permissions.sql`, the two loader tuples,
  `expected_canonical`, and `test_g1.py`'s exact ACL sets changed.

## Actual result

```text
[passed] v24 G8 host reads / closure / lease / recovery: 23 case(s)
```

All 23 IDs ran; the command exited 0 on 2026-10-24.
