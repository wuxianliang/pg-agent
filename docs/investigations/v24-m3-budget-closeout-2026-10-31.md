# Investigation: v24 M3 收尾 — 12s 扫描预算与“放宽预算”的可行性

**状态（2026-11-01）：已由 W5、W6 与 design C.18 解决；正文为 W5/W6 之前的历史分析，见文末 Resolution。**

## Summary

M3 is **not complete** under the current frozen contract, and “keep relaxing the budget limits” is **not** a closeout path.

Two independent product gaps remain:

1. **Search:** `fs_tools.js` has no 12s deadline at all, and its early `scopeExhausted` guard is strictly stronger than the §5.6 page-fill rule. A real probe with 10,001 files, exactly two matches and `limit:2` returns `search_scope_too_large`, while the frozen `cutoff_count_full` shape requires the two-hit page. Because a scan that reaches `offset+limit` hits stops on the sentinel before the file cap, `scopeExhausted` always implies `total < offset+limit`; the file-cap path can never return a page. The guard must be replaced by the post-selection rule (`k=m=limit` or `k<m`), not extended.
2. **Read:** a legal 1 MiB / 2,000-line file takes 5.08–5.49s through the real plugin frame, exceeding the 5,000ms read timeout; a 1 MiB all-LF file uses ~137 MiB and one tuple per line. This is a separate W5 read-closure track. The W5 plan's earlier “decode only the prefix” hypothesis (A3) is a **false lead**: the frozen `window_bad_utf8` vectors require decoding the whole requested window, and the code comment says so. Keep that behavior.

The minimal honest closeout is **W5 (read) + W6 (search) + one M3 declaration + M5**, with an append-only Appendix C.18 defining the M3 evidence standard. The only genuine product decision is whether “12s proven” means (a) deterministic cutoff classification through the production path plus a 12s constant and a recorded real-clock observation (recommended), or (b) a hard real-time 12s guarantee. Under (b), M3 stays blocked or needs a different design.

Budget relaxation fails for a simple reason: there is no 12s code to relax, and a larger file cap does not create a classification branch. Raising the host timeout only moves the eventual `unknown/timeout`; raising page budgets breaks frozen descriptor bytes and the §5.6 termination proof; the 64 KiB transport cap is explicitly non-raisable.

## Symptoms
- W4b 声明“M3 实现完成，timing/cutoff pending”（O8=B）；`tool.search_budget_timing_m3_pending` 仍为 `m3_pending`。
- `v24/s13/plugins/fs_tools.js` 的 search 只有 10000 regular-file 上限，没有 12s wall-clock deadline / cutoff 分支。
- 设计 §6.3 要求“扫描预算 12s（低于 15s timeout）”，预算在页未填满前耗尽必须返回 `search_scope_too_large`，而不是 host timeout 的 `unknown`。
- 当前尚不清楚：M3 的剩余工作应实现 deadline、改设计，还是靠放宽预算上限收尾；以及放宽预算是否会破坏已冻结的 v2 ABI/分页/失败语义。

## Questions
1. M3 剩余的准确范围是什么？只差一个 gate，还是差产品行为 + gate + 向量状态 + 文档收口？
2. 12s deadline 应放在插件的哪个位置，如何与 look-ahead sentinel、EOF 优先、offset 扫描、`complete/total/truncated/next_offset` 快照语义交互？
3. 如何让 deadline 可测试而不引入 CI 抖动？注入 clock 是否足够，墙钟 gate 应该断言什么？
4. “继续放宽预算限制”（12s→更大、10000→更大、15s timeout→更大、页预算→更大）能否替代实现？会破坏哪些冻结合同？
5. 如果产品上决定 v1 不做 12s，最小且诚实的收尾路径是什么？需要哪些设计/向量/台账变更，M3/M5 如何声明？

## Background / Prior Research

### Git archaeology (explore, 2026-10-31)

- The 12s contract was frozen in W1 (`b4de9b9`) at design `:871` and `:876`; the same commit created `tool.search_budget_timing_m3_pending` with `status: m3_pending`, `owner: M3-TOOLS`, `first_production_stage: M3`, `input.wall_clock_seconds: 12`, `expected.deterministic_w1_pass: false` (`v24/s13/vectors/tool_contracts.json:4406-4424`). Design `:774` already said the cutoff itself varies at runtime.
- It was never implemented, not implemented-then-reverted: `v24/s13/plugins/fs_tools.js` has exactly one commit (`80dc0c4`) and zero `Date.now`/`performance.now`/`hrtime`/`deadline`/`cutoff` matches in any revision.
- W4 formalized the deferral in `c92e2cc`: plan D10 (`docs/plans/v24-tool-plugin-abi-w4-dispatcher-worker-wiring-2026-10-31.md:316-321`) says 12s is plugin-internal and W4 adds no wall-clock gate; a `sleep(12)` test is a rejection criterion (`:56`, `:782`). O8 chose B (2/3): "M3 implementation complete, timing/cutoff pending" (`:830`, `:860-888`). The virtual-clock option C was rejected as still not proving wall-clock 12s.
- `80dc0c4` (W4b) shipped only the 10000-file cap (`fs_tools.js:523`); `test_tools.py:364-369` asserts the deferral (`timing.status == "m3_pending"`), so the gate currently ratifies the gap rather than closing it.
- No commit has ever added or removed timing code in `fs_tools.js`. The gap is a postponed product requirement, not a regression.

