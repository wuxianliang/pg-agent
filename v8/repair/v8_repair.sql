-- v8 G7c: repair — the unique exit for unknown_outcome (three terminal
-- states), the turn_end_closers history table, the SQL mirror of
-- closer_event_key@v1, and the unique protected slot update function
-- (append closer + advance the supersedes-chain head + insert the history
-- row, three-in-one, one transaction).
--
-- Source of truth: docs/designs/v8-dev.md (frozen spec), digests
-- docs/analysis/v8-impl-digest/s31b-command-table.md (§1.5 turn_end_closers
-- DDL verbatim, §2.5 repair row, §3.4 closer_event_key@v1, the slot data
-- contract (i)-(v) — the six controlled validations in the frozen order),
-- s32b-effect-ledger.md (§2.7 repair verbatim, §4.1 effect state closure
-- unknown_outcome exit edges, §4.3 cancel/unknown code map),
-- s32a-step-session.md (§4.1 blocked_unknown_effect outgoing edges, §3.4
-- retry_stop_reason ordered classification), spec §1.2 lines 66/69/71
-- (closer supersedes the provisional representation, append-only
-- recomputation, unique reducer), Conformance 5 unknown repair (spec §6
-- line 845).
--
-- Judgment order reuses v8_command_adjudicate (steps (1)-(4)) exactly like
-- every other receipt command; transaction boundaries are owned by the
-- CALLER (the Python client runs gate + business function + commit in one
-- transaction).
--
-- G7c scope guards (explicit):
--   * grant/slice and catalog_generation models are absent (same standing
--     deviation as G7a/G7b).
--   * the slot-creation entry for a repair whose turn has no slot row is
--     not reachable in this stage: every unknown settlement (completion
--     unknown closure, recovery takeover unknown branch) creates the
--     provisional slot in the same transaction. A missing slot therefore
--     rejects REPAIR_TARGET_INVALID (zero side effects) instead of
--     creating one; the create-when-absent mode lands with the
--     cancel/reconcile milestones that can produce slot-less turn ends.
--   * rule 3 (cancel closure) is completed by G8b: v_repair reaches the
--     shared implementation through the aggregation judgment (rule 3) and
--     the shared applier, which runs the shared cancel closure sub-operation
--     (v8/cancel/v8_closure.sql) over the residual siblings. Repair remains a
--     TRIGGER SOURCE (γ) — it does not own a private cancel-closure arm.
--   * repair does not require a held session coordination/recovery lease
--     (A34-style: the command receipt + session row lock is the control);
--     terminal-session repair for INFRA/WORKSPACE_LOST drains is
--     unreachable in this stage (no failure-drain paths exist yet).

-- ---------------------------------------------------------------------------
-- turn_end_closers (s31b §1.5, DDL frozen): the closer history index.
-- resolution_digest (SHA-256 native 32-byte binary of the resolution
-- canonical bytes) carries the unique constraint; the canonical bytes are a
-- NON-INDEXED retention column (byte length unbounded, J08 — an oversized
-- or incompressible resolution never makes the unique index unrealizable).
-- The composite FK (session_id, turn_id, turn_end_key) references
-- turn_end_slots' same three columns; closer/supersedes event keys are
-- covered by composite FKs (session_id, event_key) -> session_events
-- (write order inside the protected function: event row first, then
-- slot/closers rows — an orphan key can never persist).
-- ---------------------------------------------------------------------------
CREATE TABLE turn_end_closers (
    session_id                    uuid NOT NULL,
    turn_id                       uuid NOT NULL,
    turn_end_key                  text NOT NULL,
    resolution_identity_canonical bytea NOT NULL,
    resolution_digest             bytea NOT NULL
                                  CONSTRAINT turn_end_closers_digest_len
                                  CHECK (octet_length(resolution_digest) = 32),
    supersedes_event_key          text NOT NULL,
    closer_event_key              text NOT NULL,
    event_seq                     bigint NOT NULL CHECK (event_seq >= 1),
    -- UNIQUE(session_id, turn_id, resolution_digest) as the primary key.
    PRIMARY KEY (session_id, turn_id, resolution_digest),
    CONSTRAINT turn_end_closers_slot_fk
        FOREIGN KEY (session_id, turn_id, turn_end_key)
        REFERENCES turn_end_slots (session_id, turn_id, turn_end_key),
    CONSTRAINT turn_end_closers_closer_event_fk
        FOREIGN KEY (session_id, closer_event_key)
        REFERENCES session_events (session_id, event_key),
    CONSTRAINT turn_end_closers_supersedes_event_fk
        FOREIGN KEY (session_id, supersedes_event_key)
        REFERENCES session_events (session_id, event_key)
);

-- Only the protected slot update function inserts (it signals itself via
-- the transaction-local GUC v8.slot_protected_write, the same channel as
-- the turn_end_slots four-column guard, A10); after the write the row is
-- immutable (DELETE only ever follows the unified data-destruction policy,
-- which does not exist in this stage, so DELETE is rejected too).
CREATE FUNCTION v8_turn_end_closers_protected() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF coalesce(current_setting('v8.slot_protected_write', true), '') <> 'on' THEN
            RAISE EXCEPTION
                'turn_end_closers rows may only be inserted by the protected '
                'slot update function (append closer + advance head + insert '
                'history row, three-in-one)';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'turn_end_closers rows are immutable';
END;
$$;

CREATE TRIGGER trg_turn_end_closers_insert
BEFORE INSERT ON turn_end_closers
FOR EACH ROW EXECUTE FUNCTION v8_turn_end_closers_protected();

CREATE TRIGGER trg_turn_end_closers_immutable
BEFORE UPDATE OR DELETE ON turn_end_closers
FOR EACH ROW EXECUTE FUNCTION v8_turn_end_closers_protected();

-- ---------------------------------------------------------------------------
-- v_closer_event_key — the SQL mirror of closer_event_key@v1 (s31b §3.4,
-- byte-frozen; MUST be byte-identical to
-- v8/canonical/keys.py closer_event_key_v1; cross-checked by the G7c gate):
--   SHA-256("v8:closer-event-key@v1\0"
--        || len8(turn_end_key UTF-8 bytes)
--        || len8(supersedes_event_key UTF-8 bytes)
--        || len8(resolution identity canonical bytes)) as lowercase hex.
-- The two key arguments are the 64-byte lowercase-hex values; the
-- resolution argument is the canonical JSON bytes of the structured
-- resolution identity object.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_closer_event_key(
    p_turn_end_key text, p_supersedes_event_key text,
    p_resolution_canonical bytea
) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN encode(sha256(
    convert_to('v8:closer-event-key@v1', 'UTF8') || '\x00'::bytea
    || v_len8(v_identity_bytes(p_turn_end_key)) || v_identity_bytes(p_turn_end_key)
    || v_len8(v_identity_bytes(p_supersedes_event_key)) || v_identity_bytes(p_supersedes_event_key)
    || v_len8(p_resolution_canonical) || p_resolution_canonical
), 'hex');

