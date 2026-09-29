# Focused critique: v15 real-provider DeepSeek plan

## Context/Scope

Reviewed on 2026-09-29. This is a critique, not a replacement plan or an implementation approval.

- **P** = `docs/plans/v15-real-provider-deepseek-plan-2026-09-29.md` (742 lines).
- **E** = the complete requested export, `prompt-exports/oracle-plan-2026-09-29-093612-v15-jaz-on-pg-2b3c8a-fcf8.md` (2,035 lines), read through RepoPrompt's worktree mapping. Its opening composed prompt/selection is context, **not baseline requirements**. The canonical generated draft is E:249–921; the dissenting Oracle 2 partial response starts at E:930. That lane also contains a truncated restart at E:1926–2017, which reverses its earlier extra-status proposal; it is not a third completed plan. Oracle 3 has no draft.
- **Authoritative user decisions:** HTTP timeout/lease **120s/180s**; **deepseek-flash only**; accepted **D28** accounting (invoice ≥ `cost_used`, unknown calls need not have known cost). None is reopened here.
- Inspected the seven named implementation/specification files, plus the expressly requested `test_io.py`, loader-reference searches in v15 Python gates, and the `v15_loop_snapshot` definition. No v8/jaz archaeology or wider implementation review. References below use the inspected checkout's line numbers.
- No gates or live provider calls were run. No current DeepSeek API/pricing claims are independently certified here. External documentation retrieval returned no usable material; the narrow urllib observations below were checked against the installed Python standard-library docstring/source instead.

**Assessment:** P preserves almost all implementation-bearing content of the canonical draft. Its main defects are inherited interface contradictions and unclosed lifecycle seams, not wholesale loss of that draft. The dissent contributes useful validation, transport, and pricing-audit details, but its fourth terminal status and four-code scheme are not requirements to restore.

## Findings

### 1. Baseline content omitted, weakened, or superseded

| Baseline detail | What P retains or loses | Focused correction |
|---|---|---|
| Dissent's `HttpResponse(status, headers, body)` (E:1113–1134) | P:296 returns only `(status, bytes)`, although P:196 requires reading `Retry-After`. | Restore a bounded headers/result field, or explicitly replace header-sensitive backoff with fixed backoff. Keep retry delay separate from the three-key SQL detail object. |
| Dissent's `priced_at` and immutable price-version policy (E:1411–1455, 1775–1777) | P stores revision/peak/usage, but not the pricing instant or an explicit rule preserving historical versions. | Preserve the actual injected pricing instant and immutable revision/source evidence. A small Python literal table is sufficient; a separate JSON file is not required. Revision plus peak can reproduce arithmetic, but cannot audit whether the correct time band was selected. |
| Explicit boolean/float rejection and finite-cost validation (E:1457–1470) | P says “integer/nonnegative” but leaves Python's bool-as-int trap and non-finite values implicit. | Specify exact accepted numeric types and finite Decimal output; test booleans, fractional/integral floats, and non-finite inputs. Keep FakeLLM's existing contract separate. |
| Sanitization of **all** persisted provider strings (E:1291, 1481–1485) | P:479–487 sanitizes only `content`; P:279 permits response `model` and arbitrary string `finish_reason`. | Validate/sanitize metadata too. A NUL in those fields can still invalidate the entire jsonb settlement after a billed call. Do **not** adopt the dissent's sanitize-before-split ordering for program content: it loses the required synthetic NUL failure. |
| Explicit credential-fallback tests (E:1530 onward) | P specifies fallback but its listed tests mainly prove missing-key behavior. | Add explicit-argument precedence, `DEEPSEEK_API_KEY` → `OPENAI_API_KEY` fallback, and import-time-no-env/no-network tests. These are keyless fixtures, not live tests. |
| Dissent accepts only `stop`/`length`; rejects unknown finish reasons (E:1476–1485) | P:313 accepts missing and otherwise unknown finish reasons. This is an intentional relaxation inherited from the canonical lane, not equivalent validation. | Record the decision and test it. At minimum distinguish an unknown **string** from structurally invalid arrays/objects; do not let malformed envelopes enter the success branch accidentally. |