### Prior decisions on caps (explore, 2026-10-31)

- **64 KiB stdout is explicitly not raisable**: design `:767` and risk #3 at `:1040` ("禁止抬高 transport 上限"); W4b plan `:778` repeats it. `60001..65536` is transport-valid but over the built-in 60000 target; `>65536` is `stdout_limit` unknown (`:769`, frozen `results_v2.json:1916-1921`).
- **Page budgets 40960 value / 41984 content / 4096 meta / 16384 args** are frozen both in pinned design spans and in the three descriptor byte digests (e.g. `descriptor_v2.json` read/list/search `expected_length`/`expected_sha256`). Changing them changes the approved artifact identity and the §5.6 termination proof (`:782`).
- **10000 files / 200 hits / 10000 list entries / 5000-15000 ms** are frozen in §6.3 and in `tool_contracts.json` (`file_limit`, `hit_limit`, timeout rows). Search timeout `>25000 ms` is rejected by descriptor limits; `>25000` also requires a claim-before-lease design (design `:430`, risk #7 `:1044`).
- **No re-bless channel**: design `:92`, `:1283`; vectors `README.md:5`; plans `:121`, `:354-356` (D13). Design edits must be append-only Appendix C (D14); a pinned span SHA change is STOP-producing.
- Consequence: raising a cap is a contract revision, not a tuning change. Even then, the frozen vectors remain stale and would conflict.

### Preliminary assessment from `context_builder` (unverified; two Oracle lanes)

The initial assessment says:
1. M3 is not complete under the current contract; the 12s cutoff is absent and the current `scopeExhausted` guard may also reject frozen count-full/byte-full cutoff shapes.
2. "Keep relaxing budgets" is not a closeout path: it cannot make a slow scan return `search_scope_too_large`; it just moves the host `unknown/timeout` boundary later, and changing caps breaks pinned spans, descriptor bytes, lease math, and the §5.6 termination proof.
3. Remaining M3 includes read memory/perf (whole-file materialization, per-line tuples), exact content-footer accounting, empty-page budget checks, safe-integer comparisons, and a slashless-glob mismatch.
4. The 12s evidence decision is blocked on what "proven" means: deterministic cutoff classification + production 12s configuration, vs. real elapsed-time evidence. Deterministic clock injection can prove the branch; it cannot prove the wall-clock magnitude.
5. It claims the W5 plan "rules the window decode as vector authority" and A3 is not an M3 item. **This conflicts with the W5 plan text read at 13:09**, which calls the window decode too wide and proposes fixing it. The current `fs_read.py:206-211` comment says the window decode is intentional, and `window_bad_utf8` (`tool_contracts.json:193-200`) expects `not_utf8`. This contradiction must be resolved by the pair: preserve window semantics, correct the W5 plan, and treat A3 as a false lead.

### Key code anchors

- `v24/s13/plugins/fs_tools.js:478-480` sentinel; `:505-525` DFS + 10000 cap; `:535-635` freeze/guard/page enumeration; `:523` `scopeExhausted`; `:575-578` guard `scopeExhausted && total < offset + limit`.
- `v24/s13/plugins/fs_read.py:128-148` whole-file read; `:157-168` per-line ranges; `:206-254` window decode + budget loop; `:226` content `27 + escaped_len(text)`.
- `v24/host/tool_pages.py` host page relations; `v24/host/line_json.py` `_spec_v2` timeout; `v24/host/plugins.py` lease precheck; `v24/host/process_io.py` 64 KiB.
- `v24/s13/vectors/results_v2.json:960-1159` `cutoff_count_full`, `cutoff_before_fill`, `cutoff_before_offset`.
- `v24/s13/w1_reference.{js,py}` frozen page-decision predicate; `v24/s13/capture_vectors.py:280-300` emits cutoff probes with `scan_end='cutoff'`, i.e. W1 already models cutoff without a clock.
- `v24/s13/vectors/manifest_adapter_v2.json:40-75,600-620` artifact digest rows still `m3_pending`.
- Untracked `docs/plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md` (read-side closure). It was expanded concurrently during this investigation (42 lines at 13:09 → 588 lines at 13:45) and now records the window-decode tension as D7 with the same verdict as this report: keep the frozen-window semantics, do not adopt A3. It explicitly scopes itself to `read` and says it is **not** M3 completion; search 12s remains pending.

## Investigator Findings

### 1. M3 scope and the cutoff guard

**Confirmed — M3 is still open.** W4b/W4c records explicitly say “M3 implementation is complete, but timing/cutoff is pending”; the timing vector remains `m3_pending` and no 12-second wall-clock gate exists ([matrix](../reviews/v24-conformance-matrix-2026-10-23.md:700), [README](../../v24/s13/README.md:87-90), [vectors README](../../v24/s13/vectors/README.md:9-11)). The remaining product behavior is the plugin-internal 12-second search budget, stop-reason/cutoff page decision, and evidence/gate/document closeout. It is not honestly closable by merely raising limits.

**Confirmed — the cutoff guard rejects the frozen count-full shape.** In `searchWalk`, the 10,001st regular file sets `scopeExhausted` and returns before processing that file ([fs_tools.js](../../v24/s13/plugins/fs_tools.js:505-525)). After the walk, the code computes `total = state.hits.length` and throws when `scopeExhausted && total < offset + limit` ([fs_tools.js](../../v24/s13/plugins/fs_tools.js:571-578)). I created a real tree under `/tmp` with 10,001 regular files, exactly two matching files, and invoked Node `search` with `limit:2`; the process exited 3 with `{"code":"search_scope_too_large"}`. This is exactly the frozen `cutoff_count_full` candidate shape (`complete:false`, `total:2`, `scanned_files:10000`, two hits) whose expected result is selected page k=2 ([results_v2.json](../../v24/s13/vectors/results_v2.json:977-1060)). The guard tests `total < offset+limit` (2 < 3), so it rejects even though k=m=limit is count-full.

**Confirmed — current file-cap code cannot return any cutoff page.** The only stop states are hit-count (`state.stopped`) and file cap (`state.scopeExhausted`); there is no clock/deadline state ([fs_tools.js](../../v24/s13/plugins/fs_tools.js:562-574)). Whenever `scopeExhausted` is set, `total < offset+limit`, because a scan that reached `offset+limit` hits would have set the sentinel and returned before the next file. The early guard therefore throws on *every* file-cap cutoff; the file-cap path can never return a count-full or byte-full page. The one-hit `cutoff_before_fill` shape happens to produce the expected `search_scope_too_large` text, but only by short-circuiting before the §5.6 page decision, not by deciding that the page is unfilled. **Needs-more-evidence — byte-full file-cap reproduction:** a separate real tree with enough large hit/context projections to make k<m while a following candidate exists was not completed in this time box; the same guard condition would reject whenever the observed total is below `offset+limit`. The frozen `cutoff_before_fill` and `cutoff_before_offset` are reference-model cutoff cases, not evidence that the current plugin emits them ([results_v2.json](../../v24/s13/vectors/results_v2.json:1075-1137); [w1_reference.js](../../v24/s13/w1_reference.js:207-213)).

**Correction (agent, after Oracle review):** the sentinel *is* correctly included in `state.hits` and `total`; design §5.6 says `total` counts every observed hit including the sentinel, while the returned page is `hits.slice(offset-1, offset-1+limit)` and excludes it ([design](../../docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:773)). `incomplete_nonempty` (two matching lines, `limit:1` → one hit, `total:2`, `next_offset:2`) is the proof that this is the intended behavior. The pair's “incorrectly included” sentence above is rejected; only the early `scopeExhausted` guard is wrong.

### 2. Deadline semantics and minimum implementation

**Confirmed — the design’s post-selection rule is precise.** Freeze only complete observed hits/statistics at EOF, a look-ahead sentinel, file-cap, or time-cap ([design](../../docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:771-778)). Enumerate every candidate prefix k and choose the largest prefix satisfying schema, integer safety, value/content/meta/frame budgets. On a scan cutoff before EOF, success is allowed only when the selected page is count-full (`k=m=limit`) or byte-full with evidence of a following complete candidate (`k<m`); otherwise return `search_scope_too_large`. Never return an empty incomplete success. `truncated` is `!complete || offset+k-1<total`; `next_offset` is `offset+k` when truncated, otherwise null ([design](../../docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:775-778,780-784)).

**Recommended implementation (Confirmed design interpretation).** Add an explicit `stopReason` with `eof`, `sentinel`, `file-cap`, and `time-cap`. Check a monotonic clock at complete-item boundaries: after a fully constructed file/hit (including required context) and before beginning the next file. EOF/sentinel wins if reached at that boundary; otherwise set `time-cap` and freeze the completed snapshot. Do not interrupt a file or emit a partially built hit. Replace the generic `state.stopped`/`scopeExhausted` test with the post-selection predicate above. Re-scan from the root for every offset; if a cutoff occurs before the requested offset, return `search_scope_too_large`; if the offset is present, apply the same k decision and snapshot fields. Use BigInt/math comparisons for `offset+limit` and cursor safety; never emit an unsafe `next_offset` or `total` ([design](../../docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:773-776)).

**Needs-more-evidence — wall-clock proof boundary.** A deterministic injected clock can prove branch ordering, stop reason, snapshot fields, and frozen-vector decisions without CI sleeps. It cannot prove that an arbitrary machine reaches the deadline at exactly 12,000 ms. The honest gate is therefore: deterministic injected-clock tests for all four stop reasons and page-fill/error cases, plus a production configuration/code assertion that the deadline is 12 s and host timeout remains 15 s. A wall-clock run may record elapsed evidence and detect gross violations, but should not be a brittle exact-time pass/fail gate.

### 3. Read decode window (W5 A3)

**Eliminated — A3 is a false lead under the frozen authority.** `fs_read.py` intentionally decodes the complete requested window (`offset .. offset+limit-1`) before prefix selection, as documented in its comment ([fs_read.py](../../v24/s13/plugins/fs_read.py:206-211)). This matches §6.2’s “selected window” rule ([design](../../docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:818-824)) and the frozen vectors: `window_bad_utf8` and `window_bad_utf8_offset2` require `not_utf8`; `outside_bad_utf8` succeeds at offset 1 while `outside_bad_utf8_offset2` fails ([tool_contracts.json](../../v24/s13/vectors/tool_contracts.json:191-248)). The W5 plan’s A3 should be removed or rewritten as a documented §5.6/§6.2 wording tension; changing behavior to decode only a shorter candidate prefix would contradict frozen bytes/expected errors. **Needs-more-evidence:** none for the verdict; only a future authorized design revision could change this observable behavior.

### 4. Read memory/performance and accounting

**Confirmed — whole-file/range materialization is a real fixed-cap defect.** `_read_bytes` reads the entire file and `_line_ranges` allocates one tuple per LF ([fs_read.py](../../v24/s13/plugins/fs_read.py:128-168)). In a direct in-process `tracemalloc` probe, a 1 MiB all-LF file (1,048,576 lines, limit 2,000) used 137.075 MiB peak and took 920 ms. A legal 1,047,999-byte, 2,000-line file took 5.08–5.49 s in five direct subprocess runs with the normal plugin frame, so it can exceed the descriptor’s 5,000 ms timeout ([design](../../docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:806-824); [W5 hypothesis](../plans/v24-tool-plugin-abi-w5-python-read-2026-10-31.md:20-30)). Severity is high for the fixed caps: this can become host `unknown/timeout`, and the all-LF case violates the design’s “do not read the whole file into memory” intent. The W5 plan’s target of bounded/O(limit) line metadata is technically justified, but remains unimplemented and unverified here.

**Confirmed — footer accounting is incomplete for truncated read pages.** `content_len = 27 + _escaped_len(text)` omits the renderer’s continuation footer ([fs_read.py](../../v24/s13/plugins/fs_read.py:226-250); [renderers.py](../../v24/host/renderers.py:39-53)). The renderer appends the footer whenever `truncated`; the 27-byte constant covers the content-array wrapper, not that footer. Under current caps value is normally tighter, so this is a latent selection defect; it is still non-conformant to §5.3.1 and can change prefix selection under a content-bound case. **Confirmed — empty-file checks are skipped structurally:** the `total==0` branch returns `_empty_value` before any four-budget check ([fs_read.py](../../v24/s13/plugins/fs_read.py:192-212)). Under fixed path/cap limits the empty value is far below all caps, so no observable failure was produced; severity is low today but the branch violates §5.6 step 6 and must be covered if caps are injected in a test.

### 5. Other M3-relevant gaps

**Confirmed — slashless glob mismatch.** Design §6.3 requires a glob without `/` to match the basename ([design](../../docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:865-870)). The implementation constructs `^[^/]*$` and tests it against `relPath` ([fs_tools.js](../../v24/s13/plugins/fs_tools.js:360-390,442)). A real `/tmp` tree containing `root.txt` and `sub/nested.txt`, queried with `glob:"*.txt"`, returned only `root.txt`; the nested basename was excluded. This is an M3 semantic defect. **Confirmed — safe-sum risk exists in implementation:** `offset + limit` and `offset + count` are ordinary JavaScript arithmetic ([fs_tools.js](../../v24/s13/plugins/fs_tools.js:461-468,575-578,611-635)); the host separately requires safe integers ([tool_pages.py](../../v24/host/tool_pages.py:44-99,184-216), but direct plugin arithmetic can round at the boundary. The minimum fix is BigInt comparisons and an explicit safe-cursor check before constructing output.**

### 6. Budget relaxation is not a closeout path

**Confirmed — every listed cap is frozen contract surface.** The 12 s scan budget and 15 s search timeout are pinned in design §6.3/descriptor data; 10,000 regular files and 200 hits are part of search semantics, vectors, and the termination proof; value/content/meta caps (40,960/41,984/4,096) are in pinned descriptor bytes and §5.6; the 64 KiB transport ceiling is explicitly non-raisable ([design](../../docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md:765-782,852-878,1039-1045); [descriptor.py](../../v24/host/descriptor.py:45-59)). Raising any of these changes vector bytes/expected shapes, descriptor/artifact digests, lease/timeout math, or the page termination/continuation proof. Raising the scan budget also cannot make an actually slow scan return `search_scope_too_large`; it merely moves the host timeout/unknown boundary. The 64 KiB cap has no legitimate relaxation under the current design. **Confirmed conclusion:** no relaxation is a valid closeout path. A cap change is possible only after an explicit product/design revision, append-only design decision, updated descriptor/vector authority and digests, revised lease math, and new gates; frozen vectors must not be re-blessed implicitly.

### 7. Minimal honest closeout sequence

**Confirmed sequence:**

1. Fix Node search stop reasons/deadline, post-selection count-full/byte-full predicate, slashless basename matching, and safe-integer arithmetic; fix read bounded scanning/materialization and footer/empty-page accounting as separate read work.
2. Add deterministic injected-clock gates at complete-item boundaries for EOF/sentinel/file-cap/time-cap, offset re-scan, no-empty-incomplete, and all frozen cutoff decisions. Keep production deadline 12 s and descriptor timeout 15 s; record (but do not exact-gate) real wall-clock observations.
3. Run the full relevant M3 gates; frozen vectors retain their current statuses and bytes. D13/no-re-bless remains in force ([vectors README](../../v24/s13/vectors/README.md:5-11)).
4. Capture source/artifact SHA-256 and execution logs; reconcile the timing vector as evidence without changing `expected`/`status` unless a separately authorized design revision changes the vector contract.
5. Update the stage README, conformance matrix, deviation ledger, and execution record so they say exactly what was proven; distinguish design Appendix C evidence from the §5.6 body contract.
6. Run the M5 regression suite and only then perform the repository-required path-specific commit/push sequence.

**Needs-product/design decision:** whether the product still requires the frozen 12-second behavior. If yes, implement and gate it as above. If no, the only honest alternative is an explicit design revision that removes/changes the 12-second contract and updates all pinned authority; silently relaxing limits or declaring W4b complete is not a closeout.


## Investigation Log

### Phase 1 — Triage and baseline

- Confirmed `HEAD == origin/main == 5771ce3`; tracked tree clean except untracked probe files.
- Re-ran six s13 gates (`test_registry`, `test_pages`, `test_wiring`, `test_tools`, `test_lifecycle`, `test_node`); all exit 0. The green `test_tools` is not evidence of cutoff correctness: it asserts `timing.status == "m3_pending"` and contains no count-full/byte-full cutoff case.
- Formed the hypothesis that the 12s budget was deferred, not merely untested.

### Phase 1.5 — Git archaeology and prior decisions (explore agents)

- 12s was frozen in W1 (`b4de9b9`), never implemented, never reverted; `fs_tools.js` has one commit and no clock identifier.
- W4 formalized D10/O8=B: no `sleep(12)` gate; virtual clock rejected as not proving wall-clock; M3 left “implementation complete, timing/cutoff pending.”
- All caps are pinned in design spans, frozen vector bytes, descriptor digests, or lease math; no re-bless channel. The 64 KiB transport cap is explicitly non-raisable.

### Phase 2 — Context builder and initial Oracle assessment

- `context_builder` selected the design/vector/host/plugin surfaces and produced two initial lanes. They flagged the guard, read materialization, footer/empty budgets, glob, and safe-integer issues.
- One lane wrongly claimed the W5 plan chose the frozen window as authority and that A3 was not an M3 item. The plan text at that time said the opposite. This became a hypothesis to resolve, not a finding.

### Phase 3 — Pair investigator probes

- **Guard bug reproduced:** 10,001 regular files, exactly two matching files, `limit:2` → real Node plugin returns `search_scope_too_large`; frozen `cutoff_count_full` expects the two-hit page.
- **Stronger structural finding:** a scan that reaches `offset+limit` hits stops on the sentinel before the next file, so `scopeExhausted` always implies `total < offset+limit`. The early guard therefore rejects *every* file-cap cutoff, not just an edge case.
- **Deadline semantics:** add `stopReason` (`eof`/`sentinel`/`file-cap`/`time-cap`), check only at complete-item boundaries, sentinel/EOF win at the same boundary, and apply the post-selection rule.
- **A3 eliminated:** `fs_read.py:206-211` intentionally decodes the requested window; `window_bad_utf8` and `window_bad_utf8_offset2` require `not_utf8`; `outside_bad_utf8` succeeds at offset 1. Changing to prefix-only decode would break frozen expected bytes.
- **Read perf confirmed:** 1,047,999-byte / 2,000-line legal file took 5.08–5.49s through the real plugin frame, over the 5,000ms deadline; 1 MiB all-LF used ~137 MiB.
- **Glob/safe-integer confirmed:** slashless `*.txt` misses nested basenames; search arithmetic uses plain JS numbers at the safe-integer boundary.
- **Byte-full file-cap reproduction** was left `Needs-more-evidence`; the structural guard argument covers it, but no independent real-tree probe was completed.

### Phase 4 — Oracle synthesis (2 lanes, both completed)

Both lanes agreed on:
- M3 is not complete; the guard is a bug fix under the existing contract, not a design change.
- No budget relaxation closes M3.
- Use a two-tier evidence standard: deterministic production-path gate + 12s/15s constant assertions + recorded real-clock observation, not a CI `sleep(12)`.
- Sequence W5 read, W6 search, one M3 declaration, then M5.
- `deterministic_w1_pass:false` describes W1's inability to prove elapsed time; it does not mandate a real 12s gate. M4's `m4_pending` precedent shows “executed, status retained” is how this project declares completion.
- The pair's sentinel claim is wrong: `total` includes the sentinel by design; the page slice excludes it.

One lane added a useful correction: it had earlier suggested extending the early guard to a time cutoff; after the probe it agreed the guard can never be extended, because any cutoff (file or time) that has not reached the sentinel necessarily has `total < offset+limit`. The post-selection rule is mandatory.

### Phase 5 — Agent verification and corrections

- Independently reproduced the 10,001-file / 2-hit / `limit:2` failure.
- Benchmarked the legal 1 MiB / 2,000-line read at 5.066s in-process; benchmarked 1 MiB all-LF at ~295 MiB max RSS (the pair's `tracemalloc` number is ~137 MiB; both show O(lines) memory).
- Verified `tool_pages._check_search` accepts a count-full cutoff page and does **not** enforce the page-fill rule; the plugin must enforce it because the host cannot know `scan_end`.
- Verified `w1_reference` predicate: allow cutoff iff `selected == len(values) == limit` or `selected < len(values)`.
- Discovered the W5 plan was expanded concurrently from 42 to 588 lines; its new D7 now agrees that the window decode must remain unchanged. Treat the current plan as a separate read-closure track, not as M3 completion.

## Oracle reconciliation

Two lanes completed (`claude-opus-5-5`, `gpt-6.1-sol-xhigh`); neither failed. Material claims and dispositions:

| # | Claim | Source lanes | Check | Disposition |
|---|---|---|---|---|
| 1 | M3 is not complete; 12s is absent | both | code/git/vectors | **accepted** |
| 2 | Early guard rejects count-full; post-selection rule is authoritative | both + pair probe | real 10,001-file probe; `w1_reference` | **accepted** |
| 3 | `scopeExhausted` always implies `total < offset+limit`, so the file-cap path always throws | lane 1 (self-correction) | code trace: sentinel stops before next file | **accepted** |
| 4 | Sentinel is correctly included in `total`, excluded from page slice; pair's “incorrectly included” is wrong | both | design :773; `incomplete_nonempty` | **accepted; pair wording rejected** |
| 5 | A3 is a false lead; keep window decode | both | frozen `window_bad_utf8`; W5 D7 | **accepted** |
| 6 | Legal 1 MiB / 2,000-line read exceeds 5s; memory is O(lines) | pair + agent | real frame 5.08–5.49s; 5.066s in-process; ~137–295 MiB | **accepted** |
| 7 | Footer/empty-page accounting defects | pair | code + renderer | **accepted (low severity under fixed caps)** |
| 8 | Slashless glob misses nested basenames | pair | real probe; design §6.3 | **accepted** |
| 9 | Safe-integer arithmetic risk | pair | code; host fails closed | **accepted** |
| 10 | No budget relaxation closes M3 | both | cap inventory | **accepted** |
| 11 | Two-tier evidence standard (deterministic + constants + observed) | both | C.16/D10; M4 precedent | **accepted; product decision remains** |
| 12 | W5 read → W6 search → M3 declaration → M5 | both | dependencies/audits | **accepted** |
| 13 | C.18 needed for M3 binding/evidence, not for the guard fix | both | design pins/D14 | **accepted** |
| 14 | `deterministic_w1_pass:false` does not mandate a real 12s gate | both | vector semantics; M4 `m4_pending` precedent | **accepted** |
| 15 | Glob-excluded files should/shouldn't count in `scanned_files` | lane 1 | no frozen row; design ambiguous | **unresolved (W6/C.18 decision)** |
| 16 | Byte-full file-cap reproduction | pair | structural proof only | **unresolved (needs probe; low risk)** |
| 17 | Exact real-time 12s guarantee | neither requires | Node sync FS cannot be preempted | **rejected as a claim; not gated** |
| 18 | Extend the early guard to a time cutoff | lane 1 initial, self-corrected | cutoff always `total < offset+limit` | **rejected** |
| 19 | W5 initially chose A3/window as authority | lane 1 initial | W5 text at 13:09 said opposite; current D7 agrees | **rejected; corrected** |

The remaining disagreement is only #15 (a bookkeeping semantics question) and #16 (an unprobed byte-full real-tree case). Neither blocks the root cause or the recommended sequence.

## Root Cause

### 1. Search: the implementation modeled only the file cap, and modeled it as a hard error

W1 froze a deterministic reference page decision with `scan_end='cutoff'` (`w1_reference`, `results_v2`). W4b implemented a real plugin with two stop booleans (`stopped`, `scopeExhausted`) and an early rejection:

```js
if (state.scopeExhausted && total < offset + limit) {
  throw new ToolError("search_scope_too_large", ...);
}
```

This is not the §5.6 rule. The §5.6 rule is post-selection: after enumerating candidate prefixes and choosing the largest fitting `k`, a cutoff page is allowed iff `k=m=limit` (count-full) or `k<m` (a complete following candidate was observed); otherwise it is `search_scope_too_large`. The early guard uses `total < offset+limit`, which is true for every file-cap cutoff because the sentinel would have stopped the scan earlier otherwise. It therefore rejects count-full and byte-full pages unconditionally. The only reason the existing gate is green is that it tests a no-hit file cap (`file_count_cutoff`), where rejecting is the correct outcome.

The 12s deadline is a separate, larger gap: there is no clock read in the file. C.16/D10 deferred the wall-clock gate, but C.11 bound W4b to “timing/cutoff pending,” so M3 cannot be declared complete until a later stage implements the behavior and records the evidence standard.

### 2. Read: legal worst-case input exceeds the tool deadline

`fs_read.py` reads the whole file (`:128-148`), allocates one tuple per line (`:157-168`), and re-serializes every candidate prefix (`:206-254`). For a legal 1 MiB / 2,000-line file this is O(n²) serialization work and takes ~5.1s, over the 5,000ms read timeout; for 1 MiB all-LF it allocates ~137–295 MiB. The fix is a bounded two-pass scan, not a decode-window change. The earlier A3 hypothesis was a false lead: the frozen `window_bad_utf8` vectors require decoding the whole requested window.

The footer accounting (`27 + escaped_len(text)`) and the empty-file early return are real but low-severity exactness defects under current caps; they should be fixed while the read path is being rewritten, not used to justify a cap change.

### 3. Evidence: the gate ratifies the gap instead of closing it

`test_tools.py:364-369` asserts `timing.status == "m3_pending"` and the frozen vectors keep `m3_pending`; no test drives a count-full/byte-full cutoff through the real plugin. `manifest_adapter_v2` artifact digest rows still say `"M3-pending"`. D13 forbids re-blessing, so the closeout must record executed evidence without promoting status, and C.18 must define what M3 completion means.

### 4. “Relax the budget” does not address the defect

There is no 12s code to relax. Raising the number changes nothing; raising the host timeout moves the `unknown/timeout` boundary; raising the file/hit/page caps changes frozen vectors and the §5.6 termination proof; raising 64 KiB is forbidden. A slow scan still cannot return the required `search_scope_too_large`. The only honest alternative to implementing the cutoff is an explicit design scope reduction (C.18), and even then the file-cap guard bug remains.

## Recommendations

### Decision needed first (product/design)

Choose one:

| Option | Meaning | Consequence |
|---|---|---|
| **A (recommended)** | Two-tier evidence: deterministic injected-clock gate through the production path + 12s/15s constant assertions + recorded real-clock observation | M3 can close after W5/W6 with a precise claim boundary; no brittle `sleep(12)` gate |
| **B** | Hard real-time 12s guarantee in CI | M3 stays blocked; Node synchronous filesystem calls cannot be preempted mid-call; a real-time gate is slow/flaky and still cannot prove arbitrary filesystems |
| **C** | Remove the 12s requirement for v1 | Explicit design scope reduction in C.18; no false “M3 complete”; the file-cap guard bug still must be fixed |

Do not choose “raise the budget.” It is not on the table.

### W5 — read closure (separate commit)

Execute the current 588-line W5 plan (or an equivalent reviewed plan). Key requirements:

- Replace `_read_bytes` / `_line_ranges` with a bounded two-pass scan: 64 KiB chunks to count LFs and record only the requested window's LF offsets; one `pread` for the window; memory O(`limit`) plus fixed buffers.
- Keep the requested-window decode semantics; do not adopt A3. Update the W5 plan/ledger to record the §5.6:773 vs §6.2:824 wording tension as a documented interpretation.
- Compute content/footer and empty-page measurements exactly; run all four budgets on the empty page; preserve the frozen 16 read cases.
- Prove the legal 1 MiB / 2,000-line file returns inside the 5,000ms host deadline; record `wall_ms`; keep a deterministic in-process memory check (e.g. `tracemalloc` < 8 MiB) out of the wall-clock gate.
- Record the final `fs_read.py` SHA-256; leave `manifest.artifact_digest_pending` status/expected unchanged.

### W6 — search closure (separate commit, then M3 declaration)

1. **Stop state:** replace the two booleans with `stopReason ∈ {eof, sentinel, file-cap, time-cap}`; `complete = stopReason === 'eof'`.
2. **Deadline:** monotonic `process.hrtime.bigint()` (or `performance.now()`); `SCAN_BUDGET_MS = 12000`; start at `searchTool` entry; check at complete-item boundaries:
   - before beginning each directory entry;
   - before starting file inspection;
   - after a hit and its context are fully built, after the sentinel check;
   - after the walk, before freezing the snapshot.
   Do not interrupt a hit or emit partial context. Sentinel wins over time at the same boundary; EOF wins when the last item completes.
3. **Page decision:** remove the early `scopeExhausted` guard. Apply §5.6 order:
   - source errors;
   - cutoff with `m=0` → `search_scope_too_large` (before the empty-success branch);
   - no fitting prefix → `hit_too_large`;
   - cutoff with `best != null` and not (`k=m=limit` or `k<m`) → `search_scope_too_large`;
   - success.
4. **Glob:** if the pattern has no `/`, match against the basename; keep the existing regex builder for patterns with `/`. This is a bug fix; no frozen glob row uses a slashless nested case.
5. **Safe integers:** use BigInt for `offset+limit`, cursor arithmetic and sentinel comparisons; never emit an unsafe cursor/total.
6. **Test seam:** export `searchTool(args, root, {now, budgetMs})`; production `invoke` uses defaults; no env/argv knob. C.18 should explicitly accept this parameter seam (C.17 §4 was about the non-UTF-8 fixture).
7. **Gate:** add deterministic production-path cases for:
   - count-full file cap (10,001 files, 2 hits, limit 2) → success page, `total=2`, `next_offset=3`;
   - count-full time cap (2 hits, limit 2, clock expires before EOF) → success page;
   - byte-full cutoff (`k<m`) → success with `k<m`;
   - before-fill (`m<limit`, `k=m`) → `search_scope_too_large`;
   - before-offset (offset 5, fewer than 5 hits) → `search_scope_too_large`;
   - empty cutoff → `search_scope_too_large`, never `complete:true,total:0`;
   - no fitting prefix → `hit_too_large`;
   - EOF priority and sentinel priority.
   Keep the existing `incomplete_nonempty` behavior; `total` includes the sentinel, the page slice excludes it.
8. **Constants:** assert `SCAN_BUDGET_MS == 12000`, search descriptor timeout `15000`, and `12000 < 15000` with margin.
9. **Real-clock observation:** run once with a small injected budget (e.g. 50ms) on a large tree; assert only that the outcome is an allowed incomplete page or `search_scope_too_large`; record elapsed overshoot. Do not exact-gate 12s.

### M3 declaration and M5

- Append **C.18** (design is append-only under D14): bind W6 → M3, define the three evidence tiers, state that `deterministic_w1_pass:false` is a W1 limitation not a real-12s mandate, accept the clock parameter seam, and record the page-fill decision authority. Repin the whole-document SHA and `design_conformance.json` atomically; all pinned spans must keep their line ranges/headings/content SHA.
- Add ledger rows for: the W4b over-claim (“cutoff errors” while the file-cap page path was unconditional), the search guard fix, the read performance/accounting fix, the glob fix, the safe-integer audit, and the Linux limitation.
- Update `v24/s13/README.md`, conformance matrix, W5/W6 execution records, and final M3 declaration. Keep frozen vector `status`/`expected` unchanged (D13); record actual artifact hashes and executed pending cases separately.
- If Linux real non-UTF-8 evidence is part of the completion claim, run it; otherwise keep `linux_real=not_run` explicit and do not imply coverage.
- Run the full M5 sweep (W5's 32 commands + W6 additions), `git diff --exit-code -- v24/sql`, closeout **11/11**, then path-specific commit/push per AGENTS.md.
- Do not claim exact 12.0s cutoff, identical cutoff points across runs, pagination convergence across a slow scope, or vector promotion.

### What not to do

- Do not raise 12s/15s/10000/200/page/64 KiB and call it closeout.
- Do not add `sleep(12)` to CI.
- Do not change the read decode window to prefix-only; it breaks `window_bad_utf8`.
- Do not promote frozen vector statuses or artifact placeholders without a separately authorized design revision.
- Do not combine W5 and W6 into one commit; keep the read and search evidence attributable.

## Preventive Measures

- Treat stop reason and page-fill decision as one state machine; test all four stop reasons through the production path, including the count-full and byte-full cutoff successes that the current gate misses.
- Add a worst-case legal-input performance probe for `read` (1 MiB, 2,000 lines) and a memory probe for the all-LF case; keep wall-clock assertions out of the pass/fail gate, but fail on structural O(n²)/O(lines) regressions.
- Separate evidence labels in execution records: “deterministic branch proven,” “constant configured,” “real-clock observed.” Never collapse them into “12s proven.”
- Do not write “implementation complete” in a README/matrix when a normative branch is absent; the status must name the branch.
- Any cap change requires a design revision, updated vector authority, descriptor/artifact digest audit, and lease-math audit; never tune a cap to make a gate green.
- Re-read untracked plans before relying on them; the W5 plan changed from 42 to 588 lines during this investigation. Record the version/hash used for decisions.

## Resolution (2026-11-01)

正文保留为 W5/W6 之前的历史分析，行号与代码锚点不作当前权威；下列映射记录实际处置。

- **Finding 1（search）** → W6 的 `D-ABI-W6-9`（`addSafe`/安全整数）、`D-ABI-W6-10`（删除早退守卫、改为 §5.6 后置判定）、`D-ABI-W6-11`（slashless glob 只匹配 basename）、`D-ABI-W6-12`（可选第三参数 seam），以及 `D-ABI-W6-2/3`（三层 timing、C0/C1 检查点）；artifact `efd05d63f028f0da4de333684dc3e63f506302f5a1c52a26c95efe36297348e5`。本轮 row 29 的 S01–S26 全绿，S25 记录 `real_clock_elapsed_ms=50.463`、overshoot `0.463`。
- **Finding 2（read）** → W5 的 `D-ABI-W5-1…5`：单 fd 两遍有界扫描、可加计量、footer 参与 content 预算、空文件四预算、打开加固与变更检测；artifact `260274daba1efa87f4c33103fe53503c76a65187af68e610d5aedcfadad5165c`。本轮 row 29 实测 `read_1m_wall_ms=97`、`read_peak_kib=3959.904`，R26 在未变的 5000 ms host deadline 下为 `success`，不沿用 W5 的 113 ms。
- **对账 #15（glob 排除文件的 `scanned_files` 记法）** → `D-ABI-W6-1` / S17 / C.18.7 承接句：glob 排除的 regular file 仍计 `scanned_files` 并消耗 file 预算。该业务语义问题已裁决，不再记为未决。
- **对账 #16（byte-full file-cap 的真实树复现）** → W6 S02 的 `k<m` 页与 `D-ABI-W6-10`；只作结构/失败次序证明，不等同真实字节满树复现。该限制保留，不写成已复现。
- **对账 #17/#18/#19** → 保留既有否决/纠正结论：#17 精确实时 12s 不作为声明或 gate（同步 FS 不可抢占）；#18 扩展早退守卫的方案被否决，改由后置判定取代；#19 的 A3/window 前缀解码方案被否决，W5 `D7` 维持完整请求窗口解码。
- **Option A** → C.18 采纳为 M3 的证据标准（T1/T2/T3 三层，不得合并）；**Option B**（硬实时 CI gate）与 **Option C**（删除 12 秒合同）仍否决，不因 M3 声明而改变。
- **W5/W6 证据** → 各自 execution record；**M3 声明** → `docs/reviews/v24-tool-plugin-abi-m3-declaration-execution-2026-11-01.md`；C.18 只定义标准，本身不构成完成声明。
