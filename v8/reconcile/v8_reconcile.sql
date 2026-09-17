-- v8 G18 (reconcile stage): the §3.1.1 driver-switch positive protocol —
-- begin_switch / finish_switch via one `v_reconcile` command entry — plus
-- the §1.1 versioned driver switch capability declarations.
--
-- Scope (plan docs/plans/v8-remaining-milestones-plan-2026-09-16.md G18):
--   * driver_switch_capabilities — the created-immutable per-driver
--     declaration (spec L32: `supported` runs the full mode protocol,
--     `unsupported` makes begin_switch return UNSUPPORTED before any
--     mode/fence/switch-intent mutation). The compat stage keeps its own
--     manifest-declared surface and ROUTES supported drivers into the
--     shared switch core defined here (deviation A83 convergence; there is
--     exactly ONE switch-guard implementation).
--   * session_switch_intents — the switch intent as a companion table
--     (the sessions closed 15-column list is frozen; the intent MUST NOT
--     become a sessions column). At most one intent per session; the
--     finish_switch transaction clears it in place.
--   * v_begin_switch_core / v_finish_switch_core — the shared switch
--     mechanics (four-point safety guard, quiescing entry, CAS barrier,
--     one-shot epoch advance). Capability adjudication belongs to the
--     CALLERS (the native v_reconcile consults the table above; the compat
--     entry consults its manifest) so no second guard implementation
--     exists.
--   * v_reconcile — the unified command entry: adjudicate → envelope CAS
--     (driver/epoch/mode/fence; any mismatch is DRIVER_EPOCH_STALE with
--     zero control state) → valid current lease (the authorization basis;
--     the closed grant capability list has no 'reconcile' entry and the
--     recovery lease IS the switch authorization) → action dispatch.
--
-- Lock order: the session control row first (position 1, taken inside
-- v8_command_adjudicate), the switch-intent row after it. The switch
-- commands never touch turn_end_slot or compact rows (a switch entry does
-- not terminalize a session; the G17 terminal-transaction abort fires from
-- the terminalizing commands themselves).
--
-- ISOLATION_UNSUPPORTED ruling (plan open item ⑤): the reconcile entry is
-- NOT a post-lock rescan protocol (it locks the session row once and
-- judges the frozen control state under it), so the §4 isolation gate does
-- NOT apply — asserted by the G18 gate with a READ COMMITTED positive
-- control and recorded in the deviation ledger.

-- ---------------------------------------------------------------------------
-- 1. driver_switch_capabilities (spec L32, P0A frozen).
-- ---------------------------------------------------------------------------
CREATE TABLE driver_switch_capabilities (
    driver           text PRIMARY KEY,
    switch_capability text NOT NULL
                     CONSTRAINT driver_switch_capability_check
                     CHECK (switch_capability IN ('supported', 'unsupported')),
    declared_at      timestamptz NOT NULL DEFAULT now()
);

-- Created-immutable: the declaration is frozen at creation (spec L32);
-- any UPDATE or DELETE is a database-level violation.
CREATE FUNCTION v8_driver_capability_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'driver_switch_capabilities rows are created-immutable '
        '(driver %)', OLD.driver;
END;
$$;
CREATE TRIGGER trg_driver_capability_immutable
BEFORE UPDATE OR DELETE ON driver_switch_capabilities
FOR EACH ROW EXECUTE FUNCTION v8_driver_capability_immutable();

-- ---------------------------------------------------------------------------
-- 2. session_switch_intents (companion table; sessions keeps its frozen
--    closed column list).
-- ---------------------------------------------------------------------------
CREATE TABLE session_switch_intents (
    session_id            uuid PRIMARY KEY REFERENCES sessions(session_id),
    -- Unique versioned switch identity: SHA-256 over the domain-separated
    -- label, the session, the target driver and the create-time fence (the
    -- CAS snapshot the intent was persisted under).
    switch_identity       text NOT NULL UNIQUE,
    target_driver         text NOT NULL,
    created_session_fence bigint NOT NULL CHECK (created_session_fence >= 1),
    created_driver        text NOT NULL,
    created_driver_epoch  bigint NOT NULL CHECK (created_driver_epoch >= 1),
    created_by_command_id text NOT NULL,
    created_at            timestamptz NOT NULL DEFAULT now()
);

