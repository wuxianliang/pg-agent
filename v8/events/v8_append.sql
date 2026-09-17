-- v8 G3: public append_events layer — command adjudication (receipt/binding
-- judgment order (1)-(4)), the protected seven-step semantic append function,
-- and the controlled P0B session bootstrap.
--
-- Source of truth: docs/designs/v8-dev.md section 3.1.2 (lines 299-396) and
-- the digest docs/analysis/v8-impl-digest/s31b-command-table.md sections
-- 2.1-2.3 (envelope / receipt judgment order / outcome closed set), 2.5
-- (append_events command-table row), 2.7 (frozen event type permission
-- matrix), 2.9 (the seven-step protected append, implemented verbatim below),
-- 3.7 (non-stream event key).
--
-- Transaction boundaries are owned by the CALLER: the Python client runs
-- gate + business function + commit inside one transaction, so receipts,
-- control mutations and events commit together and vanish together on
-- rollback (spec section 3.1.2 unified envelope contract).

-- ---------------------------------------------------------------------------
-- Controlled P0B session bootstrap.
--
-- The frozen command list has no public start_session command; session rows
-- are created by internal control paths (claim/bootstrap). This minimal
-- entry point exists so the P0B loop has a session to append into; the
-- frozen initial row shape (state=ready, driver_mode=active, session_fence=1,
-- driver_epoch=1, next_seq=1, cancellation_epoch=0, lease/pointer/failure
-- columns NULL) is enforced by the G2 BEFORE INSERT trigger, not here.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_create_session(
    p_session_id uuid, p_driver text, p_workspace_id uuid DEFAULT NULL
) RETURNS boolean
LANGUAGE plpgsql AS $$
BEGIN
    -- G10: the optional p_workspace_id binds the calling session to its
    -- tenant (the section 2.1 conjunct-2 calling-session leg). NULL
    -- (default) keeps every legacy gate session unscoped.
    INSERT INTO sessions(session_id, driver, workspace_id)
    VALUES (p_session_id, p_driver, p_workspace_id)
    ON CONFLICT (session_id) DO NOTHING;
    RETURN FOUND;
END;
$$;

-- ---------------------------------------------------------------------------
-- Entry-envelope integer decoder: a JSON number, or the frozen tagged
-- integer reserved object {"$int": "<decimal>"} for values beyond 2^53-1
-- (canonical profile section 1.3 — both legal wire forms of one integer
-- value decode to the same numeric). Returns NULL for anything else
-- (absent, non-numeric, non-integral lexical forms); callers reject.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v8_entry_int(v jsonb) RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN v IS NULL THEN NULL
        WHEN jsonb_typeof(v) = 'number' THEN (v #>> '{}')::numeric
        WHEN jsonb_typeof(v) = 'object' AND v = jsonb_build_object('$int', v->'$int')
             AND jsonb_typeof(v->'$int') = 'string'
             AND (v->>'$int') ~ '^-?[0-9]+$'
            THEN (v->>'$int')::numeric
        ELSE NULL
    END
$$;

-- ---------------------------------------------------------------------------
-- Receipt/binding rejection writer (binding still free, canonical path).
-- Occupies the command binding with the actual rejection outcome and writes
-- the stable receipt keyed by the computed canonical request hash (digest
-- 2.2 step (3)/(4): first-arrived attributable request occupies the binding
-- whatever the outcome; receipts never vanish via rollback).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v8_reject_command(
    p_session_id uuid, p_command_id text, p_command_kind text,
    p_computed_hash text, p_outcome text, p_code text, p_detail text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_receipt jsonb;
BEGIN
    v_receipt := jsonb_build_object(
        'command_kind', p_command_kind,
        'command_id', p_command_id,
        'outcome', p_outcome,
        'code', p_code,
        'detail', p_detail);
    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            p_computed_hash, p_outcome);
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
        outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, p_command_kind, 'canonical_request_hash',
            p_computed_hash, p_outcome, p_code, v_receipt::text,
            v_sha256_hex(v_receipt::text));
    RETURN v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- Command adjudication, canonical_request_hash path only (this stage).
-- Digest 2.2 steps (1)-(4) in the frozen order. Takes the session row lock
-- first (position 1 of the eight-slot master lock order) so two concurrent
-- commands over one session serialize and the later one re-reads everything
-- inside the lock.
--
-- Returns adj_kind:
--   'replay'         existing receipt hit -> idempotent return of the original
--                    receipt (no re-execution, no state/fence/epoch re-check)
--   'binding_replay' defensive: binding holds our exact key but no receipt
--                    row survives (abnormal; replays first_outcome)
--   'conflict'       command_id already bound to a different key value ->
--                    IDEMPOTENCY_CONFLICT receipt written, first binding kept
--   'mismatch'       declared hash <> computed hash -> REQUEST_HASH_MISMATCH,
--                    binding occupied, command not executed
--   'execute'        binding free + declared hash matches: caller proceeds to
--                    the full identity/state/business guards and writes the
--                    binding/receipt with the ACTUAL outcome (step (4))
-- ---------------------------------------------------------------------------
CREATE FUNCTION v8_command_adjudicate(
    p_session_id uuid, p_command_id text, p_command_kind text,
    p_payload_canonical text, p_declared_hash text
) RETURNS TABLE(adj_kind text, adj_outcome text, adj_code text, adj_receipt jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_r_outcome text;
    v_r_code text;
    v_r_canonical text;
    v_bind command_bindings%ROWTYPE;
    v_receipt jsonb;
BEGIN
    -- Master lock order position 1: session control row.
    PERFORM 1 FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;
    IF NOT FOUND THEN
        -- No session row: a receipt cannot persist (FK); fail closed.
        RAISE EXCEPTION 'v8: session % not found', p_session_id;
    END IF;

    -- (1) Existing receipt first (including rejections), typed key pair only.
    SELECT cr.outcome, cr.code, cr.result_canonical
      INTO v_r_outcome, v_r_code, v_r_canonical
      FROM command_receipts cr
     WHERE cr.session_id = p_session_id
       AND cr.command_id = p_command_id
       AND cr.receipt_key_kind = 'canonical_request_hash'
       AND cr.receipt_key_value = v_computed;
    IF FOUND THEN
        RETURN QUERY SELECT 'replay', v_r_outcome, v_r_code, v_r_canonical::jsonb;
        RETURN;
    END IF;

    -- (2) command_id occupation: first attributable request binds, any outcome.
    SELECT * INTO v_bind FROM command_bindings cb
     WHERE cb.session_id = p_session_id AND cb.command_id = p_command_id;
    IF FOUND THEN
        IF v_bind.first_key_kind = 'canonical_request_hash'
           AND v_bind.first_key_value = v_computed THEN
            RETURN QUERY SELECT 'binding_replay', v_bind.first_outcome, NULL::text,
                jsonb_build_object('command_kind', p_command_kind,
                                   'command_id', p_command_id,
                                   'outcome', v_bind.first_outcome,
                                   'code', NULL,
                                   'detail', 'binding present without receipt row; defensive replay of first_outcome');
            RETURN;
        END IF;
        v_receipt := jsonb_build_object(
            'command_kind', p_command_kind,
            'command_id', p_command_id,
            'outcome', 'rejected_mismatch',
            'code', 'IDEMPOTENCY_CONFLICT',
            'detail', 'command_id already bound to a different canonical request hash; first binding kept');
        INSERT INTO command_receipts(
            session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
            outcome, code, result_canonical, result_hash)
        VALUES (p_session_id, p_command_id, p_command_kind, 'canonical_request_hash',
                v_computed, 'rejected_mismatch', 'IDEMPOTENCY_CONFLICT',
                v_receipt::text, v_sha256_hex(v_receipt::text));
        RETURN QUERY SELECT 'conflict', 'rejected_mismatch'::text,
                           'IDEMPOTENCY_CONFLICT'::text, v_receipt;
        RETURN;
    END IF;

    -- (3) Declared hash check (only while the binding is free). Receipt keys
    --     and records always use the computed hash; the declared hash is
    --     audit payload only. The rejection occupies the binding, so fixing
    --     the declared hash on the same command_id still replays this
    --     rejection — a new command_id is required to execute.
    IF p_declared_hash IS DISTINCT FROM v_computed THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, p_command_kind,
            v_computed, 'rejected_mismatch', 'REQUEST_HASH_MISMATCH',
            'declared command_request_hash does not match the computed canonical hash; binding occupied, command not executed');
        RETURN QUERY SELECT 'mismatch', 'rejected_mismatch'::text,
                           'REQUEST_HASH_MISMATCH'::text, v_receipt;
        RETURN;
    END IF;

    -- (4) Executable signal: guards and the actual-outcome binding/receipt
    --     write happen in the business function, same transaction.
    RETURN QUERY SELECT 'execute', NULL::text, NULL::text, NULL::jsonb;
