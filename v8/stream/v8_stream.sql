-- v8 G9a: streaming foundation.
--
-- Three pieces, loaded BEFORE the events stage (SQL_LOAD_ORDER position 3)
-- because the public append path consumes all three:
--   1. session_events stream columns (stream_id / chunk_index /
--      observation_ordinal) with column-level CHECKs;
--   2. the MINIMAL slice/grant stub (slices, grants, immutability guards);
--   3. the effective-grant predicate v_grant_valid(p_session_id, p_grant_id,
--      p_capability).
--
-- Scope declaration (P0A minimal stub, frozen by the G9a task): this file is
-- ONLY the smallest decidable model the six-item assistant/chunk attribution
-- validation items (3) and (6) and the base event_append / stream_ingest
-- capabilities need. The complete section 2.1 model — authorization
-- linearization point (SELECT ... FOR UPDATE fixed lock order or
-- revocation_version CAS), the seam list, RLS, the operator channel,
-- workspace_handles and the WORKSPACE_LOST drain — is P1. `constraints` is
-- carried as an opaque jsonb object; parameter-level constraint evaluation
-- (path/command/target/TTL/max_bytes/max_rows) is P1.
--
-- Source: docs/analysis/v8-impl-digest/s2-planes-grants.md sections 1.1/1.2/2,
-- docs/analysis/v8-impl-digest/s31b-command-table.md section 2.8, frozen spec
-- docs/designs/v8-dev.md lines 49 (stream identity) and 53 (integrity barrier).

-- ---------------------------------------------------------------------------
-- 1. session_events stream columns (G9a scope item 1)
-- ---------------------------------------------------------------------------
-- The stream event (assistant/chunk) identity is the frozen four-tuple
-- (effect_id, attempt_no, stream_id, chunk_index); chunk_index shares the
-- tagged-integer domain 0 <= chunk_index <= 2^63-1. observation_ordinal is the
-- O01 (alpha) repeatable-observation ordinal (assigned monotonically inside
-- the generating command transaction; the pending stream_progress observation
-- of the stream_complete matrix uses it).
--
-- Column-level CHECKs tie each column to its event class:
--   * an assistant/chunk row MUST carry both stream columns, in domain;
--   * every other row MUST carry neither (NULL is structural, not a default);
--   * observation_ordinal is non-NULL only for repeatable observation event
--     types and MUST be >= 1.
ALTER TABLE session_events
    ADD COLUMN stream_id text,
    ADD COLUMN chunk_index bigint,
    ADD COLUMN observation_ordinal bigint;

ALTER TABLE session_events
    ADD CONSTRAINT session_events_stream_cols_check CHECK (
        (event_type = 'assistant/chunk'
         AND stream_id IS NOT NULL
         AND chunk_index IS NOT NULL
         AND chunk_index >= 0
         AND chunk_index <= 9223372036854775807)
        OR
        (event_type <> 'assistant/chunk'
         AND stream_id IS NULL
         AND chunk_index IS NULL)
    );

-- Repeatable observation kinds carrying an ordinal, closed for P0A. Frozen
-- O01 (alpha) list: stream_progress (complete_effect non-terminal stream
-- observation) and attempt/heartbeat. New repeatable kinds extend this CHECK
-- together with a contract version bump.
ALTER TABLE session_events
    ADD CONSTRAINT session_events_observation_ordinal_check CHECK (
        observation_ordinal IS NULL
        OR (observation_ordinal >= 1
            AND event_class = 'observational'
            AND event_type IN ('stream_progress', 'attempt/heartbeat'))
    );

-- One observation_ordinal per (session, effect, attempt): O01 (alpha) assigns
-- monotonically inside the generating command transaction and a receipt retry
-- reuses the same ordinal.
CREATE UNIQUE INDEX session_events_observation_ordinal
    ON session_events (session_id, effect_id, attempt_no, observation_ordinal)
    WHERE observation_ordinal IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. slices (digest s2-planes-grants 1.1; minimal stub)
