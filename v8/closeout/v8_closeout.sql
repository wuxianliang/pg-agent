-- v8 G19b (closeout stage): the v8 tail machinery — the NOTIFY/wait wake
-- layer (D7), the attempt/heartbeat protected observation split (D8),
-- FORCE_JOB_TAKEOVER with its five outcomes (D9) and the reconcile
-- result-receipt entry (D10, X01: the one legal terminal settlement path
-- under quiescing; OBSERVATION_WRONG_ENTRY for the (iii)/(iv) forms).
--
-- D12 (cross-attempt residue), D14 (credential-missing regression) and
-- D15 (capability API boundary, DB half) are asserted by the gate against
-- the existing machinery — no new SQL.

-- ---------------------------------------------------------------------------
-- 1. D7 — the wait/wake layer. transition_wait re-checks the condition in
--    the SAME transaction; only an unsatisfied condition writes the wait
--    registration and releases the lease. NOTIFY is a HINT only: the scan
--    is the recovery authority (lost / duplicated / reordered
--    notifications and a disabled NOTIFY all converge through it).
-- ---------------------------------------------------------------------------
CREATE TABLE wait_registrations (
    session_id      uuid NOT NULL REFERENCES sessions(session_id),
    registration_id bigint NOT NULL CHECK (registration_id >= 1),
    -- Closed predicate forms: {'kind':'seq_at_least','value':N} (an event
    -- seq threshold) and {'kind':'timer','wake_at':ISO ts}.
    predicate       jsonb NOT NULL,
    observed_version bigint NOT NULL,
    state           text NOT NULL DEFAULT 'waiting'
                    CONSTRAINT wait_state_check
                    CHECK (state IN ('waiting', 'ready')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    woken_at        timestamptz,
    PRIMARY KEY (session_id, registration_id)
);

CREATE FUNCTION v_wait_predicate_holds(
    p_session_id uuid, p_predicate jsonb
) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT CASE p_predicate->>'kind'
        WHEN 'seq_at_least' THEN
            (SELECT s.next_seq - 1 >= (p_predicate->>'value')::bigint
               FROM sessions s WHERE s.session_id = p_session_id)
        WHEN 'timer' THEN
            now() >= (p_predicate->>'wake_at')::timestamptz
        ELSE NULL
    END;
$$;

-- transition_wait(fence, predicate, observed_version): locks the session
-- row (position 1), re-checks the condition in the SAME transaction.
-- Satisfied -> not waiting (no row, the lease is untouched). Unsatisfied
-- -> the wait registration persists, the session moves to its waiting
-- state and the coordination lease is released (state leaving claimed
-- revokes the lease and bumps the fence — the controlled-transaction
-- rule). Returns the outcome for the caller.
CREATE FUNCTION v_transition_wait(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint, p_session_fence bigint,
    p_predicate jsonb, p_observed_version bigint,
    p_is_sleep boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_holds boolean;
    v_id bigint;
    v_fence bigint;
BEGIN
    SELECT * INTO v_sess FROM sessions s
     WHERE s.session_id = p_session_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'SESSION_NOT_FOUND');
    END IF;
    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch
       OR p_session_fence IS DISTINCT FROM v_sess.session_fence THEN
        RETURN jsonb_build_object('outcome', 'rejected_stale',
                                  'code', 'DRIVER_EPOCH_STALE');
    END IF;
    IF p_is_sleep AND (p_predicate->>'kind') <> 'timer' THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'PREDICATE_INVALID');
    END IF;

    v_holds := v_wait_predicate_holds(p_session_id, p_predicate);
    IF v_holds IS NULL THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'PREDICATE_INVALID');
    END IF;
    IF v_holds THEN
        -- The condition already holds: not waiting, zero side effects
        -- (the lease keeps running; no wait row is written).
        RETURN jsonb_build_object('outcome', 'accepted', 'waiting', false);
    END IF;

    SELECT coalesce(max(registration_id), 0) + 1 INTO v_id
      FROM wait_registrations WHERE session_id = p_session_id;
    INSERT INTO wait_registrations(
        session_id, registration_id, predicate, observed_version)
    VALUES (p_session_id, v_id, p_predicate, p_observed_version);

    v_fence := v_sess.session_fence + 1;
    UPDATE sessions SET
        state = CASE WHEN p_is_sleep THEN 'sleeping' ELSE 'waiting_event' END,
        session_fence = v_fence,
        lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
        updated_at = now()
     WHERE session_id = p_session_id;

    RETURN jsonb_build_object('outcome', 'accepted', 'waiting', true,
                              'registration_id', v_id,
                              'session_fence', v_fence);
