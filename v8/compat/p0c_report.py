"""v8/compat/p0c_report.py — the P0C passed/failed/blocked reporter
(host-agnostic half; the G13 deliverable). Report schema version 2 (J0).

Report shape (spec P0C acceptance paragraph + section 5.2 last paragraph):
fixture/subcase granularity x test-boundary granularity (database layer
and real-I/O layer listed separately) x the two capability dimensions,
covering ALL 16 Conformance clauses. Rules enforced here:

* blocked may ONLY come from the section 5.2 capability matrix (computed
  by the single SQL source v_compat_matrix_blocked) or from the explicit
  external/pinned-host blocked allowlist (capability-source items of the
  plan's P0C environment boundary). Any other blocked source -> refuse
  (fail-class 1: 非矩阵来源 blocked, INVALID_BLOCK_SOURCE).
* no missing entries: every catalog subcase must be classified and every
  clause 1-16 must have at least one row (fail-class 2: 条目缺失,
  MISSING_RESULT).
* a Native green never substitutes compat evidence (fail-class 3: 以
  Native 绿冒充 portable, NATIVE_EVIDENCE_AS_COMPAT) — a 'passed' row
  needs compat-side execution, and a portable claim additionally needs
  BOTH runtimes on the same fixture.
* a real-I/O subcase blocked by capability degradation is never green
  (fail-class 4: 真实 I/O 层降级记绿, BLOCKED_REAL_MARKED_PASSED).
* a database-layer pass never replaces its real-I/O sibling (fail-class
  5, REAL_PASS_WITHOUT_LOOP) — real-I/O rows can only pass with a real
  compat loop (absent until the pinned host lands).
* the mandatory UNSUPPORTED negative under driver_switch=unsupported is
  never exempt (fail-class 6: 负向因 blocked 免除,
  MANDATORY_NEGATIVE_NOT_PASSED).
* while ANY pinned-host external manifest item is unresolved (null+note
  in v8/compat/pinned_host_manifest.json) the compat contract MUST NOT
  be declared passed.

Schema v2 additions (J0 plan §5):

* every subcase carries a requirement role — mandatory (default) or
  optional_smoke (ONLY c12-db-real-provider-protocol); the optional
  smoke is opt-in via the explicit --real-provider-smoke flag and its
  absence is recorded as not_run with a closed-set reason, never as a
  new capability block and never as green.
* result values are passed/failed/partial/not_run; 'blocked' is NEVER
  an input value (computed from the matrix + allowlist only).
* three non-substitutable conclusions (declared_support_surface_
  conformant / minimal_dual_loop_passed / full_target_achieved), each
  derived from row facts with stable sorted blocker lists — callers
  cannot set them directly, and a legal capability block on mandatory
  rows is tolerated ONLY by the support-surface conclusion, never by
  the full target.
* every refusal carries a stable ``code`` on ReportError (plan §5.4).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REPORT_SCHEMA_VERSION = 2

MANIFEST_ARTIFACT = Path(__file__).resolve().parent / "pinned_host_manifest.json"

# Boundary dimension (a subcase attribute, NOT a capability condition).
DB = "db"
REAL = "real"

# Requirement roles (schema v2): mandatory rows must run and pass unless
# legally capability-blocked; the optional smoke is explicitly opt-in.
MANDATORY = "mandatory"
OPTIONAL_SMOKE = "optional_smoke"

# Result value closed set (blocked is computed, never supplied).
PASSED = "passed"
FAILED = "failed"
PARTIAL = "partial"
NOT_RUN = "not_run"
RESULT_STATES = (PASSED, FAILED, PARTIAL, NOT_RUN)

# not_run reason closed set. not_requested / credentials_absent are only
# legal on optional_smoke rows; a mandatory row that did not run keeps
# blocking every conclusion (execution_interrupted / dependency_unavailable
# describe HOW it failed to run — they never mimic a capability block).
NOT_RUN_REASONS = frozenset({
    "not_requested",
    "credentials_absent",
    "execution_interrupted",
    "dependency_unavailable",
})
OPTIONAL_ONLY_REASONS = frozenset({"not_requested", "credentials_absent"})

# The section 5.2 matrix dispatch-dimension rows (verbatim ids shared with
# v_compat_matrix_blocked) + the switch-dimension row + the mandated
# negative + the independent fork subcase.
DISPATCH_REAL_ROWS = (
    "c3-real-dispatch-unknown-recovery",
    "c5-real-cancel-unknown-classification",
    "c6-real-cancel-linearization",
    "c11-real-inflight-switch-closure",
    "c13-real-workspace-lost-inflight",
    "c14-real-revoke-dispatch",
    "c15-real-cancel-unknown-fixture",
    "real-io-unlisted-forms",
)
SWITCH_DB_ROW = "c11-db-switch-positive"
MANDATED_NEGATIVE = "c11-db-unsupported-negative"
FORK_DB_ROW = "c11-db-fork-cutoff"

# The P0C main-goal subcase (the minimal dual-loop conclusion target).
MINIMAL_DUAL_LOOP_SUBCASE = "p0c-minimal-turn-dual-runtime"

# Capability-source blocked items OUTSIDE the two-dimension matrix (the
# plan's P0C environment boundary, blocked-list items ①-⑦). These are the
# ONLY non-matrix blocked sources the reporter accepts. ⑦ (credentials)
# is a diagnostic compatibility source only: it never expands a row set
# and never lifts a mandatory row's participation duty (J0: the optional
# smoke absence is not_run, not a new capability value).
EXTERNAL_BLOCKED = frozenset({
    "blocked:section-5.2-pre-verification",      # ① the pre-verification itself
    "blocked:all-real-io-subcases",              # ② every real-I/O-layer subcase
    "blocked:p0c-minimal-turn-dual-runtime",     # ③ the P0C main goal
    "blocked:pinned-five-piece-values",          # ④ pinned five-piece evidence
    "blocked:compat-only-t0-t4-participation",   # ⑤ T0-T4 tier measurement
    "blocked:p0c-final-sign-off",                # ⑥ the report final signature
    "blocked:real-provider-credentials",         # ⑦ DeepSeek credentials missing
})

# Stable refusal codes (plan §5.4): one ReportError class, code attribute.
INVALID_BLOCK_SOURCE = "INVALID_BLOCK_SOURCE"
MISSING_RESULT = "MISSING_RESULT"
NATIVE_EVIDENCE_AS_COMPAT = "NATIVE_EVIDENCE_AS_COMPAT"
BLOCKED_REAL_MARKED_PASSED = "BLOCKED_REAL_MARKED_PASSED"
REAL_PASS_WITHOUT_LOOP = "REAL_PASS_WITHOUT_LOOP"
MANDATORY_NEGATIVE_NOT_PASSED = "MANDATORY_NEGATIVE_NOT_PASSED"
INVALID_RESULT_ID = "INVALID_RESULT_ID"
INVALID_RESULT_STATE = "INVALID_RESULT_STATE"
INVALID_NOT_RUN_REASON = "INVALID_NOT_RUN_REASON"
UNIMPLEMENTED_MARKED_PASSED = "UNIMPLEMENTED_MARKED_PASSED"
INVALID_CATALOG = "INVALID_CATALOG"


class ReportError(Exception):
    """A fail-class/structure violation: the report must not be produced.
    ``code`` is one of the stable code constants (never parse the
    message to identify the refusal)."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Subcase:
    subcase_id: str
    clause: int          # Conformance clause 1-16
    title: str
    boundary: str        # DB | REAL
    requires_sync: bool = False      # dispatch_interception = sync_before_io
    requires_supported: bool = False # driver_switch_capability = supported
    implemented: bool = True         # False -> partial (yellow) with gap
    gap: str = ""                    # gap destination for unimplemented parts
    requirement: str = MANDATORY     # mandatory | optional_smoke (schema v2)


