# v24 Tool/Plugin ABI W9 `v24.text.plain` v1 execution record

Date: 2026-11-02 (label per plan §12.7; the final sweep window is `2026-11-01T09:50:45Z`–`2026-11-01T09:52:27Z`, i.e. 2026-11-01 17:50–17:52 +08:00 — the filename follows the plan, the timestamps follow the clock). Scope: W9 of the [W9 plan](../plans/v24-chainlit-agent-runtime-2026-11-01.md) §12 — one additive `v24.text.plain` v1 renderer, its sibling page contract, its fixed vector table, and the 13-gate s13 regression. This record is the W9 authority. It does not embed its own SHA or a future commit SHA.

## Result

**W9 passed.** All 13 §12.9 gates exited 0 in one serial sweep with their command-specific `[passed]` last lines; no exit 2 and no `[SKIP]` occurred. Node `v24.13.1` is present at `/Users/wxl/.nvm/versions/node/v24.13.1/bin/node`, so `test_node.py --node` executed and printed `[passed] W4 node contract; node=…`; W9 is therefore **`passed`**, not `passed-with-unverified`, and `toolchain absent` does not apply.

- Checkout `/Users/wxl/Projects/pg-agent`; branch `v24/ui-chainlit`; `HEAD` `1143dce6da0572bccab083da9a6be0175210b062`, local only. Nothing was staged, committed, or pushed in this run.
- W9 is not M6, not a new design §10 stage, not a re-litigation of M4/M5/W7/W8, and not a twelfth closeout item. Closeout remains **11/11**; s13 is extension evidence.
- The five W9 code/test paths in the working tree are `v24/host/renderers.py` (+111/−0), `v24/host/tool_pages.py` (+41/−3), `v24/s13/test_renderers.py` (+103/−4), `v24/s13/test_pages.py` (+2/−1), `v24/s13/test_wiring.py` (+76/−3), plus the new `v24/s13/vectors/text_plain_v1.json`. `renderers.py` is purely additive: its diff contains no deleted line.

## Additive ABI v1 revision (D-UI-5)

W9 is an explicit **additive revision of the frozen ABI v1** (plan §10 `D-UI-5`), not a redesign. The invariant is that nothing already frozen moves: the three existing renderer IDs, their version/projection, their 21 embedded goldens, and their 3 `golden_digest`/`render_digest` pairs stay byte-identical; `renderers.json`, `design_conformance.json`, `test_contracts.py`, `test_vectors.py`, `test_tools.py` and `capture_vectors.py` stay untouched; the ABI design body stays untouched.

What W9 adds:

| addition | location | value |
|---|---|---|
| renderer function | `v24/host/renderers.py` `_text` | closed value domain `{text, truncated, spill_path, exit_code, status}`; one `text` content block |
| embedded goldens | `v24/host/renderers.py` `_GOLDEN["text"]` | 9 cases |
| registry spec | `v24/host/renderers.py` 4th `_BUILTIN_SPECS` tuple | `v24.text.plain`, v1, projection 1 |
| golden digest | 4th spec tuple | `676b634b7bcae4ebdcb8a68f6aa221612eb8ef5a808f33d0d591676f996de524` |
| render digest | 4th spec tuple | `30ff1803fc2a2ec0f375da475a08f23c99e83e0ddf8c32502c26bc82a026a011` |
| page contract | `v24/host/tool_pages.py` `TEXT_PAGE_CONTRACTS` | sibling table, one `PageContract("v24.text.plain", "text", 2000)` |
| page checker | `v24/host/tool_pages.py` `_check_text` | NUL, UTF-8 encodability, 2000 lines, 32768 bytes, spill namespace, `exit_code`+`status` exclusion |
| dispatch | `v24/host/tool_pages.py` `validate_page` | `BUILTIN_PAGE_CONTRACTS` first, then `TEXT_PAGE_CONTRACTS` |
| vector table | `v24/s13/vectors/text_plain_v1.json` | format `v24-text-plain-1`, 30 cases |

The registry therefore holds **4** renderers. `test_renderers.py` asserts the literal four-ID union and the count 4; it does not read `renderers.json`. `contracts=3`, the kind map and the limit map remain BUILTIN-only and are unchanged.

## Design body unchanged (`DESIGN_SHA256`)

The ABI design body was **not amended**:

