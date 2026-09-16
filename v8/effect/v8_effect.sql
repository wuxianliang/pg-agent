-- v8 G4: effect state machine — claim/yield CAS, initial decision seal
-- (v_prepare_step), dispatch gate, complete_effect (two-layer validation +
-- four-step sequence; P0B non-streaming terminal path), the unique evidence
-- classification function, the shared turn-close judgment (rule 6 and
-- finish_session), and finish_session.
--
-- Source of truth: docs/designs/v8-dev.md (frozen spec), digests
-- docs/analysis/v8-impl-digest/s31a-identity-commands.md (§2.2 create_step
-- contract, §2.3 claim CAS, §2.11 controlled service transactions, §4.3
-- transition-table core rows), s31b-command-table.md (§2.6.1 initial
-- decision seal eight steps — implemented in order below, §2.7 permission
-- matrix: assistant/message is SQL-generated only), s32a-step-session.md
-- (§2.1 aggregation priority + rules 1/2/6, §3.5 evidence classification),
-- s32b-effect-ledger.md (§2.4 create_effect_in_seal, §2.5 dispatch gate,
-- §2.6 complete_effect, §3.1 dual fence, §5 EffectResult ABI),
-- s32c-completion-evidence.md (§2.1 semantic-layer entry).
--
-- Transaction boundaries are owned by the CALLER (same convention as G3):
-- the Python client runs gate + business function + commit in one
-- transaction, so receipts, control mutations and events commit together.
--
-- P0B scope guards (explicit, [LATER] in the digests): grant model /
-- generation gates are absent; retry/cohort, cancel, repair, quiescing and
-- streaming grammar are not implemented. known_failure and
-- known_cancellation keep their classification rows in v_classify_evidence
-- (the frozen decision table is implemented whole) but are refused at
-- settlement with stable codes.

-- Job fence allocator: every attempt creation (seal here, cohort allocation
-- later) draws a fresh monotonically increasing fence; the value is frozen
-- into effect.current_job_fence and attempt.dispatch_job_fence identically.
CREATE SEQUENCE v8_job_fence_seq AS bigint START WITH 1;

-- ---------------------------------------------------------------------------
-- claim / recovery_claim / yield — coordination lease CAS (s31a §2.3/§2.4).
-- These are lease operations, not receipt commands (not in the frozen
-- command list), so they return a plain jsonb result instead of a receipt.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_claim_session(
    p_session_id uuid, p_driver text, p_driver_epoch bigint,
    p_lease_owner text, p_lease_seconds int,
    p_expected_session_fence bigint DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_fence bigint;
BEGIN
    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v8: session % not found', p_session_id;
    END IF;
    -- Envelope driver/epoch must match the control row (epoch advance is a
    -- finish_switch concern, LATER). IS DISTINCT FROM: a NULL envelope leg
    -- (omitted field) fails closed as a mismatch, never a silent pass.
    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        RETURN jsonb_build_object('outcome', 'rejected_stale',
                                  'code', 'DRIVER_EPOCH_MISMATCH');
    END IF;
    -- Optional old-fence CAS: NULL (the default) keeps the legacy unchecked
    -- call shape; a non-NULL value that differs from the current row makes
    -- this a stale claim with zero side effects (lease untouched).
    IF p_expected_session_fence IS NOT NULL
       AND p_expected_session_fence IS DISTINCT FROM v_sess.session_fence THEN
        RETURN jsonb_build_object('outcome', 'rejected_stale',
                                  'code', 'SESSION_FENCE_STALE',
                                  'session_fence', v_sess.session_fence);
    END IF;
    -- Single mutual-exclusion lease slot: no preemption of a live lease
    -- (checked before state so a held lease is reported precisely).
    IF v_sess.lease_owner IS NOT NULL
       AND v_sess.lease_until IS NOT NULL AND v_sess.lease_until > now() THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'LEASE_HELD',
                                  'lease_owner', v_sess.lease_owner);
    END IF;
    -- Transition table: ready -> claimed via normal claim only.
    IF v_sess.state <> 'ready' THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'SESSION_NOT_READY', 'state', v_sess.state);
    END IF;
    IF v_sess.cancellation_epoch > 0 THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'CANCEL_STICKY');
    END IF;

    v_fence := v_sess.session_fence + 1;
    UPDATE sessions SET
        state = 'claimed',
        session_fence = v_fence,
        lease_owner = p_lease_owner,
        lease_until = now() + make_interval(secs => p_lease_seconds),
        lease_purpose = 'coordinator',
        updated_at = now()
     WHERE session_id = p_session_id;
    RETURN jsonb_build_object('outcome', 'claimed', 'session_fence', v_fence);
END;
$$;

CREATE FUNCTION v_recovery_claim_session(
    p_session_id uuid, p_driver text, p_driver_epoch bigint,
    p_lease_owner text, p_lease_seconds int
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_fence bigint;
BEGIN
    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v8: session % not found', p_session_id;
    END IF;
    -- IS DISTINCT FROM: NULL envelope legs fail closed (omitted fields are
    -- mismatches, never silent passes).
    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        RETURN jsonb_build_object('outcome', 'rejected_stale',
                                  'code', 'DRIVER_EPOCH_MISMATCH');
    END IF;
    -- Recovery claim works on any non-terminal state (terminal uses LATER),
    -- only when the lease slot is vacant or expired, never starts new work
    -- (business state untouched), and must keep/verify active_step_id.
    IF v_sess.state IN ('completed', 'failed', 'cancelled') THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'SESSION_TERMINAL', 'state', v_sess.state);
    END IF;
    IF v_sess.lease_owner IS NOT NULL
       AND v_sess.lease_until IS NOT NULL AND v_sess.lease_until > now() THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'LEASE_HELD',
                                  'lease_owner', v_sess.lease_owner);
    END IF;

    v_fence := v_sess.session_fence + 1;
    UPDATE sessions SET
        session_fence = v_fence,
        lease_owner = p_lease_owner,
        lease_until = now() + make_interval(secs => p_lease_seconds),
        lease_purpose = 'recovery',
        updated_at = now()
     WHERE session_id = p_session_id;
    RETURN jsonb_build_object('outcome', 'claimed', 'session_fence', v_fence,
                              'purpose', 'recovery');
END;
$$;

CREATE FUNCTION v_yield_session(
    p_session_id uuid, p_driver text, p_driver_epoch bigint,
    p_session_fence bigint, p_lease_owner text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_fence bigint;
BEGIN
    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v8: session % not found', p_session_id;
    END IF;
    -- Four matches: driver/epoch (IS DISTINCT FROM: NULL legs fail closed),
    -- current fence, unexpired lease, owner.
    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        RETURN jsonb_build_object('outcome', 'rejected_stale',
                                  'code', 'DRIVER_EPOCH_MISMATCH');
    END IF;
    IF p_session_fence IS DISTINCT FROM v_sess.session_fence THEN
        RETURN jsonb_build_object('outcome', 'rejected_stale',
                                  'code', 'SESSION_FENCE_STALE');
    END IF;
    IF v_sess.state <> 'claimed' THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'SESSION_NOT_CLAIMED', 'state', v_sess.state);
    END IF;
    IF v_sess.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_sess.lease_until IS NULL OR v_sess.lease_until <= now() THEN
        RETURN jsonb_build_object('outcome', 'rejected_stale',
                                  'code', 'LEASE_NOT_HELD');
    END IF;

    -- claimed -> ready; the active step (if any) is preserved, no work is
    -- regenerated; releasing the lease bumps the fence (stale old writers).
    v_fence := v_sess.session_fence + 1;
    UPDATE sessions SET
        state = 'ready',
        session_fence = v_fence,
        lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
        updated_at = now()
     WHERE session_id = p_session_id;
    RETURN jsonb_build_object('outcome', 'yielded', 'session_fence', v_fence);
END;
$$;

-- ---------------------------------------------------------------------------
-- Database-internal derived event key for completion-generated semantic
-- events (assistant/message, assistant/partial, turn/end) whose occurrence
-- identity is (effect_id, attempt_no) — s31b §5 P0B list, §3.7 (b) branch.
-- Same shape as v_nonstream_event_key; not a portable assertion object, but
-- mirrored byte-for-byte by the Python reference in v8/effect/client.py.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_completion_event_key(
    p_session_id uuid, p_event_type text, p_effect_id uuid,
    p_attempt_no bigint, p_payload_hash text
) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN encode(sha256(
    convert_to('v8:completion-event-key@db1', 'UTF8') || '\x00'::bytea
    || v_len8(v_uuid16(p_session_id)) || v_uuid16(p_session_id)
    || v_len8(v_identity_bytes(p_event_type)) || v_identity_bytes(p_event_type)
    || v_len8(v_uuid16(p_effect_id)) || v_uuid16(p_effect_id)
    || v_canonical_integer_bytes(p_attempt_no)
    || v_len8(v_identity_bytes(p_payload_hash)) || v_identity_bytes(p_payload_hash)
), 'hex');

-- ---------------------------------------------------------------------------
-- Evidence/attempt binding predicate (s32a §3.5 input contract, s32b §5.2):
-- the evidence object carries the identity of the attempt it attests. An
-- evidence object is bound to (p_effect_id, p_attempt_no) iff it carries
-- BOTH an effect_id equal to p_effect_id and an attempt_no equal to
-- p_attempt_no; anything else (fields absent, malformed, or belonging to a
-- different attempt/effect — e.g. a receipt minted for another effect) is
-- unbound, and v_classify_evidence then falls through to 'unknown'. Shared
-- by the classifier and by complete_effect (which annotates the unknown
-- receipt with EVIDENCE_NOT_BOUND when the fallthrough was a binding
-- failure) — one predicate, never a second classifier.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_evidence_attempt_bound(
    p_effect_id uuid, p_attempt_no bigint, p_evidence jsonb
) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_eff text;
    v_att numeric;
BEGIN
    IF p_evidence IS NULL OR jsonb_typeof(p_evidence) <> 'object' THEN
        RETURN false;
    END IF;
    IF NOT (p_evidence ? 'effect_id') OR NOT (p_evidence ? 'attempt_no') THEN
        RETURN false;
    END IF;
    v_eff := p_evidence->>'effect_id';
    IF v_eff IS NULL
       OR v_eff !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
       OR (v_eff)::uuid <> p_effect_id THEN
        RETURN false;
    END IF;
    v_att := v8_entry_int(p_evidence->'attempt_no');
    IF v_att IS NULL OR v_att <> p_attempt_no THEN
        RETURN false;
    END IF;
    RETURN true;
END;
$$;