-- ---------------------------------------------------------------------------
CREATE TABLE slices (
    slice_id     uuid PRIMARY KEY,
    workspace_id uuid NOT NULL,
    name         text NOT NULL,
    kind         text NOT NULL
                 CONSTRAINT slices_kind_check
                 CHECK (kind IN ('corpus', 'fs_prefix', 'tool_set',
                                 'secret', 'workspace_exec')),
    -- Opaque resource-set descriptor; content-frozen after creation.
    spec         jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    revoked_at   timestamptz,
    -- The composite UNIQUE also backs the grants tenant-consistency FK.
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
-- 3. grants (digest s2-planes-grants 1.2; minimal stub)
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
    -- Opaque constraint object; parameter-level evaluation is P1.
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
-- 4. effective-grant predicate (digest s2-planes-grants section 2.1)
-- ---------------------------------------------------------------------------
-- Valid grant <=> ALL of the following conjuncts hold:
--   * grant.revoked_at IS NULL;
--   * now() in [not_before, expires_at) (half-open);
--   * capability covers this call;
--   * tenant consistency (grant.workspace_id = slice.workspace_id) — also
--     enforced structurally by the composite FK, re-checked here;
--   * slice-membership: the owning slice is not revoked (revoked_at IS NULL).
--     Slice revocation propagates — checking the grant row alone is NOT
--     enough;
--   * the grant subject matches the caller: subject_kind='session' with the
--     calling session, or a session-bound driver/step/plugin identity leg.
--
-- The caller is identified by the session (the frozen signature takes only
-- p_session_id). Full subject resolution through the grant/driver chain and
-- the parameter-level `constraints` evaluation are P1 — this stub decides the
-- capability + subject-kind legs the chunk six-item validation items (3)/(6)
-- and the base append/stream_ingest capability checks need.
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

-- Subject of a grant (the effect's bound provider/adapter, resolved through
-- its grant_id). NULL when the grant_id is NULL or unknown.
CREATE FUNCTION v_grant_subject(p_grant_id text) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT g.subject_id FROM grants g WHERE g.grant_id = p_grant_id;
$$;

-- ===========================================================================
-- G9b: observation path, five-state gate, equivalence lifecycle, F4 extra
-- index, partial synthesis support and the two-layer portable verifier.
--
-- Source: docs/designs/v8-dev.md section 1.2 (流完整性屏障, line 53) and
-- Conformance 10; digest s32b-effect-ledger.md section 3.2 grammar (0)/(1)-(7)
-- + stream_progress state gates + observation receipt contract (Q04) +
-- zero-control-state (AF01) + observation payload layering (S04);
-- digest s32c-completion-evidence.md (L4-R03/F5 gate priority, S04).
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 5. stream_progress observation sub-operation (five-state gate + receipt)
-- ---------------------------------------------------------------------------
-- Frozen priority order (first hit stops), AFTER identity/receipt replay
-- (the caller ran v8_command_adjudicate) and AFTER the structural envelope
-- and evidence classification:
--   (1) terminal session        -> rejected_mismatch / SESSION_TERMINAL
--   (2) superseded attempt      -> rejected_stale
--   (3) attempt four terminal   -> rejected_mismatch / STREAM_CLOSED
--   (4) unknown / window out    -> repair_required / REPAIR_REQUIRED
--   (5) accept                  -> observation receipt
-- quiescing is NOT one of the five (W01): a terminal completion still returns
-- DRIVER_QUIESCING, but a non-terminal stream_progress observation is judged
-- solely by the five gates above.
--
-- Write set on accept (AF01, zero control-state): observation receipt +
-- one stream_progress observational event. NO aggregation, NO sessions.state
-- / lease / session_fence / cancellation_epoch / steps.status / aggregation
-- counters, NO attempt result_hash/status/provider_request_id mutation.
CREATE FUNCTION v_stream_observe(
    p_session_id uuid, p_command_id text,
    p_effect_id uuid, p_attempt_no bigint,
    p_result_payload_canonical text,
    p_schema_version text, p_canonicalizer_version text,
    p_computed text
) RETURNS TABLE(outcome text, code text, receipt_json jsonb)
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_er effect_requests%ROWTYPE;
    v_att effect_attempts%ROWTYPE;
    v_step_id uuid;
    v_receipt jsonb;
    v_ord bigint;
    v_digest text;
    v_obs_hash text;
    v_evkey text;
    v_seq bigint;
    v_identity jsonb;
BEGIN
    SELECT * INTO v_sess FROM sessions s WHERE s.session_id = p_session_id;
    SELECT * INTO v_er FROM effect_requests er WHERE er.effect_id = p_effect_id;
    SELECT * INTO v_att FROM effect_attempts a
     WHERE a.effect_id = p_effect_id AND a.attempt_no = p_attempt_no;
    v_step_id := v_er.step_id;

    -- (1) terminal session gate (highest priority; precedes every attempt-
    --     level state and window judgment).
    IF v_sess.state IN ('completed', 'failed', 'cancelled') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            p_computed, 'rejected_mismatch', 'SESSION_TERMINAL',
            'stream_progress observation on a terminal session (gate 1)');
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'SESSION_TERMINAL'::text, v_receipt;
        RETURN;
    END IF;
    -- (2) superseded attempt.
    IF v_att.superseded_by_attempt_no IS NOT NULL THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            p_computed, 'rejected_stale', 'ATTEMPT_SUPERSEDED',
            format('stream_progress observation on attempt %s superseded by %s (gate 2)',
                   p_attempt_no, v_att.superseded_by_attempt_no));
        RETURN QUERY SELECT 'rejected_stale'::text, 'ATTEMPT_SUPERSEDED'::text, v_receipt;
        RETURN;
    END IF;
    -- (3) attempt four terminal statuses (unknown_outcome is NOT one of the
    --     four — it belongs to gate 4).
    IF v_att.status IN ('succeeded', 'failed_terminal',
                        'cancelled_before_dispatch', 'cancelled_after_dispatch') THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            p_computed, 'rejected_mismatch', 'STREAM_CLOSED',
            format('stream_progress observation on a closed attempt (status=%s) (gate 3)',
                   v_att.status));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'STREAM_CLOSED'::text, v_receipt;
        RETURN;
    END IF;
    -- (4) unknown_outcome, or the waiting window already exhausted. The
    --     waiting window is the lease/timeout semantic of s32b (7): the real
    --     sweep is LATER, so the stage models its outcome through the
    --     transaction-local GUC v8.stream_window_exhausted (the same channel
    --     as v8.slot_protected_write). A live window (unset / off) is the
    --     default.
    IF v_att.status = 'unknown_outcome'
       OR coalesce(current_setting('v8.stream_window_exhausted', true), '') = 'on' THEN
        v_receipt := jsonb_build_object(
            'command_kind', 'complete_effect',
            'command_id', p_command_id,
            'outcome', 'repair_required',
            'code', 'REPAIR_REQUIRED',
            'effect_id', p_effect_id,
            'attempt_no', p_attempt_no,
            'detail', 'stream_progress observation outside the waiting window / on an unknown attempt (gate 4)');
        INSERT INTO command_bindings(
            session_id, command_id, first_key_kind, first_key_value, first_outcome)
        VALUES (p_session_id, p_command_id, 'canonical_request_hash',
                p_computed, 'repair_required');
        INSERT INTO command_receipts(
            session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
            outcome, code, result_canonical, result_hash)
        VALUES (p_session_id, p_command_id, 'complete_effect', 'canonical_request_hash',
                p_computed, 'repair_required', 'REPAIR_REQUIRED', v_receipt::text,
                v_sha256_hex(v_receipt::text));
        RETURN QUERY SELECT 'repair_required'::text, 'REPAIR_REQUIRED'::text, v_receipt;
        RETURN;
    END IF;
    -- (5) accept condition: the current execution attempt, still in-flight
    --     (dispatch_started) and within the live waiting window.
    IF v_att.status <> 'dispatch_started' THEN
        v_receipt := v8_reject_command(p_session_id, p_command_id, 'complete_effect',
            p_computed, 'rejected_mismatch', 'ATTEMPT_NOT_DISPATCHED',
            format('stream_progress observation requires an in-flight attempt, got %s (gate 5)',
                   v_att.status));
        RETURN QUERY SELECT 'rejected_mismatch'::text, 'ATTEMPT_NOT_DISPATCHED'::text, v_receipt;
        RETURN;
    END IF;

    -- Observation receipt contract (Q04). O01 (alpha) ordinal: monotonically
    -- assigned inside this generating command transaction; a receipt retry
    -- (same command_id, replayed by the adjudicator) reuses the same ordinal.
    SELECT coalesce(max(se.observation_ordinal), 0) + 1 INTO v_ord
      FROM session_events se
     WHERE se.session_id = p_session_id
       AND se.effect_id = p_effect_id
       AND se.attempt_no = p_attempt_no;
    v_digest := v_sha256_hex(p_result_payload_canonical);
    v_obs_hash := v_sha256_hex(v_digest || ':' || v_ord::text);
    v_evkey := v_completion_event_key(p_session_id, 'stream_progress',
                                      p_effect_id, p_attempt_no, v_obs_hash);
    SELECT s.next_seq INTO v_seq FROM sessions s WHERE s.session_id = p_session_id;
    INSERT INTO session_events(
        seq, session_id, event_type, event_class, schema_version,
        canonicalizer_version, event_key, turn_id, step_id, effect_id,
        payload, payload_hash, semantic_input_ordinal,
        internal_semantic_ordinal, attempt_no, command_id,
        batch_item_ordinal, observation_ordinal)
    VALUES (
        v_seq, p_session_id, 'stream_progress', 'observational',
        p_schema_version, p_canonicalizer_version, v_evkey,
        (SELECT st.turn_id FROM steps st WHERE st.step_id = v_step_id),
        v_step_id, p_effect_id, p_result_payload_canonical, v_digest, NULL, NULL,
        p_attempt_no, p_command_id, NULL, v_ord);
    UPDATE sessions SET next_seq = v_seq + 1, updated_at = now()
     WHERE session_id = p_session_id;

    -- receipt result_canonical = the observation identity triple
    -- (attempt_no, observation_ordinal, payload digest) (Q04 clause iii).
    v_identity := jsonb_build_object(
        'attempt_no', p_attempt_no,
        'observation_ordinal', v_ord,
        'payload_digest', v_digest);
    v_receipt := jsonb_build_object(
        'command_kind', 'complete_effect',
        'command_id', p_command_id,
        'classification', 'known_success',
        'kind', 'stream_pending',
        'outcome', 'accepted',
        'effect_id', p_effect_id,
        'attempt_no', p_attempt_no,
        'observation_identity', v_identity,
        'events', jsonb_build_array(jsonb_build_object(
            'event_type', 'stream_progress', 'seq', v_seq,
            'event_key', v_evkey)));
    INSERT INTO command_bindings(
        session_id, command_id, first_key_kind, first_key_value, first_outcome)
    VALUES (p_session_id, p_command_id, 'canonical_request_hash',
            p_computed, 'accepted');
    INSERT INTO command_receipts(
        session_id, command_id, command_kind, receipt_key_kind, receipt_key_value,
        outcome, code, result_canonical, result_hash)
    VALUES (p_session_id, p_command_id, 'complete_effect', 'canonical_request_hash',
            p_computed, 'accepted', NULL, v_receipt::text,
            v_sha256_hex(v_receipt::text));
    RETURN QUERY SELECT 'accepted'::text, NULL::text, v_receipt;
