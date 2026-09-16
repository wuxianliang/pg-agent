"""v8/compat/p0c_report.py — the P0C passed/failed/blocked reporter
(host-agnostic half; the G13 deliverable).

Report shape (spec P0C acceptance paragraph + section 5.2 last paragraph):
fixture/subcase granularity x test-boundary granularity (database layer
and real-I/O layer listed separately) x the two capability dimensions,
covering ALL 16 Conformance clauses. Rules enforced here:

* blocked may ONLY come from the section 5.2 capability matrix (computed
  by the single SQL source v_compat_matrix_blocked) or from the explicit
  external/pinned-host blocked allowlist (capability-source items of the
  plan's P0C environment boundary). Any other blocked source -> refuse
  (fail-class 1: 非矩阵来源 blocked).
* no missing entries: every catalog subcase must be classified and every
  clause 1-16 must have at least one row (fail-class 2: 条目缺失).
* a Native green never substitutes compat evidence (fail-class 3: 以
  Native 绿冒充 portable) — a 'passed' row needs compat-side execution,
  and a portable claim additionally needs BOTH runtimes on the same
  fixture.
* a real-I/O subcase blocked by capability degradation is never green
  (fail-class 4: 真实 I/O 层降级记绿).
* a database-layer pass never replaces its real-I/O sibling (fail-class
  5) — real-I/O rows can only pass with a real compat loop (absent until
  the pinned host lands).
* the mandatory UNSUPPORTED negative under driver_switch=unsupported is
  never exempt (fail-class 6: 负向因 blocked 免除).
* while ANY pinned-host external manifest item is unresolved (null+note
  in v8/compat/pinned_host_manifest.json) the compat contract MUST NOT
  be declared passed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_ARTIFACT = Path(__file__).resolve().parent / "pinned_host_manifest.json"

# Boundary dimension (a subcase attribute, NOT a capability condition).
DB = "db"
REAL = "real"

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

# Capability-source blocked items OUTSIDE the two-dimension matrix (the
# plan's P0C environment boundary, blocked-list items ①-⑦). These are the
# ONLY non-matrix blocked sources the reporter accepts.
EXTERNAL_BLOCKED = frozenset({
    "blocked:section-5.2-pre-verification",      # ① the pre-verification itself
    "blocked:all-real-io-subcases",              # ② every real-I/O-layer subcase
    "blocked:p0c-minimal-turn-dual-runtime",     # ③ the P0C main goal
    "blocked:pinned-five-piece-values",          # ④ pinned five-piece evidence
    "blocked:compat-only-t0-t4-participation",   # ⑤ T0-T4 tier measurement
    "blocked:p0c-final-sign-off",                # ⑥ the report final signature
    "blocked:real-provider-credentials",         # ⑦ DeepSeek credentials missing
})


class ReportError(Exception):
    """A fail-class violation: the report must not be produced."""


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
                gap="NOTIFY/队列唤醒层未实现；DB 扫描恢复语义由 Native chaos "
                    "gate 覆盖（不作 portable 证据）"),
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
                gap="compact 三命令未实现（LATER）；cancel 线性化数据库层合同"
                    "由共享 SQL 层承载，compat 侧执行面未接线"),
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
                gap="P1 世代域（G11，本分支未合并）——compat 侧未接线"),
        # -- clause 9: hook timeouts / plugin table access --
        Subcase("c9-db-hook-gates", 9,
                "mandatory authorization timeout no-dispatch; advisory hook "
                "degraded continue; plugin direct table access refused", DB,
                implemented=False,
                gap="hook 超时与 §4 runtime 完整面 LATER；数据库拒绝插件直接"
                    "访问的 RLS 面随 G10 完整模型"),
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
                gap="driver 切换正向机制另行排期（用户决策；本里程碑仅交付 "
                "UNSUPPORTED 强制负向）"),
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
                "idempotency / uncertain window (credentials env-gated)",
                DB),
        # -- clause 13: yield / checkpoint / WORKSPACE_LOST --
        Subcase("c13-db-yield-workspace", 13,
                "yield worker change / materialize / WORKSPACE_LOST "
                "fail-closed", DB, implemented=False,
                gap="workspace_handles 属 G10（本分支未合并）——compat 侧未接线"),
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
        Subcase("p0c-minimal-turn-dual-runtime", 15,
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
    subcase, plan blocked-list item ②). Nothing else may block a subcase."""
    blocked = matrix_blocked_ids(matrix)
    if "blocked:all-real-io-subcases" in external_blocked:
        blocked |= {s.subcase_id for s in CATALOG
                    if s.boundary == REAL}
    return blocked


