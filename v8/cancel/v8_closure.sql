-- v8 G8b: the shared cancel closure sub-operation (s32b §2.8, five exits,
-- AG01 trigger-source consolidation), the effect-level cancel code closure
-- map (s32b §4.3) and the shared cancel turn/end derivation (§1.2 unique
-- turn-finalization reducer priority (2)/(3)).
--
-- Source of truth: docs/designs/v8-dev.md (frozen spec), digest
-- docs/analysis/v8-impl-digest/s32b-effect-ledger.md §2.8 (five exits +
-- AG01 source consolidation (α)(β)(γ)(δ)) / §4.1 (effect state closure
-- edges failed_retryable -> cancelled_after_dispatch / -> failed_terminal) /
-- §4.3 (cancel/unknown code map), s32a-step-session.md §2.1 (aggregation
-- priority, rule 3 cancel-wins rows) / §4.1 (step state machine cancel
-- out-edges) / §2.2 step 3(c) (recovery takeover sticky disposition),
-- s31a-identity-commands.md §2.10 (request_cancel canonical derivation),
-- Conformance 6 (spec §6 line 846) and Conformance 15 (line 855) verbatim.
--
-- Load-order position: this file defines the cancel-family SHARED
-- sub-operation that the retry-stage ledger (aggregation rule 3 judgment +
-- applier), the recovery takeover (δ), repair (γ) and the request_cancel
-- command (β) all consume, so it is loaded after the effect/tools
-- foundations and BEFORE the retry stage (see v8/load.py). It depends only
-- on the schema/keys/events/effect foundations; the turn_end_closers
-- lookups below are guarded with to_regclass so earlier stage databases
-- (which stop before the repair stage creates that table) can load and use
-- the rest of the file unchanged.
--
-- ONE implementation (MUST NOT be duplicated by any trigger source):
--   * v_shared_cancel_closure — the five-exit disposition over a step's
--     effect batch (sticky family) / the controlled-edge closure (provider
--     family);
--   * v_aggregate_step rule 3 (v8/retry/v8_retry.sql) — the shared
--     judgment that derives the cancel-wins step/session row and hands the
--     residual set to the applier, which invokes the closure above;
--   * v_derive_cancel_turn_end — the canonical turn/end derivation shared
--     by every trigger source (MUST NOT be a second turn/end rule).
--
-- audit carrier: the cancel-family audit rows use the plain effect_audit
-- columns + reason (internal_op_kind/parent_command_id/internal_op_ordinal
-- stay NULL — A33/A47 continuation).

-- ---------------------------------------------------------------------------
-- Database-internal derived event key for a cancel-generated semantic event
-- (turn/end). The event has no settled effect to bind (the cancellation is
-- not a completion), so it is keyed on the canonical slot identity
-- turn_end_key@v1 (session + turn) and the payload hash:
--   SHA-256("v8:cancel-event-key@db1\0"
--        || len8(session_id bytes) || session_id bytes
--        || len8(event_type bytes) || event_type bytes
--        || len8(turn_end_key bytes) || turn_end_key bytes
--        || len8(payload_hash bytes) || payload_hash bytes) as lowercase hex.
-- At most one known cancel-generated turn/end exists per (session, turn), so
-- the key is stable and collision-free within the session's event_key space.
-- (Moved here from v8_cancel.sql by G8b: the shared derivation below needs
-- it in stages that load before the cancel command file.)
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_cancel_event_key(
    p_session_id uuid, p_event_type text, p_turn_end_key text,
    p_payload_hash text
) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN encode(sha256(
    convert_to('v8:cancel-event-key@db1', 'UTF8') || '\x00'::bytea
    || v_len8(v_uuid16(p_session_id)) || v_uuid16(p_session_id)
    || v_len8(v_identity_bytes(p_event_type)) || v_identity_bytes(p_event_type)
    || v_len8(v_identity_bytes(p_turn_end_key)) || v_identity_bytes(p_turn_end_key)
    || v_len8(v_identity_bytes(p_payload_hash)) || v_identity_bytes(p_payload_hash)
), 'hex');

