-- ===========================================================================
-- v8 G17 — compact: the three controlled commands (compact_lock /
-- compact_finalize / compact_abort)
-- ===========================================================================
--
-- Contract: docs/designs/v8-dev.md §3.3 (the three commands, the frozen
-- seven-step location order, the terminal-replay五步 order, the terminal-
-- transaction controlled abort) and the frozen `compactions` DDL (§4 table
-- list, digest s33 §1.1). This file is appended at the END of
-- `v8/load.py`'s SQL_LOAD_ORDER (no mid-order insertion): every lower stage
-- therefore keeps its file set, and the compact ownership checks that reach
-- into `v_prepare_step` / `v_seal_batch` / `v_dispatch_effect` MUST guard
-- with `to_regclass('compactions')` (deviation A51 precedent) because those
-- functions also run inside databases whose load set stops before this
-- file.
--
-- `internal_op_audits` (the `compact_terminal_abort` carrier) is created by
-- the G16 audit stage at load position 3; this stage only CONSUMES it and
-- MUST NOT re-create it (the plan's cross-milestone ruling).
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 1. compactions — the compact control-state table (DDL frozen)
-- ---------------------------------------------------------------------------
CREATE TABLE compactions (
    session_id       uuid NOT NULL REFERENCES sessions(session_id),
    compaction_id    text NOT NULL,
    base_seq         bigint NOT NULL CHECK (base_seq >= 0),
    through_seq      bigint NOT NULL CHECK (through_seq >= base_seq),
    status           text NOT NULL
                     CONSTRAINT compactions_status_check
                     CHECK (status IN ('locked', 'finalized', 'aborted')),
    owner_fence      bigint NOT NULL CHECK (owner_fence >= 1),
    lease_owner      text,
    lease_until      timestamptz,
    result_identity  text,
    abort_identity   text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    -- State-condition binding (database-enforced, frozen): `finalized` iff
    -- result_identity set and abort_identity NULL; `aborted` iff the
    -- reverse; `locked` iff both NULL.
    CONSTRAINT compactions_state_binding_check
        CHECK ((status = 'locked'    AND result_identity IS NULL
                                     AND abort_identity IS NULL)
            OR (status = 'finalized' AND result_identity IS NOT NULL
                                     AND abort_identity IS NULL)
            OR (status = 'aborted'   AND abort_identity IS NOT NULL
                                     AND result_identity IS NULL)),
    CONSTRAINT compactions_session_compaction_key
        UNIQUE (session_id, compaction_id)
);

-- "Current compact lock" = the session's single status='locked' row. `idle`
-- is a session-level state (no locked row), never a row value.
CREATE UNIQUE INDEX compactions_one_locked_per_session
    ON compactions (session_id) WHERE status = 'locked';

-- base_seq / through_seq freeze at creation and are immutable afterwards.
CREATE FUNCTION v8_compactions_frozen_range() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.base_seq IS DISTINCT FROM OLD.base_seq
       OR NEW.through_seq IS DISTINCT FROM OLD.through_seq
       OR NEW.session_id IS DISTINCT FROM OLD.session_id
       OR NEW.compaction_id IS DISTINCT FROM OLD.compaction_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'v8: compactions.base_seq/through_seq and the row '
                        'identity are frozen at compact_lock creation and '
                        'immutable (spec §3.3); got a divergent UPDATE';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_compactions_frozen_range
BEFORE UPDATE ON compactions
FOR EACH ROW EXECUTE FUNCTION v8_compactions_frozen_range();

-- Terminal rows (finalized/aborted) are the audit and replay locator and
-- MUST NOT be deleted; a locked row is released by transitioning it to a
-- terminal state, never by deleting it.
CREATE FUNCTION v8_compactions_no_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'v8: compactions rows MUST NOT be deleted (spec §3.3: '
                    'finalized/aborted rows are the audit and replay locator; '
                    'the lock is released by transitioning to a terminal '
                    'state, never by DELETE)';
END;
$$;

CREATE TRIGGER trg_compactions_no_delete
BEFORE DELETE ON compactions
FOR EACH ROW EXECUTE FUNCTION v8_compactions_no_delete();

-- ---------------------------------------------------------------------------
-- 2. shared helpers
-- ---------------------------------------------------------------------------

-- The compact authorization precheck (frozen location order step 1,
-- highest priority): the caller MUST hold a valid `compact` capability
-- grant and the target session MUST belong to that authorization context.
-- The rejection lives OUTSIDE the command receipt namespace — it writes an
-- independent authorization-denial audit row, never a receipt or binding —
-- and does not leak the existence of an unknown/unauthorized target.
CREATE FUNCTION v_compact_authorize(
    p_session_id uuid, p_caller_subject text, p_caller_driver text,
    p_caller_epoch bigint
) RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE
    v_grant text;
BEGIN
    v_grant := v_grant_find_valid(p_session_id, 'compact', p_caller_subject,
                                  p_caller_driver, p_caller_epoch);
    IF v_grant IS NULL THEN
        PERFORM v_authz_denial(coalesce(p_caller_subject, p_caller_driver,
                                        'unknown'),
                               'compact', 'no valid compact grant for the '
                               'caller context');
        RETURN false;
    END IF;
    RETURN true;
END;
$$;

-- The compact ownership predicate consulted by the seal and dispatch paths
-- (frozen conflict matrix item 2): an active `locked` compact row rejects
-- the creation/seal/dispatch of an LLM effect with COMPACT_IN_PROGRESS.
-- The CALLERS guard this with to_regclass('compactions') (deviation A51
-- precedent) because those functions also run in databases whose load set
-- stops before this file.
CREATE FUNCTION v_compact_active(p_session_id uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM compactions c
                    WHERE c.session_id = p_session_id AND c.status = 'locked');
$$;

-- Allocate the next session seq inside the caller's session row lock.
CREATE FUNCTION v_compact_next_seq(p_session_id uuid) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_seq bigint;
BEGIN
    SELECT s.next_seq INTO v_seq FROM sessions s
     WHERE s.session_id = p_session_id FOR UPDATE;
    UPDATE sessions SET next_seq = v_seq + 1, updated_at = now()
     WHERE session_id = p_session_id;
    RETURN v_seq;
END;
$$;

-- The frozen `compaction_result_digest@v1` (spec §3 two-stage generation
-- step (2)): SHA-256 over the canonical bytes of the payload with the
-- self-referential fields {result_identity, event_key, abort_identity}
-- EXCLUDED from the view (N01: the exclusion breaks the circularity).
CREATE FUNCTION v_compaction_result_digest(p_payload jsonb) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    v_view jsonb;
BEGIN
    SELECT jsonb_object_agg(kv.key, kv.value) INTO v_view
      FROM jsonb_each(p_payload) kv
     WHERE kv.key NOT IN ('result_identity', 'event_key', 'abort_identity');
    RETURN v_sha256_hex(v_view::text);
END;
$$;

-- `compact_result_identity@v1` (spec §3, versioned portable identity).
CREATE FUNCTION v_compact_result_identity(
    p_session_id uuid, p_logical_cutoff_digest text,
    p_replacement_set_digest text
) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    -- identity = SHA-256("v8:compact-result@v1" NUL len8(session_id raw)
    --                    raw32(logical_cutoff_digest) raw32(replacement_set_digest))
    -- The session_id contributes its 16 RAW uuid bytes (len8 = 16).
    SELECT encode(sha256(convert_to('v8:compact-result@v1', 'UTF8')
                         || '\x00'::bytea
                         || int8send(16::bigint)
                         || uuid_send(p_session_id)
                         || decode(p_logical_cutoff_digest, 'hex')
                         || decode(p_replacement_set_digest, 'hex')),
                  'hex');
$$;

-- ---------------------------------------------------------------------------
-- 3. the three controlled commands
-- ---------------------------------------------------------------------------

-- compact_lock — the ONLY idle -> locked entry. Freezes base_seq/through_seq
-- (through_seq = the max allocated seq visible under the session row lock),
-- writes the compaction/start audit event and returns the compaction
-- identity. An active non-terminal LLM effect rejects with
-- COMPACT_BUSY_EFFECTS and zero control-state change.
CREATE FUNCTION v_compact_lock(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint,
    p_compaction_id text,
    p_declared_hash text, p_payload_canonical text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_seq bigint;
    v_through bigint;
    v_locked compactions%ROWTYPE;
    v_busy integer;
    v_evkey text;
    v_payload text;
BEGIN
    -- Step (1): authorization + session ownership, OUTSIDE the receipt
    -- namespace (no receipt/binding read or write on denial).
    IF NOT v_compact_authorize(p_session_id, NULL, p_driver, p_driver_epoch)
    THEN
        v_receipt := jsonb_build_object(
            'command_kind', 'compact_lock', 'command_id', p_command_id,
            'outcome', 'rejected_mismatch', 'code', 'GRANT_DENIED',
            'detail', 'compact authorization precheck denied the caller');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'GRANT_DENIED'::text,
                            v_receipt;
        RETURN;
    END IF;

    -- Steps (2)-(5): request key, receipt replay, binding conflict.
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'compact_lock',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id;
    IF v_sess.state IN ('completed', 'failed', 'cancelled') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'compact_lock', v_computed, 'rejected_mismatch', 'SESSION_TERMINAL',
            format('compact_lock on a terminal session (state %s)',
                   v_sess.state));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_TERMINAL'::text,
                            v_receipt;
        RETURN;
    END IF;

    -- (6b) an existing locked row for this session: the same compaction is
    -- an idempotent re-entry (the lock already holds); a different one is a
    -- parameter conflict.
    SELECT * INTO v_locked FROM compactions c
     WHERE c.session_id = p_session_id AND c.status = 'locked';
    IF FOUND THEN
        IF v_locked.compaction_id = p_compaction_id THEN
            v_receipt := jsonb_build_object(
                'command_kind', 'compact_lock', 'command_id', p_command_id,
                'compaction_id', v_locked.compaction_id,
                'base_seq', v_locked.base_seq,
                'through_seq', v_locked.through_seq,
                'owner_fence', v_locked.owner_fence,
                'session_fence', v_sess.session_fence,
                'session_state', v_sess.state);
            INSERT INTO command_bindings(
                session_id, command_id, first_key_kind, first_key_value,
                first_outcome)
            VALUES (p_session_id, p_command_id, 'canonical_request_hash',
                    v_computed, 'accepted');
            INSERT INTO command_receipts(
                session_id, command_id, command_kind, receipt_key_kind,
                receipt_key_value, outcome, code, result_canonical, result_hash)
            VALUES (p_session_id, p_command_id, 'compact_lock',
                    'canonical_request_hash', v_computed, 'accepted', NULL,
                    v_receipt::text, v_sha256_hex(v_receipt::text));
            RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
            RETURN;
        END IF;
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'compact_lock', v_computed, 'rejected_mismatch',
            'IDEMPOTENCY_CONFLICT',
            'another compaction is already locked for this session');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                            'IDEMPOTENCY_CONFLICT'::text, v_receipt;
        RETURN;
    END IF;

    -- Frozen conflict matrix item (1): any non-terminal LLM effect rejects.
    SELECT count(*) INTO v_busy FROM effect_requests er
     WHERE er.session_id = p_session_id
       AND er.status IN ('planned', 'ready', 'dispatch_started');
    IF v_busy > 0 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'compact_lock', v_computed, 'rejected_mismatch',
            'COMPACT_BUSY_EFFECTS',
            format('%s non-terminal LLM effect(s) in flight', v_busy));
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                            'COMPACT_BUSY_EFFECTS'::text, v_receipt;
        RETURN;
    END IF;

    -- Freeze the range under the session row lock.
    SELECT s.next_seq - 1 INTO v_through FROM sessions s
     WHERE s.session_id = p_session_id;
    v_through := greatest(coalesce(v_through, 0), 0);

    INSERT INTO compactions(
        session_id, compaction_id, base_seq, through_seq, status,
        owner_fence, lease_owner, lease_until)
    VALUES (p_session_id, p_compaction_id, 0, v_through, 'locked',
            greatest(v_sess.session_fence, 1), p_driver,
            now() + interval '5 minutes');

    -- compaction/start audit event (§3.3: session_events, event_class=audit).
    v_payload := jsonb_build_object(
        'compaction_id', p_compaction_id,
        'base_seq', 0,
        'through_seq', v_through)::text;
    v_seq := v_compact_next_seq(p_session_id);
    v_evkey := v_nonstream_event_key(p_session_id, 'compaction/start',
                                     p_command_id, 0,
                                     v_sha256_hex(v_payload));
    INSERT INTO session_events(
        seq, session_id, event_type, event_class, schema_version,
        canonicalizer_version, event_key, turn_id, step_id, effect_id,
        payload, payload_hash, semantic_input_ordinal,
        internal_semantic_ordinal, attempt_no, command_id, batch_item_ordinal)
    VALUES (v_seq, p_session_id, 'compaction/start', 'audit', 'sv@1', 'canon@1',
            v_evkey, NULL, NULL, NULL, v_payload, v_sha256_hex(v_payload),
            NULL, NULL, NULL, p_command_id, 0);

    v_receipt := jsonb_build_object(
        'command_kind', 'compact_lock', 'command_id', p_command_id,
        'compaction_id', p_compaction_id,
        'base_seq', 0, 'through_seq', v_through,
        'owner_fence', greatest(v_sess.session_fence, 1),
        'start_event_key', v_evkey,
        'session_fence', v_sess.session_fence, 'session_state', v_sess.state);
    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'compact_lock',
            'canonical_request_hash', v_computed, 'accepted', NULL,
            v_receipt::text, v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- The terminal-replay five-step order (frozen) shared by finalize/abort:
