-- G16 (audit stage): versioned raw-byte audit keys — the effect_audit full
-- column set, the two occurrence child tables and the internal_op_audits
-- table.
--
-- Contract: docs/designs/v8-dev.md 1.3 L78-L80 (the five versioned keys),
-- 3.1.2 (the three rejection paths (a)/(b)/(c)) and 3.2.2 (the effect_audit
-- DDL, its UNIQUE NULLS NOT DISTINCT dedup key and the occurrence tables).
--
-- Load position 3 (after schema/keys, before grant): the three-key
-- judgement is consumed by the events stage's receipt/binding ordering, so
-- it must exist before v8_append.sql loads. The G2 schema DDL is frozen —
-- every column below is added by this stage-local ALTER (A8/A55/A90
-- precedent) and the occurrence/internal tables are created here.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 1. effect_audit: the remaining columns of the frozen 3.2.2 column list.
--    (The base columns — audit_context_session_id, attribution four,
--    audit_key_kind/value, result_fingerprint, reason, internal triple,
--    created_at — were created by G2; nothing here alters them.)
-- ---------------------------------------------------------------------------
ALTER TABLE effect_audit
    ADD COLUMN command_id                   text,
    ADD COLUMN result_hash                  text,
    -- G16 deviation (A113): result_parse_path is NOT NULL in the frozen
    -- column list with the three-value closed set; every pre-G16 write path
    -- (RESULT_OUTCOME_MISMATCH, the stale/mismatch rejections, the closure
    -- audits) carries no received result bytes, which is exactly the
    -- 'empty' path, so the DEFAULT keeps those inserts byte-compatible.
    ADD COLUMN result_parse_path            text NOT NULL DEFAULT 'empty'
        CONSTRAINT effect_audit_result_parse_path_check
        CHECK (result_parse_path IN ('complete', 'raw_invalid', 'empty')),
    ADD COLUMN raw_invalid_class            text
        CONSTRAINT effect_audit_raw_invalid_class_check
        CHECK (raw_invalid_class IN ('TRUNCATED', 'CORRUPT_BYTES',
                                     'UNBOUNDED_KEY')),
    ADD COLUMN binding_invalid_class        text
        CONSTRAINT effect_audit_binding_invalid_class_check
        CHECK (binding_invalid_class IN ('TRUNCATED', 'CORRUPT_BYTES',
                                         'UNBOUNDED_KEY')),
    ADD COLUMN received_session_id          uuid,
    ADD COLUMN received_step_id             uuid,
    ADD COLUMN received_effect_id           uuid,
    ADD COLUMN received_attempt_no          bigint,
    ADD COLUMN expected_driver              text,
    ADD COLUMN received_driver              text,
    ADD COLUMN expected_driver_epoch        bigint,
    ADD COLUMN received_driver_epoch        bigint,
    ADD COLUMN expected_dispatch_session_fence bigint,
    ADD COLUMN received_dispatch_session_fence bigint,
    ADD COLUMN expected_job_fence           bigint,
    ADD COLUMN received_job_fence           bigint,
    ADD COLUMN expected_request_hash        text,
    ADD COLUMN received_request_hash        text,
    ADD COLUMN expected_idempotency_key_hash text,
    ADD COLUMN received_idempotency_key_hash text,
    ADD COLUMN received_binding_raw         bytea,
    ADD COLUMN received_result_raw          bytea;

-- The dedup key is exactly the ten frozen columns: assert the column set
-- never drifted (D6 "去重键恰 10 列").
CREATE OR REPLACE FUNCTION v_effect_audit_dedup_key_columns()
RETURNS text[]
LANGUAGE sql STABLE AS $$
    SELECT array_agg(a.attname ORDER BY k.ord)
      FROM pg_constraint c,
           LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord),
           pg_attribute a
     WHERE c.conrelid = 'effect_audit'::regclass
       AND c.contype = 'u'
       AND a.attrelid = c.conrelid
       AND a.attnum = k.attnum;
$$;