-- ---------------------------------------------------------------------------
-- v_effect_cancel_code — the effect terminal cancel code closure map
-- (s32b §4.3) as a derived read: no effect column carries the code, so the
-- code is resolved from the persisted facts of the cancellation, in the
-- frozen authority order:
--   cancelled_before_dispatch        -> ABORTED_BEFORE_DISPATCH (database-
--                                       internal cancellation only, §2.9);
--   cancelled_after_dispatch
--     (a) the repair closer resolution identity code — a repair-proved
--         cancellation records the code in its closer (the §4.3 map value);
--     (b) the sticky closure audit (RETRY_SUPPRESSED_BY_CANCEL) ->
--         CANCELLED_BY_REQUEST_AFTER_DISPATCH;
--     (c) a bound provider receipt (provider_request_id) -> provider-
--         confirmed -> CANCELLED_BY_PROVIDER;
--     (d) otherwise a request-family cancellation ->
--         CANCELLED_BY_REQUEST_AFTER_DISPATCH (cancel request took effect
--         before the side effect).
-- This is the single reader used by the aggregation rule 3 family split and
-- by the turn/end derivation; no second cancel-code map is built.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_effect_cancel_code(p_effect_id uuid) RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_status text;
    v_session uuid;
    v_rec text;
    v_code text;
BEGIN
    SELECT er.status, er.session_id, er.provider_request_id
      INTO v_status, v_session, v_rec
      FROM effect_requests er WHERE er.effect_id = p_effect_id;
    IF v_status IS NULL THEN
        RETURN NULL;
    END IF;
    IF v_status = 'cancelled_before_dispatch' THEN
        RETURN 'ABORTED_BEFORE_DISPATCH';
    END IF;
    IF v_status <> 'cancelled_after_dispatch' THEN
        RETURN NULL;
    END IF;
    -- (a) repair closer resolution (authoritative when present; the table is
    -- created by the later repair stage, so earlier stage databases guard).
    IF to_regclass('turn_end_closers') IS NOT NULL THEN
        SELECT convert_from(c.resolution_identity_canonical, 'UTF8')::jsonb->>'code'
          INTO v_code
          FROM turn_end_closers c
         WHERE c.session_id = v_session
           AND convert_from(c.resolution_identity_canonical, 'UTF8')::jsonb
               ->>'effect_id' = p_effect_id::text
         ORDER BY c.event_seq DESC LIMIT 1;
        IF v_code IS NOT NULL THEN
            RETURN v_code;
        END IF;
    END IF;
    -- (b) the sticky closure wrote its audit row at the disposition point.
    IF EXISTS (SELECT 1 FROM effect_audit a
                WHERE a.effect_id = p_effect_id
                  AND a.reason = 'RETRY_SUPPRESSED_BY_CANCEL') THEN
        RETURN 'CANCELLED_BY_REQUEST_AFTER_DISPATCH';
    END IF;
    -- (c)/(d) provider receipt presence is the provider-confirmation
    -- discriminator of the §4.3 map.
    IF v_rec IS NOT NULL THEN
        RETURN 'CANCELLED_BY_PROVIDER';
    END IF;
    RETURN 'CANCELLED_BY_REQUEST_AFTER_DISPATCH';
END;
$$;

-- ---------------------------------------------------------------------------
-- v_turn_cancel_reason — the canonical cancel reason of a turn, mirroring
-- the §1.2 unique reducer segment-3 priority (2)/(3) EXACTLY:
--   sticky cancel (the session latch, or a request-family cancellation
--   effect) wins over a provider cancellation; the sticky reason splits by
--   dispatch phase (before/after); a provider cancellation without a local
--   sticky signal yields cancelled_by_provider. NULL when the turn has no
--   cancel signal (the turn stays open / closes normally).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_turn_cancel_reason(p_session_id uuid, p_turn_id uuid)
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_latch bigint;
    v_sticky boolean;
    v_provider boolean;
    v_dispatched boolean;
