-- v8 G8a: request_cancel command (sticky stop latch, the no-active-work
-- branch three windows, the canonical turn/end derivation and the
-- pre-dispatch dual-table atomic sync).
--
-- Source of truth: docs/designs/v8-dev.md §3.1.1 request_cancel (digest
-- docs/analysis/v8-impl-digest/s31a-identity-commands.md §2.10), §3.2.2
-- pre-dispatch cancellation dual-table sync (digest s32b-effect-ledger.md
-- §2.9), §3.3 (digest s33-s4-compact-plugin.md §2.2), §1.2 turn-finalization
-- reducer, Conformance 6 / 15.
--
-- Scope of THIS stage: the request_cancel command reachable paths.
--   * sticky latch: the FIRST effective cancel increments cancellation_epoch
--     0 -> 1; subsequent requests return the existing latch (no
--     re-increment; the same command_id replays the original receipt via
--     adjudication);
--   * terminal session: return the original terminal state, epoch unchanged;
--   * pre-dispatch dual-table sync: every published `ready` effect -> both
--     effect_requests.status and the current attempt row ->
--     cancelled_before_dispatch, one transaction, plus the
--     ABORTED_BEFORE_DISPATCH audit;
--   * the no-active-work branch (three windows) collapses the session to
--     cancelled/CANCELLED_BY_REQUEST in the same transaction;
--   * the canonical turn/end derivation (before/after dispatch split);
--   * the race with finish_session and with dispatch is decided by row-lock
--     commit order (both commands lock the session row first).
--
-- [LATER] not in this stage: the after-dispatch shared_cancel_closure
-- sub-operation is G8b (v8/cancel/v8_closure.sql + the aggregation rule 3
-- in v8/retry/v8_retry.sql — this command reaches it through the shared
-- judgment/applier), the WORKSPACE_LOST failure-drain and §4 generation
-- drain trigger sources of the pre-dispatch sync. Those paths leave an
-- in-flight sibling pending; the sticky-latch rule-3 arm (cancel-wins,
-- including the failed_retryable -> cancelled_after_dispatch closure and
-- the derived turn/end) is the shared implementation, never a second copy.