-- ---------------------------------------------------------------------------
-- Unique evidence classification function (s32a §3.5, frozen decision table
-- implemented WHOLE — closed output set {known_success | known_failure |
-- known_cancellation | unknown}, ordered first-match; MUST NOT restate,
-- narrow or build a second classifier). Inputs are bound to the current
-- attempt: the caller (complete_effect / later repair / recovery) passes
-- the attempt identity AND the evidence object must itself carry a matching
-- (effect_id, attempt_no) pair (v_evidence_attempt_bound) — an unbound or
-- cross-attempt evidence object classifies 'unknown'. The provider receipt
-- must be an object carrying a non-empty receipt_id to count as a bound
-- terminal receipt. Row semantics as implemented: row 1 known_success
-- requires a bound provider receipt; row 2 known_cancellation accepts
-- EITHER a bound provider receipt (provider-confirmed cancellation) OR
-- persisted no-side-effect evidence (cancel request took effect before the
-- side effect); row 3 known_failure keeps the dual requirement (failure
-- receipt AND persisted no-side-effect proof); everything else falls
-- through to 'unknown' (row 5 catch-all).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_classify_evidence(
    p_effect_id uuid, p_attempt_no bigint, p_evidence jsonb
) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_class text;
    v_receipt_ok boolean;
    v_proof_ok boolean;
BEGIN
    IF NOT v_evidence_attempt_bound(p_effect_id, p_attempt_no, p_evidence) THEN
        RETURN 'unknown';
    END IF;
    IF p_evidence IS NULL OR jsonb_typeof(p_evidence) <> 'object' THEN
        RETURN 'unknown';
    END IF;
    v_class := p_evidence->>'class';
    v_receipt_ok := p_evidence->'provider_receipt' IS NOT NULL
        AND jsonb_typeof(p_evidence->'provider_receipt') = 'object'
        AND coalesce(length(p_evidence->'provider_receipt'->>'receipt_id'), 0) > 0;
    v_proof_ok := p_evidence ? 'no_side_effect_proof'
        AND p_evidence->'no_side_effect_proof' IS NOT NULL
        AND jsonb_typeof(p_evidence->'no_side_effect_proof') = 'object';
    IF v_class = 'known_success' AND v_receipt_ok THEN
        RETURN 'known_success';
    END IF;
    IF v_class = 'known_cancellation' AND (v_receipt_ok OR v_proof_ok) THEN
        RETURN 'known_cancellation';
    END IF;
    IF v_class = 'known_failure' AND v_receipt_ok AND v_proof_ok THEN
        RETURN 'known_failure';
    END IF;
    RETURN 'unknown';
END;
$$;

-- ---------------------------------------------------------------------------
-- Shared turn-close judgment (s31b §2.6.1 tail + s32a §2.1 rule 6 / s31a
-- transition-table claimed->completed row): one SQL predicate used by both
-- the rule-6 aggregation inside complete_effect and finish_session.
--   closed       all steps of the turn succeeded and the LAST step is a
--                decision_only=true closing step, with no open work;
--   open_work    any non-terminal step or any unsettled effect (pending,
--                retryable, unknown) in the session.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_session_finalize(
    p_session_id uuid, p_turn_id uuid DEFAULT NULL
) RETURNS TABLE(closed boolean, decision_only boolean, open_work boolean)
LANGUAGE plpgsql AS $$
DECLARE
    v_turn uuid;
    v_total bigint;
    v_nonsucc bigint;
    v_do boolean := false;
    v_open bigint;
BEGIN
    IF p_turn_id IS NULL THEN
        SELECT st.turn_id INTO v_turn FROM steps st
         WHERE st.session_id = p_session_id
         ORDER BY st.created_at DESC, st.step_id DESC LIMIT 1;
        IF NOT FOUND THEN
            RETURN QUERY SELECT false, false, true;
            RETURN;
        END IF;
    ELSE
        v_turn := p_turn_id;
    END IF;

    SELECT count(*), count(*) FILTER (WHERE st.status <> 'succeeded')
      INTO v_total, v_nonsucc
      FROM steps st
     WHERE st.session_id = p_session_id AND st.turn_id = v_turn;

    SELECT st.decision_only IS TRUE INTO v_do
      FROM steps st
     WHERE st.session_id = p_session_id AND st.turn_id = v_turn
     ORDER BY st.created_at DESC, st.step_id DESC LIMIT 1;

    SELECT (SELECT count(*) FROM steps s2
             WHERE s2.session_id = p_session_id
               AND s2.status NOT IN ('succeeded', 'failed_terminal', 'cancelled'))
         + (SELECT count(*) FROM effect_requests er
             JOIN steps s3 ON s3.step_id = er.step_id
            WHERE s3.session_id = p_session_id
              AND er.status IN ('planned', 'ready', 'dispatch_started',
                                'failed_retryable', 'unknown_outcome'))
      INTO v_open;

    RETURN QUERY SELECT
        (v_total > 0 AND v_nonsucc = 0 AND coalesce(v_do, false) AND v_open = 0),
        coalesce(v_do, false),
        (v_open > 0);
END;
$$;

-- ---------------------------------------------------------------------------
-- v_prepare_step — the initial decision seal (s31b §2.6.1, steps (1)(4)(5)
-- (6)(8); steps (2) seal authorization and (3) generation check are LATER
-- and deliberately absent). create_step is a controlled sub-operation of
-- THIS transaction: the step row is created, sealed and published here and
-- nowhere else. 'planned' is an in-transaction building state only — the
-- seal transaction overwrites it before commit, so no persisted planned
-- step/effect row can exist (Conformance 1).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_prepare_step(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint, p_session_fence bigint,
    p_step_id uuid, p_turn_id uuid, p_effect_id uuid,
    p_effect_kind text, p_execution_mode text, p_retry_class text,
    p_max_attempts bigint, p_request_hash text, p_idempotency_key text,
    p_declared_hash text, p_payload_canonical text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_prev_status text;
    v_batch_id uuid;
    v_job_fence bigint;
    v_new_fence bigint;
BEGIN
    -- Judgment order (1)-(4) with the session row lock (master lock order
    -- position 1) taken inside the adjudicator.
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'prepare_step',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;

    -- Seal CAS guards — all BEFORE any business mutation, so any rejection
    -- is the whole seal with zero side effects (only binding + rejection
    -- receipt persist; step 7 of the eight-step digest).
    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'prepare_step',
            v_computed, 'rejected_stale', 'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session control row');
        RETURN QUERY SELECT 'rejected_stale'::text, 'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF p_session_fence IS DISTINCT FROM v_sess.session_fence THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'prepare_step',
            v_computed, 'rejected_stale', 'SESSION_FENCE_STALE',
            format('expected session_fence %s does not match current %s',
                   coalesce(p_session_fence::text, 'NULL'), v_sess.session_fence));
        RETURN QUERY SELECT 'rejected_stale'::text, 'SESSION_FENCE_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.driver_mode <> 'active' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'prepare_step',
            v_computed, 'rejected_mismatch', 'DRIVER_QUIESCING',
            'seal requires driver_mode=active');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'DRIVER_QUIESCING'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.state <> 'claimed' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'prepare_step',
            v_computed, 'rejected_mismatch', 'SESSION_NOT_CLAIMED',
            format('initial decision seal requires state=claimed, got %s', v_sess.state));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_NOT_CLAIMED'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.cancellation_epoch > 0 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'prepare_step',
            v_computed, 'rejected_mismatch', 'CANCEL_STICKY',
            'sticky cancel latch set: planned cancel means the whole seal is rejected');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'CANCEL_STICKY'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.lease_owner IS NULL OR v_sess.lease_until IS NULL
       OR v_sess.lease_until <= now() THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'prepare_step',
            v_computed, 'rejected_stale', 'LEASE_NOT_HELD',
            'coordination lease vacant or expired');
        RETURN QUERY SELECT 'rejected_stale'::text, 'LEASE_NOT_HELD'::text, v_receipt;
        RETURN;
    END IF;

    -- create_step guard (1): active_step_id NULL or pointing at a terminal
    -- step (single-active-step model; the partial unique index is the
    -- authority, the pointer is the locating aid).
    IF v_sess.active_step_id IS NOT NULL THEN
        SELECT st.status INTO v_prev_status FROM steps st
         WHERE st.step_id = v_sess.active_step_id;
        IF v_prev_status IS NULL
           OR v_prev_status NOT IN ('succeeded', 'failed_terminal', 'cancelled') THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'prepare_step',
                v_computed, 'rejected_mismatch', 'ACTIVE_STEP_OPEN',
                'active step is still non-terminal; a new step cannot be created');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'ACTIVE_STEP_OPEN'::text, v_receipt;
            RETURN;
        END IF;
    END IF;
    -- create_step guard (2): the target turn must not already be closed by
    -- a successful decision_only step.
    IF EXISTS (SELECT 1 FROM steps st
                WHERE st.session_id = p_session_id AND st.turn_id = p_turn_id
                  AND st.status = 'succeeded' AND st.decision_only IS TRUE) THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'prepare_step',
            v_computed, 'rejected_mismatch', 'TURN_ALREADY_CLOSED',
            'the turn already has a successful decision_only closing step');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'TURN_ALREADY_CLOSED'::text, v_receipt;
        RETURN;
    END IF;
    -- LLM slot spec validation (table CHECKs would abort the transaction
    -- and lose the receipt; reject classified instead).
    IF p_execution_mode NOT IN ('streaming', 'non_streaming')
       OR p_retry_class NOT IN ('provider_idempotent', 'verifiable_no_effect', 'unsafe')
       OR p_max_attempts IS NULL OR p_max_attempts < 1
       OR coalesce(length(p_request_hash), 0) = 0
       OR coalesce(length(p_idempotency_key), 0) = 0 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'prepare_step',
            v_computed, 'rejected_mismatch', 'SLOT_SPEC_INVALID',
            'LLM slot spec violates the frozen value domains');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SLOT_SPEC_INVALID'::text, v_receipt;
        RETURN;
    END IF;

    -- Seal step (1): create_step — created as planned/stage=decision, an
    -- in-transaction building state only.
    INSERT INTO steps(step_id, session_id, turn_id, status, stage)
    VALUES (p_step_id, p_session_id, p_turn_id, 'planned', 'decision');

    -- Seal steps (4)+(5): the unique sealed decision batch + the LLM slot
    -- effect (create_effect_in_seal mode: member creation inside the seal
    -- transaction, before the sealed flag is observable) + the FIRST
    -- attempt in the same transaction (attempt_no=1, the only creation
    -- entry point for a first attempt).
    v_batch_id := gen_random_uuid();
    INSERT INTO batches(batch_id, session_id, step_id, sealed_batch_no, kind, sealed)
    VALUES (v_batch_id, p_session_id, p_step_id, 1, 'decision', true);

    v_job_fence := nextval('v8_job_fence_seq');

    INSERT INTO effect_requests(
        effect_id, session_id, step_id, batch_id, dispatch_ordinal, tool_call_id,
        effect_kind, execution_mode, driver, driver_epoch, session_fence,
        dispatch_session_fence, current_job_fence, request_hash, idempotency_key,
        status, retry_class, max_attempts, attempt_no, dispatch_count)
    VALUES (
        p_effect_id, p_session_id, p_step_id, v_batch_id, 0, NULL,
        p_effect_kind, p_execution_mode, v_sess.driver, v_sess.driver_epoch,
        v_sess.session_fence, v_sess.session_fence, v_job_fence,
        p_request_hash, p_idempotency_key, 'planned', p_retry_class,
        p_max_attempts, 1, 0);

    INSERT INTO effect_attempts(
        effect_id, attempt_no, session_id, step_id, driver, driver_epoch,
        session_fence, dispatch_session_fence, dispatch_job_fence, request_hash,
        idempotency_key, execution_mode, status)
    VALUES (
        p_effect_id, 1, p_session_id, p_step_id, v_sess.driver, v_sess.driver_epoch,
        v_sess.session_fence, v_sess.session_fence, v_job_fence,
        p_request_hash, p_idempotency_key, p_execution_mode, 'ready');

    -- Seal step (6): publish-as-ready — the sealed effect flips to ready
    -- inside the same transaction (planned never persists); the dispatch
    -- gate ready -> dispatch_started is immediately visible after commit.
    UPDATE effect_requests SET status = 'ready', updated_at = now()
     WHERE effect_id = p_effect_id;

    -- Seal step (5)+(8): publish the seal and aggregate to waiting_effect;
    -- no partially-sealed batch is ever observable.
    UPDATE steps SET
        status = 'waiting_effect',
        sealed_batch_no = 1,
        pending_effect_count = 1,
        updated_at = now()
     WHERE step_id = p_step_id;

    -- Session aggregation (rule 2: waiting_effect). Leaving claimed revokes
    -- the coordination lease and bumps the fence (controlled-transaction
    -- rule, double-fence base semantics: old coordination writes go stale).
    v_new_fence := v_sess.session_fence + 1;
    UPDATE sessions SET
        state = 'waiting_effect',
        session_fence = v_new_fence,
        lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
        active_step_id = p_step_id,
        updated_at = now()
     WHERE session_id = p_session_id;

    v_receipt := jsonb_build_object(
        'command_kind', 'prepare_step',
        'command_id', p_command_id,
        'step_id', p_step_id,
        'turn_id', p_turn_id,
        'batch_id', v_batch_id,
        'sealed_batch_no', 1,
        'effect_id', p_effect_id,
        'attempt_no', 1,
        'job_fence', v_job_fence,
        'session_fence', v_new_fence,
        'step_status', 'waiting_effect',
        'session_state', 'waiting_effect');

    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
        outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'prepare_step', 'canonical_request_hash',
            v_computed, 'accepted', NULL, v_receipt::text,
            v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_dispatch_effect — the dispatch gate (s32b §2.5, ready -> dispatch_started)
