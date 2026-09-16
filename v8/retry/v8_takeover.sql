-- v8 G7b: recovery takeover — the single-transaction atomic takeover of
-- the result-less in-flight (dispatch_started) attempts of a session.
--
-- Source of truth: docs/designs/v8-dev.md (frozen spec), digest
-- docs/analysis/v8-impl-digest/s32a-step-session.md §2.2 (the six takeover
-- steps verbatim: full pre-lock set, CAS + job-lease guard, the three
-- ordered determinations, single-transaction atomic merge, late-completion
-- and aggregation-order rules), §2.3 FORCE_JOB_TAKEOVER ([LATER], NOT
-- implemented here — normal recovery never carries force semantics),
-- §3.2/§3.3 retry_eligible + budget, §3.5 unique evidence classification
-- (three-entry consistency: complete / recovery / repair), Conformance
-- item 2 (spec section 6, line 843).
--
-- Command shape (A13-adjacent note): the takeover is a controlled
-- recovery WRITE, not a lease CAS, so it takes the receipt-command shape
-- (command_id + the shared adjudicator's replay/conflict/hash gates),
-- like every other control write. It does NOT require a held session
-- coordination/recovery lease: the per-attempt job lease guard is the
-- takeover authority (a session lease expiry never implies job lease
-- invalidation, and conversely a live session lease never blocks the
-- takeover of an expired job lease).
--
-- G7b scope guards (explicit; the [LATER] dispositions land with G8/P1):
--   * grant/slice and catalog_generation models are absent, so the
--     eight-slot pre-lock set reduces to its reachable subset
--     session -> step -> effect -> attempt (lockless locate of the
--     immutable associations first, then tiered locks in that order,
--     each tier sorted). The generation-check deadlock assertion is
--     LATER with §4 (same reason as the G7a cohort gates).
--   * execution permission gate (3(c) determination 1): driver_mode=
--     quiescing forbids the known_failure retry disposition — with at
--     least one taken-over attempt classifying known_failure the whole
--     command refuses stably (DRIVER_QUIESCING, zero control state,
--     checked before any mutation). The quiescing controlled-edge closure
--     lands with the driver-switch milestone (P1); no public path in this
--     stage can set quiescing. The sticky cancel latch is handled in
--     transaction since G8b: the settlement proceeds and the shared
--     aggregation rule 3 + shared cancel closure sub-operation apply the
--     cancel-wins exits (the takeover is trigger source (δ)). A session
--     already failed terminal
--     is refused SESSION_TERMINAL the same way (the gate's
--     "session terminal failure" leg, which is also a safety guard for
--     the aggregation writes).
--   * known_success / known_cancellation evidence presented at the
--     takeover does NOT drive terminal settlement here: the success
--     closure requires the full EffectResult payload (message/tools/
--     decision marks) which the takeover envelope does not carry. The
--     attempt settles the conservative unknown_outcome with a receipt
--     annotation; the G7c repair milestone owns the upgrade. The
--     classification itself still runs through the unique
--     v_classify_evidence (three-entry consistency, Conformance 2(5)).
--   * the job lease carrier is the effect row lease_owner/lease_until:
--     NULL/absent or past expiry = expired-or-revoked = takeable. P0B
--     dispatch never sets a job lease, so a live lease only exists via
--     an explicit grant (tests); revocation is represented by clearing
--     both columns in the takeover transaction (receipt records the
--     revoked values).
--   * step 2 of the six steps advances current_job_fence with a fresh
--     sequence value unconditionally (also on the no-allocation
--     branches, so an old-fence completion stale-rejects whatever
--     follows); when the batch judgment then hits rule 5, the frozen
--     G7a sub-operation v_retry_cohort_allocation draws its own fresh
--     fence for the new attempt (its per-step-5 contract). Both draws
--     happen inside the one takeover transaction, so current_job_fence
--     advances strictly monotonically (F0 -> F1 -> F2) and the old
--     fence is dead either way; the new attempt's dispatch_job_fence
--     equals the current_job_fence of the takeover transaction's final
--     state, per the "value after the step-2 advance" chain reading.
CREATE FUNCTION v_recovery_takeover(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint,
    p_evidence jsonb,
    p_declared_hash text, p_payload_canonical text,
    p_schema_version text DEFAULT 'sv@1',
    p_canonicalizer_version text DEFAULT 'canon@1'
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_seq bigint;
    v_seq0 bigint;
    v_iso bigint;
    v_end_payload text;
    v_end_hash text;
    v_endkey text;
    v_turn uuid;
    -- Step 1: lockless locate, then the tiered pre-lock set.
    v_all_steps uuid[];
    v_step_id uuid;
    v_eff_ids uuid[];
    v_eff_steps uuid[];
    v_er effect_requests%ROWTYPE;
    v_att effect_attempts%ROWTYPE;
    -- Step 2/3 scan output: classified takeover targets (parallel
    -- arrays in scan order = (step, dispatch_ordinal) order).
    v_t_eff uuid[] := ARRAY[]::uuid[];
    v_t_att bigint[] := ARRAY[]::bigint[];
    v_t_step uuid[] := ARRAY[]::uuid[];
    v_t_class text[] := ARRAY[]::text[];
    v_t_note text[] := ARRAY[]::text[];
    v_used_keys text[] := ARRAY[]::text[];
    v_attempts jsonb := '[]'::jsonb;
    v_steps_out jsonb := '[]'::jsonb;
    v_unused jsonb := '[]'::jsonb;
    -- Mutation phase state.
    v_i int;
    v_n int;
    v_ev jsonb;
    v_cl text;
    v_note text;
    v_k text;
    v_newf bigint;
    v_rec_id text;
    v_fp text;
    v_elig boolean;
    v_status text;
    v_reason text;
    v_agg record;
    v_alloc jsonb;
    v_entry jsonb;
    v_end jsonb;
BEGIN
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'recovery_takeover',
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
            'recovery_takeover', v_computed, 'rejected_stale',
            'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session control row');
        RETURN QUERY SELECT 'rejected_stale'::text, 'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;
    -- Gate leg "session already failed terminal" (+ a safety guard: the
    -- aggregation writes below must never run on a terminal session).
    IF v_sess.state IN ('completed', 'failed', 'cancelled') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'recovery_takeover', v_computed, 'rejected_mismatch',
            'SESSION_TERMINAL',
            format('recovery takeover on a terminal session (state %s)',
                   v_sess.state));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_TERMINAL'::text, v_receipt;
        RETURN;
    END IF;

    v_seq := v_sess.next_seq;
    v_seq0 := v_seq;

    -- ------------------------------------------------------------------
    -- (1) pre-lock set: lockless locate of the immutable associations,
    -- then the reachable subset of the eight-slot master order
    -- session -> step -> effect -> attempt, each tier locked in sort
    -- order (grant/slice + generation tiers absent in this stage).
    -- ------------------------------------------------------------------
    SELECT array_agg(DISTINCT er.step_id) INTO v_all_steps
      FROM effect_requests er WHERE er.session_id = p_session_id;
    FOREACH v_step_id IN ARRAY coalesce(v_all_steps, ARRAY[]::uuid[]) LOOP
        PERFORM 1 FROM steps st WHERE st.step_id = v_step_id FOR UPDATE;
    END LOOP;

    SELECT array_agg(er.effect_id
                     ORDER BY er.step_id, er.dispatch_ordinal, er.effect_id),
           array_agg(er.step_id
                     ORDER BY er.step_id, er.dispatch_ordinal, er.effect_id)
      INTO v_eff_ids, v_eff_steps
      FROM effect_requests er
     WHERE er.session_id = p_session_id AND er.status = 'dispatch_started';

    v_n := coalesce(array_length(v_eff_ids, 1), 0);
    FOR v_i IN 1..v_n LOOP
        SELECT * INTO v_er FROM effect_requests er
         WHERE er.effect_id = v_eff_ids[v_i] FOR UPDATE;
        -- Current attempt = max attempt_no row, locked (the attempt row
        -- is the authority; the parent status only located the candidate).
        SELECT * INTO v_att FROM effect_attempts a
         WHERE a.effect_id = v_eff_ids[v_i]
         ORDER BY a.attempt_no DESC LIMIT 1 FOR UPDATE;

        -- (2) CAS re-verification under the locks: attempt still
        -- dispatch_started, still the current attempt, fence not yet
        -- superseded. Drift (a racing completion/allocation won) is
        -- recorded and skipped, never mutated.
        IF NOT FOUND OR v_er.status <> 'dispatch_started'
           OR v_att.status <> 'dispatch_started'
           OR v_er.attempt_no IS DISTINCT FROM v_att.attempt_no
           OR v_er.current_job_fence IS DISTINCT FROM v_att.dispatch_job_fence
           OR v_att.superseded_by_attempt_no IS NOT NULL THEN
            v_attempts := v_attempts || jsonb_build_object(
                'effect_id', v_eff_ids[v_i], 'disposition', 'not_in_flight');
            CONTINUE;
        END IF;
        IF EXISTS (SELECT 1 FROM steps st
                    WHERE st.step_id = v_eff_steps[v_i]
                      AND st.status IN ('succeeded', 'failed_terminal',
                                        'cancelled')) THEN
            v_attempts := v_attempts || jsonb_build_object(
                'effect_id', v_eff_ids[v_i], 'disposition', 'not_in_flight',
                'reason', 'step_terminal');
            CONTINUE;
        END IF;

        -- (2) job lease validity guard (frozen): a live job lease
        -- (holder set, expiry in the future = not expired and not
        -- revoked) skips the attempt ENTIRELY — no fence advance, no
        -- lease revoke, no settlement, effect/attempt/step/session
        -- control state untouched, the in-flight attempt stays. The
        -- session coordination lease is deliberately NOT consulted.
        -- Recovery is repeatable; a later rescan after the job lease
        -- expires processes the attempt through this same flow.
        IF v_er.lease_owner IS NOT NULL AND v_er.lease_until IS NOT NULL
           AND v_er.lease_until > now() THEN
            v_attempts := v_attempts || jsonb_build_object(
                'effect_id', v_eff_ids[v_i], 'attempt_no', v_att.attempt_no,
                'disposition', 'skipped_lease_valid',
                'lease_owner', v_er.lease_owner,
                'lease_until', v_er.lease_until);
            CONTINUE;
        END IF;

        -- (3a) result knownness: the unique evidence classification of
        -- the evidence presented for this attempt (no entry / unbound /
        -- insufficient evidence => 'unknown'; budget is NEVER a
        -- knownness input).
        v_ev := NULL;
        IF p_evidence IS NOT NULL AND jsonb_typeof(p_evidence) = 'object' THEN
            v_ev := p_evidence -> v_eff_ids[v_i]::text;
        END IF;
        v_cl := v_classify_evidence(v_eff_ids[v_i], v_att.attempt_no, v_ev);
        v_note := NULL;
        IF v_cl IN ('known_success', 'known_cancellation') THEN
            v_note := v_cl || '_deferred_to_repair';
            v_cl := 'unknown';
        END IF;
        v_t_eff := array_append(v_t_eff, v_eff_ids[v_i]);
        v_t_att := array_append(v_t_att, v_att.attempt_no);
        v_t_step := array_append(v_t_step, v_eff_steps[v_i]);
        v_t_class := array_append(v_t_class, v_cl);
        v_t_note := array_append(v_t_note, v_note);
        IF v_ev IS NOT NULL THEN
            v_used_keys := array_append(v_used_keys, v_eff_ids[v_i]::text);
        END IF;
    END LOOP;

    -- (3c) execution permission gate, structural form for this stage:
    -- quiescing forbids the known_failure retry disposition, so with at
    -- least one known_failure target the whole command refuses with zero
    -- control state (nothing has been mutated yet).
    -- G8b: the sticky cancel latch is NO LONGER a refusal here. The frozen
    -- gate semantics ("a sticky hit MUST first run the shared cancel
    -- closure") are satisfied in-transaction: the per-effect settlement
    -- below proceeds through the normal retry_eligible split and the shared
    -- aggregation rule 3 + applier then apply the closure exits (known
    -- retryable failure -> cancelled_after_dispatch + RETRY_SUPPRESSED_BY_
    -- CANCEL; a known terminal failure keeps failed_terminal) — the SAME
    -- sub-operation the normal completion entry (α) runs, so the two entries
    -- converge on identical effect/step/session facts.
    -- TODO(P1): the quiescing disposition (controlled-edge closure) is the
    -- driver-switch milestone.
    IF 'known_failure' = ANY (v_t_class)
       AND v_sess.driver_mode = 'quiescing' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'recovery_takeover', v_computed, 'rejected_mismatch',
            'DRIVER_QUIESCING',
            'driver_mode=quiescing: the known_failure retry disposition is forbidden (controlled-edge closure is G8)');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'DRIVER_QUIESCING'::text, v_receipt;
        RETURN;
    END IF;

    -- ------------------------------------------------------------------
    -- (2)+(3)+(4) mutations, per step: settle EVERY target of the step
    -- first (fence advance + lease revoke + old-attempt settlement),
    -- then ONE batch judgment over the fully settled state (the virtual
    -- aggregation of the 3(c) precondition; multiple settled effects of
    -- one takeover transaction are judged together, once).
    -- ------------------------------------------------------------------
    v_n := coalesce(array_length(v_t_eff, 1), 0);
    FOR v_step_id IN (SELECT DISTINCT s FROM unnest(v_t_step) s ORDER BY s) LOOP
        FOR v_i IN 1..v_n LOOP
            IF v_t_step[v_i] IS DISTINCT FROM v_step_id THEN
                CONTINUE;
            END IF;
            -- Pre-update read (row lock already held from the scan).
            -- NOTE (G8b): under the sticky latch this settlement is the
            -- INPUT to the shared cancel closure the per-step aggregation
            -- below runs (the closure converts an eligible failure to
            -- cancelled_after_dispatch), so the receipt's settled_status is
            -- the pre-closure settlement snapshot; the step receipt entry
            -- carries the final step/session state.
            SELECT * INTO v_er FROM effect_requests er
             WHERE er.effect_id = v_t_eff[v_i];
            v_reason := NULL;

            -- (2)+(4) CAS advance of the effect-level fence (the sole
            -- completion stale authority; the attempt row snapshot
            -- dispatch_job_fence stays untouched), and the old job
            -- lease revocation. The advance is unconditional for a
            -- taken-over attempt — allocation or not.
            v_newf := nextval('v8_job_fence_seq');
            UPDATE effect_requests SET
                current_job_fence = v_newf,
                lease_owner = NULL,
                lease_until = NULL,
                updated_at = now()
             WHERE effect_id = v_t_eff[v_i];

            IF v_t_class[v_i] = 'unknown' THEN
                -- (3b) unknown: effect+attempt -> unknown_outcome (code
                -- UNKNOWN_AFTER_DISPATCH via the rule-1 aggregation),
                -- budget-independent; repair is the only exit. Unique
                -- provisional turn/end {outcome:unknown} + provisional
                -- slot row when the turn has none yet (the existing
                -- unknown-closure shape).
                UPDATE effect_requests SET status = 'unknown_outcome',
                                               updated_at = now()
                 WHERE effect_id = v_t_eff[v_i];
                UPDATE effect_attempts SET status = 'unknown_outcome',
                                              completed_at = now()
                 WHERE effect_id = v_t_eff[v_i] AND attempt_no = v_t_att[v_i];
                -- G9b (s32b grammar (7) window exhaustion): a STREAMING
                -- attempt taken over with no terminal evidence settles
                -- unknown and records the STREAM_INCOMPLETE audit reason (a
                -- reason value, never a new closed code). The reason is
                -- read by the equivalence/portable verifier. Idempotent.
                IF (SELECT er.execution_mode FROM effect_requests er
                     WHERE er.effect_id = v_t_eff[v_i]) = 'streaming' THEN
                    PERFORM v_stream_incomplete_fact(
                        p_session_id, v_t_eff[v_i], v_t_att[v_i],
                        v_sha256_hex(coalesce(v_t_note[v_i], '')));
                END IF;
                SELECT st.turn_id INTO v_turn FROM steps st
                 WHERE st.step_id = v_step_id;
                IF NOT EXISTS (SELECT 1 FROM turn_end_slots tes
                                WHERE tes.session_id = p_session_id
                                  AND tes.turn_id = v_turn) THEN
                    v_end_payload := '{"outcome":"unknown"}';
                    v_end_hash := v_sha256_hex(v_end_payload);
                    v_endkey := v_completion_event_key(
                        p_session_id, 'turn/end', v_t_eff[v_i], v_t_att[v_i],
                        v_end_hash);
                    SELECT coalesce(max(se.internal_semantic_ordinal), 0) + 1
                      INTO v_iso
                      FROM session_events se
                     WHERE se.session_id = p_session_id;
                    INSERT INTO session_events(
                        seq, session_id, event_type, event_class,
                        schema_version, canonicalizer_version, event_key,
                        turn_id, step_id, effect_id, payload, payload_hash,
                        semantic_input_ordinal, internal_semantic_ordinal,
                        attempt_no, command_id, batch_item_ordinal)
                    VALUES (
                        v_seq, p_session_id, 'turn/end', 'semantic',
                        p_schema_version, p_canonicalizer_version, v_endkey,
                        v_turn, NULL, NULL, v_end_payload, v_end_hash, NULL,
                        v_iso, NULL, p_command_id, NULL);
                    v_seq := v_seq + 1;
                    INSERT INTO turn_end_slots(
                        session_id, turn_id, turn_end_key, head_event_key,
                        slot_status, resolution_identity_canonical, version)
                    VALUES (
                        p_session_id, v_turn,
                        v_turn_end_key(p_session_id, v_turn),
                        v_endkey, 'provisional', NULL, 1);
                END IF;
                v_status := 'unknown_outcome';
            ELSE
                -- (3c) known_failure disposition (determinations 2-3 of
                -- the third judgment): persist the dual-requirement
                -- evidence bound to the settled attempt (this takeover
                -- transaction IS the control-state persistence path),
                -- then settle through the shared retry_eligible split —
                -- the same settlement core as v_settle_known_failure.
                v_ev := p_evidence -> v_t_eff[v_i]::text;
                v_rec_id := v_ev->'provider_receipt'->>'receipt_id';
                INSERT INTO effect_evidence(
                    effect_id, attempt_no, evidence_class, receipt_id,
                    evidence_canonical)
                VALUES
                    (v_t_eff[v_i], v_t_att[v_i], 'failure_receipt', v_rec_id,
                     (v_ev->'provider_receipt')::text),
                    (v_t_eff[v_i], v_t_att[v_i], 'no_side_effect_proof', NULL,
                     (v_ev->'no_side_effect_proof')::text)
                ON CONFLICT DO NOTHING;

                v_elig := v_retry_eligible(v_t_eff[v_i]);
                v_fp := v_sha256_hex(v_ev::text);
                IF v_elig THEN
                    v_status := 'failed_retryable';
                    UPDATE effect_requests SET
                        status = 'failed_retryable',
                        result_hash = v_fp,
                        provider_request_id = v_rec_id,
                        updated_at = now()
                     WHERE effect_id = v_t_eff[v_i];
                    UPDATE effect_attempts SET
                        status = 'failed_retryable',
                        result_hash = v_fp,
                        provider_request_id = v_rec_id,
                        completed_at = now()
                     WHERE effect_id = v_t_eff[v_i]
                       AND attempt_no = v_t_att[v_i];
                ELSE
                    v_status := 'failed_terminal';
                    UPDATE effect_requests SET
                        status = 'failed_terminal',
                        result_hash = v_fp,
                        provider_request_id = v_rec_id,
                        updated_at = now()
                     WHERE effect_id = v_t_eff[v_i];
                    UPDATE effect_attempts SET
                        status = 'failed_terminal',
                        result_hash = v_fp,
                        provider_request_id = v_rec_id,
                        completed_at = now()
                     WHERE effect_id = v_t_eff[v_i]
                       AND attempt_no = v_t_att[v_i];
                    v_reason := v_retry_stop_reason_cas(v_t_eff[v_i]);
                END IF;
            END IF;

            v_entry := jsonb_build_object(
                'effect_id', v_t_eff[v_i],
                'attempt_no', v_t_att[v_i],
                'disposition', 'taken_over',
                'classification', v_t_class[v_i],
                'settled_status', v_status,
                'retry_stop_reason', v_reason,
                'old_job_fence', v_er.current_job_fence,
                'new_job_fence', v_newf,
                'revoked_lease_owner', v_er.lease_owner,
                'revoked_lease_until', v_er.lease_until);
            IF v_t_note[v_i] IS NOT NULL THEN
                v_entry := v_entry || jsonb_build_object('note',
                                                         v_t_note[v_i]);
            END IF;
            v_attempts := v_attempts || v_entry;
        END LOOP;

        -- (3c) batch determination over the FULLY settled batch state:
        -- the shared judgment function (identical to completion). Rule
        -- 1/2 => settle-only (no allocation); rule 4 => the shared
        -- closure through the controlled edge (no allocation); rule 5
        -- => the cohort allocation via the SAME sub-operation as
        -- retry_effect (the second entry, single creation path).
        SELECT * INTO v_agg FROM v_aggregate_step(v_step_id);
        IF v_agg.rule_no IN (1, 2, 3, 4) THEN
            PERFORM v_apply_step_aggregation(
                p_session_id, v_step_id, v_agg.rule_no, v_agg.step_status,
                v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
                v_agg.closure_effect_ids, p_command_id, v_computed);
            v_steps_out := v_steps_out || jsonb_build_object(
                'step_id', v_step_id,
                'allocated', false,
                'rule_no', v_agg.rule_no,
                'step_status', v_agg.step_status,
                'session_state', v_agg.session_state,
                'failure_code', v_agg.failure_code);
        ELSIF v_agg.rule_no = 5 THEN
            v_alloc := v_retry_cohort_allocation(p_session_id, v_step_id,
                                                  p_command_id);
            IF NOT (v_alloc->>'allocated')::boolean THEN
                RAISE EXCEPTION
                    'INFRA_PROTOCOL_VIOLATION: recovery takeover cohort '
                    'allocation declined after a rule-5 judgment (step %): %',
                    v_step_id, v_alloc;
            END IF;
            v_steps_out := v_steps_out
                || (jsonb_build_object('step_id', v_step_id) || v_alloc);
        ELSE
            RAISE EXCEPTION
                'INFRA_PROTOCOL_VIOLATION: recovery takeover batch judgment '
                'expected rule 1/2/4/5, got rule % (step %)',
                v_agg.rule_no, v_step_id;
        END IF;
    END LOOP;

    -- Unused evidence keys (entries naming non-target effects) are
    -- surfaced in the receipt for observability.
    IF p_evidence IS NOT NULL AND jsonb_typeof(p_evidence) = 'object' THEN
        FOR v_k IN (SELECT * FROM jsonb_object_keys(p_evidence)) LOOP
            IF NOT (v_k = ANY (v_used_keys)) THEN
                v_unused := v_unused || to_jsonb(v_k);
            END IF;
        END LOOP;
    END IF;

    IF v_seq IS DISTINCT FROM v_seq0 THEN
        UPDATE sessions SET next_seq = v_seq, updated_at = now()
         WHERE session_id = p_session_id;
    END IF;

    -- G8b (δ): the sticky closure may have collapsed the session through the
    -- rule-3 aggregation above; the canonical turn/end is then derived by the
    -- SHARED derivation (self-guarding: only a collapsed `cancelled` session
    -- and only a turn whose slot row is still absent) — never a second
    -- turn/end rule. Called after the seq allocator update so the derived
    -- event takes the next free seq.
    v_end := v_derive_cancel_turn_end(p_session_id, p_command_id,
                                      p_schema_version,
                                      p_canonicalizer_version);

    v_receipt := jsonb_build_object(
        'command_kind', 'recovery_takeover',
        'command_id', p_command_id,
        'attempts', v_attempts,
        'steps', v_steps_out,
        'evidence_unused', v_unused,
        'derived_turn_end', coalesce(v_end, 'null'::jsonb),
        'session_state', (SELECT s.state FROM sessions s
                           WHERE s.session_id = p_session_id),
        'session_fence', (SELECT s.session_fence FROM sessions s
                           WHERE s.session_id = p_session_id));

    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'recovery_takeover',
            'canonical_request_hash', v_computed, 'accepted', NULL,
            v_receipt::text, v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;