def _catalog() -> list[Subcase]:
    c: list[Subcase] = [
        # -- clause 1: command idempotency / seq no-hole / first attempt --
        Subcase("c1-db-receipt-idempotency", 1,
                "compat surface command idempotency (compat_unmapped_audit "
                "replay/conflict; public append replays; seq no-hole)", DB),
        Subcase("c1-db-occurrence-identity", 1,
                "non-stream occurrence identity + chunk four-tuple on the "
                "compat append surface", DB),
        Subcase("c1-real-retry-single-batch", 1,
                "network retries produce one batch/effect/completion via the "
                "real compat loop", REAL, requires_sync=True,
                implemented=False, gap="真实 compat loop（pinned host 未确认）"),
        # -- clause 2: stale snapshots / fences --
        Subcase("c2-db-stale-writes", 2,
                "stale dispatch snapshot / superseded fence / old coordinator "
                "writes rejected (shared SQL contract walked by compat "
                "fixtures)", DB, implemented=False,
                gap="compat 生命周期套件未接线——数据库层合同由共享 SQL 层承载，"
                    "compat 侧执行面随 pinned host 后补"),
        # -- clause 3 (+4 merged per the matrix note): wait/NOTIFY/recovery --
        Subcase("c3-db-scan-recovery", 3,
                "DB scan recovery after lost wakeups (chaos-equivalent)", DB,
                implemented=False,
                gap="G19b 已交付 DB wait/scan/NOTIFY hint；compat 侧恢复套件待 J3 "
                    "接线（Native 证据不代替 portable）"),
        Subcase("c3-real-dispatch-unknown-recovery", 3,
                "dispatch-then-unknown / recovery takeover via the real loop",
                REAL, requires_sync=True, implemented=False,
                gap="真实 compat loop"),
        # -- clause 5: known/unknown orthogonality --
        Subcase("c5-db-classification-orthogonal", 5,
                "evidence classification known/unknown on compat completions",
                DB, implemented=False,
                gap="compat 侧分类套件未接线（共享 SQL 判定函数；§5.1 完成面 "
                    "覆盖 known_success/unknown 两形态）"),
        Subcase("c5-real-cancel-unknown-classification", 5,
                "cancel/unknown classification via the real loop", REAL,
                requires_sync=True, implemented=False, gap="真实 compat loop"),
        # -- clause 6: cancel/compact concurrency --
        Subcase("c6-db-cancel-compact", 6,
                "cancel x dispatch linearization at the DB layer", DB,
                implemented=False,
                gap="G17 已交付 compact 三命令与终态 abort；cancel/compact "
                    "compat 侧执行面待 J3 接线"),
        Subcase("c6-real-cancel-linearization", 6,
                "cancel linearization via the real loop", REAL,
                requires_sync=True, implemented=False, gap="真实 compat loop"),
        # -- clause 7: parallel tools reverse-order --
        Subcase("c7-db-parallel-ordinal", 7,
                "reverse-order tool completion, identical trace by ordinal",
                DB, implemented=False,
                gap="compat tools 套件未接线（Native G6 覆盖共享 SQL 合同，"
                    "不作 portable 证据）"),
        # -- clause 8: generation refresh/retire --
        Subcase("c8-db-generation", 8,
                "generation refresh failure / retire drain", DB,
                implemented=False,
                gap="G11/G12/G14 世代域及并发门已交付；compat 套件待 J3 接线"),
        # -- clause 9: hook timeouts / plugin table access --
        Subcase("c9-db-hook-gates", 9,
                "mandatory authorization timeout no-dispatch; advisory hook "
                "degraded continue; plugin direct table access refused", DB,
                implemented=False,
                gap="G10 RLS 与 G19a seam 已交付；mandatory hook timeout/error "
                    "runtime/compat 测试仍待接线"),
        # -- clause 10: canonicalizer / stream integrity --
        Subcase("c10-db-s5-mapping", 10,
                "section 5.1 mapping database layer (whitelist appends, chunk "
                "attribution with grants, stream_progress via complete_effect)",
                DB),
        # -- clause 11: fork cutoff / switch positive+negative --
        Subcase(FORK_DB_ROW, 11,
                "fork cutoff stability three assertions (acceptance twins)",
                DB),
        Subcase(SWITCH_DB_ROW, 11,
                "switch positive subcase (SWITCH_DEFERRED guards, quiescing, "
                "finish_switch barrier, driver_epoch+1)", DB,
                requires_supported=True, implemented=False,
                gap="G18 共享切换机制已交付；pinned compat 声明仍 unsupported，"
                    "compat 正向完整套件待 J3/host 实证"),
        Subcase(MANDATED_NEGATIVE, 11,
                "mandatory negative: begin_switch stably returns UNSUPPORTED "
                "on unsupported drivers, mode/fence/switch intent unchanged",
                DB),
        Subcase("c11-real-inflight-switch-closure", 11,
                "in-flight switch closure via the real loop", REAL,
                requires_sync=True, implemented=False, gap="真实 compat loop"),
        # -- clause 12: deterministic fakes authoritative / real provider --
        Subcase("c12-db-fake-suite", 12,
                "deterministic fake suite stays authoritative (fake "
                "LLM/tool, fixed locale/timezone)", DB),
        Subcase("c12-db-real-provider-protocol", 12,
                "real provider DB protocol layer: protocol shape / "
                "idempotency / uncertain window (explicit opt-in "
                "--real-provider-smoke; credentials env-gated; the default "
                "keyless run records not_run/not_requested)",
                DB, requirement=OPTIONAL_SMOKE),
        # -- clause 13: yield / checkpoint / WORKSPACE_LOST --
        Subcase("c13-db-yield-workspace", 13,
                "yield worker change / materialize / WORKSPACE_LOST "
                "fail-closed", DB, implemented=False,
                gap="G10 workspace_handles/WORKSPACE_LOST 已交付；compat 侧待 J3 接线"),
        Subcase("c13-real-workspace-lost-inflight", 13,
                "WORKSPACE_LOST in-flight completion/unknown via the real "
                "loop", REAL, requires_sync=True, implemented=False,
                gap="真实 compat loop"),
        # -- clause 14: grant linearization / revoke x dispatch --
        Subcase("c14-db-grant-denied", 14,
                "grant-denied closure + chunk dual-grant conjunction via the "
                "stub surface (direct-inserted grants)", DB),
        Subcase("c14-real-revoke-dispatch", 14,
                "revoke x dispatch race via the real loop", REAL,
                requires_sync=True, implemented=False, gap="真实 compat loop"),
        # -- clause 15: cancel/unknown fixtures byte-identical --
        Subcase("c15-db-cancel-fixtures", 15,
                "cancel/unknown fixture canonical outputs (reducer unit "
                "layer, shared canonicalizer)", DB, implemented=False,
                gap="fixture 字节级双运行时比较需真实 loop；reducer 单元合同"
                    "由共享 canonicalizer 承载"),
        Subcase("c15-real-cancel-unknown-fixture", 15,
                "cancel/unknown classification fixture via the real loop",
                REAL, requires_sync=True, implemented=False, gap="真实 compat loop"),
        # -- clause 16: compat blocked matrix / P0C report --
        Subcase("c16-db-unmapped-audit", 16,
                "compat_unmapped_audit unified command (idempotent replay / "
                "IDEMPOTENCY_CONFLICT / no semantic-result events / public "
                "append refusal)", DB),
        Subcase("c16-db-matrix-logic", 16,
                "two-dimension capability matrix blocked-set union rules "
                "(GUC-seamed matrix logic)", DB),
        # -- P0C main goal --
        Subcase("real-io-unlisted-forms", 14,
                "remaining real-I/O forms incl. clause-14 revoke x dispatch "
                "real-loop shape and authorization-before-IO verification",
                REAL, requires_sync=True, implemented=False,
                gap="真实 compat loop"),
        Subcase(MINIMAL_DUAL_LOOP_SUBCASE, 15,
                "P0C main goal: one minimal turn, identical observable trace "
                "on both runtimes", REAL, requires_sync=True,
                implemented=False, gap="pinned host 未确认（blocked ③）"),
    ]
    return c


