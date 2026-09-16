-- v8 G6: tools seal — the second seal path (digest s31b §2.6.2, four steps
-- verbatim) and the sealed-batch event key for seal-generated tool/call
-- semantic events.
--
-- Source of truth: docs/designs/v8-dev.md (frozen spec), digest
-- docs/analysis/v8-impl-digest/s31b-command-table.md §2.6.2 (tools seal
-- four steps), s32a-step-session.md §2.1 rule 6 (final_tools aggregation,
-- next-decision-step continuation) + §4.1 (step state machine
-- waiting_effect <-> ready, stage decision/tools/closed), s32b §2.4
-- (create_effect_in_seal building mode: first attempt in the same seal
-- transaction, publish-as-ready).
--
-- Transaction boundaries are owned by the CALLER (same convention as
-- G3/G4): the Python client runs gate + business function + commit in one
-- transaction, so receipts, control mutations and events commit together.
--
-- G6 scope guards (explicit, [LATER] in the digests): the seal
-- authorization stage and the generation check (GRANT_DENIED /
-- GENERATION_REVOKED) are absent; retry, cancel and repair are not
-- implemented. Slot specs are frozen to execution_mode='non_streaming'.

-- ---------------------------------------------------------------------------
-- Database-internal derived event key for seal-generated semantic events
-- (tool/call) whose slot-level occurrence identity is (batch_id,
-- dispatch_ordinal) — spec §3.1.2 event-key layer (1)(b)(ii), Conformance
-- 1 scenario (4): two slots of one batch calling the SAME tool with the
-- SAME arguments get two independent events with mutually distinct keys
-- (the identity is constructed over (batch_id, dispatch_ordinal), never
-- deduplicated by tool/argument content). The payload hash is bound into
-- the key as well, mirroring v_nonstream_event_key / v_completion_event_key.
-- Mirrored byte-for-byte by the Python reference in v8/tools/client.py.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_seal_event_key(
    p_session_id uuid, p_event_type text, p_batch_id uuid,
    p_dispatch_ordinal bigint, p_payload_hash text
) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN encode(sha256(
    convert_to('v8:seal-event-key@db1', 'UTF8') || '\x00'::bytea
    || v_len8(v_uuid16(p_session_id)) || v_uuid16(p_session_id)
    || v_len8(v_identity_bytes(p_event_type)) || v_identity_bytes(p_event_type)
    || v_len8(v_uuid16(p_batch_id)) || v_uuid16(p_batch_id)
    || v_canonical_integer_bytes(p_dispatch_ordinal)
    || v_len8(v_identity_bytes(p_payload_hash)) || v_identity_bytes(p_payload_hash)
), 'hex');