**Alternatives not to restore by default:** the dissent's `rejected` attempt/request statuses, P1539–P1542 allocation, schema edits, provider factory, reasoning-text retention, thinking-mode environment switch, and JSON pricing file are alternative designs, not cumulative obligations. Existing `unknown` + a terminal invoke error + classified audit event can stop retry without a fourth status. Passing frozen llm configuration per call replaces a factory for this single-adapter scope. Dropping reasoning text replaces its storage without losing executable content. The longer timeout is superseded by A; pro support is superseded by B. The dissent's failure-cost settlement is also not a reason to reopen C or introduce another accounting path.

### 2. Code-confirmed corrections: retain accurate specificity

| Claim or uncertainty in P/baseline | Actual code | Correction / consequence |
|---|---|---|
| Are the four reused IO helpers invented or signature-incompatible? | **They exist.** `v15_io_pool_release(uuid, integer, numeric, boolean, numeric) RETURNS void`, IO SQL:89–124; `v15_io_close_self(uuid, integer, text, boolean, uuid) RETURNS void`, :162–243; `v15_io_terminal` with the same five parameter types, :245–281; `v15_io_reclaim_invoke(uuid) RETURNS void`, :725–841. | Keep this reuse. In the no-running-statement branch, reclaim really increments the fence and makes the invoke runnable (:792–802). Do not reimplement cleanup or bump the fence twice. **Existence does not imply support for custom error messages; see F3.** |
| `test_io.py` scans FakeLLM imports (P:128–130). | **True**, `v15/io/test_io.py:320–329` reads that file and checks top-level import lines for socket/random/time/urllib/http. | Retain the separate network module and this regression gate. The scan is lexical, not a transitive guarantee of no HTTP. Importing urllib itself is not a network call. |
| Some gate may require `len(SQL_LOAD_ORDER)==9` or govern-last (P:680, 704). | Searches of v15 Python files found loader/list references only in `v15/load.py`; no existing gate count assertion. Loader :17–44 contains nine entries and a prefix slice. | Replace the speculative gate-edit dependency with this finding. A new prefix-preservation assertion is useful; rewriting a nonexistent old assertion is not work. |
| Snapshot might strip `llm`, requiring stage-10 replacement (P:534). | **It does not.** `v15/loop/v15_loop.sql:583–591` passes the entire `v_inv.resolved_config`. | Remove only the conditional snapshot replacement work. Keep the worker config-flow tests; SQL projection is already sufficient. |
| Two `_mark_and_settle` call sites (P:459). | There are **three textual call sites**: `v15/worker.py:215`, :237, :262. The early `_llm` branch is redundant under today's `drive`, but still exists. | Thread the new argument through all three, or explicitly remove the redundant branch with coverage. |
| IO :1161 and :1284 both identify `logical_digest` (P:12). | :1161 begins **base_digest** computation; :1284 computes the request logical digest. Retry reconstructs request messages at :1041–1044 and reuses the request identity. | Correct the first reference; do not conflate the two digests. The statement that model is absent from this request digest remains accurate. |
| Token/cost keys, if present, must be numbers (P:100–102). | IO :1461–1483 also accepts JSON null for either field and leaves its initialized zero. | Describe the existing SQL permissiveness accurately, while keeping the real adapter's stricter fail-closed rule. No SQL relaxation is needed. |
| “Adding a table just needs a new stage” (P:134; opening export context). | Specification :290 and :2234 prohibit new tables after stage 1. | A stage number alone does not authorize another table. Keep the chosen no-new-table design; correct this rationale rather than expanding the schema. |

Other load-bearing observations were confirmed: `llm` has only the three named keys (`v15_config.sql:26–74`); attempt state/accounting CHECKs match P (`v15_schema.sql:239–272`); HTTP currently sits after committed mark and before settle (`worker.py:264–299`); attempt leases copy the invoke lease (IO :1061, :1294). These are useful precise constraints, not clutter to delete.

### 3. F3 — Required error message cannot pass through the chosen helper unchanged

**High; inherited from canonical.** P:399–449 requires `provider_rejected:<class>:<detail>` in the committed error and exact-message assertions. But `v15_io_close_self` constructs `v15_io_error(p_code, '')` at IO:180. Neither it nor `v15_io_terminal` takes a message argument. That empty-message object is used for both invoke error and history before child delivery (:188–225, :263–274). Adding only a sqlstate CASE arm cannot produce P's message.