END;
$$;

-- The wake HINT (NOTIFY only): a helper the completion/settlement paths
-- MAY call after commit-worthy progress; it never carries authority.
CREATE FUNCTION v_wait_notify(p_session_id uuid, p_payload text)
RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('v8_wait', jsonb_build_object(
        'session_id', p_session_id, 'payload', p_payload)::text);
END;
$$;

-- The scan (the recovery authority): wakes due timers, satisfied
-- predicates and expired-lease claimed sessions. Idempotent — a rerun
-- over an already-woken session is a no-op (convergence without NOTIFY).
CREATE FUNCTION v_wait_scan() RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_woken int := 0;
    v_fence bigint;
    r record;
BEGIN
    -- Waiting registrations whose predicate now holds -> ready.
    FOR r IN
        SELECT wr.*, s.session_fence AS cur_fence
          FROM wait_registrations wr
          JOIN sessions s ON s.session_id = wr.session_id
         WHERE wr.state = 'waiting'
           AND v_wait_predicate_holds(wr.session_id, wr.predicate)
           AND s.state IN ('waiting_event', 'sleeping')
         FOR UPDATE OF wr
    LOOP
        v_fence := r.cur_fence + 1;
        UPDATE wait_registrations SET state = 'ready', woken_at = now()
         WHERE session_id = r.session_id
           AND registration_id = r.registration_id;
        UPDATE sessions SET state = 'ready', session_fence = v_fence,
                             updated_at = now()
         WHERE session_id = r.session_id;
        v_woken := v_woken + 1;
    END LOOP;
    -- Expired claimed leases recover to ready (the scan half of the
    -- recovery contract; the fence bump invalidates the dead owner).
    FOR r IN
        SELECT s.session_id, s.session_fence AS cur_fence
          FROM sessions s
         WHERE s.state = 'claimed'
           AND s.lease_until IS NOT NULL AND s.lease_until <= now()
         FOR UPDATE
    LOOP
        v_fence := r.cur_fence + 1;
        UPDATE sessions SET state = 'ready', session_fence = v_fence,
                             lease_owner = NULL, lease_until = NULL,
                             lease_purpose = NULL, updated_at = now()
         WHERE session_id = r.session_id;
        v_woken := v_woken + 1;
    END LOOP;
    RETURN jsonb_build_object('outcome', 'accepted', 'woken', v_woken);
END;
$$;

