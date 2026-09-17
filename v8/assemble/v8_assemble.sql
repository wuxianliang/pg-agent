-- v8 G19a (assemble stage): the §2 seam checkpoints and the two-phase
-- assemble manifest snapshot — v10's Plan/Bind prerequisite (§3.3: fold,
-- recall, catalog, grant and policy bind ONE manifest hash; inject fixes
-- the assembly_cutoff_seq; the manifest freezes only "what the model sees
-- this round" — dispatch re-validates real-time and the snapshot never
-- exempts it, delivered by G12 and only regression-asserted here).
--
-- DB-layer shape (plan G19 D1–D6):
--   * assembly_manifests — the per-session manifest rows. The five source
--     digests are caller-supplied TEXT digests (the v10 runtime computes
--     them; v8's frozen contract is the BINDING: one versioned hash over
--     the five labeled digests + the cutoff, rows immutable after create).
--   * v_assemble_manifest — the assemble command. Any binding failure
--     (a missing source / a declared hash that does not match the
--     recomputed one) is the REAL INFRA_ASSEMBLY_FAILED trigger point
--     (plan G19 D5): the same transaction runs the G15 class-(3) closure
--     and the session fails closed — never a partial manifest.
--   * v_seam_check — the six same-transaction grant checkpoints
--     (recall/fold/env_read/env_write/tool_resolve/authorize_effect),
--     each a v_grant_find_valid lookup with parameter-level judgment
--     (v_gate_params target/path/bytes for authorize_effect, D3).
--     Denial is zero-side-effect with an independent authorization-reject
--     audit row (the G10 namespace-outside pattern).
--   * v_tool_resolve — the seam plus the frozen-set judgment (D2): the
--     resolved tool MUST be a member of the catalog generation whose
--     digest equals the manifest's frozen source_catalog; tools outside
--     the frozen snapshot never appear.
--
-- Lock order: session row first (position 1), then the manifest row; the
-- seam checks take the grant/slice locks inside v_grant_lock_judge (the
-- G12 master-order position), never out of order.

-- ---------------------------------------------------------------------------
-- 1. assembly_manifests (DDL frozen).
-- ---------------------------------------------------------------------------
CREATE TABLE assembly_manifests (
    session_id          uuid NOT NULL REFERENCES sessions(session_id),
    manifest_id         bigint NOT NULL CHECK (manifest_id >= 1),
    manifest_version    text NOT NULL DEFAULT 'assembly-manifest@v1',
    -- The frozen inject cutoff: events with seq <= cutoff are visible to
    -- THIS round; later ones wait for the next assemble (§3.3).
    assembly_cutoff_seq bigint NOT NULL CHECK (assembly_cutoff_seq >= 0),
    source_fold         text NOT NULL,
    source_recall       text NOT NULL,
    source_catalog      text NOT NULL,
    source_grant        text NOT NULL,
    source_policy       text NOT NULL,
    manifest_hash       text NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, manifest_id)
);

CREATE FUNCTION v8_assembly_manifests_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'assembly_manifests rows are immutable (session %, manifest %)',
        OLD.session_id, OLD.manifest_id;
END;
$$;
CREATE TRIGGER trg_assembly_manifests_immutable
BEFORE UPDATE OR DELETE ON assembly_manifests
FOR EACH ROW EXECUTE FUNCTION v8_assembly_manifests_immutable();

-- The versioned manifest hash, compact-style framing:
-- SHA-256("v8:assemble-manifest@v1" NUL len8(session_id) session_id
--         len8(cutoff) cutoff len8(fold) fold ... len8(policy) policy)
-- (len8 = 8-byte big-endian segment length; segments are UTF-8 BYTE
-- lengths — octet_length, never character length, so the standalone
-- hashlib mirror is byte-identical for non-ASCII digests; the
-- manifest_version label is NOT a hash input — only a version bump may
-- change this formula).
CREATE FUNCTION v_assemble_manifest_hash(
    p_session_id uuid, p_cutoff bigint,
    p_fold text, p_recall text, p_catalog text,
    p_grant text, p_policy text
) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT encode(sha256(
        convert_to('v8:assemble-manifest@v1', 'UTF8') || '\x00'::bytea
        || int8send(octet_length(convert_to(p_session_id::text, 'UTF8'))::bigint)
        || convert_to(p_session_id::text, 'UTF8')
        || int8send(octet_length(convert_to(p_cutoff::text, 'UTF8'))::bigint)
        || convert_to(p_cutoff::text, 'UTF8')
        || int8send(octet_length(convert_to(p_fold, 'UTF8'))::bigint)
        || convert_to(p_fold, 'UTF8')
        || int8send(octet_length(convert_to(p_recall, 'UTF8'))::bigint)
        || convert_to(p_recall, 'UTF8')
        || int8send(octet_length(convert_to(p_catalog, 'UTF8'))::bigint)
        || convert_to(p_catalog, 'UTF8')
        || int8send(octet_length(convert_to(p_grant, 'UTF8'))::bigint)
        || convert_to(p_grant, 'UTF8')
        || int8send(octet_length(convert_to(p_policy, 'UTF8'))::bigint)
        || convert_to(p_policy, 'UTF8')), 'hex');