**Precise options:**

1. **Smaller, sufficient design:** retain the existing empty error message, P1539/code/fatal assertions, and put detailed classification in the already-planned audit event. This fully replaces the proposed message encoding, without losing the cause.
2. If the detailed message is required in history/child-visible errors, define a message-aware shared close/terminal helper or overload in stage 10 and test propagation. This is an additional SQL dependency and contradicts “only replace one mapping branch.” Do not patch only `invokes.error` after delivery or duplicate the whole cleanup path.

The dissent noticed the need for an error-bearing cleanup seam (E:1357 onward), but its broad helper refactor is unnecessary if option 1 is selected. Repl/govern mapping questions remain implementation preconditions, not verified findings in this bounded review.

### 4. F4 — Transport result, classification, and network-test contracts do not meet

**High; mostly inherited from canonical.** P:196, 296–316, 388–392, 540–550 leave several incompatible interfaces:

- The transport discards response headers, and SQL detail allows exactly three keys. There is no channel for `Retry-After` to reach the worker. Use a result with headers and an exception's separate bounded `retry_after_s`, or choose fixed backoff. `ProviderPreflight` is also specified as an exception while the normal preflight API returns a detail dict; choose one operative contract rather than implement an unused exception route.
- A proxy-free, no-redirect urllib client normally uses a private opener. Checking only `urllib.request.urlopen` does not guard a direct `OpenerDirector.open` call. The installed implementation dispatches through `_open`, not back through `urlopen`. Patch/assert the actual production transport/opener boundary, without patching PostgreSQL's socket use. Test proxy/redirect behavior at that seam; a completely substituted scripted transport cannot prove the default transport's policy.
- “Body not JSON → abandon” and “401/402 → terminal reject” overlap. If an HTML 402 error page is parsed first, the supposed no-retry failure instead burns attempts. Classify status before success-envelope decoding; handle ordinary 4xx without requiring JSON. Treat only the narrow 400 exception as a body-dependent override, if retaining that policy. Define every 3xx and unexpected 2xx outcome, including bodies that happen to contain valid JSON.
- Specify conversion/closure of urllib HTTP-error responses as well as successful responses; otherwise 429/402 may never reach the status table. No exception should carry response bodies or credentials into persisted detail or logs.

### 5. F5 — 120s/180s is a fixed decision, but is not yet an enforceable deadline design

**High; absent as an enforceable mechanism from both drafts.** P:507–518 infers that `timeout_s=120` plus a 180-second lease guarantees a usable settle window. The installed urllib docstring describes a timeout for blocking operations, not a total wall-clock deadline. Multiple phases or periodically arriving bytes can exceed that total; the plan itself mentions keepalive blank lines. Additionally, the lease starts at **claim**, not at HTTP, and `_run` retries SQL serialization/deadlock errors without a retry bound (`worker.py:149–161`). A constructor comparison does not measure remaining lease time.

**Correction without changing A:** specify a monotonic **total** 120-second HTTP deadline, how the stdlib transport enforces cancellation/closure, and how the worker refuses to start a call without sufficient remaining claim time. Keep the 180-second lease and transaction timeout distinct. Test delayed headers, trickled reads, pre-HTTP delay, and late return using injected clocks/readers—not a real 120-second sleep. A timer that merely stops waiting while a background caller continues is not sufficient unless its ownership and late-result disposal are explicitly defined.

### 6. F6 — Billing-band approximation contradicts accepted D28

**High; internal contradiction, not an objection to C.** P:343 and D30 (:606) explicitly permit overestimating cost on holidays; P:688 asserts invoice ≥ `cost_used`. Those cannot both be guaranteed: with only settled calls, charging the higher estimated band may make `cost_used` exceed the actual invoice. Pricing at response time rather than the supplier's billing instant also leaves calls crossing a band boundary unresolved. Merely checking whether 12:00 is inclusive does not settle this.

**Correction:** preserve C and make the pricing policy consistent with it. Confirm the applicable billing instant/calendar before treating this estimate as the D28 amount; if it cannot be established, specify the already-chosen fail-closed behavior rather than claim both directional inequalities. Do not silently reinterpret C as a hard invoice cap, and do not add an invoice-reconciliation subsystem. Keep the pricing timestamp/version evidence from §1.

