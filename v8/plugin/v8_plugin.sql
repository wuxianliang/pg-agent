-- v8 G11: the §4 plugin generation domain — table family DDL, the stable
-- dependency resolution, the generation digest, the publish lifecycle
-- (building -> {active, failed}), the steps generation binding columns, the
-- shared generation-check sub-operation (delivered for G12 wiring) and the
-- active -> failed offline revocation transaction (seven-item protocol).
--
-- Source of truth: docs/designs/v8-dev.md §4 (frozen spec), digest
-- docs/analysis/v8-impl-digest/s33-s4-compact-plugin.md §1.5-§1.7 (tables),
-- §2.9 (publish + offline seven items), §3.7 (dependency resolution order),
-- §4.3 (generation lifecycle), §2.10 (runtime/readiness contract),
-- Conformance 8 (spec §6 line 846: (i)-(v), (ix), (x) reachable in this
-- stage; (vi)/(viii) seal/allocation races need the G12 gate wiring).
--
-- Load-order position (see v8/load.py): AFTER events, BEFORE the effect
-- stage — steps gain catalog_generation + the implementation binding column
-- with the DEFAULT seed generation here, and the effect/retry/cancel stages
-- (and this stage's own drain) consume the generation domain. Function
-- references into later stages (v_aggregate_step / v_apply_step_aggregation
-- / v_retry_stop_reason_cas) resolve at call time, so earlier stage
-- databases that stop before the retry stage can still load this file.
--
-- G11 scope guards (explicit): the seal/dispatch/retry-cohort generation
-- GATES (GENERATION_REVOKED rejection wiring) belong to G12 — this stage
-- delivers only the shared read sub-operation v_step_generation_status for
-- that wiring and MUST NOT touch v8_effect/v8_tools/v8_retry/v8_takeover.
-- The grant-stage linearization locks are not inserted here either (G12).
--
-- The seed generation is bootstrapped by direct INSERT (the publish flow is
-- validated independently by the G11 gate); the fixed id
-- 00000000-0000-4000-8000-000000000001 is the DEFAULT generation binding of
-- every step row created before/without an explicit catalog generation
-- (backfilled rows are indistinguishable from seed-bound rows).

-- ---------------------------------------------------------------------------
-- plugin_specs (§4, s33 §1.5) — catalog declaration rows, immutable after
-- creation (the operator declares; publishing never rewrites a spec).
-- ---------------------------------------------------------------------------
CREATE TABLE plugin_specs (
    identity           text NOT NULL,
    contract_version   text NOT NULL,
    portability        text NOT NULL DEFAULT 'native',
    fixture_digest     text,
    required_services  jsonb NOT NULL DEFAULT '[]'::jsonb,
    provided_services  jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (identity, contract_version)
);

CREATE FUNCTION v8_plugin_specs_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'plugin_specs rows are immutable after creation (identity=%, '
        'contract_version=%)', OLD.identity, OLD.contract_version;
END;
$$;

CREATE TRIGGER trg_plugin_specs_immutable
BEFORE UPDATE OR DELETE ON plugin_specs
FOR EACH ROW EXECUTE FUNCTION v8_plugin_specs_immutable();

-- ---------------------------------------------------------------------------
-- plugin_implementations (§4, s33 §1.6) — GLOBALLY immutable entities.
-- Unique key frozen: (identity, contract_version, locus, driver,
-- plugin_version) — driver only distinguishes the carrying runtime, so
-- native and compat implementations of the same logical plugin coexist as
-- distinct rows. The (identity, contract_version) -> plugin_specs binding
-- is a real FK: rows without a matching spec cannot enter the catalog or a
-- generation. first_published_generation_id is provenance only.
-- ---------------------------------------------------------------------------
CREATE TABLE plugin_implementations (
    implementation_id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    identity                      text NOT NULL,
    contract_version              text NOT NULL,
    plugin_version                text NOT NULL,
    driver                        text NOT NULL,
    locus                         text NOT NULL,
    entry                         text NOT NULL,
    implementation_digest         text NOT NULL,
    first_published_generation_id uuid,
    created_at                    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (identity, contract_version, locus, driver, plugin_version),
    FOREIGN KEY (identity, contract_version)
        REFERENCES plugin_specs (identity, contract_version)
);

-- UPDATE is always rejected (no rewrite path for an immutable entity).
-- DELETE is only legal through the protected GC function (unreferenced
-- generation GC); a shared implementation row referenced by any living
-- generation is never deleted (the GC function checks references before
-- deleting, and the GUC guard below blocks every other path).
CREATE FUNCTION v8_plugin_implementations_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION
            'plugin_implementations rows are globally immutable (no UPDATE; '
            'identity=% plugin_version=%)', OLD.identity, OLD.plugin_version;
    END IF;
    IF coalesce(current_setting('v8.generation_gc', true), '') <> 'on' THEN
        RAISE EXCEPTION
            'plugin_implementations rows may only be deleted by the '
            'unreferenced-generation GC sub-operation';
    END IF;
    RETURN OLD;
END;
$$;

CREATE TRIGGER trg_plugin_implementations_guard
BEFORE UPDATE OR DELETE ON plugin_implementations
FOR EACH ROW EXECUTE FUNCTION v8_plugin_implementations_guard();

-- ---------------------------------------------------------------------------
-- generations (§4, s33 §4.3) — lifecycle building -> {active, failed},
-- active -> {retired, failed}. Status transitions happen only through the
-- protected lifecycle functions below (v_build_generation /
-- v_activate_generation / v_fail_generation_building / v_retire_generation /
-- v_revoke_generation); direct UPDATE/DELETE is rejected.
-- ---------------------------------------------------------------------------
CREATE TABLE generations (
    generation_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    status            text NOT NULL DEFAULT 'building'
                      CONSTRAINT generations_status_check
                      CHECK (status IN ('building', 'active', 'failed',
                                        'retired')),
    generation_digest text NOT NULL,
    failure_code      text,
    failure_detail    text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION v8_generations_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF coalesce(current_setting('v8.generation_lifecycle', true), '') <> 'on' THEN
        RAISE EXCEPTION
            'generations rows may only be modified by the protected '
            'lifecycle functions (status=%)', OLD.status;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;      -- allow the GC delete (RETURN NEW is NULL on
    END IF;              -- DELETE and would silently skip the row)
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_generations_guard
BEFORE UPDATE OR DELETE ON generations
FOR EACH ROW EXECUTE FUNCTION v8_generations_guard();

-- ---------------------------------------------------------------------------
-- generation_members (§4, s33 §1.7) — the ONLY membership expression: a
-- generation's content is the full set of its member rows. Member rows are
-- written only in publish transactions and are immutable afterwards; they
-- are deleted only by the unreferenced-generation GC.
-- ---------------------------------------------------------------------------
CREATE TABLE generation_members (
    generation_id     uuid NOT NULL REFERENCES generations(generation_id),
    implementation_id uuid NOT NULL
        REFERENCES plugin_implementations(implementation_id),
    included_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (generation_id, implementation_id)
);

CREATE FUNCTION v8_generation_members_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION
            'generation_members rows are immutable after the publish '
            'transaction (generation=%)', OLD.generation_id;
    END IF;
    IF coalesce(current_setting('v8.generation_gc', true), '') <> 'on' THEN
        RAISE EXCEPTION
            'generation_members rows may only be deleted by the '
            'unreferenced-generation GC sub-operation';
    END IF;
    RETURN OLD;
END;
$$;

CREATE TRIGGER trg_generation_members_guard
BEFORE UPDATE OR DELETE ON generation_members
FOR EACH ROW EXECUTE FUNCTION v8_generation_members_guard();

-- first_published_generation_id is PROVENANCE ONLY (§4: it expresses no
-- ownership or membership and participates in no scheduling/catalog
-- judgment), so it carries NO hard FK: the unreferenced-generation GC
-- deletes a generation row whose shared, still-living implementation rows
-- cite as their first publisher (the frozen (identity, contract_version)
-- -> plugin_specs FK above is the binding the spec demands).

-- ---------------------------------------------------------------------------
-- catalog_config + catalog_pointer_history — the versioned active-pointer
-- configuration. The active pointer is operator-disposed explicitly
-- (activate / rollback / clear); it MUST NOT drift automatically. Every
-- disposition is persisted with operator, timestamp and target.
-- ---------------------------------------------------------------------------
CREATE TABLE catalog_config (
    id                   int PRIMARY KEY CHECK (id = 1),
    active_generation_id uuid REFERENCES generations(generation_id),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    updated_by           text NOT NULL DEFAULT 'bootstrap'
);

CREATE TABLE catalog_pointer_history (
    history_id        bigserial PRIMARY KEY,
    action            text NOT NULL,
    operator          text NOT NULL,
    target_generation uuid,
    detail            text,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- steps binding columns (A8 precedent: stage ALTER, not a schema change).
-- catalog_generation defaults to the seed generation — historical rows
-- backfilled by the ALTER are indistinguishable from explicitly seed-bound
-- rows. implementation_digest is the §4 "implementation binding column"
-- (steps fix catalog_generation + implementation identity; full binding at
-- seal time is wired by the later gate stages).
-- ---------------------------------------------------------------------------
ALTER TABLE steps
    ADD COLUMN catalog_generation uuid NOT NULL
        DEFAULT '00000000-0000-4000-8000-000000000001'::uuid
        REFERENCES generations(generation_id),
    ADD COLUMN implementation_digest text;

-- ---------------------------------------------------------------------------
-- v_json_str — JCS/json.dumps-compatible string escaping for the canonical
-- member/digest constructions below (mirrors Python json.dumps with
-- ensure_ascii=False: ", \, the five short control forms, \u00xx for other
-- control characters, non-ASCII verbatim UTF-8).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_json_str(p_text text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    i int;
    c text;
    v_out text := '';
BEGIN
    IF p_text IS NULL THEN
        RETURN 'null';
    END IF;
    FOR i IN 1 .. length(p_text) LOOP
        c := substr(p_text, i, 1);
        CASE
            WHEN c = '"' THEN v_out := v_out || '\"';
            WHEN c = '\' THEN v_out := v_out || '\\';
            WHEN c = chr(8) THEN v_out := v_out || '\b';
            WHEN c = chr(9) THEN v_out := v_out || '\t';
            WHEN c = chr(10) THEN v_out := v_out || '\n';
            WHEN c = chr(12) THEN v_out := v_out || '\f';
            WHEN c = chr(13) THEN v_out := v_out || '\r';
            WHEN ascii(c) < 32 THEN v_out := v_out || format('\u%04x', ascii(c));
            ELSE v_out := v_out || c;
        END CASE;
    END LOOP;
    RETURN '"' || v_out || '"';
END;
$$;

-- ---------------------------------------------------------------------------
-- v_plugin_version_key — dotted-numeric (major, minor, patch) numeric
-- comparison key; missing segments pad to 0 (§4 frozen). NULL for a
-- malformed version (the build scan rejects those candidates).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_plugin_version_key(p_version text) RETURNS int[]
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_parts text[];
    v_nums int[];
    i int;
BEGIN
    IF p_version IS NULL OR p_version = '' THEN
        RETURN NULL;
    END IF;
    v_parts := string_to_array(p_version, '.');
    IF array_length(v_parts, 1) > 3 THEN
        RETURN NULL;
    END IF;
    FOR i IN 1 .. array_length(v_parts, 1) LOOP
        IF v_parts[i] !~ '^[0-9]+$' THEN
            RETURN NULL;
        END IF;
        v_nums[i] := v_parts[i]::int;
    END LOOP;
    WHILE coalesce(array_length(v_nums, 1), 0) < 3 LOOP
        v_nums := array_append(v_nums, 0);
    END LOOP;
    RETURN v_nums;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_version_range_match — dotted-numeric range matcher for `requires`.
-- Grammar (self-defined, documented): '*' or '' = any; otherwise a
-- comma-separated conjunction of comparators
--   >=X.Y.Z | >X.Y.Z | <=X.Y.Z | <X.Y.Z | =X.Y.Z | X.Y.Z (exact)
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_version_range_match(p_range text, p_version text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_ver int[] := v_plugin_version_key(p_version);
    v_terms text[];
    t text;
    v_op text;
    v_bound text;
    v_key int[];
BEGIN
    IF v_ver IS NULL THEN
        RETURN false;
    END IF;
    IF p_range IS NULL OR trim(p_range) = '' OR trim(p_range) = '*' THEN
        RETURN true;
    END IF;
    v_terms := string_to_array(p_range, ',');
    FOREACH t IN ARRAY v_terms LOOP
        t := trim(t);
        CONTINUE WHEN t = '';
        v_op := '=';
        v_bound := t;
        IF t LIKE '>=%' THEN v_op := '>='; v_bound := substr(t, 3);
        ELSIF t LIKE '<=%' THEN v_op := '<='; v_bound := substr(t, 3);
        ELSIF t LIKE '>%' THEN v_op := '>'; v_bound := substr(t, 2);
        ELSIF t LIKE '<%' THEN v_op := '<'; v_bound := substr(t, 2);
        ELSIF t LIKE '=%' THEN v_op := '='; v_bound := substr(t, 2);
        END IF;
        v_bound := trim(v_bound);
        v_key := v_plugin_version_key(v_bound);
        IF v_key IS NULL THEN
            RETURN false;
        END IF;
        IF NOT ((v_op = '>=' AND v_ver >= v_key)
                OR (v_op = '>' AND v_ver > v_key)
                OR (v_op = '<=' AND v_ver <= v_key)
                OR (v_op = '<' AND v_ver < v_key)
                OR (v_op = '=' AND v_ver = v_key)) THEN
            RETURN false;
        END IF;
    END LOOP;
    RETURN true;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_require_range_wellformed — scan-time range grammar check (each
-- comma-separated term: optional comparator + dotted-numeric bound).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_require_range_wellformed(p_range text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    t text;
    v_bound text;
BEGIN
    IF p_range IS NULL OR trim(p_range) = '' OR trim(p_range) = '*' THEN
        RETURN true;
    END IF;
    FOREACH t IN ARRAY string_to_array(p_range, ',') LOOP
        t := trim(t);
        CONTINUE WHEN t = '';
        v_bound := t;
        IF t LIKE '>=%' OR t LIKE '<=%' THEN v_bound := substr(t, 3);
        ELSIF t LIKE '>%' OR t LIKE '<%' OR t LIKE '=%' THEN
            v_bound := substr(t, 2);
        END IF;
        IF v_plugin_version_key(trim(v_bound)) IS NULL THEN
            RETURN false;
        END IF;
    END LOOP;
    RETURN true;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_member_sort_key — the FROZEN stable-order key (§4):
--   priority DESC, identity ASC, plugin_version ASC (dotted-numeric),
--   ties broken by driver then implementation_id — all string comparisons
--   by RAW UTF-8 byte order (code point order, never the database locale;
--   NO length prefixes here: the key's lexicographic order must equal the
--   frozen string comparison, and a length-first encoding would reorder
--   e.g. 'B-upper' after 'a-low'). Composite key: u64be(2^62 - priority)
--   || identity bytes || u64be-major/minor/patch || driver bytes
--   || implementation_id bytes.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_member_sort_key(p_member jsonb) RETURNS bytea
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_priority bigint;
    v_ver int[];
BEGIN
    v_priority := coalesce((p_member->>'priority')::bigint, 0);
    IF v_priority < -4611686018427387904
       OR v_priority > 4611686018427387904 THEN
        RAISE EXCEPTION 'priority out of the frozen sort-key domain';
    END IF;
    v_ver := v_plugin_version_key(p_member->>'plugin_version');
    RETURN v_u64be(4611686018427387904 - v_priority)
        || v_identity_bytes(coalesce(p_member->>'identity', ''))
        || v_u64be(coalesce(v_ver[1], 0)) || v_u64be(coalesce(v_ver[2], 0))
        || v_u64be(coalesce(v_ver[3], 0))
        || v_identity_bytes(coalesce(p_member->>'driver', ''))
        || v_identity_bytes(coalesce(p_member->>'implementation_id', ''));
END;
$$;

-- ---------------------------------------------------------------------------
-- v_generation_member_digest — generation digest over the member list
-- (§4: MUST cover the member superset; two generations with different
-- member sets produce different digests). Canonical representation
-- (self-defined profile, deviation-noted): the compact JSON object
--   {"generation_digest_profile":"v8:generation-members@v1",
--    "members":[{...},...]}
-- with member records carrying exactly
--   contract_version, driver, identity, implementation_digest, locus,
--   plugin_version
-- in sorted-key order, members in the RESOLVED stable order (surrogate
-- implementation ids are excluded: member identity is the frozen unique
-- key + digest). Byte-level mirrored by the Python reference
-- v8/plugin/client.py generation_member_digest (SQL == Python asserted
-- with hand-computed golden vectors).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_generation_member_digest(p_members jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    v_parts text[] := ARRAY[]::text[];
    m jsonb;
BEGIN
    IF p_members IS NULL OR p_members = 'null'::jsonb THEN
        p_members := '[]'::jsonb;
    END IF;
    FOR m IN SELECT * FROM jsonb_array_elements(p_members) LOOP
        v_parts := array_append(v_parts,
            '{"contract_version":' || v_json_str(m->>'contract_version')
            || ',"driver":' || v_json_str(m->>'driver')
            || ',"identity":' || v_json_str(m->>'identity')
            || ',"implementation_digest":' || v_json_str(m->>'implementation_digest')
            || ',"locus":' || v_json_str(m->>'locus')
            || ',"plugin_version":' || v_json_str(m->>'plugin_version')
            || '}');
    END LOOP;
    RETURN v_sha256_hex(
        '{"generation_digest_profile":"v8:generation-members@v1","members":['
        || array_to_string(v_parts, ',') || ']}');
END;
$$;

-- ---------------------------------------------------------------------------
-- v_implementation_content_digest — the build's digest verification: the
-- declared implementation_digest must equal the recomputed digest over the
-- scanned implementation content (full scan + digest check, §4 publish
-- flow). Canonical object keys: content, contract_version, driver, entry,
-- identity, implementation_digest_profile ("v8:implementation-content@v1"),
-- locus, plugin_version.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_implementation_content_digest(p_member jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN v_sha256_hex(
        '{"content":' || v_json_str(p_member->>'content')
        || ',"contract_version":' || v_json_str(p_member->>'contract_version')
        || ',"driver":' || v_json_str(p_member->>'driver')
        || ',"entry":' || v_json_str(p_member->>'entry')
        || ',"identity":' || v_json_str(p_member->>'identity')
        || ',"implementation_digest_profile":"v8:implementation-content@v1"'
        || ',"locus":' || v_json_str(p_member->>'locus')
        || ',"plugin_version":' || v_json_str(p_member->>'plugin_version')
        || '}');
END;
$$;

-- ---------------------------------------------------------------------------
-- v_pre_dispatch_cancel_sync — the SHARED pre-dispatch dual-table atomic
-- sync sub-operation (G8a extraction; single implementation for the three
-- trigger sources: request_cancel, the §4 generation drain of this stage
-- and the WORKSPACE_LOST failure-drain of the grant stage).
--
-- FINAL HOME: grant/v8_grant.sql (the G10 branch delivers it there). On the
-- G11 branch v8_grant.sql is not merged yet, so the body is hosted here
-- with CREATE OR REPLACE so the cancel stage's call resolves (deviation
-- A62 in the ledger); the merge keeps one implementation.
--
-- For every `ready` effect of the session (optionally scoped to one
-- catalog generation) the SAME transaction flips effect_requests.status
-- and the current (max attempt_no) attempt row to
-- cancelled_before_dispatch and writes the ABORTED_BEFORE_DISPATCH audit
-- row; the step aggregation counters are then recomputed from the effect
-- table (authoritative). Returns the cancelled-effect jsonb array (the
-- cancel command's receipt member).
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
           AND (p_scope_generation_id IS NULL
                OR (SELECT st.catalog_generation FROM steps st
                     WHERE st.step_id = er.step_id) = p_scope_generation_id)
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
-- v_build_generation — the publish build phase: full scan, digest
-- verification, stable dependency resolution, member-set freeze and the
-- generation digest. Any build failure terminates the candidate
-- building -> failed (persisted) and MUST NOT touch the active pointer or
-- any bound step/job. Returns {outcome:'built'|'build_failed', ...} with
-- the ordered member projection (the resolution order is observable).
--
-- Manifest shape (self-defined, client-built):
--   {"candidates":[{identity, contract_version, plugin_version, driver,
--     locus, entry, content, implementation_digest, priority,
--     requires:[{identity, version, optional}],
--     provides:[{service, version}],
--     spec:{portability, fixture_digest, required_services,
--           provided_services}}]}
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_build_generation(p_manifest jsonb) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_gen uuid := gen_random_uuid();
    v_candidates jsonb;
    v_n int;
    m jsonb;
    req jsonb;
    prov jsonb;
    v_seen jsonb := '[]'::jsonb;
    v_placed jsonb := '[]'::jsonb;
    v_remaining jsonb := '[]'::jsonb;
    v_rounds int := 0;
    v_key text;
    v_existing record;
    v_dup jsonb;
    v_rec jsonb;
    v_eligible jsonb := '[]'::jsonb;
    v_best bytea;
    v_best_m jsonb := 'null'::jsonb;
    v_members jsonb := '[]'::jsonb;
    v_digest text;
    v_fresh jsonb := '[]'::jsonb;
BEGIN
    PERFORM set_config('v8.generation_lifecycle', 'on', true);
    INSERT INTO generations(generation_id, status, generation_digest)
    VALUES (v_gen, 'building', v_sha256_hex(''));

    v_candidates := coalesce(p_manifest->'candidates', '[]'::jsonb);
    IF jsonb_array_length(v_candidates) = 0 THEN
        UPDATE generations SET status = 'failed', failure_code = 'SCAN_INVALID',
               failure_detail = 'empty candidate set', updated_at = now()
         WHERE generation_id = v_gen;
        RETURN jsonb_build_object('outcome', 'build_failed', 'code', 'SCAN_INVALID',
                                  'detail', 'empty candidate set',
                                  'generation_id', v_gen);
    END IF;
    v_n := jsonb_array_length(v_candidates);

    -- ---- full scan + digest verification + key/reuse resolution ----
    FOR m IN SELECT * FROM jsonb_array_elements(v_candidates) LOOP
        IF coalesce(m->>'identity', '') = ''
           OR coalesce(m->>'contract_version', '') = ''
           OR coalesce(m->>'driver', '') = ''
           OR coalesce(m->>'locus', '') = ''
           OR coalesce(m->>'entry', '') = ''
           OR m->>'content' IS NULL
           OR coalesce(m->>'plugin_version', '') = ''
           OR coalesce(m->>'implementation_digest', '') = ''
           OR v_plugin_version_key(m->>'plugin_version') IS NULL THEN
            UPDATE generations SET status = 'failed', failure_code = 'SCAN_INVALID',
                   failure_detail = format('candidate %s has missing or malformed '
                                           'fields', coalesce(m->>'identity', '?')),
                   updated_at = now()
             WHERE generation_id = v_gen;
            RETURN jsonb_build_object('outcome', 'build_failed',
                                      'code', 'SCAN_INVALID',
                                      'detail', 'candidate field validation failed',
                                      'generation_id', v_gen);
        END IF;
        FOR req IN SELECT * FROM jsonb_array_elements(
                       coalesce(m->'requires', '[]'::jsonb)) LOOP
            IF coalesce(req->>'identity', '') = ''
               OR NOT v_require_range_wellformed(req->>'version') THEN
                UPDATE generations SET status = 'failed', failure_code = 'SCAN_INVALID',
                       failure_detail = format('candidate %s has a malformed require',
                                               m->>'identity'), updated_at = now()
                 WHERE generation_id = v_gen;
                RETURN jsonb_build_object('outcome', 'build_failed',
                                          'code', 'SCAN_INVALID',
                                          'detail', 'malformed requires entry',
                                          'generation_id', v_gen);
            END IF;
        END LOOP;
        -- digest verification (full scan): declared digest == recomputed
        IF v_implementation_content_digest(m) IS DISTINCT FROM
           m->>'implementation_digest' THEN
            UPDATE generations SET status = 'failed', failure_code = 'DIGEST_MISMATCH',
                   failure_detail = format('candidate %s declared digest does not '
                                           'match the scanned content',
                                           m->>'identity'), updated_at = now()
             WHERE generation_id = v_gen;
            RETURN jsonb_build_object('outcome', 'build_failed',
                                      'code', 'DIGEST_MISMATCH',
                                      'detail', m->>'identity', 'generation_id', v_gen);
        END IF;
        -- duplicate resolution on the frozen unique key (within this
        -- manifest): same key + same digest dedupes (refresh), same key +
        -- different digest is a content change without a version bump.
        v_key := (m->>'identity') || '|' || (m->>'contract_version') || '|'
                 || (m->>'locus') || '|' || (m->>'driver') || '|'
                 || (m->>'plugin_version');
        v_dup := 'null'::jsonb;
        FOR v_rec IN SELECT * FROM jsonb_array_elements(v_seen) LOOP
            IF v_rec->>'_key' = v_key THEN
                v_dup := v_rec;
                EXIT;
            END IF;
        END LOOP;
        IF v_dup <> 'null'::jsonb THEN
            IF v_dup->>'implementation_digest' IS DISTINCT FROM
               m->>'implementation_digest' THEN
                UPDATE generations SET status = 'failed',
                       failure_code = 'CONTENT_CHANGE_NEEDS_VERSION_BUMP',
                       failure_detail = format('candidate key %s re-declared with '
                                               'a different digest; content change '
                                               'MUST bump plugin_version', v_key),
                       updated_at = now()
                 WHERE generation_id = v_gen;
                RETURN jsonb_build_object('outcome', 'build_failed',
                                          'code', 'CONTENT_CHANGE_NEEDS_VERSION_BUMP',
                                          'detail', v_key, 'generation_id', v_gen);
            END IF;
            CONTINUE;   -- exact duplicate of an accepted candidate: dedupe
        END IF;
        -- existing immutable row lookup (refresh reuse / stable rejection)
        SELECT implementation_id, implementation_digest
          INTO v_existing
          FROM plugin_implementations
         WHERE identity = m->>'identity'
           AND contract_version = m->>'contract_version'
           AND locus = m->>'locus'
           AND driver = m->>'driver'
           AND plugin_version = m->>'plugin_version';
        IF v_existing.implementation_id IS NOT NULL THEN
            IF v_existing.implementation_digest IS DISTINCT FROM
               m->>'implementation_digest' THEN
                UPDATE generations SET status = 'failed',
                       failure_code = 'CONTENT_CHANGE_NEEDS_VERSION_BUMP',
                       failure_detail = format('republish of key %s with a different '
                                               'digest (immutable entity, no rewrite '
                                               'path)', v_key), updated_at = now()
                 WHERE generation_id = v_gen;
                RETURN jsonb_build_object('outcome', 'build_failed',
                                          'code', 'CONTENT_CHANGE_NEEDS_VERSION_BUMP',
                                          'detail', v_key, 'generation_id', v_gen);
            END IF;
            m := m || jsonb_build_object(
                'implementation_id', v_existing.implementation_id,
                '_reused', true, '_key', v_key);
        ELSE
            m := m || jsonb_build_object(
                'implementation_id', gen_random_uuid(),
                '_reused', false, '_key', v_key);
            v_fresh := v_fresh || jsonb_build_object(
                'implementation_id', m->>'implementation_id',
                'identity', m->>'identity',
                'contract_version', m->>'contract_version',
                'plugin_version', m->>'plugin_version',
                'driver', m->>'driver',
                'locus', m->>'locus',
                'entry', m->>'entry',
                'implementation_digest', m->>'implementation_digest');
        END IF;
        v_seen := v_seen || m;
        v_remaining := v_remaining || m;
    END LOOP;

    -- ---- duplicate-provide detection (same driver scope) ----
    FOR m IN SELECT * FROM jsonb_array_elements(v_seen) LOOP
        FOR prov IN SELECT * FROM jsonb_array_elements(
                         coalesce(m->'provides', '[]'::jsonb)) LOOP
            IF EXISTS (
                SELECT 1
                  FROM jsonb_array_elements(v_seen) o,
                       jsonb_array_elements(coalesce(o->'provides', '[]'::jsonb)) op
                 WHERE o->>'_key' <> m->>'_key'
                   AND o->>'driver' = m->>'driver'
                   AND op->>'service' = prov->>'service') THEN
                UPDATE generations SET status = 'failed',
                       failure_code = 'DUPLICATE_PROVIDE',
                       failure_detail = format('service %s provided twice within '
                                               'driver %s', prov->>'service',
                                               m->>'driver'), updated_at = now()
                 WHERE generation_id = v_gen;
                RETURN jsonb_build_object('outcome', 'build_failed',
                                          'code', 'DUPLICATE_PROVIDE',
                                          'detail', prov->>'service',
                                          'generation_id', v_gen);
            END IF;
        END LOOP;
    END LOOP;

    -- ---- stable topological resolution (Kahn with the frozen key) ----
    WHILE jsonb_array_length(v_remaining) > 0 LOOP
        v_rounds := v_rounds + 1;
        IF v_rounds > v_n + 1 THEN
            -- stuck: classify cycle vs version mismatch
            FOR m IN SELECT * FROM jsonb_array_elements(v_remaining) LOOP
                FOR req IN SELECT * FROM jsonb_array_elements(
                               coalesce(m->'requires', '[]'::jsonb)) LOOP
                    CONTINUE WHEN coalesce(req->>'optional', 'false')::boolean;
                    IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_seen) c
                                    WHERE c->>'identity' = req->>'identity') THEN
                        UPDATE generations SET status = 'failed',
                               failure_code = 'VERSION_MISMATCH',
                               failure_detail = format('require %s %s has no candidate',
                                                       req->>'identity',
                                                       coalesce(req->>'version', '*')),
                               updated_at = now()
                         WHERE generation_id = v_gen;
                        RETURN jsonb_build_object('outcome', 'build_failed',
                                                  'code', 'VERSION_MISMATCH',
                                                  'detail', req->>'identity',
                                                  'generation_id', v_gen);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(v_seen) c
                                    WHERE c->>'identity' = req->>'identity'
                                      AND v_version_range_match(
                                              coalesce(req->>'version', '*'),
                                              c->>'plugin_version')) THEN
                        UPDATE generations SET status = 'failed',
                               failure_code = 'VERSION_MISMATCH',
                               failure_detail = format('require %s %s matched no '
                                                       'candidate version',
                                                       req->>'identity',
                                                       coalesce(req->>'version', '*')),
                               updated_at = now()
                         WHERE generation_id = v_gen;
                        RETURN jsonb_build_object('outcome', 'build_failed',
                                                  'code', 'VERSION_MISMATCH',
                                                  'detail', req->>'identity',
                                                  'generation_id', v_gen);
                    END IF;
                END LOOP;
            END LOOP;
            UPDATE generations SET status = 'failed', failure_code = 'DEPENDENCY_CYCLE',
                   failure_detail = 'dependency cycle among the candidates',
                   updated_at = now()
             WHERE generation_id = v_gen;
            RETURN jsonb_build_object('outcome', 'build_failed',
                                      'code', 'DEPENDENCY_CYCLE',
                                      'detail', 'unresolvable candidate set',
                                      'generation_id', v_gen);
        END IF;
        -- eligible: every non-optional require satisfied by a placed member
        v_eligible := '[]'::jsonb;
        FOR m IN SELECT * FROM jsonb_array_elements(v_remaining) LOOP
            IF NOT EXISTS (
                    SELECT 1
                      FROM jsonb_array_elements(coalesce(m->'requires', '[]'::jsonb)) rq
                     WHERE coalesce(rq->>'optional', 'false')::boolean = false
                       AND NOT EXISTS (
                            SELECT 1 FROM jsonb_array_elements(v_placed) p
                             WHERE p->>'identity' = rq->>'identity'
                               AND v_version_range_match(
                                       coalesce(rq->>'version', '*'),
                                       p->>'plugin_version'))) THEN
                v_eligible := v_eligible || m;
            END IF;
        END LOOP;
        IF jsonb_array_length(v_eligible) = 0 THEN
            v_rounds := v_n + 2;   -- force the stuck classification next pass
            CONTINUE;
        END IF;
        -- pick the smallest frozen sort key (stable total order)
        v_best := NULL;
        FOR m IN SELECT * FROM jsonb_array_elements(v_eligible) LOOP
            IF v_best IS NULL OR v_member_sort_key(m) < v_best THEN
                v_best := v_member_sort_key(m);
                v_best_m := m;
            END IF;
        END LOOP;
        v_placed := v_placed || v_best_m;
        v_remaining := (
            SELECT coalesce(jsonb_agg(e), '[]'::jsonb)
              FROM jsonb_array_elements(v_remaining) e
             WHERE e->>'_key' <> v_best_m->>'_key');
    END LOOP;

    -- ---- member freeze + generation digest (resolved stable order) ----
    FOR m IN SELECT * FROM jsonb_array_elements(v_placed) LOOP
        v_members := v_members || jsonb_build_object(
            'identity', m->>'identity',
            'contract_version', m->>'contract_version',
            'locus', m->>'locus',
            'driver', m->>'driver',
            'plugin_version', m->>'plugin_version',
            'implementation_digest', m->>'implementation_digest',
            'implementation_id', m->>'implementation_id');
    END LOOP;
    v_digest := v_generation_member_digest(v_members);

    -- ---- writes: specs (operator declaration), fresh implementations,
    --      members, digest ----
    FOR m IN SELECT * FROM jsonb_array_elements(v_seen) LOOP
        INSERT INTO plugin_specs(identity, contract_version, portability,
                                 fixture_digest, required_services,
                                 provided_services)
        VALUES (m->>'identity', m->>'contract_version',
                coalesce(m->'spec'->>'portability', 'native'),
                m->'spec'->>'fixture_digest',
                coalesce(m->'spec'->'required_services', '[]'::jsonb),
                coalesce(m->'spec'->'provided_services', '[]'::jsonb))
        ON CONFLICT (identity, contract_version) DO NOTHING;
    END LOOP;
    FOR m IN SELECT * FROM jsonb_array_elements(v_fresh) LOOP
        INSERT INTO plugin_implementations(
            implementation_id, identity, contract_version, plugin_version,
            driver, locus, entry, implementation_digest,
            first_published_generation_id)
        VALUES ((m->>'implementation_id')::uuid, m->>'identity',
                m->>'contract_version', m->>'plugin_version', m->>'driver',
                m->>'locus', m->>'entry', m->>'implementation_digest', v_gen);
    END LOOP;
    FOR m IN SELECT * FROM jsonb_array_elements(v_members) LOOP
        INSERT INTO generation_members(generation_id, implementation_id)
        VALUES (v_gen, (m->>'implementation_id')::uuid);
    END LOOP;
    UPDATE generations SET generation_digest = v_digest, updated_at = now()
     WHERE generation_id = v_gen;

    RETURN jsonb_build_object(
        'outcome', 'built', 'generation_id', v_gen,
        'generation_digest', v_digest, 'members', v_members);
END;
$$;

-- ---------------------------------------------------------------------------
-- v_activate_generation — the atomic publish switch: building -> active,
-- the previous active generation -> retired, the catalog active pointer :=
-- the new generation and the versioned history row, all in ONE transaction
-- (no intermediate state is observable). Guard: the generation must still
-- be building (a failed/retired/already-active row cannot activate).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_activate_generation(
    p_generation_id uuid, p_operator text DEFAULT 'operator'
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_status text;
    v_prev uuid;
BEGIN
    SELECT status INTO v_status FROM generations
     WHERE generation_id = p_generation_id FOR UPDATE;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'v8: generation % not found', p_generation_id;
    END IF;
    IF v_status <> 'building' THEN
        RAISE EXCEPTION
            'v8: only a building generation can activate (status=%)', v_status;
    END IF;
    PERFORM set_config('v8.generation_lifecycle', 'on', true);
    SELECT active_generation_id INTO v_prev FROM catalog_config WHERE id = 1;
    UPDATE generations SET status = 'retired', updated_at = now()
     WHERE generation_id = v_prev AND status = 'active';
    UPDATE generations SET status = 'active', updated_at = now()
     WHERE generation_id = p_generation_id;
    UPDATE catalog_config SET active_generation_id = p_generation_id,
                              updated_at = now(), updated_by = p_operator
     WHERE id = 1;
    INSERT INTO catalog_pointer_history(action, operator, target_generation)
    VALUES ('activate', p_operator, p_generation_id);
    RETURN jsonb_build_object('outcome', 'activated',
                              'generation_id', p_generation_id,
                              'retired', v_prev);
END;
$$;

-- ---------------------------------------------------------------------------
-- v_fail_generation_building — terminate a building candidate as failed
-- (used for the readiness/preload failure arm of the publish flow; any
-- build-phase failure inside v_build_generation writes the same terminal
-- row itself). MUST NOT touch the active pointer.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_fail_generation_building(
    p_generation_id uuid, p_failure_code text, p_failure_detail text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_status text;
BEGIN
    SELECT status INTO v_status FROM generations
     WHERE generation_id = p_generation_id FOR UPDATE;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'v8: generation % not found', p_generation_id;
    END IF;
    IF v_status <> 'building' THEN
        RAISE EXCEPTION
            'v8: only a building generation can fail the build (status=%)',
            v_status;
    END IF;
    PERFORM set_config('v8.generation_lifecycle', 'on', true);
    UPDATE generations SET status = 'failed', failure_code = p_failure_code,
           failure_detail = p_failure_detail, updated_at = now()
     WHERE generation_id = p_generation_id;
    RETURN jsonb_build_object('outcome', 'build_failed', 'code', p_failure_code,
                              'detail', p_failure_detail,
                              'generation_id', p_generation_id);
END;
$$;

-- ---------------------------------------------------------------------------
-- v_retire_generation — the controlled active -> retired disposition
-- (already-bound steps/jobs keep using the generation; retired is NOT
-- restricted by the revocation protocol).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_retire_generation(
    p_generation_id uuid, p_operator text DEFAULT 'operator'
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_status text;
BEGIN
    SELECT status INTO v_status FROM generations
     WHERE generation_id = p_generation_id FOR UPDATE;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'v8: generation % not found', p_generation_id;
    END IF;
    IF v_status <> 'active' THEN
        RAISE EXCEPTION
            'v8: only an active generation can retire (status=%)', v_status;
    END IF;
    PERFORM set_config('v8.generation_lifecycle', 'on', true);
    UPDATE generations SET status = 'retired', updated_at = now()
     WHERE generation_id = p_generation_id;
    UPDATE catalog_config SET active_generation_id = NULL, updated_at = now(),
                              updated_by = p_operator
     WHERE id = 1 AND active_generation_id = p_generation_id;
    INSERT INTO catalog_pointer_history(action, operator, target_generation)
    VALUES ('retire', p_operator, p_generation_id);
    RETURN jsonb_build_object('outcome', 'retired',
                              'generation_id', p_generation_id);
END;
$$;

-- ---------------------------------------------------------------------------
-- v_catalog_pointer_dispose — the EXPLICIT operator disposition of the
-- active pointer (rollback to an earlier usable generation, or clear).
-- Versioned and auditable; no automatic drift anywhere.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_catalog_pointer_dispose(
    p_action text, p_target uuid, p_operator text DEFAULT 'operator'
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_cur uuid;
    v_status text;
BEGIN
    SELECT active_generation_id INTO v_cur FROM catalog_config WHERE id = 1;
    IF p_action = 'clear' THEN
        UPDATE catalog_config SET active_generation_id = NULL, updated_at = now(),
                                  updated_by = p_operator
         WHERE id = 1;
        INSERT INTO catalog_pointer_history(action, operator, target_generation)
        VALUES ('clear', p_operator, NULL);
    ELSIF p_action = 'point' THEN
        SELECT status INTO v_status FROM generations
         WHERE generation_id = p_target FOR UPDATE;
        IF v_status IS NULL THEN
            RAISE EXCEPTION 'v8: pointer target generation % not found', p_target;
        END IF;
        IF v_status = 'failed' THEN
            RAISE EXCEPTION
                'v8: the pointer MUST NOT serve through a failed generation';
        END IF;
        PERFORM set_config('v8.generation_lifecycle', 'on', true);
        IF v_cur IS NOT NULL AND v_cur <> p_target THEN
            UPDATE generations SET status = 'retired', updated_at = now()
             WHERE generation_id = v_cur AND status = 'active';
        END IF;
        UPDATE generations SET status = 'active', updated_at = now()
         WHERE generation_id = p_target AND status IN ('retired', 'building');
        UPDATE catalog_config SET active_generation_id = p_target,
                                  updated_at = now(), updated_by = p_operator
         WHERE id = 1;
        INSERT INTO catalog_pointer_history(action, operator, target_generation)
        VALUES ('rollback', p_operator, p_target);
    ELSE
        RAISE EXCEPTION 'v8: pointer action must be clear or point, got %', p_action;
    END IF;
    RETURN jsonb_build_object('outcome', 'disposed', 'action', p_action,
                              'target', p_target, 'previous', v_cur);
END;
$$;

-- ---------------------------------------------------------------------------
-- v_generation_close_step — the offline drain's per-step closure (§4 item
-- 5: EXISTING aggregation rules take priority; the failed_terminal /
-- GENERATION_REVOKED closure fires only on the frozen three-conjunction).
-- Callers hold the session and generation row locks.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_generation_close_step(
    p_session_id uuid, p_step_id uuid, p_generation_id uuid, p_revoke_id text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_agg record;
    v_step steps%ROWTYPE;
    v_sess sessions%ROWTYPE;
    v_member uuid;
    v_att bigint;
    v_fingerprint text;
    v_was_claimed boolean;
    v_fence bigint;
    v_closure text;
BEGIN
    SELECT * INTO v_step FROM steps WHERE step_id = p_step_id;
    SELECT * INTO v_sess FROM sessions WHERE session_id = p_session_id;
    SELECT * INTO v_agg FROM v_aggregate_step(p_step_id);

    IF v_agg.rule_no IN (1, 2, 3, 4) THEN
        -- Existing aggregation rules finalize the step (unknown blocked /
        -- pending waiting / cancel-wins / rule-4 terminal): their derived
        -- status and code MUST NOT be overwritten by GENERATION_REVOKED.
        PERFORM v_apply_step_aggregation(
            p_session_id, p_step_id, v_agg.rule_no, v_agg.step_status,
            v_agg.outcome_code, v_agg.session_state, v_agg.failure_code,
            v_agg.closure_effect_ids, p_revoke_id, p_revoke_id);
        RETURN jsonb_build_object('step_id', p_step_id, 'closure',
                                  'existing_rule', 'rule_no', v_agg.rule_no);
    END IF;

    -- rule 5 (pure eligible failed_retryable) or rule 6 (no failure
    -- siblings): the three-conjunction — cannot continue through the failed
    -- generation (a drained member, an unsealed plan needing a new seal, or
    -- a retryable member needing a new dispatch), cannot finalize through
    -- the existing rules, and no unresolved unknown/pending.
    IF EXISTS (SELECT 1 FROM effect_requests er
                WHERE er.step_id = p_step_id
                  AND er.status = 'cancelled_before_dispatch')
       OR (v_step.status = 'ready' AND v_step.stage = 'decision')
       OR v_agg.rule_no = 5 THEN
        v_closure := 'generation_revoked';
        -- residual failed_retryable members: the controlled edge
        -- failed_retryable -> failed_terminal (original failure code kept,
        -- retry_stop_reason persisted through the R-01 CAS writer).
        FOR v_member IN
            SELECT er.effect_id FROM effect_requests er
             WHERE er.step_id = p_step_id AND er.status = 'failed_retryable'
             ORDER BY er.dispatch_ordinal
        LOOP
            UPDATE effect_requests SET status = 'failed_terminal',
                                       updated_at = now()
             WHERE effect_id = v_member AND status = 'failed_retryable';
            SELECT max(a.attempt_no) INTO v_att FROM effect_attempts a
             WHERE a.effect_id = v_member;
            UPDATE effect_attempts SET status = 'failed_terminal',
                                       completed_at = now()
             WHERE effect_id = v_member AND attempt_no = v_att
               AND status = 'failed_retryable';
            PERFORM v_retry_stop_reason_cas(v_member);
            SELECT coalesce(er.result_hash,
                            v_sha256_hex(p_revoke_id || ':' || v_member::text))
              INTO v_fingerprint
              FROM effect_requests er WHERE er.effect_id = v_member;
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id,
                attempt_no, audit_key_kind, audit_key_value,
                result_fingerprint, reason)
            VALUES (p_session_id, p_session_id, p_step_id, v_member, v_att,
                    'canonical_binding', p_generation_id::text, v_fingerprint,
                    'RETRY_STOPPED_BY_CLOSURE')
            ON CONFLICT DO NOTHING;
        END LOOP;
        -- an unsealed tools plan is voided; the decision result stays in
        -- the audit trail (Conformance 8 (i)).
        IF v_step.status = 'ready' AND v_step.stage = 'decision' THEN
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id,
                attempt_no, audit_key_kind, audit_key_value,
                result_fingerprint, reason)
            VALUES (p_session_id, NULL, NULL, NULL, NULL,
                    'canonical_binding', p_generation_id::text,
                    coalesce(v_step.plan_hash,
                             v_sha256_hex(coalesce(v_step.plan_canonical, ''))),
                    'GENERATION_REVOKED')
            ON CONFLICT DO NOTHING;
        END IF;
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
            status = 'failed_terminal',
            outcome_code = 'GENERATION_REVOKED',
            closed_at = coalesce(st.closed_at, now()),
            updated_at = now()
         WHERE st.step_id = p_step_id;
        -- session derivation: failed / GENERATION_REVOKED (fail_session
        -- class (1) source; a claimed session has its lease revoked and
        -- fence bumped in the same transaction).
        IF v_sess.state NOT IN ('completed', 'failed', 'cancelled') THEN
            v_was_claimed := (v_sess.state = 'claimed');
            IF v_was_claimed THEN
                v_fence := v_sess.session_fence + 1;
                UPDATE sessions SET
                    state = 'failed', failure_code = 'GENERATION_REVOKED',
                    session_fence = v_fence,
                    lease_owner = NULL, lease_until = NULL, lease_purpose = NULL,
                    active_step_id = NULL, updated_at = now()
                 WHERE session_id = p_session_id;
            ELSE
                UPDATE sessions SET
                    state = 'failed', failure_code = 'GENERATION_REVOKED',
                    active_step_id = p_step_id, updated_at = now()
                 WHERE session_id = p_session_id;
            END IF;
        END IF;
    ELSE
        v_closure := 'unaffected';
    END IF;
    RETURN jsonb_build_object('step_id', p_step_id, 'closure', v_closure);
END;
$$;

-- ---------------------------------------------------------------------------
-- v_revoke_generation — the §4 item-7 offline revocation transaction:
-- active -> failed, explicit operator pointer disposition, the
-- pre-dispatch drain over every session bound to the generation and the
-- per-step closure — ONE transaction under the frozen concurrency
-- protocol:
--   (a) total-order pre-lock of every bound session (UUID RFC 9562
--       16-byte binary order) — the session position precedes the
--       generation position of the master lock order;
--   (b) generation row EXCLUSIVE lock after the pre-lock completes;
--   (c) in-lock rescan of the binding set (READ COMMITTED fresh
--       statement snapshots);
--   (d) a newly bound session discovered in the lock -> whole-transaction
--       internal rollback to the savepoint and a fresh total-order
--       pre-lock (NEVER a reverse-order补lock);
--   (e) drain + closure + failed + pointer disposition in the final lock
--       set.
-- Entry guard: READ COMMITTED only — other isolation levels are stably
-- rejected ISOLATION_UNSUPPORTED before ANY lock is taken.
--
-- Test seam (G9b GUC precedent): 'v8.revoke_test_hide_session' (uuid)
-- removes that session from the FIRST pre-lock pass only, so the in-lock
-- rescan discovers it and the rollback-and-retry path is exercised
-- deterministically.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_revoke_generation(
    p_generation_id uuid,
    p_reason text,
    p_operator text DEFAULT 'operator',
    p_pointer_action text DEFAULT NULL,   -- NULL | 'clear' | 'point'
    p_pointer_target uuid DEFAULT NULL,
    p_revoke_id text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_gen generations%ROWTYPE;
    v_ptr uuid;
    v_set uuid[];
    v_rescan uuid[];
    v_sid uuid;
    v_attempts int := 0;
    v_retry boolean;
    v_hide text;
    v_drained jsonb := '[]'::jsonb;
    v_sync jsonb;
    v_closed jsonb := '[]'::jsonb;
    v_ordinal bigint := 0;
    r record;
BEGIN
    IF current_setting('transaction_isolation', true) IS DISTINCT FROM
       'read committed' THEN
        RAISE EXCEPTION
            'ISOLATION_UNSUPPORTED: the generation revocation transaction '
            'MUST run at READ COMMITTED (got %)',
            current_setting('transaction_isolation', true);
    END IF;

    SELECT * INTO v_gen FROM generations WHERE generation_id = p_generation_id;
    IF v_gen.generation_id IS NULL THEN
        RAISE EXCEPTION 'v8: generation % not found', p_generation_id;
    END IF;
    IF v_gen.status <> 'active' THEN
        RAISE EXCEPTION
            'v8 GENERATION_NOT_ACTIVE: only an active generation can be '
            'revoked (status=%)', v_gen.status;
    END IF;

    SELECT active_generation_id INTO v_ptr FROM catalog_config WHERE id = 1;
    IF v_ptr = p_generation_id THEN
        -- the pointer is still serving through this generation: the
        -- operator MUST dispose it explicitly in the same transaction.
        IF p_pointer_action IS NULL OR p_pointer_action NOT IN
           ('clear', 'point') THEN
            RAISE EXCEPTION
                'v8 POINTER_DISPOSITION_REQUIRED: revoking the active '
                'generation needs an explicit pointer disposition '
                '(clear or point)';
        END IF;
        IF p_pointer_action = 'point'
           AND (p_pointer_target IS NULL
                OR p_pointer_target = p_generation_id) THEN
            RAISE EXCEPTION
                'v8 POINTER_TARGET_INVALID: rollback needs a different, '
                'usable target generation';
        END IF;
    END IF;

    v_hide := coalesce(current_setting('v8.revoke_test_hide_session', true), '');

    -- (a)-(d) pre-lock / generation lock / in-lock rescan / rollback-retry.
    -- The whole-transaction internal rollback uses a PL/pgSQL exception
    -- block (an implicit savepoint): raising the retry sentinel inside the
    -- block rolls back to the block start, releasing EVERY lock taken in
    -- the pass, and the loop re-runs the total-order pre-lock from scratch
    -- (never a reverse-order补lock).
    v_retry := true;
    WHILE v_retry LOOP
        v_attempts := v_attempts + 1;
        IF v_attempts > 8 THEN
            RAISE EXCEPTION
                'v8 GENERATION_REVOCATION_RETRY_EXHAUSTED: new bindings kept '
                'arriving (the protocol convergence is conditional; deploy '
                'the admission-freeze option)';
        END IF;
        v_retry := false;
        BEGIN
            -- (a) total-order pre-lock of the CURRENT binding set.
            SELECT array_agg(sub.session_id ORDER BY v_uuid16(sub.session_id))
              INTO v_set
              FROM (SELECT DISTINCT s.session_id
                      FROM steps st
                      JOIN sessions s ON s.session_id = st.session_id
                     WHERE st.catalog_generation = p_generation_id
                       AND NOT (v_attempts = 1 AND v_hide <> ''
                                AND s.session_id = v_hide::uuid)) sub;
            v_set := coalesce(v_set, ARRAY[]::uuid[]);
            PERFORM 1 FROM sessions s
             WHERE s.session_id = ANY(v_set)
             ORDER BY v_uuid16(s.session_id)
             FOR UPDATE;

            -- (b) generation exclusive lock (after the pre-lock completes).
            PERFORM 1 FROM generations g
             WHERE g.generation_id = p_generation_id FOR UPDATE;

            -- (c) in-lock rescan of the binding set.
            SELECT array_agg(sub.session_id ORDER BY v_uuid16(sub.session_id))
              INTO v_rescan
              FROM (SELECT DISTINCT s.session_id
                      FROM steps st
                      JOIN sessions s ON s.session_id = st.session_id
                     WHERE st.catalog_generation = p_generation_id) sub;
            v_rescan := coalesce(v_rescan, ARRAY[]::uuid[]);
            IF v_rescan <> v_set THEN
                -- (d) newly bound session discovered: raise the retry
                -- sentinel — the exception block rolls the whole pass back.
                v_retry := true;
                RAISE EXCEPTION 'v8: revoke rescan retry (internal)';
            END IF;
        EXCEPTION WHEN OTHERS THEN
            IF NOT v_retry THEN
                RAISE;   -- a genuine error propagates
            END IF;
            -- rolled back to the implicit savepoint: all locks of the pass
            -- are released; loop and re-run the total-order pre-lock.
        END;
    END LOOP;

    -- (e) drain + closure + terminal state in the final lock set. The
    -- lifecycle GUC is (re)applied HERE: a savepoint rollback in loop
    -- iteration (d) undoes a transaction-local setting taken before it.
    PERFORM set_config('v8.generation_lifecycle', 'on', true);
    SELECT active_generation_id INTO v_ptr FROM catalog_config WHERE id = 1;
    IF p_revoke_id IS NULL THEN
        p_revoke_id := 'revoke-' || p_generation_id::text;
    END IF;
    FOREACH v_sid IN ARRAY v_set LOOP
        -- pre-dispatch dual-table sync, scoped to this failed generation's
        -- steps of the session (the shared sub-operation; in-flight
        -- dispatch_started work keeps its snapshot and completes).
        v_sync := v_pre_dispatch_cancel_sync(
            v_sid, p_revoke_id, 'canonical_binding', p_generation_id::text,
            'ABORTED_BEFORE_DISPATCH', p_generation_id);
        v_drained := v_drained || v_sync;
        -- the GENERATION_REVOKED audit context per drained effect.
        FOR r IN
            SELECT er.effect_id, er.step_id, er.attempt_no
              FROM effect_requests er
             WHERE er.session_id = v_sid
               AND er.status = 'cancelled_before_dispatch'
               AND (SELECT st.catalog_generation FROM steps st
                     WHERE st.step_id = er.step_id) = p_generation_id
             ORDER BY er.dispatch_ordinal
        LOOP
            INSERT INTO effect_audit(
                audit_context_session_id, session_id, step_id, effect_id,
                attempt_no, audit_key_kind, audit_key_value,
                result_fingerprint, reason, internal_op_kind,
                parent_command_id, internal_op_ordinal)
            VALUES (v_sid, v_sid, r.step_id, r.effect_id, r.attempt_no,
                    'canonical_binding', p_generation_id::text,
                    v_sha256_hex(p_revoke_id || ':' || r.effect_id::text),
                    'GENERATION_REVOKED', 'generation_revocation_drain',
                    p_revoke_id, v_ordinal)
            ON CONFLICT DO NOTHING;
            v_ordinal := v_ordinal + 1;
        END LOOP;
        -- step closure: existing rules first, three-conjunction otherwise.
        FOR r IN
            SELECT st.step_id FROM steps st
             WHERE st.session_id = v_sid
               AND st.catalog_generation = p_generation_id
               AND st.status NOT IN ('succeeded', 'failed_terminal', 'cancelled')
             ORDER BY st.created_at, st.step_id
        LOOP
            v_closed := v_closed || v_generation_close_step(
                v_sid, r.step_id, p_generation_id, p_revoke_id);
        END LOOP;
    END LOOP;

    -- generation terminal state + the explicit pointer disposition.
    UPDATE generations SET status = 'failed', failure_code = 'REVOKED',
           failure_detail = p_reason, updated_at = now()
     WHERE generation_id = p_generation_id;
    IF v_ptr = p_generation_id THEN
        IF p_pointer_action = 'clear' THEN
            UPDATE catalog_config SET active_generation_id = NULL,
                                      updated_at = now(), updated_by = p_operator
             WHERE id = 1;
        ELSE
            UPDATE catalog_config SET active_generation_id = p_pointer_target,
                                      updated_at = now(), updated_by = p_operator
             WHERE id = 1;
            UPDATE generations SET status = 'active', updated_at = now()
             WHERE generation_id = p_pointer_target AND status = 'retired';
        END IF;
        INSERT INTO catalog_pointer_history(action, operator, target_generation,
                                            detail)
        VALUES ('revoke', p_operator, p_pointer_target, p_reason);
    ELSE
        INSERT INTO catalog_pointer_history(action, operator, target_generation,
                                            detail)
        VALUES ('revoke', p_operator, NULL,
                'pointer already disposed elsewhere; no drift applied');
    END IF;

    RETURN jsonb_build_object(
        'outcome', 'revoked', 'generation_id', p_generation_id,
        'reason', p_reason, 'revoke_id', p_revoke_id,
        'prelocked_sessions', to_jsonb(v_set), 'attempts', v_attempts,
        'drained', v_drained, 'closed_steps', v_closed,
        'pointer_action', p_pointer_action, 'pointer_target', p_pointer_target);
END;
$$;

-- ---------------------------------------------------------------------------
-- v_gc_generation — unreferenced-generation GC: a failed/retired
-- generation that no step binds and that the pointer does not serve
-- through is deleted together with its member rows; implementation rows
-- still referenced by ANY living generation are shared and MUST NOT be
-- deleted. The GUC guard opens the protected DELETE path.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_gc_generation(p_generation_id uuid) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_status text;
    v_members int;
    v_unshared uuid[];
    v_deleted_impls uuid[];
    m uuid;
BEGIN
    SELECT status INTO v_status FROM generations
     WHERE generation_id = p_generation_id FOR UPDATE;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'v8: generation % not found', p_generation_id;
    END IF;
    IF v_status IN ('building', 'active') THEN
        RAISE EXCEPTION
            'v8: only a failed or retired generation can be collected '
            '(status=%)', v_status;
    END IF;
    IF EXISTS (SELECT 1 FROM steps st
                WHERE st.catalog_generation = p_generation_id) THEN
        RAISE EXCEPTION 'v8: generation % is still step-bound', p_generation_id;
    END IF;
    IF EXISTS (SELECT 1 FROM catalog_config
                WHERE id = 1 AND active_generation_id = p_generation_id) THEN
        RAISE EXCEPTION 'v8: generation % is still the active pointer',
            p_generation_id;
    END IF;
    SELECT count(*) INTO v_members FROM generation_members
     WHERE generation_id = p_generation_id;
    -- Snapshot the UNSHARED implementation set first (no member row in any
    -- OTHER generation); then delete this generation's member rows (so the
    -- member FK no longer pins them), then the unshared implementation
    -- rows, then the generation row. Shared rows survive untouched.
    SELECT array_agg(sub.implementation_id) INTO v_unshared
      FROM (SELECT gm.implementation_id
              FROM generation_members gm
             WHERE gm.generation_id = p_generation_id
               AND NOT EXISTS (SELECT 1 FROM generation_members g2
                                WHERE g2.implementation_id = gm.implementation_id
                                  AND g2.generation_id <> p_generation_id)
             ORDER BY gm.implementation_id) sub;
    PERFORM set_config('v8.generation_gc', 'on', true);
    PERFORM set_config('v8.generation_lifecycle', 'on', true);
    DELETE FROM generation_members WHERE generation_id = p_generation_id;
    FOREACH m IN ARRAY coalesce(v_unshared, ARRAY[]::uuid[]) LOOP
        DELETE FROM plugin_implementations
         WHERE implementation_id = m;
        v_deleted_impls := array_append(
            coalesce(v_deleted_impls, ARRAY[]::uuid[]), m);
    END LOOP;
    DELETE FROM generations WHERE generation_id = p_generation_id;
    RETURN jsonb_build_object('outcome', 'collected',
                              'generation_id', p_generation_id,
                              'member_rows', v_members,
                              'deleted_implementations',
                              to_jsonb(coalesce(v_deleted_impls, ARRAY[]::uuid[])));
END;
$$;

-- ---------------------------------------------------------------------------
-- v_step_generation_status — the SHARED generation-check sub-operation
-- delivered for the G12 gate wiring (seal / dispatch / retry-cohort read).
-- Takes the generation row FOR SHARE (the shared-read lock of the fixed
-- master order: after the session/grant-slice positions, before the
-- step/effect/attempt positions). Returns the bound generation's status;
-- NULL when the step carries no generation binding (G12 treats an unbound
-- step as non-failed).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_step_generation_status(p_step_id uuid) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    v_gen uuid;
    v_status text;
BEGIN
    SELECT catalog_generation INTO v_gen FROM steps WHERE step_id = p_step_id;
    IF v_gen IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT g.status INTO v_status FROM generations g
     WHERE g.generation_id = v_gen FOR SHARE;
    RETURN v_status;
END;
$$;

-- ---------------------------------------------------------------------------
-- v_assemble_bind_generation — the assemble-side pointer resolution: a new
-- assemble binds the session's active_catalog_generation to the current
-- catalog active pointer; while the pointer is cleared the assemble is
-- STABLY rejected NO_ACTIVE_GENERATION with ZERO control-state change (no
-- session/step/lease/fence mutation — the coordinator must explicitly
-- yield to return to ready).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_assemble_bind_generation(p_session_id uuid) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_ptr uuid;
    v_status text;
BEGIN
    SELECT active_generation_id INTO v_ptr FROM catalog_config WHERE id = 1;
    IF v_ptr IS NULL THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'NO_ACTIVE_GENERATION');
    END IF;
    SELECT status INTO v_status FROM generations WHERE generation_id = v_ptr;
    IF v_status IS NULL THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'NO_ACTIVE_GENERATION');
    END IF;
    UPDATE sessions SET active_catalog_generation = v_ptr, updated_at = now()
     WHERE session_id = p_session_id;
    RETURN jsonb_build_object('outcome', 'bound', 'generation_id', v_ptr,
                              'status', v_status);
END;
$$;

-- ---------------------------------------------------------------------------
-- seed generation bootstrap (direct insert; the publish flow is validated
-- independently by the G11 gate). The seed is born active and pointed;
-- activating the first real generation retires it (rollback re-activates).
-- ---------------------------------------------------------------------------
INSERT INTO generations(generation_id, status, generation_digest)
VALUES ('00000000-0000-4000-8000-000000000001'::uuid, 'active',
        v_generation_member_digest('[]'::jsonb));

INSERT INTO catalog_config(id, active_generation_id, updated_by)
VALUES (1, '00000000-0000-4000-8000-000000000001'::uuid, 'bootstrap');

INSERT INTO catalog_pointer_history(action, operator, target_generation, detail)
VALUES ('bootstrap', 'bootstrap',
        '00000000-0000-4000-8000-000000000001'::uuid,
        'seed generation (empty member set)');