-- in one transaction: cancellation epoch, session/job fence, grant/handler/
-- compact/generation checks (P0B: the latter four are LATER), effect status
-- =ready. Binds the EXISTING first attempt — dispatch MUST NOT create any
-- attempt row (missing row = INFRA_PROTOCOL_VIOLATION). Rejections are
-- read-only (receipt only).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_dispatch_effect(
    p_session_id uuid, p_command_id text, p_effect_id uuid,
    p_driver text, p_driver_epoch bigint, p_session_fence bigint,
    p_job_fence bigint, p_declared_hash text, p_payload_canonical text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_step_id uuid;
    v_er effect_requests%ROWTYPE;
    v_att effect_attempts%ROWTYPE;
    v_receipt jsonb;
BEGIN
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'dispatch_effect',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;

    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'dispatch_effect',
            v_computed, 'rejected_stale', 'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session control row');
        RETURN QUERY SELECT 'rejected_stale'::text, 'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF p_session_fence IS DISTINCT FROM v_sess.session_fence THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'dispatch_effect',
            v_computed, 'rejected_stale', 'SESSION_FENCE_STALE',
            format('expected session_fence %s does not match current %s',
                   coalesce(p_session_fence::text, 'NULL'), v_sess.session_fence));
        RETURN QUERY SELECT 'rejected_stale'::text, 'SESSION_FENCE_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.cancellation_epoch > 0 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'dispatch_effect',
            v_computed, 'rejected_mismatch', 'CANCEL_STICKY',
            'sticky cancel latch set: no dispatch after cancel');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'CANCEL_STICKY'::text, v_receipt;
        RETURN;
    END IF;

    -- Locate (lockless read of the immutable association), then lock in the
    -- master order: step -> effect -> attempt.
    SELECT er.step_id INTO v_step_id FROM effect_requests er
     WHERE er.effect_id = p_effect_id;
    IF NOT FOUND THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'dispatch_effect',
            v_computed, 'rejected_mismatch', 'EFFECT_NOT_FOUND',
            'effect_id is not persisted');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EFFECT_NOT_FOUND'::text, v_receipt;
        RETURN;
    END IF;
    PERFORM 1 FROM steps st WHERE st.step_id = v_step_id FOR UPDATE;
    SELECT * INTO v_er FROM effect_requests er WHERE er.effect_id = p_effect_id FOR UPDATE;
    IF v_er.session_id IS DISTINCT FROM p_session_id THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'dispatch_effect',
            v_computed, 'rejected_mismatch', 'EFFECT_NOT_FOUND',
            'effect_id does not belong to this session');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EFFECT_NOT_FOUND'::text, v_receipt;
        RETURN;
    END IF;
    IF v_er.status <> 'ready' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'dispatch_effect',
            v_computed, 'rejected_mismatch', 'EFFECT_NOT_READY',
            format('dispatch gate requires effect status=ready, got %s', v_er.status));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EFFECT_NOT_READY'::text, v_receipt;
        RETURN;
    END IF;
    IF p_job_fence IS DISTINCT FROM v_er.current_job_fence THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'dispatch_effect',
            v_computed, 'rejected_stale', 'STALE_JOB_FENCE',
            'job fence does not match effect current_job_fence');
        RETURN QUERY SELECT 'rejected_stale'::text, 'STALE_JOB_FENCE'::text, v_receipt;
        RETURN;
    END IF;

    -- Bind the existing current attempt; a missing row is an infra
    -- protocol violation (dispatch must never create attempts).
    SELECT * INTO v_att FROM effect_attempts a
     WHERE a.effect_id = p_effect_id AND a.attempt_no = v_er.attempt_no FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'INFRA_PROTOCOL_VIOLATION: effect % has no attempt row % to bind '
            '(dispatch must never create attempts)', p_effect_id, v_er.attempt_no;
    END IF;
    IF v_att.status <> 'ready' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'dispatch_effect',
            v_computed, 'rejected_mismatch', 'EFFECT_NOT_READY',
            format('bound attempt is not ready (attempt status %s)', v_att.status));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EFFECT_NOT_READY'::text, v_receipt;
        RETURN;
    END IF;

    -- The gate transition: both tables in one transaction; the attempt
    -- status change IS the dispatch marker (with dispatched_at).
    UPDATE effect_requests SET
        status = 'dispatch_started',
        dispatch_count = dispatch_count + 1,
        dispatched_at = now(),
        updated_at = now()
     WHERE effect_id = p_effect_id;
    UPDATE effect_attempts SET
        status = 'dispatch_started',
        dispatched_at = now()
     WHERE effect_id = p_effect_id AND attempt_no = v_att.attempt_no;

    v_receipt := jsonb_build_object(
        'command_kind', 'dispatch_effect',
        'command_id', p_command_id,
        'effect_id', p_effect_id,
        'attempt_no', v_att.attempt_no,
        'dispatch_count', v_er.dispatch_count + 1,
        'job_fence', v_er.current_job_fence,
        'status', 'dispatch_started');

    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
        outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'dispatch_effect', 'canonical_request_hash',
            v_computed, 'accepted', NULL, v_receipt::text,
            v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_complete_effect — two-layer validation + four-step sequence (s32b §2.6,
-- s32c §2.1), P0B terminal non-streaming path.
--
-- Structural layer: command/transport shape (adjudicate), attempt envelope
-- against the ATTEMPT ROW authority (driver/driver_epoch/session-fence
-- family/dispatch_session_fence/attempt_no/step_id/request_hash/
-- idempotency_key; step_id per the EffectResult ABI, mismatch =
-- STEP_MISMATCH), the unknown_outcome late-completion branch
-- (REPAIR_REQUIRED, receipt + audit only — repair is the only exit for a
-- settled-unknown attempt), effect-level current_job_fence as the sole
-- stale authority
-- (STALE_JOB_FENCE: receipt + audit only, zero control state),
-- cancellation_epoch from the sessions row, outcome value domain, result
-- payload shape. Semantic layer (success path only): the decision marks /
-- tools-plan bidirectional mutex-exhaustive check. Four-step order:
-- (i) structural schema (no stream_complete matrix here), (ii) unique
-- evidence classification, (iii) known_success AND streaming -> grammar
-- (LATER in P0B), (iv) non-known_success settles by classification.
--
-- G6: effects sealed in a kind='tools' batch settle through the tool arm
-- (payload = tool result carrying the slot's tool_call_id; SQL-generated
-- tool/result semantic event; rule-6 final_tools terminalization: step
-- succeeded + stage=closed + session ready, turn left open for the next
-- decision step).
--
-- Success closure settles effect+attempt to succeeded, freezes result_hash,
-- persists the decision_result_identity components and the normalized tools
-- plan (plan_canonical + plan_hash over the plan, digest 2.6.1 — plan_hash
-- is recomputable from the persisted plan by the later tools seal, 2.6.2
-- step 2), SQL-generates the assistant/message semantic event (worker MUST
-- NOT attach events), aggregates the step (rule 6 via the shared
-- v_session_finalize judgment), closes the turn (turn_end_slots known row
-- + turn/end {interrupted:false}) and drives the session to its aggregated
-- target. Unknown closure drives unknown_outcome + the unique provisional
-- turn/end {outcome:unknown} + provisional slot + blocked session.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_complete_effect(
    p_session_id uuid, p_command_id text,
    p_effect_id uuid, p_attempt_no bigint, p_step_id uuid,
    p_driver text, p_driver_epoch bigint,
    p_dispatch_session_fence bigint, p_job_fence bigint,
    p_outcome text, p_request_hash text, p_idempotency_key text,
    p_result_payload_canonical text, p_message_canonical text,
    p_plan_canonical text,
    p_schema_version text, p_canonicalizer_version text,
    p_declared_hash text, p_payload_canonical text,
    p_evidence jsonb
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_step steps%ROWTYPE;
    v_step_id uuid;
    v_er effect_requests%ROWTYPE;
    v_att effect_attempts%ROWTYPE;
    v_receipt jsonb;
    v_res jsonb;
    v_plan jsonb;
    v_class text;
    v_derived text;
    v_bound boolean;
    v_mismatch boolean;
    v_tools_empty boolean;
    v_do boolean;
    v_ft boolean;
    v_result_hash text;
    v_msg_hash text;
    v_end_payload text;
    v_end_hash text;
    v_evkey text;
    v_endkey text;
    v_iso bigint;
    v_seq bigint;
    v_fin record;
    v_pending bigint;
    v_unknown bigint;
    v_receipt_id text;
    v_fingerprint text;
    v_events jsonb;
    v_batch_kind text;
    v_kf record;
    v_kc record;
    v_end jsonb;
    v_agg record;
    -- G9a stream_complete field matrix (grammar (0)/(1)-(4)).
    v_sc boolean;
    v_has_n boolean;
    v_has_c boolean;
    v_n numeric;
    v_c numeric;
    v_obs_ord bigint;
    v_obs_hash text;
    -- G9b observation sub-operation + certified stream facts.
    v_obs_outcome text;
    v_obs_code text;
    v_stream_final text;
BEGIN
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'complete_effect',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;

    -- Locate, then lock in the master order: step -> effect -> attempt.
    SELECT er.step_id INTO v_step_id FROM effect_requests er
     WHERE er.effect_id = p_effect_id;
    IF NOT FOUND THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'EFFECT_NOT_FOUND',
            'effect_id is not persisted');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EFFECT_NOT_FOUND'::text, v_receipt;
        RETURN;
    END IF;
    SELECT * INTO v_step FROM steps st WHERE st.step_id = v_step_id FOR UPDATE;
    SELECT * INTO v_er FROM effect_requests er WHERE er.effect_id = p_effect_id FOR UPDATE;
    IF v_er.session_id IS DISTINCT FROM p_session_id THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'EFFECT_NOT_FOUND',
            'effect_id does not belong to this session');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EFFECT_NOT_FOUND'::text, v_receipt;
        RETURN;
    END IF;
    SELECT * INTO v_att FROM effect_attempts a
     WHERE a.effect_id = p_effect_id AND a.attempt_no = p_attempt_no FOR UPDATE;
    IF NOT FOUND THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'ATTEMPT_NOT_FOUND',
            'attempt_no does not locate a persisted attempt row');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'ATTEMPT_NOT_FOUND'::text, v_receipt;
        RETURN;
    END IF;

    -- ---- structural layer: attempt envelope (attempt row authority) ----
    -- IS DISTINCT FROM: NULL envelope legs fail closed against the frozen
    -- attempt snapshot, never a silent pass.
    IF p_driver IS DISTINCT FROM v_att.driver
       OR p_driver_epoch IS DISTINCT FROM v_att.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_stale', 'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch differs from the frozen attempt snapshot');
        RETURN QUERY SELECT 'rejected_stale'::text, 'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF p_request_hash IS DISTINCT FROM v_att.request_hash
       OR p_idempotency_key IS DISTINCT FROM v_att.idempotency_key THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'REQUEST_IDENTITY_MISMATCH',
            'request_hash/idempotency_key differ from the attempt ABI fields');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REQUEST_IDENTITY_MISMATCH'::text, v_receipt;
        RETURN;
    END IF;
    -- EffectResult ABI step_id (s32b §5.2): the envelope must carry the
    -- step the settled attempt belongs to; IS DISTINCT FROM fails closed
    -- for a NULL/omitted leg and for a cross-step attribution alike.
    IF p_step_id IS DISTINCT FROM v_att.step_id THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'STEP_MISMATCH',
            'envelope step_id does not match the attempt row step attribution');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'STEP_MISMATCH'::text, v_receipt;
        RETURN;
    END IF;
    -- Dual fence (G7a order): effect-level current_job_fence is the sole
    -- stale authority -- mismatch is rejected_stale with zero control state
    -- (receipt + audit only). The fence acceptance precedes every attempt
    -- status disposition so a late completion from a superseded attempt
    -- era (its dispatch_job_fence no longer equals current_job_fence)
    -- classifies as STALE_JOB_FENCE (Conformance 2: a superseded job
    -- fence is judged solely against current_job_fence).
    IF p_job_fence IS DISTINCT FROM v_er.current_job_fence THEN
        v_fingerprint := v_sha256_hex(coalesce(p_result_payload_canonical, p_payload_canonical));
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id, attempt_no,
            audit_key_kind, audit_key_value, result_fingerprint, reason)
        VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
                'canonical_binding', v_computed, v_fingerprint, 'STALE_JOB_FENCE');
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_stale', 'STALE_JOB_FENCE',
            format('job_fence %s does not match effect current_job_fence %s',
                   coalesce(p_job_fence::text, 'NULL'), v_er.current_job_fence));
        RETURN QUERY SELECT 'rejected_stale'::text, 'STALE_JOB_FENCE'::text, v_receipt;
        RETURN;
    END IF;
    -- Superseded attempt (G7a): a completion naming an attempt that a
    -- cohort allocation has replaced is a late result of the OLD
    -- execution era -- audit only, never re-aggregated (s32b 4.2). The
    -- old-era fence case was already rejected above as STALE_JOB_FENCE;
    -- this row catches a replaced attempt carrying the current fence.
    IF v_att.superseded_by_attempt_no IS NOT NULL THEN
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id, attempt_no,
            audit_key_kind, audit_key_value, result_fingerprint, reason)
        VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
                'canonical_binding', v_computed,
                v_sha256_hex(coalesce(p_result_payload_canonical, p_payload_canonical)),
                'ATTEMPT_SUPERSEDED');
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_stale', 'ATTEMPT_SUPERSEDED',
            format('attempt %s was superseded by attempt %s: late results are audit-only',
                   p_attempt_no, v_att.superseded_by_attempt_no));
        RETURN QUERY SELECT 'rejected_stale'::text, 'ATTEMPT_SUPERSEDED'::text, v_receipt;
        RETURN;
    END IF;
    -- Single terminal settlement constraint (receipt idempotency carries
    -- same-command retries; a different command_id re-settling the same
    -- attempt is rejected).
    IF v_att.status IN ('succeeded', 'failed_terminal',
                        'cancelled_before_dispatch', 'cancelled_after_dispatch') THEN
        -- The late completion of a terminal attempt is receipt + audit only
        -- (zero control state). This covers the pre-dispatch cancel path:
        -- after request_cancel syncs the attempt to cancelled_before_dispatch
        -- a late worker completion is stably rejected here (s32b §2.9).
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id, attempt_no,
            audit_key_kind, audit_key_value, result_fingerprint, reason)
        VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
                'canonical_binding', v_computed,
                v_sha256_hex(coalesce(p_result_payload_canonical, p_payload_canonical)),
                'ATTEMPT_ALREADY_SETTLED');
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'ATTEMPT_ALREADY_SETTLED',
            format('attempt already terminal (%s): single settlement', v_att.status));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'ATTEMPT_ALREADY_SETTLED'::text, v_receipt;
        RETURN;
    END IF;
    -- Late completion of an attempt already settled unknown_outcome (the
    -- two-worker race aftermath: the winner settled unknown, the loser's
    -- real result arrives afterwards). unknown_outcome is NOT one of the
    -- four settled statuses above, and repair is its ONLY exit (s32b §2.7):
    -- a plain complete_effect MUST return repair_required / REPAIR_REQUIRED
    -- — zero control state, receipt + audit only. This check sits BEFORE
    -- the dispatch_started check so unknown_outcome never falls into the
    -- generic ATTEMPT_NOT_DISPATCHED bucket.
    IF v_att.status = 'unknown_outcome' THEN
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id, attempt_no,
            audit_key_kind, audit_key_value, result_fingerprint, reason)
        VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
                'canonical_binding', v_computed,
                v_sha256_hex(coalesce(p_result_payload_canonical, p_payload_canonical)),
                'REPAIR_REQUIRED');
        v_receipt := jsonb_build_object(
            'command_kind', 'complete_effect',
            'command_id', p_command_id,
            'outcome', 'repair_required',
            'code', 'REPAIR_REQUIRED',
            'effect_id', p_effect_id,
            'attempt_no', p_attempt_no,
            'detail', 'attempt already settled unknown_outcome; repair is the only exit for unknown attempts');
        INSERT INTO command_bindings(
            session_id, command_id, first_key_kind, first_key_value, first_outcome)
        VALUES (p_session_id, p_command_id, 'canonical_request_hash',
                v_computed, 'repair_required');
        INSERT INTO command_receipts(
            session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
            outcome, code, result_canonical, result_hash)
        VALUES (p_session_id, p_command_id, 'complete_effect', 'canonical_request_hash',
                v_computed, 'repair_required', 'REPAIR_REQUIRED', v_receipt::text,
                v_sha256_hex(v_receipt::text));
        RETURN QUERY SELECT 'repair_required'::text, 'REPAIR_REQUIRED'::text, v_receipt;
        RETURN;
    END IF;
    IF v_att.status <> 'dispatch_started' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'ATTEMPT_NOT_DISPATCHED',
            format('completion requires attempt status=dispatch_started, got %s', v_att.status));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'ATTEMPT_NOT_DISPATCHED'::text, v_receipt;
        RETURN;
    END IF;
    IF p_dispatch_session_fence IS DISTINCT FROM v_att.dispatch_session_fence THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_stale', 'STALE_SESSION_FENCE',
            'dispatch_session_fence differs from the frozen attempt snapshot');
        RETURN QUERY SELECT 'rejected_stale'::text, 'STALE_SESSION_FENCE'::text, v_receipt;
        RETURN;
    END IF;
    -- cancellation_epoch: sessions row authority. G8b (α): the sticky latch
    -- is NOT a rejection — a terminal settlement under the latch runs the
    -- shared cancel closure dispositions (s32b §2.8; see the sticky branch
    -- after the evidence classification below), never a plain settlement.
    IF p_outcome IS NULL OR p_outcome NOT IN (
            'succeeded', 'failed_retryable', 'failed_terminal',
            'cancelled_before_dispatch', 'cancelled_after_dispatch', 'unknown_outcome') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'OUTCOME_INVALID',
            'EffectResult.outcome outside the closed set');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'OUTCOME_INVALID'::text, v_receipt;
        RETURN;
    END IF;
    BEGIN
        v_res := p_result_payload_canonical::jsonb;
    EXCEPTION WHEN OTHERS THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
            'result payload canonical text is not valid JSON');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
        RETURN;
    END;
    IF jsonb_typeof(v_res) <> 'object' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
            'result payload must be a JSON object');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
        RETURN;
    END IF;

    -- ---- four-step sequence (ii): unique evidence classification ----
    v_class := v_classify_evidence(p_effect_id, p_attempt_no, p_evidence);
    v_bound := v_evidence_attempt_bound(p_effect_id, p_attempt_no, p_evidence);

    -- ---- (iii): known_success AND streaming -> stream_complete matrix ----
    -- Grammar (0) O04, five exhaustive forms, applied ONLY when the unique
    -- evidence classification is known_success AND the AUTHORITATIVE effect
    -- execution_mode is 'streaming' (N05/W02). A result's self-reported mode
    -- never decides applicability. Non-known_success results are exempt
    -- (F3/W02): a streaming known_failure missing stream_complete MUST NOT
    -- schema reject — it settles by classification in the branches below.
    IF v_class = 'known_success' AND v_er.execution_mode = 'streaming' THEN
        -- (ii) stream_complete missing (with or without counts) -> reject.
        IF NOT (v_res ? 'stream_complete') THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
                'streaming known_success result is missing stream_complete (matrix form (0)(ii))');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        IF jsonb_typeof(v_res->'stream_complete') <> 'boolean' THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
                'stream_complete must be a boolean');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        v_sc := (v_res->>'stream_complete')::boolean;
        -- "counts present" = final_chunk_index / chunk_count exactly one or
        -- both (a JSON null is absence, not a value).
        v_has_n := (v_res ? 'final_chunk_index')
                   AND jsonb_typeof(v_res->'final_chunk_index') <> 'null';
        v_has_c := (v_res ? 'chunk_count')
                   AND jsonb_typeof(v_res->'chunk_count') <> 'null';

        -- (4) count value domain: negative / non-integer;
        --     final_chunk_index > 2^63-2 (N04); chunk_count > 2^63-1.
        IF v_has_n THEN
            v_n := v8_entry_int(v_res->'final_chunk_index');
            IF v_n IS NULL OR v_n < 0 OR v_n <> floor(v_n)
               OR v_n > 9223372036854775806 THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                    v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
                    'final_chunk_index outside [0, 2^63-2] or not an integer (grammar (4))');
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
                RETURN;
            END IF;
        END IF;
        IF v_has_c THEN
            v_c := v8_entry_int(v_res->'chunk_count');
            IF v_c IS NULL OR v_c < 0 OR v_c <> floor(v_c)
               OR v_c > 9223372036854775807 THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                    v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
                    'chunk_count outside [0, 2^63-1] or not an integer (grammar (4))');
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
                RETURN;
            END IF;
        END IF;
        -- (3) coexistence contradiction: both present MUST satisfy C = N+1.
        IF v_has_n AND v_has_c AND v_c <> v_n + 1 THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
                'final_chunk_index / chunk_count coexist without C = N+1 (grammar (3))');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
            RETURN;
        END IF;

        IF NOT v_sc THEN
            -- Forms (iii)/(iv): stream_complete=false -> pending non-terminal
            -- stream observation. The observation sub-operation applies the
            -- frozen five-state gate (SESSION_TERMINAL / superseded /
            -- STREAM_CLOSED / REPAIR_REQUIRED / accept) and owns the
            -- observation receipt contract (Q04) + the zero-control-state
            -- write set (AF01): the attempt row, session state, lease, fences
            -- and every aggregation counter keep their pre-arrival values.
            -- The caller's structural prefix already enforced gates 2-4 for
            -- this entry; gate 1 (terminal session) and gate 5 (accept) are
            -- decided here.
            SELECT o.outcome, o.code, o.receipt_json
              INTO v_obs_outcome, v_obs_code, v_receipt
              FROM v_stream_observe(
                  p_session_id, p_command_id, p_effect_id, p_attempt_no,
                  p_result_payload_canonical, p_schema_version,
                  p_canonicalizer_version, v_computed) o;
            RETURN QUERY SELECT v_obs_outcome, v_obs_code, v_receipt;
            RETURN;
        END IF;

        -- Form (v): stream_complete=true with no count -> reject. Form (4):
        -- stream_complete=true with a zero chunk_count -> reject (a
        -- non-streaming-shaped success); final_chunk_index=0 implies
        -- chunk_count=1 and stays legal.
        IF NOT (v_has_n OR v_has_c) THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
                'stream_complete=true without a count (matrix form (0)(v))');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        IF v_has_c AND v_c = 0 THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
                'stream_complete=true with chunk_count=0 (grammar (4))');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        -- Form (i): complete flow. Record the certified stream facts (needed
        -- by the equivalence lifecycle and the F4 range check) and run the
        -- canonicalizer-side (a)/(b)/F4 judgment. The completion is never
        -- blocked by equivalence: a mismatch records the
        -- CANONICALIZER_CONFLICT conflict fact, a missing tail or a
        -- not-yet-arrived final leaves the verification pending (b)/(5).
        v_stream_final := CASE
            WHEN p_message_canonical IS NULL THEN NULL
            WHEN jsonb_typeof(p_message_canonical::jsonb) = 'string'
                THEN p_message_canonical::jsonb #>> '{}'
            ELSE p_message_canonical::jsonb ->> 'text' END;
        PERFORM v_stream_record_completion(
            p_session_id, p_effect_id, p_attempt_no,
            CASE WHEN v_has_n THEN v_n::bigint END,
            CASE WHEN v_has_c THEN v_c::bigint END,
            v_stream_final);
        PERFORM v_stream_equivalence(
            p_session_id, p_effect_id, p_attempt_no,
            CASE WHEN v_has_n THEN v_n::bigint END,
            CASE WHEN v_has_c THEN v_c::bigint END,
            v_stream_final);
    END IF;
    -- W01 quiescing note: the (iii)/(iv) non-terminal stream observation forms
    -- returned above (quiescing is not one of the five gates and does NOT
    -- block a non-terminal observation). Reaching this point means a TERMINAL
    -- settlement — a quiescing driver stably rejects it (zero control state,
    -- receipt + audit only).
    IF v_sess.driver_mode = 'quiescing' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            v_computed, 'rejected_mismatch', 'DRIVER_QUIESCING',
            'terminal completion while driver_mode=quiescing (W01)');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'DRIVER_QUIESCING'::text, v_receipt;
        RETURN;
    END IF;
    -- G7a: known_failure settlement is OPEN (the retry_eligible split,
    -- aggregation rules 4/5, retry_stop_reason persistence and the
    -- dual-requirement evidence persistence live in the retry stage's
    -- shared settlement function — v8/retry/v8_retry.sql, appended after
    -- this file in the cumulative load order; the function reference is
    -- resolved at call time and stage databases that stop before the
    -- retry stage never reach this arm). G8b opens known_cancellation and
    -- the sticky-latch cancel closure dispositions below.
    IF v_class = 'known_failure' THEN
        SELECT * INTO v_kf FROM v_settle_known_failure(
            p_session_id, p_command_id, v_computed, v_step_id,
            p_effect_id, p_attempt_no, p_evidence,
            v_sha256_hex(coalesce(p_result_payload_canonical,
                                  p_payload_canonical)),
            p_outcome, p_schema_version, p_canonicalizer_version);
        RETURN QUERY SELECT v_kf.outcome, v_kf.code, v_kf.receipt_json;
        RETURN;
    END IF;
    -- G8b (α): known_cancellation is a KNOWN terminal result — the exit-5
    -- disposition of the shared cancel closure sub-operation
    -- (v8/cancel/v8_closure.sql): the effect keeps cancelled_after_dispatch
    -- with the §4.3 map code, the shared judgment/applier derive the
    -- cancel-wins parent row and the canonical turn/end is re-derived. The
    -- reference resolves at call time (the shared sub-operation lives in a
    -- file loaded before the retry stage), so earlier stage databases that
    -- never present cancellation evidence are unaffected.
    IF v_class = 'known_cancellation' THEN
        SELECT * INTO v_kc FROM v_settle_known_cancellation(
            p_session_id, p_command_id, v_computed, v_step_id,
            p_effect_id, p_attempt_no, p_evidence,
            v_sha256_hex(coalesce(p_result_payload_canonical,
                                  p_payload_canonical)),
            p_outcome, p_schema_version, p_canonicalizer_version);
        RETURN QUERY SELECT v_kc.outcome, v_kc.code, v_kc.receipt_json;
        RETURN;
    END IF;

    -- G8b (α): exit 3 — a SUCCESSFUL completion landing under the sticky
    -- latch keeps `succeeded` and records COMPLETED_AFTER_CANCEL. The parent
    -- layer still derives the cancel-wins row, so the decision-mark / tools /
    -- turn-close arms of the normal success path are moot (the completion
    -- fact is recorded by result_hash + the audit, and the turn ends
    -- cancelled). A non-success classification (unknown) falls through to the
    -- ordinary closure below — exit 4 keeps blocked_unknown_effect (rule 1
    -- outranks the cancel).
    IF v_sess.cancellation_epoch > 0 AND v_class = 'known_success' THEN
        v_derived := 'succeeded';
        IF p_outcome <> v_derived THEN
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id, attempt_no,
                audit_key_kind, audit_key_value, result_fingerprint, reason)
            VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
                    'canonical_binding', v_computed,
                    v_sha256_hex(coalesce(p_result_payload_canonical,
                                          p_payload_canonical)),
                    'RESULT_OUTCOME_MISMATCH')
            ON CONFLICT DO NOTHING;
        END IF;
        v_result_hash := v_sha256_hex(p_result_payload_canonical);
        v_receipt_id := coalesce(p_evidence->'provider_receipt'->>'receipt_id',
                                 v_att.provider_request_id);
        UPDATE effect_requests SET
            status = 'succeeded',
            result_hash = v_result_hash,
            provider_request_id = v_receipt_id,
            updated_at = now()
         WHERE effect_id = p_effect_id;
        UPDATE effect_attempts SET
            status = 'succeeded',
            result_hash = v_result_hash,
            provider_request_id = v_receipt_id,
            completed_at = now()
         WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id, attempt_no,
            audit_key_kind, audit_key_value, result_fingerprint, reason)
        VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
                'canonical_binding', v_computed, v_result_hash,
                'COMPLETED_AFTER_CANCEL')
        ON CONFLICT DO NOTHING;

        -- The completion keeps its semantic result event (the same
        -- SQL-generated event as the normal success path — every settled
        -- effect keeps a representing trace event, so the canonicalizer's
        -- per-effect dispatch signal stays derivable).
        SELECT b.kind INTO v_batch_kind FROM batches b
         WHERE b.batch_id = v_er.batch_id;
        SELECT s.next_seq INTO v_seq FROM sessions s
         WHERE s.session_id = p_session_id;
        SELECT coalesce(max(se.internal_semantic_ordinal), 0) + 1 INTO v_iso
          FROM session_events se WHERE se.session_id = p_session_id;
        IF v_batch_kind = 'tools' THEN
            v_msg_hash := v_sha256_hex(p_result_payload_canonical);
            v_evkey := v_completion_event_key(p_session_id, 'tool/result',
                                              p_effect_id, p_attempt_no,
                                              v_msg_hash);
            INSERT INTO session_events(
                seq, session_id, event_type, event_class, schema_version,
                canonicalizer_version, event_key, turn_id, step_id, effect_id,
                payload, payload_hash, semantic_input_ordinal,
                internal_semantic_ordinal, attempt_no, command_id,
                batch_item_ordinal)
            VALUES (
                v_seq, p_session_id, 'tool/result', 'semantic', p_schema_version,
                p_canonicalizer_version, v_evkey, v_step.turn_id, v_step_id,
                p_effect_id, p_result_payload_canonical, v_msg_hash, NULL,
                v_iso, p_attempt_no, p_command_id, NULL);
            v_events := jsonb_build_array(jsonb_build_object(
                'event_type', 'tool/result', 'seq', v_seq,
                'event_key', v_evkey));
        ELSE
            v_msg_hash := v_sha256_hex(p_message_canonical);
            v_evkey := v_completion_event_key(p_session_id, 'assistant/message',
                                              p_effect_id, p_attempt_no,
                                              v_msg_hash);
            INSERT INTO session_events(
                seq, session_id, event_type, event_class, schema_version,
                canonicalizer_version, event_key, turn_id, step_id, effect_id,
                payload, payload_hash, semantic_input_ordinal,
                internal_semantic_ordinal, attempt_no, command_id,
                batch_item_ordinal)
            VALUES (
                v_seq, p_session_id, 'assistant/message', 'semantic',
                p_schema_version, p_canonicalizer_version, v_evkey,
                v_step.turn_id, v_step_id, p_effect_id, p_message_canonical,
                v_msg_hash, NULL, v_iso, p_attempt_no, p_command_id, NULL);
            v_events := jsonb_build_array(jsonb_build_object(
                'event_type', 'assistant/message', 'seq', v_seq,
                'event_key', v_evkey));
        END IF;
        UPDATE sessions SET next_seq = v_seq + 1, updated_at = now()
         WHERE session_id = p_session_id;

        -- shared judgment + applier: rule 3 cancel-wins (or rule 1/2 while a
        -- sibling is still unresolved — then the turn stays open).
        SELECT * INTO v_agg FROM v_aggregate_step(v_step_id);
        PERFORM v_apply_step_aggregation(
            p_session_id, v_step_id, v_agg.rule_no, v_agg.step_status,
            v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
            v_agg.closure_effect_ids, p_command_id, v_computed);
        v_end := v_derive_cancel_turn_end(p_session_id, p_command_id,
                                          p_schema_version,
                                          p_canonicalizer_version);
        IF v_end IS NOT NULL THEN
            v_events := v_events || jsonb_build_array(jsonb_build_object(
                'event_type', 'turn/end', 'seq', v_end->'seq',
                'event_key', v_end->>'event_key', 'reason', v_end->>'reason'));
        END IF;

        v_receipt := jsonb_build_object(
            'command_kind', 'complete_effect',
            'command_id', p_command_id,
            'classification', 'known_success',
            'cancel_closure', 'completed_after_cancel',
            'effect_id', p_effect_id,
            'attempt_no', p_attempt_no,
            'result_hash', v_result_hash,
            'events', v_events,
            'step_status', (SELECT st.status FROM steps st
                             WHERE st.step_id = v_step_id),
            'session_state', (SELECT s.state FROM sessions s
                               WHERE s.session_id = p_session_id));
        INSERT INTO command_bindings(
            session_id, command_id, first_key_kind, first_key_value, first_outcome)
        VALUES (p_session_id, p_command_id, 'canonical_request_hash',
                v_computed, 'accepted');
        INSERT INTO command_receipts(
            session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
            outcome, code, result_canonical, result_hash)
        VALUES (p_session_id, p_command_id, 'complete_effect', 'canonical_request_hash',
                v_computed, 'accepted', NULL, v_receipt::text,
                v_sha256_hex(v_receipt::text));
        RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
        RETURN;
    END IF;

    -- Declared outcome vs evidence-derived result: NEVER rejected; audited.
    -- The audit row is bound to the completion actually SETTLING by the
    -- derived result (s32b §5.2: "completion 按派生结果正常收束结算…同一事务
    -- 在 effect_audit.reason 记 RESULT_OUTCOME_MISMATCH"), so the write is
    -- deferred to after the semantic-layer checks pass — a completion later
    -- rejected by DECISION_PLAN_INVALID must not leave a mismatch audit
    -- behind. Both branch writes below share this transaction with the
    -- settlement mutations.
    v_derived := CASE v_class WHEN 'known_success' THEN 'succeeded'
                              ELSE 'unknown_outcome' END;
    v_mismatch := (p_outcome <> v_derived);

    v_events := '[]'::jsonb;
    v_iso := NULL;
    v_seq := v_sess.next_seq;

    IF v_class = 'known_success' THEN
        -- ---- G6 tool-effect settlement (batch kind='tools') ----
        -- Tool completions pass the same two-layer validation and the same
        -- four-step sequence but settle a TOOL RESULT, not a decision: the
        -- payload must be an object carrying the sealed slot's
        -- tool_call_id; the SQL-generated tool/result semantic event is the
        -- only public trace (workers MUST NOT attach events); aggregation
        -- follows rule 6's final_tools arm — all-succeeded tools batch with
        -- final_tools=true -> step succeeded, stage=closed, session ready
        -- (the turn is still open: the coordinator MUST create the next
        -- decision step; completed only enters via finish_session).
        SELECT b.kind INTO v_batch_kind FROM batches b WHERE b.batch_id = v_er.batch_id;
        IF v_batch_kind = 'tools' THEN
            IF NOT (v_res ? 'tool_call_id')
               OR jsonb_typeof(v_res->'tool_call_id') <> 'string'
               OR (v_res->>'tool_call_id') IS DISTINCT FROM v_er.tool_call_id THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                    v_computed, 'rejected_mismatch', 'TOOL_RESULT_MISMATCH',
                    'tool result payload tool_call_id does not match the sealed slot');
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'TOOL_RESULT_MISMATCH'::text, v_receipt;
                RETURN;
            END IF;
            -- Tool settlement settles by the derived (success) result, so
            -- the declared-outcome mismatch audit belongs here (same
            -- transaction as the settlement below).
            IF v_mismatch THEN
                INSERT INTO effect_audit(
                    audit_context_session_id, session_id, step_id, effect_id, attempt_no,
                    audit_key_kind, audit_key_value, result_fingerprint, reason)
                VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
                        'canonical_binding', v_computed,
                        v_sha256_hex(coalesce(p_result_payload_canonical, p_payload_canonical)),
                        'RESULT_OUTCOME_MISMATCH');
            END IF;

            -- ---- success closure (tool arm) ----
            v_result_hash := v_sha256_hex(p_result_payload_canonical);
            v_receipt_id := coalesce(p_evidence->'provider_receipt'->>'receipt_id',
                                     v_att.provider_request_id);
            UPDATE effect_requests SET
                status = 'succeeded',
                result_hash = v_result_hash,
                provider_request_id = v_receipt_id,
                updated_at = now()
             WHERE effect_id = p_effect_id;
            UPDATE effect_attempts SET
                status = 'succeeded',
                result_hash = v_result_hash,
                provider_request_id = v_receipt_id,
                completed_at = now()
             WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;

            -- Step counters recomputed from the effect table (authoritative).
            -- The decision marks and the persisted plan are NOT rewritten by
            -- a tool settlement (they were frozen by the decision result).
            UPDATE steps st SET
                pending_effect_count = (SELECT count(*) FROM effect_requests er
                                         WHERE er.step_id = st.step_id
                                           AND er.status IN ('planned', 'ready', 'dispatch_started')),
                unknown_effect_count = (SELECT count(*) FROM effect_requests er
                                         WHERE er.step_id = st.step_id
                                           AND er.status = 'unknown_outcome'),
                retryable_effect_count = (SELECT count(*) FROM effect_requests er
                                          WHERE er.step_id = st.step_id
                                            AND er.status = 'failed_retryable'),
                terminal_effect_count = (SELECT count(*) FROM effect_requests er
                                         WHERE er.step_id = st.step_id
                                           AND er.status IN ('succeeded', 'failed_terminal',
                                                             'cancelled_before_dispatch',
                                                             'cancelled_after_dispatch')),
                updated_at = now()
             WHERE st.step_id = v_step_id;

            -- SQL-generated tool/result semantic event (the ONLY public
            -- trace of the tool execution; occurrence identity
            -- (effect_id, attempt_no, payload_hash) via the shared
            -- completion-event key).
            v_msg_hash := v_sha256_hex(p_result_payload_canonical);
            v_evkey := v_completion_event_key(p_session_id, 'tool/result',
                                              p_effect_id, p_attempt_no, v_msg_hash);
            SELECT coalesce(max(se.internal_semantic_ordinal), 0) + 1 INTO v_iso
              FROM session_events se WHERE se.session_id = p_session_id;
            INSERT INTO session_events(
                seq, session_id, event_type, event_class, schema_version,
                canonicalizer_version, event_key, turn_id, step_id, effect_id,
                payload, payload_hash, semantic_input_ordinal, internal_semantic_ordinal,
                attempt_no, command_id, batch_item_ordinal)
            VALUES (
                v_seq, p_session_id, 'tool/result', 'semantic', p_schema_version,
                p_canonicalizer_version, v_evkey, v_step.turn_id, v_step_id, p_effect_id,
                p_result_payload_canonical, v_msg_hash, NULL, v_iso, p_attempt_no,
                p_command_id, NULL);
            v_events := v_events || jsonb_build_object(
                'event_type', 'tool/result', 'seq', v_seq, 'event_key', v_evkey);
            v_seq := v_seq + 1;
            v_iso := v_iso + 1;

            -- Sibling re-evaluation for the aggregation priority
            -- unknown > pending > (tools arm) all-succeeded final_tools.
            SELECT count(*) FILTER (WHERE er.status IN ('planned', 'ready', 'dispatch_started')),
                   count(*) FILTER (WHERE er.status = 'unknown_outcome')
              INTO v_pending, v_unknown
              FROM effect_requests er WHERE er.step_id = v_step_id;

            IF v_unknown > 0 THEN
                -- rule 1 (defensive here: an earlier unknown sibling).
                UPDATE steps SET status = 'blocked_unknown_effect',
                                 outcome_code = 'UNKNOWN_AFTER_DISPATCH', updated_at = now()
                 WHERE step_id = v_step_id;
                UPDATE sessions SET state = 'blocked_unknown_effect', updated_at = now()
                 WHERE session_id = p_session_id;
            ELSIF v_pending > 0 THEN
                -- rule 2: pending sibling keeps step and session waiting_effect.
                UPDATE steps SET status = 'waiting_effect', updated_at = now()
                 WHERE step_id = v_step_id;
                UPDATE sessions SET state = 'waiting_effect', updated_at = now()
                 WHERE session_id = p_session_id;
            ELSE
                -- G7a: failure siblings now persist (known_failure
                -- settlement). The aggregation priority puts
                -- failed_terminal > failed_retryable > success, so rules
                -- 4/5 outrank the final_tools terminalization whenever a
                -- failure sibling exists; the shared judgment function +
                -- applier own those rows (rule 4 closes the residual
                -- eligible siblings through the controlled edge). The
                -- plain-SQL EXISTS guard keeps earlier stage databases
                -- (effect/tools) from resolving the retry-stage functions
                -- on batches they can never produce.
                IF EXISTS (SELECT 1 FROM effect_requests er
                            WHERE er.step_id = v_step_id
                              AND er.status IN ('failed_terminal',
                                                'failed_retryable')) THEN
                    SELECT * INTO v_agg FROM v_aggregate_step(v_step_id);
                    IF v_agg.rule_no IN (4, 5) THEN
                        PERFORM v_apply_step_aggregation(
                            p_session_id, v_step_id, v_agg.rule_no,
                            v_agg.step_status, v_agg.outcome_code,
                            v_agg.session_state, v_agg.failure_code,
                            v_agg.closure_effect_ids, p_command_id, v_computed);
                    ELSE
                        RAISE EXCEPTION
                            'INFRA_PROTOCOL_VIOLATION: failure siblings present '
                            'but the aggregation derived rule % (session %, step %)',
                            v_agg.rule_no, p_session_id, v_step_id;
                    END IF;
                ELSIF NOT EXISTS (SELECT 1 FROM effect_requests er
                                   WHERE er.step_id = v_step_id AND er.status <> 'succeeded')
                      AND v_step.final_tools IS TRUE THEN
                    -- rule 6 final_tools arm: the sealed tools batch is
                    -- all-succeeded and the step carries the frozen
                    -- final_tools=true mark -> terminalize with stage=closed.
                    -- The turn is NOT closed here (decision_only=true is the
                    -- only turn-complete signal): session MUST be ready so the
                    -- coordinator creates the next decision step; completed
                    -- only enters via finish_session (Conformance 5).
                    UPDATE steps SET
                        status = 'succeeded', stage = 'closed', outcome_code = 'SUCCEEDED',
                        closed_at = now(), updated_at = now()
                     WHERE step_id = v_step_id;
                    UPDATE sessions SET state = 'ready', updated_at = now()
                     WHERE session_id = p_session_id;
                ELSE
                    -- Unreachable: a settled tools batch with no unknown,
                    -- pending or failure siblings is all-succeeded.
                    RAISE EXCEPTION
                        'INFRA_PROTOCOL_VIOLATION: tools batch has neither unknown, pending nor failure '
                        'siblings but is not all-succeeded/final_tools (session %, step %)',
                        p_session_id, v_step_id;
                END IF;
            END IF;

            v_receipt := jsonb_build_object(
                'command_kind', 'complete_effect',
                'command_id', p_command_id,
                'classification', 'known_success',
                'effect_id', p_effect_id,
                'attempt_no', p_attempt_no,
                'result_hash', v_result_hash,
                'events', v_events,
                'step_status', (SELECT st.status FROM steps st WHERE st.step_id = v_step_id),
                'session_state', (SELECT s.state FROM sessions s WHERE s.session_id = p_session_id));
            UPDATE sessions SET next_seq = v_seq, updated_at = now()
             WHERE session_id = p_session_id;
            INSERT INTO command_bindings(
                session_id, command_id, first_key_kind, first_key_value, first_outcome)
            VALUES (p_session_id, p_command_id, 'canonical_request_hash',
                    v_computed, 'accepted');
            INSERT INTO command_receipts(
                session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
                outcome, code, result_canonical, result_hash)
            VALUES (p_session_id, p_command_id, 'complete_effect', 'canonical_request_hash',
                    v_computed, 'accepted', NULL, v_receipt::text,
                    v_sha256_hex(v_receipt::text));
            RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
            RETURN;
        END IF;

        -- ---- semantic layer: decision marks bidirectional mutex (X02+Y02:
        -- entry is a successful decision result entering terminal
        -- settlement; the check is written in full even though P0B only
        -- exercises the empty-plan branch). ----
        IF v_res->'message' IS NULL OR jsonb_typeof(v_res->'message') <> 'object'
           OR v_res->'tools' IS NULL OR jsonb_typeof(v_res->'tools') <> 'array'
           OR v_res->'decision_only' IS NULL
           OR jsonb_typeof(v_res->'decision_only') <> 'boolean'
           OR v_res->'final_tools' IS NULL
           OR jsonb_typeof(v_res->'final_tools') <> 'boolean' THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
                'successful decision result requires message/tools/decision_only/final_tools');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        v_tools_empty := jsonb_array_length(v_res->'tools') = 0;
        v_do := (v_res->>'decision_only')::boolean;
        v_ft := (v_res->>'final_tools')::boolean;
        IF NOT ((v_tools_empty AND v_do AND NOT v_ft)
                OR (NOT v_tools_empty AND NOT v_do AND v_ft)) THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                v_computed, 'rejected_mismatch', 'DECISION_PLAN_INVALID',
                'decision marks/tools plan combination violates the bidirectional mutex schema');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'DECISION_PLAN_INVALID'::text, v_receipt;
            RETURN;
        END IF;

        -- Normalized tools plan (digest 2.6.1: the successful decision
        -- result MUST persist the normalized tools plan; the later tools
        -- seal recomputes plan_hash from the persisted plan, 2.6.2 step 2).
        -- The plan text is produced by the shared Python canonical profile
        -- (same convention as every other canonical column); SQL validates
        -- that it parses and is jsonb-equal to the result payload's tools
        -- member, so the persisted bytes bind to the settled result.
        IF p_plan_canonical IS NULL THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                v_computed, 'rejected_mismatch', 'DECISION_PLAN_INVALID',
                'successful decision result requires the normalized tools plan canonical text');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'DECISION_PLAN_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        BEGIN
            v_plan := p_plan_canonical::jsonb;
        EXCEPTION WHEN OTHERS THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                v_computed, 'rejected_mismatch', 'DECISION_PLAN_INVALID',
                'tools plan canonical text is not valid JSON');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'DECISION_PLAN_INVALID'::text, v_receipt;
            RETURN;
        END;
        IF jsonb_typeof(v_plan) <> 'array' OR v_plan IS DISTINCT FROM (v_res->'tools') THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
                v_computed, 'rejected_mismatch', 'DECISION_PLAN_INVALID',
                'tools plan canonical does not match the result payload tools member');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'DECISION_PLAN_INVALID'::text, v_receipt;
            RETURN;
        END IF;

        -- Semantic layer passed: the completion settles by the derived
        -- (success) result, so this is where the declared-outcome mismatch
        -- audit belongs (same transaction as the settlement below).
        IF v_mismatch THEN
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id, attempt_no,
                audit_key_kind, audit_key_value, result_fingerprint, reason)
            VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
                    'canonical_binding', v_computed,
                    v_sha256_hex(coalesce(p_result_payload_canonical, p_payload_canonical)),
                    'RESULT_OUTCOME_MISMATCH');
        END IF;

        -- ---- success closure ----
        v_result_hash := v_sha256_hex(p_result_payload_canonical);
        v_receipt_id := coalesce(p_evidence->'provider_receipt'->>'receipt_id',
                                 v_att.provider_request_id);
        UPDATE effect_requests SET
            status = 'succeeded',
            result_hash = v_result_hash,
            provider_request_id = v_receipt_id,
            updated_at = now()
         WHERE effect_id = p_effect_id;
        UPDATE effect_attempts SET
            status = 'succeeded',
            result_hash = v_result_hash,
            provider_request_id = v_receipt_id,
            completed_at = now()
         WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;

        -- Step counters recomputed from the effect table (authoritative).
        UPDATE steps st SET
            pending_effect_count = (SELECT count(*) FROM effect_requests er
                                     WHERE er.step_id = st.step_id
                                       AND er.status IN ('planned', 'ready', 'dispatch_started')),
            unknown_effect_count = (SELECT count(*) FROM effect_requests er
                                     WHERE er.step_id = st.step_id
                                       AND er.status = 'unknown_outcome'),
            retryable_effect_count = (SELECT count(*) FROM effect_requests er
                                      WHERE er.step_id = st.step_id
                                        AND er.status = 'failed_retryable'),
            terminal_effect_count = (SELECT count(*) FROM effect_requests er
                                     WHERE er.step_id = st.step_id
                                       AND er.status IN ('succeeded', 'failed_terminal',
                                                         'cancelled_before_dispatch',
                                                         'cancelled_after_dispatch')),
            decision_only = v_do,
            final_tools = v_ft,
            -- Persist the normalized tools plan and freeze plan_hash OVER
            -- THE PLAN (not the full result payload): the later tools seal
            -- recomputes plan_hash from the persisted plan (digest 2.6.2
            -- step 2). The decision_only branch keeps both NULL — its
            -- empty plan is fully determined by the decision_only mark.
            plan_canonical = CASE WHEN NOT v_do THEN p_plan_canonical
                                  ELSE st.plan_canonical END,
            plan_hash = CASE WHEN NOT v_do THEN v_sha256_hex(p_plan_canonical)
                             ELSE st.plan_hash END,
            updated_at = now()
         WHERE st.step_id = v_step_id;

        -- SQL-generated assistant/message semantic event (the ONLY public
        -- trace of the result; workers MUST NOT attach events). Internal
        -- semantic ordinal allocated inside the session row lock; seq from
        -- the unified allocator.
        v_msg_hash := v_sha256_hex(p_message_canonical);
        v_evkey := v_completion_event_key(p_session_id, 'assistant/message',
                                          p_effect_id, p_attempt_no, v_msg_hash);
        SELECT coalesce(max(se.internal_semantic_ordinal), 0) + 1 INTO v_iso
          FROM session_events se WHERE se.session_id = p_session_id;
        INSERT INTO session_events(
            seq, session_id, event_type, event_class, schema_version,
            canonicalizer_version, event_key, turn_id, step_id, effect_id,
            payload, payload_hash, semantic_input_ordinal, internal_semantic_ordinal,
            attempt_no, command_id, batch_item_ordinal)
        VALUES (
            v_seq, p_session_id, 'assistant/message', 'semantic', p_schema_version,
            p_canonicalizer_version, v_evkey, v_step.turn_id, v_step_id, p_effect_id,
            p_message_canonical, v_msg_hash, NULL, v_iso, p_attempt_no,
            p_command_id, NULL);
        v_events := v_events || jsonb_build_object(
            'event_type', 'assistant/message', 'seq', v_seq, 'event_key', v_evkey);
        v_seq := v_seq + 1;
        v_iso := v_iso + 1;

        -- Sibling re-evaluation for the aggregation priority
        -- unknown > pending > ... > success.
        SELECT count(*) FILTER (WHERE er.status IN ('planned', 'ready', 'dispatch_started')),
               count(*) FILTER (WHERE er.status = 'unknown_outcome')
          INTO v_pending, v_unknown
          FROM effect_requests er WHERE er.step_id = v_step_id;

        IF v_unknown > 0 THEN
            -- rule 1 (defensive here: an earlier unknown sibling).
            UPDATE steps SET status = 'blocked_unknown_effect',
                             outcome_code = 'UNKNOWN_AFTER_DISPATCH', updated_at = now()
             WHERE step_id = v_step_id;
            UPDATE sessions SET state = 'blocked_unknown_effect', updated_at = now()
             WHERE session_id = p_session_id;
        ELSIF v_pending > 0 THEN
            -- rule 2: pending sibling keeps step and session waiting_effect.
            UPDATE steps SET status = 'waiting_effect', updated_at = now()
             WHERE step_id = v_step_id;
            UPDATE sessions SET state = 'waiting_effect', updated_at = now()
             WHERE session_id = p_session_id;
        ELSIF v_do THEN
            -- rule 6 success branch: terminalize the closing step.
            UPDATE steps SET
                status = 'succeeded', stage = 'closed', outcome_code = 'SUCCEEDED',
                closed_at = now(), updated_at = now()
             WHERE step_id = v_step_id;
            -- Shared turn-close judgment (also used by finish_session).
            SELECT * INTO v_fin FROM v_session_finalize(p_session_id, v_step.turn_id);
            IF NOT v_fin.closed THEN
                RAISE EXCEPTION
                    'INFRA_PROTOCOL_VIOLATION: turn-close judgment failed after a '
                    'clean decision_only success (session %, turn %)',
                    p_session_id, v_step.turn_id;
            END IF;
            -- Turn closure: known turn/end {interrupted:false} + slot row.
            v_end_payload := '{"interrupted":false}';
            v_end_hash := v_sha256_hex(v_end_payload);
            v_endkey := v_completion_event_key(p_session_id, 'turn/end',
                                               p_effect_id, p_attempt_no, v_end_hash);
            INSERT INTO session_events(
                seq, session_id, event_type, event_class, schema_version,
                canonicalizer_version, event_key, turn_id, step_id, effect_id,
                payload, payload_hash, semantic_input_ordinal, internal_semantic_ordinal,
                attempt_no, command_id, batch_item_ordinal)
            VALUES (
                v_seq, p_session_id, 'turn/end', 'semantic', p_schema_version,
                p_canonicalizer_version, v_endkey, v_step.turn_id, NULL, NULL,
                v_end_payload, v_end_hash, NULL, v_iso, NULL, p_command_id, NULL);
            v_events := v_events || jsonb_build_object(
                'event_type', 'turn/end', 'seq', v_seq, 'event_key', v_endkey);
            v_seq := v_seq + 1;
            INSERT INTO turn_end_slots(
                session_id, turn_id, turn_end_key, head_event_key, slot_status,
                resolution_identity_canonical, version)
            VALUES (
                p_session_id, v_step.turn_id,
                v_turn_end_key(p_session_id, v_step.turn_id),
                v_endkey, 'known', convert_to(v_end_payload, 'UTF8'), 1);
            -- Aggregation NEVER derives completed: rule 6 targets ready;
            -- only finish_session completes.
            UPDATE sessions SET state = 'ready', updated_at = now()
             WHERE session_id = p_session_id;
        ELSE
            -- final_tools branch: step waits the tools seal (LATER).
            UPDATE steps SET status = 'ready', updated_at = now()
             WHERE step_id = v_step_id;
            UPDATE sessions SET state = 'ready', updated_at = now()
             WHERE session_id = p_session_id;
        END IF;

        v_receipt := jsonb_build_object(
            'command_kind', 'complete_effect',
            'command_id', p_command_id,
            'classification', 'known_success',
            'effect_id', p_effect_id,
            'attempt_no', p_attempt_no,
            'result_hash', v_result_hash,
            'events', v_events,
            'step_status', (SELECT st.status FROM steps st WHERE st.step_id = v_step_id),
            'session_state', (SELECT s.state FROM sessions s WHERE s.session_id = p_session_id));
    ELSE
        -- ---- unknown closure (rule 1): effect unknown_outcome, unique
        -- provisional turn/end {outcome:unknown}, provisional slot row,
        -- step/session blocked_unknown_effect. ----
        -- The unknown closure is itself a settlement by the derived result,
        -- so the declared-outcome mismatch audit is written here (same
        -- transaction as the settlement below).
        IF v_mismatch THEN
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id, attempt_no,
                audit_key_kind, audit_key_value, result_fingerprint, reason)
            VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
                    'canonical_binding', v_computed,
                    v_sha256_hex(coalesce(p_result_payload_canonical, p_payload_canonical)),
                    'RESULT_OUTCOME_MISMATCH');
        END IF;
        UPDATE effect_requests SET status = 'unknown_outcome', updated_at = now()
         WHERE effect_id = p_effect_id;
        UPDATE effect_attempts SET status = 'unknown_outcome', completed_at = now()
         WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;

        UPDATE steps st SET
            pending_effect_count = (SELECT count(*) FROM effect_requests er
                                     WHERE er.step_id = st.step_id
                                       AND er.status IN ('planned', 'ready', 'dispatch_started')),
            unknown_effect_count = (SELECT count(*) FROM effect_requests er
                                     WHERE er.step_id = st.step_id
                                       AND er.status = 'unknown_outcome'),
            retryable_effect_count = (SELECT count(*) FROM effect_requests er
                                      WHERE er.step_id = st.step_id
                                        AND er.status = 'failed_retryable'),
            terminal_effect_count = (SELECT count(*) FROM effect_requests er
                                     WHERE er.step_id = st.step_id
                                       AND er.status IN ('succeeded', 'failed_terminal',
                                                         'cancelled_before_dispatch',
                                                         'cancelled_after_dispatch')),
            status = 'blocked_unknown_effect',
            outcome_code = 'UNKNOWN_AFTER_DISPATCH',
            updated_at = now()
         WHERE st.step_id = v_step_id;

        -- Unique provisional end per turn: the slot row is the creation
        -- entry point and UNIQUE(session_id, turn_id) collapses concurrency.
        -- The event carries the effect attribution the creation key already
        -- binds (v_completion_event_key(session,'turn/end',effect,attempt)),
        -- so the canonicalizer's per-effect control signal stays derivable
        -- from the event stream alone (G8b note).
        IF NOT EXISTS (SELECT 1 FROM turn_end_slots tes
                        WHERE tes.session_id = p_session_id
                          AND tes.turn_id = v_step.turn_id) THEN
            v_end_payload := '{"outcome":"unknown"}';
            v_end_hash := v_sha256_hex(v_end_payload);
            v_endkey := v_completion_event_key(p_session_id, 'turn/end',
                                               p_effect_id, p_attempt_no, v_end_hash);
            SELECT coalesce(max(se.internal_semantic_ordinal), 0) + 1 INTO v_iso
              FROM session_events se WHERE se.session_id = p_session_id;
            INSERT INTO session_events(
                seq, session_id, event_type, event_class, schema_version,
                canonicalizer_version, event_key, turn_id, step_id, effect_id,
                payload, payload_hash, semantic_input_ordinal, internal_semantic_ordinal,
                attempt_no, command_id, batch_item_ordinal)
            VALUES (
                v_seq, p_session_id, 'turn/end', 'semantic', p_schema_version,
                p_canonicalizer_version, v_endkey, v_step.turn_id, v_step_id, p_effect_id,
                v_end_payload, v_end_hash, NULL, v_iso, p_attempt_no, p_command_id, NULL);
            v_events := v_events || jsonb_build_object(
                'event_type', 'turn/end', 'seq', v_seq, 'event_key', v_endkey);
            v_seq := v_seq + 1;
            INSERT INTO turn_end_slots(
                session_id, turn_id, turn_end_key, head_event_key, slot_status,
                resolution_identity_canonical, version)
            VALUES (
                p_session_id, v_step.turn_id,
                v_turn_end_key(p_session_id, v_step.turn_id),
                v_endkey, 'provisional', NULL, 1);
        END IF;
        -- assistant/partial prefix events would be synthesized here when
        -- accepted chunks exist; P0B executes non-streaming effects only
        -- and session_events carries no chunk_index column, so the merge
        -- stays LATER.

        UPDATE sessions SET state = 'blocked_unknown_effect', updated_at = now()
         WHERE session_id = p_session_id;

        v_receipt := jsonb_build_object(
            'command_kind', 'complete_effect',
            'command_id', p_command_id,
            'classification', 'unknown',
            'effect_id', p_effect_id,
            'attempt_no', p_attempt_no,
            'events', v_events,
            'step_status', 'blocked_unknown_effect',
            'session_state', 'blocked_unknown_effect');
        -- Receipt annotation (not a rejection code): the unknown
        -- classification was caused by an evidence object that is not
        -- bound to the settled attempt — missing or mismatched
        -- effect_id/attempt_no (e.g. a receipt minted for another effect).
        IF NOT v_bound THEN
            v_receipt := v_receipt || jsonb_build_object(
                'code', 'EVIDENCE_NOT_BOUND',
                'detail', 'evidence object does not carry a matching (effect_id, attempt_no) binding; classified unknown');
        END IF;
    END IF;

    UPDATE sessions SET next_seq = v_seq, updated_at = now()
     WHERE session_id = p_session_id;

    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
        outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'complete_effect', 'canonical_request_hash',
            v_computed, 'accepted', NULL, v_receipt::text,
            v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_finish_session — claimed -> completed (s31a transition table; the ONLY
-- completed entry). Guard shares the rule-6 judgment function
-- v_session_finalize: every step of the turn succeeded, the last one is a
-- decision_only=true closing step, and no unsealed plan or pending work.
-- Terminalization clears active_step_id and releases the lease with a
-- fence bump in the same transaction.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_finish_session(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint, p_session_fence bigint,
    p_declared_hash text, p_payload_canonical text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_fin record;
    v_fence bigint;
BEGIN
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'finish_session',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;

    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'finish_session',
            v_computed, 'rejected_stale', 'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session control row');
        RETURN QUERY SELECT 'rejected_stale'::text, 'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF p_session_fence IS DISTINCT FROM v_sess.session_fence THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'finish_session',
            v_computed, 'rejected_stale', 'SESSION_FENCE_STALE',
            format('expected session_fence %s does not match current %s',
                   coalesce(p_session_fence::text, 'NULL'), v_sess.session_fence));
        RETURN QUERY SELECT 'rejected_stale'::text, 'SESSION_FENCE_STALE'::text, v_receipt;
        RETURN;
    END IF;
    -- completed only enters from claimed (transition table row).
    IF v_sess.state <> 'claimed' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'finish_session',
            v_computed, 'rejected_mismatch', 'SESSION_NOT_CLAIMED',
            format('finish_session requires state=claimed, got %s', v_sess.state));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_NOT_CLAIMED'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.lease_owner IS NULL OR v_sess.lease_until IS NULL
       OR v_sess.lease_until <= now() THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'finish_session',
            v_computed, 'rejected_stale', 'LEASE_NOT_HELD',
            'coordination lease vacant or expired');
        RETURN QUERY SELECT 'rejected_stale'::text, 'LEASE_NOT_HELD'::text, v_receipt;
        RETURN;
    END IF;

    -- Shared judgment (same SQL predicate as aggregation rule 6).
    SELECT * INTO v_fin FROM v_session_finalize(p_session_id, NULL);
    IF NOT v_fin.closed OR v_fin.open_work THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'finish_session',
            v_computed, 'rejected_mismatch', 'SESSION_NOT_FINALIZABLE',
            'turn not closed by a successful decision_only step, or open work remains');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_NOT_FINALIZABLE'::text, v_receipt;
        RETURN;
    END IF;

    v_fence := v_sess.session_fence + 1;
    UPDATE sessions SET
        state = 'completed',
        session_fence = v_fence,
        lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
        active_step_id = NULL,
        updated_at = now()
     WHERE session_id = p_session_id;

    v_receipt := jsonb_build_object(
        'command_kind', 'finish_session',
        'command_id', p_command_id,
        'state', 'completed',
        'session_fence', v_fence);

    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
        outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'finish_session', 'canonical_request_hash',
            v_computed, 'accepted', NULL, v_receipt::text,
            v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;
