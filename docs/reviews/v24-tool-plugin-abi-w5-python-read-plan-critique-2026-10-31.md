# W5 Python `read` plan — focused critique

Date: 2026-10-31.

Reviewed artifacts:

- Plan: `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md`.
- Baseline: only the `## Generated Plan` portion of `prompt-exports/oracle-plan-2026-10-31-133506-deep-plan-w5-python-6010.md:171-1112`. The opening prompt and selected-file inventory are not treated as plan content. Lane 1 is partial; lane 2 is complete.

The plan is not implementation-ready: one ruling is unsupported by the cited export, and five material algorithm/test/audit issues need correction. The accurate low-level formulas and host/deadline analysis should be retained.

## Findings

### 1. Blocker — the export does not support the recorded six-item Oracle adjudication

**Plan location:** `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:188-199,229-231,554-565`.

The plan says both lanes returned completely and all six questions were adjudicated as A, including ledger-only handling of empty-page `output_too_large` with no design repin. The export says the group failed and lane 1 is partial (`prompt-exports/oracle-plan-2026-10-31-133506-deep-plan-w5-python-6010.md:171-192`); lane 1 actually ends mid-risk-table (`:760-762`). Complete lane 2 recommends the opposite design disposition: add Appendix C.18 for the plugin's empty-page exception (`:775,857-863`), then atomically update `test_contracts.py` and `design_conformance.json` (`:1026-1054`).

**Correction:** do not describe this as an Oracle consensus. Record lane 1 as incomplete and lane 2's C.18 recommendation accurately. Before W5-0, resolve this material question with evidence of a real post-export ruling:

- If C.18 is selected, restore the design/pin work item, the two pin-file changes, candidate paths, and the repin form of scope audit 3 before plugin implementation.
- If ledger-only behavior is explicitly selected later, retain the no-design path but cite that separate adjudication; it is not in this export.

Until then D6/D12 and the implementation order are unresolved, not adjudicated.

### 2. Material — the `_scan` formula makes an empty file one line long

**Plan location:** `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:266-273`.

For an empty file, the specified initial state is `nl = 0`, `last = b""`. The literal formula `total = nl + (0 if last == b"\n" else 1)` therefore returns 1, despite the adjacent parenthetical saying `total = 0`. That breaks `empty_offset1/2` before the later empty branch can work. The existing scanner adds a final range only when bytes remain (`v24/s13/plugins/fs_read.py:157-167`), and the normative rule is empty file = 0 lines (`docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:817-820`).

**Correction:** use:

```text
total = 0 if bytes_seen == 0 else nl + (0 if last == b"\n" else 1)
```

Equivalently, `total = nl + (1 if bytes_seen > 0 and last != b"\n" else 0)`. Update `last` only for nonempty chunks, and use a name such as `bytes_seen` rather than overloading `pos` as both the byte count and the LF-position notation in step 5.

With that guard made explicit, a focused differential reproduced all 15 frozen cases not rejected by the initial size precheck; the oversize case remained a precheck. This includes `empty_offset1/2`, `empty_line`, `cr_preserved`, `truncated_bytes`, and `cursor` (`v24/s13/vectors/tool_contracts.json:113-147,169-188,251-270,358-401`).

### 3. Material — R19 lost the required simultaneous line/byte binding and now repeats frozen semantics

**Plan location:** `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:114,317-320,366-368`.

R19 uses `three` with `limit=2`, yielding `k=2, truncated_by="lines"`. That exercises the same reason as frozen `truncated_lines` (`v24/s13/vectors/tool_contracts.json:337-356`), not the stated “lines/bytes 同时绑定” edge. The export's partial lane had the discriminating fixture: `nine5` with `limit=4` (`prompt-exports/oracle-plan-2026-10-31-133506-deep-plan-w5-python-6010.md:585,627-628`); complete lane 2 also calls for large-file limit contrasts (`:927`).

**Correction:** make R19 `nine5, limit=4`, expecting `k=4, truncated_by="lines"`; keep R20 as `nine5, limit=5`, expecting `k=4, truncated_by="bytes"`. At R19 the line limit selects four lines, while the byte budget also rejects the fifth; `k == limit` still assigns `"lines"` (`v24/s13/w1_reference.py:295-311`). R20 removes the line-limit binding and isolates the byte-bound control. Probe counts do not change.