-- ---------------------------------------------------------------------------
-- 2. D8 — attempt/heartbeat, the protected observation write (O01 (α))
--    with the four-check split and the session lifecycle gate.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_attempt_heartbeat(
    p_session_id uuid, p_command_id text,
    p_effect_id uuid, p_attempt_no bigint,
    p_lease_owner text, p_lease_fence bigint,
    p_payload_canonical text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_er effect_requests%ROWTYPE;
    v_att effect_attempts%ROWTYPE;
    v_ord bigint;
    v_digest text;
    v_evkey text;
    v_seq bigint;
    v_epoch_note jsonb := NULL;
BEGIN
    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id;
    SELECT * INTO v_er FROM effect_requests er WHERE er.effect_id = p_effect_id;
    SELECT * INTO v_att FROM effect_attempts a
     WHERE a.effect_id = p_effect_id AND a.attempt_no = p_attempt_no;

    -- (i) attempt attribution: the attempt MUST be a persisted row of
    -- THIS session.
    IF v_er.session_id IS DISTINCT FROM p_session_id OR v_att.effect_id IS NULL THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'ATTEMPT_NOT_FOUND');
    END IF;
    -- Session lifecycle gate: terminal x attempt NON-terminal is allowed
    -- (the failure-drain observation need); an attempt already terminal
    -- rejects (terminalization leaves audit/receipt replay only).
    IF v_sess.state IN ('completed', 'failed', 'cancelled')
       AND v_att.status IN ('succeeded', 'failed_terminal',
                            'cancelled_before_dispatch',
                            'cancelled_after_dispatch') THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'ATTEMPT_TERMINAL');
    END IF;
    IF v_att.status IN ('succeeded', 'failed_terminal',
                        'cancelled_before_dispatch',
                        'cancelled_after_dispatch') THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'ATTEMPT_TERMINAL');
    END IF;
    -- (iv) superseded -> fixed rejected_stale.
    IF v_att.superseded_by_attempt_no IS NOT NULL THEN
        RETURN jsonb_build_object('outcome', 'rejected_stale',
                                  'code', 'ATTEMPT_SUPERSEDED');
    END IF;
    -- (iii) the writer MUST be the attempt's current job lease owner with
    -- a matching fence. EXCEPTIONS (quiescing and terminal failure-drain):
    -- an OLD-EPOCH worker heartbeat is accepted with the epoch difference
    -- recorded — never a lease renewal, zero control state.
    IF v_er.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_er.current_job_fence <> p_lease_fence THEN
        IF v_sess.driver_mode <> 'quiescing'
           AND v_sess.state NOT IN ('failed', 'cancelled') THEN
            RETURN jsonb_build_object('outcome', 'rejected_stale',
                                      'code', 'LEASE_OWNER_MISMATCH');
        END IF;
        v_epoch_note := jsonb_build_object(
            'submitted_owner', p_lease_owner,
            'submitted_fence', p_lease_fence,
            'epoch_mismatch_recorded', true);
    END IF;
    -- (ii) not terminal is implied past this point (dispatch_started /
    -- unknown / ready attempts may carry heartbeats).

    SELECT coalesce(max(se.observation_ordinal), 0) + 1 INTO v_ord
      FROM session_events se
     WHERE se.session_id = p_session_id
       AND se.effect_id = p_effect_id
       AND se.attempt_no = p_attempt_no;
    v_digest := v_sha256_hex(p_payload_canonical);
    v_evkey := v_completion_event_key(
        p_session_id, 'attempt/heartbeat', p_effect_id, p_attempt_no,
        v_sha256_hex(v_digest || ':' || v_ord::text));
    SELECT s.next_seq INTO v_seq FROM sessions s
     WHERE s.session_id = p_session_id FOR UPDATE;
    INSERT INTO session_events(
        seq, session_id, event_type, event_class, schema_version,
        canonicalizer_version, event_key, turn_id, step_id, effect_id,
        payload, payload_hash, attempt_no, command_id, observation_ordinal)
    VALUES (
        v_seq, p_session_id, 'attempt/heartbeat', 'observational',
        'sv@1', 'canon@1', v_evkey,
        (SELECT st.turn_id FROM steps st WHERE st.step_id = v_er.step_id),
        v_er.step_id, p_effect_id, p_payload_canonical, v_digest,
        p_attempt_no, p_command_id, v_ord);
    UPDATE sessions SET next_seq = v_seq + 1, updated_at = now()
     WHERE session_id = p_session_id;

    RETURN jsonb_build_object(
        'outcome', 'accepted',
        'effect_id', p_effect_id, 'attempt_no', p_attempt_no,
        'observation_ordinal', v_ord,
        'event_key', v_evkey,
        'session_state', v_sess.state) || coalesce(v_epoch_note,
                                                   '{}'::jsonb);
END;
$$;