- `docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md` SHA-256 is `778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d`, equal to `v24/s13/test_contracts.py:10` `DESIGN_SHA256` and to `design_conformance.json.design_input.sha256_at_review`.
- Appending an Appendix would require changing both pins in the same atomic step. Plan §12.7 lists `test_contracts.py` and `design_conformance.json` as forbidden, so W9 does not touch the design. This is a hard constraint, not an oversight: `test_contracts.py` verifies the whole-file SHA and every pinned span.

## Old 3 renderers: 21 goldens + 3 digest pairs byte-identical

Six digest literals are unchanged from `c8c4bd0`:

| renderer | `golden_digest` | `render_digest` |
|---|---|---|
| `v24.fs.read.text` | `b803bdd5c1cd3fd25ef62f564c949d2aebd6cafdd04dcf8d740d07dc31961a1d` | `ca52198cf6c2edae798f2340ba4f370f658d422fa05f5d529c28510dea0a680c` |
| `v24.fs.list.text` | `a23d757c36073b6d5cd1b609d21a1e0ae41ad8336eccde4ce6eb3bb0f5896a5f` | `5b0bbe8d0fc70ea68c73baeb01b4df1d6be1a4e31e303dc22e3079605376f9c7` |
| `v24.fs.search.text` | `e4075fe195b7f030bd1d335ec37e9ae2a87af3ba4b497fe0a7a3dfc8565b13ac` | `fd2f51e8c3d7328b0af7ceafcbefc21418f799921e9e470f12b3f7b1b6344011` |

All six appear at the same values in `git show c8c4bd0:v24/host/renderers.py` (baseline lines 254–269) and in the working tree (lines 358–373); the literals themselves were not re-emitted or reformatted.

Two independent checks support the 21-golden claim:

1. `v24/host/renderers.py` has a purely additive diff (+111/−0), so the pre-existing `_GOLDEN` dict literal, `_GOLDEN_BY_ID`, `RENDERERS`, and the three old spec tuples cannot have changed.
2. `v24/s13/test_wiring.py::_renderer_identity_audit` re-derives the claim under `git show c8c4bd0`: it parses both revisions with `ast`, takes the `ast.get_source_segment` of the `_GOLDEN` assignment **value** (the dict literal carrying `read`/`list`/`search` = 21 cases) and of each of the three old `_BUILTIN_SPECS` tuples, and requires exact string equality. It also requires exactly 3 baseline specs, exactly 4 current specs, `set(old) == {3 old IDs}`, `set(new) == old ∪ {"v24.text.plain"}`, and `_GOLDEN["text"]` to be a 9-element list.

The runtime gate confirms the same numbers: `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3; text_positives=9; text_negatives=21`. The frozen substring `cases=7; golden_cases=21; digest_pairs=3` is preserved verbatim and the W9 counts are appended.

## Preflight inventory (§12.8) and the discovered `test_wiring.py` hit

The §12.8 table, reproduced with this run's disposition, plus the hit that table omitted:

| # | hit | location | class | disposition |
|---:|---|---|---|---|
| 1 | `len(renderers.RENDERERS) == 3` | `test_renderers.py:64` (baseline) | registry count | whitelisted; changed to 4 |
| 2 | `{entry.ref.id …} == {3 IDs}` | `test_renderers.py:65-67` (baseline) | ID set | whitelisted; changed to the literal four-ID union |
| 3 | `set(BUILTIN_PAGE_CONTRACTS) == {3 IDs}` | `tool_pages.py:249-250` (baseline), `test_pages.py:203-204` | import-time / test equality | whitelisted; changed to the union of the two tables |
| 4 | `len(BUILTIN_PAGE_CONTRACTS) == 3` | `test_tools.py:1695` | count only | **untouched**; the sibling table does not change this number |
| 5 | `BUILTIN_PAGE_CONTRACTS` limit map | `tool_pages.py:251-255`, `test_pages.py:209-213` | limit map | **untouched** |
| 6 | `v24.fs.<kind>.text` | `renderers.py`, `tool_pages.py`, `s13/*`, `vectors/renderers.json` | old 3 identities | **untouched** |
| 7 | `render.manifest.<kind>` | `test_vectors.py:119,126,150,275`, `test_contracts.py:25-26`, `vectors/*.json` | fixed triple / frozen key set | **untouched**; the new manifest case does not enter these files |
| 8 | `for kind in ('read','list','search')` | `test_vectors.py:105` | fixed triple | **untouched**; the 4th renderer does not fail it |
| 9 | `DESIGN_SHA256` / `sha256_at_review` | `test_contracts.py:10`, `vectors/design_conformance.json:6` | design pin | **untouched** |
| 10 | Node entry | `test_node.py` docstring, `:75-77` | toolchain | present; ran as `[passed]`, so no `[SKIP]` path |
| **11** | whole-file freeze of `renderers.py` | `test_wiring.py` `scope_audit()` `frozen` tuple | **frozen-baseline audit** | **not in §12.7 / not in §12.8**; see the authorized extension below |

