"""Final release-gate evaluator.

Requires a completed Phase 0 result plus explicit Phase 1–7 and E3 states.
Never assigns would_pass from phase0_pass alone.
Malformed or contradictory Phase 0 input is unverified, never release-ready.
release_ready additionally requires a canonical Phase 0 attestation of current
repository inputs. Optional expected_source_fingerprint may further constrain
that attestation; it is not the only race defense.
A structurally valid hand-authored phase0_pass=true projection is not enough.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Mapping

from v7.gates.phase0_evaluator import (
    EVALUATOR_ID as PHASE0_EVALUATOR_ID,
    PHASE0_ATTESTATION_SCHEMA,
    PHASE0_BLOCKER_CLASS_ORDER,
    REASON_CODES as PHASE0_REASON_CODES,
    SCHEMA_VERSION as PHASE0_SCHEMA_VERSION,
    attest_phase0_from_repo,
    phase0_projection,
    phase0_result_validation_codes,
)

SCHEMA_VERSION = "flock-rag-release-gate/2"
EVALUATOR_ID = "v7.gates.release_evaluator"

PHASE_IDS = [f"phase_{index}" for index in range(1, 8)]
PHASE_STATES = {"NOT_STARTED", "IN_PROGRESS", "BLOCKED", "PASSED"}
EVIDENCE_LEVELS = {"E0", "E1", "E2", "E3"}

BLOCKER_CLASS_PHASE0_ATTESTATION = "phase0_attestation"
BLOCKER_CLASS_PHASE_GATES = "phase_gates"
BLOCKER_CLASS_E3 = "e3_integration"
RELEASE_BLOCKER_CLASS_ORDER = (
    [BLOCKER_CLASS_PHASE0_ATTESTATION]
    + list(PHASE0_BLOCKER_CLASS_ORDER)
    + [
        BLOCKER_CLASS_PHASE_GATES,
        BLOCKER_CLASS_E3,
    ]
)

CODE_PHASE0_NOT_VERIFIED = "PHASE0_NOT_VERIFIED"
CODE_PHASE0_SOURCE_UNBOUND = "PHASE0_SOURCE_UNBOUND"
CODE_PHASE0_FINGERPRINT_MISMATCH = "PHASE0_FINGERPRINT_MISMATCH"
CODE_PHASE0_NOT_CANONICAL = "PHASE0_NOT_CANONICAL"
CODE_PHASE0_SOURCE_CHANGED = "PHASE0_SOURCE_CHANGED"
CODE_PHASE_GATE_NOT_PASSED = "PHASE_GATE_NOT_PASSED"
CODE_E3_NOT_VERIFIED = "E3_NOT_VERIFIED"
PHASE0_NOT_VERIFIED = "phase0_not_verified"
PHASE0_SOURCE_UNBOUND = "phase0_source_unbound"
PHASE0_FINGERPRINT_MISMATCH = "phase0_fingerprint_mismatch"
PHASE0_NOT_CANONICAL = "phase0_not_canonical"
PHASE0_SOURCE_CHANGED = "phase0_source_changed"

RELEASE_REASON_CODES = set(PHASE0_REASON_CODES) | {
    CODE_PHASE0_NOT_VERIFIED,
    CODE_PHASE0_SOURCE_UNBOUND,
    CODE_PHASE0_FINGERPRINT_MISMATCH,
    CODE_PHASE0_NOT_CANONICAL,
    CODE_PHASE0_SOURCE_CHANGED,
    CODE_PHASE_GATE_NOT_PASSED,
    CODE_E3_NOT_VERIFIED,
}

RELEASE_RESULT_CODES = [
    "RELEASE_RESULT_NOT_OBJECT",
    "RELEASE_SCHEMA_VERSION_INVALID",
    "RELEASE_EVALUATOR_INVALID",
    "RELEASE_READY_TYPE_INVALID",
    "RELEASE_WOULD_PASS_MISMATCH",
    "RELEASE_BLOCKER_IDS_INVALID",
    "RELEASE_BLOCKER_CLASSES_INVALID",
    "RELEASE_REASONS_INVALID",
    "RELEASE_BLOCKER_ID_DUPLICATE",
    "RELEASE_CLASS_ORDER_INVALID",
    "RELEASE_REASON_ALIGNMENT_INVALID",
    "RELEASE_READY_CONTRADICTS_BLOCKERS",
    "RELEASE_PHASE0_PROJECTION_MISSING",
    "RELEASE_PHASE0_PROJECTION_INVALID",
    "RELEASE_PHASE_GATES_MISSING",
    "RELEASE_PHASE_GATES_INVALID",
    "RELEASE_E3_MISSING",
    "RELEASE_E3_INVALID",
]

PHASE_GATE_STATE_KEYS = ("state", "evidence_level", "exit_criteria_passed")
E3_STATE_KEYS = (
    "state",
    "evidence_level",
    "frozen_four_repo_pins",
    "cross_repo_integration_passed",
    "phase_7_exit_criteria_passed",
)

DEFAULT_PHASE_STATE = {
    "state": "NOT_STARTED",
    "evidence_level": "E0",
    "exit_criteria_passed": False,
}

DEFAULT_E3_STATE = {
    "state": "NOT_STARTED",
    "evidence_level": "E0",
    "frozen_four_repo_pins": False,
    "cross_repo_integration_passed": False,
    "phase_7_exit_criteria_passed": False,
}

UNVERIFIED_PHASE0 = {
    "schema_version": PHASE0_SCHEMA_VERSION,
    "evaluator": PHASE0_EVALUATOR_ID,
    "phase0_pass": False,
    "blocker_ids": [],
    "blocker_classes": [],
    "reasons": [],
}

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def default_phase_gates() -> dict[str, dict[str, Any]]:
    return {phase_id: dict(DEFAULT_PHASE_STATE) for phase_id in PHASE_IDS}


def default_e3_state() -> dict[str, Any]:
    return dict(DEFAULT_E3_STATE)


def _reason(blocker_id: str, blocker_class: str, code: str, details: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "blocker_id": blocker_id,
        "blocker_class": blocker_class,
        "code": code,
        "details": dict(details),
    }


def _allowed_token(value: object, allowed: set[str] | tuple[str, ...] | list[str]) -> bool:
    return isinstance(value, str) and value in allowed


def _is_bool(value: object) -> bool:
    return isinstance(value, bool)


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_fingerprint(value: object) -> bool:
    return isinstance(value, str) and bool(_FINGERPRINT_RE.match(value))


def _phase_gate_state_structurally_valid(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if set(value) != set(PHASE_GATE_STATE_KEYS):
        return False
    if not _allowed_token(value.get("state"), PHASE_STATES):
        return False
    if not _allowed_token(value.get("evidence_level"), EVIDENCE_LEVELS):
        return False
    return _is_bool(value.get("exit_criteria_passed"))


def _release_phase_gates_structurally_valid(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if set(value) != set(PHASE_IDS):
        return False
    return all(_phase_gate_state_structurally_valid(value.get(phase_id)) for phase_id in PHASE_IDS)


def _release_e3_structurally_valid(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if set(value) != set(E3_STATE_KEYS):
        return False
    if not _allowed_token(value.get("state"), PHASE_STATES):
        return False
    if not _allowed_token(value.get("evidence_level"), EVIDENCE_LEVELS):
        return False
    return (
        _is_bool(value.get("frozen_four_repo_pins"))
        and _is_bool(value.get("cross_repo_integration_passed"))
        and _is_bool(value.get("phase_7_exit_criteria_passed"))
    )


def _phase_passes(phase_id: str, state: Mapping[str, Any] | None) -> bool:
    if not isinstance(state, Mapping):
        return False
    if state.get("state") != "PASSED":
        return False
    if state.get("exit_criteria_passed") is not True:
        return False
    level = state.get("evidence_level")
    if phase_id == "phase_7":
        return level == "E3"
    return _allowed_token(level, {"E2", "E3"})


def _e3_passes(state: Mapping[str, Any] | None) -> bool:
    if not isinstance(state, Mapping):
        return False
    return (
        state.get("state") == "PASSED"
        and state.get("evidence_level") == "E3"
        and state.get("frozen_four_repo_pins") is True
        and state.get("cross_repo_integration_passed") is True
        and state.get("phase_7_exit_criteria_passed") is True
    )


def _normalized_phase_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        return dict(DEFAULT_PHASE_STATE)
    recorded_state = state.get("state")
    level = state.get("evidence_level")
    return {
        "state": recorded_state if _allowed_token(recorded_state, PHASE_STATES) else "BLOCKED",
        "evidence_level": level if _allowed_token(level, EVIDENCE_LEVELS) else "E0",
        "exit_criteria_passed": state.get("exit_criteria_passed") is True,
    }


def _normalized_e3_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        return dict(DEFAULT_E3_STATE)
    recorded_state = state.get("state")
    level = state.get("evidence_level")
    return {
        "state": recorded_state if _allowed_token(recorded_state, PHASE_STATES) else "BLOCKED",
        "evidence_level": level if _allowed_token(level, EVIDENCE_LEVELS) else "E0",
        "frozen_four_repo_pins": state.get("frozen_four_repo_pins") is True,
        "cross_repo_integration_passed": state.get("cross_repo_integration_passed") is True,
        "phase_7_exit_criteria_passed": state.get("phase_7_exit_criteria_passed") is True,
    }


class _ReleaseSink:
    def __init__(self) -> None:
        self._by_class: dict[str, list[dict[str, Any]]] = {cls: [] for cls in RELEASE_BLOCKER_CLASS_ORDER}
        self._seen: set[str] = set()

    def add(
        self,
        blocker_id: str,
        blocker_class: str,
        code: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if blocker_class not in self._by_class:
            raise ValueError(blocker_class)
        if code not in RELEASE_REASON_CODES:
            raise ValueError(code)
        if blocker_id in self._seen:
            return
        self._seen.add(blocker_id)
        self._by_class[blocker_class].append(_reason(blocker_id, blocker_class, code, details or {}))

    def assembled(self) -> tuple[list[str], list[str], list[dict[str, Any]]]:
        blocker_ids: list[str] = []
        blocker_classes: list[str] = []
        reasons: list[dict[str, Any]] = []
        for cls in RELEASE_BLOCKER_CLASS_ORDER:
            rows = self._by_class[cls]
            if not rows:
                continue
            blocker_classes.append(cls)
            for row in rows:
                blocker_ids.append(row["blocker_id"])
                reasons.append(row)
        return blocker_ids, blocker_classes, reasons


def _attestation_is_canonical(attestation: object) -> bool:
    if not isinstance(attestation, Mapping):
        return False
    if attestation.get("schema_version") != PHASE0_ATTESTATION_SCHEMA:
        return False
    if attestation.get("evaluator") != PHASE0_EVALUATOR_ID:
        return False
    if not _is_bool(attestation.get("attested")):
        return False
    if not _is_fingerprint(attestation.get("source_fingerprint")):
        return False
    if phase0_result_validation_codes(attestation.get("phase0")):
        return False
    return True


def _copy_environ(environ: Mapping[str, str] | None) -> dict[str, str] | None:
    return None if environ is None else dict(environ)


def evaluate_release_from_repo(
    repo_root: Path,
    phase_gates: Mapping[str, Any] | None,
    e3: Mapping[str, Any] | None,
    *,
    environ: Mapping[str, str] | None = None,
    expected_source_fingerprint: str | None = None,
    source_reader: Callable[[Path], bytes] | None = None,
) -> dict[str, Any]:
    env = _copy_environ(environ)
    attestation = attest_phase0_from_repo(repo_root, environ=env, source_reader=source_reader)
    return _assemble_release(
        attestation["phase0"],
        phase_gates,
        e3,
        attestation=attestation,
        expected_source_fingerprint=expected_source_fingerprint,
    )


def evaluate_release_gate(
    phase0: Mapping[str, Any],
    phase_gates: Mapping[str, Any] | None,
    e3: Mapping[str, Any] | None,
    *,
    repo_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    expected_source_fingerprint: str | None = None,
    source_reader: Callable[[Path], bytes] | None = None,
) -> dict[str, Any]:
    attestation = None
    if repo_root is not None:
        attestation = attest_phase0_from_repo(
            repo_root,
            environ=_copy_environ(environ),
            source_reader=source_reader,
        )
    return _assemble_release(
        phase0,
        phase_gates,
        e3,
        attestation=attestation,
        expected_source_fingerprint=expected_source_fingerprint,
    )


def _assemble_release(
    phase0: Mapping[str, Any],
    phase_gates: Mapping[str, Any] | None,
    e3: Mapping[str, Any] | None,
    *,
    attestation: Mapping[str, Any] | None,
    expected_source_fingerprint: str | None,
) -> dict[str, Any]:
    extras: list[tuple[str, str, str, dict[str, Any]]] = []

    def add_attestation(blocker_id: str, code: str, details: Mapping[str, Any]) -> None:
        extras.append((blocker_id, BLOCKER_CLASS_PHASE0_ATTESTATION, code, dict(details)))

    validation_codes = phase0_result_validation_codes(phase0)
    phase0_structurally_verified = not validation_codes
    if phase0_structurally_verified:
        caller_obj = phase0_projection(phase0)
        inherited_reasons = list(caller_obj["reasons"])
        phase0_pass = caller_obj["phase0_pass"] is True
        phase0_obj = caller_obj
    else:
        phase0_obj = dict(UNVERIFIED_PHASE0)
        inherited_reasons = []
        phase0_pass = False
        add_attestation(
            PHASE0_NOT_VERIFIED,
            CODE_PHASE0_NOT_VERIFIED,
            {"failure_codes": list(validation_codes)},
        )

    bound = False
    computed_fingerprint: str | None = None
    if attestation is not None:
        att_ok = _attestation_is_canonical(attestation)
        computed_fingerprint = attestation.get("source_fingerprint") if isinstance(attestation, Mapping) else None
        if not _is_fingerprint(computed_fingerprint):
            computed_fingerprint = None
        if att_ok:
            canonical_obj = phase0_projection(attestation["phase0"])
            if phase0_structurally_verified:
                if phase0_obj != canonical_obj:
                    add_attestation(
                        PHASE0_NOT_CANONICAL,
                        CODE_PHASE0_NOT_CANONICAL,
                        {
                            "caller_phase0_pass": phase0_obj["phase0_pass"],
                            "canonical_phase0_pass": canonical_obj["phase0_pass"],
                        },
                    )
            else:
                add_attestation(
                    PHASE0_NOT_CANONICAL,
                    CODE_PHASE0_NOT_CANONICAL,
                    {"failure_codes": list(validation_codes)},
                )
            if attestation.get("attested") is not True:
                add_attestation(
                    PHASE0_SOURCE_CHANGED,
                    CODE_PHASE0_SOURCE_CHANGED,
                    {
                        "failure_codes": list(attestation.get("failure_codes") or []),
                        "changed_paths": list(attestation.get("changed_paths") or []),
                        "unreadable_paths": list(attestation.get("unreadable_paths") or []),
                    },
                )
            phase0_obj = canonical_obj
            inherited_reasons = list(canonical_obj["reasons"])
            phase0_pass = canonical_obj["phase0_pass"] is True
            extra_attestation_ids = {row[0] for row in extras}
            bound = (
                phase0_structurally_verified
                and attestation.get("attested") is True
                and PHASE0_NOT_CANONICAL not in extra_attestation_ids
                and PHASE0_SOURCE_CHANGED not in extra_attestation_ids
            )
        else:
            add_attestation(
                PHASE0_NOT_CANONICAL,
                CODE_PHASE0_NOT_CANONICAL,
                {"failure_codes": ["ATTESTATION_INVALID"]},
            )
        caller_fp = phase0.get("source_fingerprint") if isinstance(phase0, Mapping) else None
        fingerprint_ok = True
        if expected_source_fingerprint is not None:
            if expected_source_fingerprint != computed_fingerprint:
                fingerprint_ok = False
        if _non_empty_str(caller_fp) and caller_fp != computed_fingerprint:
            fingerprint_ok = False
        if not fingerprint_ok:
            bound = False
            add_attestation(
                PHASE0_FINGERPRINT_MISMATCH,
                CODE_PHASE0_FINGERPRINT_MISMATCH,
                {
                    "expected": expected_source_fingerprint,
                    "computed": computed_fingerprint,
                },
            )
    else:
        if expected_source_fingerprint is not None:
            add_attestation(
                PHASE0_FINGERPRINT_MISMATCH,
                CODE_PHASE0_FINGERPRINT_MISMATCH,
                {"expected": expected_source_fingerprint, "computed": None},
            )
        if phase0_structurally_verified and phase0_pass:
            add_attestation(
                PHASE0_SOURCE_UNBOUND,
                CODE_PHASE0_SOURCE_UNBOUND,
                {"reason": "release_ready requires canonical Phase 0 inputs"},
            )

    gates_in = phase_gates if isinstance(phase_gates, Mapping) else {}
    normalized_gates: dict[str, dict[str, Any]] = {}
    for phase_id in PHASE_IDS:
        raw = gates_in.get(phase_id)
        missing = phase_id not in gates_in
        normalized = _normalized_phase_state(raw if isinstance(raw, Mapping) else None)
        normalized_gates[phase_id] = normalized
        if missing or not _phase_passes(phase_id, raw if isinstance(raw, Mapping) else None):
            extras.append(
                (
                    f"{phase_id}_not_passed",
                    BLOCKER_CLASS_PHASE_GATES,
                    CODE_PHASE_GATE_NOT_PASSED,
                    {
                        "phase": phase_id,
                        "state": normalized["state"],
                        "evidence_level": normalized["evidence_level"],
                        "exit_criteria_passed": normalized["exit_criteria_passed"],
                        "schema": "MISSING" if missing else "PRESENT",
                    },
                )
            )

    e3_missing = not isinstance(e3, Mapping)
    e3_norm = _normalized_e3_state(e3)
    if e3_missing or not _e3_passes(e3):
        extras.append(
            (
                "e3_not_verified",
                BLOCKER_CLASS_E3,
                CODE_E3_NOT_VERIFIED,
                {
                    "state": e3_norm["state"],
                    "evidence_level": e3_norm["evidence_level"],
                    "frozen_four_repo_pins": e3_norm["frozen_four_repo_pins"],
                    "cross_repo_integration_passed": e3_norm["cross_repo_integration_passed"],
                    "phase_7_exit_criteria_passed": e3_norm["phase_7_exit_criteria_passed"],
                    "schema": "MISSING" if e3_missing else "PRESENT",
                },
            )
        )

    sink = _ReleaseSink()
    for row in inherited_reasons:
        if not isinstance(row, Mapping):
            continue
        details = row.get("details")
        sink.add(
            str(row.get("blocker_id")),
            str(row.get("blocker_class")),
            str(row.get("code")),
            details if isinstance(details, Mapping) else {},
        )
    extra_ids = [blocker_id for blocker_id, _cls, _code, _details in extras]
    for blocker_id, blocker_class, code, details in extras:
        sink.add(blocker_id, blocker_class, code, details)
    blocker_ids, blocker_classes, reasons = sink.assembled()
    release_ready = bound and phase0_structurally_verified and phase0_pass and not extra_ids
    return {
        "schema_version": SCHEMA_VERSION,
        "evaluator": EVALUATOR_ID,
        "phase0": phase0_obj,
        "phase_gates": normalized_gates,
        "e3": e3_norm,
        "release_ready": release_ready,
        "would_pass": release_ready,
        "blocker_ids": blocker_ids,
        "blocker_classes": blocker_classes,
        "reasons": reasons,
    }


def release_result_validation_codes(result: object) -> list[str]:
    codes: list[str] = []
    if not isinstance(result, Mapping):
        return ["RELEASE_RESULT_NOT_OBJECT"]
    if result.get("schema_version") != SCHEMA_VERSION:
        codes.append("RELEASE_SCHEMA_VERSION_INVALID")
    if result.get("evaluator") != EVALUATOR_ID:
        codes.append("RELEASE_EVALUATOR_INVALID")
    if not _is_bool(result.get("release_ready")):
        codes.append("RELEASE_READY_TYPE_INVALID")
    if result.get("would_pass") is not result.get("release_ready"):
        codes.append("RELEASE_WOULD_PASS_MISMATCH")
    ids = result.get("blocker_ids")
    classes = result.get("blocker_classes")
    reasons = result.get("reasons")
    ids_ok = isinstance(ids, list) and all(_non_empty_str(item) for item in ids)
    classes_ok = isinstance(classes, list) and all(_allowed_token(item, RELEASE_BLOCKER_CLASS_ORDER) for item in classes)
    reasons_ok = isinstance(reasons, list)
    if not ids_ok:
        codes.append("RELEASE_BLOCKER_IDS_INVALID")
    if not classes_ok:
        codes.append("RELEASE_BLOCKER_CLASSES_INVALID")
    if not reasons_ok:
        codes.append("RELEASE_REASONS_INVALID")
    if ids_ok and len(ids) != len(set(ids)):
        codes.append("RELEASE_BLOCKER_ID_DUPLICATE")
    if classes_ok:
        expected_classes = [cls for cls in RELEASE_BLOCKER_CLASS_ORDER if cls in set(classes)]
        if list(classes) != expected_classes:
            codes.append("RELEASE_CLASS_ORDER_INVALID")
    if ids_ok and reasons_ok:
        if len(ids) != len(reasons):
            codes.append("RELEASE_REASON_ALIGNMENT_INVALID")
        else:
            reason_classes: list[str] = []
            for blocker_id, reason in zip(ids, reasons):
                if not isinstance(reason, Mapping):
                    codes.append("RELEASE_REASONS_INVALID")
                    break
                if set(reason) != {"blocker_id", "blocker_class", "code", "details"}:
                    codes.append("RELEASE_REASONS_INVALID")
                    break
                if reason.get("blocker_id") != blocker_id:
                    codes.append("RELEASE_REASON_ALIGNMENT_INVALID")
                    break
                if not _allowed_token(reason.get("blocker_class"), RELEASE_BLOCKER_CLASS_ORDER):
                    codes.append("RELEASE_REASONS_INVALID")
                    break
                if not _allowed_token(reason.get("code"), RELEASE_REASON_CODES):
                    codes.append("RELEASE_REASONS_INVALID")
                    break
                if not isinstance(reason.get("details"), Mapping):
                    codes.append("RELEASE_REASONS_INVALID")
                    break
                reason_classes.append(str(reason.get("blocker_class")))
            else:
                projected = [cls for cls in RELEASE_BLOCKER_CLASS_ORDER if cls in set(reason_classes)]
                if classes_ok and list(classes) != projected:
                    codes.append("RELEASE_REASON_ALIGNMENT_INVALID")
                grouped = list(reason_classes)
                if grouped != sorted(grouped, key=lambda item: RELEASE_BLOCKER_CLASS_ORDER.index(item)):
                    codes.append("RELEASE_CLASS_ORDER_INVALID")
    empty = ids_ok and reasons_ok and classes_ok and ids == [] and classes == [] and reasons == []
    if _is_bool(result.get("release_ready")) and (result.get("release_ready") is True) != empty:
        codes.append("RELEASE_READY_CONTRADICTS_BLOCKERS")
    if "phase0" not in result:
        codes.append("RELEASE_PHASE0_PROJECTION_MISSING")
    else:
        phase0_obj = result.get("phase0")
        if not isinstance(phase0_obj, Mapping) or phase0_result_validation_codes(phase0_obj):
            codes.append("RELEASE_PHASE0_PROJECTION_INVALID")
    if "phase_gates" not in result:
        codes.append("RELEASE_PHASE_GATES_MISSING")
    elif not _release_phase_gates_structurally_valid(result.get("phase_gates")):
        codes.append("RELEASE_PHASE_GATES_INVALID")
    if "e3" not in result:
        codes.append("RELEASE_E3_MISSING")
    elif not _release_e3_structurally_valid(result.get("e3")):
        codes.append("RELEASE_E3_INVALID")
    ordered: list[str] = []
    seen_codes: set[str] = set()
    for code in RELEASE_RESULT_CODES:
        if code in codes and code not in seen_codes:
            ordered.append(code)
            seen_codes.add(code)
    return ordered


def release_record_consistency_errors(
    recorded_release_gate: Mapping[str, Any],
    evaluated_release_gate: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(recorded_release_gate, Mapping):
        return ["release_gate is not an object"]
    if not isinstance(evaluated_release_gate, Mapping):
        return ["evaluated release_gate is not an object"]
    evaluated = dict(evaluated_release_gate)
    recorded = dict(recorded_release_gate)
    if recorded != evaluated:
        for key in (
            "schema_version",
            "evaluator",
            "phase0",
            "phase_gates",
            "e3",
            "release_ready",
            "would_pass",
            "blocker_ids",
            "blocker_classes",
            "reasons",
        ):
            if recorded.get(key) != evaluated.get(key):
                errors.append(f"release_gate.{key} does not exactly equal evaluator output")
        extra = [key for key in recorded if key not in evaluated]
        missing = [key for key in evaluated if key not in recorded]
        if extra:
            errors.append(f"release_gate has unmodeled keys {extra}")
        if missing:
            errors.append(f"release_gate missing keys {missing}")
        if not errors:
            errors.append("release_gate does not exactly equal evaluator output")
    if recorded.get("would_pass") is not recorded.get("release_ready"):
        errors.append("would_pass must equal release_ready")
    if recorded.get("phase0") != evaluated.get("phase0"):
        errors.append("release_gate.phase0 must equal the canonical Phase 0 projection")
    reasons = recorded.get("reasons")
    if "reasons" in recorded and not isinstance(reasons, list):
        errors.append("release_gate.reasons is not an array")
    elif isinstance(reasons, list) and any(isinstance(row, str) for row in reasons):
        errors.append("release_gate.reasons must be structured objects, not strings")
    for key in ("blocker_ids", "blocker_classes"):
        value = recorded.get(key)
        if key in recorded and not isinstance(value, list):
            errors.append(f"release_gate.{key} is not an array")
    return errors