CATALOG = _catalog()
BY_ID = {s.subcase_id: s for s in CATALOG}


def load_pinned_manifest() -> dict:
    with open(MANIFEST_ARTIFACT, encoding="utf-8") as fh:
        return json.load(fh)


def pinned_unresolved_items(pinned: dict) -> list[str]:
    """The pinned five-piece set + section 5.2 pre-verification items that
    are still null+note (unresolved)."""
    unresolved = []
    for name, item in pinned["pinned"].items():
        if item.get("value") is None:
            unresolved.append(f"pinned.{name}")
    pv = pinned["section_5_2_pre_verification"]["dispatch_interception"]
    if pv.get("value") is None:
        unresolved.append("section_5_2_pre_verification.dispatch_interception")
    return unresolved


def matrix_blocked_ids(matrix: dict) -> set[str]:
    return set(matrix.get("blocked", []))


def effective_blocked(matrix: dict, external_blocked: frozenset) -> set[str]:
    """The per-subcase blocked set: the two-dimension matrix rows PLUS the
    allowlisted external source 'blocked:all-real-io-subcases' (the pinned
    host is missing — a capability-source block covering EVERY real-I/O
    subcase, plan blocked-list item ②). Nothing else may block a subcase.
    A missing-credential diagnostic (⑦) never expands this set (J0: the
    optional smoke absence is not_run, not a capability block)."""
    blocked = matrix_blocked_ids(matrix)
    if "blocked:all-real-io-subcases" in external_blocked:
        blocked |= {s.subcase_id for s in CATALOG
                    if s.boundary == REAL}
    return blocked