-- ---------------------------------------------------------------------------
-- v_turn_end_slot_update — the UNIQUE protected slot update function
-- (slot contract (i): "append closer + advance head + slot_status/version
-- increment + closers history row insert" three-in-one, one transaction;
-- there is NO second validation/write path outside this function). The
-- caller (v_repair) holds the session/step/effect/attempt row locks in the
-- master order; this function takes the turn_end_slot row lock (the
-- seventh lock position, after attempt).
--
-- The six controlled validations (v) run in the frozen order inside the
-- slot row lock:
--   (1) locate + lock the unique slot row by (session_id, turn_id);
--   (2) idempotency pre-check (digest + canonical two-level, J08) BEFORE
--       any chain validation: digest hit + canonical exact-equal + payload
--       + derived event_key + predecessor all equal -> idempotent return
--       of the existing closer (the chain check is NOT executed — a resend
--       carrying the old chain head still returns the original closer);
--       digest hit with canonical/payload/key/predecessor any mismatch ->
--       IDEMPOTENCY_CONFLICT (no second closer);
--   (3) the candidate supersedes MUST belong to the same session/turn and
--       MUST be the slot's CURRENT chain head (the provisional end while
--       no closer is committed, or the latest committed closer) — the
--       candidate-head attribution check rejects the three classes
--       (ordinary event / cross-turn / orphan key) plus off-chain or
--       stale-head references, all REPAIR_TARGET_INVALID, zero side
--       effects;
--   (4) resolution/predecessor consistency: the closer event_key is
--       derived by (ii) from (turn_end_key, supersedes, resolution) — the
--       caller never supplies it;
--   (5) the CAS re-read under the row lock: head already advanced means a
--       concurrent closer committed first — same resolution classifies by
--       (2), a different resolution rejects and MUST NOT overwrite (the
--       caller resends against the current head). The version CAS is
--       written in the frozen form (UPDATE ... WHERE version = expected);
--   (6) the unified REPAIR_TARGET_INVALID rejection for cross session /
--       cross turn / non-slot event / off-chain supersedes references
--       (receipt lands rejected_mismatch with the code preserved, zero
--       control state, no event appended).
--
-- Returns out_status 'appended' | 'idempotent' | 'rejected' (with
-- out_code). Rejections return without raising so the caller can convert
-- them into a zero-side-effect rejection receipt (the settlement +
-- slot-update work of the repair transaction runs inside a savepoint that
-- the caller rolls back on 'rejected').
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_turn_end_slot_update(
    p_session_id uuid, p_turn_id uuid,
    p_event_type text, p_payload_canonical text,
    p_resolution_canonical bytea, p_supersedes_event_key text,
    p_schema_version text, p_canonicalizer_version text,
    p_step_id uuid, p_effect_id uuid, p_attempt_no bigint,
    p_command_id text
) RETURNS TABLE(out_status text, out_code text, out_closer_event_key text,
                out_event_seq bigint, out_slot_version bigint,
                out_slot_status text, out_head_event_key text,
                out_idempotent boolean)
LANGUAGE plpgsql AS $$
DECLARE
    v_slot turn_end_slots%ROWTYPE;
    v_digest bytea := sha256(p_resolution_canonical);
    v_closer turn_end_closers%ROWTYPE;
    v_derived text;
    v_prev_payload text;
    v_ev session_events%ROWTYPE;
    v_payload jsonb;
    v_key text;
    v_seq bigint;
    v_iso bigint;