$$;

-- ---------------------------------------------------------------------------
-- 2. v_assemble_manifest — the assemble command (two-phase snapshot,
--    phase A: generation). Every binding failure is the REAL
--    INFRA_ASSEMBLY_FAILED trigger (plan G19 D5): same-transaction G15
--    class-(3) closure, zero partial manifest.
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_assemble_manifest(
    p_session_id uuid,
    p_fold text, p_recall text, p_catalog text,
    p_grant text, p_policy text,
    p_declared_hash text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_sess sessions%ROWTYPE;
    v_cutoff bigint;
    v_hash text;
    v_id bigint;
    v_closure jsonb;
BEGIN
    SELECT * INTO v_sess FROM sessions s
     WHERE s.session_id = p_session_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'SESSION_NOT_FOUND');
    END IF;

    -- Binding validation BEFORE any persistence: all five sources present
    -- (a missing source cannot bind) and the declared hash equals the
    -- recomputed one (five sources bind ONE manifest hash).
    IF p_fold IS NULL OR p_recall IS NULL OR p_catalog IS NULL
       OR p_grant IS NULL OR p_policy IS NULL
       OR p_fold = '' OR p_recall = '' OR p_catalog = ''
       OR p_grant = '' OR p_policy = '' THEN
        v_closure := v_failure_drain_core(p_session_id,
            'INFRA_ASSEMBLY_FAILED',
            'assemble: a manifest source is missing (five sources must '
            'bind one hash)', 'infra:INFRA_ASSEMBLY_FAILED',
            'infra_drain');
        RETURN jsonb_build_object('outcome', 'accepted',
                                  'closure', v_closure,
                                  'code', 'INFRA_ASSEMBLY_FAILED');
    END IF;

    v_cutoff := v_sess.next_seq - 1;
    v_hash := v_assemble_manifest_hash(p_session_id, v_cutoff,
                                       p_fold, p_recall, p_catalog,
                                       p_grant, p_policy);
    IF p_declared_hash IS NULL OR p_declared_hash <> v_hash THEN
        v_closure := v_failure_drain_core(p_session_id,
            'INFRA_ASSEMBLY_FAILED',
            format('assemble: the declared hash does not match the '
                   'recomputed five-source binding (declared %s, computed %s)',
                   coalesce(p_declared_hash, 'NULL'), v_hash),
            'infra:INFRA_ASSEMBLY_FAILED', 'infra_drain');
        RETURN jsonb_build_object('outcome', 'accepted',
                                  'closure', v_closure,
                                  'code', 'INFRA_ASSEMBLY_FAILED');
    END IF;
    IF v_cutoff IS NULL OR v_cutoff < 0 THEN
        v_closure := v_failure_drain_core(p_session_id,
            'INFRA_ASSEMBLY_FAILED',
            'assemble: the cutoff snapshot is incomplete',
            'infra:INFRA_ASSEMBLY_FAILED', 'infra_drain');
        RETURN jsonb_build_object('outcome', 'accepted',
                                  'closure', v_closure,
                                  'code', 'INFRA_ASSEMBLY_FAILED');
    END IF;

    SELECT coalesce(max(manifest_id), 0) + 1 INTO v_id
      FROM assembly_manifests WHERE session_id = p_session_id;
    INSERT INTO assembly_manifests(
        session_id, manifest_id, assembly_cutoff_seq,
        source_fold, source_recall, source_catalog, source_grant,
        source_policy, manifest_hash)
    VALUES (p_session_id, v_id, v_cutoff,
            p_fold, p_recall, p_catalog, p_grant, p_policy, v_hash);

    RETURN jsonb_build_object(
        'outcome', 'accepted',
        'manifest_id', v_id,
        'manifest_hash', v_hash,
        'assembly_cutoff_seq', v_cutoff);