### 4. Material — the prescribed old-code red baseline calls APIs that do not exist yet

**Plan location:** `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:380-384,475-479`.

W5-1 requires R21–R29 against the old plugin, but R22 injects through new `_caps()`, R23 calls new measurement helpers, and R29 wraps new `_scan()`. None exists in the baseline (`v24/s13/plugins/fs_read.py:170-189,206-265`). R28 is a positive control for an already-working digest mechanism (`v24/host/registry.py:57-83`), not an expected-red probe. Requiring the fresh log to contain exactly `6.742 s` and `123.9 MiB` also contradicts the plan's correct rejection of wall-clock gates.

**Correction:** define the baseline per probe instead of requiring every probe to be red:

- R21/R24/R25/R26/R27 can run against old behavior through existing interfaces.
- For R22, call old `_read_page()` with patched module caps and record that it returns the empty value without budget checks.
- For R23, compare old `27 + _escaped_len(text)` with the footer-inclusive reference directly; do not call `page_measures` before it exists.
- R29 is a post-implementation green-only probe because there is no old `_scan` to wrap.
- R28 and its tamper negative control should already be green.
- Record fresh measured time/memory. Treat `6.742 s` and `123.9 MiB` as prior observations, not required reproduction values. A focused rerun here measured 6.590 s directly and still reproduced the 5 s host timeout.

### 5. Material — R26's callback is not placed around the helper's success-only unboxing

**Plan location:** `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:328-330,373-374`.

The plan adds `result_check` to capture `usage.wall_ms` and to prove both the old timeout and new success. The existing helper unconditionally evaluates `payload["tool_result"]["output"]["value"]` immediately after finding the dispatch (`v24/s13/test_tools.py:240-265`). An old unknown timeout has only an error output, so the helper raises `KeyError` before it can return or perform a callback added near the existing return.

**Correction:** invoke `result_check(tool_result)` immediately after obtaining `payload["tool_result"]`, before reading `output["value"]`. For the callback-enabled non-`ok` path, return after the callback instead of executing `check_value`/`value_check`; keep the existing success return and all existing call sites unchanged. The red callback can then assert an error-only unknown `timeout` envelope and capture `usage.wall_ms`, while the green callback asserts `status == "ok"`.

### 6. Material — the candidate-only audit fails on known unrelated files and runs before the final candidate exists

**Plan location:** `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:444-457,475-482,540-544`.

The union of all tracked differences and **all** untracked files must be a candidate subset. The current checkout already contains the unrelated untracked files that the plan itself later excludes from publication (`.ctx-export-*`, `.token-probe*`, `ctx_export_check*`, the M3 investigation, and `v20/experiments/ce_native_d5/**`). Thus the audit as written deterministically STOPs even with a perfect W5 change set.

In addition, W5-5 performs the audits before W5-6 creates/modifies the README, matrix, ledger, plan Result, and new execution record. The final candidate is therefore not audited. `git diff --name-only` plus untracked enumeration does cover the new execution record, but only if run after that record is created.

**Correction:** snapshot untracked paths at W5-0 and audit the W5 delta, or explicitly classify the known preexisting paths; do not delete or hide unrelated work. Re-run all seven scope audits after W5-6 and before staging in W5-7. Keep `5771ce3` as the W5 candidate base. The six inherited audits should remain pinned to `c8c4bd0`: it is still an ancestor of HEAD, the executable audit uses that pin (`v24/s13/test_wiring.py:779-873`), and W4c used the same boundary (`docs/reviews/v24-tool-plugin-abi-w4c-execution-2026-10-31.md:54-67`).

### 7. Nit — the plan weakens lane 2's file signature by dropping `st_ctime_ns`

**Plan location:** `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:140-146,505-515`.

Complete lane 2 includes `st_ctime_ns` in every comparison (`prompt-exports/oracle-plan-2026-10-31-133506-deep-plan-w5-python-6010.md:833-837`); the plan retains only dev/inode/size/mtime and consequently accepts a weaker same-size/same-mtime blind spot.

**Correction:** include `st_ctime_ns` in all three comparisons and add an R29 subcase that rewrites without changing size and restores mtime. Update the ledger limitation accordingly; this remains best-effort, not an atomic snapshot or adversarial-workspace guarantee. macOS exposes all five fields in the focused probe.