BEGIN
    SELECT s.cancellation_epoch INTO v_latch FROM sessions s
     WHERE s.session_id = p_session_id;
    v_sticky := coalesce(v_latch, 0) > 0 OR EXISTS (
        SELECT 1 FROM effect_requests er
          JOIN steps st ON st.step_id = er.step_id
         WHERE st.session_id = p_session_id AND st.turn_id = p_turn_id
           AND er.status = 'cancelled_after_dispatch'
           AND v_effect_cancel_code(er.effect_id) IN
               ('CANCELLED_BY_REQUEST_AFTER_DISPATCH',
                'cancelled_by_request_after_dispatch'));
    v_provider := EXISTS (
        SELECT 1 FROM effect_requests er
          JOIN steps st ON st.step_id = er.step_id
         WHERE st.session_id = p_session_id AND st.turn_id = p_turn_id
           AND er.status = 'cancelled_after_dispatch'
           AND v_effect_cancel_code(er.effect_id) IN
               ('CANCELLED_BY_PROVIDER', 'cancelled_by_provider'));
    IF v_sticky THEN
        -- dispatch-phase split: cancelled_before_dispatch is NOT a
        -- dispatched signal (the `dispatched` set of the reducer).
        SELECT EXISTS (
            SELECT 1 FROM effect_requests er
              JOIN steps st ON st.step_id = er.step_id
             WHERE st.session_id = p_session_id AND st.turn_id = p_turn_id
               AND er.status IN ('dispatch_started', 'succeeded',
                                 'failed_retryable', 'failed_terminal',
                                 'cancelled_after_dispatch', 'unknown_outcome'))
          INTO v_dispatched;
        RETURN CASE WHEN coalesce(v_dispatched, false)
                    THEN 'cancelled_by_request_after_dispatch'
                    ELSE 'cancelled_by_request_before_dispatch' END;
    ELSIF v_provider THEN
        RETURN 'cancelled_by_provider';
    END IF;
    RETURN NULL;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_shared_cancel_closure — the shared cancel closure sub-operation