Row 11 was invisible to the §12.8 greps because it names the path inside a `frozen` tuple rather than matching `RENDERERS.entries`, `len(RENDERERS)`, `BUILTIN_PAGE_CONTRACTS`, `v24.fs.`, `render.manifest` or the design-SHA tokens. It surfaced only in the post-fix spike rerun: `v24/s13/test_wiring.py:800` raised `CalledProcessError` for `git diff --exit-code c8c4bd0 -- … v24/host/renderers.py …`. That is an audit of the frozen baseline, not a registry count, ID set, or page-contract set, so it fell outside the three assertion classes §12.9 authorizes.

## Authorized scope extension for `v24/s13/test_wiring.py`

**Explicit statement: plan §12.7 did not list `v24/s13/test_wiring.py`, and the plan's §12.8 hit table omitted it.** The plan file was **not edited** by this run; it remains an untracked working-tree file (`?? docs/plans/v24-chainlit-agent-runtime-2026-11-01.md`), unmodified by this run.

**Why it was needed.** Adding the 4th renderer necessarily edits `v24/host/renderers.py`. `scope_audit()` required whole-file equality of that path against `c8c4bd0`, which no additive change to the file can satisfy. The alternative — dropping the audit check — would have removed the only guard on the frozen renderer bytes, so the amendment replaces whole-file equality with a narrower, stronger target.

**Exact narrow amendment (user-approved).**

1. `"v24/host/renderers.py"` is removed from the `frozen` tuple in `scope_audit()`. The other twelve frozen paths (`v24/b0`, `v24/s10`, `v24/s11`, `v24/load.py`, `canonical.py`, `descriptor.py`, `tool_schema.py`, `tool_results.py`, `line_json.py`, `journal.py`, `db.py`, `process_io.py`) still require whole-file equality.
2. A new `_renderer_identity_audit()` AST-pins, against `c8c4bd0`: (a) the `_GOLDEN` dict-literal value byte-for-byte, and (b) each of the three old `_BUILTIN_SPECS` tuples byte-for-byte. It requires exactly 3 baseline specs, exactly 4 current specs, `set(old) == {"v24.fs.read.text", "v24.fs.list.text", "v24.fs.search.text"}`, `set(new) == old ∪ {"v24.text.plain"}`, and `_GOLDEN["text"]` with exactly 9 elements.
3. The untracked-path assertion for `v24/b0`, `v24/s10`, `v24/s11`, `v24/sql`, `v24/s13/vectors` now allows exactly one path: `v24/s13/vectors/text_plain_v1.json`. Any other untracked file fails.
4. The vectors diff excludes `text_plain_v1.json` in addition to `design_conformance.json`, and a new assertion requires the changed-file set under `v24/s13/vectors` to be a subset of `{design_conformance.json, text_plain_v1.json}`.

**Why this is not a relaxation.** The audit count stays `checks=6`; twelve of the original thirteen frozen paths keep whole-file equality; the one path that lost whole-file equality is now pinned at exactly the bytes the old check protected (the 21 goldens and the three old digest pairs), plus new shape requirements the old check never had. No other assertion in `scope_audit()` was edited, and no production file was changed to satisfy the audit.

The gate's final line is unchanged in shape: `[scope] passed base=c8c4bd0 checks=6`.

## Vector encoding

`v24/s13/vectors/text_plain_v1.json`: 409 lines, 206826 bytes, SHA-256 `e42b765ea27053c73a11652907c10d5246826b7954af89f53515051136adfbaf`, format `v24-text-plain-1`.

