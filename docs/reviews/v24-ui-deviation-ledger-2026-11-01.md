# v24 UI deviation ledger (2026-11-01)

M1 only; feature branch `v24/ui-chainlit`, no push (plan D7 overrides general AGENTS main/push rule). W9 was already green before this work and is not reimplemented.

## D-UI-6 — approved install ACL and exact immutable audit manifest

User explicitly authorizes only adding `v24_admin` to the public install wrapper EXECUTE GRANT, retaining 27 SQL statements, minimal S1/S9 ACL expectations, and exact exceptions in S13/DP4/DP5/DP6 audits. Original BASEs and complete scopes remain intact; update only the permissions hash among all 12 SQL hashes. S13 retains its 12 frozen paths, whole-module renderer AST stripping exactly five W9 additions, and checks=6 marker.

DP5/DP6 retain BASE `57e2c1e` and full `v24/load.py`, `v24/sql`, S1–S12 scope. Exactly six M-status deltas are allowed and required: permissions SQL, S1 test_g1, S9 test_g8, and historical S9/S10/S11 READMEs. First three equal raw BASE blobs transformed only by unique approved literal substitutions. Other frozen files have zero diff. Reject missing delta, seventh path, non-M status, or historical README mutation. The READMEs must not be edited.

| Historical path | Source commit | Blob | SHA256 |
|---|---|---|---|
| v24/s9/README.md | f3c48a1fc11567e6f7e6bd422eb97fac3c3a29a9 | 3ac204b4ef399091e6cc2aa43765c8b22eeca981 | 0a3c64ddb0e4997d287de81b5c93582cb97320bcb18416c18f7e54fcd318551b |
| v24/s10/README.md | d8029b73e230d68c4a3817fa14a95c72151f4c02 | b37b5fe03ab43d09565d3a17a08d1c6677cdeb02 | a25595bf64d05a649313ba9a48b1e8f1c1c385a365330799be2a126787610ae3 |
| v24/s11/README.md | d13391d27f9c7363906282af4cea4160c5aa97a8 | 2fb92cdcdee994ad030a2b9046b4d8fc5cb267b4 | dc9e0e575d3cb2061eff286ae5fefa3d83b2bf8a2d36cae200c4eca484262063 |

All three sources are ancestors of pre-M1 9ba0b782797c5c2c421f6355f01d0047d1955b23 and equal that HEAD's bytes. Prior 0189029/five-path assumptions are superseded by verified provenance. Negative controls reject extra bytes, SQL admin removal/PUBLIC/second-line mutation, old S1 admin-denied block, old S9 count/negative assertion, README mutation, and seventh path.

Authorized dedicated helper `v24/ui/d_ui_6_acl.py` has --check/--apply only: exact preupgrade, ACL-upgraded metadata-old, completed states; reject other drift. Apply holds .uidata/lock and validates target agent_v24_ui, server identity, database OID and fingerprint; execute only the target admin GRANT and atomically rebind permissions digest and manifest digest. Disposable proof precedes existing-state check/apply/check. No reset/replay/load_stage; ordinary migrate remains unsupported/2. Plan/ledger/audit/ACL/helper paths are explicit M1 whitelist exceptions; host/load/design are unchanged.

Factual correction: lookup_install raises AdapterNotFound(adapter_not_approved), never None. UI RPC commits returned domain rejection envelopes and rolls back Python/SQL exceptions, leaving IDLE.

## M1 execution evidence (2026-11-02)

- Physical checkout: `/Users/wxl/Projects/pg-agent`, branch `v24/ui-chainlit`, pre-commit HEAD `9ba0b782797c5c2c421f6355f01d0047d1955b23`; main baseline `1143dce6da0572bccab083da9a6be0175210b062`; no push.
- `uv run python -m v24.ui.env --init` exit 0, last line `{"status": "ok", "loaded": ["already_initialized"]}`; `--status` exit 0, last line `{"status": "ok", "diffs": [], "db_name": "agent_v24_ui"}`; `--migrate` exit 2, last line `migration_unsupported`.
- Existing-state D-UI-6 `--check/--apply/--check` exited 0/0/0 with `preupgrade`/`completed`/`completed`; OID 4785566 and fingerprint `0f1b51ffafbdebe1facdc0d89bda27a872c1caa8881a1b52e02a7545ac1e9285` stayed unchanged. Disposable helper proof exited 0; last line `migrate=2 migration_unsupported; drift=2; reset --yes=0; persistent state untouched`.
- `uv run python -m v24.ui.control --selftest` exit 0. First run `31c5aefd-5bc5-4d90-95f9-280352728cdf` completed with `done`; pins `{read}`; actual tool effect succeeded; unspent tokens `[20000,19995,19995,19990]`; same-scope second start `914fb23e-7c21-43cb-adb3-50f936f95d39` committed and completed. The effect timeline printed three IDs, kinds, statuses, ordinals and timestamps.
- Focused S1/S9, DP4/DP5/DP6 and all 13 S13 commands passed exit 0, including `uv run python v24/s13/test_node.py --node` (`node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node`).
- Oracle review used selected diff artifacts `2026-11-02/0006` and three completed lanes. Accepted fixes: read continuation/error mapping, drift reset recovery, literal-only catalog extraction, JSON response adaptation, and selftest tool-effect assertion. D-UI-6 scope was approved unchanged; no blocker found.

Next milestone: M2, not started.