### 7. F7 — “length becomes prose/continue” is not a property of the executable program model

**High; inherited from canonical.** P:313 settles `length` and justifies it by existing prose recovery. Specification §4.11 (:1278–1284) says completed prefix statements can execute and remain committed before a later failure. A response truncated after a valid statement, or after a valid prefix followed by malformed SQL, is not necessarily harmless prose. The dissent also allowed `length`, so neither draft resolves this execution risk.

**Correction:** make the policy explicit: either knowingly permit partial-program execution on `length`, with a prefix-side-effect fixture, or prevent execution of truncated programs through a specifically defined failure path. Do not claim the existing splitter guarantees no execution. The same explicitness is needed for P's unknown/missing finish-reason acceptance.

### 8. F8 — Smoke scope and lifecycle need a choice before adding `exec_enabled`

**High; the lifecycle problem is not solved in either draft.** P:582–589 requires one HTTP, a settled DB attempt, and no model execution, yet P:651 leaves an executable iteration in a leased invoke. Exiting the process is not cleanup: a later ordinary worker can reclaim and execute those statements. Also, the normal scheduler retries an abandoned request (`worker.py:619–644`); `exec_enabled=False` stops execution, not a second HTTP. An after-the-fact count assertion does not prevent an extra billed call.

**Two bounded options:**

- **Named simpler replacement: adapter-only smoke + hermetic SQL integration.** The dissent proposes this at E:1600 onward. One transport call tests live request/usage/pricing, while the provider gate proves worker/settle integration. It fully removes the need for a generic `exec_enabled` flag, real-model statements in a DB, and destructive stage setup in the live probe. It does not remove DB coverage from the gate.
- If a live end-to-end **DB settlement** probe is essential, scope it to one invoke and one permitted attempt, never drain all runnable invokes, and define disposal/isolation of its DB on success, error, interruption, and assertion failure. Its lifecycle must make later execution impossible. P's warning that setup drops every `agent_v15_*` database is accurate but does not make that destruction necessary for testing an HTTP adapter.

This is a design question, not permission to rewrite the smoke unilaterally.

### 9. F9 — Worker/provider ownership and post-call cancellation are underspecified

**High; absent from both drafts as an operational contract.** The scheduler scans runnable IDs and uses one injected provider (`worker.py:131–137, 177–189, 619–639`). P keeps the default `model=fake` profile but a DeepSeek worker rejects that model terminally. In a mixed database, the wrong worker can claim and permanently fail another provider's invoke; a FakeLLM worker can likewise mark a real invocation before raising its missing-script error.

**Minimum correction:** state a homogeneous-provider database/worker-pool precondition, if that is the intended scope. Otherwise model-aware claim eligibility is needed **before** an incompatible worker mutates the invoke. Do not automatically introduce a routing framework. Specify whether endpoint/key changes between crash recovery attempts are allowed; do not persist secrets to solve this.

After a call starts, define local interruption, ownership loss, and database connection/commit uncertainty. P handles P1502 on reject/abandon, but not the complete matrix of late success, P1501, expired-holder P1523, or a lost commit acknowledgment. Existing settle checks are at IO:1442–1455; `_run` only automatically retries 40001/40P01. Preserve the rule: never repeat HTTP for the same marked attempt, never overwrite a terminal attempt with a late result, and distinguish SQL-only retry from provider retry. Close transport/DB resources on normal and exceptional exits. D28 covers unknown charges; it does not define cancellation or connection ownership.

Local sleep after abandon also cannot guarantee multi-worker backoff: the invoke is already runnable and another worker may immediately claim it. Either describe it strictly as best-effort pacing, or choose a durable scheduling mechanism only if real cross-worker backoff is required. Do not sell process-local sleep as rate-limit coordination.

### 10. F10 — Remaining boundary/dependency gaps

These are small implementation obligations, not new features:

- **Valid config can be silently ignored.** `v15_jsonb_posint` accepts integral numeric values such as `10.0` (`v15_config.sql:1–21`), and `v15_check_component` returns the unchanged object (:95). P:291 sends `max_tokens` only for a Python int. Normalize a validated integral number to int rather than silently drop a valid configured output limit. This numeric-representation seam is absent from both drafts.
- **Bound and validate untrusted responses.** Specify maximum bytes read, structural checks before indexing choices/message/usage, treatment of invalid Unicode, and safe persisted/logged metadata. Neither draft bounds response size or resolves a mismatched response model versus the requested flash pricing identity. P's 80-character truncation is not proof of model identity or safe metadata. Do not add another model; reject or normalize mismatches by an explicit policy.
- **Security assertions are missing from the new gate list.** P specifies SECURITY DEFINER ownership/search_path/worker-only EXECUTE but does not list corresponding ACL/identity tests for all three new entry points. Add denial for model role and wrong session identity, wrong owner/expired lease, null/invalid detail, plus custom `reserved_calls > 1` and nonzero reserved cost. Happy-path tests using 1/0 do not prove stored-quantity accounting.
- **Stage-10 setup must satisfy stage-9 prerequisites.** P:660 says copy IO setup, but the specification :2256–2263 requires five additional optional-hook owner roles before loading govern. Carry that bootstrap dependency into provider setup; merely renaming stage 6 is insufficient.
- **The revision checklist is incomplete.** Specification §0.19 (:107) still says 38 codes ending at P1538; P's edit list names §13/§18 but not that sentence. §3/:290 and §15/:2234 authorize only the named replacements; stage-10 mapping/helper replacements need an explicit rev-9 allowance. Adding stage 10 alone does not update every frozen sentence.
- **Test terminology/order contradicts the promised gate.** P:600 says only FakeLLM is permitted in gates and DeepSeek is constructed only by opt-in drivers, yet the provider gate constructs it with injected transport. Authorize adapter tests with FakeTransport and no external network, while retaining FakeLLM for existing behavioral gates. Make that clarification in M1/M2, not only the M3 smoke exception. “Only smoke may call live” also conflicts with P:725's hand-driven real-worker claim; distinguish supported entry points from the underlying injectable capability.

### 11. F11 — Remove stale work, not accurate constraints

P:712 still asks for **pro cache-hit prices** and a `None` fallback. Delete that residual instruction: it directly conflicts with B and P's prohibition on pro branches. It is not evidence that pro support is missing.

Replace “old gate behavior bytes unchanged” (P:205) with “prefix SQL files unchanged.” Shared `worker.py` and `fake_llm.py` do change in M2; the nine-gate regression run remains necessary. Do not remove the explicit NUL pipeline, Decimal/jsonb number handling, stored reservation quantities, same-transaction child delivery, or the documented bad-exit-hook rollback residual merely because they are low-level. They carry real implementation constraints.

## Recommendations and material questions

Resolve these before the affected milestone; no broader redesign is requested:

1. **Before M1:** Is classified audit detail sufficient, allowing existing empty terminal messages, or must detailed messages propagate into history/child errors? This decides whether SQL helper work is needed.
2. **Before M1/M2:** Is the intended runtime one provider per database/worker pool? If not, claim eligibility precedes provider invocation work.
3. **Before M2:** What stdlib mechanism enforces the accepted total 120-second deadline and closes timed-out work? How is remaining 180-second lease time checked?
4. **Before M2:** Which billing instant/calendar makes the chosen estimate consistent with accepted C? D30 must be reconciled with C, not the reverse.
5. **Before M2:** Are partial programs on `length`, and unknown/missing finish reasons, intentionally executable? This decides acceptance and failure tests.
6. **Before adding `exec_enabled`:** Must live smoke prove DB settlement, or is adapter-only smoke plus hermetic SQL integration sufficient? The latter eliminates pause-state and destructive-setup dependencies.
7. **Before M2:** Is retry pacing best-effort only? If yes, choose a complete header-aware seam or fixed delay, and test status-first classification without inventing distributed backoff.

Acceptance evidence should include real transport-boundary interception, malformed non-JSON 402, zero/invalid usage, metadata NUL, numeric config normalization, late-response/reclaim races, SQL commit uncertainty, custom reservations, and cancellation/resource cleanup. These are additions to—not substitutes for—the plan's existing SQL, keyless, NUL, Decimal, child-delivery, and regression assertions.

**Work performed:** document/baseline comparison and bounded static spot-checks only. No implementation milestone was executed; no test pass, commit, push, or live-provider success is claimed.