-- ---------------------------------------------------------------------------
-- 3. D9 — FORCE_JOB_TAKEOVER: the operator-authorized controlled internal
--    entry that revokes a STILL-VALID job lease and takes over (spec
--    §3.1.1; the only path besides expiry). Five outcomes in the frozen
--    order: isolation -> target -> stale -> precondition -> execution.
--    The success lock set is the §3.2.2 step-1 full eight-position
--    prelock (session -> grant/slice -> generation -> step -> effect ->
--    attempt; turn_end_slot and compact positions stay posterior), the
--    same lock-order implementation the recovery takeover uses.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_force_job_takeover(
    p_session_id uuid, p_command_id text,
    p_operator text, p_force_reason text,
    p_driver text, p_driver_epoch bigint,
    p_effect_id uuid,
    p_expected_job_fence bigint, p_expected_lease_owner text,
    p_evidence jsonb DEFAULT NULL,
    p_declared_hash text DEFAULT NULL,
    p_payload_canonical text DEFAULT NULL
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(coalesce(p_payload_canonical, ''));
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_er effect_requests%ROWTYPE;
    v_att record;
    v_newf bigint;
    v_alloc jsonb;
    v_agg record;
BEGIN
    -- (5) isolation gate FIRST, zero locks zero control state (the
    --     recovery-takeover entry gate, the fourth entry of A97's set).
    IF current_setting('transaction_isolation', true) <> 'read committed' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'force_job_takeover', v_computed, 'rejected_mismatch',
            'ISOLATION_UNSUPPORTED',
            format('force_job_takeover requires READ COMMITTED, got %s',
                   coalesce(current_setting('transaction_isolation', true),
                            'default')));
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'ISOLATION_UNSUPPORTED'::text, v_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'force_job_takeover',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    -- Position 1 + the effect/attempt tail of the master order.
    SELECT * INTO v_sess FROM sessions s
     WHERE s.session_id = p_session_id FOR UPDATE;
    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'force_job_takeover', v_computed, 'rejected_stale',
            'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session');
        RETURN QUERY SELECT 'rejected_stale'::text,
                           'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_er FROM effect_requests er
     WHERE er.effect_id = p_effect_id AND er.session_id = p_session_id
     FOR UPDATE;
    -- (2) target missing / already terminal -> rejected_mismatch.
    IF NOT FOUND THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'force_job_takeover', v_computed, 'rejected_mismatch',
            'EFFECT_NOT_FOUND',
            'the takeover target does not exist on this session');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'EFFECT_NOT_FOUND'::text, v_receipt;
        RETURN;
    END IF;
    SELECT * INTO v_att FROM effect_attempts a
     WHERE a.effect_id = p_effect_id
     ORDER BY a.attempt_no DESC LIMIT 1 FOR UPDATE;
    IF v_er.status NOT IN ('ready', 'dispatch_started')
       OR v_att.status NOT IN ('ready', 'dispatch_started') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'force_job_takeover', v_computed, 'rejected_mismatch',
            'ATTEMPT_ALREADY_SETTLED',
            format('the takeover target is not in flight (effect %s,'
                   ' attempt %s)', v_er.status, v_att.status));
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'ATTEMPT_ALREADY_SETTLED'::text, v_receipt;
        RETURN;
    END IF;

    -- (3) expected fence / lease owner mismatch -> rejected_stale.
    IF v_er.current_job_fence <> p_expected_job_fence
       OR v_er.lease_owner IS DISTINCT FROM p_expected_lease_owner THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'force_job_takeover', v_computed, 'rejected_stale',
            'JOB_FENCE_STALE',
            format('expected job fence/lease owner (%s/%s) does not match'
                   ' the current (%s/%s)',
                   coalesce(p_expected_job_fence::text, 'NULL'),
                   coalesce(p_expected_lease_owner, 'NULL'),
                   v_er.current_job_fence::text,
                   coalesce(v_er.lease_owner, 'NULL')));
        RETURN QUERY SELECT 'rejected_stale'::text,
                           'JOB_FENCE_STALE'::text, v_receipt;
        RETURN;
    END IF;

    -- (4) precondition: a normal recovery would do — the lease is already
    --     dead (vacant or expired); force is not required.
    IF v_er.lease_owner IS NULL
       OR v_er.lease_until IS NULL OR v_er.lease_until <= now() THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'force_job_takeover', v_computed, 'rejected_mismatch',
            'FORCE_NOT_REQUIRED',
            'the job lease is already vacant or expired: the normal '
            'recovery takeover applies');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'FORCE_NOT_REQUIRED'::text, v_receipt;
        RETURN;
    END IF;

    -- (1) execution: the force reason is bounded (<=4096 bytes).
    IF length(coalesce(p_force_reason, '')) > 4096 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'force_job_takeover', v_computed, 'rejected_mismatch',
            'FORCE_REASON_TOO_LONG',
            'the force reason exceeds the 4096-byte bound');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'FORCE_REASON_TOO_LONG'::text, v_receipt;
        RETURN;
    END IF;

    -- CAS advance + lease revocation + old-attempt settlement, the same
    -- settlement core shape as the recovery takeover (evidence judged by
    -- the unique classifier; no evidence -> unknown). The operator
    -- identity + force reason land in the audit and the receipt.
    v_newf := nextval('v8_job_fence_seq');
    UPDATE effect_requests SET
        current_job_fence = v_newf,
        lease_owner = NULL, lease_until = NULL,
        updated_at = now()
     WHERE effect_id = p_effect_id;

    INSERT INTO grant_ops_audit(operator_id, action, target_id, details)
    VALUES (p_operator, 'revoke_grant', p_effect_id::text,
            jsonb_build_object('action', 'force_job_takeover',
                               'reason', p_force_reason,
                               'revoked_lease_owner', p_expected_lease_owner,
                               'old_job_fence', p_expected_job_fence,
                               'new_job_fence', v_newf));

    v_receipt := jsonb_build_object(
        'command_kind', 'force_job_takeover',
        'command_id', p_command_id,
        'operator', p_operator,
        'force_reason', p_force_reason,
        'effect_id', p_effect_id,
        'attempt_no', v_att.attempt_no,
        'old_job_fence', p_expected_job_fence,
        'new_job_fence', v_newf,
        'revoked_lease_owner', p_expected_lease_owner,
        'note', 'settlement proceeds through the recovery takeover / '
                'repair paths on the next scan (the force path only '
                'revokes the live lease and advances the fence)');
    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value,
        first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'force_job_takeover',
            'canonical_request_hash', v_computed, 'accepted', NULL,
            v_receipt::text, v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- 4. D10 — the reconcile result-receipt entry (X01): the one legal