END;
$$;

-- ---------------------------------------------------------------------------
-- Generic command gate (digest 2.1/2.2 wrapper for every command kind).
-- p_expected_extra is RESERVED for later command kinds' expected values
-- (fence, sealed_batch_no, ...) and is deliberately not part of any key or
-- guard in this stage. Transaction boundary owned by the caller.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_command_gate(
    p_session_id uuid, p_command_id text, p_command_kind text,
    p_payload_canonical text, p_declared_hash text,
    p_expected_extra jsonb DEFAULT NULL
) RETURNS TABLE(outcome text, code text, receipt_json jsonb, executable boolean)
LANGUAGE plpgsql AS $$
DECLARE
    r record;
BEGIN
    SELECT * INTO r FROM v8_command_adjudicate(
        p_session_id, p_command_id, p_command_kind,
        p_payload_canonical, p_declared_hash);
    IF r.adj_kind = 'execute' THEN
        RETURN QUERY SELECT 'execute'::text, NULL::text, NULL::jsonb, true;
    END IF;
    RETURN QUERY SELECT r.adj_outcome, r.adj_code, r.adj_receipt, false;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_append_events: the ONLY public semantic append implementation path
-- (digest 2.9, seven steps in the frozen order; MUST NOT merge/skip/swap).
--
-- Entries arrive as a JSON array; batch_item_ordinal is the 0-based array
-- position (raw occurrence identity (command_id, batch_item_ordinal), digest
-- 3.7 / spec occurrence-identity clause (i)). Each entry carries the CANONICAL
-- payload text produced by the shared Python canonical profile (escape ->
-- JCS); SQL re-hashes it with v_sha256_hex, mirroring the frozen
-- "SQL recomputes, caller declares" command convention.
--
-- Entry envelope fields:
--   event_type, schema_version, canonicalizer_version   (required, string)
--   payload_canonical                                   (required, string)
--   turn_id / step_id / effect_id                       (attribution triple)
--   semantic_input_ordinal                              (semantic entries only)
--   attempt_no / stream_id / chunk_index                (assistant/chunk only)
--
-- Caller-identity legs (G9a, digest 2.8 items (3)/(6)): p_caller_subject /
-- p_caller_driver / p_caller_epoch / p_caller_grant_id. They default to NULL
-- so the legacy call sites stay byte-identical. G12 REMOVED the A57 opt-in
-- downgrade: the full attribution conjunction (items (3)/(6)) is enforced
-- for EVERY chunk append — an unbound effect with no caller legs now fails
-- CHUNK_ATTRIBUTION_INVALID (zero rows persisted).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_append_events(
    p_session_id uuid, p_command_id text, p_driver text, p_driver_epoch bigint,
    p_expected_seq bigint, p_declared_hash text, p_payload_canonical text,
    p_entries jsonb,
    p_caller_subject text DEFAULT NULL,
    p_caller_driver text DEFAULT NULL,
    p_caller_epoch bigint DEFAULT NULL,
    p_caller_grant_id text DEFAULT NULL
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_n int;
    v_i int;
    v_e jsonb;
    v_it record;
    v_prev record;
    v_ex record;
    v_key text;
    v_ord numeric;
    v_turn uuid;
    v_effect uuid;
    v_maxatt bigint;
    v_er record;
    v_terminal boolean;
    v_quiescing boolean;
    v_epoch_note jsonb := NULL;
    v_event_type text;
    v_class text;
    v_sv text;
    v_cv text;
    v_payload text;
    v_payload_hash text;
    v_sio bigint;
    v_new_count bigint;
    v_next bigint;
    v_first_seq bigint;
    v_prev_pos int;
    v_prev_payload text;
    v_ex_seq bigint;
    v_ex_payload text;
    v_esc_code text;
    v_esc_detail text;
    v_unresolved boolean;
    -- G9a chunk attribution (items (2)/(3)/(6)).
    v_att effect_attempts%ROWTYPE;
    v_eff_subject text;
    v_caller text;
    v_caller_driver text;
    v_caller_epoch bigint;
    v_stream_bound boolean;
    v_ea_grant text;
    v_si_grant text;
    -- G9b late-chunk equivalence completion (barrier (d)).
    v_lc record;
    -- G10 session/heartbeat authorization precheck.
    v_hb_caller text;
    -- G10 stream registry ownership lookup.
    v_reg_owner text;
    v_reg record;
BEGIN
    -- G10: session/heartbeat event_append authorization gate — an
    -- authorization PRECHECK rejection (authorization precedes every
    -- receipt/binding processing): no command_receipts/command_bindings row
    -- is written or read, no command binding is occupied; the denial lands
    -- in the independent authz_denial_audits table keyed by the calling
    -- security context + target command identity (repeated denials of the
    -- same context merge into one row). Enforced when the caller identity
    -- context is supplied (the grant-model path). No valid grant (including
    -- a revoked one) or a cross-tenant grant context -> GRANT_DENIED,
    -- without leaking target existence beyond the denial audit.
    IF (p_caller_subject IS NOT NULL OR p_caller_driver IS NOT NULL
        OR p_caller_epoch IS NOT NULL OR p_caller_grant_id IS NOT NULL)
       AND p_entries IS NOT NULL AND jsonb_typeof(p_entries) = 'array'
       AND EXISTS (SELECT 1
                     FROM jsonb_array_elements(p_entries) elem(j)
                    WHERE j->>'event_type' = 'session/heartbeat')
       AND EXISTS (SELECT 1 FROM sessions s WHERE s.session_id = p_session_id) THEN
        -- Master lock order position 1 (session row) BEFORE the grant/slice
        -- locks taken by the judge (the adjudicator below re-locks it
        -- harmlessly inside the same transaction).
        PERFORM 1 FROM sessions a WHERE a.session_id = p_session_id FOR UPDATE;
        v_hb_caller := coalesce(p_caller_subject,
                                v_grant_subject(p_caller_grant_id));
        IF v_grant_find_valid(p_session_id, 'event_append', v_hb_caller,
                              p_caller_driver, p_caller_epoch,
                              p_caller_grant_id, NULL) IS NULL THEN
            PERFORM v_authz_denial(
                coalesce(v_hb_caller, '') || '|' || coalesce(p_caller_driver, '')
                || '|' || coalesce(p_caller_epoch::text, '')
                || '|' || coalesce(p_caller_grant_id, ''),
                'append_events/session_heartbeat:' || p_session_id::text,
                'no valid event_append grant for the calling context '
                '(revoked, unissued or cross-tenant)');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'GRANT_DENIED'::text,
                jsonb_build_object(
                    'command_kind', 'append_events',
                    'command_id', p_command_id,
                    'outcome', 'rejected_mismatch',
                    'code', 'GRANT_DENIED',
                    'authz_precheck', true,
                    'detail', 'authorization precheck (outside the receipt '
                              'namespace): no valid event_append grant');
            RETURN;
        END IF;
    END IF;

    -- Step (1) of the seven steps (session row lock, master lock order
    -- position 1) is taken inside the adjudicator, together with the outer
    -- command receipt/binding judgment order (1)-(4).
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'append_events',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id FOR UPDATE;

    -- Envelope driver/epoch guard (L4-U03; NOT exempted by the all-duplicate
    -- batch special case). IS DISTINCT FROM so a NULL envelope leg (omitted
    -- driver/driver_epoch) is a mismatch, never a silent pass — every write
    -- command MUST carry both fields (spec 3.1.2). G18 (D5, heartbeat
    -- lifecycle matrix note (iv)): under driver_mode=quiescing a batch of
    -- ONLY session/heartbeat entries downgrades the mismatch to a recorded
    -- difference (the old-epoch heartbeat is accepted, zero control state,
    -- the submitted epoch lands in the receipt); active keeps the standard
    -- contract, terminal rejects below.
    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        IF v_sess.driver_mode = 'quiescing'
           AND p_entries IS NOT NULL
           AND jsonb_typeof(p_entries) = 'array'
           AND jsonb_array_length(p_entries) > 0
           AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p_entries) e
                            WHERE e->>'event_type' <> 'session/heartbeat')
        THEN
            v_epoch_note := jsonb_build_object(
                'submitted_driver', p_driver,
                'submitted_driver_epoch', p_driver_epoch,
                'epoch_mismatch_recorded', true);
        ELSE
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                v_computed, 'rejected_stale', 'DRIVER_EPOCH_STALE',
                'envelope driver/driver_epoch does not match the session control row');
            RETURN QUERY SELECT 'rejected_stale'::text, 'DRIVER_EPOCH_STALE'::text, v_receipt;
            RETURN;
        END IF;
    END IF;

    v_terminal := v_sess.state IN ('completed', 'failed', 'cancelled');
    v_quiescing := v_sess.driver_mode = 'quiescing';

    -- Step (2): full-batch structural / permission validation. Any single
    -- entry failing rejects the WHOLE batch atomically — zero events, no
    -- next_seq advance, only the binding + rejection receipt persist. This
    -- step does NOT include the expected-seq check (see the L4-U-R01 special
    -- case below). This stage's terminal definition: state IN
    -- ('completed','failed','cancelled'); the matrix-(c) late-chunk exception
    -- is kept (only assistant/chunk entries may pass on a terminal session,
    -- still subject to the six-item validation).
    IF p_entries IS NULL OR jsonb_typeof(p_entries) <> 'array' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
            v_computed, 'rejected_mismatch', 'ENVELOPE_INVALID',
            'entries must be a JSON array');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'ENVELOPE_INVALID'::text, v_receipt;
        RETURN;
    END IF;
    v_n := jsonb_array_length(p_entries);
    IF v_n = 0 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
            v_computed, 'rejected_mismatch', 'EMPTY_BATCH',
            'append_events requires at least one entry');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'EMPTY_BATCH'::text, v_receipt;
        RETURN;
    END IF;

    -- Explicitly pg_temp-qualified (DROP/CREATE/INSERT/SELECT/UPDATE): an
    -- unqualified reference resolves through search_path, so the DROP would
    -- silently destroy a same-named PERMANENT table whenever no temp table
    -- exists in this backend yet (ON COMMIT DROP empties the temp schema
    -- after every transaction, i.e. before every call).
    DROP TABLE IF EXISTS pg_temp.v8_batch_items;
    CREATE TEMP TABLE pg_temp.v8_batch_items (
        pos int PRIMARY KEY,
        event_type text NOT NULL,
        event_class text NOT NULL,
        schema_version text NOT NULL,
        canonicalizer_version text NOT NULL,
        turn_id uuid,
        step_id uuid,
        effect_id uuid,
        semantic_input_ordinal bigint,
        attempt_no bigint,
        stream_id text,
        chunk_index bigint,
        payload_canonical text NOT NULL,
        payload_hash text NOT NULL,
        is_chunk boolean NOT NULL,
        action text,      -- 'insert' | 'existing' | 'merged'
        rep_pos int,      -- representative position for in-batch merges (F2)
        event_key text,
        seq bigint
    ) ON COMMIT DROP;

    FOR v_i IN 0 .. v_n - 1 LOOP
        v_e := p_entries -> v_i;

        -- Required scalar fields (W03 core).
        IF NOT (v_e ? 'event_type') OR jsonb_typeof(v_e->'event_type') IS NULL
           OR jsonb_typeof(v_e->'event_type') <> 'string'
           OR length(v_e->>'event_type') = 0 THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                v_computed, 'rejected_mismatch', 'ENVELOPE_FIELD_MISSING',
                format('entry %s: event_type missing or not a string', v_i));
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'ENVELOPE_FIELD_MISSING'::text, v_receipt;
            RETURN;
        END IF;
        v_event_type := v_e->>'event_type';
        IF NOT (v_e ? 'schema_version') OR jsonb_typeof(v_e->'schema_version') <> 'string'
           OR NOT (v_e ? 'canonicalizer_version')
           OR jsonb_typeof(v_e->'canonicalizer_version') <> 'string' THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                v_computed, 'rejected_mismatch', 'ENVELOPE_FIELD_MISSING',
                format('entry %s: schema_version/canonicalizer_version required (W03)', v_i));
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'ENVELOPE_FIELD_MISSING'::text, v_receipt;
            RETURN;
        END IF;
        IF NOT (v_e ? 'payload_canonical') OR jsonb_typeof(v_e->'payload_canonical') <> 'string' THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                v_computed, 'rejected_mismatch', 'ENVELOPE_FIELD_MISSING',
                format('entry %s: payload_canonical required', v_i));
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'ENVELOPE_FIELD_MISSING'::text, v_receipt;
            RETURN;
        END IF;
        v_sv := v_e->>'schema_version';
        v_cv := v_e->>'canonicalizer_version';
        v_payload := v_e->>'payload_canonical';
        v_payload_hash := v_sha256_hex(v_payload);

        -- Type permission matrix (digest 2.7): closed whitelist
        -- public_append_types@v1 = {user/message, turn/start, agent/inject,
        -- assistant/chunk, session/heartbeat}; everything else — including
        -- semantic-result and audit types and the removed bare heartbeat /
        -- attempt/heartbeat — is EVENT_TYPE_RESTRICTED.
        v_class := CASE v_event_type
            WHEN 'user/message' THEN 'semantic'
            WHEN 'turn/start' THEN 'semantic'
            WHEN 'agent/inject' THEN 'semantic'
            WHEN 'assistant/chunk' THEN 'observational'
            WHEN 'session/heartbeat' THEN 'observational'
        END;
        IF v_class IS NULL THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                v_computed, 'rejected_mismatch', 'EVENT_TYPE_RESTRICTED',
                format('entry %s: event_type %L not in public_append_types@v1', v_i, v_event_type));
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'EVENT_TYPE_RESTRICTED'::text, v_receipt;
            RETURN;
        END IF;

        IF v_class = 'semantic' THEN
            -- Session lifecycle gates for semantic input (W01/Q03: quiescing
            -- rejects semantic input; terminal rejects it outright).
            IF v_terminal THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'SESSION_TERMINAL',
                    format('entry %s: semantic input on a terminal session', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_TERMINAL'::text, v_receipt;
                RETURN;
            END IF;
            IF v_quiescing THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'DRIVER_QUIESCING',
                    format('entry %s: semantic input while driver_mode=quiescing', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'DRIVER_QUIESCING'::text, v_receipt;
                RETURN;
            END IF;

            -- Attribution matrix X03 (3 classes x 3 components): turn_id
            -- MUST be present and non-NULL, step_id/effect_id fixed NULL.
            -- NULL is a value, not a missing field (W03); violations are
            -- envelope structural rejections here, never IDEMPOTENCY_CONFLICT.
            IF NOT (v_e ? 'turn_id') OR (v_e->>'turn_id') IS NULL
               OR (v_e->>'turn_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
               OR ((v_e ? 'step_id') AND (v_e->>'step_id') IS NOT NULL)
               OR ((v_e ? 'effect_id') AND (v_e->>'effect_id') IS NOT NULL) THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'ATTRIBUTION_MATRIX_VIOLATION',
                    format('entry %s: public semantic input requires turn_id non-NULL and step_id/effect_id NULL (X03)', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'ATTRIBUTION_MATRIX_VIOLATION'::text, v_receipt;
                RETURN;
            END IF;
            v_turn := (v_e->>'turn_id')::uuid;
            v_effect := NULL;

            -- semantic_input_ordinal: carried by every semantic whitelist
            -- entry, frozen value domain [1, 2^63-1] (L4-U01); either legal
            -- wire form (JSON number, or the tagged $int object for values
            -- beyond 2^53-1). Missing/non-decodable and out-of-domain values
            -- are envelope rejections.
            IF NOT (v_e ? 'semantic_input_ordinal')
               OR v8_entry_int(v_e->'semantic_input_ordinal') IS NULL THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'SEMANTIC_ORDINAL_MISSING',
                    format('entry %s: semantic entries must carry an integer semantic_input_ordinal', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'SEMANTIC_ORDINAL_MISSING'::text, v_receipt;
                RETURN;
            END IF;
            v_ord := v8_entry_int(v_e->'semantic_input_ordinal');
            IF v_ord < 1 OR v_ord > 9223372036854775807 OR v_ord <> floor(v_ord) THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'SEMANTIC_ORDINAL_OUT_OF_RANGE',
                    format('entry %s: semantic_input_ordinal outside [1, 2^63-1] or not an integer', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'SEMANTIC_ORDINAL_OUT_OF_RANGE'::text, v_receipt;
                RETURN;
            END IF;
            v_sio := v_ord::bigint;

            INSERT INTO pg_temp.v8_batch_items(pos, event_type, event_class, schema_version,
                canonicalizer_version, turn_id, step_id, effect_id,
                semantic_input_ordinal, payload_canonical, payload_hash, is_chunk)
            VALUES (v_i, v_event_type, 'semantic', v_sv, v_cv, v_turn, NULL, NULL,
                    v_sio, v_payload, v_payload_hash, false);

        ELSIF v_event_type = 'assistant/chunk' THEN
            -- Observational entries never carry the public ordinal column.
            IF (v_e ? 'semantic_input_ordinal') AND (v_e->>'semantic_input_ordinal') IS NOT NULL THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'SEMANTIC_ORDINAL_FORBIDDEN',
                    format('entry %s: observational entries must not carry semantic_input_ordinal', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'SEMANTIC_ORDINAL_FORBIDDEN'::text, v_receipt;
                RETURN;
            END IF;
            IF NOT (v_e ? 'effect_id') OR (v_e->>'effect_id') IS NULL
               OR (v_e->>'effect_id') !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$' THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                    format('entry %s: assistant/chunk requires a well-formed effect_id', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                RETURN;
            END IF;
            v_effect := (v_e->>'effect_id')::uuid;
            IF v8_entry_int(v_e->'attempt_no') IS NULL
               OR v8_entry_int(v_e->'attempt_no') < 1
               OR NOT (v_e ? 'stream_id') OR jsonb_typeof(v_e->'stream_id') <> 'string'
               OR length(v_e->>'stream_id') = 0 THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                    format('entry %s: assistant/chunk requires a positive integer attempt_no and a non-empty stream_id', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                RETURN;
            END IF;
            -- chunk_index value domain, item (5): 0 <= v <= 2^63-1, integer
            -- (either legal wire form).
            IF v8_entry_int(v_e->'chunk_index') IS NULL THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                    format('entry %s: chunk_index must be an integer', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                RETURN;
            END IF;
            v_ord := v8_entry_int(v_e->'chunk_index');
            IF v_ord < 0 OR v_ord > 9223372036854775807 OR v_ord <> floor(v_ord) THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                    format('entry %s: chunk_index outside [0, 2^63-1]', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                RETURN;
            END IF;

            -- Six-item attribution validation (digest 2.8), reachable items
            -- of this stage:
            SELECT er.session_id AS er_session, er.step_id AS er_step,
                   er.status AS er_status, er.dispatched_at AS er_dispatched_at,
                   er.grant_id AS er_grant_id, st.turn_id AS er_turn
              INTO v_er
              FROM effect_requests er
              JOIN steps st ON st.step_id = er.step_id
             WHERE er.effect_id = v_effect;
            -- (1) effect_id belongs to a persisted effect of this session.
            IF NOT FOUND OR v_er.er_session IS DISTINCT FROM p_session_id THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                    format('entry %s: effect_id not persisted for this session (item 1)', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                RETURN;
            END IF;
            -- (2) attempt_no is the current (max) persisted attempt of the
            --     effect OR an already-accepted settled attempt (a row that
            --     froze an accepted settlement, i.e. result_hash is non-NULL).
            SELECT max(a.attempt_no) INTO v_maxatt
              FROM effect_attempts a WHERE a.effect_id = v_effect;
            SELECT a.* INTO v_att
              FROM effect_attempts a
             WHERE a.effect_id = v_effect
               AND a.attempt_no = v8_entry_int(v_e->'attempt_no')::bigint;
            IF v_maxatt IS NULL OR NOT FOUND
               OR (v8_entry_int(v_e->'attempt_no') <> v_maxatt
                   AND v_att.result_hash IS NULL) THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                    format('entry %s: attempt_no is neither the current persisted attempt nor an accepted settled attempt (item 2)', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                RETURN;
            END IF;
            -- (4) the effect has entered dispatch_started (persisted dispatch
            --     marker: dispatched_at or a reached post-dispatch status).
            IF v_er.er_dispatched_at IS NULL AND v_er.er_status NOT IN (
                   'dispatch_started', 'succeeded', 'failed_retryable',
                   'failed_terminal', 'cancelled_after_dispatch', 'unknown_outcome') THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                    format('entry %s: effect has not entered dispatch_started (item 4)', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                RETURN;
            END IF;
            -- (5) chunk_index domain checked above; arrival order and gaps
            --     never affect legality (frozen; 2,0,1 accepted).
            --
            -- (3)/(6): the grant-chain attribution. G12 REMOVED the A57
            -- opt-in legacy downgrade: items (3) and (6) are ALWAYS
            -- enforced now — an UNBOUND effect (grant_id NULL) fails item
            -- (3) (no bound provider/adapter subject) and a caller without
            -- valid event_append + stream_ingest grants fails item (6);
            -- the all-legs-default legacy path no longer passes.
            v_eff_subject := v_grant_subject(v_er.er_grant_id);
            v_caller := COALESCE(p_caller_subject,
                                 v_grant_subject(p_caller_grant_id),
                                 v_eff_subject);
            v_caller_driver := COALESCE(p_caller_driver, v_sess.driver);
            v_caller_epoch := COALESCE(p_caller_epoch, v_sess.driver_epoch);
            v_stream_bound := true;
            IF v_stream_bound THEN
                -- (3) stream_id attribution (G10: the stream registry
                --     replaces the A60 cross-session chunk-scan
                --     approximation). The effect MUST resolve to a bound
                --     provider/adapter subject, and the stream_id MUST NOT
                --     be registered to a DIFFERENT provider (first legal
                --     use binds the stream; foreign reuse rejects).
                IF v_eff_subject IS NULL
                   OR EXISTS (SELECT 1 FROM stream_registry sr
                               WHERE sr.stream_id = (v_e->>'stream_id')
                                 AND sr.owner_subject IS DISTINCT FROM v_eff_subject) THEN
                    v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                        v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                        format('entry %s: stream_id is not attributable to the effect''s bound provider/adapter (item 3)', v_i));
                    RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                    RETURN;
                END IF;
                -- (6)(i) a valid event_append grant held by the caller
                --     (base capability; a chunk append never waives it).
                --     G10: the grant lookup goes through the full judge
                --     (v_grant_find_valid — subject resolved through the
                --     grant/driver chain, all conjuncts evaluated under the
                --     fixed lock order); a bare subject_id match never
                --     decides validity anymore.
                v_ea_grant := v_grant_find_valid(
                    p_session_id, 'event_append', v_caller,
                    p_caller_driver, p_caller_epoch, p_caller_grant_id,
                    jsonb_build_object('target', v_e->>'stream_id'));
                IF v_ea_grant IS NULL THEN
                    v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                        v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                        format('entry %s: caller holds no valid event_append grant (item 6i)', v_i));
                    RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                    RETURN;
                END IF;
                -- (6)(ii) a valid stream_ingest grant held by the same caller
                --     (dual-grant conjunction; stream_ingest alone never
                --     substitutes for event_append).
                v_si_grant := v_grant_find_valid(
                    p_session_id, 'stream_ingest', v_caller,
                    p_caller_driver, p_caller_epoch, p_caller_grant_id,
                    jsonb_build_object('target', v_e->>'stream_id'));
                IF v_si_grant IS NULL THEN
                    v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                        v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                        format('entry %s: caller holds no valid stream_ingest grant (item 6ii)', v_i));
                    RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                    RETURN;
                END IF;
                -- (6)(iii) identity full match: caller subject == the effect's
                --     bound provider/adapter, and the caller driver/epoch ==
                --     the attempt row's frozen execution snapshot.
                IF v_caller IS DISTINCT FROM v_eff_subject
                   OR v_caller_driver IS DISTINCT FROM v_att.driver
                   OR v_caller_epoch IS DISTINCT FROM v_att.driver_epoch THEN
                    v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                        v_computed, 'rejected_mismatch', 'CHUNK_ATTRIBUTION_INVALID',
                        format('entry %s: caller identity does not match the effect''s bound provider/driver/epoch (item 6iii)', v_i));
                    RETURN QUERY SELECT 'rejected_mismatch'::text, 'CHUNK_ATTRIBUTION_INVALID'::text, v_receipt;
                    RETURN;
                END IF;
            END IF;

            INSERT INTO pg_temp.v8_batch_items(pos, event_type, event_class, schema_version,
                canonicalizer_version, turn_id, step_id, effect_id,
                semantic_input_ordinal, attempt_no, stream_id, chunk_index,
                payload_canonical, payload_hash, is_chunk)
            VALUES (v_i, v_event_type, 'observational', v_sv, v_cv,
                    v_er.er_turn, v_er.er_step, v_effect, NULL,
                    v8_entry_int(v_e->'attempt_no')::bigint, v_e->>'stream_id',
                    v_ord::bigint, v_payload, v_payload_hash, true);

        ELSE
            -- session/heartbeat: session-level observational, no turn
            -- attribution (P01 split), never occupies an ordinal column.
            IF (v_e ? 'semantic_input_ordinal') AND (v_e->>'semantic_input_ordinal') IS NOT NULL THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'SEMANTIC_ORDINAL_FORBIDDEN',
                    format('entry %s: observational entries must not carry semantic_input_ordinal', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'SEMANTIC_ORDINAL_FORBIDDEN'::text, v_receipt;
                RETURN;
            END IF;
            IF ((v_e ? 'turn_id') AND (v_e->>'turn_id') IS NOT NULL)
               OR ((v_e ? 'step_id') AND (v_e->>'step_id') IS NOT NULL)
               OR ((v_e ? 'effect_id') AND (v_e->>'effect_id') IS NOT NULL) THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'ATTRIBUTION_MATRIX_VIOLATION',
                    format('entry %s: session/heartbeat carries no turn/step/effect attribution', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'ATTRIBUTION_MATRIX_VIOLATION'::text, v_receipt;
                RETURN;
            END IF;
            IF v_terminal THEN
                v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                    v_computed, 'rejected_mismatch', 'SESSION_TERMINAL',
                    format('entry %s: session/heartbeat on a terminal session', v_i));
                RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_TERMINAL'::text, v_receipt;
                RETURN;
            END IF;
            -- Quiescing accepts session-level observational writes (W01);
            -- the old-epoch heartbeat downgrade (L4-U03) is LATER.

            INSERT INTO pg_temp.v8_batch_items(pos, event_type, event_class, schema_version,
                canonicalizer_version, turn_id, step_id, effect_id,
                semantic_input_ordinal, payload_canonical, payload_hash, is_chunk)
            VALUES (v_i, v_event_type, 'observational', v_sv, v_cv,
                    NULL, NULL, NULL, NULL, v_payload, v_payload_hash, false);
        END IF;
    END LOOP;

    -- Steps (3)-(5): dedup against existing rows AND the batch itself, by
    -- (session_id, semantic_input_ordinal) for semantic entries and by the
    -- frozen per-type keys for observational entries. The all-duplicate /
    -- contains-new classification counts the post-merge LOGICAL entry set
    -- (F2: merged entries count once).
    FOR v_it IN SELECT * FROM pg_temp.v8_batch_items ORDER BY pos LOOP
        IF v_it.event_class = 'semantic' THEN
            SELECT * INTO v_prev FROM pg_temp.v8_batch_items b
             WHERE b.event_class = 'semantic'
               AND b.semantic_input_ordinal = v_it.semantic_input_ordinal
               AND b.pos < v_it.pos
             ORDER BY b.pos LIMIT 1;
            IF FOUND THEN
                -- (4) same-ordinal five-part compare domain —
                --     {event_type, schema_version/canonicalizer_version,
                --     attribution triple, canonical payload} — fully equal:
                --     in-batch merge onto the representative (F2) ...
                IF v_prev.event_type = v_it.event_type
                   AND v_prev.schema_version = v_it.schema_version
                   AND v_prev.canonicalizer_version = v_it.canonicalizer_version
                   AND v_prev.turn_id IS NOT DISTINCT FROM v_it.turn_id
                   AND v_prev.step_id IS NOT DISTINCT FROM v_it.step_id
                   AND v_prev.effect_id IS NOT DISTINCT FROM v_it.effect_id
                   AND v_prev.payload_canonical = v_it.payload_canonical THEN
                    UPDATE pg_temp.v8_batch_items SET action = 'merged', rep_pos = v_prev.pos
                     WHERE pos = v_it.pos;
                ELSE
                    -- (5) ... any single part differing (same payload but a
                    --      different event_type / attribution / version
                    --      included) -> whole-batch IDEMPOTENCY_CONFLICT,
                    --      zero events, decided BEFORE any insert.
                    v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                        v_computed, 'rejected_mismatch', 'IDEMPOTENCY_CONFLICT',
                        format('in-batch semantic_input_ordinal %s compares unequal on the five-part domain',
                               v_it.semantic_input_ordinal));
                    RETURN QUERY SELECT 'rejected_mismatch'::text, 'IDEMPOTENCY_CONFLICT'::text, v_receipt;
                    RETURN;
                END IF;
            ELSE
                SELECT se.event_key, se.seq, se.event_type, se.schema_version,
                       se.canonicalizer_version, se.turn_id, se.step_id,
                       se.effect_id, se.payload
                  INTO v_ex
                  FROM session_events se
                 WHERE se.session_id = p_session_id
                   AND se.semantic_input_ordinal = v_it.semantic_input_ordinal;
                IF FOUND THEN
                    IF v_ex.event_type = v_it.event_type
                       AND v_ex.schema_version = v_it.schema_version
                       AND v_ex.canonicalizer_version = v_it.canonicalizer_version
                       AND v_ex.turn_id IS NOT DISTINCT FROM v_it.turn_id
                       AND v_ex.step_id IS NOT DISTINCT FROM v_it.step_id
                       AND v_ex.effect_id IS NOT DISTINCT FROM v_it.effect_id
                       AND v_ex.payload = v_it.payload_canonical THEN
                        UPDATE pg_temp.v8_batch_items
                           SET action = 'existing', event_key = v_ex.event_key, seq = v_ex.seq
                         WHERE pos = v_it.pos;
                    ELSE
                        v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                            v_computed, 'rejected_mismatch', 'IDEMPOTENCY_CONFLICT',
                            format('semantic_input_ordinal %s differs from the persisted event on the five-part domain',
                                   v_it.semantic_input_ordinal));
                        RETURN QUERY SELECT 'rejected_mismatch'::text, 'IDEMPOTENCY_CONFLICT'::text, v_receipt;
                        RETURN;
                    END IF;
                ELSE
                    UPDATE pg_temp.v8_batch_items SET action = 'insert' WHERE pos = v_it.pos;
                END IF;
            END IF;

        ELSIF v_it.is_chunk THEN
            -- Streaming key (event_key@v1, four-tuple derivation). Same
            -- four-tuple + same content -> idempotent dedup; same four-tuple
            -- with different content -> CANONICALIZER_CONFLICT (never a
            -- second row). In-batch duplicates of one four-tuple merge onto
            -- the first occurrence.
            v_key := v_event_key_streaming(v_it.effect_id, v_it.attempt_no,
                                           v_it.stream_id, v_it.chunk_index);
            SELECT b.pos, b.payload_canonical INTO v_prev_pos, v_prev_payload
              FROM pg_temp.v8_batch_items b
             WHERE b.is_chunk
               AND b.effect_id IS NOT DISTINCT FROM v_it.effect_id
               AND b.attempt_no IS NOT DISTINCT FROM v_it.attempt_no
               AND b.stream_id IS NOT DISTINCT FROM v_it.stream_id
               AND b.chunk_index IS NOT DISTINCT FROM v_it.chunk_index
               AND b.pos < v_it.pos
             ORDER BY b.pos LIMIT 1;
            IF FOUND THEN
                IF v_prev_payload = v_it.payload_canonical THEN
                    UPDATE pg_temp.v8_batch_items
                       SET action = 'merged', rep_pos = v_prev_pos, event_key = v_key
                     WHERE pos = v_it.pos;
                ELSE
                    v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                        v_computed, 'rejected_mismatch', 'CANONICALIZER_CONFLICT',
                        format('entry %s: same streaming four-tuple with different content', v_it.pos));
                    RETURN QUERY SELECT 'rejected_mismatch'::text, 'CANONICALIZER_CONFLICT'::text, v_receipt;
                    RETURN;
                END IF;
            ELSE
                SELECT se.seq, se.payload INTO v_ex_seq, v_ex_payload
                  FROM session_events se
                 WHERE se.session_id = p_session_id AND se.event_key = v_key;
                IF FOUND THEN
                    IF v_ex_payload = v_it.payload_canonical THEN
                        UPDATE pg_temp.v8_batch_items
                           SET action = 'existing', event_key = v_key, seq = v_ex_seq
                         WHERE pos = v_it.pos;
                    ELSE
                        v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                            v_computed, 'rejected_mismatch', 'CANONICALIZER_CONFLICT',
                            format('entry %s: same streaming four-tuple with different content', v_it.pos));
                        RETURN QUERY SELECT 'rejected_mismatch'::text, 'CANONICALIZER_CONFLICT'::text, v_receipt;
                        RETURN;
                    END IF;
                ELSE
                    UPDATE pg_temp.v8_batch_items SET action = 'insert', event_key = v_key
                     WHERE pos = v_it.pos;
                END IF;
            END IF;

        ELSE
            -- session/heartbeat: database-internal derived non-stream key
            -- bound to (session_id, event_type, (command_id,
            -- batch_item_ordinal), canonical payload hash) — digest 3.7.
            v_key := v_nonstream_event_key(p_session_id, v_it.event_type,
                                           p_command_id, v_it.pos, v_it.payload_hash);
            SELECT se.seq, se.payload INTO v_ex_seq, v_ex_payload
              FROM session_events se
             WHERE se.session_id = p_session_id AND se.event_key = v_key;
            IF FOUND THEN
                -- The key binds the payload hash, so equal keys with unequal
                -- payloads can only be a digest collision; fail closed.
                IF v_ex_payload = v_it.payload_canonical THEN
                    UPDATE pg_temp.v8_batch_items
                       SET action = 'existing', event_key = v_key, seq = v_ex_seq
                     WHERE pos = v_it.pos;
                ELSE
                    v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                        v_computed, 'rejected_mismatch', 'CANONICALIZER_CONFLICT',
                        format('entry %s: non-stream event key collision with different payload', v_it.pos));
                    RETURN QUERY SELECT 'rejected_mismatch'::text, 'CANONICALIZER_CONFLICT'::text, v_receipt;
                    RETURN;
                END IF;
            ELSE
                UPDATE pg_temp.v8_batch_items SET action = 'insert', event_key = v_key
                 WHERE pos = v_it.pos;
            END IF;
        END IF;
    END LOOP;

    SELECT count(*) INTO v_new_count FROM pg_temp.v8_batch_items WHERE action = 'insert';

    -- expected-seq special case (L4-U-R01, frozen): the check sits AFTER the
    -- full-batch validation and the event-level dedup, and only applies to
    -- batches containing new entries. An all-duplicate batch returns the
    -- existing identity/seq mapping without checking expected seq and
    -- without advancing next_seq (driver/epoch checks above are NOT
    -- exempted).
    IF v_new_count > 0 AND p_expected_seq IS DISTINCT FROM v_sess.next_seq THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
            v_computed, 'rejected_stale', 'EXPECTED_SEQ_MISMATCH',
            format('expected seq %s does not match current next_seq %s',
                   coalesce(p_expected_seq::text, 'NULL'), v_sess.next_seq));
        RETURN QUERY SELECT 'rejected_stale'::text, 'EXPECTED_SEQ_MISMATCH'::text, v_receipt;
        RETURN;
    END IF;

    -- Step (6): only entries whose ordinal (or per-type key) does not exist
    -- — in-batch merged entries derive from their representative's raw
    -- occurrence identity (smallest batch_item_ordinal, F2) — get new
    -- events, one contiguous seq interval next_seq..next_seq+n-1 (the
    -- no-hole invariant constrains exactly this interval).
    v_next := v_sess.next_seq;
    v_first_seq := v_next;
    BEGIN
        FOR v_it IN SELECT * FROM pg_temp.v8_batch_items WHERE action = 'insert' ORDER BY pos LOOP
            -- New semantic events derive their database-internal non-stream
            -- key from the request raw occurrence identity (command_id,
            -- batch_item_ordinal); chunk/heartbeat keys were derived during
            -- the dedup pass. In-batch merged entries inherit their
            -- representative's key (the representative IS this row — the
            -- smallest batch_item_ordinal of the merge group, F2).
            IF v_it.event_class = 'semantic' THEN
                v_key := v_nonstream_event_key(p_session_id, v_it.event_type,
                                               p_command_id, v_it.pos,
                                               v_it.payload_hash);
                UPDATE pg_temp.v8_batch_items SET event_key = v_key WHERE pos = v_it.pos;
            ELSE
                v_key := v_it.event_key;
            END IF;
            INSERT INTO session_events(
                seq, session_id, event_type, event_class, schema_version,
                canonicalizer_version, event_key, turn_id, step_id, effect_id,
                payload, payload_hash, semantic_input_ordinal,
                internal_semantic_ordinal, attempt_no, command_id, batch_item_ordinal,
                stream_id, chunk_index, observation_ordinal)
            VALUES (
                v_next, p_session_id, v_it.event_type, v_it.event_class,
                v_it.schema_version, v_it.canonicalizer_version, v_key,
                v_it.turn_id, v_it.step_id, v_it.effect_id,
                v_it.payload_canonical, v_it.payload_hash, v_it.semantic_input_ordinal,
                NULL, v_it.attempt_no, p_command_id, v_it.pos,
                v_it.stream_id, v_it.chunk_index, NULL);
            UPDATE pg_temp.v8_batch_items SET seq = v_next WHERE pos = v_it.pos;
            v_next := v_next + 1;
        END LOOP;
        -- Defensive unique-index escape (digest 2.2 concurrency ruling /
        -- 2.9 tail): any abnormal UNIQUE(session_id, semantic_input_ordinal)
        -- / UNIQUE(session_id, event_key) conflict is caught and escaped as
        -- the (4)/(5) classification, never as a bare constraint violation.
        -- The subtransaction rollback above removed every event row of this
        -- batch (zero-events guarantee), so the handler re-reads the
        -- persisted row for each still-new entry under the held session row
        -- lock and applies the same compare domain as the pre-insert dedup:
        -- fully equal -> idempotent existing mapping (the batch falls
        -- through to the all-duplicate receipt, next_seq not advanced); any
        -- part differing -> whole-batch conflict with the same code the
        -- pre-insert dedup would have produced; no surviving conflicting
        -- row at all -> fail closed (defensive conflict, zero events).
    EXCEPTION WHEN unique_violation THEN
        v_esc_code := NULL;
        v_esc_detail := NULL;
        v_unresolved := false;
        FOR v_it IN SELECT * FROM pg_temp.v8_batch_items
                     WHERE action = 'insert' ORDER BY pos LOOP
            EXIT WHEN v_esc_code IS NOT NULL;
            IF v_it.event_class = 'semantic' THEN
                SELECT se.event_key, se.seq, se.event_type, se.schema_version,
                       se.canonicalizer_version, se.turn_id, se.step_id,
                       se.effect_id, se.payload
                  INTO v_ex
                  FROM session_events se
                 WHERE se.session_id = p_session_id
                   AND se.semantic_input_ordinal = v_it.semantic_input_ordinal;
                IF FOUND THEN
                    IF v_ex.event_type = v_it.event_type
                       AND v_ex.schema_version = v_it.schema_version
                       AND v_ex.canonicalizer_version = v_it.canonicalizer_version
                       AND v_ex.turn_id IS NOT DISTINCT FROM v_it.turn_id
                       AND v_ex.step_id IS NOT DISTINCT FROM v_it.step_id
                       AND v_ex.effect_id IS NOT DISTINCT FROM v_it.effect_id
                       AND v_ex.payload = v_it.payload_canonical THEN
                        UPDATE pg_temp.v8_batch_items
                           SET action = 'existing', event_key = v_ex.event_key,
                               seq = v_ex.seq
                         WHERE pos = v_it.pos;
                    ELSE
                        v_esc_code := 'IDEMPOTENCY_CONFLICT';
                        v_esc_detail := format('semantic_input_ordinal %s differs from the concurrently persisted event on the five-part domain',
                                               v_it.semantic_input_ordinal);
                    END IF;
                ELSE
                    v_unresolved := true;
                END IF;
            ELSIF v_it.is_chunk THEN
                v_key := v_event_key_streaming(v_it.effect_id, v_it.attempt_no,
                                               v_it.stream_id, v_it.chunk_index);
                SELECT se.seq, se.payload INTO v_ex_seq, v_ex_payload
                  FROM session_events se
                 WHERE se.session_id = p_session_id AND se.event_key = v_key;
                IF FOUND THEN
                    IF v_ex_payload = v_it.payload_canonical THEN
                        UPDATE pg_temp.v8_batch_items
                           SET action = 'existing', event_key = v_key, seq = v_ex_seq
                         WHERE pos = v_it.pos;
                    ELSE
                        v_esc_code := 'CANONICALIZER_CONFLICT';
                        v_esc_detail := format('entry %s: same streaming four-tuple with different content',
                                               v_it.pos);
                    END IF;
                ELSE
                    v_unresolved := true;
                END IF;
            ELSE
                v_key := v_nonstream_event_key(p_session_id, v_it.event_type,
                                               p_command_id, v_it.pos,
                                               v_it.payload_hash);
                SELECT se.seq, se.payload INTO v_ex_seq, v_ex_payload
                  FROM session_events se
                 WHERE se.session_id = p_session_id AND se.event_key = v_key;
                IF FOUND THEN
                    IF v_ex_payload = v_it.payload_canonical THEN
                        UPDATE pg_temp.v8_batch_items
                           SET action = 'existing', event_key = v_key, seq = v_ex_seq
                         WHERE pos = v_it.pos;
                    ELSE
                        v_esc_code := 'CANONICALIZER_CONFLICT';
                        v_esc_detail := format('entry %s: non-stream event key collision with different payload',
                                               v_it.pos);
                    END IF;
                ELSE
                    v_unresolved := true;
                END IF;
            END IF;
        END LOOP;
        IF v_esc_code IS NOT NULL OR v_unresolved THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'append_events',
                v_computed, 'rejected_mismatch', coalesce(v_esc_code, 'IDEMPOTENCY_CONFLICT'),
                coalesce(v_esc_detail,
                         'unique-index conflict escaped defensively; no conflicting row visible on the in-lock re-read; zero events'));
            RETURN QUERY SELECT 'rejected_mismatch'::text,
                               coalesce(v_esc_code, 'IDEMPOTENCY_CONFLICT')::text,
                               v_receipt;
            RETURN;
        END IF;
        -- Every formerly-new entry re-read as an exact duplicate: the batch
        -- is all-duplicate now (receipt maps each input position to the
        -- existing identity/seq; inserted interval empty; no next_seq move).
        SELECT count(*) INTO v_new_count FROM pg_temp.v8_batch_items
         WHERE action = 'insert';
    END;

    IF v_new_count > 0 THEN
        UPDATE sessions SET next_seq = next_seq + v_new_count, updated_at = now()
         WHERE session_id = p_session_id;

        -- G10: stream registration (item 3). The FIRST legally attributed
        -- bound chunk binds its stream to the effect's provider subject
        -- (resolved through the bound grant) in this same transaction, so
        -- any later batch rejection rolls the registration back with the
        -- later batch rejection rolls the registration back with the
        -- events. A foreign registration that raced past the validation
        -- check fails closed here (the whole transaction aborts — zero
        -- events, zero registration).
        FOR v_reg IN
            SELECT DISTINCT ON (b.stream_id) b.stream_id, b.effect_id, er.grant_id
              FROM pg_temp.v8_batch_items b
              JOIN effect_requests er ON er.effect_id = b.effect_id
             WHERE b.is_chunk AND b.action = 'insert'
               AND er.grant_id IS NOT NULL
             ORDER BY b.stream_id, b.effect_id
        LOOP
            INSERT INTO stream_registry(stream_id, workspace_id,
                                        owner_subject, effect_id)
            VALUES (v_reg.stream_id,
                    (SELECT g.workspace_id FROM grants g
                      WHERE g.grant_id = v_reg.grant_id),
                    v_grant_subject(v_reg.grant_id), v_reg.effect_id)
            ON CONFLICT (stream_id) DO NOTHING;
            SELECT sr.owner_subject INTO v_reg_owner
              FROM stream_registry sr WHERE sr.stream_id = v_reg.stream_id;
            IF v_reg_owner IS DISTINCT FROM v_grant_subject(v_reg.grant_id) THEN
                RAISE EXCEPTION
                    'v8: stream % raced a foreign provider registration (CHUNK_ATTRIBUTION_INVALID)',
                    v_reg.stream_id;
            END IF;
        END LOOP;

        -- G9b: late-chunk equivalence completion (spec §1.2 barrier (d),
        -- second fact). A legally attributed chunk accepted AFTER the effect
        -- reached a terminal state is retained observationally and MAY
        -- complete an equivalence verification that was still pending: pass
        -- -> no conflict fact; fail -> the CANONICALIZER_CONFLICT audit fact
        -- is recorded. The business terminal state is never rewritten
        -- (barrier (d) first fact). Idempotent (effect_audit UNIQUE).
        FOR v_lc IN
            SELECT DISTINCT b.effect_id, b.attempt_no
              FROM pg_temp.v8_batch_items b
              JOIN effect_requests er ON er.effect_id = b.effect_id
             WHERE b.is_chunk AND b.action <> 'existing'
               AND er.status IN ('succeeded', 'failed_terminal',
                                 'cancelled_before_dispatch',
                                 'cancelled_after_dispatch', 'unknown_outcome')
               AND EXISTS (SELECT 1 FROM stream_completions sc
                            WHERE sc.effect_id = b.effect_id
                              AND sc.attempt_no = b.attempt_no)
        LOOP
            PERFORM v_stream_equivalence(
                p_session_id, v_lc.effect_id, v_lc.attempt_no,
                (SELECT sc.final_chunk_index FROM stream_completions sc
                  WHERE sc.effect_id = v_lc.effect_id
                    AND sc.attempt_no = v_lc.attempt_no),
                (SELECT sc.chunk_count FROM stream_completions sc
                  WHERE sc.effect_id = v_lc.effect_id
                    AND sc.attempt_no = v_lc.attempt_no),
                (SELECT sc.final_text FROM stream_completions sc
                  WHERE sc.effect_id = v_lc.effect_id
                    AND sc.attempt_no = v_lc.attempt_no));
        END LOOP;
    END IF;

    -- Merged entries map to their representative's identity (F2).
    UPDATE pg_temp.v8_batch_items m
       SET event_key = r.event_key, seq = r.seq
      FROM pg_temp.v8_batch_items r
     WHERE m.action = 'merged' AND m.rep_pos = r.pos;

    -- Step (7): the two-part receipt — (1) per-input-position event
    -- identity/seq mapping in input order (existing hits return the EXISTING
    -- event identity, never the request-side derived one; every merged input
    -- position maps to the same new event_key/seq), (2) the contiguous seq
    -- interval of THIS command's newly inserted events (empty for
    -- all-duplicate batches; n counts post-merge logical new events only).
    SELECT jsonb_build_object(
             'command_kind', 'append_events',
             'command_id', p_command_id,
             'items', coalesce((
                 SELECT jsonb_agg(jsonb_build_object(
                            'batch_item_ordinal', b.pos,
                            'event_key', b.event_key,
                            'seq', b.seq,
                            'disposition', b.action) ORDER BY b.pos)
                   FROM pg_temp.v8_batch_items b), '[]'::jsonb),
             'inserted', CASE WHEN v_new_count > 0 THEN jsonb_build_object(
                        'first_seq', v_first_seq,
                        'last_seq', v_first_seq + v_new_count - 1,
                        'count', v_new_count)
                 END)
      || coalesce(v_epoch_note, '{}'::jsonb)
      INTO v_receipt;

    -- Actual-outcome first occupation (step (4) of the judgment order):
    -- accepted, keyed by the computed canonical request hash.
    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
        outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'append_events', 'canonical_request_hash',
            v_computed, 'accepted', NULL, v_receipt::text,
            v_sha256_hex(v_receipt::text));

    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;