-- lease requirement -> owner-fence stale -> parameter identity -> read-only
-- return. Returns a row describing the outcome; the callers turn it into a
-- receipt.
CREATE FUNCTION v_compact_terminal_replay(
    p_session_id uuid, p_command_id text, p_compaction_id text,
    p_owner_fence bigint, p_base_seq bigint, p_through_seq bigint,
    p_audit_key_kind text, p_audit_key_value text,
    p_payload_canonical text, p_declared_hash text
) RETURNS TABLE(kind text, outcome text, code text, receipt jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_row compactions%ROWTYPE;
BEGIN
    SELECT * INTO v_row FROM compactions c
     WHERE c.session_id = p_session_id AND c.compaction_id = p_compaction_id
       AND c.status IN ('finalized', 'aborted');
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'not_terminal'::text, NULL::text, NULL::text,
                            NULL::jsonb;
        RETURN;
    END IF;
    -- (3) owner fence stale takes priority over parameter disagreement.
    IF p_owner_fence IS DISTINCT FROM v_row.owner_fence THEN
        RETURN QUERY SELECT 'stale'::text, 'rejected_stale'::text,
            'STALE_COMPACT_FENCE'::text,
            v8_reject_command(p_session_id, p_command_id, 'compact',
                v_computed, 'rejected_stale', 'STALE_COMPACT_FENCE',
                'caller owner fence does not match the frozen terminal row');
        RETURN;
    END IF;
    -- (4) parameter identity: base_seq/through_seq must equal the frozen
    -- values; any disagreement is a fixed IDEMPOTENCY_CONFLICT.
    IF p_base_seq IS DISTINCT FROM v_row.base_seq
       OR p_through_seq IS DISTINCT FROM v_row.through_seq THEN
        RETURN QUERY SELECT 'conflict'::text, 'rejected_mismatch'::text,
            'IDEMPOTENCY_CONFLICT'::text,
            v8_reject_command(p_session_id, p_command_id, 'compact',
                v_computed, 'rejected_mismatch', 'IDEMPOTENCY_CONFLICT',
                'frozen base_seq/through_seq disagree with the terminal row');
        RETURN;
    END IF;
    -- (5) fully consistent: read-only return of the historical identity.
    RETURN QUERY SELECT 'replay'::text, 'accepted'::text, NULL::text,
        jsonb_build_object(
            'command_kind', 'compact',
            'command_id', p_command_id,
            'compaction_id', v_row.compaction_id,
            'status', v_row.status,
            'result_identity', v_row.result_identity,
            'abort_identity', v_row.abort_identity,
            'base_seq', v_row.base_seq, 'through_seq', v_row.through_seq,
            'owner_fence', v_row.owner_fence,
            'read_only_replay', true);
END;
$$;

-- compact_abort — the ONLY locked -> aborted path. Fenced CAS; releases the
-- lock back to idle (the row stays as the replay locator). Writes the
-- internal_op_audits `compact_terminal_abort` row and freezes its event_key
-- as abort_identity. MUST NOT produce a compaction result event.
CREATE FUNCTION v_compact_abort(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint,
    p_compaction_id text, p_owner_fence bigint,
    p_declared_hash text, p_payload_canonical text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_row compactions%ROWTYPE;
    v_rep record;
    v_receipt jsonb;
    v_abort_key text;
    v_ordinal bigint;
BEGIN
    IF NOT v_compact_authorize(p_session_id, NULL, p_driver, p_driver_epoch)
    THEN
        v_receipt := jsonb_build_object(
            'command_kind', 'compact_abort', 'command_id', p_command_id,
            'outcome', 'rejected_mismatch', 'code', 'GRANT_DENIED');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'GRANT_DENIED'::text,
                            v_receipt;
        RETURN;
    END IF;
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'compact_abort',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id;

    -- Terminal history replay (five-step order) for an already-terminal row.
    SELECT * INTO v_rep FROM v_compact_terminal_replay(
        p_session_id, p_command_id, p_compaction_id, p_owner_fence,
        (SELECT c.base_seq FROM compactions c
          WHERE c.session_id = p_session_id
            AND c.compaction_id = p_compaction_id),
        (SELECT c.through_seq FROM compactions c
          WHERE c.session_id = p_session_id
            AND c.compaction_id = p_compaction_id),
        'canonical_binding', v_computed, p_payload_canonical, p_declared_hash);
    IF v_rep.kind <> 'not_terminal' THEN
        RETURN QUERY SELECT v_rep.outcome, v_rep.code, v_rep.receipt;
        RETURN;
    END IF;

    SELECT * INTO v_row FROM compactions c
     WHERE c.session_id = p_session_id AND c.compaction_id = p_compaction_id
       AND c.status = 'locked';
    IF NOT FOUND THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'compact_abort', v_computed, 'rejected_mismatch',
            'IDEMPOTENCY_CONFLICT',
            'no locked compaction with that identity for this session');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                            'IDEMPOTENCY_CONFLICT'::text, v_receipt;
        RETURN;
    END IF;
    -- Fenced CAS: the caller owner fence must match the row.
    IF p_owner_fence IS DISTINCT FROM v_row.owner_fence THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'compact_abort', v_computed, 'rejected_stale',
            'STALE_COMPACT_FENCE',
            'caller owner fence does not match the locked row');
        RETURN QUERY SELECT 'rejected_stale'::text,
                            'STALE_COMPACT_FENCE'::text, v_receipt;
        RETURN;
    END IF;

    -- The internal sub-operation audit row: derive its event_key and freeze
    -- it as abort_identity. internal_op_audits carries no session_events seq
    -- and never enters the semantic/portable trace.
    SELECT coalesce(max(ioa.internal_op_ordinal), -1) + 1 INTO v_ordinal
      FROM internal_op_audits ioa
     WHERE ioa.parent_session_id = p_session_id
       AND ioa.parent_command_id = p_command_id;
    v_abort_key := v_sha256_hex('v8:compact_terminal_abort@v1|'
                                || p_session_id::text || '|'
                                || p_command_id || '|' || v_ordinal::text);
    INSERT INTO internal_op_audits(
        parent_session_id, parent_command_id, internal_op_ordinal,
        internal_op_kind, source_operation, target_identity, event_key,
        parent_receipt_ref)
    VALUES (p_session_id, p_command_id, v_ordinal, 'compact_terminal_abort',
            'compact_abort', p_compaction_id, v_abort_key,
            'canonical_request_hash:' || v_computed);

    UPDATE compactions SET
        status = 'aborted', abort_identity = v_abort_key, updated_at = now()
     WHERE session_id = p_session_id AND compaction_id = p_compaction_id;

    v_receipt := jsonb_build_object(
        'command_kind', 'compact_abort', 'command_id', p_command_id,
        'compaction_id', p_compaction_id,
        'abort_identity', v_abort_key,
        'base_seq', v_row.base_seq, 'through_seq', v_row.through_seq,
        'session_fence', v_sess.session_fence, 'session_state', v_sess.state);
    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'compact_abort',
            'canonical_request_hash', v_computed, 'accepted', NULL,
            v_receipt::text, v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- compact_finalize — the ONLY locked -> finalized path. Fenced CAS; writes