END;
$$;

-- ---------------------------------------------------------------------------
-- 6. certified stream completion facts (settlement write, read by the
--    equivalence judgments and the late-chunk hook)
-- ---------------------------------------------------------------------------
-- The stream end facts of a form-(0)(i) completion (final_chunk_index N /
-- chunk_count C and the final message text) are needed long after settlement:
-- by the (a)/(b) equivalence lifecycle when a late tail chunk completes a
-- pending verification, and by the F4 extra-index range check. The result
-- payload itself is not persisted queryably (only its hash), so the certified
-- facts are recorded here in the settlement transaction.
CREATE TABLE stream_completions (
    effect_id          uuid NOT NULL,
    attempt_no         bigint NOT NULL,
    session_id         uuid NOT NULL,
    final_chunk_index  bigint,
    chunk_count        bigint,
    final_text         text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (effect_id, attempt_no),
    CONSTRAINT stream_completions_at_least_one_count
        CHECK (final_chunk_index IS NOT NULL OR chunk_count IS NOT NULL)
);

CREATE FUNCTION v_stream_record_completion(
    p_session_id uuid, p_effect_id uuid, p_attempt_no bigint,
    p_final_chunk_index bigint, p_chunk_count bigint, p_final_text text
) RETURNS void
LANGUAGE sql AS $$
    INSERT INTO stream_completions(
        effect_id, attempt_no, session_id, final_chunk_index, chunk_count,
        final_text)
    VALUES (p_effect_id, p_attempt_no, p_session_id, p_final_chunk_index,
            p_chunk_count, p_final_text)
    ON CONFLICT (effect_id, attempt_no) DO NOTHING;
