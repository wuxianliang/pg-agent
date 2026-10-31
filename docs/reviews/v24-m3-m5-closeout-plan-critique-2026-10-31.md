# Critique: v24 M3–M5 closeout plan

1. **blocker — plan §9, lines 221–240; §14 M5-3, line 451.** Correction: count only `immutable_required_suites[*].status` in `design_conformance.json` (or exclude `reviewed_design_decisions`), then assert the per-file counts 8/10/5/11 and the exact 34-pointer set before adjudication.
   Evidence: the supplied walker returns 12 mapping statuses and 36 total because `reviewed_design_decisions` adds two `design_resolved` statuses at `design_conformance.json:458` and `:468`.

2. **blocker — plan §8.1, lines 201–207; §14 M5-1, line 449.** Correction: the existing revision appendix makes a dated entry mandatory; preserve the §5.1/§5.4 body lines, but allow an EOF appendix addition and change the diff check to “two body-line edits plus the dated appendix entry,” not whole-file `wc -l` invariance.
   Evidence: `docs/designs/v24-pg-agent-2026-10-22.md:656` already starts the revision appendix and `:786` explicitly prescribes inline revision plus EOF append.

3. **major — plan §5 C.18.3, line 108.** Correction: bind S06–S11 only to injected-clock time-cap/EOF/sentinel behavior, and explicitly add S01–S05 for file-cap and S12 for candidate failure ordering, as lane 2 did.
   Evidence: `docs/reviews/v24-tool-plugin-abi-w6-execution-2026-10-31.md:60-62` assigns those probes to file-cap and failure ordering; S06–S11 do not establish them.

4. **major — plan §5 C.18.4, lines 118–119.** Correction: describe the overshoot unit as the remainder of one directory batch—including `readdir`, sorting, and all entry name-filtering/`lstat`/classification—plus at most one ≤1 MiB file read/scan after the last C1 check; do not omit work from the stated upper bound or imply a constant/time bound.
   Evidence: `v24/s13/plugins/fs_tools.js:578-618` performs `readdir`, `names.sort`, and `lstat` for every non-name-filtered entry, not merely name filtering and symlink `lstat`.

5. **major — plan §5 C.18.5, lines 124–133.** Correction: restore the complete terminal decision order: source error/invalid statistics or integers → `m=0` (including empty-page budget and offset failures) → no fitting prefix → cutoff page-fill decision → success; keep the sentinel and convergence explanations after that order.
   Evidence: ABI design §5.6 at `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:778` fixes this order, and `fs_tools.js:680-756` implements it; the plan says “按顺序” but omits the first two stages.

6. **minor — plan §5 C.18.6, line 137.** Correction: apply the provenance reading only to `m2_pending/m3_pending/m4_pending/provisional_w2_pending`; remove “九个” from that claim and leave the other five tokens’ meanings unchanged.
   Evidence: `design_conformance.json:10-19` also includes `planned`, `design_resolved`, `pending_vectors`, `pending_reference`, and `not_run`, which are not first-production-evidence labels.

7. **major — plan §5 C.18.2, line 102; §10, lines 350–358; §14 M3-3, line 444.** Correction: require extraction of the current row-29 full-log R26 read evidence and S25 real-clock probe, record their actual values, and explicitly verify R26 succeeded under the unchanged 5000 ms deadline rather than copying W5’s 113 ms or recording only the final marker.
   Evidence: `v24/s13/test_tools.py:1248-1249` and `:1705-1709` print S25/R26 before the final marker at `:1710-1714`; M3-3 names T1/T2/T3 and artifacts but omits C.18.2(d)’s fresh read observation.

8. **major — plan §9, line 221 and tables at lines 250–303; §11.3, line 384.** Correction: make every adjudication row contain JSON pointer/case ID, frozen token, `first_production_stage`, satisfying stage, current evidence log with sweep row plus marker/probe, verdict, limitation, and frozen-byte audit result.
   Evidence: lane 1 requires record-plus-marker and both stage fields （lane 1 的 adjudication 段）, and lane 2 requires current log/limit/audit columns （lane 2 的 M5 record 段）; the plan retains only generic evidence labels.

9. **major — plan §14 M5-0, line 448; §17, lines 512–522.** Correction: restore a read-only evidence-review prerequisite before M5-3 for the W1–W4 execution records, W4/W5 plans, and W5/W6 critiques, and use those sources when binding the adjudication’s stage evidence.
   Evidence: lane 2 makes exactly these reviews mandatory in lane 2's references section, while the plan checks only `test_wiring.py` at line 378 and cites only W5/W6 execution records.

