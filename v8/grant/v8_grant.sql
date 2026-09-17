-- v8 G10: authorization and generation domain — §2.1/§2.2 complete model.
--
-- Source of truth: docs/designs/v8-dev.md §2.1 (slice/grant planes),
-- §2.2 (workspace handles), §3.1.2 (chunk six-item attribution items (3)/(6),
-- heartbeat authorization field contract), §3.3 fork; digests
-- docs/analysis/v8-impl-digest/s2-planes-grants.md, s31a/s31b/s32a/s32b/s33.
--
-- Scope (per the G10 gate row):
--   * the G9a minimal slice/grant stub DDL is MIGRATED here from
--     v8/stream/v8_stream.sql §2–§4 and replaced by the complete §2.1 model
--     (column face unchanged — additions only; G13 depends on the stable
--     stub surface);
--   * parameter-level constraint evaluation (path prefix / command
--     whitelist / target set / TTL / max_bytes / max_rows);
--   * the authorization linearization point, mechanism (a): SELECT ... FOR
--     UPDATE in the fixed composite order (workspace_id, slice_id,
--     grant_id) ASC, nested inside the master order session → grant/slice
--     → generation → step → effect → attempt — delivered as the reusable
--     lock+judge suboperation v_grant_lock_judge that every G12 gate
--     consumes;
--   * controlled revocation (p_reason + same-transaction audit), the
--     operator channel, RLS tenant isolation, the stream registry (replaces
--     the A60 approximation), workspace_handles with the WORKSPACE_LOST
--     fail-closed drain, the pre-dispatch dual-table atomic sync
--     suboperation moved forward from v8_cancel.sql, and the minimal fork.
--
-- Loaded at SQL_LOAD_ORDER position 3: still BEFORE the events stage (the
-- public append path consumes the grant predicates) and before stream; the
-- pre-dispatch sync depends only on the schema table family (function
-- bodies are late-bound, so its position before the cancel stage that G11
-- will rewire carries no call-order risk).

-- ---------------------------------------------------------------------------
-- 0. sessions.workspace_id — tenant binding of the calling session
-- ---------------------------------------------------------------------------
-- §2.1 conjunct 2 freezes "grant、slice、调用 session 与目标资源的
-- workspace_id 租户一致". The grant↔slice half is enforced structurally by
-- the composite FK; the calling-session half needs the binding. Nullable,
-- default NULL: every existing gate session is a legacy unscoped session
-- (no tenant restriction — the A57-family downgrade), while G10 tests bind
-- workspaces explicitly. (Column addition outside the frozen 15-column
-- control-row list follows the A8 "contains" precedent.)
ALTER TABLE sessions ADD COLUMN workspace_id uuid;

-- Deterministic-enough UUID generation (no pgcrypto in this cluster).
CREATE FUNCTION v_uuidgen() RETURNS uuid
LANGUAGE sql VOLATILE AS $$
    SELECT (substr(md5(random()::text || clock_timestamp()::text ||
                       pg_backend_pid()::text), 1, 8) || '-' ||
            substr(md5(random()::text || clock_timestamp()::text), 9, 4) || '-' ||
            substr(md5(random()::text || clock_timestamp()::text), 13, 4) || '-' ||
            substr(md5(random()::text || clock_timestamp()::text), 17, 4) || '-' ||
            substr(md5(random()::text || clock_timestamp()::text), 21, 12))::uuid
$$;

-- ---------------------------------------------------------------------------
-- 1.1 slices (§2.1; migrated from v8_stream.sql §2, column face unchanged)
-- ---------------------------------------------------------------------------
CREATE TABLE slices (
    slice_id     uuid PRIMARY KEY,
    workspace_id uuid NOT NULL,
    name         text NOT NULL,
    kind         text NOT NULL
                 CONSTRAINT slices_kind_check
                 CHECK (kind IN ('corpus', 'fs_prefix', 'tool_set',
                                 'secret', 'workspace_exec')),
    -- Resource-set descriptor; content-frozen after creation. The §2.1
    -- slice-membership conjunct judges the accessed target against
    -- spec->'resources' when both the spec and the call carry one.
    spec         jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    revoked_at   timestamptz,
    CONSTRAINT slices_workspace_name_key UNIQUE (workspace_id, name),
    CONSTRAINT slices_workspace_slice_key UNIQUE (workspace_id, slice_id)
);

-- slice spec (with its workspace_id / slice_id binding fields) is immutable
-- after creation; content changes MUST go through revoke + recreate. No
-- UPDATE path is provided; the trigger is defense in depth. revoked_at is
-- monotonic: NULL -> non-NULL only.
CREATE FUNCTION v8_slices_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.slice_id IS DISTINCT FROM NEW.slice_id
       OR OLD.workspace_id IS DISTINCT FROM NEW.workspace_id
       OR OLD.name IS DISTINCT FROM NEW.name
       OR OLD.kind IS DISTINCT FROM NEW.kind
       OR OLD.spec IS DISTINCT FROM NEW.spec THEN
        RAISE EXCEPTION
            'slices content (slice_id, workspace_id, name, kind, spec) is '
            'immutable; revoke and re-create instead of UPDATE';
    END IF;
    IF OLD.revoked_at IS NOT NULL
       AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
        RAISE EXCEPTION 'slices.revoked_at is monotonic (NULL -> non-NULL only)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_slices_immutable
BEFORE UPDATE ON slices
FOR EACH ROW EXECUTE FUNCTION v8_slices_immutable();

-- ---------------------------------------------------------------------------
-- 1.2 grants (§2.1; migrated from v8_stream.sql §3, column face unchanged)
-- ---------------------------------------------------------------------------
CREATE TABLE grants (
    grant_id     text PRIMARY KEY,
    workspace_id uuid NOT NULL,
    slice_id     uuid NOT NULL,
    subject_kind text NOT NULL
                 CONSTRAINT grants_subject_kind_check
                 CHECK (subject_kind IN ('session', 'step',
                                         'plugin_identity', 'driver')),
    subject_id   text NOT NULL,
    capability   text NOT NULL
                 CONSTRAINT grants_capability_check
                 CHECK (capability IN ('recall', 'fold', 'env_read', 'env_write',
                                       'tool_resolve', 'authorize_effect',
                                       'effect_submit', 'event_append',
                                       'stream_ingest', 'process', 'network',
                                       'credential', 'compact')),
    -- Constraint object; the six dimensions are evaluated parameter-level
    -- by v_constraints_ok (§2.5 below) — schema self-chosen per the plan's
    -- largest-implementation-freedom ruling.
    constraints  jsonb,
    issued_at    timestamptz NOT NULL DEFAULT now(),
    not_before   timestamptz NOT NULL DEFAULT now(),
    -- Half-open validity interval [not_before, expires_at).
    expires_at   timestamptz NOT NULL,
    revoked_at   timestamptz,
    delegable    boolean NOT NULL DEFAULT false,
    CONSTRAINT grants_expiry_after_not_before CHECK (expires_at > not_before),
    -- Tenant consistency (invariant 12): grant.workspace_id = slice's,
    -- enforced by a COMPOSITE FOREIGN KEY, never by convention alone.
    CONSTRAINT grants_slice_tenant_fk
        FOREIGN KEY (workspace_id, slice_id)
        REFERENCES slices (workspace_id, slice_id)
);

CREATE FUNCTION v8_grants_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.grant_id IS DISTINCT FROM NEW.grant_id
       OR OLD.workspace_id IS DISTINCT FROM NEW.workspace_id
       OR OLD.slice_id IS DISTINCT FROM NEW.slice_id
       OR OLD.subject_kind IS DISTINCT FROM NEW.subject_kind
       OR OLD.subject_id IS DISTINCT FROM NEW.subject_id
       OR OLD.capability IS DISTINCT FROM NEW.capability
       OR OLD.constraints IS DISTINCT FROM NEW.constraints
       OR OLD.issued_at IS DISTINCT FROM NEW.issued_at
       OR OLD.not_before IS DISTINCT FROM NEW.not_before
       OR OLD.expires_at IS DISTINCT FROM NEW.expires_at
       OR OLD.delegable IS DISTINCT FROM NEW.delegable THEN
        RAISE EXCEPTION
            'grants content (grant_id, workspace_id, slice_id, subject_kind, '
            'subject_id, capability, constraints, issued_at, not_before, '
            'expires_at, delegable) is immutable; revoke and re-sign instead';
    END IF;
    IF OLD.revoked_at IS NOT NULL
       AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
        RAISE EXCEPTION 'grants.revoked_at is monotonic (NULL -> non-NULL only)';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_grants_immutable
BEFORE UPDATE ON grants
FOR EACH ROW EXECUTE FUNCTION v8_grants_immutable();