-- the compaction/end audit event with the two-stage generation order
-- (semantic payload -> digest -> event_key) and freezes result_identity.
CREATE FUNCTION v_compact_finalize(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint,
    p_compaction_id text, p_owner_fence bigint,
    p_declared_hash text, p_payload_canonical text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_row compactions%ROWTYPE;
    v_rep record;
    v_receipt jsonb;
    v_payload text;
    v_digest text;
    v_evkey text;
    v_seq bigint;
    v_identity text;
BEGIN
    IF NOT v_compact_authorize(p_session_id, NULL, p_driver, p_driver_epoch)
    THEN
        v_receipt := jsonb_build_object(
            'command_kind', 'compact_finalize', 'command_id', p_command_id,
            'outcome', 'rejected_mismatch', 'code', 'GRANT_DENIED');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'GRANT_DENIED'::text,
                            v_receipt;
        RETURN;
    END IF;
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'compact_finalize',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id;

    SELECT * INTO v_rep FROM v_compact_terminal_replay(
        p_session_id, p_command_id, p_compaction_id, p_owner_fence,
        (SELECT c.base_seq FROM compactions c
          WHERE c.session_id = p_session_id
            AND c.compaction_id = p_compaction_id),
        (SELECT c.through_seq FROM compactions c
          WHERE c.session_id = p_session_id
            AND c.compaction_id = p_compaction_id),
        'canonical_binding', v_computed, p_payload_canonical, p_declared_hash);
    IF v_rep.kind <> 'not_terminal' THEN
        RETURN QUERY SELECT v_rep.outcome, v_rep.code, v_rep.receipt;
        RETURN;
    END IF;

    SELECT * INTO v_row FROM compactions c
     WHERE c.session_id = p_session_id AND c.compaction_id = p_compaction_id
       AND c.status = 'locked';
    IF NOT FOUND THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'compact_finalize', v_computed, 'rejected_mismatch',
            'IDEMPOTENCY_CONFLICT',
            'no locked compaction with that identity for this session');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                            'IDEMPOTENCY_CONFLICT'::text, v_receipt;
        RETURN;
    END IF;
    IF p_owner_fence IS DISTINCT FROM v_row.owner_fence THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'compact_finalize', v_computed, 'rejected_stale',
            'STALE_COMPACT_FENCE',
            'caller owner fence does not match the locked row');
        RETURN QUERY SELECT 'rejected_stale'::text,
                            'STALE_COMPACT_FENCE'::text, v_receipt;
        RETURN;
    END IF;

    -- Frozen two-stage generation: semantic payload -> digest -> event_key.
    v_payload := jsonb_build_object(
        'compaction_id', p_compaction_id,
        'identity_class', 'compaction/end',
        'base_seq', v_row.base_seq,
        'through_seq', v_row.through_seq)::text;
    v_digest := v_compaction_result_digest(v_payload::jsonb);
    v_seq := v_compact_next_seq(p_session_id);
    v_evkey := v_nonstream_event_key(p_session_id, 'compaction/end',
                                     p_command_id, 0, v_digest);
    v_identity := v_compact_result_identity(
        p_session_id,
        v_sha256_hex('logical_cutoff@v1|' || p_session_id::text || '|'
                     || v_row.through_seq::text),
        v_sha256_hex('replacement_set@v1|' || v_row.base_seq::text || '|'
                     || v_row.through_seq::text));

    INSERT INTO session_events(
        seq, session_id, event_type, event_class, schema_version,
        canonicalizer_version, event_key, turn_id, step_id, effect_id,
        payload, payload_hash, semantic_input_ordinal,
        internal_semantic_ordinal, attempt_no, command_id, batch_item_ordinal)
    VALUES (v_seq, p_session_id, 'compaction/end', 'audit', 'sv@1', 'canon@1',
            v_evkey, NULL, NULL, NULL, v_payload, v_sha256_hex(v_payload),
            NULL, NULL, NULL, p_command_id, 0);

    UPDATE compactions SET
        status = 'finalized', result_identity = v_identity, updated_at = now()
     WHERE session_id = p_session_id AND compaction_id = p_compaction_id;

    v_receipt := jsonb_build_object(
        'command_kind', 'compact_finalize', 'command_id', p_command_id,
        'compaction_id', p_compaction_id,
        'result_identity', v_identity,
        'result_digest', v_digest,
        'end_event_key', v_evkey,
        'base_seq', v_row.base_seq, 'through_seq', v_row.through_seq,
        'session_fence', v_sess.session_fence, 'session_state', v_sess.state);
    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'compact_finalize',
            'canonical_request_hash', v_computed, 'accepted', NULL,
            v_receipt::text, v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;