def _validate_catalog() -> None:
    seen: set[str] = set()
    for s in CATALOG:
        if s.subcase_id in seen:
            raise ReportError(
                f"duplicate catalog subcase_id {s.subcase_id!r}",
                code=INVALID_CATALOG)
        seen.add(s.subcase_id)
    if any(s.requirement not in (MANDATORY, OPTIONAL_SMOKE)
           or (s.requirement == OPTIONAL_SMOKE
               and s.subcase_id != "c12-db-real-provider-protocol")
           for s in CATALOG):
        raise ReportError("catalog carries an illegal requirement role",
                          code=INVALID_CATALOG)


def _validate_not_run(results: dict[str, str],
                      not_run_reasons: dict[str, str]) -> None:
    """The centralized not_run decision matrix (plan §5.4): checked after
    the illegal-value checks and BEFORE the fail-class 2 missing-entry
    check. A mandatory row holding 'not_run' HAS a value, so the missing
    branch never covers it — these are independent checks."""
    for sid, value in results.items():
        if value != NOT_RUN:
            continue
        reason = not_run_reasons.get(sid)
        if reason not in NOT_RUN_REASONS:
            raise ReportError(
                f"subcase {sid} is not_run without a closed-set reason "
                f"(got {reason!r}; expected one of "
                f"{sorted(NOT_RUN_REASONS)})",
                code=INVALID_NOT_RUN_REASON)
        if (BY_ID[sid].requirement == MANDATORY
                and reason in OPTIONAL_ONLY_REASONS):
            raise ReportError(
                f"mandatory subcase {sid} is not_run with optional-only "
                f"reason {reason!r} (not_requested/credentials_absent are "
                f"reserved for the optional smoke)",
                code=INVALID_NOT_RUN_REASON)
    for sid in not_run_reasons:
        if results.get(sid) != NOT_RUN:
            raise ReportError(
                f"not_run reason supplied for {sid} whose result is "
                f"{results.get(sid, 'missing')!r} (leftover reasons are "
                f"refused)",
                code=INVALID_NOT_RUN_REASON)