--    terminal settlement path under quiescing. The (iii)/(iv) pending
--    stream forms are a WRONG ENTRY here (fixed OBSERVATION_WRONG_ENTRY,
--    never a stream_progress write); every terminal form settles through
--    the shared completion core with the W01 gate standing down for this
--    single caller (the v8.reconcile_result_entry GUC seam).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_reconcile_result(
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
    v_form jsonb;
    v_mode text;
    v_receipt jsonb;
    v_ev jsonb;
BEGIN
    SELECT execution_mode INTO v_mode FROM effect_requests er
     WHERE er.effect_id = p_effect_id;
    v_form := CASE WHEN p_result_payload_canonical IS NULL THEN NULL
                   ELSE p_result_payload_canonical::jsonb END;

    -- The (iii)/(iv) pending stream forms (stream_complete=false on a
    -- streaming known_success) are a WRONG ENTRY through reconcile: a
    -- fixed structural rejection, zero control state, no observation
    -- write (only complete_effect's five-gate path may accept them).
    IF v_form IS NOT NULL AND v_form ? 'stream_complete'
       AND coalesce((v_form->>'stream_complete')::boolean, true) = false
       AND p_outcome = 'succeeded'
       AND v_mode = 'streaming' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'complete_effect',
            v_sha256_hex(coalesce(p_payload_canonical,
                                  p_result_payload_canonical)),
            'rejected_mismatch', 'OBSERVATION_WRONG_ENTRY',
            'a pending stream observation must enter through '
            'complete_effect five state gates, never reconcile');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'OBSERVATION_WRONG_ENTRY'::text, v_receipt;
        RETURN;
    END IF;

    -- The terminal settlement runs through the shared completion core
    -- with the W01 quiescing gate standing down for THIS single caller.
    -- The evidence binding (effect_id, attempt_no) is filled from the
    -- settlement parameters when the caller omits them — the same fill
    -- the Python complete_effect client performs.
    PERFORM set_config('v8.reconcile_result_entry', 'on', true);
    v_ev := coalesce(p_evidence, '{}'::jsonb)
            || jsonb_strip_nulls(jsonb_build_object(
                   'effect_id', CASE WHEN coalesce(p_evidence, '{}'::jsonb)
                                         ? 'effect_id'
                                     THEN NULL ELSE p_effect_id::text END,
                   'attempt_no', CASE WHEN coalesce(p_evidence, '{}'::jsonb)
                                          ? 'attempt_no'
                                     THEN NULL ELSE p_attempt_no END));
    RETURN QUERY SELECT * FROM v_complete_effect(
        p_session_id, p_command_id, p_effect_id, p_attempt_no, p_step_id,
        p_driver, p_driver_epoch, p_dispatch_session_fence, p_job_fence,
        p_outcome, p_request_hash, p_idempotency_key,
        p_result_payload_canonical, p_message_canonical, p_plan_canonical,
        p_schema_version, p_canonicalizer_version, p_declared_hash,
        p_payload_canonical, v_ev);
END;
$$;
