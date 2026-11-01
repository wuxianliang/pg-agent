# v24 Chainlit UI conformance matrix — M1 (2026-11-02)

Scope is M1 only on `v24/ui-chainlit`. W9 was green before this work; no W9 implementation or M2 work was started. The S13 regression commands below verify compatibility after D-UI-6.

| Acceptance | Actual command | Exit | Last line / observed result |
|---|---|---:|---|
| Persistent init | `uv run python -m v24.ui.env --init` | 0 | `{"status": "ok", "loaded": ["already_initialized"]}` |
| Persistent status | `uv run python -m v24.ui.env --status` | 0 | `{"status": "ok", "diffs": [], "db_name": "agent_v24_ui"}` |
| Migration boundary | `uv run python -m v24.ui.env --migrate` | 2 | `migration_unsupported` |
| Disposable helper/persistence proof | `PYTHONPATH=/Users/wxl/Projects/pg-agent uv run python /tmp/v24-m1-disposable.py` | 0 | `[disposable] migrate=2 migration_unsupported; drift=2; reset --yes=0; persistent state untouched` |
| Existing D-UI-6 before | `uv run python -m v24.ui.d_ui_6_acl --check` | 0 | `{"status": "preupgrade"}` |
| Existing D-UI-6 apply | `uv run python -m v24.ui.d_ui_6_acl --apply` | 0 | `{"status": "completed"}` |
| Existing D-UI-6 after | `uv run python -m v24.ui.d_ui_6_acl --check` | 0 | `{"status": "completed"}` |
| Runtime | `uv run python -m v24.ui.control --selftest` | 0 | `[effect] id=9a828def-443a-3e6c-fee6-f74d6af4afb9 kind=model_call status=succeeded ordinal=0 created_at=2026-11-02T00:30:39.8538+08:00` |
| Oracle correction checks | `PYTHONPATH=/Users/wxl/Projects/pg-agent uv run python /tmp/v24-m1-review-checks.py` | 0 | `[passed] disposable CLI empty-init recovery, SQL/OID/manifest drift, lock=3, migrate=2, reset drift=0; persistent untouched` |

The temporary diagnostic scripts exercised disposable servers only. Their observed cases: create-only/idempotent init, exactly ten tables, failed-initial-init recovery, SQL/OID/fingerprint/manifest/version drift, lock exclusion, unsupported migration, explicit reset, all three helper states, unexpected PUBLIC ACL rejection, activation rejection cleanup and incomplete-close state retention. The persistent helper sequence ran only after disposable proof. OID `4785566` and fingerprint `0f1b51ffafbdebe1facdc0d89bda27a872c1caa8881a1b52e02a7545ac1e9285` were unchanged; only the permissions and manifest digests in loaded.json were rebound.

The final selftest printed run `31c5aefd-5bc5-4d90-95f9-280352728cdf`, completed with `done`, exactly `{read}` pins and tools, an actual succeeded read with exact fixture output, and unspent token samples `[20000,19995,19995,19990]` (10 spent). Same-scope second start `914fb23e-7c21-43cb-adb3-50f936f95d39` committed and completed. Three durable effect IDs/kinds/statuses/ordinals/timestamps were printed. Python/SQL RPC errors rolled back to IDLE, and returned rejected domain envelopes committed. A separate in-memory pagination check verified 1-based offsets 1/2/3, complete lines and continuation offsets 2/3; Pi's original read descriptor confirms 1-indexed semantics.