- **30 cases = 9 positives + 21 negatives.** Positives are exactly the 9 embedded goldens; each is tagged `layer:"both"` and is executed through both `RENDERERS.render` and `validate_page`.
- **17 distinct negative scenarios.** The 21 negative cases collapse to 17 unique `id` values because 4 negative scenarios are duplicated across both layers under the **same** `id`: `text.plain.nul`, `text.plain.both_exit_status`, `text.plain.spill_empty_when_truncated`, `text.plain.spill_nonempty_when_plain`. Each of the other 13 negative IDs appears once, in exactly one declared layer.
- **Layer distribution:** `both` 9, `renderer` 10, `page` 11. Every negative runs through exactly one layer; no negative is counted twice in one layer.
- **Expectations:** `ok` 9, `render_failed` 9, `invalid_tool_output` 11, `invalid_tool_content` 1.
- **Exact boundaries:** 2000 lines accepted and 2001 lines rejected at the page layer; 32768 UTF-8 bytes accepted and 32769 rejected at the page layer; the `text.plain.value_40960` value serializes to exactly 40960 bytes under the canonical compact encoder and is accepted (its raw `text` stays under 32768, so both layers accept it).
- **NUL at both layers:** `text.plain.nul` is `render_failed` at the renderer layer (explicit `"\x00"` rejection in `_text`) and `invalid_tool_output` at the page layer (explicit `"\x00"` rejection in `_check_text`). `_check_safe_domain` does not inspect strings, so each layer has to reject it once; the two-layer case records both.
- **Lone surrogate is renderer-only:** `text.plain.lone_surrogate` expects `invalid_tool_content`. `_text` returns the string, and canonical serialization of the resulting content block fails. It is deliberately not a page case, because the page path would have to encode the value first and would fail earlier for a different reason.

The JSON key set per case is exactly `{id, args, value, content, meta, layer, expect}` for positives and `{id, args, value, layer, expect}` for negatives; `test_renderers.py` asserts the positive key set and the embedded-golden equality for the five golden keys.

## Deviation: `render.manifest.text`

**`render.manifest.text` is carried by `text_plain_v1.json`, not by `renderers.json`, and the design body was not amended.** This is the one recorded deviation (plan §12.9, `D-UI-5`).

- `test_contracts.py` pins the `renderers.json` key set with strict equality (`set(local) == REQUIRED[name]`), pins the inventory with `inventory == REQUIRED`, and pins `len(allcases) == 71`. Appending a manifest case to `renderers.json` would force edits to `test_contracts.py` and `design_conformance.json`, both forbidden by §12.7.
- Therefore the new renderer's manifest identity lives only in the 4th `_BUILTIN_SPECS` tuple (its `golden_digest`/`render_digest` pair) and in `text_plain_v1.json`. `render.manifest.text` is not registered in the W1 inventory, is not consumed by `test_vectors.py`, and does not appear in `renderers.json`.
- The design body still does not mention a generic text renderer or this manifest placement. That gap is **not** papered over as "already covered by the design": it is an additive ABI v1 extension whose documentation lives in this record, the W9 matrix section, and the README.
- Ledger note: this section is the deviation's text. `docs/reviews/v24-deviation-ledger-2026-10-23.md` was **not** appended in this run because the W9 closeout scope given for this turn named three documents (README, this record, matrix); if the ledger line is required, it is a one-section mechanical append of this same text.

## Frozen zero-diff evidence

Run from the repository root at `HEAD=1143dce6…`:

```bash
git diff --stat -- v24/s13/vectors/renderers.json v24/s13/vectors/design_conformance.json \
  v24/s13/test_contracts.py v24/s13/test_vectors.py
# (empty)

git diff --stat -- v24/s13/test_tools.py v24/s13/capture_vectors.py \
  docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md
# (empty)

git diff --name-only c8c4bd0 -- v24/b0 v24/s10 v24/s11 v24/load.py \
  v24/host/canonical.py v24/host/descriptor.py v24/host/tool_schema.py \
  v24/host/tool_results.py v24/host/line_json.py v24/host/journal.py \
  v24/host/db.py v24/host/process_io.py
# (empty)

shasum -a 256 docs/designs/v24-tool-plugin-abi-v1-2026-10-30.md
# 778b13a4df78f47987626bbe466b70ebada95fe939565253749b7e6105991a2d
```

All eight pre-existing contract vector files (`descriptor_v2`, `frames_v2`, `manifest_adapter_v2`, `provider_projection_v2`, `results_v2`, `schema_v2`, `tool_contracts`, `renderers.json`) are byte-identical; only the new `text_plain_v1.json` was added under `v24/s13/vectors`.

## Gate set