-- ---------------------------------------------------------------------------
-- 2. Internal sub-operation audit rows (D14 — created HERE; the compact
--    stage only consumes it).
-- ---------------------------------------------------------------------------
CREATE TABLE internal_op_audits (
    internal_audit_id       bigserial PRIMARY KEY,
    parent_session_id       uuid NOT NULL,
    parent_command_id       text NOT NULL,
    internal_op_ordinal     bigint NOT NULL
                            CONSTRAINT internal_op_audits_ordinal_check
                            CHECK (internal_op_ordinal >= 0),
    internal_op_kind        text NOT NULL
                            CONSTRAINT internal_op_audits_kind_check
                            CHECK (internal_op_kind IN ('failure_drain',
                                                        'shared_cancel_closure',
                                                        'compact_terminal_abort',
                                                        'infra_closure',
                                                        'generation_revocation_drain')),
    source_operation        text,
    target_identity         text,
    event_key               text,
    parent_receipt_ref      text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT internal_op_audits_ordinal_unique
        UNIQUE (parent_session_id, parent_command_id, internal_op_ordinal),
    CONSTRAINT internal_op_audits_event_key_unique
        UNIQUE (parent_session_id, event_key)
);

-- ---------------------------------------------------------------------------
-- 3. Received-binding occurrence rows (D7).
--    value_raw is the masked-byte domain: any decoded member name equal to
--    `idempotency_key` was replaced by its SHA-256 hex at receipt time.
-- ---------------------------------------------------------------------------
CREATE TABLE effect_audit_binding_occurrences (
    audit_id        bigint NOT NULL
                    REFERENCES effect_audit(audit_id),
    occurrence_no   bigint NOT NULL
                    CONSTRAINT effect_audit_binding_occ_no_check
                    CHECK (occurrence_no >= 0),
    field_name_raw  bytea NOT NULL,
    type_tag        text NOT NULL
                    CONSTRAINT effect_audit_binding_occ_tag_check
                    CHECK (type_tag IN ('TEXT', 'NUMBER', 'BOOLEAN',
                                        'JSON', 'NULL')),
    value_raw       bytea NOT NULL,
    PRIMARY KEY (audit_id, occurrence_no)
);

-- ---------------------------------------------------------------------------
-- 4. Received-result occurrence rows (D7). The tag domain adds RAW, produced
--    only by the single `__raw_invalid__` row of the corrupt path.
-- ---------------------------------------------------------------------------
CREATE TABLE effect_audit_result_occurrences (
    audit_id        bigint NOT NULL
                    REFERENCES effect_audit(audit_id),
    occurrence_no   bigint NOT NULL
                    CONSTRAINT effect_audit_result_occ_no_check
                    CHECK (occurrence_no >= 0),
    field_name_raw  bytea NOT NULL,
    type_tag        text NOT NULL
                    CONSTRAINT effect_audit_result_occ_tag_check
                    CHECK (type_tag IN ('TEXT', 'NUMBER', 'BOOLEAN',
                                        'JSON', 'NULL', 'RAW')),
    value_raw       bytea NOT NULL,
    PRIMARY KEY (audit_id, occurrence_no)
);

-- ---------------------------------------------------------------------------
-- 5. Immutability: every audit carrier is append-only (rows MUST NOT be
--    updated or deleted; the GUC-protected lifecycle channel does not apply
--    to audit rows).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION v_audit_row_immutable()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'v8: audit carrier % is append-only (no UPDATE/DELETE)', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER audit_binding_occurrences_immutable
    BEFORE UPDATE OR DELETE ON effect_audit_binding_occurrences
    FOR EACH ROW EXECUTE FUNCTION v_audit_row_immutable();

CREATE TRIGGER audit_result_occurrences_immutable
    BEFORE UPDATE OR DELETE ON effect_audit_result_occurrences
    FOR EACH ROW EXECUTE FUNCTION v_audit_row_immutable();

CREATE TRIGGER internal_op_audits_immutable
    BEFORE UPDATE OR DELETE ON internal_op_audits
    FOR EACH ROW EXECUTE FUNCTION v_audit_row_immutable();

-- ---------------------------------------------------------------------------
-- 6. Byte-level replay: the fingerprint of an occurrence set is the SHA-256
--    over the ordered concatenation of the frozen per-occurrence framing
--    [8B BE name length][name][tag ASCII]0x00[8B BE value length][value].
--    This SQL side MUST stay byte-identical to the Python reference
--    (v8/canonical/keys.py) so the golden vectors can be cross-checked.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION v_occurrence_bytes(
    p_field_name_raw bytea, p_type_tag text, p_value_raw bytea
) RETURNS bytea
LANGUAGE sql IMMUTABLE AS $$
    SELECT int8send(octet_length(p_field_name_raw)) || p_field_name_raw
        || convert_to(p_type_tag, 'UTF8') || '\x00'::bytea
        || int8send(octet_length(p_value_raw)) || p_value_raw;