-- (s32b §2.8, the ONLY implementation; every trigger source runs it in its
-- own transaction — MUST NOT replay a stale cancel command). It applies the
-- five frozen exits to every effect of the batch:
--   exit 1  known retryable failure (failed_retryable) -> cancelled_after_
--           dispatch, code CANCELLED_BY_REQUEST_AFTER_DISPATCH, audit
--           RETRY_SUPPRESSED_BY_CANCEL (sticky family);
--   exit 2  known terminal failure (failed_terminal) -> kept as-is with the
--           original failure code (the parent layer derives cancel-wins);
--   exit 3  success (succeeded) -> kept, audit COMPLETED_AFTER_CANCEL;
--   exit 4  unknown_outcome -> kept (rule 1 keeps blocked_unknown_effect;
--           after the repair closure it returns here);
--   exit 5  known cancellation (cancelled_after_dispatch) -> kept with the
--           code already written by §4.3 (CANCELLED_BY_PROVIDER MUST NOT be
--           rewritten to CANCELLED_BY_REQUEST_AFTER_DISPATCH); MUST NOT
--           write COMPLETED_AFTER_CANCEL / RETRY_SUPPRESSED_BY_CANCEL.
-- The provider family (no local sticky latch; a provider-confirmed
-- cancellation) closes residual failed_retryable siblings through the
-- controlled edge failed_retryable -> failed_terminal (original failure
-- facts kept, audit RETRY_STOPPED_BY_CLOSURE, retry_stop_reason persisted
-- through the R-01 CAS writer) — §2.1 rule 3 extension; exits 3/5 stay
-- sticky-family only.
-- Returns a jsonb summary of the disposition (effect ids per exit).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_shared_cancel_closure(
    p_session_id uuid, p_step_id uuid, p_command_id text,
    p_audit_key_value text, p_family text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    r record;
    v_att bigint;
    v_fp text;
    v_sup uuid[] := ARRAY[]::uuid[];
    v_cmp uuid[] := ARRAY[]::uuid[];
    v_term uuid[] := ARRAY[]::uuid[];
    v_unk uuid[] := ARRAY[]::uuid[];
    v_can uuid[] := ARRAY[]::uuid[];
BEGIN
    IF p_family NOT IN ('sticky', 'provider') THEN
        RAISE EXCEPTION
            'INFRA_PROTOCOL_VIOLATION: shared_cancel_closure requires the '
            'sticky or provider family, got %', p_family;
    END IF;

    FOR r IN
        SELECT er.effect_id, er.status, er.result_hash
          FROM effect_requests er
         WHERE er.step_id = p_step_id
         ORDER BY er.dispatch_ordinal, er.effect_id
    LOOP
        IF r.status = 'failed_retryable' AND p_family = 'sticky' THEN
            -- exit 1: known retryable failure suppressed by the latch.
            UPDATE effect_requests SET status = 'cancelled_after_dispatch',
                                       updated_at = now()
             WHERE effect_id = r.effect_id;
            SELECT max(a.attempt_no) INTO v_att FROM effect_attempts a
             WHERE a.effect_id = r.effect_id;
            UPDATE effect_attempts SET status = 'cancelled_after_dispatch',
                                       completed_at = now()
             WHERE effect_id = r.effect_id AND attempt_no = v_att;
            SELECT coalesce(r.result_hash,
                            v_sha256_hex(p_command_id || ':' || r.effect_id::text))
              INTO v_fp;
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id,
                attempt_no, audit_key_kind, audit_key_value,
                result_fingerprint, reason)
            VALUES (p_session_id, p_session_id, p_step_id, r.effect_id, v_att,
                    'canonical_binding', p_audit_key_value, v_fp,
                    'RETRY_SUPPRESSED_BY_CANCEL')
            ON CONFLICT DO NOTHING;
            v_sup := v_sup || r.effect_id;
        ELSIF r.status = 'failed_retryable' THEN
            -- provider family: the controlled edge (no new attempt, original
            -- failure facts kept, R-01 reason CAS).
            UPDATE effect_requests SET status = 'failed_terminal',
                                       updated_at = now()
             WHERE effect_id = r.effect_id AND status = 'failed_retryable';
            SELECT max(a.attempt_no) INTO v_att FROM effect_attempts a
             WHERE a.effect_id = r.effect_id;
            UPDATE effect_attempts SET status = 'failed_terminal',
                                       completed_at = now()
             WHERE effect_id = r.effect_id AND attempt_no = v_att
               AND status = 'failed_retryable';
            PERFORM v_retry_stop_reason_cas(r.effect_id);
            SELECT coalesce(er.result_hash,
                            v_sha256_hex(p_command_id || ':' || r.effect_id::text))
              INTO v_fp
              FROM effect_requests er WHERE er.effect_id = r.effect_id;
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id,
                attempt_no, audit_key_kind, audit_key_value,
                result_fingerprint, reason)
            VALUES (p_session_id, p_session_id, p_step_id, r.effect_id, v_att,
                    'canonical_binding', p_audit_key_value, v_fp,
                    'RETRY_STOPPED_BY_CLOSURE')
            ON CONFLICT DO NOTHING;
            v_term := v_term || r.effect_id;
        ELSIF r.status = 'succeeded' AND p_family = 'sticky' THEN
            -- exit 3: the completion stands; the audit records that it
            -- landed after the cancel.
            SELECT max(a.attempt_no) INTO v_att FROM effect_attempts a
             WHERE a.effect_id = r.effect_id;
            SELECT coalesce(r.result_hash,
                            v_sha256_hex(p_command_id || ':' || r.effect_id::text))
              INTO v_fp;
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id,
                attempt_no, audit_key_kind, audit_key_value,
                result_fingerprint, reason)
            VALUES (p_session_id, p_session_id, p_step_id, r.effect_id, v_att,
                    'canonical_binding', p_audit_key_value, v_fp,
                    'COMPLETED_AFTER_CANCEL')
            ON CONFLICT DO NOTHING;
            v_cmp := v_cmp || r.effect_id;
        ELSIF r.status = 'succeeded' THEN
            v_cmp := v_cmp || r.effect_id;      -- exit 3 (provider family, no audit)
        ELSIF r.status = 'failed_terminal' THEN
            v_term := v_term || r.effect_id;    -- exit 2 (kept verbatim)
        ELSIF r.status = 'unknown_outcome' THEN
            v_unk := v_unk || r.effect_id;      -- exit 4 (kept; rule 1 holds)
        ELSIF r.status = 'cancelled_after_dispatch' THEN
            v_can := v_can || r.effect_id;      -- exit 5 (kept; no audit)
        END IF;
    END LOOP;

    RETURN jsonb_build_object(
        'family', p_family,
        'retry_suppressed', to_jsonb(coalesce(v_sup, ARRAY[]::uuid[])),
        'completed_after_cancel', to_jsonb(coalesce(v_cmp, ARRAY[]::uuid[])),
        'terminal_kept', to_jsonb(coalesce(v_term, ARRAY[]::uuid[])),
        'unknown_kept', to_jsonb(coalesce(v_unk, ARRAY[]::uuid[])),
        'cancel_kept', to_jsonb(coalesce(v_can, ARRAY[]::uuid[])));