END;
$$;

-- ---------------------------------------------------------------------------
-- 3. v_seam_check — the six same-transaction grant checkpoints (D1/D3).
--    Authorization precedes everything; denial is zero-side-effect with
--    an independent authorization-reject audit row (outside the command
--    receipt namespace, the G10 pattern).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_seam_check(
    p_session_id uuid, p_seam text,
    p_target text DEFAULT NULL, p_path text DEFAULT NULL,
    p_bytes bigint DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_grant_id text;
BEGIN
    IF p_seam NOT IN ('recall', 'fold', 'env_read', 'env_write',
                      'tool_resolve', 'authorize_effect') THEN
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'SEAM_UNKNOWN');
    END IF;
    -- The parameter object mirrors the effect stage's v_gate_params shape
    -- (command/target/path/bytes) but is built inline: v_gate_params lives
    -- in the effect stage, and this stage's databases stop before it.
    v_grant_id := v_grant_find_valid(
        p_session_id, p_seam, NULL, NULL, NULL, NULL,
        jsonb_build_object('command', p_seam, 'target', p_target,
                           'path', p_path, 'bytes', p_bytes));
    IF v_grant_id IS NULL THEN
        INSERT INTO grant_ops_audit(operator_id, action, target_id, details)
        VALUES ('system', 'seam_denied', p_session_id::text,
                jsonb_build_object('seam', p_seam, 'target', p_target,
                                   'code', 'GRANT_DENIED'));
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'GRANT_DENIED',
                                  'seam', p_seam);
    END IF;
    RETURN jsonb_build_object('outcome', 'accepted', 'seam', p_seam,
                              'grant_id', v_grant_id);
END;
$$;

-- ---------------------------------------------------------------------------
-- 4. v_tool_resolve — the seam plus the frozen-set judgment (D2). The
--    resolved tool MUST be a member of the catalog generation whose
--    digest equals the LATEST manifest's frozen source_catalog; tools
--    outside the frozen snapshot never appear (the visible set == the
--    frozen set). Generation revocation still gates real-time through the
--    G11/G12 machinery (regression-asserted by those gates).
-- ---------------------------------------------------------------------------
CREATE FUNCTION v_tool_resolve(
    p_session_id uuid, p_tool_identity text
) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    v_seam jsonb;
    v_catalog text;
    v_member boolean;
BEGIN
    v_seam := v_seam_check(p_session_id, 'tool_resolve',
                           'tool:' || p_tool_identity, NULL, NULL);
    IF (v_seam->>'outcome') <> 'accepted' THEN
        RETURN v_seam;
    END IF;

    SELECT m.source_catalog INTO v_catalog
      FROM assembly_manifests m
     WHERE m.session_id = p_session_id
     ORDER BY m.manifest_id DESC LIMIT 1;
    IF v_catalog IS NULL THEN
        INSERT INTO grant_ops_audit(operator_id, action, target_id, details)
        VALUES ('system', 'tool_resolve_denied', p_session_id::text,
                jsonb_build_object('tool', p_tool_identity,
                                   'code', 'MANIFEST_MISSING'));
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'MANIFEST_MISSING',
                                  'tool', p_tool_identity);
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM generation_members gm
          JOIN generations g ON g.generation_id = gm.generation_id
          JOIN plugin_implementations pi
            ON pi.implementation_id = gm.implementation_id
         WHERE pi.identity = p_tool_identity
           AND g.generation_digest = v_catalog)
      INTO v_member;
    IF NOT v_member THEN
        INSERT INTO grant_ops_audit(operator_id, action, target_id, details)
        VALUES ('system', 'tool_resolve_denied', p_session_id::text,
                jsonb_build_object('tool', p_tool_identity,
                                   'code', 'TOOL_NOT_IN_FROZEN_CATALOG',
                                   'frozen_catalog', v_catalog));
        RETURN jsonb_build_object('outcome', 'rejected_mismatch',
                                  'code', 'TOOL_NOT_IN_FROZEN_CATALOG',
                                  'tool', p_tool_identity);
    END IF;
    RETURN jsonb_build_object('outcome', 'accepted',
                              'tool', p_tool_identity,
                              'grant_id', v_seam->>'grant_id',
                              'frozen_catalog', v_catalog);
END;
$$;
