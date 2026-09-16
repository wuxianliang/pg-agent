-- v8 G13: P0C dsh-compat host-agnostic contract surface.
--
-- Scope declaration (frozen by the G13 task / plan
-- docs/plans/v8-p1-grant-generation-p0c-plan-2026-09-16.md): this file is
-- the HOST-INDEPENDENT half of the P0C dsh-compat contract only --
--   1. compat_adapter_manifests (section 5.2 two capability dimensions,
--      immutable after creation, explicit compat-only scope lists);
--   2. the unified audit command v_compat_unmapped_audit (section 3.1.2
--      command table row `compat_unmapped_audit` + section 5.1 preamble);
--   3. the mandatory negative driver-switch entry v_compat_begin_switch
--      (Conformance 11 (c): `unsupported` -> stable UNSUPPORTED before any
--      mode/fence/switch-intent mutation; the positive switch machinery is
--      explicitly deferred -- see the deviation ledger G13 block);
--   4. the fork-cutoff acceptance twins v_compat_fork_cutoff_stable /
--      v_compat_fork (Conformance 11 (a) three assertions; the fork command
--      itself belongs to the G10 grant stage -- this branch does not have
--      it, so the G13 gate validates the frozen cutoff-stability judgment
--      through these acceptance twins, see the deviation ledger);
--   5. the two-dimension capability matrix logic v_compat_matrix_blocked +
--      the GUC-seamed participation read v_compat_participation (the G9b
--      `v8.stream_window_exhausted` precedent -- the GUC channel drives
--      MATRIX LOGIC TESTS ONLY and can never mark a real-I/O-layer row
--      green; the real dispatch_interception value can only come from the
--      section 5.2 pre-verification of the pinned DSH package, which is
--      blocked -- see v8/compat/pinned_host_manifest.json).
--
-- Everything real-I/O (the actual Node compat loop, section 5.2
-- pre-verification, pinned five-piece values) is blocked and lives in the
-- explicit blocked list -- it MUST NOT be faked through the GUC seam.
--
-- Loaded LAST in SQL_LOAD_ORDER; depends only on the schema/keys/events
-- foundations and the slice/grant STUB surface (table names and existing
-- columns + the three-argument v_grant_valid signature; deviation A56) --
-- no G10/G11 object is referenced (this branch predates their merge; after
-- the merge the full grant model replaces the stub behind the same names).
--
-- Source: docs/designs/v8-dev.md sections 5 / 5.1 / 5.2, P0C (line 823),
-- Conformance 11/12/16 (lines 851/852/856); digests s31b-command-table.md
-- section 2.0/2.5 (`compat_unmapped_audit` row), s2-planes-grants.md.