-- Unique versioned switch identity, compact-style framing:
-- SHA-256("v8:switch-intent@v1" NUL len8(session_id) session_id
--         len8(target_driver) target_driver len8(fence) fence)
-- (len8 = 8-byte big-endian segment length; segments are the UTF-8 texts).
CREATE FUNCTION v_switch_intent_identity(
    p_session_id uuid, p_target_driver text, p_fence bigint
) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT encode(sha256(
        convert_to('v8:switch-intent@v1', 'UTF8') || '\x00'::bytea
        || int8send(length(p_session_id::text)::bigint)
        || convert_to(p_session_id::text, 'UTF8')
        || int8send(length(p_target_driver)::bigint)
        || convert_to(p_target_driver, 'UTF8')
        || int8send(length(p_fence::text)::bigint)
        || convert_to(p_fence::text, 'UTF8')), 'hex');
$$;

-- ---------------------------------------------------------------------------
-- 3. v_begin_switch_core — the shared begin_switch mechanics (guards +
--    quiescing entry). The CALLER has already adjudicated the command
--    envelope (receipt replay / binding conflict / hash mismatch) and the
--    switch capability; p_computed is the canonical request hash.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_begin_switch_core(
    p_session_id uuid, p_command_id text, p_computed text,
    p_target_driver text, p_lease_owner text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_identity text;
BEGIN
    -- Session row already locked by the caller (position 1).
    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id;

    -- Lease authorization (shared with the finish core so the compat
    -- routing enforces the same contract): the caller must hold the
    -- current valid session lease. begin_switch revokes it in its success
    -- transaction; zero control state on denial.
    IF v_sess.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_sess.lease_until IS NULL OR v_sess.lease_until <= now() THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_stale', 'NO_VALID_LEASE',
            format('begin_switch requires the current valid session lease '
                   '(row owner %s, caller %s)',
                   coalesce(v_sess.lease_owner, 'NULL'),
                   coalesce(p_lease_owner, 'NULL')));
        RETURN QUERY SELECT 'rejected_stale'::text,
                           'NO_VALID_LEASE'::text, v_receipt;
        RETURN;
    END IF;

    -- Terminal sessions never enter a new switch (terminal matrix (d) only
    -- ever finishes an EXISTING intent).
    IF v_sess.state IN ('completed', 'failed', 'cancelled') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch', 'SESSION_TERMINAL',
            format('begin_switch on a terminal session (state %s)',
                   v_sess.state));
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SESSION_TERMINAL'::text, v_receipt;
        RETURN;
    END IF;

    -- One intent per session (D1); a second begin is a stable conflict.
    IF EXISTS (SELECT 1 FROM session_switch_intents i
                WHERE i.session_id = p_session_id) THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch',
            'SWITCH_IN_PROGRESS',
            'a switch intent already exists for this session');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SWITCH_IN_PROGRESS'::text, v_receipt;
        RETURN;
    END IF;

    -- The four-point safety guard (§3.1.1 mode table, frozen). Any hit is
    -- a STABLE SWITCH_DEFERRED with zero control state — mode/fence/switch
    -- intent untouched, the lease NOT revoked; the caller retries once the
    -- condition clears through seal/dispatch/completion/repair.
    IF EXISTS (SELECT 1 FROM steps st
                WHERE st.session_id = p_session_id
                  AND st.status = 'ready' AND st.stage = 'decision') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch', 'SWITCH_DEFERRED',
            'guard (i): an unsealed tools plan (step ready, stage=decision)');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SWITCH_DEFERRED'::text, v_receipt;
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM effect_requests er
                JOIN steps st ON st.step_id = er.step_id
               WHERE st.session_id = p_session_id
                 AND st.stage = 'decision'
                 AND er.status = 'dispatch_started') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch', 'SWITCH_DEFERRED',
            'guard (ii): an in-flight stage=decision effect');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SWITCH_DEFERRED'::text, v_receipt;
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM effect_requests er
                WHERE er.session_id = p_session_id
                  AND er.status IN ('planned', 'ready')) THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch', 'SWITCH_DEFERRED',
            'guard (iii): an undispatched ready effect');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SWITCH_DEFERRED'::text, v_receipt;
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM steps st
                WHERE st.session_id = p_session_id
                  AND st.stage = 'decision'
                  AND st.status NOT IN ('succeeded', 'failed_terminal',
                                        'cancelled')) THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch', 'SWITCH_DEFERRED',
            'guard (iv): a non-terminal decision step that may still '
            'produce a tools plan (incl. blocked_unknown_effect)');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SWITCH_DEFERRED'::text, v_receipt;
        RETURN;
    END IF;

    -- Guards pass: same-transaction effects (§3.1.1 mode table) — persist
    -- the unique switch identity + target driver, bump the session fence,
    -- revoke the CURRENT COORDINATION lease (checkpoint/lost rules apply;
    -- valid JOB leases are NOT auto-revoked — D4), mode -> quiescing.
    v_identity := v_switch_intent_identity(p_session_id, p_target_driver,
                                           v_sess.session_fence);
    INSERT INTO session_switch_intents(
        session_id, switch_identity, target_driver, created_session_fence,
        created_driver, created_driver_epoch, created_by_command_id)
    VALUES (p_session_id, v_identity, p_target_driver,
            v_sess.session_fence, v_sess.driver, v_sess.driver_epoch,
            p_command_id);
    UPDATE sessions SET
        driver_mode = 'quiescing',
        session_fence = v_sess.session_fence + 1,
        lease_owner = NULL,
        lease_until = NULL,
        lease_purpose = NULL,
        updated_at = now()
     WHERE session_id = p_session_id;

    v_receipt := jsonb_build_object(
        'command_kind', 'reconcile', 'command_id', p_command_id,
        'action', 'begin_switch',
        'switch_identity', v_identity,
        'target_driver', p_target_driver,
        'session_fence', v_sess.session_fence + 1,
        'driver_mode', 'quiescing',
        'coordination_lease_revoked', true,
        'job_leases_revoked', false);
    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value,
        first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            p_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'reconcile',
            'canonical_request_hash', p_computed, 'accepted', NULL,
            v_receipt::text, v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- 4. v_finish_switch_core — the shared finish_switch mechanics (CAS
--    barrier + the one-shot epoch advance). The caller has adjudicated
--    the envelope; the intent row supplies the frozen target driver.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_finish_switch_core(
    p_session_id uuid, p_command_id text, p_computed text,
    p_lease_owner text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_intent session_switch_intents%ROWTYPE;
    v_receipt jsonb;
    v_step_status text;
BEGIN
    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id;

    -- Lease authorization (the recovery claim taken during quiescing —
    -- including the terminal matrix (d) restricted claim).
    IF v_sess.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_sess.lease_until IS NULL OR v_sess.lease_until <= now() THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_stale', 'NO_VALID_LEASE',
            format('finish_switch requires the current valid session lease '
                   '(row owner %s, caller %s)',
                   coalesce(v_sess.lease_owner, 'NULL'),
                   coalesce(p_lease_owner, 'NULL')));
        RETURN QUERY SELECT 'rejected_stale'::text,
                           'NO_VALID_LEASE'::text, v_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_intent FROM session_switch_intents i
     WHERE i.session_id = p_session_id FOR UPDATE;
    IF NOT FOUND THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch',
            'SWITCH_INTENT_MISSING',
            'finish_switch requires an existing switch intent');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SWITCH_INTENT_MISSING'::text, v_receipt;
        RETURN;
    END IF;

    -- The CAS barrier (§3.1.1 mode table quiescing -> active, frozen).
    -- Every item unmet keeps the session quiescing with zero control
    -- state (stable SWITCH_DEFERRED); the closure entries (repair /
    -- reconcile result receipt / recovery takeover) are the means that
    -- clear the items — the barrier never inverts against them.
    IF EXISTS (SELECT 1 FROM effect_requests er
                WHERE er.session_id = p_session_id
                  AND er.status IN ('planned', 'ready', 'dispatch_started',
                                    'failed_retryable')) THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch', 'SWITCH_DEFERRED',
            'barrier: a non-terminal old-epoch effect remains');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SWITCH_DEFERRED'::text, v_receipt;
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM effect_requests er
                WHERE er.session_id = p_session_id
                  AND er.status = 'unknown_outcome') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch', 'SWITCH_DEFERRED',
            'barrier: an unresolved unknown remains (repair it first)');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SWITCH_DEFERRED'::text, v_receipt;
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM effect_requests er
                WHERE er.session_id = p_session_id
                  AND er.lease_owner IS NOT NULL
                  AND er.lease_until > now()) THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch', 'SWITCH_DEFERRED',
            'barrier: a valid old job lease remains (wait for expiry or '
            'operator FORCE_JOB_TAKEOVER)');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SWITCH_DEFERRED'::text, v_receipt;
        RETURN;
    END IF;
    IF v_sess.active_step_id IS NOT NULL THEN
        SELECT st.status INTO v_step_status FROM steps st
         WHERE st.step_id = v_sess.active_step_id;
        IF v_step_status IS NULL
           OR v_step_status NOT IN ('succeeded', 'failed_terminal',
                                    'cancelled') THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id,
                'reconcile', p_computed, 'rejected_mismatch',
                'SWITCH_DEFERRED',
                'barrier: active_step_id is set to a non-terminal step');
            RETURN QUERY SELECT 'rejected_mismatch'::text,
                               'SWITCH_DEFERRED'::text, v_receipt;
            RETURN;
        END IF;
    END IF;
    IF EXISTS (SELECT 1 FROM steps st
                WHERE st.session_id = p_session_id
                  AND st.status = 'ready' AND st.stage = 'decision') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', p_computed, 'rejected_mismatch', 'SWITCH_DEFERRED',
            'barrier: an unsealed tools plan remains');
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'SWITCH_DEFERRED'::text, v_receipt;
        RETURN;
    END IF;

    -- Barrier met: the one-shot epoch advance (§3.1.1). Writes the target
    -- driver, driver_epoch+1, session_fence+1, clears the lease and the
    -- switch intent — and ONLY those: state, failure_code, the sticky
    -- cancellation latch and active_step_id keep their values (a terminal
    -- session stays terminal — matrix (d); the session is never
    -- unconditionally returned to ready).
    UPDATE sessions SET
        driver = v_intent.target_driver,
        driver_epoch = v_sess.driver_epoch + 1,
        driver_mode = 'active',
        session_fence = v_sess.session_fence + 1,
        lease_owner = NULL,
        lease_until = NULL,
        lease_purpose = NULL,
        updated_at = now()
     WHERE session_id = p_session_id;
    DELETE FROM session_switch_intents WHERE session_id = p_session_id;

    v_receipt := jsonb_build_object(
        'command_kind', 'reconcile', 'command_id', p_command_id,
        'action', 'finish_switch',
        'switch_identity', v_intent.switch_identity,
        'old_driver', v_sess.driver,
        'new_driver', v_intent.target_driver,
        'old_driver_epoch', v_sess.driver_epoch,
        'new_driver_epoch', v_sess.driver_epoch + 1,
        'session_fence', v_sess.session_fence + 1,
        'driver_mode', 'active',
        'session_state', (SELECT s.state FROM sessions s
                           WHERE s.session_id = p_session_id));
    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value,
        first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            p_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind,
        receipt_key_value, outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'reconcile',
            'canonical_request_hash', p_computed, 'accepted', NULL,
            v_receipt::text, v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- 5. v_reconcile — the unified command entry (§3.1.1). Envelope carries