-- ---------------------------------------------------------------------------
-- v_cancel_event_key moved to v8/cancel/v8_closure.sql (G8b): the shared
-- cancel turn/end derivation needs it in stages that load before this file.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- v_request_cancel — receipt command. Locks the session row (master lock
-- order position 1) inside v8_command_adjudicate and executes identity
-- checks, the sticky latch, the pre-dispatch sync, the collapse and the
-- turn/end derivation in ONE transaction with the receipt/binding.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_request_cancel(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint,
    p_schema_version text, p_canonicalizer_version text,
    p_declared_hash text, p_payload_canonical text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_first boolean;
    v_new_epoch bigint;
    v_new_fence bigint;
    v_events jsonb := '[]'::jsonb;
    v_cancelled jsonb := '[]'::jsonb;
    v_active uuid;
    v_target_state text;
    v_target_code text;
    v_clear_active boolean := false;
    v_agg record;
    v_end jsonb;
    r record;
BEGIN
    -- Judgment order (1)-(4) with the session row lock (master lock order
    -- position 1) taken inside the adjudicator, so the cancel/finish and
    -- cancel/dispatch races serialize on the session row and are decided by
    -- commit order.
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'request_cancel',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;

    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'request_cancel',
            v_computed, 'rejected_stale', 'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session control row');
        RETURN QUERY SELECT 'rejected_stale'::text, 'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;

    -- Terminal session: return the original terminal state, epoch unchanged
    -- (state/failure_code/fence/epoch all preserved — zero control change).
    IF v_sess.state IN ('completed', 'failed', 'cancelled') THEN
        v_receipt := jsonb_build_object(
            'command_kind', 'request_cancel',
            'command_id', p_command_id,
            'state', v_sess.state,
            'failure_code', v_sess.failure_code,
            'cancellation_epoch', v_sess.cancellation_epoch,
            'terminal', true,
            'epoch_changed', false,
            'events', '[]'::jsonb);
        INSERT INTO command_bindings(
            session_id, command_id, first_key_kind, first_key_value, first_outcome)
        VALUES (p_session_id, p_command_id, 'canonical_request_hash',
                v_computed, 'accepted');
        INSERT INTO command_receipts(
            session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
            outcome, code, result_canonical, result_hash)
        VALUES (p_session_id, p_command_id, 'request_cancel', 'canonical_request_hash',
                v_computed, 'accepted', NULL, v_receipt::text,
                v_sha256_hex(v_receipt::text));
        RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
        RETURN;
    END IF;

    -- Sticky latch: the FIRST effective cancel increments cancellation_epoch
    -- (0 -> 1); a later request with the latch already set keeps the value
    -- (monotone latch, never cleared). The same command_id replays the
    -- original receipt through adjudication and never reaches here.
    v_first := (v_sess.cancellation_epoch = 0);
    v_new_epoch := CASE WHEN v_first THEN 1 ELSE v_sess.cancellation_epoch END;
    v_new_fence := v_sess.session_fence + 1;

    -- ---- pre-dispatch cancellation, dual-table atomic sync (s32b §2.9) ----
    -- Every published `ready` effect of the session -> cancelled_before_dispatch
    -- together with its CURRENT (max attempt_no) attempt row in the SAME
    -- transaction (no single-sided intermediate state). The database-internal
    -- cancellation produces no completion semantic event; the code
    -- ABORTED_BEFORE_DISPATCH is recorded on the audit row.
    -- [LATER] the WORKSPACE_LOST failure-drain and §4 generation drain are
    -- further trigger sources of this same sync; this stage exposes only the
    -- request_cancel source.
    FOR r IN
        SELECT er.effect_id, er.step_id, er.attempt_no
          FROM effect_requests er
         WHERE er.session_id = p_session_id AND er.status = 'ready'
         ORDER BY er.dispatch_ordinal
    LOOP
        UPDATE effect_requests SET
            status = 'cancelled_before_dispatch', updated_at = now()
         WHERE effect_id = r.effect_id;
        UPDATE effect_attempts SET
            status = 'cancelled_before_dispatch', completed_at = now()
         WHERE effect_id = r.effect_id AND attempt_no = r.attempt_no;
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id, attempt_no,
            audit_key_kind, audit_key_value, result_fingerprint, reason)
        VALUES (p_session_id, p_session_id, r.step_id, r.effect_id, r.attempt_no,
                'canonical_binding', v_computed,
                v_sha256_hex(p_command_id || ':' || r.effect_id::text),
                'ABORTED_BEFORE_DISPATCH');
        v_cancelled := v_cancelled || jsonb_build_object(
            'effect_id', r.effect_id, 'attempt_no', r.attempt_no,
            'code', 'ABORTED_BEFORE_DISPATCH');
    END LOOP;

    -- Recompute the aggregation counters of the session's steps from the
    -- effect table (authoritative).
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
     WHERE st.session_id = p_session_id;

    -- ---- collapse decision ----
    -- The unique non-terminal step (single-active-step model; NULL when the
    -- session has no live step — the three no-active-work windows).
    SELECT st.step_id INTO v_active FROM steps st
     WHERE st.session_id = p_session_id
       AND st.status NOT IN ('succeeded', 'failed_terminal', 'cancelled')
     LIMIT 1;

    IF v_active IS NULL THEN
        -- No active work: window (i) ready/new, window (ii) waiting_event/
        -- sleeping, window (iii) a terminal step awaiting finish_session —
        -- collapse to cancelled/CANCELLED_BY_REQUEST in this transaction,
        -- bypassing the aggregation (there is no live step to aggregate;
        -- §3.1.1 request_cancel no-active-work branch).
        v_target_state := 'cancelled';
        v_target_code := 'CANCELLED_BY_REQUEST';
        v_clear_active := true;
    ELSE
        -- G8b: the sticky latch MUST be visible to the ONE shared judgment
        -- before it runs (rule 3 reads sessions.cancellation_epoch), so the
        -- latch + fence bump are written first; the session control state
        -- itself is written after the aggregation. The applier runs with
        -- p_write_session=false so the fence is never bumped twice.
        UPDATE sessions SET
            cancellation_epoch = v_new_epoch,
            session_fence = v_new_fence,
            lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
            updated_at = now()
         WHERE session_id = p_session_id;

        SELECT * INTO v_agg FROM v_aggregate_step(v_active);
        PERFORM v_apply_step_aggregation(
            p_session_id, v_active, v_agg.rule_no, v_agg.step_status,
            v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
            v_agg.closure_effect_ids, p_command_id, v_computed, false);
        v_target_state := v_agg.session_state;
        v_target_code := v_agg.failure_code;
        -- §3.1 rule: a session leaving its active step clears the locating
        -- pointer.
        v_clear_active := v_agg.step_status IN ('succeeded', 'failed_terminal',
                                                'cancelled');
    END IF;

    -- ---- session control mutation ----
    UPDATE sessions SET
        state = v_target_state,
        failure_code = v_target_code,
        cancellation_epoch = v_new_epoch,
        session_fence = v_new_fence,
        lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
        active_step_id = CASE WHEN v_clear_active THEN NULL ELSE active_step_id END,
        updated_at = now()
     WHERE session_id = p_session_id;

    -- ---- canonical turn/end derivation (SHARED implementation) ----
    -- S31a §2.10: never a second turn/end rule. The shared derivation is
    -- self-guarding (only a collapsed `cancelled` session, only a turn whose
    -- slot row is still absent) and derives the reason by the §1.2 reducer
    -- priority (2)/(3) — sticky wins over provider, dispatch-phase split.
    v_end := v_derive_cancel_turn_end(p_session_id, p_command_id,
                                      p_schema_version,
                                      p_canonicalizer_version);
    IF v_end IS NOT NULL THEN
        v_events := jsonb_build_array(jsonb_build_object(
            'event_type', 'turn/end', 'seq', v_end->'seq',
            'event_key', v_end->>'event_key', 'reason', v_end->>'reason'));
    END IF;

    v_receipt := jsonb_build_object(
        'command_kind', 'request_cancel',
        'command_id', p_command_id,
        'cancellation_epoch', v_new_epoch,
        'epoch_incremented', v_first,
        'session_fence', v_new_fence,
        'state', v_target_state,
        'failure_code', v_target_code,
        'cancelled_effects', v_cancelled,
        'events', v_events);

    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
        outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'request_cancel', 'canonical_request_hash',
            v_computed, 'accepted', NULL, v_receipt::text,
            v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;