$$;

-- ---------------------------------------------------------------------------
-- 7. unified controlled extraction of the accepted chunk set (S04 clause 2)
-- ---------------------------------------------------------------------------
-- The ONLY source of the flow-collection set fact: the accepted assistant/
-- chunk events' index set (sorted) and their merged text, assembled in
-- chunk_index order. Observation payloads never enter this function.
CREATE FUNCTION v_stream_flow_indices(
    p_session_id uuid, p_effect_id uuid, p_attempt_no bigint
) RETURNS TABLE(indices bigint[], merged_text text)
LANGUAGE sql STABLE AS $$
    SELECT array_agg(se.chunk_index ORDER BY se.chunk_index),
           string_agg(coalesce(se.payload::jsonb ->> 'text', ''),
                      '' ORDER BY se.chunk_index)
      FROM session_events se
     WHERE se.session_id = p_session_id
       AND se.effect_id = p_effect_id
       AND se.attempt_no = p_attempt_no
       AND se.event_type = 'assistant/chunk'
       AND se.event_class = 'observational';
$$;

-- ---------------------------------------------------------------------------
-- 8. persisted CANONICALIZER_CONFLICT conflict fact (portable verifier layer 2)
-- ---------------------------------------------------------------------------
-- Idempotent: the effect_audit UNIQUE (NULLS NOT DISTINCT) constraint on
-- (audit_context_session_id, effect_id, attempt_no, audit_key_kind,
-- audit_key_value, result_fingerprint, reason, ...) collapses repeated writes,
-- so a late-chunk re-verification never duplicates the fact.
CREATE FUNCTION v_stream_conflict_fact(
    p_session_id uuid, p_effect_id uuid, p_attempt_no bigint,
    p_scope text, p_fingerprint text
) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_step_id uuid;
BEGIN
    SELECT er.step_id INTO v_step_id FROM effect_requests er
     WHERE er.effect_id = p_effect_id;
    INSERT INTO effect_audit(
        audit_context_session_id, session_id, step_id, effect_id, attempt_no,
        audit_key_kind, audit_key_value, result_fingerprint, reason)
    VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
            'canonical_binding', p_scope, coalesce(p_fingerprint, ''),
            'CANONICALIZER_CONFLICT')
    ON CONFLICT DO NOTHING;