-- ---------------------------------------------------------------------------
-- v_seal_batch — the tools seal (digest s31b §2.6.2, four steps in the
-- frozen order).
--
-- Step (i)  receipt replay first: the command adjudication order runs as
--           for every command (same command_id + same canonical payload ->
--           original receipt returned); a replay under a NEW command_id is
--           detected via the unique tools batch this seal would create
--           (step_id, expected sealed_batch_no + 1): identical
--           result/batch identity + plan_hash + slot payload returns the
--           ORIGINAL seal receipt and saves a referencing receipt for the
--           new command_id; any inconsistency is a stable mismatch.
-- Step (ii) lock session/step (master lock order positions 1-2), CAS
--           status='ready' AND stage='decision' + expected sealed_batch_no
--           + driver/epoch/fence + active mode + no sticky cancel +
--           claimed coordination lease; verify the accepted decision result
--           identity (effect_id, attempt_no, result_hash, event_key)
--           against the persisted decision effect/event; recompute
--           plan_hash from the PERSISTED plan; require final_tools=true
--           explicitly.
-- Step (iii) one transaction: stage=tools, sealed_batch_no+1, unique batch
--           identity (kind='tools'), the complete slot manifest and ALL
--           tool effects (create_effect_in_seal building mode:
--           effect_kind='tool', execution_mode='non_streaming', fixed
--           dispatch_ordinal per slot, tool_call_id, frozen
--           retry_class/max_attempts/request_hash/idempotency_key, first
--           attempt in the same transaction with the job fence frozen at
--           the same value as effect current_job_fence, publish-as-ready),
--           the per-slot tool/call semantic events (slot-level occurrence
--           identity (batch_id, dispatch_ordinal)), sealed=true set once at
--           the end of the transaction, aggregation to waiting_effect.
--           An in-transaction CAS rejection is the WHOLE seal with zero
--           side effects (binding + rejection receipt only).
-- Step (iv) terminalization is NOT done here: only a decision_only=true
--           successful decision or a final_tools=true all-succeeded tools
--           batch terminalize (rule 6, implemented in v_complete_effect).
--
-- An empty plan is rejected explicitly (EMPTY_TOOLS_PLAN): an empty batch
-- must never be sealed (and can never succeed-close a step).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_seal_batch(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint, p_session_fence bigint,
    p_step_id uuid, p_expected_sealed_batch_no bigint,
    p_decision_effect_id uuid, p_decision_attempt_no bigint,
    p_decision_result_hash text, p_decision_event_key text,
    p_plan_hash text,
    p_schema_version text, p_canonicalizer_version text,
    p_declared_hash text, p_payload_canonical text,
    p_slots jsonb
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_step steps%ROWTYPE;
    v_prior batches%ROWTYPE;
    v_dec record;
    v_dec_ev record;
    v_eff record;
    v_orig record;
    v_receipt jsonb;
    v_n int;
    v_i int;
    v_slot jsonb;
    v_pj jsonb;
    v_effect_id uuid;
    v_tool_call_id text;
    v_job_fence bigint;
    v_new_fence bigint;
    v_new_batch_no bigint;
    v_batch_id uuid;
    v_payload text;
    v_payload_hash text;
    v_evkey text;
    v_iso bigint;
    v_seq bigint;
    v_cnt bigint;
    v_effects jsonb;
    v_events jsonb;
    v_match boolean;
    v_dec_ok boolean;
    v_plan_ok boolean;
BEGIN
    -- Step (ii) preamble: judgment order (1)-(4) with the session row lock
    -- (master lock order position 1) taken inside the adjudicator.
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'seal_batch',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;

    -- Lock the step (master lock order position 2) BEFORE the prior-seal
    -- lookup, so the replay/CAS split is decided under the lock.
    SELECT * INTO v_step FROM steps st
     WHERE st.step_id = p_step_id AND st.session_id = p_session_id
     FOR UPDATE;
    IF v_step.step_id IS NULL THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_mismatch', 'STEP_NOT_FOUND',
            'step_id does not locate a persisted step of this session');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'STEP_NOT_FOUND'::text, v_receipt;
        RETURN;
    END IF;

    -- Shared decision-result-identity verification (used by BOTH the replay
    -- branch and the CAS branch): the envelope's four identity components
    -- must match the persisted successful decision effect of this step's
    -- decision batch and the SQL-generated assistant/message event it
    -- produced. Repair-persisted identities are consumed identically (same
    -- columns, same recomputation — no second identity scheme).
    SELECT er.effect_id, er.status, er.attempt_no, er.result_hash, b.kind AS batch_kind
      INTO v_dec
      FROM effect_requests er
      JOIN batches b ON b.batch_id = er.batch_id
     WHERE er.effect_id = p_decision_effect_id
       AND er.step_id = p_step_id;
    v_dec_ok :=
        ((v_dec.effect_id IS NOT NULL)
         AND (v_dec.batch_kind = 'decision')
         AND (v_dec.status = 'succeeded')
         AND (v_dec.attempt_no = p_decision_attempt_no)
         AND (v_dec.result_hash = p_decision_result_hash)
         AND EXISTS (SELECT 1 FROM effect_attempts a
                      WHERE a.effect_id = p_decision_effect_id
                        AND a.attempt_no = p_decision_attempt_no
                        AND a.status = 'succeeded')
         AND EXISTS (SELECT 1 FROM session_events se
                      WHERE se.session_id = p_session_id
                        AND se.event_key = p_decision_event_key
                        AND se.event_type = 'assistant/message'
                        AND se.effect_id = p_decision_effect_id
                        AND se.attempt_no = p_decision_attempt_no)) IS TRUE;
    -- Plan recomputation from the PERSISTED plan (never the envelope's
    -- bytes): the stored plan's hash must match both the stored plan_hash
    -- and the envelope's expected plan_hash.
    v_plan_ok :=
        ((v_step.plan_canonical IS NOT NULL)
         AND (v_sha256_hex(v_step.plan_canonical) = v_step.plan_hash)
         AND (p_plan_hash = v_step.plan_hash)) IS TRUE;

    -- ---- step (i): prior seal receipt lookup ----
    -- The unique tools batch this seal's CAS would create.
    SELECT * INTO v_prior FROM batches b
     WHERE b.session_id = p_session_id
       AND b.step_id = p_step_id
       AND b.sealed_batch_no = p_expected_sealed_batch_no + 1
       AND b.kind = 'tools';

    IF v_prior.batch_id IS NOT NULL THEN
        -- Replay under a new command_id: same result/batch identity +
        -- plan_hash + slot payload MUST return the original seal receipt
        -- (and save a referencing receipt for this command_id); anything
        -- else is a stable mismatch with zero side effects.
        IF p_slots IS NULL OR jsonb_typeof(p_slots) <> 'array' THEN
            v_n := 0;
            v_match := false;
        ELSE
            v_n := jsonb_array_length(p_slots);
            SELECT count(*) INTO v_cnt FROM effect_requests er
             WHERE er.batch_id = v_prior.batch_id;
            v_match := (v_cnt = v_n);
        END IF;
        FOR v_i IN 0 .. v_n - 1 LOOP
            v_slot := p_slots -> v_i;
            SELECT er.effect_id, er.tool_call_id, er.request_hash, er.idempotency_key,
                   er.execution_mode, er.retry_class, er.max_attempts,
                   (SELECT se.payload FROM session_events se
                     WHERE se.session_id = p_session_id
                       AND se.event_type = 'tool/call'
                       AND se.effect_id = er.effect_id LIMIT 1) AS call_payload
              INTO v_eff
              FROM effect_requests er
             WHERE er.batch_id = v_prior.batch_id
               AND er.dispatch_ordinal = v_i;
            IF NOT (
                (v_eff.effect_id IS NOT NULL)
                AND ((v_eff.effect_id)::text = (v_slot->>'effect_id'))
                AND (v_eff.tool_call_id = (v_slot->>'tool_call_id'))
                AND (v_eff.request_hash = (v_slot->>'request_hash'))
                AND (v_eff.idempotency_key = (v_slot->>'idempotency_key'))
                AND (v_eff.execution_mode = (v_slot->>'execution_mode'))
                AND (v_eff.retry_class = (v_slot->>'retry_class'))
                AND ((v_eff.max_attempts)::text = (v_slot->>'max_attempts'))
                AND (v_eff.call_payload = (v_slot->>'payload_canonical'))
            ) IS TRUE THEN
                v_match := false;
            END IF;
        END LOOP;

        IF NOT (v_match AND v_dec_ok AND v_plan_ok
                AND (v_step.final_tools IS TRUE)) IS TRUE THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
                v_computed, 'rejected_mismatch', 'SEAL_MISMATCH',
                'replay of an already-sealed tools batch with inconsistent result identity, plan_hash or slot payload');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'SEAL_MISMATCH'::text, v_receipt;
            RETURN;
        END IF;

        -- The original accepted seal receipt for this batch.
        SELECT cr.command_id, cr.result_canonical
          INTO v_orig
          FROM command_receipts cr
         WHERE cr.session_id = p_session_id
           AND cr.command_kind = 'seal_batch'
           AND cr.outcome = 'accepted'
           AND (cr.result_canonical::jsonb)->>'batch_id' = (v_prior.batch_id)::text
         ORDER BY cr.created_at
         LIMIT 1;
        IF v_orig.command_id IS NULL THEN
            RAISE EXCEPTION
                'INFRA_PROTOCOL_VIOLATION: sealed tools batch % has no accepted '
                'seal receipt (session %)', v_prior.batch_id, p_session_id;
        END IF;
        v_receipt := (v_orig.result_canonical)::jsonb || jsonb_build_object(
            'replay', true,
            'replay_of_command_id', v_orig.command_id);
        INSERT INTO command_bindings(
            session_id, command_id, first_key_kind, first_key_value, first_outcome)
        VALUES (p_session_id, p_command_id, 'canonical_request_hash',
                v_computed, 'accepted');
        INSERT INTO command_receipts(
            session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
            outcome, code, result_canonical, result_hash)
        VALUES (p_session_id, p_command_id, 'seal_batch', 'canonical_request_hash',
                v_computed, 'accepted', NULL, v_receipt::text,
                v_sha256_hex(v_receipt::text));
        RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
        RETURN;
    END IF;

    -- ---- step (ii): seal CAS guards, all BEFORE any business mutation ----
    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_stale', 'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session control row');
        RETURN QUERY SELECT 'rejected_stale'::text, 'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF p_session_fence IS DISTINCT FROM v_sess.session_fence THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_stale', 'SESSION_FENCE_STALE',
            format('expected session_fence %s does not match current %s',
                   coalesce(p_session_fence::text, 'NULL'), v_sess.session_fence));
        RETURN QUERY SELECT 'rejected_stale'::text, 'SESSION_FENCE_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.driver_mode <> 'active' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_mismatch', 'DRIVER_QUIESCING',
            'seal requires driver_mode=active');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'DRIVER_QUIESCING'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.state <> 'claimed' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_mismatch', 'SESSION_NOT_CLAIMED',
            format('tools seal requires state=claimed (coordination lease held), got %s',
                   v_sess.state));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_NOT_CLAIMED'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.cancellation_epoch > 0 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_mismatch', 'CANCEL_STICKY',
            'sticky cancel latch set: the whole seal is rejected with zero side effects');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'CANCEL_STICKY'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.lease_owner IS NULL OR v_sess.lease_until IS NULL
       OR v_sess.lease_until <= now() THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_stale', 'LEASE_NOT_HELD',
            'coordination lease vacant or expired');
        RETURN QUERY SELECT 'rejected_stale'::text, 'LEASE_NOT_HELD'::text, v_receipt;
        RETURN;
    END IF;
    -- The step CAS itself: ready + stage=decision is the ONLY precondition
    -- under which the tools seal may run (an accepted tools-plan decision
    -- result waiting for its batch; digest s32a 4.1 ready out-edge).
    IF v_step.status <> 'ready' OR v_step.stage <> 'decision' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_mismatch', 'STEP_NOT_SEALABLE',
            format('tools seal CAS requires status=ready, stage=decision; got %s/%s',
                   v_step.status, v_step.stage));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'STEP_NOT_SEALABLE'::text, v_receipt;
        RETURN;
    END IF;
    IF p_expected_sealed_batch_no IS DISTINCT FROM v_step.sealed_batch_no THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_stale', 'SEALED_BATCH_NO_STALE',
            format('expected sealed_batch_no %s does not match current %s',
                   coalesce(p_expected_sealed_batch_no::text, 'NULL'),
                   v_step.sealed_batch_no));
        RETURN QUERY SELECT 'rejected_stale'::text, 'SEALED_BATCH_NO_STALE'::text, v_receipt;
        RETURN;
    END IF;
    IF NOT v_dec_ok THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_mismatch', 'DECISION_IDENTITY_MISMATCH',
            'the decision result identity does not match the accepted successful decision of this step');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'DECISION_IDENTITY_MISMATCH'::text, v_receipt;
        RETURN;
    END IF;
    IF NOT v_plan_ok THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_mismatch', 'PLAN_HASH_MISMATCH',
            'plan_hash does not match the hash recomputed from the persisted tools plan');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'PLAN_HASH_MISMATCH'::text, v_receipt;
        RETURN;
    END IF;
    IF v_step.decision_only IS TRUE OR v_step.final_tools IS NOT TRUE THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_mismatch', 'DECISION_MARK_INVALID',
            'tools seal requires the persisted decision marks decision_only=false AND final_tools=true');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'DECISION_MARK_INVALID'::text, v_receipt;
        RETURN;
    END IF;

    -- Slot manifest validation (table CHECKs would abort the transaction
    -- and lose the receipt; reject classified instead). The manifest is an
    -- ordered array; the array position IS the frozen dispatch_ordinal.
    IF p_slots IS NULL OR jsonb_typeof(p_slots) <> 'array' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_mismatch', 'SLOT_SPEC_INVALID',
            'slots must be a JSON array');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SLOT_SPEC_INVALID'::text, v_receipt;
        RETURN;
    END IF;
    v_n := jsonb_array_length(p_slots);
    IF v_n = 0 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
            v_computed, 'rejected_mismatch', 'EMPTY_TOOLS_PLAN',
            'an empty tools batch must not be sealed (and can never succeed-close a step)');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EMPTY_TOOLS_PLAN'::text, v_receipt;
        RETURN;
    END IF;
    FOR v_i IN 0 .. v_n - 1 LOOP
        v_slot := p_slots -> v_i;
        IF jsonb_typeof(v_slot) <> 'object'
           OR jsonb_typeof(v_slot->'effect_id') <> 'string'
           OR (v_slot->>'effect_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
           OR jsonb_typeof(v_slot->'tool_call_id') <> 'string'
           OR length(v_slot->>'tool_call_id') = 0
           OR jsonb_typeof(v_slot->'tool') <> 'string'
           OR length(v_slot->>'tool') = 0
           OR NOT (v_slot ? 'arguments')
           OR jsonb_typeof(v_slot->'payload_canonical') <> 'string'
           OR (v_slot->>'execution_mode') <> 'non_streaming'
           OR (v_slot->>'retry_class') NOT IN
                ('provider_idempotent', 'verifiable_no_effect', 'unsafe')
           OR v8_entry_int(v_slot->'max_attempts') IS NULL
           OR v8_entry_int(v_slot->'max_attempts') < 1
           OR jsonb_typeof(v_slot->'request_hash') <> 'string'
           OR length(v_slot->>'request_hash') = 0
           OR jsonb_typeof(v_slot->'idempotency_key') <> 'string'
           OR length(v_slot->>'idempotency_key') = 0 THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
                v_computed, 'rejected_mismatch', 'SLOT_SPEC_INVALID',
                format('slot %s violates the frozen slot value domains', v_i));
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'SLOT_SPEC_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        -- Slot effect_id / tool_call_id uniqueness inside the manifest.
        IF EXISTS (SELECT 1
                     FROM jsonb_array_elements(p_slots) WITH ORDINALITY AS t(elem, ord)
                    WHERE t.ord::int - 1 < v_i
                      AND (t.elem->>'effect_id') = (v_slot->>'effect_id'))
           OR EXISTS (SELECT 1
                        FROM jsonb_array_elements(p_slots) WITH ORDINALITY AS t(elem, ord)
                       WHERE t.ord::int - 1 < v_i
                         AND (t.elem->>'tool_call_id') = (v_slot->>'tool_call_id')) THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
                v_computed, 'rejected_mismatch', 'SLOT_SPEC_INVALID',
                format('slot %s repeats an earlier effect_id or tool_call_id', v_i));
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'SLOT_SPEC_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        -- The tool/call payload canonical text must parse as a JSON object
        -- and be jsonb-equal to the {tool_call_id, tool, arguments} subset
        -- of the slot (binds the persisted event bytes to the manifest).
        BEGIN
            v_pj := (v_slot->>'payload_canonical')::jsonb;
        EXCEPTION WHEN OTHERS THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
                v_computed, 'rejected_mismatch', 'SLOT_SPEC_INVALID',
                format('slot %s payload_canonical is not valid JSON', v_i));
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'SLOT_SPEC_INVALID'::text, v_receipt;
            RETURN;
        END;
        IF jsonb_typeof(v_pj) <> 'object'
           OR v_pj IS DISTINCT FROM jsonb_build_object(
                  'tool_call_id', v_slot->'tool_call_id',
                  'tool', v_slot->'tool',
                  'arguments', v_slot->'arguments') THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'seal_batch',
                v_computed, 'rejected_mismatch', 'SLOT_SPEC_INVALID',
                format('slot %s payload_canonical does not match its tool_call_id/tool/arguments', v_i));
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'SLOT_SPEC_INVALID'::text, v_receipt;
            RETURN;
        END IF;
    END LOOP;

    -- ---- step (iii): one-transaction seal ----
    v_new_batch_no := v_step.sealed_batch_no + 1;
    v_batch_id := gen_random_uuid();
    INSERT INTO batches(batch_id, session_id, step_id, sealed_batch_no, kind, sealed)
    VALUES (v_batch_id, p_session_id, p_step_id, v_new_batch_no, 'tools', false);

    v_effects := '[]'::jsonb;
    v_events := '[]'::jsonb;
    v_iso := (SELECT coalesce(max(se.internal_semantic_ordinal), 0) + 1
                FROM session_events se WHERE se.session_id = p_session_id);
    v_seq := v_sess.next_seq;

    FOR v_i IN 0 .. v_n - 1 LOOP
        v_slot := p_slots -> v_i;
        v_effect_id := (v_slot->>'effect_id')::uuid;
        v_tool_call_id := v_slot->>'tool_call_id';
        v_job_fence := nextval('v8_job_fence_seq');

        -- create_effect_in_seal building mode: member creation inside the
        -- seal transaction, planned is an in-transaction state only.
        INSERT INTO effect_requests(
            effect_id, session_id, step_id, batch_id, dispatch_ordinal, tool_call_id,
            effect_kind, execution_mode, driver, driver_epoch, session_fence,
            dispatch_session_fence, current_job_fence, request_hash, idempotency_key,
            status, retry_class, max_attempts, attempt_no, dispatch_count)
        VALUES (
            v_effect_id, p_session_id, p_step_id, v_batch_id, v_i, v_tool_call_id,
            'tool', 'non_streaming', v_sess.driver, v_sess.driver_epoch,
            v_sess.session_fence, v_sess.session_fence, v_job_fence,
            v_slot->>'request_hash', v_slot->>'idempotency_key',
            'planned', v_slot->>'retry_class',
            v8_entry_int(v_slot->'max_attempts')::bigint, 1, 0);

        -- The first (and only) attempt creation entry point: same
        -- transaction, attempt_no=1, dispatch_job_fence frozen at the same
        -- value as effect current_job_fence, execution snapshot frozen.
        INSERT INTO effect_attempts(
            effect_id, attempt_no, session_id, step_id, driver, driver_epoch,
            session_fence, dispatch_session_fence, dispatch_job_fence, request_hash,
            idempotency_key, execution_mode, status)
        VALUES (
            v_effect_id, 1, p_session_id, p_step_id, v_sess.driver, v_sess.driver_epoch,
            v_sess.session_fence, v_sess.session_fence, v_job_fence,
            v_slot->>'request_hash', v_slot->>'idempotency_key',
            'non_streaming', 'ready');

        -- Slot-level occurrence identity (batch_id, dispatch_ordinal): the
        -- SQL-generated tool/call semantic event for this slot.
        v_payload := v_slot->>'payload_canonical';
        v_payload_hash := v_sha256_hex(v_payload);
        v_evkey := v_seal_event_key(p_session_id, 'tool/call', v_batch_id, v_i,
                                    v_payload_hash);
        INSERT INTO session_events(
            seq, session_id, event_type, event_class, schema_version,
            canonicalizer_version, event_key, turn_id, step_id, effect_id,
            payload, payload_hash, semantic_input_ordinal, internal_semantic_ordinal,
            attempt_no, command_id, batch_item_ordinal)
        VALUES (
            v_seq, p_session_id, 'tool/call', 'semantic', p_schema_version,
            p_canonicalizer_version, v_evkey, v_step.turn_id, p_step_id, v_effect_id,
            v_payload, v_payload_hash, NULL, v_iso, NULL,
            p_command_id, NULL);
        v_effects := v_effects || jsonb_build_object(
            'effect_id', v_effect_id, 'dispatch_ordinal', v_i,
            'tool_call_id', v_tool_call_id, 'job_fence', v_job_fence);
        v_events := v_events || jsonb_build_object(
            'event_type', 'tool/call', 'seq', v_seq, 'event_key', v_evkey);
        v_seq := v_seq + 1;
        v_iso := v_iso + 1;
    END LOOP;

    -- Publish-as-ready (frozen): the sealed effects flip to ready inside
    -- the same transaction; the dispatch gate is immediately visible after
    -- commit. No partially-sealed batch is ever observable: sealed is set
    -- once, at the end of the transaction.
    UPDATE effect_requests SET status = 'ready', updated_at = now()
     WHERE batch_id = v_batch_id;
    UPDATE batches SET sealed = true WHERE batch_id = v_batch_id;

    -- Step transitions + aggregation to waiting_effect (rule 2). Leaving
    -- claimed revokes the coordination lease and bumps the fence
    -- (controlled-transaction rule: old coordination writes go stale).
    UPDATE steps SET
        stage = 'tools',
        sealed_batch_no = v_new_batch_no,
        status = 'waiting_effect',
        pending_effect_count = v_n,
        updated_at = now()
     WHERE step_id = p_step_id;
    v_new_fence := v_sess.session_fence + 1;
    UPDATE sessions SET
        state = 'waiting_effect',
        session_fence = v_new_fence,
        lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
        next_seq = v_seq,
        updated_at = now()
     WHERE session_id = p_session_id;

    v_receipt := jsonb_build_object(
        'command_kind', 'seal_batch',
        'command_id', p_command_id,
        'step_id', p_step_id,
        'turn_id', v_step.turn_id,
        'batch_id', v_batch_id,
        'sealed_batch_no', v_new_batch_no,
        'decision', jsonb_build_object(
            'effect_id', p_decision_effect_id,
            'attempt_no', p_decision_attempt_no,
            'result_hash', p_decision_result_hash,
            'event_key', p_decision_event_key),
        'plan_hash', p_plan_hash,
        'effects', v_effects,
        'events', v_events,
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
    VALUES (p_session_id, p_command_id, 'seal_batch', 'canonical_request_hash',
            v_computed, 'accepted', NULL, v_receipt::text,
            v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;