END;
$$;

-- ---------------------------------------------------------------------------
-- v_derive_cancel_turn_end — the SHARED cancel turn/end derivation (s31a
-- §2.10 / §1.2 reducer priority (2)/(3); MUST NOT be a second turn/end
-- rule). Self-guarding and idempotent:
--   * only a session already collapsed to `cancelled` derives an end;
--   * a turn whose slot row already exists is left untouched (a closed turn
--     keeps its end; a repair closer owns its own turn/end event);
--   * the reason comes from v_turn_cancel_reason (sticky wins over
--     provider, dispatch-phase split) and is written as the canonical
--     `{"interrupted":true,"reason":...}` payload + the known slot row.
-- Returns {reason, seq, event_key} when it wrote the derived end, else NULL.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_derive_cancel_turn_end(
    p_session_id uuid, p_command_id text,
    p_schema_version text, p_canonicalizer_version text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_turn uuid;
    v_reason text;
    v_payload text;
    v_hash text;
    v_tek text;
    v_evkey text;
    v_seq bigint;
    v_iso bigint;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sessions s
                    WHERE s.session_id = p_session_id
                      AND s.state = 'cancelled') THEN
        RETURN NULL;
    END IF;
    SELECT st.turn_id INTO v_turn FROM steps st
     WHERE st.session_id = p_session_id
     ORDER BY st.created_at DESC, st.step_id DESC LIMIT 1;
    IF v_turn IS NULL THEN
        SELECT se.turn_id INTO v_turn FROM session_events se
         WHERE se.session_id = p_session_id AND se.event_type = 'turn/start'
           AND se.turn_id IS NOT NULL
         ORDER BY se.seq DESC LIMIT 1;
    END IF;
    IF v_turn IS NULL THEN
        RETURN NULL;                       -- no turn opened: no turn event
    END IF;
    IF EXISTS (SELECT 1 FROM turn_end_slots tes
                WHERE tes.session_id = p_session_id AND tes.turn_id = v_turn) THEN
        RETURN NULL;                       -- the turn already has its end
    END IF;
    v_reason := v_turn_cancel_reason(p_session_id, v_turn);
    IF v_reason IS NULL THEN
        RETURN NULL;
    END IF;
    v_payload := format('{"interrupted":true,"reason":"%s"}', v_reason);
    v_hash := v_sha256_hex(v_payload);
    v_tek := v_turn_end_key(p_session_id, v_turn);
    v_evkey := v_cancel_event_key(p_session_id, 'turn/end', v_tek, v_hash);
    SELECT s.next_seq INTO v_seq FROM sessions s WHERE s.session_id = p_session_id;
    SELECT coalesce(max(se.internal_semantic_ordinal), 0) + 1 INTO v_iso
      FROM session_events se WHERE se.session_id = p_session_id;
    INSERT INTO session_events(
        seq, session_id, event_type, event_class, schema_version,
        canonicalizer_version, event_key, turn_id, step_id, effect_id,
        payload, payload_hash, semantic_input_ordinal,
        internal_semantic_ordinal, attempt_no, command_id,
        batch_item_ordinal)
    VALUES (
        v_seq, p_session_id, 'turn/end', 'semantic', p_schema_version,
        p_canonicalizer_version, v_evkey, v_turn, NULL, NULL,
        v_payload, v_hash, NULL, v_iso, NULL, p_command_id, NULL);
    INSERT INTO turn_end_slots(
        session_id, turn_id, turn_end_key, head_event_key, slot_status,
        resolution_identity_canonical, version)
    VALUES (
        p_session_id, v_turn, v_tek, v_evkey, 'known',
        convert_to(v_payload, 'UTF8'), 1);
    UPDATE sessions SET next_seq = v_seq + 1, updated_at = now()
     WHERE session_id = p_session_id;
    RETURN jsonb_build_object('reason', v_reason, 'seq', v_seq,
                              'turn_id', v_turn, 'event_key', v_evkey);