All 13 commands were run serially from the repository root with the prefix `env -u DEEPSEEK_API_KEY -u OPENAI_API_KEY -u OPENAI_API_URI -u OPENAI_MODEL UV_NO_ENV_FILE=1`.

| # | command | exit | last line |
|---:|---|---:|---|
| 1 | `uv run python v24/s13/test_contracts.py` | 0 | `[passed] W1 contract inventory; suites=10; cases=71; fixed_ids=true; tool_fixtures=concrete; read_only=true` |
| 2 | `uv run python v24/s13/test_descriptor.py` | 0 | `[passed] W2 descriptor contract; cases=16; canonical_python=9; reasons=4` |
| 3 | `uv run python v24/s13/test_pages.py` | 0 | `[passed] W4 page contract; contracts=3; cases=5417; oracle_differential=4281; unknown_ref_rejected=true` |
| 4 | `uv run python v24/s13/test_registry.py` | 0 | `[passed] W3 registry contract; cases=17; manifest_bytes=3; zero_spawn_paths=6; construction_reasons=14` |
| 5 | `uv run python v24/s13/test_renderers.py` | 0 | `[passed] W2 renderer contract; cases=7; golden_cases=21; digest_pairs=3; text_positives=9; text_negatives=21` |
| 6 | `uv run python v24/s13/test_results.py` | 0 | `[passed] W2 result contract; cases=8; envelope_bytes=3; frame_boundaries=4; replay_claimed=false` |
| 7 | `uv run python v24/s13/test_schema.py` | 0 | `[passed] W2 schema contract; cases=9; first_error_order=frozen; defaults_injected=false` |
| 8 | `uv run python v24/s13/test_tools.py` | 0 | `[passed] W4 fs tools; cases=140; read=16; read_probes=29; list=7; list_probes=11; search=24; search_probes=26; pagination_converged=true; page_contracts_imported=3` |
| 9 | `uv run python v24/s13/test_vectors.py` | 0 | `[passed] W1 read-only vectors; cases=71; PG+Python canonical=9; Node=not_requested` |
| 10 | `uv run python v24/s13/test_line_json.py` | 0 | `[passed] W3 line-json v2 contract; cases=10; frame_bytes=7; parse_rows=55; preflight_rejections=5; unknown_outcomes=4; v1_bytes_unchanged=true` |
| 11 | `uv run python v24/s13/test_lifecycle.py` | 0 | `[passed] W4 lifecycle; cases=30; recovery_probes=16; python=ok node=ok; second_spawn=false; rerender=false; journal_events_unchanged=true; no_replay=true` |
| 12 | `uv run python v24/s13/test_wiring.py` | 0 | `[passed] W4 dispatch wiring; cases=56; zero_spawn_paths=6; model_text_bytes=11; v1_bytes_unchanged=true; resource_receipt_v1=true` |
| 13 | `uv run python v24/s13/test_node.py --node` | 0 | `[passed] W4 node contract; node=/Users/wxl/.nvm/versions/node/v24.13.1/bin/node` |

`test_pages` still reports `contracts=3` and `cases=5417`; `test_tools` still reports `page_contracts_imported=3` and `len(BUILTIN_PAGE_CONTRACTS) == 3`; the W9 text cases are consumed by `test_renderers` (9 positives through both layers, 21 negatives through one layer), not by `test_pages`.

## Environment and non-claims

- No SQL file was edited and no schema change was made: `v24/sql/` contains no renderer ID, and `git diff --exit-code c8c4bd0 -- v24/sql` is empty (the `test_wiring` audit re-asserts this).
- No real provider was constructed or called; no provider socket was opened. The DB-backed gates use the disposable local PostgreSQL test database created by `setup_db`, and the plugin gates use local stub subprocesses only.
- No gate makes an outbound network connection. As in the earlier W-stage records, "no network" is a per-line construction argument, not an OS-level isolation proof.
- W9 does **not** prove: UI/Chainlit wiring or any M1+ behavior; that a real tool already emits this value shape (`bash`/apply-patch families arrive later); a hard real-time budget; or any promotion of the frozen `status` tokens. Every `status` position in `design_conformance.json` is untouched, because the file is byte-identical (`git diff` empty); W9 does not re-adjudicate any of them.
- `40960` acceptance here is the serialized-value boundary in the renderer/page layer. The host `40960`/`41984` budgets remain covered by `test_tools.py` and are not duplicated in `text_plain_v1.json`.
