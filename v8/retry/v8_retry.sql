-- v8 G7a: known_failure settlement + retry (shared cohort allocation
-- sub-operation, aggregation rules 4/5, retry_stop_reason ordered
-- classification).
--
-- Source of truth: docs/designs/v8-dev.md (frozen spec), digests
-- docs/analysis/v8-impl-digest/s32a-step-session.md (§2.1 aggregation
-- priority + rules 1/2/4/5, §3.2 retry_eligible verbatim, §3.3 retry
-- budget formula, §3.4 retry_stop_reason ordered classification + R-01
-- cache contract, §4.1 step state machine failed_retryable row),
-- s32b-effect-ledger.md (§2.1 retry_cohort_allocation six steps, §2.2
-- retry_effect, §4.1 effect state closure controlled edge
-- failed_retryable -> failed_terminal with audit RETRY_STOPPED_BY_CLOSURE,
-- §4.2 superseded semantics, §4.3 cancel/unknown code map), Conformance
-- items 2/5 (spec section 6, lines 843/845).
--
-- v_complete_effect (v8/effect/v8_effect.sql, edited by this stage) calls
-- v_settle_known_failure below for the known_failure arm it used to refuse
-- with KNOWN_FAILURE_LATER; the function references are resolved at call
-- time, so effect/tools/loop stage databases (which never reach that arm)
-- are unaffected.
--
-- G7a scope guards RETIRED in G12: the cohort authorization check
-- (sub-operation step 3) and the generation check (step 4) are real
-- implementations now (grant/slice pre-locked by the callers in the
-- eight-slot master order; generation read FOR SHARE; denials map to
-- GRANT_DENIED / GENERATION_REVOKED per entry contract).
-- known_cancellation settlement (rule 3, shared cancel closure) was
-- refused CANCEL_LATER in G7a; G8b opens it (v_complete_effect routes the
-- classification to the shared closure sub-operation in
-- v8/cancel/v8_closure.sql) and completes aggregation rule 3 below.
-- recovery takeover (the second cohort allocation entry) is G7b.

-- ---------------------------------------------------------------------------
-- effect_evidence: the control-state persistence carrier for the
-- known_failure dual requirement (s32a §3.5 input contract): a deterministic
-- provider failure receipt AND a persisted no-side-effect proof, BOTH bound
-- to the attested attempt. The completion settlement transaction writes
-- these rows (the completion path IS the provider->worker->control-state
-- persistence path); v_retry_eligible reads them back. Append-only.
-- ---------------------------------------------------------------------------
CREATE TABLE effect_evidence (
    effect_id          uuid NOT NULL REFERENCES effect_requests(effect_id),
    attempt_no         bigint NOT NULL CHECK (attempt_no >= 1),
    evidence_class     text NOT NULL
                       CONSTRAINT effect_evidence_class_check
                       CHECK (evidence_class IN ('failure_receipt',
                                                 'no_side_effect_proof')),
    -- failure_receipt rows: the provider terminal receipt id.
    receipt_id         text,
    -- Canonical text of the persisted evidence component (jsonb ::text is
    -- the deterministic canonical form).
    evidence_canonical text NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (effect_id, attempt_no, evidence_class)
);

CREATE FUNCTION v8_effect_evidence_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'effect_evidence is append-only';
END;
$$;

CREATE TRIGGER trg_effect_evidence_append_only
BEFORE UPDATE OR DELETE ON effect_evidence
FOR EACH ROW EXECUTE FUNCTION v8_effect_evidence_append_only();

-- ---------------------------------------------------------------------------
-- v_retry_eligible — the shared predicate (s32a §3.2, verbatim):
--   retry_eligible(effect) := retry budget available
--       AND retry_class IN {provider_idempotent, verifiable_no_effect}
--       AND corresponding evidence persisted in control state
--   retry budget available <=> attempt_no < max_attempts (effect level,
--   frozen at creation).
-- Authority sources only: the CURRENT attempt row (max attempt_no — the
-- parent snapshot attempt_no is display-only and MUST NOT be judged), the
-- effect row's immutable metadata, and the persisted evidence rows bound to
-- that attempt. grant/slice validity is NOT a predicate input (s32b §2.1
-- step 3); the closure environment is NOT a predicate input.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_retry_eligible(p_effect_id uuid) RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE
    v_class text;
    v_max bigint;
    v_att bigint;
BEGIN
    SELECT er.retry_class, er.max_attempts INTO v_class, v_max
      FROM effect_requests er WHERE er.effect_id = p_effect_id;
    IF v_class IS NULL THEN
        RAISE EXCEPTION 'v8: effect % not found in v_retry_eligible',
            p_effect_id;
    END IF;
    -- Current attempt = the max attempt_no row (attempt authority).
    SELECT max(a.attempt_no) INTO v_att
      FROM effect_attempts a WHERE a.effect_id = p_effect_id;
    IF v_att IS NULL THEN
        RETURN false;  -- no attempt authority row: fail closed
    END IF;
    IF v_att >= v_max THEN
        RETURN false;  -- retry budget exhausted
    END IF;
    IF v_class NOT IN ('provider_idempotent', 'verifiable_no_effect') THEN
        RETURN false;
    END IF;
    -- Corresponding evidence persisted in control state, bound to the
    -- current attempt (both dual-requirement components: the deterministic
    -- failure receipt and the no-side-effect proof — the known_failure
    -- classification itself demanded both, so their persistence is the
    -- faithful "already persisted" reading for both retry classes).
    IF NOT EXISTS (SELECT 1 FROM effect_evidence ee
                    WHERE ee.effect_id = p_effect_id
                      AND ee.attempt_no = v_att
                      AND ee.evidence_class = 'failure_receipt')
       OR NOT EXISTS (SELECT 1 FROM effect_evidence ee
                       WHERE ee.effect_id = p_effect_id
                         AND ee.attempt_no = v_att
                         AND ee.evidence_class = 'no_side_effect_proof') THEN
        RETURN false;
    END IF;
    RETURN true;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_retry_stop_reason — the unique ordered classification function (s32a
-- §3.4, R-01). Closed output set {budget_exhausted, first_attempt_failure,
-- not_retry_eligible}, ordered first-match:
--   1. retry budget exhausted (max_attempts > 1 frozen at creation AND
--      attempt_no >= max_attempts, both effect-level authorities)
--      -> budget_exhausted;
--   2. else never eligible from creation (retry_class=unsafe, or
--      max_attempts=1 = zero retry budget at creation)
--      -> first_attempt_failure;
--   3. else (was creation-eligible but current evidence/conditions fail —
--      evidence not persisted in control state, or the closure environment
--      forbids a new attempt) -> not_retry_eligible.
-- Constraints: an unsafe first failure only ever lands in item 2 (never
-- not_retry_eligible); max_attempts=1 only ever lands in item 2 (never the
-- budget bucket). Inputs are creation-persisted retry_class/max_attempts,
-- the attempt authority row and the persisted evidence — never mutable
-- derived caches (steps.retry_count/max_retries) or the cached
-- retry_stop_reason column itself.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_retry_stop_reason(p_effect_id uuid) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    v_class text;
    v_max bigint;
    v_att bigint;
