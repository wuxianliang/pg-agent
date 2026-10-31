# v24 Tool/Plugin ABI W6 plan critique

Date: 2026-10-31. Scope: the W6 plan and only the two `## Generated Plan` lanes in the context_builder export (lane 1: export 209–947; lane 2: export 955–1557). `PLAN` below means `docs/plans/v24-tool-plugin-abi-w6-node-list-search-2026-10-31.md`; `EXPORT` means `prompt-exports/oracle-plan-2026-10-31-161447-deep-plan-w6-node-li-50a2.md`.

This review does not reopen the settled baseline, D3 glob accounting, footer-inclusive `27+E(text)`, O1–O6, or the post-W5 `test_tools.py` line map. Corrections below preserve `cases=140` by adding variants to existing probes or moving coverage between existing rows, not by adding probe rows.

## Blockers

### 1. The 32 gate commands are not executable as written

- **Location:** `PLAN:383-416`.
- **Evidence:** commands 1–31 are listed as bare paths (or bare `python -m` for command 28), without the required `uv run python` runner. Lane 2 gives the executable commands explicitly at `EXPORT:1360-1391`; the repository convention is also `uv run python ...`.
- **Correction:** prefix commands 1–31 with `uv run python`, including command 28 (`uv run python -m v24.host.plugin_smoke --multilingual-smoke`), under `$ENVPFX`. Leave command 32 as the exact `git diff --exit-code c8c4bd0 -- v24/sql` check. Do not change their order or count.

### 2. S11 expires one clock call too early; S10(a) no longer proves the intended EOF boundary

- **Location:** `PLAN:322-323`, with the C0/C1 contract at `PLAN:188-193`.
- **Evidence:** C0 is call 1; the C1 calls for `a0`, `a1`, and `a2` are calls 2, 3, and 4. S11 says the clock expires on call 4 but expects `stopReason:"sentinel"` from the third hit. That clock instead produces `time-cap` before `a2` is inspected. Lane 1 correctly specifies expiry on call 5 while expecting four calls (`EXPORT:638`); the sentinel is set only after the complete hit is pushed (`v24/s13/plugins/fs_tools.js:477-480`). S10(a) also omitted lane 1's expiring clock (`EXPORT:637`), reducing it to an ordinary EOF test.
- **Correction:** in S11, expire on the **5th** `now()` call and retain `nowCalls:4`, `stopReason:"sentinel"`. In S10(a), inject expiry on the **3rd** call; exactly two calls must occur before EOF, yielding `complete:true` and `stopReason:"eof"`.

### 3. L03's expected `total` omits the visible directory entry

- **Location:** `PLAN:348`.
- **Evidence:** the fixture contains visible directory `d` and visible file `d/f`; `.git` and `d/.git` are excluded. `listScan` appends a directory before recursing into it (`v24/s13/plugins/fs_tools.js:281-285`), so the result has two entries, not one.
- **Correction:** expect `total:2` and entries `d`, `d/f`, while asserting that neither `.git` subtree appears. For the injected boundary in this same tree, four raw entries are consumed (`.git`, `d`, `d/.git`, `d/f`): `scanLimit:4` succeeds and `scanLimit:3` raises `directory_too_large`.

### 4. L08 expects a recursive child from a non-recursive invocation

- **Location:** `PLAN:353`.
- **Evidence:** the row says `直连非递归` but includes `a/c` in both fixture and expected order. Recursion is the only path that descends into `a` (`v24/s13/plugins/fs_tools.js:281-285`). Lane 1 explicitly called for a recursive list of `a/c` (`EXPORT:668`).
- **Correction:** invoke L08 with `recursive:true` (or split the row into non-recursive root ordering and a recursive variant). The expected order `B,a,a-b,a/c,é,～,😀` is then consistent with UTF-8 path-byte ordering.

### 5. L07 names a fixture that the existing workspace/shim cannot create