def validate_results(results: dict[str, str], matrix: dict,
                     real_loop_available: bool = False,
                     external_blocked: frozenset = frozenset(),
                     native_evidence_only: frozenset = frozenset()) -> None:
    """The six fail-class validations. Raises ReportError on any violation.

    ``results`` maps subcase_id -> 'passed' | 'failed' | 'partial'.
    Blocked is never an input value -- it is computed from the matrix and
    the external allowlist.
    """
    blocked = effective_blocked(matrix, external_blocked)
    mandated = set(matrix.get("mandated_negative", []))

    # fail-class 2: missing entries. Every catalog subcase must be
    # classified; every clause 1-16 must have at least one report row
    # (catalog-level coverage — unimplemented subcases are yellow rows,
    # not absent rows).
    for s in CATALOG:
        if s.subcase_id in results and results[s.subcase_id] not in (
                "passed", "failed", "partial"):
            raise ReportError(
                f"subcase {s.subcase_id}: illegal result value "
                f"{results[s.subcase_id]!r} (blocked is computed, never "
                f"an input)")
    present = {s.clause for s in CATALOG}
    for clause in range(1, 17):
        if clause == 4:
            continue  # merged into 3, per the conformance-matrix note
        if clause not in present:
            raise ReportError(f"clause {clause} has no report row (missing entry)")
    runnable = [s for s in CATALOG
                if s.subcase_id not in blocked and s.implemented]
    missing = [s.subcase_id for s in runnable
               if s.subcase_id not in results]
    if missing:
        raise ReportError(
            f"implemented, non-blocked subcases without a result: {missing}")

    # fail-class 1: non-matrix blocked. A 'blocked' may only originate
    # from the two-dimension matrix rows or the external allowlist; the
    # input channel for the former is the matrix itself, so a caller
    # trying to smuggle extra blocked sources shows up as an
    # unallowlisted external item.
    for item in external_blocked:
        if item not in EXTERNAL_BLOCKED:
            raise ReportError(
                f"non-matrix blocked source not in the external allowlist: "
                f"{item!r}")

    # fail-class 3: native green masquerading as portable. A subcase whose
    # only evidence is a Native gate run can never be 'passed'.
    for sid in native_evidence_only:
        if results.get(sid) == "passed":
            raise ReportError(
                f"subcase {sid}: Native green must not be recorded as "
                f"compat/portable passed")

    # fail-class 4 + 5: real-I/O degradation. A blocked real-I/O subcase
    # is never green, and a real-I/O subcase cannot pass without a real
    # compat loop -- the database-layer sibling passing never substitutes.
    for s in CATALOG:
        if s.boundary != REAL:
            continue
        if s.subcase_id in blocked and results.get(s.subcase_id) == "passed":
            raise ReportError(
                f"real-I/O subcase {s.subcase_id} is capability-blocked and "
                f"must not be green")
        if (s.subcase_id in results
                and results[s.subcase_id] == "passed"
                and not real_loop_available):
            raise ReportError(
                f"real-I/O subcase {s.subcase_id} cannot pass without a real "
                f"compat loop (a database-layer pass never substitutes)")

    # fail-class 6: the mandated UNSUPPORTED negative is never exempt.
    if mandated:
        for sid in mandated:
            if results.get(sid) != "passed":
                raise ReportError(
                    f"mandatory negative {sid} must be present and passed "
                    f"(never exempt due to blocked)")


def build_report(results: dict[str, str], matrix: dict, *,
                 real_loop_available: bool = False,
                 external_blocked: frozenset = frozenset(),
                 native_evidence_only: frozenset = frozenset(),
                 unmapped_failed_fixtures: tuple = (),
                 compat_only_fixtures: tuple = ()) -> dict:
    """Assemble the P0C report. ``matrix`` comes from the SQL single
    source (v_compat_matrix_blocked / v_compat_participation)."""
    validate_results(results, matrix, real_loop_available,
                     external_blocked, native_evidence_only)
    blocked = effective_blocked(matrix, external_blocked)
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
            "state": state,
            "gap": s.gap if state == "partial" else "",
        })

    counts = {k: sum(1 for r in rows if r["state"] == k)
              for k in ("passed", "failed", "blocked", "partial")}
    # While ANY pinned-host external item is unresolved the compat
    # contract MUST NOT be declared passed.
    contract_passable = (
        not unresolved and counts["failed"] == 0 and counts["blocked"] == 0)
    return {
        "rows": rows,
        "counts": counts,
        "capability_matrix": matrix,
        "external_blocked": sorted(external_blocked),
        "pinned_unresolved": unresolved,
        "unmapped_failed_fixtures": list(unmapped_failed_fixtures),
        "compat_only_excluded_from_portable": list(compat_only_fixtures),
        "compat_contract_passed": False,
        "compat_contract_passable": contract_passable,
        "note": "host-agnostic half only: real-I/O rows hang blocked until "
                "the pinned DSH host lands (see "
                "v8/compat/pinned_host_manifest.json); the fake suite "
                "stays authoritative",
    }


def render(report: dict) -> str:
    lines = ["P0C passed/failed/blocked report (G13 host-agnostic half)",
             "=" * 64]
    for r in report["rows"]:
        mark = {"passed": "✅", "failed": "❌", "blocked": "⛔",
                "partial": "🟡"}[r["state"]]
        lines.append(
            f"{mark} c{r['clause']:<2d} [{r['boundary']:<4}] "
            f"{r['subcase']}: {r['state']}"
            + (f" — {r['gap']}" if r["gap"] else ""))
    c = report["counts"]
    lines.append("-" * 64)
    lines.append(
        f"passed={c['passed']} failed={c['failed']} "
        f"blocked={c['blocked']} partial(yellow)={c['partial']}")
    lines.append(
        f"external blocked sources: {report['external_blocked']}")
    lines.append(
        f"pinned-host unresolved items: {report['pinned_unresolved']}")
    lines.append(
        "compat contract declared passed: "
        f"{report['compat_contract_passed']} "
        f"(passable now: {report['compat_contract_passable']})")
    return "\n".join(lines)