def validate_results(results: dict[str, str], matrix: dict,
                     real_loop_available: bool = False,
                     external_blocked: frozenset = frozenset(),
                     native_evidence_only: frozenset = frozenset(),
                     not_run_reasons: dict[str, str] | None = None) -> None:
    """The six fail-class validations plus the schema-v2 structure checks.
    Raises ReportError (with a stable ``code``) on any violation.

    ``results`` maps subcase_id -> passed | failed | partial | not_run.
    Blocked is never an input value -- it is computed from the matrix and
    the external allowlist. Validation order (plan §5.4): external-block
    legality and result structure first, then missing entries -> Native
    evidence -> REAL degradation (blocked) -> REAL without a loop -> the
    mandated negative.
    """
    _validate_catalog()
    reasons = dict(not_run_reasons or {})
    blocked = effective_blocked(matrix, external_blocked)
    mandated = set(matrix.get("mandated_negative", []))

    # ---- structure: external blocked legality + result shape ----
    for item in external_blocked:
        if item not in EXTERNAL_BLOCKED:
            raise ReportError(
                f"non-matrix blocked source not in the external allowlist: "
                f"{item!r}", code=INVALID_BLOCK_SOURCE)
    for sid in results:
        if sid not in BY_ID:
            raise ReportError(
                f"result for an unknown subcase id: {sid!r}",
                code=INVALID_RESULT_ID)
    for sid in reasons:
        if sid not in BY_ID:
            raise ReportError(
                f"not_run reason for an unknown subcase id: {sid!r}",
                code=INVALID_RESULT_ID)
    for sid, value in results.items():
        if value not in RESULT_STATES:
            raise ReportError(
                f"subcase {sid}: illegal result value {value!r} (blocked is "
                f"computed, never an input; legal values: {RESULT_STATES})",
                code=INVALID_RESULT_STATE)
    _validate_not_run(results, reasons)
    for sid, value in results.items():
        if value == PASSED and not BY_ID[sid].implemented:
            raise ReportError(
                f"unimplemented subcase {sid} self-reports passed (a caller "
                f"cannot bypass the catalog)",
                code=UNIMPLEMENTED_MARKED_PASSED)

    # ---- fail-class 2: missing entries ----
    present = {s.clause for s in CATALOG}
    for clause in range(1, 17):
        if clause == 4:
            continue  # merged into 3, per the conformance-matrix note
        if clause not in present:
            raise ReportError(f"clause {clause} has no report row (missing "
                              f"entry)", code=MISSING_RESULT)
    runnable = [s for s in CATALOG
                if s.subcase_id not in blocked and s.implemented]
    missing = [s.subcase_id for s in runnable
               if s.subcase_id not in results]
    if missing:
        raise ReportError(
            f"implemented, non-blocked subcases without a result: {missing}",
            code=MISSING_RESULT)

    # ---- fail-class 3: native green masquerading as portable ----
    for sid in native_evidence_only:
        if results.get(sid) == PASSED:
            raise ReportError(
                f"subcase {sid}: Native green must not be recorded as "
                f"compat/portable passed", code=NATIVE_EVIDENCE_AS_COMPAT)

    # ---- fail-class 4: blocked REAL degradation ----
    for s in CATALOG:
        if s.boundary != REAL:
            continue
        if s.subcase_id in blocked and results.get(s.subcase_id) == PASSED:
            raise ReportError(
                f"real-I/O subcase {s.subcase_id} is capability-blocked and "
                f"must not be green", code=BLOCKED_REAL_MARKED_PASSED)

    # ---- fail-class 5: real pass without a real loop ----
    for s in CATALOG:
        if s.boundary != REAL:
            continue
        if (s.subcase_id in results
                and results[s.subcase_id] == PASSED
                and not real_loop_available):
            raise ReportError(
                f"real-I/O subcase {s.subcase_id} cannot pass without a real "
                f"compat loop (a database-layer pass never substitutes)",
                code=REAL_PASS_WITHOUT_LOOP)

    # ---- fail-class 6: the mandated UNSUPPORTED negative ----
    if mandated:
        for sid in mandated:
            if results.get(sid) != PASSED:
                raise ReportError(
                    f"mandatory negative {sid} must be present and passed "
                    f"(never exempt due to blocked)",
                    code=MANDATORY_NEGATIVE_NOT_PASSED)