- **Location:** `PLAN:352` and the reuse decision at `PLAN:241`.
- **Evidence:** L07 requires `sub/<0xff>` and `sub/ok`, but `workspace(root,"list")` materializes the fixed tree in `v24/s13/fixtures.py:242-252`, whose invalid name is at the root and which has no such `sub` tree. The preload injects only into the one configured root realpath (`v24/s13/w4b_non_utf8_preload.cjs:34-58`), not arbitrary subdirectories. Lane 1 explicitly retained this limitation and marked the macOS subdirectory variant `not_run` (`EXPORT:667,883`); the plan dropped that limitation while strengthening the claim to “非 UTF-8 子目录条目”.
- **Correction:** for the current candidate scope, make L07 a root-level non-UTF-8 entry probe using the existing workspace/shim, and state that subdirectory injection is not covered on macOS. If subdirectory coverage is mandatory, explicitly add a test-only shim change and its path to the candidate allowlist instead of pretending the existing fixture supplies it; see question Q1.

### 6. S25 rejects a valid fast run and allows an impossible incomplete-empty success

- **Location:** `PLAN:337`; compare the correct outcome wording at `PLAN:144`.
- **Evidence:** S25 has no hits. If the 10,000-file scan reaches EOF within the injected 50 ms budget, the valid result is a **complete empty success**. If time-cap occurs, `m=0` requires `search_scope_too_large`; an incomplete empty success is forbidden by the snapshot and empty-page rules (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:774,778`). Thus the table's set `{成功 incomplete 页, search_scope_too_large}` is wrong in both directions and can make a valid fast environment fail despite the no-wall-clock-gate decision.
- **Correction:** require exactly one of `{complete:true,total:0,hits:[]}` success or `search_scope_too_large`. Record elapsed/overshoot in either case and impose no elapsed-time pass/fail threshold.

## Should-fix findings

### 7. The synthesized L10 dropped both lanes' default-argument probe, leaving `Done when` uncovered

- **Location:** default behavior is promised at `PLAN:58`, but L10 became the 10,000-entry cap probe at `PLAN:355`.
- **Evidence:** both lanes define L10 as defaults (`EXPORT:670` and `EXPORT:1330`). No remaining L01–L11 row compares omitted arguments with `path:"."`, `recursive:false`, `include_hidden:false`, `offset:1`, `limit:500`.
- **Correction:** restore L10 to a byte-for-byte omitted-vs-explicit defaults comparison. Move the real 10,000/10,001 raw-entry cap boundary into L03, which already owns scan-cap accounting. This preserves 11 list probes and `cases=140` while covering both requirements.

### 8. The red-baseline inventory contradicts the final D3 behavior and the probes' own invocation paths

- **Location:** `PLAN:215` and `PLAN:366-373`.
- **Evidence:**
  - S17(a) is labeled red, but final D3 keeps pre-glob incrementing (`PLAN:156-158`), which is already the old code at `v24/s13/plugins/fs_tools.js:441-442`; its expected `scanned_files:3` is old-green.
  - L01, L08, and L09 are existing behavior and are old-green in both lanes (`EXPORT:680,1173`), not red.
  - L02(b) needs the new exported `listTool` and injected `caps`, so it cannot run on the old file; it is green-only, like L02(a).
  - S16's direct raw unsafe-offset subcase needs no new seam and is red on old code: old validation accepts the rounded integer (`v24/s13/plugins/fs_tools.js:544-549`) and later returns `offset_out_of_range` (`:595-600`), whereas the new expectation is `invalid_path`. Lane 1 identifies this red subcase at `EXPORT:643,677`.
  - L10(b) is explicitly a direct 10,001-entry invocation at `PLAN:355`, so it is old-green, not seam-dependent green-only.
- **Correction:** rebuild W6-1 around three honest classes: old-runnable red (at least S01, S13, S16 raw subcase, and S24's missing-constant assertion), old-runnable green regression guards (including S17(a), L01, L08, L09, and the direct 10,001-entry cap case), and green-only seam probes (including all of L02). Optionally retain the lanes' separate “right code for the wrong reason” label for direct S03–S05 variants; do not call those red.

### 9. The safe-integer work omits renderer arithmetic and no longer tests `addSafe` overflow

- **Location:** `PLAN:209`, `PLAN:253-265`, `PLAN:276,284`, and S16 at `PLAN:328`.
- **Evidence:** lane 1 explicitly included `listText`/`searchText` arithmetic (`EXPORT:508`), but the plan only names candidate/cursor sites. The retained renderers still compute `value.offset + value.entries.length - 1` and `value.offset + count - 1` at `v24/s13/plugins/fs_tools.js:213-214,237-243`. Also, both lanes had a direct helper-overflow check (`EXPORT:643,1306`); the final S16's safe-large-offset case exits through `offset_out_of_range` before any overflowing cursor addition, and `addSafe` is not exported in the proposed export list.
- **Correction:** include both renderer footer/summary calculations in the BigInt/safe-integer audit, converting back to `number` only after a safety check. Export `addSafe` for the JS probe and add S16(c): `addSafe(2**53-1,1)` must raise the classification selected after resolving Q2 (D11 currently says `io_error`), without leaking a `TypeError` or emitting JSON. Keep these as S16 variants, not new probe rows.

### 10. The four-budget seam is incomplete, and the new search empty-page branch has no probe

- **Location:** `PLAN:168`, `PLAN:197`, `PLAN:260-284`, S12 at `PLAN:324`, and L02 at `PLAN:347`.
- **Evidence:**
  - `emptyMeasures(value)` refers to an undefined `text`; lane 1's implementable shape was `emptyMeasures(value, extraText)` (`EXPORT:569`).
  - Existing non-empty candidate predicates check only value/content/frame (`v24/s13/plugins/fs_tools.js:347-350,625-628`). Replacing those constants with `caps.*` does not implement the new `caps.meta` domain. Lane 2 explicitly calls for value/content/meta/frame injection (`EXPORT:1144,1322`).
  - `PLAN:197,277` adds search empty-page `output_too_large`, but S01–S26 exercise only list empty-page budget failure; L02(b) checks only `caps.content:1`.
- **Correction:** define `emptyMeasures(value,text)` and pass `listText(value)` or `searchText(value)` explicitly. For every empty and non-empty candidate, check all four domains, using `meta=2` for the default `{}` meta. Parameterize L02 and S12 variants across value/content/meta/frame; extend S12 with search `eof,total:0,offset:1` narrow-cap cases returning `output_too_large`, plus offset-2 precedence. These are variants within existing rows, so marker counts stay fixed.

### 11. D14/S26 retain a wall-clock STOP and a false monotonicity rationale, while the required structural measurement has no defined seam

- **Location:** `PLAN:227-229`, `PLAN:338`, and `PLAN:512,547`.
- **Evidence:** D14 still says `>1500 ms` triggers STOP, contradicting the settled structural-count criterion and the later risk/Oracle text. D14 also claims the four budget measures are monotonic in prefix length; §5.6 explicitly forbids that assumption because the final-page footer can make fitness non-monotonic (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:775,777`; lane 1 also says “不假设单调” at `EXPORT:661`). Finally, S26 requires cumulative `JSON.stringify`/`escapedLen` counts or bytes but no production option/export supplies them.
- **Correction:** make only the structural-count excess a STOP; `enum_cost_wall_ms` is informational, with no automatic 1500 ms gate. Justify full enumeration by non-monotonic fitness, not monotonic budgets. For a concrete zero-production-seam measurement, wrap `JSON.stringify` inside the JS probe around `searchTool`, restore it before serializing the probe result, and assert the exact expected candidate-measurement count (three existing serialization sites per candidate, hence 600 for S26's 200 candidates if meta remains the literal measure `2`). Alternatively specify an equally exact serialized-byte bound before implementation; do not leave an “or” choice to the executor.

### 12. `expect_error` does not provide the strict error assertions attributed to it

- **Location:** `PLAN:121`.
- **Evidence:** the plan says the existing helper checks closed-set code, message size, and absolute-path absence. The actual post-W5 helper only asserts `ok is False` and equality with the caller-supplied code (`v24/s13/test_tools.py:202-206`). Direct `invoke` bypasses host validation, so those extra properties are otherwise unasserted. Lane 1 called for unified error-shape checks at `EXPORT:611`.
- **Correction:** add a test-local `check_error`/`expect_error` wrapper that validates the error envelope, exact expected code, UTF-8 message length ≤1024 bytes, and absence of the workspace absolute path. Have `js_call` return the caught message as well as the code so JS-layer failures receive the same checks. Do not impose descriptor closed-set membership on the deliberately ledgered `output_too_large` case.

### 13. Closeout requirements from both lanes were narrowed out of the ledger, and the evidence layout omits the baseline snapshot

- **Location:** evidence layout at `PLAN:436-444`; ledger inventory at `PLAN:485-496`; snapshot requirement at `PLAN:424,452`.
- **Evidence:** `baseline-untracked.txt` is required for audit 7 but absent from the evidence directory list; lane 1 includes it at `EXPORT:770`. The final eight ledger rows omit the stop-reason/post-selection correction, slashless basename decision, options/no-env-argv seam, W4 O8=B follow-up, and the `linux_real=not_run` limitation, all present in lane 1's ledger (`EXPORT:824-833`) and lane 2's required ledger topics (`EXPORT:1435`). These are closeout artifacts, not optional prose.
- **Correction:** add `baseline-untracked.txt` to `/tmp/w6-<UTC>/`. Extend the ledger inventory to cover those five omitted topics while retaining D-ABI-W6-1..8's frozen decisions; assign final numbers when writing the ledger rather than dropping topics to preserve the current numbering.

### 14. The host-deadline failure behavior present in lane 2 is missing

- **Location:** the 3-second margin and bounded-item discussion at `PLAN:77,188-193`; limits at `PLAN:522-529`.
- **Evidence:** lane 2 states that synchronous filesystem calls cannot be cancelled mid-call and that overshoot beyond 15,000 ms is classified by the host as unknown `timeout` (`EXPORT:1017-1019,1249-1255`), with a corresponding STOP risk (`EXPORT:1501`). The plan records operation-count overshoot but not this externally visible failure mode.
- **Correction:** add the existing behavior to Risks and “W6 不证明什么”: a synchronous operation can overrun both budgets; if the host deadline wins, the result is unknown `timeout`, not `search_scope_too_large`. Such a harness result stops closeout for investigation; do not raise either cap or convert it into a wall-clock timing gate.

## Nit

### 15. The artifact tamper probe lacks mandatory cleanup

- **Location:** `PLAN:245,336`.
- **Evidence:** lane 2 explicitly requires restoring the temporary copied artifact in `finally` (`EXPORT:1179`). The plan only says to flip a byte and expect rejection, so a later probe using the same spec could inherit poisoned state.
- **Correction:** call `spec.entry.require_artifact()` directly for the counter-proof, wrap mutation in `try/finally`, restore the original bytes in `finally`, and verify the digest again before continuing.

## Material questions

- **Q1 — non-UTF-8 ownership and scope (blocks L07):** is W6 required to prove a non-UTF-8 entry **inside a subdirectory** on macOS, or is root-level shim evidence plus an explicit subdirectory limitation sufficient? The former requires a deliberate test-only shim/candidate-scope expansion before W6-1; the latter permits the smaller correction in finding 5.
- **Q2 — theoretical safe-add overflow classification (changes S16 and the ledger):** `PLAN:209,261` chooses plugin `io_error`, while §5.6 names `invalid_tool_output` for unsafe cursor/statistics (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:777`). Confirm that D11's host-only boundary intentionally makes the defensive plugin branch `io_error`, and record that deviation before writing S16(c). This is separate from settled O5, which only fixes unsafe **input** as `invalid_path`.