### 8. Nit — R23 needs explicit bytes/string adaptation and oracle call shapes

**Plan location:** `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:253-264,369-370,380-383`.

The new `escaped_bytes_len` accepts `bytes`, but `w1_reference.escaped_payload_bytes` accepts `str` (`v24/s13/w1_reference.py:188-190`). Passing the same sample object to both will fail rather than differential-test the formula.

**Correction:** compare `escaped_bytes_len(raw)` with `escaped_payload_bytes(raw.decode("utf-8", "strict"))`. For page comparisons, construct each finalized `V_k`, call `content, meta = w1_reference.render("read", V_k)`, then compare only value/content/meta/frame from `w1_reference.budget_measures(args, V_k, content, meta)` and `tool_results.measure(args, V_k, content, meta)`; both oracles also return an args measurement (`v24/s13/w1_reference.py:228-231`, `v24/host/tool_results.py:252-268`).

### 9. Nit — `test_registry.py` pins a different pending case

**Plan location:** `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:558-565`.

The artifact-digest ruling cites `test_registry.py:233` as though it directly pinned `manifest.artifact_digest_pending`. That assertion belongs to the five-field-key case: the surrounding code constructs `pending_case` from the five-field manifest identity and checks its fields (`v24/s13/test_registry.py:221-234`).

**Correction:** state that `test_registry.py:233` pins `manifest.five_field_key.status`, not the artifact-digest case. The artifact case remains frozen through the vector rules and its own bytes/status; no promotion is implied.

### 10. Nit — Done-when marker rule contradicts command 32

**Plan location:** `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:42,440-442`.

Done when #7 requires a command-specific `[passed]` last line for all 32 commands, but the gate section correctly requires command 32 to have empty output.

**Correction:** require markers for commands 1–31 and exit 0 plus empty output for command 32.

## Spot-checks that support the plan; retain these details

- **Deadline chain:** confirmed. Invoke selects the approved tool's timeout (`v24/host/line_json.py:250-264`), `run_process` computes the deadline, kills the process group, and reaps (`v24/host/process_io.py:89-98,129-139,167-181`), and `line_json` maps it to unknown `timeout` (`v24/host/line_json.py:267-298`). On the specified 1,047,999-byte input, a fresh focused call took 6.590 s in `read_tool`; the real `line_json` path returned `class_name="unknown"`, `reason="timeout"`, `wall_ms=5012`. The exact historical 6.742 s is not portable, but the breach and enforcement chain are real.
- **Escape and four-domain formulas:** `E_line`, `E_text`, footer-inclusive `27 + E(T)`, empty-text skeletons, meta = 2, and frame + LF agree with `w1_reference` (`v24/s13/w1_reference.py:153-158,188-231`) and host measurement (`v24/host/tool_results.py:243-268`). Focused checks matched all nine escape samples, the 86-byte truncated example, 39-byte `[empty file]` content, and all 10 successful frozen read values across value/content/meta/frame.
- **Window boundaries:** after correction #2, the LF-ordinal interval and bounds construction reproduce the frozen trailing-LF, empty-line, CR, truncation, and cursor behavior. The requested interval includes the prior LF/sentinel and each selected line's ending LF; an unterminated final line uses EOF. No additional off-by-one correction is needed.
- **Plugin `output_too_large`:** it survives as a known failure. Exit-3 classification validates only the error envelope (`v24/host/line_json.py:240-247`), returns `known_error`/`failure` (`:292-298`), and the dispatcher forwards the code (`v24/host/plugins.py:184-189`). Host error validation checks syntax/message safety, not membership in read's 14-code list (`v24/host/tool_results.py:141-157`). No host code validates plugin codes against that vector list; the plan's D6 pass-through statement is correct.
- **Probe arithmetic:** current 74 = 16 read + 7 list + 24 search + 15 path differential + 5 macOS shim guards + 4 selector + 3 harness (`v24/s13/test_tools.py:63-95,270-286,289-362`). Adding one counted unit per R01–R29 gives macOS 103 and Linux 98, while `read=16` remains the frozen count. No probe repeats `path_differential` verbatim: R10 is absolute-outside and R11 is an intermediate symlink. R19 is the semantic duplication corrected in finding #3.
- **macOS/APFS operations:** a focused local open using `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` succeeded on a regular file, a 1 MiB `pread` returned all 1,048,576 bytes, a final symlink failed with `ELOOP`, and dev/ino/size/mtime_ns/ctime_ns were available. Short reads are already fail-closed as `io_error`; no platform correction is needed beyond restoring ctime in finding #7.