--    the current driver/driver_epoch/driver_mode/session_fence CAS legs;
--    any envelope mismatch is a stable DRIVER_EPOCH_STALE with zero
--    control state (plan D2). Authorization = a valid current session
--    lease owned by the caller (begin_switch revokes the coordination
--    lease in its success transaction; finish_switch runs under the
--    recovery claim taken during quiescing — including the terminal
--    matrix (d) restricted claim).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_reconcile(
    p_session_id uuid, p_command_id text,
    p_action text,
    p_driver text, p_driver_epoch bigint,
    p_expected_mode text, p_session_fence bigint,
    p_lease_owner text,
    p_target_driver text DEFAULT NULL,
    p_declared_hash text DEFAULT NULL,
    p_payload_canonical text DEFAULT NULL
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_computed text := v_sha256_hex(coalesce(p_payload_canonical, ''));
    v_adj record;
    v_sess sessions%ROWTYPE;
    v_receipt jsonb;
    v_cap driver_switch_capabilities%ROWTYPE;
BEGIN
    SELECT * INTO v_adj FROM v8_command_adjudicate(
        p_session_id, p_command_id, 'reconcile',
        p_payload_canonical, p_declared_hash);
    IF v_adj.adj_kind <> 'execute' THEN
        RETURN QUERY SELECT v_adj.adj_outcome, v_adj.adj_code, v_adj.adj_receipt;
        RETURN;
    END IF;

    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id;

    -- Envelope CAS (driver/epoch/mode/fence): zero control state.
    IF p_driver IS DISTINCT FROM v_sess.driver
       OR p_driver_epoch IS DISTINCT FROM v_sess.driver_epoch
       OR p_expected_mode IS DISTINCT FROM v_sess.driver_mode
       OR p_session_fence IS DISTINCT FROM v_sess.session_fence THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', v_computed, 'rejected_stale', 'DRIVER_EPOCH_STALE',
            format('envelope driver/epoch/mode/fence does not match the '
                   'session control row (driver %s/%s, epoch %s/%s, mode '
                   '%s/%s, fence %s/%s)',
                   coalesce(p_driver, 'NULL'), v_sess.driver,
                   coalesce(p_driver_epoch::text, 'NULL'),
                   v_sess.driver_epoch::text,
                   coalesce(p_expected_mode, 'NULL'), v_sess.driver_mode,
                   coalesce(p_session_fence::text, 'NULL'),
                   v_sess.session_fence::text));
        RETURN QUERY SELECT 'rejected_stale'::text,
                           'DRIVER_EPOCH_STALE'::text, v_receipt;
        RETURN;
    END IF;

    -- Unknown action: stable rejection, zero control state (D2).
    IF p_action NOT IN ('begin_switch', 'finish_switch') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id,
            'reconcile', v_computed, 'rejected_mismatch', 'UNKNOWN_ACTION',
            format('unknown reconcile action %L', p_action));
        RETURN QUERY SELECT 'rejected_mismatch'::text,
                           'UNKNOWN_ACTION'::text, v_receipt;
        RETURN;
    END IF;

    -- begin_switch capability: UNSUPPORTED before any mode/fence/intent
    -- mutation (spec L32 / Conformance 11 (c)). A missing declaration
    -- fails closed to UNSUPPORTED.
    IF p_action = 'begin_switch' THEN
        SELECT * INTO v_cap FROM driver_switch_capabilities c
         WHERE c.driver = v_sess.driver;
        IF NOT FOUND OR v_cap.switch_capability = 'unsupported' THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id,
                'reconcile', v_computed, 'rejected_mismatch', 'UNSUPPORTED',
                format('driver %s declared driver_switch_capability=%s '
                       '(created-immutable); begin_switch refused before '
                       'any mode/fence/switch-intent mutation',
                       v_sess.driver,
                       CASE WHEN FOUND THEN v_cap.switch_capability
                            ELSE 'undeclared' END));
            RETURN QUERY SELECT 'rejected_mismatch'::text,
                               'UNSUPPORTED'::text, v_receipt;
            RETURN;
        END IF;
        IF p_target_driver IS NULL OR p_target_driver = '' THEN
            v_receipt := v8_reject_command(p_session_id, p_command_id,
                'reconcile', v_computed, 'rejected_mismatch',
                'TARGET_DRIVER_REQUIRED',
                'begin_switch requires a target_driver');
            RETURN QUERY SELECT 'rejected_mismatch'::text,
                               'TARGET_DRIVER_REQUIRED'::text, v_receipt;
            RETURN;
        END IF;
    END IF;

    -- Lease authorization lives INSIDE the shared cores (begin/finish) so
    -- the compat routing enforces the identical contract; nothing further
    -- to check at the entry.

    IF p_action = 'begin_switch' THEN
        RETURN QUERY SELECT * FROM v_begin_switch_core(
            p_session_id, p_command_id, v_computed, p_target_driver,
            p_lease_owner);
        RETURN;
    END IF;
    RETURN QUERY SELECT * FROM v_finish_switch_core(
        p_session_id, p_command_id, v_computed, p_lease_owner);
END;
$$;