$$;

CREATE OR REPLACE FUNCTION v_binding_occurrences_fingerprint(p_audit_id bigint)
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_hex text;
BEGIN
    SELECT coalesce(string_agg(
               encode(v_occurrence_bytes(field_name_raw, type_tag, value_raw),
                      'hex'), '' ORDER BY occurrence_no), '')
      INTO v_hex
      FROM effect_audit_binding_occurrences
     WHERE audit_id = p_audit_id;
    -- Empty occurrence sequence encodes as the empty byte sequence.
    RETURN encode(sha256(decode(v_hex, 'hex')), 'hex');
END;
$$;

CREATE OR REPLACE FUNCTION v_result_occurrences_fingerprint(p_audit_id bigint)
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_hex text;
BEGIN
    SELECT coalesce(string_agg(
               encode(v_occurrence_bytes(field_name_raw, type_tag, value_raw),
                      'hex'), '' ORDER BY occurrence_no), '')
      INTO v_hex
      FROM effect_audit_result_occurrences
     WHERE audit_id = p_audit_id;
    -- Empty occurrence sequence encodes as the empty byte sequence.
    RETURN encode(sha256(decode(v_hex, 'hex')), 'hex');
END;
$$;

-- ---------------------------------------------------------------------------
-- 7. The three rejection paths (D5) and the independent ingress rejection
--    store (D10).
--
--    v8 has no real transport/ingress host (the P0C pinned-host decision is
--    open), so the contract surface is delivered DB-side with raw bytes as
--    inputs — the G13 precedent. The real transport wiring stays out of
--    scope and MUST NOT be recorded as green.
--
--    Path semantics (frozen ordering: (b) before (c)):
--      (a) the ID cannot be attributed        -> transport_rejection_key@v1,
--          command_id NOT occupied, recorded in the independent ingress
--          store only;
--      (b) transport malformed (valid ID)     -> transport_rejection_key@v1
--          AND command_id occupied;
--      (c) transport valid, payload not canonicalizable -> rejection_
--          fingerprint@v1, routed through and occupying command_id.
--    The three key kinds are mutually exclusive and MUST NOT be mixed; the
--    accepted namespace carries only canonical_request_hash.
-- ---------------------------------------------------------------------------
CREATE TABLE ingress_rejections (
    rejection_id            bigserial PRIMARY KEY,
    rejection_key_kind      text NOT NULL
                            CONSTRAINT ingress_rejections_kind_check
                            CHECK (rejection_key_kind IN
                                   ('transport_rejection_key')),
    rejection_key_value     text NOT NULL,
    -- Bound to the authorized calling context (never to untrusted input).
    audit_context_session_id uuid NOT NULL,
    frame_raw               bytea NOT NULL,
    created_at              timestamptz NOT NULL DEFAULT now(),
    -- Idempotent resend of the same frame merges into one row.
    CONSTRAINT ingress_rejections_key_unique
        UNIQUE (rejection_key_kind, rejection_key_value,
                audit_context_session_id)
);