END;
$$;

-- The F4 extra-index range criterion and the final/chunk equivalence
-- assertion, judged on the accepted chunk set alone. Returns a jsonb
-- {status, conflict, merged_text, indices}:
--   status 'no_fact'             — neither count present
--   status 'pending'             — set ⊆ target (missing index) OR the count
--                                  target is complete but no final text yet
--                                  (equivalence stays pending, MUST NOT
--                                  judge CANONICALIZER_CONFLICT — (b)/(5))
--   status 'conflict_extra_index'— an accepted index outside the certified
--                                  end range (F4): conflict fact recorded,
--                                  equivalence NOT evaluated
--   status 'ok'                  — complete AND merged text == final text
--   status 'conflict_equivalence'— complete AND merged text != final text:
--                                  conflict fact recorded ((a) row)
CREATE FUNCTION v_stream_equivalence(
    p_session_id uuid, p_effect_id uuid, p_attempt_no bigint,
    p_final_chunk_index bigint, p_chunk_count bigint, p_final_text text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_idx bigint[];
    v_txt text;
    v_cnt bigint;
    v_min bigint;
    v_max bigint;
    v_end bigint;   -- certified end index (N, or C-1)
BEGIN
    SELECT fi.indices, fi.merged_text INTO v_idx, v_txt
      FROM v_stream_flow_indices(p_session_id, p_effect_id, p_attempt_no) fi;
    v_idx := coalesce(v_idx, ARRAY[]::bigint[]);
    v_txt := coalesce(v_txt, '');
    SELECT count(*), min(i), max(i) INTO v_cnt, v_min, v_max FROM unnest(v_idx) i;
    v_cnt := coalesce(v_cnt, 0);

    IF p_final_chunk_index IS NULL AND p_chunk_count IS NULL THEN
        RETURN jsonb_build_object('status', 'no_fact', 'conflict', false,
                                  'merged_text', v_txt, 'indices', to_jsonb(v_idx));
    END IF;

    -- Certified end index: N when present, else C-1. The target set {0..end}
    -- is NEVER materialized — with N up to 2^63-2 an array would be absurd;
    -- the exact set equality below is decided from the three aggregate facts
    -- (count / min / max) over the distinct accepted indices.
    v_end := CASE WHEN p_final_chunk_index IS NOT NULL
                  THEN p_final_chunk_index ELSE p_chunk_count - 1 END;

    -- F4: an accepted index beyond the certified end range is an independent
    -- range conflict — recorded directly, equivalence NOT evaluated.
    IF v_max IS NOT NULL AND v_max > v_end THEN
        PERFORM v_stream_conflict_fact(p_session_id, p_effect_id, p_attempt_no,
                                       'extra_index', v_sha256_hex(v_max::text));
        RETURN jsonb_build_object('status', 'conflict_extra_index', 'conflict', true,
                                  'merged_text', v_txt, 'indices', to_jsonb(v_idx));
    END IF;

    -- Collection criterion: accepted index set EXACTLY equals {0..end}.
    -- Distinct indices with min=0, max=end and count=end+1 is exactly that
    -- set; anything else (a gap, a missing head, a short count) is pending.
    IF NOT (v_cnt = v_end + 1 AND v_min = 0 AND v_max = v_end) THEN
        RETURN jsonb_build_object('status', 'pending', 'conflict', false,
                                  'merged_text', v_txt, 'indices', to_jsonb(v_idx));
    END IF;

    -- Flow confirmed complete: the (a) full-text equivalence assertion runs
    -- only here. No final text yet (only counts) keeps the verification
    -- pending — completion is not blocked by equivalence (b).
    IF p_final_text IS NULL THEN
        RETURN jsonb_build_object('status', 'pending', 'conflict', false,
                                  'merged_text', v_txt, 'indices', to_jsonb(v_idx));
    END IF;
    IF v_txt = p_final_text THEN
        RETURN jsonb_build_object('status', 'ok', 'conflict', false,
                                  'merged_text', v_txt, 'indices', to_jsonb(v_idx));
    END IF;
    PERFORM v_stream_conflict_fact(p_session_id, p_effect_id, p_attempt_no,
                                   'equivalence', v_sha256_hex(v_txt));
    RETURN jsonb_build_object('status', 'conflict_equivalence', 'conflict', true,
                              'merged_text', v_txt, 'indices', to_jsonb(v_idx));
END;
$$;

-- ---------------------------------------------------------------------------
-- 9. waiting-window exhaustion marker (STREAM_INCOMPLETE audit reason)
-- ---------------------------------------------------------------------------
-- s32b grammar (7): a streaming attempt settled unknown_outcome with no
-- terminal evidence records the STREAM_INCOMPLETE audit reason (a reason
-- VALUE, not a new closed code). Idempotent per (effect, attempt).
CREATE FUNCTION v_stream_incomplete_fact(
    p_session_id uuid, p_effect_id uuid, p_attempt_no bigint,
    p_fingerprint text
) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v_step_id uuid;
BEGIN
    SELECT er.step_id INTO v_step_id FROM effect_requests er
     WHERE er.effect_id = p_effect_id;
    INSERT INTO effect_audit(
        audit_context_session_id, session_id, step_id, effect_id, attempt_no,
        audit_key_kind, audit_key_value, result_fingerprint, reason)
    VALUES (p_session_id, p_session_id, v_step_id, p_effect_id, p_attempt_no,
            'canonical_binding', 'stream_incomplete', coalesce(p_fingerprint, ''),
            'STREAM_INCOMPLETE')
    ON CONFLICT DO NOTHING;
END;
$$;

