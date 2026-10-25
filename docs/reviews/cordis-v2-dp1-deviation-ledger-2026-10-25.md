# Cordis v2 DP1 Deviation Ledger

| Date | Item | Baseline / spec | DP1 treatment | Rationale and evidence |
|---|---|---|---|---|
| 2026-10-25 | Claim token | Appendix A has `token uuid`; §3.1 protocol is `{attempt,fence,owner}` | Use attempt/fence/owner; omit UUID token | Design adjudication; keep ABI tuple authoritative. Verify in CDP1-K. |
| 2026-10-25 | resource_quiesced_at | Appendix has a timestamp; §1.2 leaves unknown resource settlement unspecified | Defer column and producer to DP6 if required | No DP1 producer/consumer; lease expiry cannot prove quiescence. |
| 2026-10-25 | events.created_at | Not required by appendix A | Omit | Cursor and G-serialized sequence do not require timestamp. |
| 2026-10-25 | Replay closure order | Generic closure language might suggest closure before replay | Lock/replay target before closure discovery | §3.2 and adjudication preserve replay under unrelated oversized closure. |
| 2026-10-25 | Empty delta | Lifecycle interpreters are not DP1 scope | Keep production interpreter seams at `0A000`; production receipt applier handles empty-domain delta | Prevent an empty probe from claiming lifecycle/DAG correctness. |
| 2026-10-25 | W1 environment | Historical versions are not current execution evidence | Record P0 command evidence separately | No historical run is represented as current. |