CREATE OR REPLACE FUNCTION v_ingress_reject(
    p_frame_raw          bytea,
    p_payload_raw        bytea,   -- NULL: payload boundary not locatable
    p_canonicalizable    boolean, -- NULL: not applicable on this path
    p_id_assignable      boolean,
    p_calling_session_id uuid
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_kind  text;
    v_value text;
    v_path  text;
    v_occupies boolean;
BEGIN
    -- (b) precedes (c): a malformed transport never reaches the payload
    -- canonicalization judgement.
    IF NOT p_id_assignable THEN
        v_path := 'a';
        v_kind := 'transport_rejection_key';
        v_value := encode(sha256(p_frame_raw), 'hex');
        v_occupies := false;
    ELSIF p_payload_raw IS NULL THEN
        v_path := 'b';
        v_kind := 'transport_rejection_key';
        v_value := encode(sha256(p_frame_raw), 'hex');
        v_occupies := true;
    ELSIF p_canonicalizable IS NOT TRUE THEN
        v_path := 'c';
        v_kind := 'rejection_fingerprint';
        v_value := encode(sha256(p_payload_raw), 'hex');
        v_occupies := true;
    ELSE
        RAISE EXCEPTION
            'v8: v_ingress_reject is a rejection path only (canonicalizable '
            'input MUST NOT be routed here)';
    END IF;

    IF v_path = 'a' THEN
        -- Independent ingress storage: no command_bindings row, no
        -- command_id occupation. Same frame resend merges (idempotent).
        INSERT INTO ingress_rejections(rejection_key_kind, rejection_key_value,
                                       audit_context_session_id, frame_raw)
        VALUES (v_kind, v_value, p_calling_session_id, p_frame_raw)
        ON CONFLICT (rejection_key_kind, rejection_key_value,
                     audit_context_session_id) DO NOTHING;
    END IF;

    RETURN jsonb_build_object(
        'path', v_path,
        'rejection_key_kind', v_kind,
        'rejection_key_value', v_value,
        'command_id_occupied', v_occupies);
END;
$$;

-- The accepted namespace carries only the canonical computed hash: any
-- other key kind presented as an accepted key is refused.
CREATE OR REPLACE FUNCTION v_assert_accepted_key_kind(p_kind text)
RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
    SELECT p_kind = 'canonical_request_hash';
$$;

-- ---------------------------------------------------------------------------
-- 8. effect_audit full-column writer (D9 contract surface). Every structural
--    reject writes exactly one audit row with the expected side read from the
--    persisted control state and the received side stored masked.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION v_effect_audit_write(
    p_audit_context_session_id uuid,
    p_audit_key_kind      text,
    p_audit_key_value     text,
    p_result_fingerprint  text,
    p_reason              text,
    p_command_id          text DEFAULT NULL,
    p_result_hash         text DEFAULT NULL,
    p_result_parse_path   text DEFAULT 'empty',
    p_raw_invalid_class   text DEFAULT NULL,
    p_binding_invalid_class text DEFAULT NULL,
    p_session_id          uuid DEFAULT NULL,
    p_step_id             uuid DEFAULT NULL,
    p_effect_id           uuid DEFAULT NULL,
    p_attempt_no          bigint DEFAULT NULL,
    p_received_binding_raw bytea DEFAULT NULL,
    p_received_result_raw  bytea DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_audit_id bigint;
BEGIN
    INSERT INTO effect_audit(
        audit_context_session_id, audit_key_kind, audit_key_value,
        result_fingerprint, reason, command_id, result_hash,
        result_parse_path, raw_invalid_class, binding_invalid_class,
        session_id, step_id, effect_id, attempt_no,
        received_binding_raw, received_result_raw)
    VALUES (
        p_audit_context_session_id, p_audit_key_kind, p_audit_key_value,
        p_result_fingerprint, p_reason, p_command_id, p_result_hash,
        p_result_parse_path, p_raw_invalid_class, p_binding_invalid_class,
        p_session_id, p_step_id, p_effect_id, p_attempt_no,
        p_received_binding_raw, p_received_result_raw)
    -- The ten-column dedup key collapses a byte-identical repeat: the same
    -- binding resend is idempotent (one row), a different result under the
    -- same binding yields a second row.
    ON CONFLICT (audit_context_session_id, effect_id, attempt_no,
                 audit_key_kind, audit_key_value, result_fingerprint, reason,
                 internal_op_kind, parent_command_id, internal_op_ordinal)
        DO NOTHING
    RETURNING audit_id INTO v_audit_id;
    IF v_audit_id IS NULL THEN
        SELECT audit_id INTO v_audit_id FROM effect_audit
         WHERE audit_context_session_id = p_audit_context_session_id
           AND effect_id IS NOT DISTINCT FROM p_effect_id
           AND attempt_no IS NOT DISTINCT FROM p_attempt_no
           AND audit_key_kind = p_audit_key_kind
           AND audit_key_value = p_audit_key_value
           AND result_fingerprint = p_result_fingerprint
           AND reason = p_reason
           AND internal_op_kind IS NULL
           AND parent_command_id IS NULL
           AND internal_op_ordinal IS NULL;
    END IF;
    RETURN v_audit_id;
END;
$$;
