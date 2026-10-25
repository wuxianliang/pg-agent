# Cordis v2 DP1 Deviation Ledger

| Date | Item | Baseline / spec | DP1 treatment | Rationale and evidence |
|---|---|---|---|---|
| 2026-10-25 | Claim token | Appendix A has `token uuid`; §3.1 protocol is `{attempt,fence,owner}` | Use attempt/fence/owner; omit UUID token | Design adjudication; keep ABI tuple authoritative. Verify in CDP1-K. |
| 2026-10-25 | resource_quiesced_at | Appendix has a timestamp; §1.2 leaves unknown resource settlement unspecified | Defer column and producer to DP6 if required | No DP1 producer/consumer; lease expiry cannot prove quiescence. |
| 2026-10-25 | events.created_at | Not required by appendix A | Omit | Cursor and G-serialized sequence do not require timestamp. |
| 2026-10-25 | Replay closure order | Generic closure language might suggest closure before replay | Lock/replay target before closure discovery | §3.2 and adjudication preserve replay under unrelated oversized closure. |
| 2026-10-25 | Empty delta | Lifecycle interpreters are not DP1 scope | Keep production interpreter seams at `0A000`; production receipt applier handles empty-domain delta | Prevent an empty probe from claiming lifecycle/DAG correctness. |
| 2026-10-25 | W1 environment | Historical versions are not current execution evidence | Record P0 command evidence separately | No historical run is represented as current. |

## W2 implementation / gate findings

- Initial DDL gate failed on Python quoting, UUID adaptation, seed updates that correctly hit immutable guards, deferred constraints tested before transaction-end, and an omitted expected NOT NULL SQLSTATE. Corrected the tests; no production guard was weakened.
- Initial scope cycle guard ran BEFORE rows and admitted a two-row cycle. It is now an AFTER, initially-deferred constraint trigger and checks the final parent graph. Current-episode deferred checks likewise query final stored rows so an intermediate pointer can be cleared/replaced before COMMIT.
- Install/fiber historical owner episode FKs are deferred to support constructing cyclic declaration references in one transaction without mutating immutable ownership later. All references remain enforced at COMMIT.
- Final W2 loader/self-check/environment/DDL commands exit 0; CDP1-D reports 88 zero-write negatives plus positive and actual COMMIT failure cases.