def _conclusions(results: dict[str, str], rows: list[dict],
                 blocked: set[str], matrix: dict, real_loop_available: bool,
                 native_evidence_only: frozenset,
                 unmapped_failed_fixtures: tuple,
                 unresolved: list[str]) -> dict:
    """Derive the three non-substitutable conclusions from row facts.
    Callers never set these booleans directly; every blocker id is stable
    and the lists are sorted."""
    mandated = set(matrix.get("mandated_negative", []))
    row_state = {r["subcase"]: r["state"] for r in rows}
    explicit_failed = sorted(sid for sid, v in results.items()
                             if v == FAILED)

    # 1. declared support surface: legally capability-blocked mandatory
    #    rows are tolerated; every other mandatory row must be green.
    #    An actually-run-and-failed optional smoke is an explicit failure
    #    too — it is never hidden as an absence.
    sss: list[str] = [f"pinned:{item}" for item in unresolved]
    for s in CATALOG:
        if s.requirement != MANDATORY or s.subcase_id in blocked:
            continue
        if row_state[s.subcase_id] != PASSED:
            sss.append(f"subcase:{s.subcase_id}:{row_state[s.subcase_id]}")
    for sid in sorted(mandated):
        if results.get(sid) != PASSED:
            sss.append(f"mandatory_negative:{sid}")
    for sid in explicit_failed:
        sss.append(f"explicit_failure:{sid}")
    if unmapped_failed_fixtures:
        sss.append("unmapped_failed_fixtures")

    # 2. minimal dual loop: only describes the minimal experiment, never
    #    the wider fixture surface.
    mdl: list[str] = []
    target = BY_ID.get(MINIMAL_DUAL_LOOP_SUBCASE)
    if target is None:
        mdl.append("minimal_turn_subcase_missing")
    else:
        if target.subcase_id in blocked:
            mdl.append(f"subcase:{target.subcase_id}:blocked")
        elif results.get(target.subcase_id) != PASSED:
            mdl.append(f"subcase:{target.subcase_id}:"
                       f"{results.get(target.subcase_id, 'missing')}")
        if target.subcase_id in native_evidence_only:
            mdl.append(f"native_evidence_only:{target.subcase_id}")
    if not real_loop_available:
        mdl.append("no_real_loop")
    if unmapped_failed_fixtures:
        mdl.append("unmapped_failed_fixtures")

    # 3. full target: stricter than the support surface — NO mandatory
    #    blocked/partial/not_run/failed at all, both conclusions above
    #    true, pinned resolved, no unmapped failures. An optional smoke
    #    that merely did not run never blocks it; an optional smoke that
    #    actually ran and failed keeps its failure.
    ft: list[str] = []
    if sss:
        ft.append("declared_support_surface_conformant")
    if mdl:
        ft.append("minimal_dual_loop_passed")
    ft += [f"pinned:{item}" for item in unresolved]
    for s in CATALOG:
        if s.requirement != MANDATORY:
            continue
        if row_state[s.subcase_id] != PASSED:
            ft.append(f"mandatory:{s.subcase_id}:{row_state[s.subcase_id]}")
    for sid in explicit_failed:
        if sid in BY_ID and BY_ID[sid].requirement != MANDATORY:
            ft.append(f"optional_failure:{sid}")
    if unmapped_failed_fixtures:
        ft.append("unmapped_failed_fixtures")

    def _c(blockers: list[str]) -> dict:
        uniq = sorted(set(blockers))
        return {"passed": not uniq, "blockers": uniq}

    return {
        "declared_support_surface_conformant": _c(sss),
        "minimal_dual_loop_passed": _c(mdl),
        "full_target_achieved": _c(ft),
    }


