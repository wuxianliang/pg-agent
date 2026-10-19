# v13 Stannum 0.5.1 Compatibility Upgrade

## Scope And Decision

2026-10-19 user instruction supersedes the earlier proposal to isolate 0.4.0:
upgrade related pg-agent code/docs to 0.5.1, consult Oracle, implement, then
resume registry Phase 3. Oracle `untitled-chat-52843A` selected a separate
upgrade milestone U, not a relaxation of the Phase 3 docs-only boundary.

Baseline: v99/origin/v99 `93d05f12090ce4b27b62b1a6f90d3c1b438eab68`.
The fourteen unfinished Phase 3 documents are preserved in scoped stash
`99d334fe90af613605b6e9ec2a7d7c0a3c5abd2d`; the unrelated untracked Stage41
review is excluded. Do not drop the stash until restoration is verified.

## One Upgrade Milestone

1. Pin usage V1/V2/V3/R17 to exactly 0.5.1 through a fixed test constant.
   Keep PG18 and pgembed 0.3.0rc2 checks. Preserve production queries, SQL,
   indexes, jieba, grants, loader, dependencies and all existing P/F/R guarantees.
2. Add V12: owner can read capabilities. Actual API is `contract_version` plus
   nested `engine.name/format`; Oracle's suggested top-level contract/format
   keys were corrected against upstream source before implementation.
   Contract engine.version is not the package version. Do not pin all features.
3. Add V13a/b/c: unique template0 database, no extension/AM, LOAD actual
   installed module, ordinary constant/catalog planning succeeds before CREATE,
   then CREATE exact 0.5.1 in that backend and query again. Always close/drop
   only the database created by this helper; cleanup failure is a gate failure.
4. Audit frozen guards. Restore only exact approved final file bytes to the
   fixed pre-upgrade baseline before running all original freeze proofs. Never
   skip an entire file or move the historical base. Prove version regression,
   out-of-block mutation, assertion deletion and unrelated-file mutation fail.
   Confirm ordinary-file type and historical Git mode before normalization;
   executable-bit and symlink mutation negatives must fail too.
5. Update current mgraph/characterize README entry points and migration limits;
   keep historical observations and frozen SQL comments unchanged. Add a
   separate upgrade report and matrix/ledger rows, not Phase 3 PASS claims.
6. Serial targeted checks: characterize, both mgraph gates, plan_arm,
   frontier_gap, goal_supervise, goal_supervisor, fair_claim, fair_driver,
   loop_driver, workspace_admit, parity, ports, read_tools, both registry gates. Then independent complete 51-item upgrade
   regression with frozen UV and existing offline PiSwift environment. Expected
   49 exit 0, #17 exit 1/refusal, #18 exit 2/usage; every trace restored.
7. All tests green and artifacts current: scoped stage, normal hooks, commit
   `v13: validate Stannum 0.5.1 compatibility`, immediately push origin/v99.
   No main/force push, no unrelated Phase 3 documents or ignored artifacts.
8. Restore Phase 3 stash without dropping it, retain U matrix/ledger rows,
   re-lock baseline to pushed U, retain old run01 RED, then run two new full
   Phase 3 sequences for A/B. Upgrade results cannot substitute either round.

## Allowed Changes

Usage gate, plan_arm shared freeze proof and test_stage_bytes; test_stage_bytes
bodies in workspace_admit/frontier_gap/goal_supervise/goal_supervisor/fair_claim/
fair_driver (local diff comparisons independently reject the approved changes), mgraph/characterize README,
this plan, upgrade report, control-plane matrix/ledger and the current-version
inventory in docs/designs/v13-rag-subagent.md. Other freeze entry
points change only if direct investigation proves a duplicate blocker; record
exact functions before editing. No new files under registry or runtime changes.

## Storage And Operations

0.4 kind-1/LSG indexes require ordinary non-concurrent REINDEX under 0.5;
catalog-only ALTER does not convert storage. New STN3 cannot be read by 0.4.
Existing installations require backup, quiesce, CHECKPOINT/clean stop, one
matching library, restart, per-database ALTER EXTENSION, rebuild every index,
verify and application checks before traffic. Replicas are rebuilt; rollback
is restore, not a binary downgrade. 0.5.0->0.5.1 SQL is no-op but old backends
must reload the fixed library. No production migration is executed here.
Stage databases are disposable DROP/CREATE installations. Do not alter external
Stannum/pgembed/PiSwift checkouts, which may contain user work.

## Execution

U implementation and acceptance PASS. Original Phase 3 run01 RED (#26 V1,
actual 0.5.1 vs required 0.4.0) is retained separately in its stash/receipt;
#27-51 were NOT RUN. Targeted run02 completed 16/16. Oracle implementation review
returned one P1 and two P2 findings; file type/mode checks, BaseExceptionGroup,
and the nine-file ledger correction were implemented. Both changed gates and
mutation/cleanup checks passed again. Independent upgrade51 run01 completed
51/51 contracts, 908.70s, 49 exit0 plus expected exit1/2; all traces restored,
registry485/consumer289 manually checked, final PiSwift verify green. Detailed
per-item results are in the upgrade report. U commit/push is the next required
operation; no future identity or push result is prefilled. Phase3 A/B remain
pending and require their own independently restarted sequences after U.