10. **major — plan §8.2, lines 211–217; §14 M5-2 and dependency graph, lines 450 and 459–462.** Correction: have D2 cite the newly revised main-design §5.1/§5.4 text and make M5-2 depend on M5-1; only M5-3 remains independent/parallel.
    Evidence: lane 2 explicitly requires the new-main-design citation in lane 2's drift-factcheck and work-item sections; the plan drops both and declares M5-2 parallel with M5-1.

11. **major — plan §3.1, line 51; §12.1, lines 388–400; §14 M3-6 and §15 M3 staging.** Correction: before M3-0, decide whether this requested critique is a publication candidate; if yes, add it to the snapshot, candidate set, audit, and staging and change nine paths to ten, otherwise explicitly record its exclusion and leave it unchanged outside the candidate delta.
    Evidence: the plan omits `docs/reviews/v24-m3-m5-closeout-plan-critique-2026-10-31.md`, whereas the analogous W6 critique is an explicit candidate in `docs/reviews/v24-tool-plugin-abi-w6-execution-2026-10-31.md:19`.

12. **minor — plan §4 DM7, line 86; §5 C.18.1, line 97 and C.18.7, line 149.** Correction: restore the M5 row to C.18.1’s continuation table so the claimed M5 authority has the same explicit stage binding as M3.
    Evidence: lane 1 specifies both M3 and M5 continuation rows in lane 1's C.18.1 table; the plan retains only M3 while asserting that C.18 fixes M5’s reading.

## Re-review of the 554-line plan revision

Findings 1–12 above apply to the pre-revision plan; findings 13–18 below apply to the current revision.

13. **blocker — plan §9.4, line 322; §4 DM7, line 86; §11.2 audit 3, line 389.** Correction: use `2307077` only for M3’s one-SHA-line diff, but use the actual M3 commit SHA for M5’s required empty `git diff --exit-code <M3-SHA> -- v24/s13/vectors`.
    Evidence: M3 necessarily leaves `design_conformance.json` at new digest `S1`, so the line-322 command against `2307077` cannot be empty in M5 without a forbidden second repin.

14. **major — plan §5 C.18.5, lines 135–136.** Correction: remove `offset_out_of_range` from the pre-`m=0` source-error stage; handle empty-snapshot offset errors in `m=0`, and nonempty complete-snapshot offset errors after snapshot validation but before prefix enumeration.
    Evidence: `v24/s13/plugins/fs_tools.js:680-715` executes the `total===0` branch first and only then checks `offsetBig > totalBig`; ABI §5.6 at design line 778 also places empty-set offset handling in `m=0`.

15. **major — plan §5 C.18.1, lines 98–105; C.18.7, line 157.** Correction: label both continuation rows as done-when conditions, state that actual declarations require their respective execution records, and either add SQL zero-diff plus 11/11 to the M5 row or explicitly defer to C.18.7’s full conjunction.
    Evidence: the M3 append would otherwise contain an unconditional `M5 完成` while the plan Result at lines 547–552 says M5 is unrun, and the row omits two M5 requirements stated at line 157.

16. **major — plan §7.4, line 201.** Correction: extend the investigation Resolution to map reconciliation #15 to D-ABI-W6-1/S17/C.18.7, #16 to W6 S02/D-ABI-W6-10, and Finding 1’s safe-integer and timing work to D-ABI-W6-9 and D-ABI-W6-2/3 respectively.
    Evidence: `docs/investigations/v24-m3-budget-closeout-2026-10-31.md:187-193` names #15/#16 as the only remaining disagreements, but the planned Resolution omits both and cites only W6-10/11/12 for all of Finding 1.

17. **minor — plan §12.2, line 424; §8.1, line 215; §14 M5-1, line 468.** Correction: replace “可选修订记录” with the required dated Appendix C entry used by the operative instructions.
    Evidence: sections 8.1 and M5-1 mandate the appendix entry, while the file-by-file table alone makes it optional.

18. **minor — plan §9.3, line 304; §9, line 231; §14 M5-4, line 471.** Correction: record the actual artifact digests from M5’s row-29 R28/S24 execution and use W5/W6 values only as historical cross-checks; do not describe the fresh verification as “不当作新实测.”
    Evidence: the plan requires current evidence in every adjudication row and a fresh M5 sweep, and R28/S24 recompute source/copy/entry digests in `test_tools.py` as recorded by W5/W6.