def build_report(results: dict[str, str], matrix: dict, *,
                 real_loop_available: bool = False,
                 external_blocked: frozenset = frozenset(),
                 native_evidence_only: frozenset = frozenset(),
                 not_run_reasons: dict[str, str] | None = None,
                 unmapped_failed_fixtures: tuple = (),
                 compat_only_fixtures: tuple = ()) -> dict:
    """Assemble the P0C report (schema v2). ``matrix`` comes from the SQL
    single source (v_compat_matrix_blocked / v_compat_participation)."""
    validate_results(results, matrix, real_loop_available,
                     external_blocked, native_evidence_only, not_run_reasons)
    blocked = effective_blocked(matrix, external_blocked)
    reasons = dict(not_run_reasons or {})
    pinned = load_pinned_manifest()
    unresolved = pinned_unresolved_items(pinned)

    rows = []
    for s in CATALOG:
        if s.subcase_id in blocked:
            state = "blocked"
        elif not s.implemented:
            state = "partial"      # yellow, with the gap destination
        else:
            state = results.get(s.subcase_id, "partial")
        rows.append({
            "subcase": s.subcase_id,
            "clause": s.clause,
            "title": s.title,
            "boundary": s.boundary,
            "requirement": s.requirement,
            "state": state,
            "not_run_reason": (reasons.get(s.subcase_id, "")
                               if state == NOT_RUN else ""),
            "gap": s.gap if state == "partial" else "",
        })

    counts = {k: sum(1 for r in rows if r["state"] == k)
              for k in ("passed", "failed", "blocked", "partial", "not_run")}
    conclusions = _conclusions(results, rows, blocked, matrix,
                               real_loop_available, native_evidence_only,
                               unmapped_failed_fixtures, unresolved)
    # The legacy passable alias carries ONLY schema-v2 semantics (review
    # F6): under any other schema version the old formula must not be
    # silently reinterpreted (an optional-smoke row blocked by the matrix
    # would make the new value LOOSER than the old blocked==0 rule).
    assert REPORT_SCHEMA_VERSION == 2, \
        "compat_contract_passable alias requires report schema v2"
    contract_passable = conclusions["full_target_achieved"]["passed"]
    # While ANY pinned-host external item is unresolved the compat
    # contract MUST NOT be declared passed (the explicit final signature
    # stays a human act — never auto-signed here).
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "rows": rows,
        "counts": counts,
        "capability_matrix": matrix,
        "external_blocked": sorted(external_blocked),
        "pinned_unresolved": unresolved,
        "unmapped_failed_fixtures": list(unmapped_failed_fixtures),
        "compat_only_excluded_from_portable": list(compat_only_fixtures),
        "conclusions": conclusions,
        "compat_contract_passed": False,
        "compat_contract_passable": contract_passable,
        "note": "host-agnostic half only: real-I/O rows hang blocked until "
                "the pinned DSH host lands (see "
                "v8/compat/pinned_host_manifest.json); the fake suite "
                "stays authoritative; script green != P0C complete",
    }