No full W5 gate was run. Verification here consisted of source inspection and focused, temporary-file/local-process differentials only; no production or frozen-vector files were changed.

## Resolution (2026-10-31)

All ten findings were applied to the plan. The blocker is resolved by a **separate adjudication round**, not by the plan-generation export: after the draft was integrated, an `ask_oracle` pass (both lanes complete) ruled A on all six material decisions, including plugin-emitted `output_too_large` with a ledger entry and no design change/repin. The plan now records the generation round (lane 1 partial; lane 2 recommending Appendix C.18), the adjudication round, and the evidence that overturned C.18 (host passes the code through; the branch is unreachable under built-in caps).

Applied corrections: empty-file `total_lines` guard; R19 changed to `nine5, limit=4` to isolate simultaneous line/byte binding; per-probe red-baseline definition; `result_check` callback placed before the helper's success unboxing; candidate-only audit via a W5-0 untracked snapshot plus a post-documentation re-run; `st_ctime_ns` restored with a same-size/restore-mtime subcase; R23 bytes→str adaptation and both-oracle four-domain comparison; `test_registry.py:233` clarified as pinning `manifest.five_field_key`; command 32 marker rule separated from commands 1–31. No production, plan-baseline, or frozen-vector file was changed by this review.

### Implementation and closeout follow-through (2026-10-31)

The findings above remain the original review of the earlier draft. The existing resolution is retained; the table below maps it to the implemented outcome and the W5-5 serial evidence, without reopening D1–D14 or O1–O6.

| Finding | Resolution and implementation outcome |
|---|---|
| 1 | The plan distinguishes generation from the separate six-item adjudication. O1/O6 retain read closeout, plugin `output_too_large` and ledger-only handling; D-ABI-W5-4 records all three conflicting clauses. No design or pin change. |
| 2 | O3/D2 explicitly guard zero bytes; frozen `empty_offset1/2`, the 16-case byte comparison and the final contract/vector gates pass. |
| 3 | R19/R20 use `nine5` with limit=4/5; simultaneous binding selects `lines`, removing that binding selects `bytes`. Both execute in the 29-probe gate. |
| 4 | The per-probe red baseline is preserved: old host `unknown`/`timeout` at 5006 ms, old peak 128043.177 KiB, footer delta 55 B, 2000 growing-text serializations; R28 baseline-green and R29 green-only. Older plan observations remain labelled as earlier measurements. |
| 5 | O4/D3 place the callback before success unboxing. The old timeout is recorded; final R26 reports success at 113 ms (earlier verified W5-4: 92–93 ms) under the unchanged host deadline. |
| 6 | Audit 7 subtracts `baseline-untracked.txt` and pins the tracked delta to `5771ce3`. All seven checks run as precheck and again after documentation before staging; pre-existing unrelated files are excluded from publication. |
| 7 | O3/D2/D11 retain ctime in the five-field signature; R29 append and same-size/restore-mtime subcases pass. The ledger states best-effort detection rather than an atomic snapshot. |
| 8 | O2/D5/R23 use strict bytes→str adaptation, finalized candidates and both oracles' four domains; R23/R24/R27 pass. |
| 9 | O5/D1 preserve both manifest cases' own bytes/status/expected. R28 adds three-way digest equality and one-byte tamper rejection; no vector promotion. |
| 10 | The actual sweep requires exact `[passed]` last lines for commands 1–31; command 32 exits 0 with a zero-byte log and an empty TSV last-line field. |

Final sweep: 32/32 exit 0, no `[SKIP]`; marker `cases=103; read=16; read_probes=29`, peak 3959.904 KiB, `permission_probe=real`. The [W5 execution record](v24-tool-plugin-abi-w5-execution-2026-10-31.md) and `/tmp/w5-20261031T063812Z/` contain the measured evidence. M3 timing/cutoff and Linux real remain pending; closeout stays 11/11.