BEGIN
    SELECT er.retry_class, er.max_attempts INTO v_class, v_max
      FROM effect_requests er WHERE er.effect_id = p_effect_id;
    IF v_class IS NULL THEN
        RAISE EXCEPTION 'v8: effect % not found in v_retry_stop_reason',
            p_effect_id;
    END IF;
    SELECT max(a.attempt_no) INTO v_att
      FROM effect_attempts a WHERE a.effect_id = p_effect_id;
    IF v_att IS NULL THEN
        RAISE EXCEPTION
            'v8: effect % has no attempt authority row in v_retry_stop_reason',
            p_effect_id;
    END IF;
    IF v_max > 1 AND v_att >= v_max THEN
        RETURN 'budget_exhausted';
    END IF;
    IF v_class = 'unsafe' OR v_max = 1 THEN
        RETURN 'first_attempt_failure';
    END IF;
    RETURN 'not_retry_eligible';
END;
$$;

-- ---------------------------------------------------------------------------
-- v_retry_stop_reason_cas — the R-01 classification-output cache contract
-- writer. Every write path that classifies an effect failed_terminal
-- (completion classification, later recovery/repair, the controlled
-- closure edge and the rule-4 residual sibling closure) recomputes the
-- reason from the authoritative inputs and CAS-writes the column:
--   column NULL      -> write the recomputed value;
--   column equal     -> idempotent return, no rewrite;
--   column different -> INFRA_PROTOCOL_VIOLATION, CLOSED NOT ABORTED (G15
--                       D7, ledger A30): the column keeps the original
--                       value, both sides are retained in one
--                       effect_audit row (reason INFRA_PROTOCOL_VIOLATION,
--                       internal_op_kind failure_drain), the function
--                       RETURNS the code instead of raising, and the caller
--                       transaction continues. Re-running the same CAS
--                       writes no second audit row.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_retry_stop_reason_cas(p_effect_id uuid) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text;
    v_existing text;