def render(report: dict) -> str:
    lines = ["P0C passed/failed/blocked report (G13 host-agnostic half)",
             "=" * 64]
    marks = {"passed": "✅", "failed": "❌", "blocked": "⛔",
             "partial": "🟡", "not_run": "⏸"}
    for r in report["rows"]:
        role = (" [optional-smoke]"
                if r.get("requirement") == OPTIONAL_SMOKE else "")
        reason = (f" (reason: {r['not_run_reason']})"
                  if r.get("not_run_reason") else "")
        lines.append(
            f"{marks[r['state']]} c{r['clause']:<2d} [{r['boundary']:<4}] "
            f"{r['subcase']}{role}: {r['state']}{reason}"
            + (f" — {r['gap']}" if r["gap"] else ""))
    c = report["counts"]
    lines.append("-" * 64)
    lines.append(
        f"passed={c['passed']} failed={c['failed']} "
        f"blocked={c['blocked']} partial(yellow)={c['partial']} "
        f"not_run={c['not_run']}")
    lines.append(
        f"external blocked sources: {report['external_blocked']}")
    lines.append(
        f"pinned-host unresolved items: {report['pinned_unresolved']}")
    for key, label in (
            ("declared_support_surface_conformant", "declared support surface"),
            ("minimal_dual_loop_passed", "minimal dual loop"),
            ("full_target_achieved", "full target")):
        cc = report["conclusions"][key]
        state = "passed" if cc["passed"] else "not passed"
        blockers = (f" — blockers: {', '.join(cc['blockers'])}"
                    if cc["blockers"] else "")
        lines.append(f"{label}: {state}{blockers}")
    lines.append(
        "compat contract declared passed: "
        f"{report['compat_contract_passed']} "
        f"(passable now: {report['compat_contract_passable']})")
    lines.append("script green != P0C complete; the fake suite stays "
                 "authoritative")
    return "\n".join(lines)
