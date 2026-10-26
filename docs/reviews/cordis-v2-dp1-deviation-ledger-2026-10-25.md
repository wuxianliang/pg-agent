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

## W3 implementation review and gate findings

- Static implementation review identified a temporary-schema catalog shadowing risk in `role_family()`: all Cordis functions now explicitly place `pg_temp` after `pg_catalog,v24_cordis`, and CDP1-K injects temporary catalog lookalikes through a foreign LOGIN and expects `unauthorized` with zero writes.
- Contract admission now requires JSON string types for both installed `handler_digest` and frozen effect binding; a numeric 64-digit digest is rejected. The inverse CHECK now requires a string-valued closed-set `op`, including an explicit `{"op":null}` negative.
- The deferred pin epoch trigger re-reads the final surviving pin row and ignores deleted rows, so intermediate update and insert/delete sequences are checked by final COMMIT state. DDL gate covers these sequences.
- Body traversal was changed to a recursive set-based walk to avoid stack-array slicing quadratic behavior; CDP1-K includes a 20,000-element wide-array boundary probe and NULL body probe.
- W3 gate final result: loader, fixture, environment, DDL and kernel exit 0; production lifecycle interpreters remain explicit `0A000`; no DP2+ lifecycle behavior is claimed.

## W4 closeout

- Final W4 reran all 11 v24 closeout commands and the separate s9 extension gate on 2026-10-26; all exit 0 and s9 reports 23 passing named cases.
- The full v24 loader/SQL/s1–s12 diff and explicit nine-frozen-SQL diff against P0 commit `57e2c1e` are empty; all twelve original v24 SQL hashes match P0; remote tracking status was synchronized before W4 (`0/0`).
- All five DP1 gates were rerun after W3 final fixes and exit 0. The final DDL gate has 97 zero-write negatives. A final review found that a missing manifest property could make its CHECK expression NULL (which PostgreSQL accepts); the full manifest predicate now requires `IS TRUE`, and a missing-`requires` probe with all other properties present rejects. Implementation review corrections described above are included in this final evidence; lifecycle handlers remain intentionally unimplemented (`0A000`).