BEGIN
    v_computed := v_retry_stop_reason(p_effect_id);
    SELECT er.retry_stop_reason INTO v_existing
      FROM effect_requests er WHERE er.effect_id = p_effect_id;
    IF v_existing IS NULL THEN
        UPDATE effect_requests SET retry_stop_reason = v_computed,
                                   updated_at = now()
         WHERE effect_id = p_effect_id;
        RETURN v_computed;
    ELSIF v_existing = v_computed THEN
        RETURN v_computed;
    ELSE
        -- G15 D7 (A30): a CAS mismatch is an INFRA_PROTOCOL_VIOLATION, but
        -- it is NO LONGER a transaction abort. The caller keeps running and
        -- the violation closes as a controlled result: the column keeps its
        -- original value and BOTH sides are retained in effect_audit. The
        -- write is idempotent — re-running the same CAS on the same effect
        -- adds no second audit row.
        IF NOT EXISTS (SELECT 1 FROM effect_audit ea
                        WHERE ea.effect_id = p_effect_id
                          AND ea.reason = 'INFRA_PROTOCOL_VIOLATION') THEN
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id,
                attempt_no, audit_key_kind, audit_key_value,
                result_fingerprint, reason, internal_op_kind,
                parent_command_id, internal_op_ordinal)
            SELECT er.session_id, er.session_id, er.step_id, er.effect_id,
                   er.attempt_no, 'canonical_binding',
                   coalesce(er.retry_stop_reason, '') || '->' || v_computed,
                   v_sha256_hex('retry_stop_reason_cas:' ||
                                p_effect_id::text || ':' ||
                                coalesce(v_existing, '') || ':' || v_computed),
                   'INFRA_PROTOCOL_VIOLATION', 'infra_closure',
                   'v_retry_stop_reason_cas', 0
              FROM effect_requests er WHERE er.effect_id = p_effect_id;
        END IF;
        RETURN 'INFRA_PROTOCOL_VIOLATION';
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_aggregate_step — the shared batch judgment function (s32a §2.1 rules
-- 1-6 over the step's persisted effect state; "the same judgment function
-- as normal completion" for the failure domain and both retry entries).
-- PURE: it derives and writes nothing (the virtual-aggregation step of
-- retry_cohort_allocation calls it for permission only). Rules evaluated
-- in the frozen priority
--   unknown > pending > cancel > failed_terminal > failed_retryable
--   > success
-- (rule 3 cancel closure completed by G8b below).
--
-- rule_no 1: any unknown_outcome sibling ->
--           step blocked_unknown_effect / UNKNOWN_AFTER_DISPATCH,
--           session blocked_unknown_effect.
-- rule_no 2: any pending sibling -> step waiting_effect (sticky latch set:
--           step cancel_requested — cancel waiting, never new work),
--           session waiting_effect.
-- rule_no 3 (G8b): cancel closure — sticky latch set, or a non-local
--           cancellation sibling, and no unknown/pending sibling:
--           cancel-wins. step/session cancelled; the step outcome_code comes
--           from the frozen derivation table (sticky family: CANCELLED_BY_
--           REQUEST, or FAILED_TERMINAL_CANCELLED when a failed_terminal
--           sibling exists; provider family: CANCELLED_BY_PROVIDER /
--           FAILED_TERMINAL_PROVIDER_CANCELLED), session cancelled with the
--           matching failure_code. closure_effect_ids = the residual
--           failed_retryable siblings (the applier runs the shared cancel
--           closure sub-operation over them).
-- rule_no 4: any failed_terminal sibling OR a failed_retryable sibling
--           failing the defensive retry_eligible re-evaluation ->
--           closure_effect_ids = ALL remaining failed_retryable siblings
--           (the full residual set), step failed_terminal, session failed,
--           code derived uniquely from the batch terminal-failure
--           retry_stop_reason set: any not_retry_eligible or
--           first_attempt_failure -> FAILED_TERMINAL (a coexisting
--           budget_exhausted does not change it); otherwise (all
--           budget_exhausted) -> FAILED_RETRY_BUDGET_EXHAUSTED.
-- rule_no 5: only eligible failed_retryable siblings ->
--           step failed_retryable / FAILED_RETRYABLE, session ready.
-- rule_no 6: no unknown/pending/failure siblings (the success arms own
--           the decision_only / final_tools handling; retry paths can
--           never hit it).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_aggregate_step(p_step_id uuid)
RETURNS TABLE(rule_no int, step_status text, outcome_code text,
              session_state text, failure_code text,
              closure_effect_ids uuid[])
LANGUAGE plpgsql AS $$
DECLARE
    v_pending bigint;
    v_unknown bigint;
    v_fterm bigint;
    v_fretry bigint;
    v_bad uuid[];
    v_closure uuid[];
    v_reasons text[];
    v_member uuid;
    v_code text;
    v_latch bigint;
    v_sticky boolean;
    v_any_cancel boolean;
    v_cancel_codes text[];
BEGIN
    SELECT count(*) FILTER (WHERE er.status IN
                                ('planned', 'ready', 'dispatch_started')),
           count(*) FILTER (WHERE er.status = 'unknown_outcome'),
           count(*) FILTER (WHERE er.status = 'failed_terminal'),
           count(*) FILTER (WHERE er.status = 'failed_retryable')
      INTO v_pending, v_unknown, v_fterm, v_fretry
      FROM effect_requests er WHERE er.step_id = p_step_id;

    IF v_unknown > 0 THEN
        RETURN QUERY SELECT 1, 'blocked_unknown_effect'::text,
                           'UNKNOWN_AFTER_DISPATCH'::text,
                           'blocked_unknown_effect'::text, NULL::text,
                           ARRAY[]::uuid[];
        RETURN;
    END IF;
    IF v_pending > 0 THEN
        -- rule 2: a pending sibling keeps the batch waiting; under the
        -- sticky latch the step waits for cancellation (cancel_requested),
        -- never for new work (§2.1 rule 2 sticky branch).
        SELECT s.cancellation_epoch INTO v_latch
          FROM steps st JOIN sessions s ON s.session_id = st.session_id
         WHERE st.step_id = p_step_id;
        RETURN QUERY SELECT 2,
            CASE WHEN coalesce(v_latch, 0) > 0 THEN 'cancel_requested'::text
                 ELSE 'waiting_effect'::text END,
            NULL::text, 'waiting_effect'::text, NULL::text,
            ARRAY[]::uuid[];
        RETURN;
    END IF;

    -- rule 3 (G8b): cancel closure. Fires when a cancel signal is present
    -- and no unknown/pending sibling blocks it: either the sticky latch on
    -- the session control row, or a non-local (provider or repair-proved
    -- request) cancellation effect. The sticky family is decided by the
    -- latch OR by a request-family cancel code; the code read is the shared
    -- v_effect_cancel_code map (§4.3). Cancelled siblings cannot exist in
    -- databases that stop before the cancel/repair stages, so the code read
    -- is only reached where the signal exists.
    SELECT s.cancellation_epoch INTO v_latch
      FROM steps st JOIN sessions s ON s.session_id = st.session_id
     WHERE st.step_id = p_step_id;
    SELECT array_agg(er.effect_id ORDER BY er.dispatch_ordinal)
      INTO v_closure
      FROM effect_requests er
     WHERE er.step_id = p_step_id AND er.status = 'cancelled_after_dispatch';
    v_any_cancel := v_closure IS NOT NULL;
    v_sticky := coalesce(v_latch, 0) > 0;
    IF NOT v_sticky AND v_any_cancel THEN
        SELECT array_agg(DISTINCT v_effect_cancel_code(m.eid))
          INTO v_cancel_codes
          FROM unnest(v_closure) AS m(eid);
        v_sticky := EXISTS (
            SELECT 1 FROM unnest(coalesce(v_cancel_codes, ARRAY[]::text[])) c
             WHERE c IN ('CANCELLED_BY_REQUEST_AFTER_DISPATCH',
                         'cancelled_by_request_after_dispatch',
                         'CANCELLED_BY_REQUEST_BEFORE_DISPATCH'));
    END IF;

    IF v_sticky OR v_any_cancel THEN
        -- cancel-wins: step/session terminate cancelled even with a
        -- failed_terminal sibling present; the derivation table fixes both
        -- codes uniquely.
        SELECT array_agg(er.effect_id ORDER BY er.dispatch_ordinal)
          INTO v_closure
          FROM effect_requests er
         WHERE er.step_id = p_step_id AND er.status = 'failed_retryable';
        IF v_sticky THEN
            RETURN QUERY SELECT 3, 'cancelled'::text,
                (CASE WHEN v_fterm > 0 THEN 'FAILED_TERMINAL_CANCELLED'
                      ELSE 'CANCELLED_BY_REQUEST' END)::text,
                'cancelled'::text, 'CANCELLED_BY_REQUEST'::text,
                coalesce(v_closure, ARRAY[]::uuid[]);
        ELSE
            -- A residual failed_retryable sibling is closed to
            -- failed_terminal by the controlled edge inside this same
            -- closure (the G7c reading of the derivation table's
            -- "存在 failed_terminal effect" row: the failure fact is kept in
            -- the step outcome_code).
            RETURN QUERY SELECT 3, 'cancelled'::text,
                (CASE WHEN v_fterm > 0
                        OR coalesce(array_length(v_closure, 1), 0) > 0
                      THEN 'FAILED_TERMINAL_PROVIDER_CANCELLED'
                      ELSE 'CANCELLED_BY_PROVIDER' END)::text,
                'cancelled'::text, 'CANCELLED_BY_PROVIDER'::text,
                coalesce(v_closure, ARRAY[]::uuid[]);
        END IF;
        RETURN;
    END IF;

    -- Defensive retry_eligible re-evaluation of every failed_retryable
    -- sibling (s32a rule 5: normally unreachable, a hit is an
    -- implementation defect and MUST be closed via the controlled edge
    -- with rule-4 semantics).
    IF v_fretry > 0 THEN
        SELECT array_agg(er.effect_id ORDER BY er.dispatch_ordinal)
          INTO v_bad
          FROM effect_requests er
         WHERE er.step_id = p_step_id AND er.status = 'failed_retryable'
           AND NOT v_retry_eligible(er.effect_id);
    END IF;

    IF v_fterm > 0 OR coalesce(array_length(v_bad, 1), 0) > 0 THEN
        -- Rule 4 closes the whole batch: every remaining failed_retryable
        -- sibling settles through the controlled edge (residual eligible
        -- siblings -> not_retry_eligible; defensively ineligible siblings
        -- -> their own ordered classification).
        SELECT array_agg(er.effect_id ORDER BY er.dispatch_ordinal)
          INTO v_closure
          FROM effect_requests er
         WHERE er.step_id = p_step_id AND er.status = 'failed_retryable';

        SELECT array_agg(DISTINCT er.retry_stop_reason)
          INTO v_reasons
          FROM effect_requests er
         WHERE er.step_id = p_step_id AND er.status = 'failed_terminal'
           AND er.retry_stop_reason IS NOT NULL;
        FOREACH v_member IN ARRAY coalesce(v_closure, ARRAY[]::uuid[]) LOOP
            v_reasons := array_append(coalesce(v_reasons, ARRAY[]::text[]),
                                      v_retry_stop_reason(v_member));
        END LOOP;

        IF v_reasons IS NULL OR array_length(v_reasons, 1) IS NULL THEN
            RAISE EXCEPTION
                'INFRA_PROTOCOL_VIOLATION: rule 4 derivation found no '
                'retry_stop_reason set for step % (terminal failure without '
                'a persisted reason)', p_step_id;
        END IF;
        IF EXISTS (SELECT 1 FROM unnest(v_reasons) r
                    WHERE r IN ('not_retry_eligible', 'first_attempt_failure'))
        THEN
            v_code := 'FAILED_TERMINAL';
        ELSIF EXISTS (SELECT 1 FROM unnest(v_reasons) r
                       WHERE r = 'budget_exhausted') THEN
            v_code := 'FAILED_RETRY_BUDGET_EXHAUSTED';
        ELSE
            RAISE EXCEPTION
                'INFRA_PROTOCOL_VIOLATION: rule 4 derivation found an '
                'unknown retry_stop_reason set (%) for step %',
                v_reasons, p_step_id;
        END IF;
        RETURN QUERY SELECT 4, 'failed_terminal'::text, v_code,
                           'failed'::text, v_code,
                           coalesce(v_closure, ARRAY[]::uuid[]);
        RETURN;
    END IF;

    IF v_fretry > 0 THEN
        RETURN QUERY SELECT 5, 'failed_retryable'::text,
                           'FAILED_RETRYABLE'::text, 'ready'::text,
                           NULL::text, ARRAY[]::uuid[];
        RETURN;
    END IF;

    RETURN QUERY SELECT 6, NULL::text, NULL::text, NULL::text, NULL::text,
                       ARRAY[]::uuid[];
END;
$$;

-- ---------------------------------------------------------------------------
-- v_apply_step_aggregation — the shared mutation applier for the failure
-- and cancel domains (used by the known_failure settlement, the rule-4
-- defensive closure of retry_effect, the cancel closure rule 3 and — as the
-- post-allocation final aggregation — the cohort sub-operation). Executes
-- the rule-4 controlled-edge closure for every closure member
-- (failed_retryable -> failed_terminal, the original failure facts kept,
-- audit RETRY_STOPPED_BY_CLOSURE, retry_stop_reason persisted through the
-- R-01 CAS writer) and the rule-3 cancel closure by calling the shared
-- cancel closure sub-operation (G8b; family derived from the derived
-- outcome_code), recomputes the step counters from the effect table and
-- derives the step/session target. A session leaving 'claimed' by the
-- aggregation has its coordination lease revoked and its fence bumped in
-- the same transaction (the settlement paths run from waiting_effect so
-- this is defensive there; retry_effect may run claimed).
-- p_write_session = false lets a caller that owns the session control
-- mutation itself (request_cancel writes the sticky latch before the
-- aggregation and the final state after it) run the step-domain writes
-- only.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_apply_step_aggregation(
    p_session_id uuid, p_step_id uuid,
    p_rule_no int, p_step_status text, p_outcome_code text,
    p_session_state text, p_failure_code text,
    p_closure_effect_ids uuid[],
    p_command_id text, p_audit_key_value text,
    p_write_session boolean DEFAULT true
) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_member uuid;
    v_att bigint;
    v_fingerprint text;
    v_was_claimed boolean;
    v_fence bigint;
BEGIN
    IF p_rule_no = 3 THEN
        -- cancel-wins closure: the family follows the derived table row
        -- (CANCELLED_BY_REQUEST family = the sticky closure; the provider
        -- family closes through the controlled edge).
        PERFORM v_shared_cancel_closure(
            p_session_id, p_step_id, p_command_id, p_audit_key_value,
            CASE WHEN p_outcome_code IN ('CANCELLED_BY_REQUEST',
                                         'FAILED_TERMINAL_CANCELLED',
                                         'CANCELLED_BY_REQUEST_AFTER_DISPATCH')
                 THEN 'sticky' ELSE 'provider' END);
    END IF;
    IF p_rule_no = 4 THEN
        FOREACH v_member IN ARRAY coalesce(p_closure_effect_ids,
                                           ARRAY[]::uuid[]) LOOP
            UPDATE effect_requests SET status = 'failed_terminal',
                                       updated_at = now()
             WHERE effect_id = v_member AND status = 'failed_retryable';
            SELECT max(a.attempt_no) INTO v_att FROM effect_attempts a
             WHERE a.effect_id = v_member;
            UPDATE effect_attempts SET status = 'failed_terminal',
                                       completed_at = now()
             WHERE effect_id = v_member AND attempt_no = v_att
               AND status = 'failed_retryable';
            PERFORM v_retry_stop_reason_cas(v_member);
            SELECT coalesce(er.result_hash,
                            v_sha256_hex(p_command_id || ':' || v_member::text))
              INTO v_fingerprint
              FROM effect_requests er WHERE er.effect_id = v_member;
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id,
                attempt_no, audit_key_kind, audit_key_value,
                result_fingerprint, reason)
            VALUES (p_session_id, p_session_id, p_step_id, v_member, v_att,
                    'canonical_binding', p_audit_key_value, v_fingerprint,
                    'RETRY_STOPPED_BY_CLOSURE')
            ON CONFLICT DO NOTHING;
        END LOOP;
    END IF;

    UPDATE steps st SET
        pending_effect_count = (SELECT count(*) FROM effect_requests er
                                 WHERE er.step_id = st.step_id
                                   AND er.status IN ('planned', 'ready',
                                                     'dispatch_started')),
        unknown_effect_count = (SELECT count(*) FROM effect_requests er
                                 WHERE er.step_id = st.step_id
                                   AND er.status = 'unknown_outcome'),
        retryable_effect_count = (SELECT count(*) FROM effect_requests er
                                   WHERE er.step_id = st.step_id
                                     AND er.status = 'failed_retryable'),
        terminal_effect_count = (SELECT count(*) FROM effect_requests er
                                  WHERE er.step_id = st.step_id
                                    AND er.status IN ('succeeded',
                                                      'failed_terminal',
                                                      'cancelled_before_dispatch',
                                                      'cancelled_after_dispatch')),
        status = p_step_status,
        outcome_code = p_outcome_code,
        closed_at = CASE WHEN p_step_status IN ('succeeded', 'failed_terminal',
                                                'cancelled')
                          AND st.closed_at IS NULL
                         THEN now() ELSE st.closed_at END,
        updated_at = now()
     WHERE st.step_id = p_step_id;

    IF NOT p_write_session THEN
        RETURN;
    END IF;

    SELECT (s.state = 'claimed') INTO v_was_claimed FROM sessions s
     WHERE s.session_id = p_session_id;
    IF p_session_state = 'failed' THEN
        -- fail_session class (1) source (the rule-4 batch): session
        -- failed with the derived code.
        IF v_was_claimed THEN
            SELECT s.session_fence + 1 INTO v_fence FROM sessions s
             WHERE s.session_id = p_session_id;
            UPDATE sessions SET
                state = 'failed', failure_code = p_failure_code,
                session_fence = v_fence,
                lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
                updated_at = now()
             WHERE session_id = p_session_id;
        ELSE
            UPDATE sessions SET state = 'failed',
                                failure_code = p_failure_code,
                                updated_at = now()
             WHERE session_id = p_session_id;
        END IF;
    ELSE
        -- Non-failed targets (rules 1/2/5 -> waiting/blocked/ready with a
        -- NULL code; rule 3 -> cancelled with the cancel-wins code).
        IF v_was_claimed THEN
            SELECT s.session_fence + 1 INTO v_fence FROM sessions s
             WHERE s.session_id = p_session_id;
            UPDATE sessions SET
                state = p_session_state,
                failure_code = p_failure_code,
                session_fence = v_fence,
                lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
                updated_at = now()
             WHERE session_id = p_session_id;
        ELSE
            UPDATE sessions SET state = p_session_state,
                                failure_code = p_failure_code,
                                updated_at = now()
             WHERE session_id = p_session_id;
        END IF;
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_settle_known_failure — the known_failure settlement (called by
-- v_complete_effect after the four-step sequence classified known_failure;
-- the caller holds the session/step/effect/attempt row locks and has
-- passed the structural layer). Settlement order:
--   (1) persist the dual-requirement evidence bound to the settled attempt
--       (the deterministic failure receipt + the no-side-effect proof —
--       the completion transaction IS the control-state persistence path);
--   (2) evaluate the shared retry_eligible predicate (with the evidence
--       rows now visible in this transaction);
--   (3) settle effect+attempt failed_retryable (eligible) or
--       failed_terminal (not eligible — the budget-exhaustion controlled
--       edge: max_attempts=1 -> first_attempt_failure, attempt exhausted
--       -> budget_exhausted, unsafe with budget -> first_attempt_failure)
--       with retry_stop_reason persisted through the R-01 CAS writer; under
--       the G8b sticky latch the shared cancel closure classifies the
--       settlement instead (exit 1/2 — see below);
--   (4) audit a declared-vs-derived outcome mismatch (never rejected);
--   (5) aggregate via the shared judgment + applier (rules 1/2/4/5 — an
--       unknown/pending sibling keeps the settlement settle-only; a
--       failed_terminal sibling closes the residual eligible siblings and
--       derives the step/session terminal failure; a pure eligible batch
--       derives rule 5).
-- No semantic events are generated by a failure settlement (no
-- assistant/message; the turn-end family belongs to the success/unknown/
-- cancel arms and the later repair/cancel milestones).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_settle_known_failure(
    p_session_id uuid, p_command_id text, p_computed text,
    p_step_id uuid, p_effect_id uuid, p_attempt_no bigint,
    p_evidence jsonb, p_result_fingerprint text, p_declared_outcome text,
    p_schema_version text, p_canonicalizer_version text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_class text;
    v_receipt_id text;
    v_elig boolean;
    v_status text;
    v_reason text := NULL;
    v_agg record;
    v_receipt jsonb;
    v_latch bigint;
    v_end jsonb;
    v_events jsonb := '[]'::jsonb;
BEGIN
    -- Defensive: the classifier must reproduce known_failure for this
    -- bound evidence (the caller already ran it; a divergence is an
    -- implementation defect).
    v_class := v_classify_evidence(p_effect_id, p_attempt_no, p_evidence);
    IF v_class <> 'known_failure' THEN
        RAISE EXCEPTION
            'INFRA_PROTOCOL_VIOLATION: v_settle_known_failure called with '
            'evidence classifying % (effect % attempt %)',
            v_class, p_effect_id, p_attempt_no;
    END IF;

    -- (1) dual-requirement persistence, bound to the settled attempt.
    v_receipt_id := p_evidence->'provider_receipt'->>'receipt_id';
    INSERT INTO effect_evidence(
        effect_id, attempt_no, evidence_class, receipt_id,
        evidence_canonical)
    VALUES
        (p_effect_id, p_attempt_no, 'failure_receipt', v_receipt_id,
         (p_evidence->'provider_receipt')::text),
        (p_effect_id, p_attempt_no, 'no_side_effect_proof', NULL,
         (p_evidence->'no_side_effect_proof')::text)
    ON CONFLICT DO NOTHING;

    -- (2) shared predicate (evidence rows visible in this transaction).
    v_elig := v_retry_eligible(p_effect_id);

    -- (3) settlement by the derived result (the declared outcome is an
    -- untrusted worker claim, s32b §5.2). Under the sticky cancel latch the
    -- shared cancel closure sub-operation classifies the settlement: a
    -- retryable (eligible) known failure is a known retryable failure and
    -- closes to cancelled_after_dispatch with the §4.3 request-family code
    -- (exit 1); a non-eligible known failure is a known terminal failure and
    -- keeps failed_terminal with its original failure code (exit 2).
    SELECT s.cancellation_epoch INTO v_latch FROM sessions s
     WHERE s.session_id = p_session_id;
    IF v_elig AND coalesce(v_latch, 0) > 0 THEN
        v_status := 'cancelled_after_dispatch';
        UPDATE effect_requests SET
            status = 'cancelled_after_dispatch',
            result_hash = p_result_fingerprint,
            provider_request_id = v_receipt_id,
            updated_at = now()
         WHERE effect_id = p_effect_id;
        UPDATE effect_attempts SET
            status = 'cancelled_after_dispatch',
            result_hash = p_result_fingerprint,
            provider_request_id = v_receipt_id,
            completed_at = now()
         WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id,
            attempt_no, audit_key_kind, audit_key_value,
            result_fingerprint, reason)
        VALUES (p_session_id, p_session_id, p_step_id, p_effect_id,
                p_attempt_no, 'canonical_binding', p_computed,
                p_result_fingerprint, 'RETRY_SUPPRESSED_BY_CANCEL')
        ON CONFLICT DO NOTHING;
    ELSIF v_elig THEN
        v_status := 'failed_retryable';
        UPDATE effect_requests SET
            status = 'failed_retryable',
            result_hash = p_result_fingerprint,
            provider_request_id = v_receipt_id,
            updated_at = now()
         WHERE effect_id = p_effect_id;
        UPDATE effect_attempts SET
            status = 'failed_retryable',
            result_hash = p_result_fingerprint,
            provider_request_id = v_receipt_id,
            completed_at = now()
         WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;
    ELSE
        v_status := 'failed_terminal';
        UPDATE effect_requests SET
            status = 'failed_terminal',
            result_hash = p_result_fingerprint,
            provider_request_id = v_receipt_id,
            updated_at = now()
         WHERE effect_id = p_effect_id;
        UPDATE effect_attempts SET
            status = 'failed_terminal',
            result_hash = p_result_fingerprint,
            provider_request_id = v_receipt_id,
            completed_at = now()
         WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;
        v_reason := v_retry_stop_reason_cas(p_effect_id);
    END IF;

    -- (4) declared outcome vs derived: audited, never rejected (the audit
    -- row shares the settlement transaction).
    IF p_declared_outcome <> v_status THEN
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id,
            attempt_no, audit_key_kind, audit_key_value,
            result_fingerprint, reason)
        VALUES (p_session_id, p_session_id, p_step_id, p_effect_id,
                p_attempt_no, 'canonical_binding', p_computed,
                p_result_fingerprint, 'RESULT_OUTCOME_MISMATCH')
        ON CONFLICT DO NOTHING;
    END IF;

    -- (5) aggregation (single judgment function + shared applier).
    SELECT * INTO v_agg FROM v_aggregate_step(p_step_id);
    PERFORM v_apply_step_aggregation(
        p_session_id, p_step_id, v_agg.rule_no, v_agg.step_status,
        v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
        v_agg.closure_effect_ids, p_command_id, p_computed);

    -- G8b: when the sticky closure collapsed the session, the canonical
    -- turn/end is derived through the shared derivation (a no-op for the
    -- failure rows — the session is failed/ready, never cancelled).
    v_end := v_derive_cancel_turn_end(p_session_id, p_command_id,
                                      p_schema_version,
                                      p_canonicalizer_version);
    IF v_end IS NOT NULL THEN
        v_events := jsonb_build_array(jsonb_build_object(
            'event_type', 'turn/end', 'seq', v_end->'seq',
            'event_key', v_end->>'event_key', 'reason', v_end->>'reason'));
    END IF;

    v_receipt := jsonb_build_object(
        'command_kind', 'complete_effect',
        'command_id', p_command_id,
        'classification', 'known_failure',
        'effect_id', p_effect_id,
        'attempt_no', p_attempt_no,
        'derived_status', v_status,
        'retry_eligible', v_elig,
        'retry_stop_reason', v_reason,
        'result_hash', p_result_fingerprint,
        'events', v_events,
        'step_status', (SELECT st.status FROM steps st
                         WHERE st.step_id = p_step_id),
        'session_state', (SELECT s.state FROM sessions s
                           WHERE s.session_id = p_session_id),
        'failure_code', (SELECT s.failure_code FROM sessions s
                          WHERE s.session_id = p_session_id));

    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value,
        first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            p_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'complete_effect',
            'canonical_request_hash', p_computed, 'accepted', NULL,
            v_receipt::text, v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_retry_cohort_allocation — the shared batch retry allocation