-- ---------------------------------------------------------------------------
-- 1.3 stream registry (replaces the A60 cross-session scan approximation)
-- ---------------------------------------------------------------------------
-- stream_id is attributable to the provider/adapter subject resolved
-- through the effect's bound grant (chunk six-item item (3)). The first
-- legally attributed chunk binds the stream to that subject; a foreign
-- provider reusing a registered stream is rejected CHUNK_ATTRIBUTION_INVALID.
-- Registered in the SAME transaction as the accepted chunk write, so any
-- later batch rejection rolls the registration back with the events.
CREATE TABLE stream_registry (
    stream_id    text PRIMARY KEY,
    workspace_id uuid NOT NULL,
    owner_subject text NOT NULL,
    effect_id    uuid,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 1.4 operator / capability audit (SECURITY DEFINER per-function audit) and
--     the independent authorization-denial audit row (receipt-namespace-out)
-- ---------------------------------------------------------------------------
CREATE TABLE grant_ops_audit (
    op_id        bigserial PRIMARY KEY,
    operator_id  text NOT NULL,
    action       text NOT NULL
                 CONSTRAINT grant_ops_audit_action_check
                 CHECK (action IN ('issue_slice', 'issue_grant', 'revoke_grant',
                                   'revoke_slice', 'ws_initialize',
                                   'ws_register_mutation', 'ws_fenced_publish',
                                   'ws_yield_checkpoint', 'ws_materialize',
                                   'ws_lost_drain', 'fork_session',
                                   -- G15: the §3.1.1 fail_session class (3)
                                   -- INFRA closure (same shape as
                                   -- ws_lost_drain, different failure code).
                                   'infra_drain',
                                   -- G19a: the §2 seam authorization-reject
                                   -- audit rows (namespace-outside, the G10
                                   -- authorization-denial pattern).
                                   'seam_denied', 'tool_resolve_denied')),
    target_id    text NOT NULL,
    workspace_id uuid,
    reason       text,
    details      jsonb,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- §3.1.2 授权前置拒绝 (outside the command receipt namespace): keyed by the
-- calling security context + target command identity; repeated denials of
-- the same context+command merge into ONE row (idempotent merge). The
-- occurrences counter is a plain column of this self-chosen table, not the
-- deferred three-key/occurrences fingerprint subtable family.
CREATE TABLE authz_denial_audits (
    authz_context text NOT NULL,
    target_command text NOT NULL,
    code          text NOT NULL DEFAULT 'GRANT_DENIED',
    detail        text,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    occurrences   bigint NOT NULL DEFAULT 1,
    PRIMARY KEY (authz_context, target_command)
);

CREATE FUNCTION v_authz_denial(
    p_context text, p_target text, p_detail text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO authz_denial_audits(authz_context, target_command, detail)
    VALUES (p_context, p_target, p_detail)
    ON CONFLICT (authz_context, target_command)
    DO UPDATE SET last_seen_at = now(),
                  occurrences = authz_denial_audits.occurrences + 1;
END;
$$;

-- ---------------------------------------------------------------------------
-- 2. effective-grant judgment (§2.1 full conjunction)
-- ---------------------------------------------------------------------------

-- 2.1 parameter-level constraint evaluation over the six frozen dimensions.
-- Self-chosen constraint schema (each key optional; a PRESENT constraint
-- with a MISSING parameter fails closed):
--   paths        — array of path prefixes; params.path must match one as a
--                  prefix (LIKE p || '%')
--   commands     — exact whitelist; params.command must be a member
--   targets      — target id set; params.target must be a member
--   ttl_seconds  — bounds the usable window relative to not_before
--                  ([not_before, min(expires_at, not_before + ttl)));
--                  evaluated in v_grant_lock_judge (needs the grant row)
--   max_bytes    — params.bytes <= max_bytes
--   max_rows     — params.rows  <= max_rows
CREATE FUNCTION v_constraints_ok(p_constraints jsonb, p_params jsonb)
RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT p_constraints IS NULL
       OR (
            (NOT (p_constraints ? 'paths')
             OR (p_params IS NOT NULL AND p_params ? 'path'
                 AND EXISTS (SELECT 1
                               FROM jsonb_array_elements_text(p_constraints->'paths') pfx
                              WHERE p_params->>'path' LIKE pfx || '%')))
       AND (NOT (p_constraints ? 'commands')
             OR (p_params IS NOT NULL AND p_params ? 'command'
                 AND (p_constraints->'commands') ? (p_params->>'command')))
       AND (NOT (p_constraints ? 'targets')
             OR (p_params IS NOT NULL AND p_params ? 'target'
                 AND (p_constraints->'targets') ? (p_params->>'target')))
       AND (NOT (p_constraints ? 'max_bytes')
             OR (p_params IS NOT NULL AND p_params ? 'bytes'
                 AND (p_params->>'bytes')::numeric
                     <= (p_constraints->>'max_bytes')::numeric))
       AND (NOT (p_constraints ? 'max_rows')
             OR (p_params IS NOT NULL AND p_params ? 'rows'
                 AND (p_params->>'rows')::numeric
                     <= (p_constraints->>'max_rows')::numeric))
       );
       -- NOTE: ttl_seconds is NOT judged here (it needs the grant row's
       -- not_before); v_grant_lock_judge evaluates it directly.
$$;

-- 2.2 slice-membership by target resource (§2.1 conjunct 3). The accessed
-- object must belong to slice.spec's resource set. Applies when BOTH the
-- spec declares 'resources' and the call carries a 'target'; RLS tenant
-- isolation never substitutes for this in-agent resource boundary.
CREATE FUNCTION v_slice_member(p_spec jsonb, p_params jsonb)
RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT (NOT (p_params IS NOT NULL AND p_params ? 'target'
                 AND p_spec IS NOT NULL AND p_spec ? 'resources'))
        OR ((p_spec->'resources') ? (p_params->>'target'))
$$;

-- 2.3 v_grant_valid — the frozen three-argument face (A56 frozen surface,
-- migrated verbatim from v8_stream.sql §4). Kept for the migrated
-- test_grant_stub assertions; new callers use the full entry below.
CREATE FUNCTION v_grant_valid(
    p_session_id uuid, p_grant_id text, p_capability text
) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(bool_or(
        g.revoked_at IS NULL
        AND s.revoked_at IS NULL
        AND g.not_before <= now()
        AND now() < g.expires_at
        AND g.capability = p_capability
        AND g.workspace_id = s.workspace_id
        AND (
            (g.subject_kind = 'session'
             AND g.subject_id = p_session_id::text)
            OR (g.subject_kind = 'driver'
                AND g.subject_id = (SELECT se.driver FROM sessions se
                                     WHERE se.session_id = p_session_id))
            OR (g.subject_kind = 'step'
                AND g.subject_id = (SELECT se.active_step_id::text FROM sessions se
                                     WHERE se.session_id = p_session_id))
            OR (g.subject_kind = 'plugin_identity'
                AND g.subject_id = (SELECT se.driver FROM sessions se
                                     WHERE se.session_id = p_session_id))
        )
    ), false)
    FROM grants g
    JOIN slices s ON s.slice_id = g.slice_id
    WHERE g.grant_id = p_grant_id;
$$;

-- 2.4 subject of a grant (the effect's bound provider/adapter). NULL when
-- the grant_id is NULL or unknown. (Migrated verbatim.)
CREATE FUNCTION v_grant_subject(p_grant_id text) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT g.subject_id FROM grants g WHERE g.grant_id = p_grant_id;
$$;

-- 2.5 v_grant_lock_judge — the reusable "lock + judge" suboperation.
--
-- Authorization linearization point, mechanism (a): every grant/slice row
-- of the judged set is locked SELECT ... FOR UPDATE in the frozen composite
-- order (workspace_id, slice_id, grant_id) ASC — a slice row (grant_id
-- NULLS FIRST) precedes its own grants — nested inside the master lock
-- order: the CALLER must already hold the session row lock (position 1)
-- before calling; this function never locks the session row itself.
-- Revocation transactions lock the same rows in the same order, so the
-- database commit order is the sole adjudicator: revoke commits first ->
-- subsequent checks see revoked and return GRANT_DENIED; the authorization/
-- dispatch transaction commits first -> the later revoke MUST NOT
-- retroactively cancel an already dispatch_started attempt (revocation
-- only flips grant/slice rows; nothing here touches attempts).
--
-- Subject resolution through the grant/driver chain (self-chosen rules):
--   session          — subject_id = the calling session, or the explicitly
--                      declared caller subject
--   driver           — subject_id = the session's current driver, the
--                      declared caller driver, or the declared caller subject
--   step             — subject_id = the session's active_step_id, or the
--                      declared caller subject
--   plugin_identity  — subject_id = the declared caller subject (the
--                      provider/adapter identity anchored by the effect's
--                      bound grant in the chunk path), or the session driver
-- Declared caller driver/epoch legs MUST match the session control row
-- (fail closed on mismatch).
CREATE FUNCTION v_grant_lock_judge(
    p_session_id uuid,
    p_grant_ids text[],
    p_capability text,
    p_caller_subject text DEFAULT NULL,
    p_caller_driver text DEFAULT NULL,
    p_caller_epoch bigint DEFAULT NULL,
    p_params jsonb DEFAULT NULL
) RETURNS TABLE(grant_id text, valid boolean, reason text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_row record;
BEGIN
    SELECT * INTO v_sess FROM sessions WHERE session_id = p_session_id;
    IF NOT FOUND THEN
        RETURN QUERY SELECT NULL::text, false, 'SESSION_NOT_FOUND';
        RETURN;
    END IF;

    -- Declared caller driver/epoch must match the session control row.
    IF (p_caller_driver IS NOT NULL
        AND p_caller_driver IS DISTINCT FROM v_sess.driver)
       OR (p_caller_epoch IS NOT NULL
           AND p_caller_epoch IS DISTINCT FROM v_sess.driver_epoch) THEN
        FOR v_row IN SELECT unnest(coalesce(p_grant_ids, ARRAY[]::text[])) AS gid LOOP
            RETURN QUERY SELECT v_row.gid, false, 'CALLER_DRIVER_MISMATCH';
        END LOOP;
        RETURN;
    END IF;

    -- Lock phase: (workspace_id, slice_id, grant_id) ASC, slices first.
    FOR v_row IN
        SELECT u.kind, u.slice_id, u.grant_id
          FROM (SELECT 'slice'::text AS kind, s.slice_id, NULL::text AS grant_id,
                       s.workspace_id AS ws, s.slice_id AS sl
                  FROM slices s
                 WHERE s.slice_id IN (SELECT g.slice_id FROM grants g
                                       WHERE g.grant_id = ANY(p_grant_ids))
                UNION ALL
                SELECT 'grant', g.slice_id, g.grant_id, g.workspace_id, g.slice_id
                  FROM grants g
                 WHERE g.grant_id = ANY(p_grant_ids)) u
         ORDER BY u.ws, u.sl, u.grant_id NULLS FIRST
    LOOP
        IF v_row.kind = 'slice' THEN
            PERFORM 1 FROM slices sc
             WHERE sc.slice_id = v_row.slice_id FOR UPDATE;
        ELSE
            PERFORM 1 FROM grants gr
             WHERE gr.grant_id = v_row.grant_id FOR UPDATE;
        END IF;
    END LOOP;

    -- Judge phase (rows re-read under the held locks).
    FOR v_row IN
        SELECT g.grant_id, g.workspace_id, g.slice_id, g.subject_kind,
               g.subject_id, g.capability, g.constraints,
               g.not_before, g.expires_at, g.revoked_at AS grant_revoked,
               g.delegable,
               s.revoked_at AS slice_revoked, s.spec
          FROM grants g
          JOIN slices s ON s.slice_id = g.slice_id
                       AND s.workspace_id = g.workspace_id
         WHERE g.grant_id = ANY(coalesce(p_grant_ids, ARRAY[]::text[]))
         ORDER BY g.grant_id
    LOOP
        IF v_row.grant_revoked IS NOT NULL THEN
            RETURN QUERY SELECT v_row.grant_id, false, 'GRANT_REVOKED';
        ELSIF v_row.slice_revoked IS NOT NULL THEN
            -- Conjunct 1: slice revocation cascades (equivalent check under
            -- the held slice lock — checking the grant row alone is not
            -- enough).
            RETURN QUERY SELECT v_row.grant_id, false, 'SLICE_REVOKED';
        ELSIF NOT (v_row.not_before <= now() AND now() < v_row.expires_at) THEN
            RETURN QUERY SELECT v_row.grant_id, false, 'OUT_OF_VALIDITY_WINDOW';
        ELSIF v_row.constraints IS NOT NULL
              AND (v_row.constraints ? 'ttl_seconds')
              AND now() >= v_row.not_before
                            + (v_row.constraints->>'ttl_seconds')::bigint
                                * interval '1 second' THEN
            RETURN QUERY SELECT v_row.grant_id, false, 'CONSTRAINT_VIOLATED';
        ELSIF v_row.capability IS DISTINCT FROM p_capability THEN
            RETURN QUERY SELECT v_row.grant_id, false, 'CAPABILITY_MISMATCH';
        ELSIF v_sess.workspace_id IS NOT NULL
              AND v_row.workspace_id IS DISTINCT FROM v_sess.workspace_id THEN
            -- Conjunct 2: calling-session tenant consistency (the
            -- grant<->slice half is the composite FK).
            RETURN QUERY SELECT v_row.grant_id, false, 'TENANT_MISMATCH';
        ELSIF NOT (
                (v_row.subject_kind = 'session'
                 AND (v_row.subject_id = p_session_id::text
                      OR v_row.subject_id IS NOT DISTINCT FROM p_caller_subject))
             OR (v_row.subject_kind = 'driver'
                 AND (v_row.subject_id = v_sess.driver
                      OR v_row.subject_id IS NOT DISTINCT FROM p_caller_subject
                      OR v_row.subject_id IS NOT DISTINCT FROM p_caller_driver))
             OR (v_row.subject_kind = 'step'
                 AND (v_row.subject_id IS NOT DISTINCT FROM v_sess.active_step_id::text
                      OR v_row.subject_id IS NOT DISTINCT FROM p_caller_subject))
             OR (v_row.subject_kind = 'plugin_identity'
                 AND (v_row.subject_id IS NOT DISTINCT FROM p_caller_subject
                      OR v_row.subject_id = v_sess.driver))
              ) THEN
            RETURN QUERY SELECT v_row.grant_id, false, 'SUBJECT_MISMATCH';
        ELSIF NOT v_constraints_ok(v_row.constraints, p_params) THEN
            RETURN QUERY SELECT v_row.grant_id, false, 'CONSTRAINT_VIOLATED';
        ELSIF NOT v_slice_member(v_row.spec, p_params) THEN
            -- Conjunct 3: the accessed object belongs to slice.spec.
            RETURN QUERY SELECT v_row.grant_id, false, 'SLICE_MEMBERSHIP_DENIED';
        ELSE
            RETURN QUERY SELECT v_row.grant_id, true, NULL::text;
        END IF;
    END LOOP;
END;
$$;

-- 2.6 v_grant_find_valid — candidate search through the full judge. The
-- lookup NEVER decides by a bare subject_id match (the A56 approximation):
-- subject_id value matching only NARROWS the candidate set to the
-- resolvable identity values; validity is decided exclusively by
-- v_grant_lock_judge under the fixed lock order. Deterministic pick: the
-- lowest grant_id among the valid ones.
CREATE FUNCTION v_grant_find_valid(
    p_session_id uuid, p_capability text,
    p_caller_subject text DEFAULT NULL,
    p_caller_driver text DEFAULT NULL,
    p_caller_epoch bigint DEFAULT NULL,
    p_caller_grant_id text DEFAULT NULL,
    p_params jsonb DEFAULT NULL
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_caller text := p_caller_subject;
    v_ids text[];
    r record;
BEGIN
    SELECT * INTO v_sess FROM sessions WHERE session_id = p_session_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF p_caller_grant_id IS NOT NULL THEN
        v_caller := coalesce(v_caller,
                             (SELECT g.subject_id FROM grants g
                               WHERE g.grant_id = p_caller_grant_id));
    END IF;
    SELECT array_agg(g.grant_id) INTO v_ids
      FROM grants g
     WHERE g.capability = p_capability
       AND (v_sess.workspace_id IS NULL
            OR g.workspace_id = v_sess.workspace_id)
       AND g.subject_id IN (p_session_id::text, v_sess.driver,
                            v_sess.active_step_id::text,
                            v_caller, p_caller_driver);
    IF v_ids IS NULL THEN
        RETURN NULL;
    END IF;
    FOR r IN SELECT lj.grant_id
               FROM v_grant_lock_judge(p_session_id, v_ids, p_capability,
                                       v_caller, p_caller_driver,
                                       p_caller_epoch, p_params) lj
              WHERE lj.valid
              ORDER BY lj.grant_id
              LIMIT 1
    LOOP
        RETURN r.grant_id;
    END LOOP;
    RETURN NULL;
END;
$$;

-- ---------------------------------------------------------------------------
-- 3. operator channel — controlled issue/revoke with reason and audit
-- ---------------------------------------------------------------------------
-- Grant/slice issuance and revocation go through these controlled internal
-- operations only (operator identity + reason + same-transaction audit
-- row). plugin_specs.required_services is catalog declaration only (the
-- §4 catalog arrives with G11); FORCE_JOB_TAKEOVER is unimplemented and
-- separately scheduled (see the plan's explicit-non-goals).

CREATE FUNCTION v_operator_issue_slice(
    p_operator text, p_workspace_id uuid, p_name text, p_kind text,
    p_spec jsonb DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_id uuid := v_uuidgen();
BEGIN
    INSERT INTO slices(slice_id, workspace_id, name, kind, spec)
    VALUES (v_id, p_workspace_id, p_name, p_kind,
            coalesce(p_spec, '{}'::jsonb));
    INSERT INTO grant_ops_audit(operator_id, action, target_id, workspace_id,
                                details)
    VALUES (p_operator, 'issue_slice', v_id::text, p_workspace_id,
            jsonb_build_object('name', p_name, 'kind', p_kind));
    RETURN v_id;
END;
$$;

CREATE FUNCTION v_operator_issue_grant(
    p_operator text, p_workspace_id uuid, p_slice_id uuid,
    p_subject_kind text, p_subject_id text, p_capability text,
    p_constraints jsonb DEFAULT NULL,
    p_not_before timestamptz DEFAULT NULL,
    p_expires_at timestamptz DEFAULT NULL,
    p_delegable boolean DEFAULT false
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_id text := 'gr-' || substr(md5(random()::text || clock_timestamp()::text
                                      || p_capability), 1, 16);
    v_ws uuid;
BEGIN
    -- Tenant consistency: the slice MUST belong to the stated workspace.
    SELECT workspace_id INTO v_ws FROM slices WHERE slice_id = p_slice_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v8: slice % not found', p_slice_id;
    END IF;
    IF v_ws IS DISTINCT FROM p_workspace_id THEN
        RAISE EXCEPTION 'v8: slice % does not belong to workspace %',
            p_slice_id, p_workspace_id;
    END IF;
    INSERT INTO grants(grant_id, workspace_id, slice_id, subject_kind,
                       subject_id, capability, constraints, not_before,
                       expires_at, delegable)
    VALUES (v_id, p_workspace_id, p_slice_id, p_subject_kind, p_subject_id,
            p_capability, p_constraints,
            coalesce(p_not_before, now()),
            coalesce(p_expires_at, now() + interval '1 hour'),
            p_delegable);
    INSERT INTO grant_ops_audit(operator_id, action, target_id, workspace_id,
                                details)
    VALUES (p_operator, 'issue_grant', v_id, p_workspace_id,
            jsonb_build_object('slice_id', p_slice_id,
                               'subject_kind', p_subject_kind,
                               'subject_id', p_subject_id,
                               'capability', p_capability,
                               'delegable', p_delegable));
    RETURN v_id;
END;
$$;

-- Controlled grant revocation: locks the slice+grant rows in the composite
-- order, flips grants.revoked_at, writes the same-transaction audit row.
-- Re-signing after revocation goes through v_operator_issue_grant (a NEW
-- grant_id — constraints/spec are never updated in place).
CREATE FUNCTION v_operator_revoke_grant(
    p_operator text, p_grant_id text, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_grant grants%ROWTYPE;
BEGIN
    IF coalesce(p_reason, '') = '' THEN
        RAISE EXCEPTION 'v8: grant revocation requires a non-empty reason';
    END IF;
    SELECT * INTO v_grant FROM grants WHERE grant_id = p_grant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v8: grant % not found (no audit path)', p_grant_id;
    END IF;
    -- Composite lock order: slice row first, then the grant row.
    PERFORM 1 FROM slices WHERE slice_id = v_grant.slice_id FOR UPDATE;
    PERFORM 1 FROM grants WHERE grant_id = p_grant_id FOR UPDATE;
    IF v_grant.revoked_at IS NOT NULL THEN
        RETURN jsonb_build_object('grant_id', p_grant_id,
                                  'already_revoked', true,
                                  'revoked_at', v_grant.revoked_at);
    END IF;
    UPDATE grants SET revoked_at = now() WHERE grant_id = p_grant_id;
    INSERT INTO grant_ops_audit(operator_id, action, target_id, workspace_id,
                                reason)
    VALUES (p_operator, 'revoke_grant', p_grant_id, v_grant.workspace_id,
            p_reason);
    RETURN jsonb_build_object('grant_id', p_grant_id, 'revoked', true,
                              'reason', p_reason);
END;
$$;

-- Controlled slice revocation: cascade semantics close under the lock
-- order via the equivalent check (the judge's slice.revoked_at conjunct) —
-- no UPDATE cascade on the grant rows (the plan's frozen ruling). The audit
-- row records the number of grants thereby invalidated.
CREATE FUNCTION v_operator_revoke_slice(
    p_operator text, p_slice_id uuid, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_slice slices%ROWTYPE;
    v_count bigint;
BEGIN
    IF coalesce(p_reason, '') = '' THEN
        RAISE EXCEPTION 'v8: slice revocation requires a non-empty reason';
    END IF;
    SELECT * INTO v_slice FROM slices WHERE slice_id = p_slice_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v8: slice % not found (no audit path)', p_slice_id;
    END IF;
    IF v_slice.revoked_at IS NOT NULL THEN
        RETURN jsonb_build_object('slice_id', p_slice_id,
                                  'already_revoked', true,
                                  'revoked_at', v_slice.revoked_at);
    END IF;
    SELECT count(*) INTO v_count FROM grants
     WHERE slice_id = p_slice_id AND revoked_at IS NULL;
    UPDATE slices SET revoked_at = now() WHERE slice_id = p_slice_id;
    INSERT INTO grant_ops_audit(operator_id, action, target_id, workspace_id,
                                reason, details)
    VALUES (p_operator, 'revoke_slice', p_slice_id::text,
            v_slice.workspace_id, p_reason,
            jsonb_build_object('grants_invalidated', v_count));
    RETURN jsonb_build_object('slice_id', p_slice_id, 'revoked', true,
                              'reason', p_reason,
                              'grants_invalidated', v_count);
END;
$$;

-- ---------------------------------------------------------------------------
-- 4. pre-dispatch dual-table atomic sync — the single shared suboperation
-- ---------------------------------------------------------------------------
-- The ONE implementation of the pre-dispatch dual-table atomic sync, shared
-- by the three trigger sources: request_cancel, the §4 generation drain and
-- the §2.2 WORKSPACE_LOST failure-drain of this stage.
--
-- G17 (D14) unified the two historical copies (deviation A68/A73): the
-- narrow four-parameter variant that used to live here
-- (v_predispatch_cancel_sync) is DELETED, and the rich six-parameter
-- variant (p_reason / p_scope_generation_id defaults + the authoritative
-- counter recompute) moved here from plugin/v8_plugin.sql. This file sits
-- at load position 4, so every consumer stage (grant, cancel, plugin,
-- drain, compact and later) has it; the plugin segment of a grant-stage
-- database does not exist, which is exactly why the rich variant could not
-- stay in the plugin file. Function bodies are late-bound, so the callers
-- in the later stages resolve against this single definition.
--
-- For every `ready` effect of the session (optionally scoped to one
-- catalog generation) the SAME transaction flips effect_requests.status
-- and the current (max attempt_no) attempt row to
-- cancelled_before_dispatch and writes the audit row named by
-- (p_audit_key_kind, p_audit_key_value) with reason p_reason; the step
-- aggregation counters are then recomputed from the effect table
-- (authoritative). Returns the cancelled-effect jsonb array.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION v_pre_dispatch_cancel_sync(
    p_session_id uuid,
    p_command_id text,
    p_audit_key_kind text,
    p_audit_key_value text,
    p_reason text DEFAULT 'ABORTED_BEFORE_DISPATCH',
    p_scope_generation_id uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    r record;
    v_cancelled jsonb := '[]'::jsonb;
BEGIN
    FOR r IN
        SELECT er.effect_id, er.step_id, er.attempt_no
          FROM effect_requests er
         WHERE er.session_id = p_session_id
           AND er.status = 'ready'
           -- G17 (D14, deviation A121): the generation scoping reads the
           -- step's catalog_generation through a whole-row to_jsonb() probe
           -- instead of a direct column reference. The column is added by
           -- the plugin stage (load position 7), so a grant-stage database
           -- (load set through position 6) has no such column and a direct
           -- reference would fail to parse. to_jsonb() yields NULL for an
           -- absent column, which makes a non-NULL scope fail closed in
           -- those stages (they never pass one) while stages that carry the
           -- column resolve the frozen generation exactly.
           AND (p_scope_generation_id IS NULL
                OR (SELECT (to_jsonb(st) ->> 'catalog_generation')::uuid
                      FROM steps st WHERE st.step_id = er.step_id)
                   = p_scope_generation_id)
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
                p_audit_key_kind, p_audit_key_value,
                v_sha256_hex(p_command_id || ':' || r.effect_id::text),
                p_reason);
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

    RETURN v_cancelled;
END;
$$;

-- ---------------------------------------------------------------------------
-- 5. workspace_handles (§2.2) and the WORKSPACE_LOST fail-closed drain
-- ---------------------------------------------------------------------------
CREATE TABLE workspace_handles (
    handle_id        uuid PRIMARY KEY,
    session_id       uuid NOT NULL REFERENCES sessions(session_id),
    run_id           text NOT NULL,
    workspace_id     uuid NOT NULL,
    owner_fence      bigint NOT NULL CHECK (owner_fence >= 1),
    status           text NOT NULL
                     CONSTRAINT workspace_handles_status_check
                     CHECK (status IN ('uninitialized', 'active',
                                       'handoff_ready', 'lost', 'discarded')),
    checkpoint_seq   bigint CHECK (checkpoint_seq IS NULL OR checkpoint_seq >= 0),
    checkpoint_digest text,
    op_seq           bigint NOT NULL DEFAULT 0 CHECK (op_seq >= 0),
    generation       bigint NOT NULL DEFAULT 1 CHECK (generation >= 1),
    created_at       timestamptz NOT NULL DEFAULT now(),
    lost_reason      text,
    -- Guarantees both unique initialization and handle_id non-reuse.
    CONSTRAINT workspace_handles_session_run_key UNIQUE (session_id, run_id)
);

-- Controlled mutation records (three-phase protocol, §2.2 item 1).
CREATE TABLE workspace_mutations (
    mutation_id bigserial PRIMARY KEY,
    handle_id   uuid NOT NULL REFERENCES workspace_handles(handle_id),
    op_seq      bigint NOT NULL CHECK (op_seq >= 1),
    status      text NOT NULL
                CONSTRAINT workspace_mutations_status_check
                CHECK (status IN ('in_flight', 'completed', 'invalidated')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (handle_id, op_seq)
);

-- Five-state closed transition table: only the listed edges may execute;
-- lost/discarded are terminal with no out-edges. The controlled functions
-- only ever perform listed edges, so the table is enforced for every
-- updater alike (direct UPDATEs outside the controlled functions are
-- rejected exactly the same way).
CREATE FUNCTION v8_workspace_handles_transitions() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- Same-status updates (op_seq / checkpoint / fence / generation advances
    -- inside `active`, per the three-phase protocol) are not status
    -- transitions; the guard polices the state machine only.
    IF OLD.status = NEW.status THEN
        RETURN NEW;
    END IF;
    IF OLD.status IN ('lost', 'discarded') AND NEW.status <> OLD.status THEN
        RAISE EXCEPTION
            'workspace_handles: % is terminal with no out-edges', OLD.status;
    END IF;
    IF NOT (
        (OLD.status = 'uninitialized' AND NEW.status = 'active')
        OR (OLD.status = 'active' AND NEW.status = 'handoff_ready')
        OR (OLD.status = 'handoff_ready' AND NEW.status = 'active')
        OR (OLD.status = 'active' AND NEW.status = 'lost')
        OR (OLD.status = 'handoff_ready' AND NEW.status = 'lost')
        OR (OLD.status IN ('active', 'handoff_ready')
            AND NEW.status = 'discarded')
    ) THEN
        RAISE EXCEPTION
            'workspace_handles: transition % -> % is not in the closed table',
            OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_workspace_handles_transitions
BEFORE UPDATE ON workspace_handles
FOR EACH ROW EXECUTE FUNCTION v8_workspace_handles_transitions();

-- checkpoint digest: MUST cover the worktree manifest, the REPL variable
-- references and the latest completed op_seq/generation. Byte encoding is
-- self-chosen (the canonical checkpoint_digest computation lives in §3.3,
-- LATER): sha256 over manifest '|' repl '|' op_seq '|' generation.
CREATE FUNCTION v_workspace_checkpoint_digest(
    p_manifest text, p_repl text, p_op_seq bigint, p_generation bigint
) RETURNS text
LANGUAGE sql AS $$
    SELECT v_sha256_hex(coalesce(p_manifest, '') || '|' || coalesce(p_repl, '')
                        || '|' || coalesce(p_op_seq, 0)::text
                        || '|' || coalesce(p_generation, 1)::text)
$$;

-- 5.1 uninitialized -> active: first initialization, CAS'd by
--     UNIQUE(session_id, run_id); op_seq=0, checkpoint fields empty.
CREATE FUNCTION v_workspace_initialize(
    p_session_id uuid, p_run_id text, p_workspace_id uuid,
    p_owner_fence bigint DEFAULT 1
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_id uuid := v_uuidgen();
    v_existing uuid;
BEGIN
    INSERT INTO workspace_handles(handle_id, session_id, run_id,
                                  workspace_id, owner_fence, status,
                                  op_seq, generation)
    VALUES (v_id, p_session_id, p_run_id, p_workspace_id,
            greatest(coalesce(p_owner_fence, 1), 1), 'active', 0, 1)
    ON CONFLICT (session_id, run_id) DO NOTHING;
    IF NOT FOUND THEN
        SELECT handle_id INTO v_existing FROM workspace_handles
         WHERE session_id = p_session_id AND run_id = p_run_id;
        RETURN v_existing;
    END IF;
    INSERT INTO grant_ops_audit(operator_id, action, target_id, workspace_id)
    VALUES ('system', 'ws_initialize', v_id::text, p_workspace_id);
    RETURN v_id;
END;
$$;

-- 5.2 controlled mutation, phase 1 (register): same-transaction CAS
--     UPDATE ... SET op_seq = op_seq + 1 WHERE handle_id = ? AND
--     owner_fence = ? AND op_seq = expected, plus the in_flight record.
--     CAS failure rejects; external IO never happens inside this
--     transaction (phase 2 executes outside the database transaction).
CREATE FUNCTION v_workspace_register_mutation(
    p_handle_id uuid, p_owner_fence bigint, p_expected_op_seq bigint
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_new bigint;
BEGIN
    UPDATE workspace_handles SET op_seq = op_seq + 1
     WHERE handle_id = p_handle_id AND owner_fence = p_owner_fence
       AND status = 'active' AND op_seq = p_expected_op_seq
     RETURNING op_seq INTO v_new;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'CAS_FAILED');
    END IF;
    INSERT INTO workspace_mutations(handle_id, op_seq, status)
    VALUES (p_handle_id, v_new, 'in_flight');
    INSERT INTO grant_ops_audit(operator_id, action, target_id, details)
    VALUES ('system', 'ws_register_mutation', p_handle_id::text,
            jsonb_build_object('op_seq', v_new));
    RETURN jsonb_build_object('outcome', 'accepted', 'op_seq', v_new);
END;
$$;

-- 5.3 controlled mutation, phase 3 (fenced publish): the same DB
--     transaction writes status=completed and advances the checkpoint,
--     whose digest covers the latest completed op_seq/generation. A stale
--     owner's publish is rejected by the owner_fence CAS — it MUST NOT
--     write into the checkpoint.
CREATE FUNCTION v_workspace_fenced_publish(
    p_handle_id uuid, p_owner_fence bigint, p_op_seq bigint,
    p_manifest text DEFAULT NULL, p_repl text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_mut workspace_mutations%ROWTYPE;
    v_h workspace_handles%ROWTYPE;
    v_seq bigint;
    v_digest text;
BEGIN
    SELECT * INTO v_mut FROM workspace_mutations
     WHERE handle_id = p_handle_id AND op_seq = p_op_seq;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'MUTATION_UNKNOWN');
    END IF;
    IF v_mut.status = 'completed' THEN
        RETURN jsonb_build_object('outcome', 'accepted', 'already', true,
                                  'op_seq', p_op_seq);
    END IF;
    IF v_mut.status <> 'in_flight' THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'MUTATION_NOT_IN_FLIGHT');
    END IF;
    SELECT * INTO v_h FROM workspace_handles WHERE handle_id = p_handle_id
     FOR UPDATE;
    v_digest := v_workspace_checkpoint_digest(p_manifest, p_repl, p_op_seq,
                                              v_h.generation);
    UPDATE workspace_handles SET
        checkpoint_seq = coalesce(checkpoint_seq, 0) + 1,
        checkpoint_digest = v_digest
     WHERE handle_id = p_handle_id AND owner_fence = p_owner_fence
       AND status = 'active'
     RETURNING checkpoint_seq INTO v_seq;
    IF NOT FOUND THEN
        -- Stale publish: MUST NOT write into the checkpoint.
        RETURN jsonb_build_object('outcome', 'rejected_stale',
                                  'code', 'STALE_OWNER_FENCE');
    END IF;
    UPDATE workspace_mutations SET status = 'completed', completed_at = now()
     WHERE handle_id = p_handle_id AND op_seq = p_op_seq;
    INSERT INTO grant_ops_audit(operator_id, action, target_id, details)
    VALUES ('system', 'ws_fenced_publish', p_handle_id::text,
            jsonb_build_object('op_seq', p_op_seq, 'checkpoint_seq', v_seq));
    RETURN jsonb_build_object('outcome', 'accepted', 'op_seq', p_op_seq,
                              'checkpoint_seq', v_seq,
                              'checkpoint_digest', v_digest);
END;
$$;

-- 5.4 yield-before-checkpoint (§2.2 item 2): active -> handoff_ready only
--     when no in_flight mutation remains (all controlled operations
--     completed or invalidated by takeover) and the checkpoint covers the
--     latest completed execution state. When coverage cannot be proven the
--     handle goes lost and the session walks WORKSPACE_LOST fail-closed —
--     an "old but digest-correct" checkpoint is never restored.
CREATE FUNCTION v_workspace_yield_checkpoint(
    p_handle_id uuid, p_owner_fence bigint,
    p_manifest text DEFAULT NULL, p_repl text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_h workspace_handles%ROWTYPE;
    v_digest text;
    v_seq bigint;
BEGIN
    SELECT * INTO v_h FROM workspace_handles WHERE handle_id = p_handle_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'HANDLE_NOT_FOUND');
    END IF;
    IF EXISTS (SELECT 1 FROM workspace_mutations
                WHERE handle_id = p_handle_id AND status = 'in_flight') THEN
        -- Coverage cannot be proven: the handle goes lost and the session
        -- walks WORKSPACE_LOST fail-closed (an "old but digest-correct"
        -- checkpoint is never restored).
        RETURN jsonb_build_object(
            'outcome', 'rejected_mismatch', 'code', 'WORKSPACE_LOST',
            'rejection', 'yield_unprovable',
            'fail_closed', v_workspace_fail_closed(
                v_h.session_id, v_h.run_id,
                'yield_checkpoint_unprovable_in_flight_mutation'));
    END IF;
    v_digest := v_workspace_checkpoint_digest(p_manifest, p_repl, v_h.op_seq,
                                              v_h.generation);
    UPDATE workspace_handles SET
        checkpoint_seq = coalesce(checkpoint_seq, 0) + 1,
        checkpoint_digest = v_digest,
        status = 'handoff_ready'
     WHERE handle_id = p_handle_id AND owner_fence = p_owner_fence
       AND status = 'active'
     RETURNING checkpoint_seq INTO v_seq;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'rejected_stale',
                                  'code', 'STALE_OWNER_FENCE');
    END IF;
    INSERT INTO grant_ops_audit(operator_id, action, target_id, details)
    VALUES ('system', 'ws_yield_checkpoint', p_handle_id::text,
            jsonb_build_object('checkpoint_seq', v_seq,
                               'covered_op_seq', v_h.op_seq));
    RETURN jsonb_build_object('outcome', 'accepted', 'status',
                              'handoff_ready', 'checkpoint_seq', v_seq,
                              'checkpoint_digest', v_digest,
                              'covered_op_seq', v_h.op_seq);
END;
$$;

-- 5.5 materialize(checkpoint_digest) (§2.2 item 3): the next worker's
--     claim entry. The four frozen rejections — files missing, digest
--     mismatch, checkpoint not covering the latest completed execution
--     state, handle already lost — all return WORKSPACE_LOST (fail-closed:
--     forbidden to open an empty workspace and continue). Success CAS's
--     owner_fence to the new worker, bumps generation, returns to active;
--     op_seq continues (never resets), checkpoint fields retained.
CREATE FUNCTION v_workspace_materialize(
    p_handle_id uuid, p_new_owner_fence bigint,
    p_expected_checkpoint_digest text,
    p_files_present boolean DEFAULT true
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_h workspace_handles%ROWTYPE;
BEGIN
    SELECT * INTO v_h FROM workspace_handles WHERE handle_id = p_handle_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'HANDLE_NOT_FOUND');
    END IF;
    -- (4) handle already lost.
    IF v_h.status IN ('lost', 'discarded') THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'WORKSPACE_LOST',
                                  'rejection', 'handle_lost');
    END IF;
    IF v_h.status <> 'handoff_ready' THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'HANDLE_NOT_HANDOFF_READY');
    END IF;
    -- (1) files missing / (2) digest mismatch / (3) checkpoint not covering
    -- the latest completed execution state: all fail closed (forbidden to
    -- open an empty workspace and continue; handoff_ready -> lost).
    IF NOT p_files_present
       OR p_expected_checkpoint_digest IS DISTINCT FROM v_h.checkpoint_digest
       OR EXISTS (SELECT 1 FROM workspace_mutations
                   WHERE handle_id = p_handle_id AND status = 'in_flight') THEN
        RETURN jsonb_build_object(
            'outcome', 'rejected_mismatch', 'code', 'WORKSPACE_LOST',
            'rejection', CASE WHEN NOT p_files_present THEN 'files_missing'
                              WHEN p_expected_checkpoint_digest IS DISTINCT FROM
                                   v_h.checkpoint_digest THEN 'digest_mismatch'
                              ELSE 'checkpoint_not_covering' END,
            'fail_closed', v_workspace_fail_closed(
                v_h.session_id, v_h.run_id,
                'materialize_rejected'));
    END IF;
    UPDATE workspace_handles SET
        owner_fence = p_new_owner_fence,
        generation = generation + 1,
        status = 'active'
     WHERE handle_id = p_handle_id AND status = 'handoff_ready';
    INSERT INTO grant_ops_audit(operator_id, action, target_id, details)
    VALUES ('system', 'ws_materialize', p_handle_id::text,
            jsonb_build_object('generation', v_h.generation + 1,
                               'op_seq', v_h.op_seq));
    RETURN jsonb_build_object('outcome', 'accepted', 'status', 'active',
                              'generation', v_h.generation + 1,
                              'op_seq', v_h.op_seq);
END;
$$;

-- 5.5b v_failure_drain_core — the SHARED deterministic failure-drain core
--      (G15; §2.2 item 3 WORKSPACE_LOST + §3.1.1 fail_session class (3)
--      INFRA closure, "第 (3) 类与 §2.2 第 3 条 WORKSPACE_LOST fail-closed
--      同构"). One control transaction:
--        (a) drain every `ready` effect through the shared pre-dispatch
--            dual-table atomic sync sub-operation;
--        (b) recompute the aggregation counters from the effect table;
--        (c) settle the single non-terminal step by the three drain
--            branches (unknown > pending > neither), the `neither` arm
--            taking `outcome_code = p_failure_code`;
--        (d) take the session terminal: FIRST failure sets
--            state='failed' / failure_code=p_failure_code / session_fence+1
--            / coordination lease revoked / active_step_id cleared. An
--            ALREADY-TERMINAL session is NEVER overwritten (G15 D5
--            parent-layer cause priority: a session that already failed
--            with WORKSPACE_LOST or another INFRA code keeps its cause);
--            only `drain_step_id` is refreshed, so re-running the SAME
--            drain judgment (late completion/repair arrival) converges —
--            no second event, no second fence bump.
--      Entry (and repeat entry) refuses non-READ COMMITTED with
--      ISOLATION_UNSUPPORTED (Conformance 8 (x) drain half).
CREATE FUNCTION v_failure_drain_core(
    p_session_id uuid, p_failure_code text, p_reason text,
    p_audit_key_value text, p_audit_action text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_repeated boolean;
    v_cancelled jsonb;
    v_step uuid;
    v_unknown bigint;
    v_pending bigint;
    v_drain_step uuid;
BEGIN
    IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'ISOLATION_UNSUPPORTED',
                                  'detail', 'failure-drain entries require '
                                            'READ COMMITTED');
    END IF;

    SELECT * INTO v_sess FROM sessions WHERE session_id = p_session_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v8: session % not found', p_session_id;
    END IF;
    -- Any terminal state is a repeat: the drain judgment converges and the
    -- session terminal is never rewritten (parent-layer cause priority).
    v_repeated := v_sess.state IN ('completed', 'failed', 'cancelled');

    -- (a) effect drain: every ready effect -> cancelled_before_dispatch,
    --     dual-table atomic sync (shared suboperation).
    -- The shared suboperation recomputes the step aggregation counters.
    v_cancelled := v_pre_dispatch_cancel_sync(
        p_session_id, p_audit_key_value, 'canonical_binding',
        p_audit_key_value, 'ABORTED_BEFORE_DISPATCH', NULL);

    -- (b) step drain three branches.
    SELECT st.step_id INTO v_step
      FROM steps st
     WHERE st.session_id = p_session_id
       AND st.status NOT IN ('succeeded', 'failed_terminal', 'cancelled')
     ORDER BY st.created_at DESC, st.step_id DESC
     LIMIT 1;
    v_drain_step := NULL;
    IF v_step IS NOT NULL THEN
        SELECT count(*) FILTER (WHERE er.status = 'unknown_outcome'),
               count(*) FILTER (WHERE er.status IN ('planned', 'ready',
                                                    'dispatch_started'))
          INTO v_unknown, v_pending
          FROM effect_requests er WHERE er.step_id = v_step;
        IF v_unknown > 0 THEN
            UPDATE steps SET status = 'blocked_unknown_effect',
                             updated_at = now()
             WHERE step_id = v_step;
            v_drain_step := v_step;
        ELSIF v_pending > 0 THEN
            UPDATE steps SET
                status = CASE WHEN v_sess.cancellation_epoch > 0
                              THEN 'cancel_requested' ELSE 'waiting_effect' END,
                updated_at = now()
             WHERE step_id = v_step;
            v_drain_step := v_step;
        ELSE
            -- Neither unknown nor pending (this arm also voids an unsealed
            -- tools plan — the accepted decision result stays in history,
            -- no tools effect is created).
            UPDATE steps SET status = 'failed_terminal',
                             outcome_code = p_failure_code,
                             closed_at = now(), updated_at = now()
             WHERE step_id = v_step;
        END IF;
    END IF;

    -- (c) session terminal (first failure only; repeats and already-terminal
    --     sessions keep their existing state and failure_code).
    IF v_repeated THEN
        UPDATE sessions SET drain_step_id = v_drain_step, updated_at = now()
         WHERE session_id = p_session_id;
    ELSE
        UPDATE sessions SET
            state = 'failed',
            failure_code = p_failure_code,
            session_fence = session_fence + 1,
            lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
            active_step_id = NULL,
            drain_step_id = v_drain_step,
            updated_at = now()
         WHERE session_id = p_session_id;

    END IF;

    -- G17 (D7): the failure-drain terminal transition aborts a still
    -- locked compact lock in the SAME transaction, AFTER the whole drain
    -- write set (step drain branches + turn/end slot closures — the
    -- compact row is lock-order position 8, strictly after the
    -- turn_end_slot position 7). Guarded by to_regclass: grant-stage
    -- databases stop before the compact file. The drain core carries no
    -- command_id; the audit key value (the caller command's canonical
    -- hash) serves as the internal sub-operation's parent_command_id.
    IF NOT v_repeated AND to_regclass('public.compactions') IS NOT NULL THEN
        PERFORM v_compact_terminal_abort_tx(p_session_id, p_audit_key_value,
                                            'failure_drain');
    END IF;

    INSERT INTO grant_ops_audit(operator_id, action, target_id, reason,
                                details)
    VALUES ('system', p_audit_action, p_session_id::text, p_reason,
            jsonb_build_object('failure_code', p_failure_code,
                               'repeated', v_repeated,
                               'drain_step_id', v_drain_step));
    RETURN jsonb_build_object('outcome', 'accepted',
                              'repeated', v_repeated,
                              'failure_code', p_failure_code,
                              'cancelled_effects', v_cancelled,
                              'drain_step_id', v_drain_step);
END;
$$;

-- 5.5c v_infra_failure_code_ok / v_infra_closure_effect — the §3.1.1
--      fail_session class (3) closed set and its closure over a triggering
--      effect (G15). Both live here (position 3) so every consumer —
--      including the completion path in effect/v8_effect.sql (position 7)
--      — can reach them; the drain stage hosts only the thin validated
--      entry (v8/drain/v8_drain.sql).
--
--      The closure settles the TRIGGERING effect failed_terminal first, so
--      the drain's three-branch pending/unknown count no longer sees it and
--      the unfinished step takes the `neither` arm, landing
--      failed_terminal / <the INFRA code> exactly per the §3.2.1 INFRA
--      derivation rows.
CREATE FUNCTION v_infra_failure_code_ok(p_code text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    SELECT p_code IN ('INFRA_ASSEMBLY_FAILED', 'INFRA_PROTOCOL_VIOLATION');
$$;

CREATE FUNCTION v_infra_closure_effect(
    p_session_id uuid, p_effect_id uuid, p_failure_code text, p_reason text,
    p_parent_command_id text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_core jsonb;
BEGIN
    IF NOT v_infra_failure_code_ok(p_failure_code) THEN
        RETURN jsonb_build_object(
            'outcome', 'rejected_mismatch',
            'code', 'FAILURE_CODE_INVALID',
            'detail', 'INFRA closure accepts only the closed class (3) set');
    END IF;
    UPDATE effect_requests SET status = 'failed_terminal', updated_at = now()
     WHERE effect_id = p_effect_id
       AND status IN ('planned', 'ready', 'dispatch_started');
    UPDATE effect_attempts SET status = 'failed_terminal', completed_at = now()
     WHERE effect_id = p_effect_id
       AND attempt_no = (SELECT max(a.attempt_no) FROM effect_attempts a
                          WHERE a.effect_id = p_effect_id)
       AND status IN ('ready', 'dispatch_started');
    -- §3.2.2 ordered classification for the settled terminal failure. The
    -- retry stage loads AFTER the effect stage, so an effect-stage database
    -- has no v_retry_stop_reason_cas: guard it (A51 precedent, the same
    -- shape as the G17 compact table guard) — the derivation lands in every
    -- stage database that includes the retry file, which is where the
    -- drain gate asserts it.
    IF to_regprocedure('v_retry_stop_reason_cas(uuid)') IS NOT NULL THEN
        PERFORM v_retry_stop_reason_cas(p_effect_id);
    END IF;

    -- One closure audit row (idempotent: a repeat writes no second row).
    -- The triggering effect is NOT classified by evidence here — the closure
    -- is a protocol-level settlement, so it never writes a
    -- RESULT_OUTCOME_MISMATCH row.
    IF NOT EXISTS (SELECT 1 FROM effect_audit ea
                    WHERE ea.effect_id = p_effect_id
                      AND ea.reason = p_failure_code) THEN
        INSERT INTO effect_audit(
            audit_context_session_id, session_id, step_id, effect_id,
            attempt_no, audit_key_kind, audit_key_value, result_fingerprint,
            reason, internal_op_kind, parent_command_id, internal_op_ordinal)
        SELECT er.session_id, er.session_id, er.step_id, er.effect_id,
               er.attempt_no, 'canonical_binding', p_reason,
               v_sha256_hex('infra_closure:' || p_effect_id::text || ':' ||
                            p_failure_code),
               p_failure_code, 'infra_closure', p_parent_command_id, 0
          FROM effect_requests er WHERE er.effect_id = p_effect_id;
    END IF;

    v_core := v_failure_drain_core(p_session_id, p_failure_code, p_reason,
                                   'infra:' || p_failure_code, 'infra_drain');
    RETURN v_core || jsonb_build_object('effect_id', p_effect_id);
END;
$$;

-- 5.6 WORKSPACE_LOST fail-closed + deterministic failure-drain (§2.2
--     item 3). One control transaction: append workspace/lost, set the
--     handle lost, session -> failed/WORKSPACE_LOST (lease revoked, fence
--     bumped, active_step_id cleared), drain every ready effect via the
--     shared pre-dispatch sync, then settle the step by the three drain
--     branches. Re-running the SAME drain judgment (late completion/repair
--     arrival) converges: no second event, no second fence bump — only the
--     branch resolution is re-evaluated and drain_step_id refreshed.
--     Entry (and repeat entry) refuses non-READ COMMITTED with
--     ISOLATION_UNSUPPORTED (Conformance 8 (x) drain half).
CREATE FUNCTION v_workspace_fail_closed(
    p_session_id uuid, p_run_id text, p_reason text,
    p_from_status text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_h workspace_handles%ROWTYPE;
    v_repeated boolean;
    v_evkey text;
    v_seq bigint;
    v_core jsonb;
BEGIN
    IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'ISOLATION_UNSUPPORTED',
                                  'detail', 'WORKSPACE_LOST drain entries '
                                            'require READ COMMITTED');
    END IF;

    SELECT * INTO v_sess FROM sessions WHERE session_id = p_session_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v8: session % not found', p_session_id;
    END IF;
    v_repeated := (v_sess.state = 'failed'
                   AND v_sess.failure_code = 'WORKSPACE_LOST');

    SELECT * INTO v_h FROM workspace_handles
     WHERE session_id = p_session_id AND run_id = p_run_id
     FOR UPDATE;
    IF FOUND AND v_h.status IN ('active', 'handoff_ready') THEN
        UPDATE workspace_handles SET status = 'lost', lost_reason = p_reason
         WHERE handle_id = v_h.handle_id;
    END IF;

    -- workspace/lost event, appended exactly once per (session, run). The
    -- payload carries ONLY the run identity — the free-form reason stays
    -- on the handle row and the audit (capability API boundary,
    -- Conformance 13: credentials never enter session_events payloads).
    v_evkey := v_sha256_hex('v8:workspace-lost@db1:' || p_session_id::text
                            || ':' || p_run_id);
    IF NOT v_repeated
       AND NOT EXISTS (SELECT 1 FROM session_events se
                        WHERE se.session_id = p_session_id
                          AND se.event_key = v_evkey) THEN
        v_seq := v_sess.next_seq;
        INSERT INTO session_events(seq, session_id, event_type, event_class,
                                   schema_version, canonicalizer_version,
                                   event_key, payload, payload_hash)
        VALUES (v_seq, p_session_id, 'workspace/lost', 'audit', 'sv@1',
                'canon@1', v_evkey,
                jsonb_build_object('run_id', p_run_id)::text,
                v_sha256_hex(jsonb_build_object('run_id', p_run_id)::text));
        UPDATE sessions SET next_seq = v_seq + 1 WHERE session_id = p_session_id;
    END IF;

    -- (a)-(c) the SHARED deterministic failure-drain core (G15): the
    --     pre-dispatch dual-table atomic sync for every ready effect, the
    --     aggregation counter recompute, the three-branch step drain
    --     (outcome code = WORKSPACE_LOST) and the session terminal (first
    --     failure only; repeats and already-terminal sessions keep their
    --     existing state and failure_code).
    v_core := v_failure_drain_core(
        p_session_id, 'WORKSPACE_LOST', p_reason,
        'workspace_lost:' || p_run_id, 'ws_lost_drain');

    RETURN v_core || jsonb_build_object('event_key', v_evkey);
END;
$$;

-- ---------------------------------------------------------------------------
-- 6. minimal fork (§2.2 item 4 / §3.3 fork)
-- ---------------------------------------------------------------------------
-- Cutoff guard: parent_through_seq MUST point at a stable cut — no turn
-- within seq <= cutoff may carry an unresolved unknown (a provisional
-- turn/end {outcome:unknown} without a known end inside the prefix — a
-- parent repair AFTER the cutoff never resolves the cut) or a pending
-- non-terminal effect. The child inherits ONLY the event prefix and
-- delegable=true grants over immutable slices (new grant_id, subject =
-- the child session); live handles are never inherited. The Conformance
-- 11 (a) three assertions are implemented here and accepted by the G13
-- gate (whose load order includes the repair/closer tables).
--
-- G18 (D9): the fork metadata persists in the session_fork_provenance
-- companion table — parent_session_id / parent_through_seq (the cross-
-- session source {session_id, seq}), fork_depth, the manifest version and
-- the inherited_event_count CACHE (the authoritative count is the child
-- event rows themselves). The child's control plane stays the frozen
-- fresh initial state (driver_epoch=1, session_fence=1,
-- driver_mode=active; no lease / switch intent / cancellation latch /
-- compact lock / job is ever inherited — those live only in the parent),
-- and the parent's control state is untouched (a parent in quiescing or
-- a terminal state can still be forked; the fork never reads or writes
-- the parent's switch intent).
CREATE TABLE session_fork_provenance (
    session_id            uuid PRIMARY KEY REFERENCES sessions(session_id),
    parent_session_id     uuid NOT NULL REFERENCES sessions(session_id),
    parent_through_seq    bigint NOT NULL CHECK (parent_through_seq >= 1),
    fork_depth            bigint NOT NULL CHECK (fork_depth >= 0),
    manifest_version      text NOT NULL,
    inherited_event_count bigint NOT NULL DEFAULT 0
                          CHECK (inherited_event_count >= 0),
    created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION v_fork_session(
    p_parent_session_id uuid, p_parent_through_seq bigint,
    p_driver text DEFAULT NULL,
    p_manifest_version text DEFAULT 'assembly-manifest@v1'
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_parent sessions%ROWTYPE;
    v_child uuid := v_uuidgen();
    v_count bigint;
    v_gcount bigint;
    t record;
BEGIN
    SELECT * INTO v_parent FROM sessions WHERE session_id = p_parent_session_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'SESSION_NOT_FOUND');
    END IF;
    IF p_parent_through_seq IS NULL OR p_parent_through_seq < 1
       OR p_parent_through_seq >= v_parent.next_seq THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'FORK_CUTOFF_UNSTABLE',
                                  'detail', 'cutoff outside the allocated prefix');
    END IF;

    FOR t IN
        SELECT DISTINCT se.turn_id
          FROM session_events se
         WHERE se.session_id = p_parent_session_id
           AND se.seq <= p_parent_through_seq AND se.turn_id IS NOT NULL
    LOOP
        IF EXISTS (SELECT 1 FROM session_events se
                    WHERE se.session_id = p_parent_session_id
                      AND se.turn_id = t.turn_id AND se.seq <= p_parent_through_seq
                      AND se.event_type = 'turn/end'
                      AND se.payload::jsonb ->> 'outcome' = 'unknown')
           AND NOT EXISTS (SELECT 1 FROM session_events se
                            WHERE se.session_id = p_parent_session_id
                              AND se.turn_id = t.turn_id
                              AND se.seq <= p_parent_through_seq
                              AND se.event_type = 'turn/end'
                              AND coalesce(se.payload::jsonb ->> 'outcome', '')
                                  <> 'unknown')
           -- G18 (Conformance 11 (a)2): a provisional unknown is also
           -- resolved in-prefix when a repair closer LANDED INSIDE the
           -- cutoff (the closer is self-describing in its event payload —
           -- "closer": true with the resolution triple, the canonicalizer's
           -- own consumption model, §1.2; a repair after the cutoff leaves
           -- no in-prefix closer and stays unstable — the stability
           -- judgment never borrows a post-cutoff resolution). Judging
           -- from the events themselves also keeps forked children
           -- forkable: they inherit the closer events verbatim.
           AND NOT EXISTS (
                SELECT 1 FROM session_events se2
                 WHERE se2.session_id = p_parent_session_id
                   AND se2.turn_id = t.turn_id
                   AND se2.seq <= p_parent_through_seq
                   AND se2.payload::jsonb ->> 'closer' = 'true') THEN
            RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                      'code', 'FORK_CUTOFF_UNSTABLE',
                                      'detail', 'unresolved unknown inside the cutoff');
        END IF;
        IF EXISTS (SELECT 1
                     FROM effect_requests er
                     JOIN steps st ON st.step_id = er.step_id
                    WHERE st.session_id = p_parent_session_id
                      AND st.turn_id = t.turn_id
                      AND er.status IN ('planned', 'ready', 'dispatch_started',
                                        'failed_retryable',
                                        'unknown_outcome')) THEN
            RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                      'code', 'FORK_CUTOFF_UNSTABLE',
                                      'detail', 'pending non-terminal effect inside the cutoff');
        END IF;
    END LOOP;

    INSERT INTO sessions(session_id, driver, workspace_id)
    VALUES (v_child, coalesce(p_driver, v_parent.driver),
            v_parent.workspace_id);

    -- Event prefix inheritance (seq renumbered from 1; internal semantic
    -- ordinals re-assigned in seq order; event keys carried verbatim —
    -- keys stay unique within the child and replay identities persist).
    INSERT INTO session_events(
        seq, session_id, event_type, event_class, schema_version,
        canonicalizer_version, event_key, turn_id, step_id, effect_id,
        payload, payload_hash, semantic_input_ordinal,
        internal_semantic_ordinal, attempt_no, command_id,
        batch_item_ordinal, stream_id, chunk_index, observation_ordinal)
    SELECT row_number() OVER (ORDER BY se.seq),
           v_child, se.event_type, se.event_class, se.schema_version,
           se.canonicalizer_version, se.event_key, se.turn_id, se.step_id,
           se.effect_id, se.payload, se.payload_hash,
           se.semantic_input_ordinal,
           CASE WHEN se.internal_semantic_ordinal IS NOT NULL
                THEN (SELECT count(*)
                        FROM session_events x
                       WHERE x.session_id = p_parent_session_id
                         AND x.seq <= p_parent_through_seq
                         AND x.internal_semantic_ordinal IS NOT NULL
                         AND (x.seq < se.seq
                              OR (x.seq = se.seq
                                  AND x.internal_semantic_ordinal
                                      <= se.internal_semantic_ordinal)))
           END,
           se.attempt_no, se.command_id, se.batch_item_ordinal,
           se.stream_id, se.chunk_index, se.observation_ordinal
      FROM session_events se
     WHERE se.session_id = p_parent_session_id
       AND se.seq <= p_parent_through_seq;

    -- Grant copies: delegable=true over immutable (non-workspace_exec)
    -- slices only; new grant_id; subject = the child session; validity
    -- window carried verbatim. Live handles are NOT inherited (no
    -- workspace_handles row is created for the child).
    INSERT INTO grants(grant_id, workspace_id, slice_id, subject_kind,
                       subject_id, capability, constraints, not_before,
                       expires_at, delegable)
    SELECT 'gr-fork-' || substr(md5(g.grant_id || v_child::text), 1, 16),
           g.workspace_id, g.slice_id, 'session', v_child::text,
           g.capability, g.constraints, g.not_before, g.expires_at,
           g.delegable
      FROM grants g
      JOIN slices s ON s.slice_id = g.slice_id AND s.workspace_id = g.workspace_id
     WHERE g.revoked_at IS NULL AND s.revoked_at IS NULL AND g.delegable
       AND s.kind <> 'workspace_exec'
       AND ((g.subject_kind = 'session'
             AND g.subject_id = p_parent_session_id::text)
            OR (g.subject_kind = 'driver'
                AND g.subject_id = v_parent.driver)
            OR (g.subject_kind = 'step'
                AND g.subject_id IS NOT DISTINCT FROM v_parent.active_step_id::text));

    SELECT count(*) INTO v_count FROM session_events WHERE session_id = v_child;
    -- G18 (D9): the child's seq allocator resumes AFTER the inherited
    -- prefix (the insert above numbered the prefix 1..v_count; leaving the
    -- default next_seq=1 would collide the child's first own append with
    -- seq 1).
    UPDATE sessions SET next_seq = v_count + 1, updated_at = now()
     WHERE session_id = v_child;
    SELECT count(*) INTO v_gcount FROM grants WHERE subject_id = v_child::text;
    -- G18 (D9): fork metadata persistence. fork_depth = parent depth + 1
    -- (a parent without a provenance row is a root session, depth 0).
    INSERT INTO session_fork_provenance(
        session_id, parent_session_id, parent_through_seq, fork_depth,
        manifest_version, inherited_event_count)
    VALUES (v_child, p_parent_session_id, p_parent_through_seq,
            coalesce((SELECT f.fork_depth + 1
                        FROM session_fork_provenance f
                       WHERE f.session_id = p_parent_session_id), 1),
            p_manifest_version, v_count);
    INSERT INTO grant_ops_audit(operator_id, action, target_id, details)
    VALUES ('system', 'fork_session', v_child::text,
            jsonb_build_object('parent_session_id', p_parent_session_id,
                               'parent_through_seq', p_parent_through_seq,
                               'inherited_event_count', v_count,
                               'inherited_grant_count', v_gcount));
    RETURN jsonb_build_object('outcome', 'accepted',
                              'child_session_id', v_child,
                              'inherited_event_count', v_count,
                              'inherited_grant_count', v_gcount,
                              'fork_depth',
                              coalesce((SELECT f.fork_depth
                                          FROM session_fork_provenance f
                                         WHERE f.session_id = v_child), 0),
                              'manifest_version', p_manifest_version);
END;
$$;

-- ---------------------------------------------------------------------------
-- 7. RLS — workspace_id row-level isolation
-- ---------------------------------------------------------------------------
-- Forced RLS with a session-GUC policy predicate; exercised through a
-- non-superuser worker role (created by this stage's setup_db, granted
-- SELECT on the tenant tables and EXECUTE on functions — never business
-- DML). RLS never substitutes slice-membership: a same-tenant grant over a
-- different slice still fails the authorization conjunction. The
-- SECURITY DEFINER capability functions run as the bootstrap owner and
-- carry their own per-function audit.
ALTER TABLE slices ENABLE ROW LEVEL SECURITY;
ALTER TABLE slices FORCE ROW LEVEL SECURITY;
CREATE POLICY slices_tenant_isolation ON slices
    USING (workspace_id::text = current_setting('v8.workspace_id', true));

ALTER TABLE grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE grants FORCE ROW LEVEL SECURITY;
CREATE POLICY grants_tenant_isolation ON grants
    USING (workspace_id::text = current_setting('v8.workspace_id', true));

ALTER TABLE workspace_handles ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_handles FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_handles_tenant_isolation ON workspace_handles
    USING (workspace_id::text = current_setting('v8.workspace_id', true));