BEGIN
    -- Protected-write channel (A10): the slot's four protected columns and
    -- the closers inserts may only move under this GUC, and this function
    -- is its only legitimate user.
    PERFORM set_config('v8.slot_protected_write', 'on', true);

    -- (v)(1): locate + lock the unique slot row; every judgment below runs
    -- inside this row lock (the concurrency arbitration of (iv): the first
    -- committer wins, later ones re-read inside the lock).
    SELECT * INTO v_slot FROM turn_end_slots tes
     WHERE tes.session_id = p_session_id AND tes.turn_id = p_turn_id
     FOR UPDATE;
    IF NOT FOUND THEN
        -- G19b (D11, A41 resolved): create-when-absent. The turn's chain
        -- EVENT (the provisional unknown end) locates the initial head;
        -- the row is created in the standard provisional shape —
        -- turn_end_key derived from (session_id, turn_id), never
        -- caller-supplied, resolution NULL, version 1 — and the update
        -- proceeds through the normal protected flow. Concurrent
        -- double-writes converge on UNIQUE(session_id, turn_id). A turn
        -- with NO chain event at all keeps the stable classified
        -- rejection (nothing can be superseded).
        SELECT event_key INTO v_key
          FROM session_events se
         WHERE se.session_id = p_session_id AND se.turn_id = p_turn_id
           AND se.event_type = 'turn/end'
           AND se.payload::jsonb ->> 'outcome' = 'unknown'
         ORDER BY se.seq DESC LIMIT 1;
        IF v_key IS NULL THEN
            RETURN QUERY SELECT 'rejected'::text, 'REPAIR_TARGET_INVALID'::text,
                NULL::text, NULL::bigint, NULL::bigint, NULL::text, NULL::text,
                false;
            RETURN;
        END IF;
        INSERT INTO turn_end_slots(
            session_id, turn_id, turn_end_key, head_event_key, slot_status,
            resolution_identity_canonical, version)
        VALUES (
            p_session_id, p_turn_id, v_turn_end_key(p_session_id, p_turn_id),
            v_key, 'provisional', NULL, 1)
        ON CONFLICT (session_id, turn_id) DO NOTHING;
        SELECT * INTO v_slot FROM turn_end_slots tes
         WHERE tes.session_id = p_session_id AND tes.turn_id = p_turn_id
         FOR UPDATE;
    END IF;

    -- (v)(2): idempotency pre-check (digest + canonical two-level), BEFORE
    -- any chain validation.
    SELECT * INTO v_closer FROM turn_end_closers c
     WHERE c.session_id = p_session_id AND c.turn_id = p_turn_id
       AND c.resolution_digest = v_digest;
    IF FOUND THEN
        v_derived := v_closer_event_key(v_slot.turn_end_key,
                                        p_supersedes_event_key,
                                        p_resolution_canonical);
        SELECT se.payload INTO v_prev_payload FROM session_events se
         WHERE se.session_id = p_session_id
           AND se.event_key = v_closer.closer_event_key;
        IF v_closer.resolution_identity_canonical = p_resolution_canonical
           AND v_prev_payload IS NOT NULL
           AND v_prev_payload = p_payload_canonical
           AND v_closer.supersedes_event_key = p_supersedes_event_key
           AND v_closer.closer_event_key = v_derived THEN
            RETURN QUERY SELECT 'idempotent'::text, NULL::text,
                v_closer.closer_event_key, v_closer.event_seq,
                v_slot.version, v_slot.slot_status, v_slot.head_event_key,
                true;
            RETURN;
        END IF;
        -- Same digest but canonical bytes / payload / derived key /
        -- predecessor any mismatch -> stable IDEMPOTENCY_CONFLICT.
        RETURN QUERY SELECT 'rejected'::text, 'IDEMPOTENCY_CONFLICT'::text,
            NULL::text, NULL::bigint, NULL::bigint, NULL::text, NULL::text,
            false;
        RETURN;
    END IF;

    -- (v)(3)+(6): candidate-head attribution check (the three database
    -- classes) and the current-chain-head requirement (stale head /
    -- off-chain reference). All rejections are REPAIR_TARGET_INVALID with
    -- zero side effects.
    SELECT * INTO v_ev FROM session_events se
     WHERE se.session_id = p_session_id
       AND se.event_key = p_supersedes_event_key;
    IF NOT FOUND THEN
        -- Orphan key: no session_events row (the composite FK is the
        -- database-level backstop; this check produces the stable
        -- classified rejection).
        RETURN QUERY SELECT 'rejected'::text, 'REPAIR_TARGET_INVALID'::text,
            NULL::text, NULL::bigint, NULL::bigint, NULL::text, NULL::text,
            false;
        RETURN;
    END IF;
    IF v_ev.turn_id IS DISTINCT FROM p_turn_id THEN
        -- Cross-turn supersedes (event row turn attribution mismatch).
        RETURN QUERY SELECT 'rejected'::text, 'REPAIR_TARGET_INVALID'::text,
            NULL::text, NULL::bigint, NULL::bigint, NULL::text, NULL::text,
            false;
        RETURN;
    END IF;
    IF v_ev.event_type <> 'turn/end'
       AND NOT EXISTS (SELECT 1 FROM turn_end_closers c
                        WHERE c.session_id = p_session_id
                          AND c.turn_id = p_turn_id
                          AND c.closer_event_key = p_supersedes_event_key) THEN
        -- Ordinary event as candidate head (neither the provisional end
        -- nor a closer-class event recorded in turn_end_closers).
        RETURN QUERY SELECT 'rejected'::text, 'REPAIR_TARGET_INVALID'::text,
            NULL::text, NULL::bigint, NULL::bigint, NULL::text, NULL::text,
            false;
        RETURN;
    END IF;
    IF p_supersedes_event_key IS DISTINCT FROM v_slot.head_event_key THEN
        -- Stale head / off-chain reference (incl. a historical closer of
        -- this chain that is no longer the head): (v)(5) — a different
        -- resolution MUST NOT overwrite the committed head; the caller
        -- resends against the current chain head.
        RETURN QUERY SELECT 'rejected'::text, 'REPAIR_TARGET_INVALID'::text,
            NULL::text, NULL::bigint, NULL::bigint, NULL::text, NULL::text,
            false;
        RETURN;
    END IF;

    -- Closer payload metadata (defensive envelope consistency; the client
    -- builds the payload, SQL validates the three metadata fields before
    -- persisting it).
    BEGIN
        v_payload := p_payload_canonical::jsonb;
    EXCEPTION WHEN OTHERS THEN
        v_payload := NULL;
    END;
    IF v_payload IS NULL OR jsonb_typeof(v_payload) <> 'object'
       OR v_payload->'closer' IS DISTINCT FROM 'true'::jsonb
       OR v_payload->'resolution' IS DISTINCT FROM
            convert_from(p_resolution_canonical, 'UTF8')::jsonb
       OR (v_payload->>'supersedes_event_key')
            IS DISTINCT FROM p_supersedes_event_key THEN
        RETURN QUERY SELECT 'rejected'::text, 'REPAIR_TARGET_INVALID'::text,
            NULL::text, NULL::bigint, NULL::bigint, NULL::text, NULL::text,
            false;
        RETURN;
    END IF;

    -- (v)(4): the closer event_key is ALWAYS derived by (ii); the caller
    -- never supplies it.
    v_key := v_closer_event_key(v_slot.turn_end_key, p_supersedes_event_key,
                                p_resolution_canonical);

    -- Append the closer event FIRST (the composite FKs of the slot/closers
    -- rows to session_events hold at statement time; the unified seq
    -- allocator advances sessions.next_seq inside the session row lock the
    -- caller already holds; the internal semantic ordinal is allocated by
    -- commit order, max+1, same convention as the completion closure).
    SELECT s.next_seq INTO v_seq FROM sessions s
     WHERE s.session_id = p_session_id;
    UPDATE sessions SET next_seq = v_seq + 1, updated_at = now()
     WHERE session_id = p_session_id;
    SELECT coalesce(max(se.internal_semantic_ordinal), 0) + 1 INTO v_iso
      FROM session_events se WHERE se.session_id = p_session_id;
    INSERT INTO session_events(
        seq, session_id, event_type, event_class, schema_version,
        canonicalizer_version, event_key, turn_id, step_id, effect_id,
        payload, payload_hash, semantic_input_ordinal,
        internal_semantic_ordinal, attempt_no, command_id,
        batch_item_ordinal)
    VALUES (
        v_seq, p_session_id, p_event_type, 'semantic', p_schema_version,
        p_canonicalizer_version, v_key, p_turn_id, p_step_id, p_effect_id,
        p_payload_canonical, v_sha256_hex(p_payload_canonical), NULL,
        v_iso, p_attempt_no, p_command_id, NULL);

    -- (v)(5): head advance + slot_status -> known + resolution bytes +
    -- version CAS in the frozen form. The slot row lock is held, so the
    -- CAS always matches; a raced head advance would have classified at
    -- (2)/(3) above after the lock wait.
    UPDATE turn_end_slots SET
        head_event_key = v_key,
        slot_status = 'known',
        resolution_identity_canonical = p_resolution_canonical,
        version = version + 1
     WHERE session_id = p_session_id AND turn_id = p_turn_id
       AND version = v_slot.version;

    -- The immutable history row (three-in-one with the event append and
    -- the head advance).
    INSERT INTO turn_end_closers(
        session_id, turn_id, turn_end_key, resolution_identity_canonical,
        resolution_digest, supersedes_event_key, closer_event_key,
        event_seq)
    VALUES (
        p_session_id, p_turn_id, v_slot.turn_end_key,
        p_resolution_canonical, v_digest, p_supersedes_event_key, v_key,
        v_seq);

    RETURN QUERY SELECT 'appended'::text, NULL::text, v_key, v_seq,
        v_slot.version + 1, 'known'::text, v_key, false;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_repair — the repair receipt command (s32b §2.7 verbatim: every exit of
-- unknown_outcome runs ONLY through repair and lands only on
-- succeeded | failed_terminal | cancelled_after_dispatch; a plain
-- complete_effect on an unknown attempt returns REPAIR_REQUIRED).
--
-- Envelope: target effect_id/attempt_no, the structured resolution
-- identity object (canonical bytes), supersedes_event_key (the caller's
-- view of the current chain head), the evidence object, and — for a
-- success resolution — the result payload in the same shape as the
-- completion path (decision result for an LLM slot, tool result for a
-- tool slot).
--
-- Classification (s32b §2.7 / Conformance 5):
--   * target effect MUST be unknown_outcome with the current, un-superseded
--     attempt — otherwise REPAIR_TARGET_INVALID (target not unknown / not
--     persisted / attempt row missing) or REPAIR_EVIDENCE_REQUIRED (the
--     envelope attempt is not the current execution attempt, i.e. an old
--     superseded attempt's evidence impersonating the current one);
--   * evidence through the UNIQUE v_classify_evidence: known (success
--     receipt / failure receipt + persisted no-side-effect proof dual
--     requirement / cancellation evidence) -> the three terminal states,
--     NEVER a new attempt; a failure persists retry_stop_reason through
--     the ordered classification (budget exhaustion derives
--     FAILED_RETRY_BUDGET_EXHAUSTED via rule 4);
--   * a no-side-effect proof alone, or a failure receipt with side-effect
--     state unclear (classification stays unknown) -> stable
--     REPAIR_EVIDENCE_REQUIRED, zero control state, unknown kept.
--
-- Settlement + turn-level unknown closure: the closer event (LLM effect ->
-- assistant/message-class closer, tool effect -> tool/result-class closer;
-- failure/cancellation -> turn/end-class closer) carries
-- supersedes_event_key and the resolution identity, its event_key derived
-- by v_closer_event_key; the protected v_turn_end_slot_update appends the
-- event, CAS-advances the slot head, flips slot_status -> known and
-- inserts the turn_end_closers row in one transaction. All siblings are
-- re-aggregated in the same transaction (rules 1/2/4/5 through the shared
-- judgment + applier; the rule-6 success arms and the G8b rule-3 cancel
-- closure share the one sub-operation).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_repair(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint,
    p_effect_id uuid, p_attempt_no bigint,
    p_resolution_canonical text, p_supersedes_event_key text,
    p_closer_event_type text, p_closer_payload_canonical text,
    p_result_payload_canonical text, p_plan_canonical text,
    p_evidence jsonb,
    p_schema_version text, p_canonicalizer_version text,
    p_declared_hash text, p_payload_canonical text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    -- G12 (A39 closure): repair on a drain-terminal session (failed /
    -- WORKSPACE_LOST / INFRA_*) settles the effect and closes steps but
    -- MUST NOT overwrite the terminal session state; completed/cancelled
    -- sessions are rejected.
    v_terminal boolean := false;
    v_receipt jsonb;
    v_er effect_requests%ROWTYPE;
    v_att effect_attempts%ROWTYPE;
    v_step steps%ROWTYPE;
    v_step_id uuid;
    v_turn uuid;
    v_batch_kind text;
    v_res_bytes bytea := convert_to(p_resolution_canonical, 'UTF8');
    v_digest bytea := sha256(convert_to(p_resolution_canonical, 'UTF8'));
    v_res jsonb;
    v_closer turn_end_closers%ROWTYPE;
    v_derived text;
    v_tek text;
    v_prev_payload text;
    v_class text;
    v_resolution text;
    v_code text;
    v_cancel_reason text;
    v_receipt_id text;
    v_result_hash text;
    v_result jsonb;
    v_plan jsonb;
    v_tools_empty boolean;
    v_do boolean;
    v_ft boolean;
    v_max_att bigint;
    v_reason text := NULL;
    v_upd record;
    v_agg record;
    v_fin record;
    v_rej_code text;
    v_expected_type text;
    v_cp jsonb;
BEGIN
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'repair',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id
     FOR UPDATE;

    -- G12 (A39 closure): the terminal-session repair exception covers ONLY
    -- drain-terminal sessions (failed with a WORKSPACE_LOST / INFRA drain
    -- code); completed/cancelled and non-drain failures reject stably.
    IF v_sess.state IN ('completed', 'cancelled')
       OR (v_sess.state = 'failed'
           AND NOT (v_sess.failure_code IS NOT NULL
                    AND v_sess.failure_code IN ('WORKSPACE_LOST',
                                                'INFRA_ASSEMBLY_FAILED',
                                                'INFRA_PROTOCOL_VIOLATION'))) THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'SESSION_TERMINAL',
            format('repair on a terminal session (state %s, code %s)',
                   v_sess.state, v_sess.failure_code));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_TERMINAL'::text, v_receipt;
        RETURN;
    END IF;
    v_terminal := v_sess.state = 'failed';

    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_stale', 'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session control row');
        RETURN QUERY SELECT 'rejected_stale'::text, 'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;

    -- Locate (lockless read of the immutable association), then lock in
    -- the master order: step -> effect -> attempt (the slot row lock is
    -- taken inside v_turn_end_slot_update, the seventh position).
    SELECT er.step_id INTO v_step_id FROM effect_requests er
     WHERE er.effect_id = p_effect_id;
    IF NOT FOUND THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'REPAIR_TARGET_INVALID',
            'repair target effect is not persisted');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_TARGET_INVALID'::text, v_receipt;
        RETURN;
    END IF;
    SELECT * INTO v_step FROM steps st WHERE st.step_id = v_step_id FOR UPDATE;
    SELECT * INTO v_er FROM effect_requests er
     WHERE er.effect_id = p_effect_id FOR UPDATE;
    IF v_er.session_id IS DISTINCT FROM p_session_id THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'REPAIR_TARGET_INVALID',
            'repair target effect does not belong to this session');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_TARGET_INVALID'::text, v_receipt;
        RETURN;
    END IF;
    v_turn := v_step.turn_id;
    SELECT max(a.attempt_no) INTO v_max_att FROM effect_attempts a
     WHERE a.effect_id = p_effect_id;

    -- (v)(2) upfront idempotency read. The protected function re-executes
    -- the full two-level comparison authoritatively inside the slot lock;
    -- this early read exists only to ORDER the idempotent return BEFORE
    -- the target-state guard: a same-resolution resend (including one
    -- carrying the old supersedes chain head) returns the original closer
    -- even though the effect is already terminal, and a same-resolution /
    -- different-payload-or-keys resend is IDEMPOTENCY_CONFLICT.
    SELECT * INTO v_closer FROM turn_end_closers c
     WHERE c.session_id = p_session_id AND c.turn_id = v_turn
       AND c.resolution_digest = v_digest;
    IF FOUND THEN
        v_tek := v_turn_end_key(p_session_id, v_turn);
        v_derived := v_closer_event_key(v_tek, p_supersedes_event_key,
                                        v_res_bytes);
        SELECT se.payload INTO v_prev_payload FROM session_events se
         WHERE se.session_id = p_session_id
           AND se.event_key = v_closer.closer_event_key;
        IF v_closer.resolution_identity_canonical = v_res_bytes
           AND v_prev_payload IS NOT NULL
           AND v_prev_payload = p_closer_payload_canonical
           AND v_closer.supersedes_event_key = p_supersedes_event_key
           AND v_closer.closer_event_key = v_derived THEN
            v_receipt := jsonb_build_object(
                'command_kind', 'repair',
                'command_id', p_command_id,
                'idempotent', true,
                'effect_id', p_effect_id,
                'attempt_no', p_attempt_no,
                'resolution_digest', encode(v_digest, 'hex'),
                'closer', jsonb_build_object(
                    'event_key', v_closer.closer_event_key,
                    'seq', v_closer.event_seq,
                    'supersedes_event_key', v_closer.supersedes_event_key),
                'slot', (SELECT jsonb_build_object(
                            'head_event_key', tes.head_event_key,
                            'slot_status', tes.slot_status,
                            'version', tes.version)
                          FROM turn_end_slots tes
                         WHERE tes.session_id = p_session_id
                           AND tes.turn_id = v_turn),
                'step_status', (SELECT st.status FROM steps st
                                 WHERE st.step_id = v_step_id),
                'session_state', (SELECT s.state FROM sessions s
                                   WHERE s.session_id = p_session_id));
            INSERT INTO command_bindings(
                session_id, command_id, first_key_kind, first_key_value,
                first_outcome)
            VALUES (p_session_id, p_command_id, 'canonical_request_hash',
                    v_computed, 'accepted');
            INSERT INTO command_receipts(
                session_id, command_id, command_kind, receipt_key_kind,
                receipt_key_value, outcome, code, result_canonical,
                result_hash)
            VALUES (p_session_id, p_command_id, 'repair',
                    'canonical_request_hash', v_computed, 'accepted', NULL,
                    v_receipt::text, v_sha256_hex(v_receipt::text));
            RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
            RETURN;
        END IF;
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'IDEMPOTENCY_CONFLICT',
            'same resolution digest but canonical bytes / payload / derived '
            'event key / predecessor mismatch; no second closer appended');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'IDEMPOTENCY_CONFLICT'::text, v_receipt;
        RETURN;
    END IF;

    -- ---- target guards (s32b §2.7) ----
    IF v_max_att IS NULL THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'REPAIR_TARGET_INVALID',
            'repair target has no attempt authority row');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_TARGET_INVALID'::text, v_receipt;
        RETURN;
    END IF;
    IF v_er.status <> 'unknown_outcome' THEN
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id,
            attempt_no, audit_key_kind, audit_key_value, result_fingerprint,
            reason)
        VALUES (p_session_id, p_session_id, v_step_id, p_effect_id,
                p_attempt_no, 'canonical_binding', v_computed,
                v_sha256_hex(coalesce(p_result_payload_canonical,
                                      p_evidence::text)),
                'REPAIR_TARGET_INVALID');
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'REPAIR_TARGET_INVALID',
            format('repair target effect must be unknown_outcome, got %s '
                   '(unknown exits run only through repair)', v_er.status));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_TARGET_INVALID'::text, v_receipt;
        RETURN;
    END IF;
    -- The envelope attempt must be the current execution attempt: an old,
    -- superseded attempt's evidence impersonating the current one is the
    -- evidence-binding failure family (REPAIR_EVIDENCE_REQUIRED), never a
    -- target reclassification.
    IF p_attempt_no IS DISTINCT FROM v_max_att THEN
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id,
            attempt_no, audit_key_kind, audit_key_value, result_fingerprint,
            reason)
        VALUES (p_session_id, p_session_id, v_step_id, p_effect_id,
                p_attempt_no, 'canonical_binding', v_computed,
                v_sha256_hex(p_evidence::text), 'REPAIR_EVIDENCE_REQUIRED');
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'REPAIR_EVIDENCE_REQUIRED',
            format('envelope attempt_no %s is not the current execution '
                   'attempt %s: old-attempt evidence cannot be reused',
                   coalesce(p_attempt_no::text, 'NULL'), v_max_att));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_EVIDENCE_REQUIRED'::text, v_receipt;
        RETURN;
    END IF;
    SELECT * INTO v_att FROM effect_attempts a
     WHERE a.effect_id = p_effect_id AND a.attempt_no = p_attempt_no
     FOR UPDATE;
    IF v_att.superseded_by_attempt_no IS NOT NULL THEN
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id,
            attempt_no, audit_key_kind, audit_key_value, result_fingerprint,
            reason)
        VALUES (p_session_id, p_session_id, v_step_id, p_effect_id,
                p_attempt_no, 'canonical_binding', v_computed,
                v_sha256_hex(p_evidence::text), 'REPAIR_EVIDENCE_REQUIRED');
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'REPAIR_EVIDENCE_REQUIRED',
            format('attempt %s was superseded by attempt %s: its evidence '
                   'is audit-only and cannot repair the current attempt',
                   p_attempt_no, v_att.superseded_by_attempt_no));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_EVIDENCE_REQUIRED'::text, v_receipt;
        RETURN;
    END IF;
    IF v_att.status <> 'unknown_outcome' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'REPAIR_TARGET_INVALID',
            format('repair target attempt must be unknown_outcome, got %s',
                   v_att.status));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_TARGET_INVALID'::text, v_receipt;
        RETURN;
    END IF;

    -- ---- evidence through the UNIQUE classification function ----
    v_class := v_classify_evidence(p_effect_id, p_attempt_no, p_evidence);
    IF v_class = 'unknown' THEN
        -- No verifiably bound evidence, or bound evidence that still
        -- classifies unknown (a no-side-effect proof alone, or a failure
        -- receipt with side-effect state unclear): stable
        -- REPAIR_EVIDENCE_REQUIRED, zero control state, unknown kept.
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id,
            attempt_no, audit_key_kind, audit_key_value, result_fingerprint,
            reason)
        VALUES (p_session_id, p_session_id, v_step_id, p_effect_id,
                p_attempt_no, 'canonical_binding', v_computed,
                v_sha256_hex(p_evidence::text), 'REPAIR_EVIDENCE_REQUIRED');
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'REPAIR_EVIDENCE_REQUIRED',
            'evidence fails the binding requirement or still classifies '
            'unknown (no-side-effect proof alone, or failure receipt with '
            'side-effect state unclear); unknown_outcome kept');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_EVIDENCE_REQUIRED'::text, v_receipt;
        RETURN;
    END IF;

    -- ---- resolution identity object validation (the caller submits the
    -- value as an OBJECT check only; derivation always follows the frozen
    -- algorithm — a mismatch is a mismatch rejection) ----
    BEGIN
        v_res := p_resolution_canonical::jsonb;
    EXCEPTION WHEN OTHERS THEN
        v_res := NULL;
    END;
    v_resolution := CASE v_class
        WHEN 'known_success' THEN 'succeeded'
        WHEN 'known_failure' THEN 'failed_terminal'
        ELSE 'cancelled_after_dispatch' END;
    v_receipt_id := p_evidence->'provider_receipt'->>'receipt_id';
    IF v_class = 'known_cancellation' THEN
        v_code := CASE WHEN v_receipt_id IS NOT NULL
                       THEN 'CANCELLED_BY_PROVIDER'
                       ELSE 'CANCELLED_BY_REQUEST_AFTER_DISPATCH' END;
    ELSIF v_class = 'known_success' THEN
        v_code := 'SUCCEEDED';
    ELSE
        v_code := v_res->>'code';
    END IF;
    IF v_res IS NULL OR jsonb_typeof(v_res) <> 'object'
       OR (v_res->>'effect_id') IS DISTINCT FROM p_effect_id::text
       OR v8_entry_int(v_res->'attempt_no') IS DISTINCT FROM p_attempt_no::numeric
       OR (v_res->>'resolution') IS DISTINCT FROM v_resolution
       OR coalesce(v_res->>'code', '') = ''
       OR (v_class <> 'known_failure'
           AND (v_res->>'code') IS DISTINCT FROM v_code) THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'REPAIR_TARGET_INVALID',
            'resolution identity object does not match the derived '
            'settlement (effect/attempt/resolution/code)');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_TARGET_INVALID'::text, v_receipt;
        RETURN;
    END IF;
    v_code := v_res->>'code';

    SELECT b.kind INTO v_batch_kind FROM batches b
     WHERE b.batch_id = v_er.batch_id;

    -- ---- closer event type derivation + payload shape validation ----
    v_expected_type := CASE
        WHEN v_class = 'known_success'
            THEN CASE WHEN v_batch_kind = 'tools' THEN 'tool/result'
                      ELSE 'assistant/message' END
        ELSE 'turn/end' END;
    BEGIN
        v_cp := p_closer_payload_canonical::jsonb;
    EXCEPTION WHEN OTHERS THEN
        v_cp := NULL;
    END;
    IF p_closer_event_type IS DISTINCT FROM v_expected_type
       OR v_cp IS NULL OR jsonb_typeof(v_cp) <> 'object' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
            v_computed, 'rejected_mismatch', 'REPAIR_TARGET_INVALID',
            format('closer event type/payload inconsistent with the derived '
                   'settlement (expected type %s)', v_expected_type));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_TARGET_INVALID'::text, v_receipt;
        RETURN;
    END IF;

    IF v_class = 'known_success' AND v_batch_kind = 'tools' THEN
        -- Tool arm: the result payload must carry the sealed slot's
        -- tool_call_id (same contract as the completion tool arm).
        BEGIN
            v_result := p_result_payload_canonical::jsonb;
        EXCEPTION WHEN OTHERS THEN
            v_result := NULL;
        END;
        IF v_result IS NULL OR jsonb_typeof(v_result) <> 'object'
           OR (v_result->>'tool_call_id') IS DISTINCT FROM v_er.tool_call_id
           OR (v_cp->>'tool_call_id') IS DISTINCT FROM v_er.tool_call_id
           OR NOT (v_cp ? 'output') THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
                v_computed, 'rejected_mismatch', 'TOOL_RESULT_MISMATCH',
                'tool result payload tool_call_id does not match the sealed slot');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'TOOL_RESULT_MISMATCH'::text, v_receipt;
            RETURN;
        END IF;
    ELSIF v_class = 'known_success' THEN
        -- Decision arm: the SAME semantic layer as the completion path —
        -- the decision marks / tools-plan bidirectional mutex-exhaustive
        -- schema (the repair-persisted decision_result_identity and the
        -- normalized plan MUST be isomorphic to a normal completion's, so
        -- the later tools seal can consume them unchanged).
        BEGIN
            v_result := p_result_payload_canonical::jsonb;
        EXCEPTION WHEN OTHERS THEN
            v_result := NULL;
        END;
        IF v_result IS NULL OR jsonb_typeof(v_result) <> 'object'
           OR v_result->'message' IS NULL
           OR jsonb_typeof(v_result->'message') <> 'object'
           OR v_result->'tools' IS NULL
           OR jsonb_typeof(v_result->'tools') <> 'array'
           OR v_result->'decision_only' IS NULL
           OR jsonb_typeof(v_result->'decision_only') <> 'boolean'
           OR v_result->'final_tools' IS NULL
           OR jsonb_typeof(v_result->'final_tools') <> 'boolean'
           OR NOT (v_cp ? 'message') THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
                v_computed, 'rejected_mismatch', 'RESULT_PAYLOAD_INVALID',
                'successful decision resolution requires message/tools/'
                'decision_only/final_tools and a message closer payload');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'RESULT_PAYLOAD_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        v_tools_empty := jsonb_array_length(v_result->'tools') = 0;
        v_do := (v_result->>'decision_only')::boolean;
        v_ft := (v_result->>'final_tools')::boolean;
        IF NOT ((v_tools_empty AND v_do AND NOT v_ft)
                OR (NOT v_tools_empty AND NOT v_do AND v_ft)) THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
                v_computed, 'rejected_mismatch', 'DECISION_PLAN_INVALID',
                'decision marks/tools plan combination violates the '
                'bidirectional mutex schema');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'DECISION_PLAN_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        IF p_plan_canonical IS NULL THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
                v_computed, 'rejected_mismatch', 'DECISION_PLAN_INVALID',
                'successful decision resolution requires the normalized '
                'tools plan canonical text');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'DECISION_PLAN_INVALID'::text, v_receipt;
            RETURN;
        END IF;
        BEGIN
            v_plan := p_plan_canonical::jsonb;
        EXCEPTION WHEN OTHERS THEN
            v_plan := NULL;
        END;
        IF v_plan IS NULL OR jsonb_typeof(v_plan) <> 'array'
           OR v_plan IS DISTINCT FROM (v_result->'tools') THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
                v_computed, 'rejected_mismatch', 'DECISION_PLAN_INVALID',
                'tools plan canonical does not match the resolution payload '
                'tools member');
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'DECISION_PLAN_INVALID'::text, v_receipt;
            RETURN;
        END IF;
    ELSE
        -- Failure/cancellation closer: a turn/end-class payload with the
        -- derived reason.
        v_cancel_reason := CASE
            WHEN v_class = 'known_failure' THEN 'failed'
            WHEN v_code = 'CANCELLED_BY_PROVIDER'
                THEN 'cancelled_by_provider'
            ELSE 'cancelled_by_request_after_dispatch' END;
        IF (v_cp->>'interrupted') IS DISTINCT FROM 'true'
           OR (v_cp->>'reason') IS DISTINCT FROM v_cancel_reason THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id, 'repair',
                v_computed, 'rejected_mismatch', 'REPAIR_TARGET_INVALID',
                format('turn/end closer payload must carry interrupted=true '
                       'and the derived reason %s', v_cancel_reason));
            RETURN QUERY SELECT 'rejected_mismatch'::text, 'REPAIR_TARGET_INVALID'::text, v_receipt;
            RETURN;
        END IF;
    END IF;

    -- ==================================================================
    -- Settlement + closer append + slot update + sibling re-aggregation.
    -- The slot chain validations live ONLY inside v_turn_end_slot_update;
    -- a 'rejected' outcome there rolls this savepoint back (zero control
    -- state) and converts into the classified rejection receipt.
    -- ==================================================================
    BEGIN
        IF v_class = 'known_success' THEN
            v_result_hash := v_sha256_hex(p_result_payload_canonical);
            UPDATE effect_requests SET
                status = 'succeeded',
                result_hash = v_result_hash,
                provider_request_id = coalesce(v_receipt_id,
                                               v_att.provider_request_id),
                updated_at = now()
             WHERE effect_id = p_effect_id;
            UPDATE effect_attempts SET
                status = 'succeeded',
                result_hash = v_result_hash,
                provider_request_id = coalesce(v_receipt_id,
                                               v_att.provider_request_id),
                completed_at = now()
             WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;
            IF v_batch_kind = 'decision' THEN
                -- Persist the decision marks and the normalized plan
                -- (decision_result_identity = (effect_id, attempt_no,
                -- result_hash, closer event_key) — the closer event below
                -- IS the semantic result event; plan_hash over the plan,
                -- recomputable by the later tools seal).
                UPDATE steps st SET
                    decision_only = v_do,
                    final_tools = v_ft,
                    plan_canonical = CASE WHEN NOT v_do
                                          THEN p_plan_canonical
                                          ELSE st.plan_canonical END,
                    plan_hash = CASE WHEN NOT v_do
                                     THEN v_sha256_hex(p_plan_canonical)
                                     ELSE st.plan_hash END,
                    updated_at = now()
                 WHERE st.step_id = v_step_id;
            END IF;
        ELSIF v_class = 'known_failure' THEN
            -- The repair transaction IS the control-state persistence path
            -- for the dual-requirement evidence bound to this attempt.
            INSERT INTO effect_evidence(
                effect_id, attempt_no, evidence_class, receipt_id,
                evidence_canonical)
            VALUES
                (p_effect_id, p_attempt_no, 'failure_receipt', v_receipt_id,
                 (p_evidence->'provider_receipt')::text),
                (p_effect_id, p_attempt_no, 'no_side_effect_proof', NULL,
                 (p_evidence->'no_side_effect_proof')::text)
            ON CONFLICT DO NOTHING;
            v_result_hash := v_sha256_hex(coalesce(p_result_payload_canonical,
                                                   p_evidence::text));
            UPDATE effect_requests SET
                status = 'failed_terminal',
                result_hash = v_result_hash,
                provider_request_id = coalesce(v_receipt_id,
                                               v_att.provider_request_id),
                updated_at = now()
             WHERE effect_id = p_effect_id;
            UPDATE effect_attempts SET
                status = 'failed_terminal',
                result_hash = v_result_hash,
                provider_request_id = coalesce(v_receipt_id,
                                               v_att.provider_request_id),
                completed_at = now()
             WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;
            -- retry_stop_reason through the unique ordered classification
            -- (R-01 CAS writer; an effect-level repair NEVER produces a
            -- new attempt).
            v_reason := v_retry_stop_reason_cas(p_effect_id);
        ELSE
            -- known_cancellation: provider-confirmed (receipt) or the
            -- cancel request took effect before the side effect (proof).
            v_result_hash := v_sha256_hex(coalesce(p_result_payload_canonical,
                                                   p_evidence::text));
            UPDATE effect_requests SET
                status = 'cancelled_after_dispatch',
                result_hash = v_result_hash,
                provider_request_id = coalesce(v_receipt_id,
                                               v_att.provider_request_id),
                updated_at = now()
             WHERE effect_id = p_effect_id;
            UPDATE effect_attempts SET
                status = 'cancelled_after_dispatch',
                result_hash = v_result_hash,
                provider_request_id = coalesce(v_receipt_id,
                                               v_att.provider_request_id),
                completed_at = now()
             WHERE effect_id = p_effect_id AND attempt_no = p_attempt_no;
        END IF;

        -- Turn-level unknown closure: closer event + slot head CAS +
        -- closers history row, three-in-one, via the ONLY protected path.
        SELECT * INTO v_upd FROM v_turn_end_slot_update(
            p_session_id, v_turn, p_closer_event_type,
            p_closer_payload_canonical, v_res_bytes, p_supersedes_event_key,
            p_schema_version, p_canonicalizer_version,
            v_step_id, p_effect_id, p_attempt_no, p_command_id);
        IF v_upd.out_status = 'rejected' THEN
            RAISE EXCEPTION 'V8_REPAIR_SLOT_REJECTED:%', v_upd.out_code;
        END IF;

        -- ---- sibling re-aggregation (same transaction; effect-level
        -- repair NEVER creates an attempt — the step-level controlled
        -- recovery edges below create none either) ----
        SELECT * INTO v_agg FROM v_aggregate_step(v_step_id);

        IF v_agg.rule_no IN (1, 2) THEN
            -- Partial repair (unknown sibling remains) or a pending
            -- sibling: the step/session stay blocked / go waiting through
            -- the shared applier (counters recomputed).
            PERFORM v_apply_step_aggregation(
                p_session_id, v_step_id, v_agg.rule_no, v_agg.step_status,
                v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
                v_agg.closure_effect_ids, p_command_id, v_computed,
                p_write_session => NOT v_terminal);
        ELSIF v_agg.rule_no = 3 THEN
            -- G8b: the COMPLETE rule 3 (cancel-wins), replacing the G7c
            -- minimal repair-triggered arm. The shared judgment above
            -- derived the row uniquely — sticky family when the sticky latch
            -- is set or a request-family cancellation is present, provider
            -- family otherwise — and the shared applier runs the shared
            -- cancel closure sub-operation over the residual failed_retryable
            -- siblings (sticky: cancelled_after_dispatch + audit
            -- RETRY_SUPPRESSED_BY_CANCEL; provider: the controlled edge
            -- failed_retryable -> failed_terminal + RETRY_STOPPED_BY_CLOSURE),
            -- then writes the step/session cancel row from the derivation
            -- table. No turn/end derivation runs here: the repair closer
            -- appended above IS this turn's end (the protected slot update
            -- owns it — a second derivation MUST NOT run).
            PERFORM v_apply_step_aggregation(
                p_session_id, v_step_id, v_agg.rule_no, v_agg.step_status,
                v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
                v_agg.closure_effect_ids, p_command_id, v_computed,
                p_write_session => NOT v_terminal);
        ELSIF v_agg.rule_no IN (4, 5) THEN
            -- Rule 4 (a repair-proved failure closes the batch) and rule 5
            -- (the aggregation-completion edge: the last unknown cleared
            -- and the remaining retryable siblings satisfy retry_eligible
            -- — MUST NOT create any new attempt for a repaired effect).
            PERFORM v_apply_step_aggregation(
                p_session_id, v_step_id, v_agg.rule_no, v_agg.step_status,
                v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
                v_agg.closure_effect_ids, p_command_id, v_computed,
                p_write_session => NOT v_terminal);
        ELSE
            -- Rule 6 (all siblings terminal, none failed/cancelled): the
            -- success arms — decision_only closes the turn (step
            -- succeeded/closed through the shared judgment, session
            -- ready); a tools plan aggregates back to ready,stage=decision
            -- with plan_hash frozen (the blocked_unknown_effect -> ready
            -- controlled recovery edge); a final_tools tools batch
            -- terminalizes succeeded/closed.
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
                updated_at = now()
             WHERE st.step_id = v_step_id;
            IF v_batch_kind = 'decision' THEN
                IF v_do THEN
                    UPDATE steps SET status = 'succeeded', stage = 'closed',
                                     outcome_code = 'SUCCEEDED',
                                     closed_at = now(), updated_at = now()
                     WHERE step_id = v_step_id;
                    IF NOT v_terminal THEN
                        SELECT * INTO v_fin FROM v_session_finalize(
                            p_session_id, v_turn);
                        IF NOT v_fin.closed THEN
                            RAISE EXCEPTION
                                'INFRA_PROTOCOL_VIOLATION: turn-close judgment '
                                'failed after a repaired decision_only success '
                                '(session %, turn %)', p_session_id, v_turn;
                        END IF;
                    END IF;
                ELSE
                    -- Controlled recovery edge: ready, stage=decision with
                    -- plan_hash frozen at settlement (tools seal LATER).
                    UPDATE steps SET status = 'ready', updated_at = now()
                     WHERE step_id = v_step_id;
                END IF;
            ELSE
                IF v_step.final_tools IS TRUE THEN
                    UPDATE steps SET status = 'succeeded', stage = 'closed',
                                     outcome_code = 'SUCCEEDED',
                                     closed_at = now(), updated_at = now()
                     WHERE step_id = v_step_id;
                ELSE
                    RAISE EXCEPTION
                        'INFRA_PROTOCOL_VIOLATION: repaired tools batch is '
                        'all-terminal without failure/cancel but lacks the '
                        'final_tools mark (session %, step %)',
                        p_session_id, v_step_id;
                END IF;
            END IF;
            -- Aggregation NEVER derives completed: rule 6 targets ready;
            -- only finish_session completes. G12: on a drain-terminal
            -- session the step closes but the terminal state stays.
            IF NOT v_terminal THEN
                UPDATE sessions SET state = 'ready', updated_at = now()
                 WHERE session_id = p_session_id;
            END IF;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM LIKE 'V8_REPAIR_SLOT_REJECTED:%' THEN
            -- The settlement + slot work rolled back to the savepoint:
            -- zero control state; the classified rejection receipt and its
            -- binding persist in the outer transaction.
            v_rej_code := substring(SQLERRM from 'V8_REPAIR_SLOT_REJECTED:(.*)');
            v_receipt := v8_reject_command(
                p_session_id, p_command_id, 'repair', v_computed,
                'rejected_mismatch', v_rej_code,
                'turn-end slot chain validation failed; settlement rolled '
                'back, zero control state');
            RETURN QUERY SELECT 'rejected_mismatch'::text, v_rej_code, v_receipt;
            RETURN;
        END IF;
        RAISE;
    END;

    v_receipt := jsonb_build_object(
        'command_kind', 'repair',
        'command_id', p_command_id,
        'idempotent', false,
        'classification', v_class,
        'effect_id', p_effect_id,
        'attempt_no', p_attempt_no,
        'settled_status', v_resolution,
        'effect_code', v_code,
        'retry_stop_reason', v_reason,
        'result_hash', v_result_hash,
        'resolution_digest', encode(v_digest, 'hex'),
        'closer', jsonb_build_object(
            'event_key', v_upd.out_closer_event_key,
            'seq', v_upd.out_event_seq,
            'event_type', p_closer_event_type,
            'supersedes_event_key', p_supersedes_event_key),
        'slot', jsonb_build_object(
            'head_event_key', v_upd.out_head_event_key,
            'slot_status', v_upd.out_slot_status,
            'version', v_upd.out_slot_version),
        'step_status', (SELECT st.status FROM steps st
                         WHERE st.step_id = v_step_id),
        'session_state', (SELECT s.state FROM sessions s
                           WHERE s.session_id = p_session_id),
        'failure_code', (SELECT s.failure_code FROM sessions s
                          WHERE s.session_id = p_session_id));

    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value,
        first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'repair', 'canonical_request_hash',
            v_computed, 'accepted', NULL, v_receipt::text,
            v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;