-- sub-operation (s32b §2.1, six steps in the frozen order; the ONLY
-- successor-attempt creation path — normal retry_effect here, the recovery
-- takeover step 3(c) joins in G7b). The allocation unit is the BATCH cohort
-- (never a single effect). The caller (retry_effect / the later recovery
-- takeover) owns the session/step/effect/attempt row locks and the
-- transaction boundary.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_retry_cohort_allocation(
    p_session_id uuid, p_step_id uuid, p_command_id text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_agg record;
    v_row record;
    v_effects jsonb := '[]'::jsonb;
    v_fence bigint;
    v_new_no bigint;
    v_was_claimed boolean;
    v_new_fence bigint;
    -- G12 cohort gates (3)/(4).
    v_deny text;
    v_denied jsonb;
    v_gen uuid;
    v_gen_status text;
    v_closure jsonb;
BEGIN
    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id;

    -- (1) virtual aggregation (permission judgment only — derives and
    -- writes NO step/session control state; the GENERATION_REVOKED
    -- three-conjunction exception branch is explicitly excluded here, it
    -- belongs to the final aggregations and the offline drain).
    SELECT * INTO v_agg FROM v_aggregate_step(p_step_id);
    IF v_agg.rule_no = 1 OR v_agg.rule_no = 2 THEN
        -- Unknown/pending sibling: rule 5 not hit — no cohort freeze, no
        -- allocation; only settlements already on disk remain (the
        -- retry_effect entry rejects before reaching this point; the
        -- G7b recovery entry settles only).
        RETURN jsonb_build_object('allocated', false, 'rule_no',
                                  v_agg.rule_no, 'reason',
                                  'sibling_unknown_or_pending');
    END IF;
    IF v_agg.rule_no = 4 THEN
        -- Rule 3/4 terminal closure conditions hit: execute the shared
        -- closure WITHOUT allocating (eligible residual siblings close
        -- through the controlled edge; authorization never blocks a
        -- closure).
        PERFORM v_apply_step_aggregation(
            p_session_id, p_step_id, v_agg.rule_no, v_agg.step_status,
            v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
            v_agg.closure_effect_ids, p_command_id, p_command_id);
        RETURN jsonb_build_object('allocated', false, 'rule_no', 4,
                                  'reason', 'batch_terminal_closure',
                                  'closed_effect_ids', v_agg.closure_effect_ids,
                                  'step_status', v_agg.step_status,
                                  'session_state', v_agg.session_state,
                                  'failure_code', v_agg.failure_code);
    END IF;
    IF v_agg.rule_no <> 5 THEN
        RAISE EXCEPTION
            'INFRA_PROTOCOL_VIOLATION: retry_cohort_allocation step 1 '
            'requires virtual rule 5, got rule % for step %',
            v_agg.rule_no, p_step_id;
    END IF;

    -- (2) cohort freeze: the FULL set of failed_retryable effects of the
    -- batch that satisfy retry_eligible (no subsetting — there is no
    -- per-effect allocation variant). The virtual aggregation already
    -- verified that every failed_retryable sibling re-evaluates eligible.
    --
    -- (3) cohort authorization check (G12, real implementation replacing
    -- the G7a always-pass scope guard): re-validate EVERY cohort member's
    -- seal-frozen grants under the §2.1 linearization point. The callers
    -- pre-locked this exact grant/slice set (retry_effect / the recovery
    -- takeover step-1 full prelock), so the judge re-locks only rows
    -- already held by this transaction — no new lock order is introduced.
    -- Any member invalid (or never grant-bound) -> NO allocation, no
    -- attempt_no increment, the whole cohort stays failed_retryable; this
    -- sub-operation writes ZERO control state on this branch and the
    -- entries map the denial per their own contracts (normal entry:
    -- rejected_mismatch GRANT_DENIED with session/lease/fence unchanged;
    -- recovery entry: allocation_denied sub-result + final aggregation).
    v_denied := '[]'::jsonb;
    FOR v_row IN
        SELECT er.effect_id, er.grant_id, er.authz_params,
               er.dispatch_ordinal
          FROM effect_requests er
         WHERE er.step_id = p_step_id AND er.status = 'failed_retryable'
           AND v_retry_eligible(er.effect_id)
         ORDER BY er.dispatch_ordinal
    LOOP
        v_deny := v_gate_revalidate(p_session_id, v_row.grant_id,
                                    v_row.authz_params);
        IF v_deny IS NULL THEN
            v_deny := v_gate_revalidate_authorize(p_session_id,
                                                  v_row.authz_params);
        END IF;
        IF v_deny IS NOT NULL THEN
            v_denied := v_denied || jsonb_build_object(
                'effect_id', v_row.effect_id,
                'grant_id', v_row.grant_id,
                'reason', v_deny);
        END IF;
    END LOOP;
    IF jsonb_array_length(v_denied) > 0 THEN
        RETURN jsonb_build_object('allocated', false,
                                  'reason', 'grant_denied',
                                  'denied', v_denied);
    END IF;
    --
    -- (4) generation check (G12, §4 first-item third gate): the step-bound
    -- catalog generation shared read (the callers pre-locked it FOR
    -- SHARE); already failed -> NO allocation, the post-denial final
    -- aggregation runs in this same transaction through the SHARED
    -- generation closure sub-operation (three-conjunction: close the step
    -- failed_terminal/GENERATION_REVOKED; existing rules finalize first;
    -- unaffected keeps failed_retryable). The entries map the denial:
    -- normal entry -> rejected_mismatch GENERATION_REVOKED receipt; the
    -- recovery entry records allocation_denied: GENERATION_REVOKED.
    SELECT st.catalog_generation INTO v_gen FROM steps st
     WHERE st.step_id = p_step_id;
    IF v_gen IS NOT NULL THEN
        SELECT g.status INTO v_gen_status FROM generations g
         WHERE g.generation_id = v_gen FOR SHARE;
        IF v_gen_status = 'failed' THEN
            v_closure := v_generation_close_step(p_session_id, p_step_id,
                                                 v_gen, p_command_id);
            RETURN jsonb_build_object('allocated', false,
                                      'reason', 'generation_revoked',
                                      'generation_id', v_gen,
                                      'closure', v_closure);
        END IF;
    END IF;
    FOR v_row IN
        SELECT er.effect_id, er.dispatch_ordinal,
               (SELECT max(a.attempt_no) FROM effect_attempts a
                 WHERE a.effect_id = er.effect_id) AS att_no,
               er.request_hash, er.idempotency_key, er.execution_mode
          FROM effect_requests er
         WHERE er.step_id = p_step_id AND er.status = 'failed_retryable'
           AND v_retry_eligible(er.effect_id)
         ORDER BY er.dispatch_ordinal
    LOOP
        -- (5) same-transaction allocation for every cohort member:
        -- attempt_no+1, identity reuse (request_hash/idempotency_key),
        -- execution snapshot re-frozen from the CURRENT session authority
        -- (driver/driver_epoch/session_fence/dispatch_session_fence;
        -- cancellation_epoch is a session-level control field and is never
        -- frozen into attempt rows), a fresh job fence advanced
        -- monotonically and frozen at the same value into
        -- effect.current_job_fence and attempt.dispatch_job_fence, status
        -- ready (no "ready without a new attempt" window — one commit),
        -- and the superseded marker written onto the old attempt
        -- (write-once; the old attempt keeps its own status untouched).
        v_fence := nextval('v8_job_fence_seq');
        v_new_no := v_row.att_no + 1;
        UPDATE effect_requests SET
            status = 'ready',
            attempt_no = v_new_no,
            current_job_fence = v_fence,
            session_fence = v_sess.session_fence,
            dispatch_session_fence = v_sess.session_fence,
            result_hash = NULL,
            provider_request_id = NULL,
            dispatched_at = NULL,
            updated_at = now()
         WHERE effect_id = v_row.effect_id;
        INSERT INTO effect_attempts(
            effect_id, attempt_no, session_id, step_id, driver, driver_epoch,
            session_fence, dispatch_session_fence, dispatch_job_fence,
            request_hash, idempotency_key, execution_mode, status)
        VALUES (
            v_row.effect_id, v_new_no, p_session_id, p_step_id,
            v_sess.driver, v_sess.driver_epoch,
            v_sess.session_fence, v_sess.session_fence, v_fence,
            v_row.request_hash, v_row.idempotency_key,
            v_row.execution_mode, 'ready');
        UPDATE effect_attempts SET superseded_by_attempt_no = v_new_no
         WHERE effect_id = v_row.effect_id AND attempt_no = v_row.att_no
           AND superseded_by_attempt_no IS NULL;
        v_effects := v_effects || jsonb_build_object(
            'effect_id', v_row.effect_id,
            'dispatch_ordinal', v_row.dispatch_ordinal,
            'old_attempt_no', v_row.att_no,
            'attempt_no', v_new_no,
            'job_fence', v_fence);
    END LOOP;

    -- (6) post-allocation final aggregation (the same judgment function
    -- over the final batch state): the cohort is pending again ->
    -- rule 2 -> step and session both waiting_effect. There is NO
    -- post-allocation rule-5 / session-ready exit (rule 5 exists only in
    -- the step-1 permission phase).
    SELECT * INTO v_agg FROM v_aggregate_step(p_step_id);
    IF v_agg.rule_no <> 2 THEN
        RAISE EXCEPTION
            'INFRA_PROTOCOL_VIOLATION: post-allocation aggregation '
            'expected rule 2, got rule % for step %', v_agg.rule_no,
            p_step_id;
    END IF;
    PERFORM v_apply_step_aggregation(
        p_session_id, p_step_id, v_agg.rule_no, v_agg.step_status,
        v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
        v_agg.closure_effect_ids, p_command_id, p_command_id);
    -- Derived retry caches (display/aggregation statistics only, never a
    -- judgment source): retry_count advances with every allocated retry,
    -- max_retries tracks the frozen effect budgets.
    UPDATE steps st SET
        retry_count = st.retry_count + jsonb_array_length(v_effects),
        max_retries = GREATEST(st.max_retries,
            coalesce((SELECT max(er.max_attempts - 1)
                        FROM effect_requests er
                       WHERE er.step_id = st.step_id), 0)),
        updated_at = now()
     WHERE st.step_id = p_step_id;

    v_was_claimed := (v_sess.state = 'claimed');
    IF v_was_claimed THEN
        -- Leaving claimed revokes the coordination lease and bumps the
        -- fence (v_apply_step_aggregation already did the state move and
        -- the lease/fence bookkeeping; the fence value is re-read here
        -- for the receipt).
        SELECT s.session_fence INTO v_new_fence FROM sessions s
         WHERE s.session_id = p_session_id;
    ELSE
        v_new_fence := v_sess.session_fence;
    END IF;

    RETURN jsonb_build_object(
        'allocated', true,
        'rule_no', 2,
        'effects', v_effects,
        'session_fence', v_new_fence,
        'step_status', 'waiting_effect',
        'session_state', 'waiting_effect');
END;
$$;

-- ---------------------------------------------------------------------------
-- v_retry_effect — the public retry command (s32b §2.2; the coordinator
-- entry of the shared sub-operation; the recovery entry joins in G7b).
-- Precondition (frozen as the step-level batch condition): the target
-- effect is failed_retryable and retry_eligible (cohort membership), the
-- step is failed_retryable, and the sub-operation step-1 virtual
-- aggregation hits rule 5. Classified rejections:
--   SIBLING_UNKNOWN / SIBLING_PENDING  the virtual aggregation hit
--         rule 1/2 — zero control state, only the rejection receipt
--         persists; the step keeps its blocked/waiting state.
--   GRANT_DENIED (G12)  the cohort authorization check found a member
--         whose frozen grant/slice is no longer valid — zero control
--         state (session/lease/fence keep their entry values, the whole
--         cohort stays failed_retryable, no attempt is created).
--   GENERATION_REVOKED (G12)  the step-bound generation is failed — the
--         shared post-denial final aggregation runs in the same
--         transaction (three-conjunction closure), the rejection receipt
--         commits with it.
-- The defensive rule-4 case (a failed_retryable sibling failing the
-- retry_eligible re-evaluation — normally unreachable, an implementation
-- defect if seen) executes the budget/closure controlled edge in this
-- transaction: the batch closes through failed_retryable ->
-- failed_terminal with the ordered retry_stop_reason, the step/session
-- terminal failure derivation and the fail_session class (1) source.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_retry_effect(
    p_session_id uuid, p_command_id text, p_effect_id uuid,
    p_driver text, p_driver_epoch bigint, p_session_fence bigint,
    p_declared_hash text, p_payload_canonical text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_step_id uuid;
    v_er effect_requests%ROWTYPE;
    v_att_no bigint;
    v_receipt jsonb;
    v_agg record;
    v_alloc jsonb;
    -- G12 prelock set (grant/slice + generation shared read).
    v_pre_grants text[];
    v_pre_auth text[];
    v_pre_gen uuid;
BEGIN
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'retry_effect',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id
     FOR UPDATE;

    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_stale',
            'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session control row');
        RETURN QUERY SELECT 'rejected_stale'::text, 'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF p_session_fence IS DISTINCT FROM v_sess.session_fence THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_stale',
            'SESSION_FENCE_STALE',
            format('expected session_fence %s does not match current %s',
                   coalesce(p_session_fence::text, 'NULL'),
                   v_sess.session_fence));
        RETURN QUERY SELECT 'rejected_stale'::text, 'SESSION_FENCE_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.state IN ('completed', 'failed', 'cancelled') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_mismatch',
            'SESSION_TERMINAL',
            format('retry on a terminal session (state %s)', v_sess.state));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_TERMINAL'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.cancellation_epoch > 0 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_mismatch',
            'CANCEL_STICKY',
            'sticky cancel latch set: no retry after cancel');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'CANCEL_STICKY'::text, v_receipt;
        RETURN;
    END IF;
    -- Locate (lockless read of the immutable association), then lock in
    -- the master order: step -> effect -> attempt.
    SELECT er.step_id INTO v_step_id FROM effect_requests er
     WHERE er.effect_id = p_effect_id;
    IF NOT FOUND THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_mismatch',
            'EFFECT_NOT_FOUND', 'effect_id is not persisted');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EFFECT_NOT_FOUND'::text, v_receipt;
        RETURN;
    END IF;

    -- G12: eight-slot master order — the grant/slice locks (authorization
    -- linearization point) and the generation shared read are taken BEFORE
    -- the step/effect/attempt locks below. The pre-locked grant set covers
    -- EVERY frozen grant of the located step's effects (the cohort plus
    -- eligible siblings, matching the recovery takeover's step-1 full
    -- prelock); the cohort sub-operation step (3) re-judges under these
    -- held locks and never takes a grant lock out of order.
    SELECT array_agg(DISTINCT er.grant_id) INTO v_pre_grants
      FROM effect_requests er
     WHERE er.step_id = v_step_id AND er.grant_id IS NOT NULL;
    IF v_pre_grants IS NOT NULL THEN
        PERFORM lj.grant_id FROM v_grant_lock_judge(
            p_session_id, v_pre_grants, 'effect_submit',
            NULL, NULL, NULL, NULL) lj;
    END IF;
    SELECT array_agg(DISTINCT er.authz_params->>'authorize_grant_id')
      INTO v_pre_auth
      FROM effect_requests er
     WHERE er.step_id = v_step_id
       AND er.authz_params->>'authorize_grant_id' IS NOT NULL;
    IF v_pre_auth IS NOT NULL THEN
        PERFORM lj.grant_id FROM v_grant_lock_judge(
            p_session_id, v_pre_auth, 'authorize_effect',
            NULL, NULL, NULL, NULL) lj;
    END IF;
    SELECT st.catalog_generation INTO v_pre_gen FROM steps st
     WHERE st.step_id = v_step_id;
    IF v_pre_gen IS NOT NULL THEN
        PERFORM 1 FROM generations g
         WHERE g.generation_id = v_pre_gen FOR SHARE;
    END IF;

    PERFORM 1 FROM steps st WHERE st.step_id = v_step_id FOR UPDATE;
    SELECT * INTO v_er FROM effect_requests er
     WHERE er.effect_id = p_effect_id FOR UPDATE;
    IF v_er.session_id IS DISTINCT FROM p_session_id THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_mismatch',
            'EFFECT_NOT_FOUND',
            'effect_id does not belong to this session');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EFFECT_NOT_FOUND'::text, v_receipt;
        RETURN;
    END IF;
    IF v_er.status <> 'failed_retryable' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_mismatch',
            'EFFECT_NOT_RETRYABLE',
            format('retry requires effect status=failed_retryable, got %s',
                   v_er.status));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EFFECT_NOT_RETRYABLE'::text, v_receipt;
        RETURN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM steps st
                    WHERE st.step_id = v_step_id
                      AND st.status = 'failed_retryable') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_mismatch',
            'STEP_NOT_RETRYABLE',
            format('retry requires step status=failed_retryable, got %s',
                   (SELECT st.status FROM steps st WHERE st.step_id = v_step_id)));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'STEP_NOT_RETRYABLE'::text, v_receipt;
        RETURN;
    END IF;
    SELECT max(a.attempt_no) INTO v_att_no FROM effect_attempts a
     WHERE a.effect_id = p_effect_id;
    PERFORM 1 FROM effect_attempts a
     WHERE a.effect_id = p_effect_id AND a.attempt_no = v_att_no FOR UPDATE;
    IF v_sess.state NOT IN ('ready', 'claimed') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_mismatch',
            'SESSION_NOT_RETRYABLE',
            format('retry_effect requires session state ready or claimed, got %s',
                   v_sess.state));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_NOT_RETRYABLE'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.state = 'claimed' AND (v_sess.lease_owner IS NULL
       OR v_sess.lease_until IS NULL OR v_sess.lease_until <= now()) THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_stale', 'LEASE_NOT_HELD',
            'claimed-state retry requires a live coordination lease');
        RETURN QUERY SELECT 'rejected_stale'::text, 'LEASE_NOT_HELD'::text, v_receipt;
        RETURN;
    END IF;

    -- Batch precondition (sub-operation step 1, same judgment function).
    SELECT * INTO v_agg FROM v_aggregate_step(v_step_id);
    IF v_agg.rule_no = 1 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_mismatch',
            'SIBLING_UNKNOWN',
            'an unknown_outcome sibling blocks the batch: no rule-5 cohort');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SIBLING_UNKNOWN'::text, v_receipt;
        RETURN;
    END IF;
    IF v_agg.rule_no = 2 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'retry_effect', v_computed, 'rejected_mismatch',
            'SIBLING_PENDING',
            'a pending sibling keeps the batch waiting: no rule-5 cohort');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SIBLING_PENDING'::text, v_receipt;
        RETURN;
    END IF;
    IF v_agg.rule_no = 4 THEN
        -- Defensive controlled edge (normally unreachable: a persisted
        -- failed_retryable that fails the eligibility re-evaluation).
        PERFORM v_apply_step_aggregation(
            p_session_id, v_step_id, v_agg.rule_no, v_agg.step_status,
            v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
            v_agg.closure_effect_ids, p_command_id, v_computed);
        v_receipt := jsonb_build_object(
            'command_kind', 'retry_effect',
            'command_id', p_command_id,
            'effect_id', p_effect_id,
            'allocated', false,
            'closed_effect_ids', v_agg.closure_effect_ids,
            'step_status', v_agg.step_status,
            'session_state', v_agg.session_state,
            'failure_code', v_agg.failure_code);
        INSERT INTO command_bindings(
            session_id, command_id, first_key_kind, first_key_value,
            first_outcome)
        VALUES (p_session_id, p_command_id, 'canonical_request_hash',
                v_computed, 'accepted');
        INSERT INTO command_receipts(
            session_id, command_id, command_kind, receipt_key_kind,
            receipt_key_value, outcome, code, result_canonical,
            result_hash)
        VALUES (p_session_id, p_command_id, 'retry_effect',
                'canonical_request_hash', v_computed, 'accepted', NULL,
                v_receipt::text, v_sha256_hex(v_receipt::text));
        RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
        RETURN;
    END IF;
    IF v_agg.rule_no <> 5 THEN
        RAISE EXCEPTION
            'INFRA_PROTOCOL_VIOLATION: retry_effect batch precondition '
            'expected rule 5, got rule % (step %)', v_agg.rule_no, v_step_id;
    END IF;

    -- Rule 5 + cohort membership: allocate through the shared
    -- sub-operation (the only successor-attempt creation path).
    v_alloc := v_retry_cohort_allocation(p_session_id, v_step_id,
                                         p_command_id);
    IF NOT (v_alloc->>'allocated')::boolean THEN
        -- G12: the cohort gates deny with their own classified receipts.
        -- grant_denied: zero control-state change (the sub-operation wrote
        -- nothing) — session stays claimed/ready, the coordination lease
        -- is not implicitly released, the fence is not bumped, every
        -- cohort member (and any initial ready effect) keeps its state.
        -- generation_revoked: the post-denial final aggregation already
        -- ran inside the sub-operation (shared generation closure) and
        -- commits together with this rejection receipt (spec receipt-rule
        -- exception for the step-4 generation denial).
        IF v_alloc->>'reason' = 'grant_denied' THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id,
                'retry_effect', v_computed, 'rejected_mismatch',
                'GRANT_DENIED',
                format('cohort authorization check failed for %s member(s): %s',
                       jsonb_array_length(v_alloc->'denied'),
                       (v_alloc->'denied'->0->>'reason')));
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'GRANT_DENIED'::text, v_receipt;
            RETURN;
        END IF;
        IF v_alloc->>'reason' = 'generation_revoked' THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id,
                'retry_effect', v_computed, 'rejected_mismatch',
                'GENERATION_REVOKED',
                'cohort generation check: the step-bound catalog generation is failed');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'GENERATION_REVOKED'::text, v_receipt;
            RETURN;
        END IF;
        RAISE EXCEPTION
            'INFRA_PROTOCOL_VIOLATION: retry_cohort_allocation declined '
            'after a rule-5 precondition (step %): %', v_step_id, v_alloc;
    END IF;

    v_receipt := jsonb_build_object(
        'command_kind', 'retry_effect',
        'command_id', p_command_id,
        'effect_id', p_effect_id) || v_alloc;

    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value,
        first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'retry_effect',
            'canonical_request_hash', v_computed, 'accepted', NULL,
            v_receipt::text, v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;