-- ---------------------------------------------------------------------------
-- 1. compat adapter manifests (section 5.2 "缩小支持面必须写进 adapter
--    manifest" + section 1.1 driver_switch_capability, created immutable)
-- ---------------------------------------------------------------------------
CREATE TABLE compat_adapter_manifests (
    adapter_id              text PRIMARY KEY,
    -- The compat driver identity this adapter binds; a session driven by
    -- this driver is compat-hosted and its unmapped-audit caller must be
    -- this adapter.
    driver                  text NOT NULL,
    -- Dimension 1: dispatch_interception in {sync_before_io, after_io_only,
    -- none}; an UNKNOWN value IS `none`. The pinned host's value is NULL +
    -- note until the section 5.2 pre-verification resolves it (unresolved
    -- items MUST NOT let the compat contract be declared passed).
    dispatch_interception   text
        CONSTRAINT compat_manifest_dispatch_check
        CHECK (dispatch_interception IN
               ('sync_before_io', 'after_io_only', 'none')),
    dispatch_note           text,
    -- Dimension 2: declared at creation, immutable afterwards.
    driver_switch_capability text NOT NULL
        CONSTRAINT compat_manifest_switch_check
        CHECK (driver_switch_capability IN ('supported', 'unsupported')),
    -- A compat-only declaration MUST act on EXPLICIT plugin / fixture
    -- lists (section 5.2 last paragraph); dropping unsupported events
    -- outside these lists is forbidden (the unmapped-audit path is then
    -- mandatory and fails the fixture).
    compat_only_plugins     jsonb NOT NULL DEFAULT '[]'::jsonb,
    compat_only_fixtures    jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at              timestamptz NOT NULL DEFAULT now(),
    -- NULL value requires a note; a resolved value forbids one.
    CONSTRAINT compat_manifest_note_pairing CHECK (
        (dispatch_interception IS NULL AND dispatch_note IS NOT NULL)
        OR (dispatch_interception IS NOT NULL AND dispatch_note IS NULL))
);

CREATE FUNCTION v8_compat_manifests_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'compat_adapter_manifests rows are immutable after creation '
        '(both capability dimensions are created-immutable declarations); '
        're-register a new adapter identity instead';
END;
$$;

CREATE TRIGGER trg_compat_manifests_immutable
BEFORE UPDATE OR DELETE ON compat_adapter_manifests
FOR EACH ROW EXECUTE FUNCTION v8_compat_manifests_immutable();

-- JSON array of strings (the explicit-list shape the compat-only
-- declaration requires).
CREATE FUNCTION v_compat_is_string_array(p_v jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    SELECT p_v IS NOT NULL
       AND jsonb_typeof(p_v) = 'array'
       AND NOT EXISTS (
           SELECT 1 FROM jsonb_array_elements(p_v) e
            WHERE jsonb_typeof(e) <> 'string'
               OR length(e #>> '{}') = 0);
$$;

-- Controlled registration: the only write path. Validates the closed
-- sets, the NULL+note pairing and the explicit-list shape, then inserts.
CREATE FUNCTION v_compat_manifest_register(
    p_adapter_id text, p_driver text,
    p_dispatch_interception text, p_dispatch_note text,
    p_driver_switch_capability text,
    p_compat_only_plugins jsonb, p_compat_only_fixtures jsonb
) RETURNS boolean
LANGUAGE plpgsql AS $$
BEGIN
    IF p_adapter_id IS NULL OR length(p_adapter_id) = 0
       OR p_driver IS NULL OR length(p_driver) = 0 THEN
        RAISE EXCEPTION 'adapter_id and driver are required (canonical identities)';
    END IF;
    IF p_dispatch_interception IS NOT NULL
       AND p_dispatch_interception NOT IN
           ('sync_before_io', 'after_io_only', 'none') THEN
        RAISE EXCEPTION 'dispatch_interception must be in {sync_before_io, after_io_only, none} or NULL+note (unresolved)';
    END IF;
    IF (p_dispatch_interception IS NULL AND p_dispatch_note IS NULL)
       OR (p_dispatch_interception IS NOT NULL AND p_dispatch_note IS NOT NULL) THEN
        RAISE EXCEPTION 'an unresolved dispatch_interception requires a note; a resolved value forbids one';
    END IF;
    IF p_driver_switch_capability NOT IN ('supported', 'unsupported') THEN
        RAISE EXCEPTION 'driver_switch_capability must be in {supported, unsupported} (created-immutable declaration)';
    END IF;
    IF NOT v_compat_is_string_array(p_compat_only_plugins)
       OR NOT v_compat_is_string_array(p_compat_only_fixtures) THEN
        RAISE EXCEPTION 'compat-only declarations must be explicit arrays of plugin/fixture identity strings';
    END IF;
    INSERT INTO compat_adapter_manifests(
        adapter_id, driver, dispatch_interception, dispatch_note,
        driver_switch_capability, compat_only_plugins, compat_only_fixtures)
    VALUES (p_adapter_id, p_driver, p_dispatch_interception, p_dispatch_note,
            p_driver_switch_capability, p_compat_only_plugins,
            p_compat_only_fixtures);
    RETURN true;
END;
$$;

-- "丢弃不支持事件仍宣称 portable 被拒" (section 5.2 last paragraph): a
-- fixture declared compat-only (its unsupported events are dropped, it is
-- excluded from portable comparison) can never be claimed portable. FALSE
-- from this predicate is the rejection fact the P0C reporter consumes.
CREATE FUNCTION v_compat_portable_claim_ok(
    p_adapter_id text, p_claimed_fixtures jsonb
) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT NOT EXISTS (
        SELECT 1
          FROM compat_adapter_manifests m,
               jsonb_array_elements(m.compat_only_fixtures) cof,
               jsonb_array_elements(p_claimed_fixtures) cf
         WHERE m.adapter_id = p_adapter_id
           AND cof #>> '{}' = cf #>> '{}');
$$;

-- ---------------------------------------------------------------------------
-- 2. compat_unmapped_audit (unified command; spec section 3.1.2 command
--    table + section 5.1 preamble + Conformance 16 second half)
-- ---------------------------------------------------------------------------
-- Envelope: the five unified fields plus the four compat-specific ones the
-- frozen row demands -- adapter identity, fixture digest, the unknown DSH
-- type's canonical identity and the payload hash. The computed hash covers
-- the full canonical request (built by the shared Python canonical
-- profile; SQL recomputes v_sha256_hex over the canonical text).
--
-- Write set: ONE compat/unmapped audit event (normal seq allocation,
-- event_key = non-stream database-internal derivation -- key layer (1)(b))
-- + receipt/binding. Zero control state (no effect/step/lease/fence/epoch/
-- cancellation mutation; the seq allocator, receipts and mandated audit
-- metadata are the sanctioned exceptions). "使 fixture 失败" is an
-- acceptance-report fact (audit persistence IS the failure marker), not a
-- control-state change. MUST NOT write any effect semantic-result event --
-- structural: this function inserts compat/unmapped only.
CREATE FUNCTION v_compat_unmapped_audit(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint,
    p_declared_hash text, p_payload_canonical text,
    p_adapter_identity text, p_fixture_digest text,
    p_dsh_type_canonical_identity text, p_payload_hash text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_adapter compat_adapter_manifests.adapter_id%TYPE;
    v_payload jsonb;
    v_payload_text text;
    v_evkey text;
    v_seq bigint;
BEGIN
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'compat_unmapped_audit',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s
     WHERE s.session_id = p_session_id FOR UPDATE;

    -- Envelope driver/epoch guard (unified contract; the quiescing
    -- heartbeat downgrade does not apply to this command).
    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'compat_unmapped_audit', v_computed, 'rejected_stale',
            'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session control row');
        RETURN QUERY SELECT 'rejected_stale'::text,
                           'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;

    -- Envelope field checks (the four compat-specific fields are
    -- mandatory non-empty strings).
    IF p_adapter_identity IS NULL OR length(p_adapter_identity) = 0
       OR p_fixture_digest IS NULL OR length(p_fixture_digest) = 0
       OR p_dsh_type_canonical_identity IS NULL
       OR length(p_dsh_type_canonical_identity) = 0
       OR p_payload_hash IS NULL OR length(p_payload_hash) = 0 THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'compat_unmapped_audit', v_computed, 'rejected_mismatch',
            'ENVELOPE_FIELD_MISSING',
            'adapter identity, fixture digest, unknown-type canonical identity and payload hash are all required');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'ENVELOPE_FIELD_MISSING'::text, v_receipt;
        RETURN;
    END IF;

    -- Caller binding: the session's driver must be a compat driver with a
    -- manifest row, and the envelope adapter identity must be exactly the
    -- bound adapter. (Stage-local code name -- the grant/driver-chain
    -- subject resolution is P1; deviation ledger G13 block.)
    SELECT m.adapter_id INTO v_adapter
      FROM compat_adapter_manifests m
     WHERE m.driver = v_sess.driver;
    IF v_adapter IS NULL OR v_adapter IS DISTINCT FROM p_adapter_identity THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'compat_unmapped_audit', v_computed, 'rejected_mismatch',
            'ADAPTER_IDENTITY_MISMATCH',
            'caller is not the compat adapter bound to this session''s driver');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'ADAPTER_IDENTITY_MISMATCH'::text, v_receipt;
        RETURN;
    END IF;

    -- The audit event. event_class=audit, normal seq allocation, key
    -- derived per the non-stream internal pattern (occurrence identity =
    -- (command_id, 0)).
    v_payload := jsonb_build_object(
        'adapter_identity', p_adapter_identity,
        'fixture_digest', p_fixture_digest,
        'dsh_type_canonical_identity', p_dsh_type_canonical_identity,
        'payload_hash', p_payload_hash);
    v_payload_text := v_payload::text;
    v_evkey := v_nonstream_event_key(p_session_id, 'compat/unmapped',
                                     p_command_id, 0,
                                     v_sha256_hex(v_payload_text));
    SELECT s.next_seq INTO v_seq FROM sessions s
     WHERE s.session_id = p_session_id;
    INSERT INTO session_events(
        seq, session_id, event_type, event_class, schema_version,
        canonicalizer_version, event_key, turn_id, step_id, effect_id,
        payload, payload_hash, semantic_input_ordinal,
        internal_semantic_ordinal, attempt_no, command_id, batch_item_ordinal)
    VALUES (
        v_seq, p_session_id, 'compat/unmapped', 'audit', 'sv@1', 'canon@1',
        v_evkey, NULL, NULL, NULL, v_payload_text,
        v_sha256_hex(v_payload_text), NULL, NULL, NULL, p_command_id, 0);
    UPDATE sessions SET next_seq = v_seq + 1, updated_at = now()
     WHERE session_id = p_session_id;

    v_receipt := jsonb_build_object(
        'command_kind', 'compat_unmapped_audit',
        'command_id', p_command_id,
        'outcome', 'accepted',
        'fixture', v_payload,
        'events', jsonb_build_array(jsonb_build_object(
            'event_type', 'compat/unmapped',
            'event_key', v_evkey,
            'seq', v_seq)));
    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            v_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'compat_unmapped_audit',
            'canonical_request_hash', v_computed, 'accepted', NULL,
            v_receipt::text, v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- 3. driver-switch entry, negative-only (Conformance 11 (c), frozen):
--    begin_switch on an `unsupported` driver MUST stably return
--    UNSUPPORTED BEFORE any mode, fence or switch-intent mutation. The
--    positive switch machinery (SWITCH_DEFERRED guards, quiescing,
--    finish_switch barrier) is explicitly deferred (plan "明确不做");
--    a `supported` declaration therefore lands on a stable stage-local
--    not-implemented rejection -- still zero mutation.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_compat_begin_switch(
    p_session_id uuid, p_command_id text,
    p_driver text, p_driver_epoch bigint,
    p_declared_hash text, p_payload_canonical text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(p_payload_canonical);
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_switch compat_adapter_manifests.driver_switch_capability%TYPE;
    v_found boolean;
BEGIN
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'reconcile',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s
     WHERE s.session_id = p_session_id FOR UPDATE;

    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', v_computed, 'rejected_stale', 'DRIVER_EPOCH_STALE',
            'envelope driver/driver_epoch does not match the session control row');
        RETURN QUERY SELECT 'rejected_stale'::text,
                           'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;

    SELECT m.driver_switch_capability INTO v_switch
      FROM compat_adapter_manifests m
     WHERE m.driver = v_sess.driver;
    v_found := FOUND;
    IF NOT v_found THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', v_computed, 'rejected_mismatch',
            'DRIVER_MANIFEST_MISSING',
            'session driver has no compat adapter manifest declaration');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'DRIVER_MANIFEST_MISSING'::text, v_receipt;
        RETURN;
    END IF;

    IF v_switch = 'unsupported' THEN
        -- The frozen mandatory negative: UNSUPPORTED before any mode,
        -- fence or switch-intent mutation (this function executes no
        -- mutation at all before returning).
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', v_computed, 'rejected_mismatch', 'UNSUPPORTED',
            'driver declared driver_switch_capability=unsupported '
            '(created-immutable); begin_switch refused before any '
            'mode/fence/switch-intent mutation');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'UNSUPPORTED'::text, v_receipt;
        RETURN;
    END IF;

    v_receipt := v8_reject_command(p_session_id, p_command_id,
        'reconcile', v_computed, 'rejected_mismatch',
        'SWITCH_PROTOCOL_NOT_IMPLEMENTED',
        'driver declared driver_switch_capability=supported but the '
        'positive switch machinery (SWITCH_DEFERRED guards, quiescing, '
        'finish_switch barrier) is deferred -- see the deviation ledger');
    RETURN QUERY SELECT 'rejected_mismatch'::text,
                       'SWITCH_PROTOCOL_NOT_IMPLEMENTED'::text, v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- 4. fork-cutoff acceptance twins (Conformance 11 (a), frozen at spec
--    line 711). The fork COMMAND belongs to the G10 grant stage; on this
--    branch the G13 gate validates the frozen cutoff-stability judgment
--    and prefix-inheritance semantics through these twins. Merge note in
--    the deviation ledger: after G10 merges, its real fork command and
--    these twins MUST agree on every judgment vector of this gate.
--
--    Frozen guard: `parent_through_seq` MUST point at a stable cutoff --
--    within seq <= cutoff there MUST be no unclosed turn (including turns
--    with unresolved unknown or pending non-terminal effects); stability
--    is judged by the events WITHIN the cutoff and their resolutions and
--    MUST NOT borrow parent repairs that happen AFTER the cutoff.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_compat_fork_cutoff_stable(
    p_session_id uuid, p_through_seq bigint
) RETURNS TABLE(stable boolean, reason text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_bad_turn uuid;
    v_bad_unknown uuid;
    v_bad_effect uuid;
BEGIN
    IF p_through_seq IS NULL OR p_through_seq < 0 THEN
        RETURN QUERY SELECT false, 'cutoff seq must be >= 0';
        RETURN;
    END IF;

    -- (a) an in-range turn without an in-range turn/end (covers "pending
    -- non-terminal effect of an unclosed turn": aggregation closes the
    -- turn together with its effects, so a closed turn has no pending
    -- effects; the explicit pending-effect leg below is defense).
    SELECT t INTO v_bad_turn
      FROM (SELECT DISTINCT turn_id AS t
              FROM session_events
             WHERE session_id = p_session_id
               AND seq <= p_through_seq
               AND turn_id IS NOT NULL) turns
     WHERE NOT EXISTS (
               SELECT 1 FROM session_events e2
                WHERE e2.session_id = p_session_id
                  AND e2.turn_id = turns.t
                  AND e2.event_type = 'turn/end'
                  AND e2.seq <= p_through_seq)
     LIMIT 1;
    IF v_bad_turn IS NOT NULL THEN
        RETURN QUERY SELECT false,
            'unclosed turn within the cutoff (pending non-terminal effect or open turn)';
        RETURN;
    END IF;

    -- (b) an in-range provisional unknown end whose turn has no closer
    -- with event_seq <= cutoff. A parent repair after the cutoff does NOT
    -- resolve it (stability MUST NOT borrow post-cutoff resolutions).
    SELECT e.turn_id INTO v_bad_unknown
      FROM session_events e
     WHERE e.session_id = p_session_id
       AND e.seq <= p_through_seq
       AND e.event_type = 'turn/end'
       AND (e.payload::jsonb ->> 'outcome') = 'unknown'
       AND NOT EXISTS (
               SELECT 1 FROM turn_end_closers c
                WHERE c.session_id = p_session_id
                  AND c.turn_id = e.turn_id
                  AND c.event_seq <= p_through_seq)
     LIMIT 1;
    IF v_bad_unknown IS NOT NULL THEN
        RETURN QUERY SELECT false,
            'unresolved unknown within the cutoff (a parent repair after the cutoff does not count)';
        RETURN;
    END IF;

    -- (c) defense: an in-range turn still holding a pending effect
    -- (non-terminal statuses) whose end is not within the cutoff.
    SELECT er.effect_id INTO v_bad_effect
      FROM effect_requests er
      JOIN steps st ON st.step_id = er.step_id
     WHERE er.session_id = p_session_id
       AND er.status IN ('planned', 'ready', 'dispatch_started',
                         'unknown_outcome')
       AND EXISTS (SELECT 1 FROM session_events e3
                    WHERE e3.session_id = p_session_id
                      AND e3.turn_id = st.turn_id
                      AND e3.seq <= p_through_seq)
       AND NOT EXISTS (SELECT 1 FROM session_events e4
                        WHERE e4.session_id = p_session_id
                          AND e4.turn_id = st.turn_id
                          AND e4.event_type = 'turn/end'
                          AND e4.seq <= p_through_seq)
     LIMIT 1;
    IF v_bad_effect IS NOT NULL THEN
        RETURN QUERY SELECT false,
            'pending non-terminal effect within an unclosed turn of the cutoff';
        RETURN;
    END IF;

    RETURN QUERY SELECT true, NULL::text;
END;
$$;

-- Minimal fork acceptance twin: stable cutoff -> child session created
-- with the event prefix inherited (logical history only -- the child
-- inherits NO control state and no step/effect/attempt/lease/fence/
-- cancellation/compact object; those live only in the parent). Unstable
-- cutoff -> stable FORK_CUTOFF_UNSTABLE refusal, parent control state
-- untouched (the caller may retry with an earlier stable cutoff).
--
-- Not a receipt command: fork is not in the unified command list (its
-- command surface is frozen by the G10 stage that owns the real command);
-- this twin returns a structured outcome without touching the receipt
-- namespace. Deviation ledger G13 block.
CREATE FUNCTION v_compat_fork(
    p_parent_session_id uuid, p_child_session_id uuid,
    p_through_seq bigint, p_driver text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_stable boolean;
    v_reason text;
    v_count bigint;
    v_next bigint;
BEGIN
    SELECT s.stable, s.reason INTO v_stable, v_reason
      FROM v_compat_fork_cutoff_stable(p_parent_session_id, p_through_seq) s;
    IF NOT v_stable THEN
        RETURN jsonb_build_object(
            'outcome', 'rejected_mismatch',
            'code', 'FORK_CUTOFF_UNSTABLE',
            'detail', v_reason,
            'parent_control_state', 'untouched');
    END IF;

    INSERT INTO sessions(session_id, driver)
    VALUES (p_child_session_id, p_driver);
    INSERT INTO session_events(
        seq, session_id, event_type, event_class, schema_version,
        canonicalizer_version, event_key, turn_id, step_id, effect_id,
        payload, payload_hash, semantic_input_ordinal,
        internal_semantic_ordinal, attempt_no, command_id,
        batch_item_ordinal, stream_id, chunk_index, observation_ordinal)
    SELECT seq, p_child_session_id, event_type, event_class,
           schema_version, canonicalizer_version, event_key, turn_id,
           step_id, effect_id, payload, payload_hash,
           semantic_input_ordinal, internal_semantic_ordinal, attempt_no,
           command_id, batch_item_ordinal, stream_id, chunk_index,
           observation_ordinal
      FROM session_events
     WHERE session_id = p_parent_session_id
       AND seq <= p_through_seq;
    GET DIAGNOSTICS v_count = ROW_COUNT;
    SELECT coalesce(max(seq), 0) + 1 INTO v_next
      FROM session_events WHERE session_id = p_child_session_id;
    UPDATE sessions SET next_seq = v_next, updated_at = now()
     WHERE session_id = p_child_session_id;

    RETURN jsonb_build_object(
        'outcome', 'accepted',
        'child_session_id', p_child_session_id,
        'parent_through_seq', p_through_seq,
        'inherited_event_count', v_count,
        'inherited_control_state', 'none');
END;
$$;

-- ---------------------------------------------------------------------------
-- 5. two-dimension capability matrix logic (section 5.2 capability
--    matrix, the single authority) + the GUC seam.
-- ---------------------------------------------------------------------------
-- Pure judgment over the two dimensions. Blocked subcase ids (verbatim
-- rows of the frozen matrix):
--   dispatch dimension (each row requires dispatch_interception =
--   sync_before_io; a degraded runtime is blocked, its database-layer
--   sibling runs but MUST NOT substitute):
--     c3-real-dispatch-unknown-recovery
--     c5-real-cancel-unknown-classification
--     c6-real-cancel-linearization
--     c11-real-inflight-switch-closure
--     c13-real-workspace-lost-inflight
--     c14-real-revoke-dispatch
--     c15-real-cancel-unknown-fixture
--     real-io-unlisted-forms
--   switch dimension (requires driver_switch_capability = supported):
--     c11-db-switch-positive -- blocked, and MUST be replaced by the
--     mandatory negative c11-db-unsupported-negative (never exempt).
--   Fork-like independent subcases are never blocked by either dimension.
CREATE FUNCTION v_compat_matrix_blocked(
    p_dispatch_interception text, p_driver_switch text
) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_dispatch text := coalesce(p_dispatch_interception, 'none');
    v_switch text := p_driver_switch;
    v_blocked text[] := ARRAY[]::text[];
    v_mandated text[] := ARRAY[]::text[];
    v_dispatch_rows text[] := ARRAY[
        'c3-real-dispatch-unknown-recovery',
        'c5-real-cancel-unknown-classification',
        'c6-real-cancel-linearization',
        'c11-real-inflight-switch-closure',
        'c13-real-workspace-lost-inflight',
        'c14-real-revoke-dispatch',
        'c15-real-cancel-unknown-fixture',
        'real-io-unlisted-forms'];
BEGIN
    -- Unknown dispatch value IS none (frozen).
    IF v_dispatch NOT IN ('sync_before_io', 'after_io_only', 'none') THEN
        v_dispatch := 'none';
    END IF;
    IF v_dispatch <> 'sync_before_io' THEN
        v_blocked := v_blocked || v_dispatch_rows;
    END IF;
    IF v_switch = 'unsupported' THEN
        v_blocked := v_blocked || ARRAY['c11-db-switch-positive'];
        v_mandated := ARRAY['c11-db-unsupported-negative'];
    END IF;
    RETURN jsonb_build_object(
        'dispatch_interception', v_dispatch,
        'driver_switch', v_switch,
        'blocked', to_jsonb(v_blocked),
        'mandated_negative', to_jsonb(v_mandated));
END;
$$;

-- Participation read for one manifest row. The effective dispatch value
-- falls back to 'none' while the stored value is NULL+note (unresolved).
--
-- GUC SEAM (the G9b `v8.stream_window_exhausted` precedent):
--   v8.compat_dispatch_interception / v8.compat_driver_switch, when set
--   (transaction-local), override the dimension values feeding the MATRIX
--   LOGIC ONLY. This channel exists so the four capability combinations
--   of the frozen union rules are testable against an immutable manifest.
--   It MUST NOT be used to fake a capability: the function computes
--   blocked sets and mandated negatives only -- it structurally cannot
--   mark a real-I/O-layer row green, and the real dispatch_interception
--   value can only ever come from the section 5.2 pre-verification of the
--   pinned DSH package (currently blocked; see
--   v8/compat/pinned_host_manifest.json).
CREATE FUNCTION v_compat_participation(p_adapter_id text) RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE
    m compat_adapter_manifests%ROWTYPE;
    v_dispatch text;
    v_switch text;
    v_overrides text[] := ARRAY[]::text[];
BEGIN
    SELECT * INTO m FROM compat_adapter_manifests
     WHERE adapter_id = p_adapter_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('error', 'adapter manifest not found');
    END IF;
    v_dispatch := coalesce(m.dispatch_interception, 'none');
    v_switch := m.driver_switch_capability;
    IF coalesce(current_setting('v8.compat_dispatch_interception', true), '')
       IN ('sync_before_io', 'after_io_only', 'none') THEN
        v_dispatch := current_setting('v8.compat_dispatch_interception');
        v_overrides := v_overrides
            || ARRAY['v8.compat_dispatch_interception'];
    END IF;
    IF coalesce(current_setting('v8.compat_driver_switch', true), '')
       IN ('supported', 'unsupported') THEN
        v_switch := current_setting('v8.compat_driver_switch');
        v_overrides := v_overrides || ARRAY['v8.compat_driver_switch'];
    END IF;
    RETURN jsonb_build_object(
        'adapter_id', m.adapter_id,
        'driver', m.driver,
        'dispatch_interception_effective', v_dispatch,
        'dispatch_unresolved', m.dispatch_interception IS NULL,
        'driver_switch', v_switch,
        'guc_overrides_used', to_jsonb(v_overrides),
        'matrix', v_compat_matrix_blocked(v_dispatch, v_switch));
END;
$$;