| Affected gate command | Exit | Exact last line |
|---|---:|---|
| `uv run python v24/s1/test_ddl.py` | 0 | `[passed] v24 W2 G1-O owner DDL probes (no advance/ACL/lifecycle claim)` |
| `uv run python v24/s1/test_g1.py` | 0 | `[passed] v24 G1 kernel, commands, claim, locks, host_prepare settlement and ACL` |
| `uv run python v24/s9/test_g8.py` | 0 | `[passed] v24 G8 host reads / closure / lease / recovery: 23 case(s)` |
| `uv run python v24/cordis/dp4/test_closeout.py` | 0 | `[passed] CDP4-B` |
| `uv run python v24/cordis/dp4/test_loop.py` | 0 | `[passed] CDP4-T` |
| `uv run python v24/cordis/dp4/test_reducer.py` | 0 | `[passed] CDP4-M` |
| `uv run python v24/cordis/dp4/test_run.py` | 0 | `[passed] CDP4-R` |
| `uv run python v24/cordis/dp5/test_boundaries.py` | 0 | `[passed] CDP5-B (W5: B1-B6 final layout, ACL, capacity, seed/closure, bounds, frozen)` |
| `uv run python v24/cordis/dp5/test_dispatch.py` | 0 | `[passed] CDP5-D (W3: D1-D12 atomic producer, five modes, host path, fences, limits)` |
| `uv run python v24/cordis/dp5/test_listeners.py` | 0 | `[passed] CDP5-E (W2: E1-E7 registration/revocation subset; ordering/unavailable/real drain are W3 D evidence)` |
| `uv run python v24/cordis/dp5/test_resolution.py` | 0 | `[passed] CDP5-R (W4: R1-R8, five-mode reference, purity and host premises)` |
| `uv run python v24/cordis/dp6/test_boundaries.py` | 0 | `[passed] CDP6-B (W5: whole layout/ACL, three interpreters/terminal/replay/slot, closure/successor/protocol bounds, frozen surfaces)` |
| `uv run python v24/cordis/dp6/test_dispose.py` | 0 | `[passed] CDP6-U/D` |
| `uv run python v24/cordis/dp6/test_recovery.py` | 0 | `[passed] CDP6-R` |
| `uv run python v24/cordis/dp6/test_scanner.py` | 0 | `[passed] CDP6-S` |
| `uv run python v24/cordis/dp6/test_upgrade.py` | 0 | `[passed] CDP6-H` |

| S13 command (all 13 required gates) | Exit | Exact last line |
|---|---:|---|
| `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` |
| `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` |
| `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` |
| `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` |
| `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3; text_positives=9; text_negatives=21` |
| `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` |
| `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` |
| `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` |
| `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` |
| `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` |
| `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` |
| `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true` |
| `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` |

Additional Node vector command `uv run python v24/s13/test_vectors.py --node` exited 0; exact last line: `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=checked`.

D-UI-6 retains BASE `57e2c1e` and the full load/sql/S1–S12 scope. Exactly six M paths are accepted: permissions SQL, S1 test_g1, S9 test_g8, and immutable historical S9/S10/S11 READMEs. The first three use unique literal substitutions of raw BASE bytes; the README source commits/blobs/SHA256 are pinned in the plan and ledger and their bytes were not edited. DP5 and DP6 each printed `[D-UI-6] exact six M paths; immutable provenance and in-memory negatives passed`. Negatives reject extra bytes, missing/seventh paths, non-M status, admin removal/PUBLIC/another SQL-line mutation, old S1 denial, old S9 count/negative assertion and README mutation. All twelve SQL hashes remain checked with only the permissions hash changed. S13 retains BASE `c8c4bd0`, twelve frozen paths, whole-module renderer AST comparison stripping exactly five W9 additions, and `[scope] passed base=c8c4bd0 checks=6`. DP4 retains its original BASE/scope and an exact permissions-byte exception.

The mandatory Oracle review used explicit selection plus git diff artifacts snapshot `2026-11-02/0006`; all three lanes completed. Initial requests for correction concerned drift reset, read continuation, lifecycle cleanup, JSON adaptation, executable catalog extraction and the selftest's actual-read assertion. These were corrected in scope and verified by the runtime/disposable checks above. No D-UI-6 scope blocker was found. No second review was requested.

Observed compatibility deviation: db_fingerprint retains the pre-existing deterministic functions-then-columns compact JSON encoding so the existing environment remains loadable. No host/load/design changes. Physical checkout `/Users/wxl/Projects/pg-agent`; pre-M1 HEAD `9ba0b782797c5c2c421f6355f01d0047d1955b23`; main baseline `1143dce6da0572bccab083da9a6be0175210b062` remains unchanged. No push. Next milestone: M2, assigned separately.