END;
$$;

-- ---------------------------------------------------------------------------
-- v_settle_known_cancellation — the known_cancellation terminal settlement
-- (s32b §2.8 exit 5 + §2.7; the (α) complete_effect / later reconcile
-- entry). The cancellation is a known result: the effect settles
-- cancelled_after_dispatch with the §4.3 map code (a bound provider receipt
-- ->
-- CANCELLED_BY_PROVIDER, a no-side-effect proof -> CANCELLED_BY_REQUEST_
-- AFTER_DISPATCH) and MUST NOT write RETRY_SUPPRESSED_BY_CANCEL /
-- COMPLETED_AFTER_CANCEL. Then the shared judgment + applier derive the
-- parent layer (rule 3 provider/sticky cancel-wins, or rule 1/2 while a
-- sibling is unresolved) and the shared derivation writes the canonical
-- turn/end when the session collapsed to cancelled.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_settle_known_cancellation(
    p_session_id uuid, p_command_id text, p_computed text,
    p_step_id uuid, p_effect_id uuid, p_attempt_no bigint,
    p_evidence jsonb, p_result_fingerprint text, p_declared_outcome text,
    p_schema_version text, p_canonicalizer_version text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_receipt_id text;
    v_code text;
    v_agg record;
    v_end jsonb;
    v_events jsonb := '[]'::jsonb;
    v_receipt jsonb;
BEGIN
    IF v_classify_evidence(p_effect_id, p_attempt_no, p_evidence)
       <> 'known_cancellation' THEN
        RAISE EXCEPTION
            'INFRA_PROTOCOL_VIOLATION: v_settle_known_cancellation called '
            'with evidence classifying % (effect % attempt %)',
            v_classify_evidence(p_effect_id, p_attempt_no, p_evidence),
            p_effect_id, p_attempt_no;
    END IF;

    v_receipt_id := p_evidence->'provider_receipt'->>'receipt_id';
    v_code := CASE WHEN v_receipt_id IS NOT NULL
                   THEN 'CANCELLED_BY_PROVIDER'
                   ELSE 'CANCELLED_BY_REQUEST_AFTER_DISPATCH' END;

    -- exit 5: the effect keeps cancelled_after_dispatch and the map code.
    UPDATE effect_requests SET
        status = 'cancelled_after_dispatch',
        result_hash = p_result_fingerprint,
        provider_request_id = coalesce(v_receipt_id, provider_request_id),
        updated_at = now()
     WHERE effect_id = p_effect_id;
    UPDATE effect_attempts SET
        status = 'cancelled_after_dispatch',
        result_hash = p_result_fingerprint,
        provider_request_id = coalesce(v_receipt_id, provider_request_id),
        completed_at = now()
     WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;

    -- declared outcome vs the derived cancellation: audited, never rejected.
    IF p_declared_outcome <> 'cancelled_after_dispatch' THEN
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id,
            attempt_no, audit_key_kind, audit_key_value,
            result_fingerprint, reason)
        VALUES (p_session_id, p_session_id, p_step_id, p_effect_id,
                p_attempt_no, 'canonical_binding', p_computed,
                p_result_fingerprint, 'RESULT_OUTCOME_MISMATCH')
        ON CONFLICT DO NOTHING;
    END IF;

    -- the shared judgment + applier (rule 1/2 while a sibling is unresolved,
    -- rule 3 cancel-wins otherwise; the applier runs the closure).
    SELECT * INTO v_agg FROM v_aggregate_step(p_step_id);
    PERFORM v_apply_step_aggregation(
        p_session_id, p_step_id, v_agg.rule_no, v_agg.step_status,
        v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
        v_agg.closure_effect_ids, p_command_id, p_computed);

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
        'classification', 'known_cancellation',
        'effect_id', p_effect_id,
        'attempt_no', p_attempt_no,
        'derived_status', 'cancelled_after_dispatch',
        'effect_code', v_code,
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
