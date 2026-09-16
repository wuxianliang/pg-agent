-- v8 G15: failure-drain — §3.1.1 `fail_session` class (3) INFRA closure.
--
-- Source of truth: docs/designs/v8-dev.md §3.1.1 (the three closed sources
-- of `N -> failed`; class (3) = the infrastructure failure closed set
-- {INFRA_ASSEMBLY_FAILED, INFRA_PROTOCOL_VIOLATION}), §2.2 item 3
-- (WORKSPACE_LOST fail-closed — the shape class (3) is "同构" with), and the
-- §3.2.1 derivation table (the two INFRA rows).
--
-- This file is the drain stage's artifact. The shared deterministic drain
-- core (v_failure_drain_core) and the class (3) closure used by the
-- completion path (v_infra_closure_effect) live in grant/v8_grant.sql
-- (position 3) because effect/v8_effect.sql — loaded at position 7, i.e.
-- BEFORE this file — MUST be able to take the same-transaction INFRA
-- closure on a DECISION_PLAN_INVALID rejection, and an effect-stage database
-- does not include this file. Function bodies are late-bound, so a lower
-- stage may freely reference objects that only exist in higher stages.
-- Keeping ONE implementation in the lowest file every consumer can see
-- avoids the dual-implementation divergence the ledger flags elsewhere
-- (A68/A73).
--
-- Contract (§3.1.1 class (3), the verbatim shape of §2.2 item 3):
--   * session -> failed / failure_code = the given INFRA code, immediately,
--     in the same control transaction (fence bumped, coordination lease
--     revoked, active_step_id cleared);
--   * un-dispatched `ready` effects -> cancelled_before_dispatch (shared
--     pre-dispatch dual-table atomic sync);
--   * in-flight effects follow the three drain branches (unknown / pending /
--     neither) and settle later through completion / repair / reconcile;
--   * an unfinished step -> failed_terminal / <the INFRA code>;
--   * an already-terminal step keeps its outcome_code;
--   * an already-terminal SESSION is never overwritten (G15 D5
--     parent-layer cause priority).
-- Public callers MUST NOT supply an arbitrary failure_code: only the closed
-- set is accepted; anything else is a stable rejection with zero control
-- state.

-- ---------------------------------------------------------------------------
-- 1. v_fail_session — the controlled class (3) INFRA closure entry
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_fail_session(
    p_session_id uuid, p_failure_code text, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT v_infra_failure_code_ok(p_failure_code) THEN
        RETURN jsonb_build_object(
            'outcome', 'rejected_mismatch',
            'code', 'FAILURE_CODE_INVALID',
            'detail', 'fail_session class (3) accepts only the closed INFRA '
                      'set {INFRA_ASSEMBLY_FAILED, INFRA_PROTOCOL_VIOLATION}');
    END IF;
    RETURN v_failure_drain_core(p_session_id, p_failure_code, p_reason,
                                'infra:' || p_failure_code, 'infra_drain');
END;
$$;
