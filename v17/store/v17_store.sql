-- v17 G1: the jiti file store as Postgres tables (plan §3.1).
--
-- jiti persists a Lisp world as a directory tree: revision dirs with
-- manifest.sexp + world.sexp, a CURRENT pointer swapped by atomic rename +
-- fsync, and an append-only events.sexp journal. Here all of that becomes
-- rows: a revision INSERT and the CURRENT pointer CAS commit in the caller's
-- single transaction, so jiti's two-phase fsync dance collapses into one
-- COMMIT and the uncertain publication window disappears (the residual
-- "committed but connection dropped" case is v12 G3's unknown wall, already
-- handled there). Semantics ported, code written fresh (jiti has no LICENSE).

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

-- World registry: one row per persistent Lisp world (jiti has no equivalent;
-- worlds there are just store directories).
CREATE TABLE lisp_worlds (
    world_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL UNIQUE,
    package_name text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- revision dir + manifest.sexp + world.sexp. state_text is the
-- *print-readably* world state (data + defun source), isomorphic to jiti's
-- world.sexp. seq is per-world, no holes (allocated under advisory lock).
CREATE TABLE lisp_revisions (
    revision_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    world_id        uuid NOT NULL REFERENCES lisp_worlds (world_id),
    seq             int NOT NULL CHECK (seq >= 1),
    parent_id       uuid REFERENCES lisp_revisions (revision_id),
    state_text      text NOT NULL,
    manifest        jsonb NOT NULL DEFAULT '{}',
    sbcl_version    text NOT NULL,
    rollback_source uuid REFERENCES lisp_revisions (revision_id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (world_id, seq)
);

-- The CURRENT pointer. UPDATE is the pointer CAS; it must happen in the same
-- transaction as the revision INSERT it points at (see v17_publish_revision).
CREATE TABLE lisp_current (
    world_id    uuid PRIMARY KEY REFERENCES lisp_worlds (world_id),
    revision_id uuid NOT NULL REFERENCES lisp_revisions (revision_id),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- events.sexp journal. seq per world, no holes; event is the JSON rendering
-- of jiti's journal s-expressions (e.g. {"event":"operation-start",
-- "record":{...}}).
CREATE TABLE lisp_journal (
    world_id     uuid NOT NULL REFERENCES lisp_worlds (world_id),
    seq          bigint NOT NULL CHECK (seq >= 1),
    operation_id text,
    generation   int NOT NULL DEFAULT 0,
    event        jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (world_id, seq)
);

-- Append-only discipline, same as v12 events (revisions and journal are
-- history; lisp_current is control state and may UPDATE).
CREATE FUNCTION v17_store_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'v17: % is append-only (% on world % seq %)',
        TG_TABLE_NAME, TG_OP, OLD.world_id, OLD.seq;
END;
$$;

CREATE TRIGGER trg_lisp_revisions_append_only
    BEFORE UPDATE OR DELETE ON lisp_revisions
    FOR EACH ROW EXECUTE FUNCTION v17_store_append_only();

CREATE TRIGGER trg_lisp_journal_append_only
    BEFORE UPDATE OR DELETE ON lisp_journal
    FOR EACH ROW EXECUTE FUNCTION v17_store_append_only();

-- ---------------------------------------------------------------------------
-- Functions
-- ---------------------------------------------------------------------------

-- Publish: revision INSERT + CURRENT pointer CAS in one function, so the
-- caller's transaction is the atomic unit. Cross-process single-writer per
-- world via pg_advisory_xact_lock (jiti's in-process ownership mutex
-- upgraded; released automatically at COMMIT/ROLLBACK). seq is allocated
-- under that lock as max(seq)+1 — no holes per world.
--
-- p_manifest must carry the producer's lisp-implementation-version under
-- key "sbcl"; loading a revision across SBCL versions is refused by the
-- Lisp side comparing this value (drift = loud failure, plan §2/§7.4).
CREATE FUNCTION v17_publish_revision(p_world uuid, p_state_text text,
                                     p_manifest jsonb DEFAULT '{}',
                                     p_rollback_source uuid DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_parent uuid;
    v_seq    int;
    v_id     uuid;
    v_sbcl   text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM lisp_worlds WHERE world_id = p_world) THEN
        RAISE EXCEPTION 'v17: unknown world %', p_world;
    END IF;

    PERFORM pg_advisory_xact_lock(hashtext(p_world::text));

    SELECT c.revision_id INTO v_parent
      FROM lisp_current c WHERE c.world_id = p_world;

    SELECT coalesce(max(r.seq), 0) + 1 INTO v_seq
      FROM lisp_revisions r WHERE r.world_id = p_world;

    v_sbcl := p_manifest ->> 'sbcl';
    IF v_sbcl IS NULL OR length(v_sbcl) = 0 THEN
        RAISE EXCEPTION 'v17: manifest must carry key "sbcl" (lisp-implementation-version)';
    END IF;

    INSERT INTO lisp_revisions
        (world_id, seq, parent_id, state_text, manifest, sbcl_version,
         rollback_source)
    VALUES (p_world, v_seq, v_parent, p_state_text, p_manifest, v_sbcl,
            p_rollback_source)
    RETURNING revision_id INTO v_id;

    -- Pointer CAS, same transaction as the INSERT above.
    IF v_parent IS NULL THEN
        INSERT INTO lisp_current (world_id, revision_id)
        VALUES (p_world, v_id);
    ELSE
        UPDATE lisp_current
           SET revision_id = v_id, updated_at = now()
         WHERE world_id = p_world AND revision_id = v_parent;
        IF NOT FOUND THEN
            -- unreachable while everyone takes the advisory lock; means a
            -- writer bypassed the protocol
            RAISE EXCEPTION
                'v17: CURRENT pointer moved during publish for world %', p_world;
        END IF;
    END IF;
    RETURN v_id;
END;
$$;

-- Load: default target is the CURRENT pointer. Returns the full revision row;
-- the Lisp side validates sbcl_version against lisp-implementation-version
-- before importing state_text (jiti load-revision identity check).
CREATE FUNCTION v17_load_revision(p_world uuid, p_revision uuid DEFAULT NULL)
RETURNS TABLE(revision_id uuid, seq int, parent_id uuid, state_text text,
              manifest jsonb, sbcl_version text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_id uuid;
BEGIN
    IF p_revision IS NULL THEN
        SELECT c.revision_id INTO v_id
          FROM lisp_current c WHERE c.world_id = p_world;
        IF v_id IS NULL THEN
            RAISE EXCEPTION 'v17: no CURRENT revision for world %', p_world;
        END IF;
    ELSE
        v_id := p_revision;
    END IF;
    RETURN QUERY
        SELECT r.revision_id, r.seq, r.parent_id, r.state_text, r.manifest,
               r.sbcl_version
          FROM lisp_revisions r
         WHERE r.revision_id = v_id AND r.world_id = p_world;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v17: unknown revision % for world %', v_id, p_world;
    END IF;
END;
$$;

-- List: newest first, only the accepted CURRENT ancestry. Ported validation
-- of jiti list-revisions: sequence continuity (exactly 1..N), parent linkage
-- (seq k's parent is seq k-1; seq 1 has no parent), no cycles, no orphans
-- (every revision of the world is reachable from CURRENT). Violations raise.
CREATE FUNCTION v17_list_revisions(p_world uuid)
RETURNS TABLE(revision_id uuid, seq int, parent_id uuid,
              rollback_source uuid, created_at timestamptz)
LANGUAGE plpgsql VOLATILE AS $$  -- VOLATILE: materializes the ancestry walk in a temp table
DECLARE
    v_tip     uuid;
    v_count   int;
    v_max     int;
    v_min     int;
    v_bad     int;
    v_orphans int;
BEGIN
    SELECT c.revision_id INTO v_tip
      FROM lisp_current c WHERE c.world_id = p_world;
    IF v_tip IS NULL THEN
        RETURN;  -- no published revision yet: empty list
    END IF;

    DROP TABLE IF EXISTS _v17_ancestry;  -- survive repeat calls in one txn
    CREATE TEMP TABLE _v17_ancestry ON COMMIT DROP AS
    WITH RECURSIVE walk AS (
        SELECT r.revision_id, r.seq, r.parent_id, r.rollback_source,
               r.created_at, r.world_id
          FROM lisp_revisions r
         WHERE r.revision_id = v_tip
        UNION ALL
        SELECT r.revision_id, r.seq, r.parent_id, r.rollback_source,
               r.created_at, r.world_id
          FROM walk w
          JOIN lisp_revisions r ON r.revision_id = w.parent_id
    ) CYCLE revision_id SET is_cycle USING cycle_path
    SELECT walk.revision_id, walk.seq, walk.parent_id, walk.rollback_source,
           walk.created_at, walk.world_id, walk.is_cycle
      FROM walk;  -- qualified: OUT params shadow bare names; cycle_path not storable

    IF EXISTS (SELECT 1 FROM _v17_ancestry WHERE is_cycle) THEN
        RAISE EXCEPTION 'v17: revision ancestry has a cycle for world %', p_world;
    END IF;
    IF EXISTS (SELECT 1 FROM _v17_ancestry WHERE world_id <> p_world) THEN
        RAISE EXCEPTION
            'v17: revision ancestry crosses into another world from %', p_world;
    END IF;

    SELECT count(*), max(a.seq), min(a.seq) INTO v_count, v_max, v_min
      FROM _v17_ancestry a;
    IF v_min <> 1 OR v_max <> v_count THEN
        RAISE EXCEPTION
            'v17: revision sequence not contiguous (min % max % count %) for world %',
            v_min, v_max, v_count, p_world;
    END IF;

    -- parent linkage: seq 1 has no parent; seq k>1 has parent with seq k-1
    SELECT count(*) INTO v_bad
      FROM _v17_ancestry a
     WHERE (a.seq = 1 AND a.parent_id IS NOT NULL)
        OR (a.seq > 1 AND NOT EXISTS (
                SELECT 1 FROM _v17_ancestry p
                 WHERE p.revision_id = a.parent_id AND p.seq = a.seq - 1));
    IF v_bad > 0 THEN
        RAISE EXCEPTION 'v17: broken parent linkage in ancestry of world %',
            p_world;
    END IF;

    -- orphans: revisions of this world unreachable from CURRENT
    SELECT count(*) INTO v_orphans
      FROM lisp_revisions r
     WHERE r.world_id = p_world
       AND NOT EXISTS (SELECT 1 FROM _v17_ancestry a
                        WHERE a.revision_id = r.revision_id);
    IF v_orphans > 0 THEN
        RAISE EXCEPTION 'v17: % orphan revision(s) for world %',
            v_orphans, p_world;
    END IF;

    RETURN QUERY SELECT a.revision_id, a.seq, a.parent_id, a.rollback_source,
                        a.created_at
                   FROM _v17_ancestry a ORDER BY a.seq DESC;
END;
$$;

-- Journal append: no-hole seq per world under the same advisory lock
-- discipline as publish.
--
-- Operation events (operation-start / operation-finish) are validated on the
-- way in: v17_recover_operations groups by record->>'id', so a malformed
-- record (missing/empty id or status) would silently fold into or swallow
-- recovery state. Drift fails loudly here instead. The operation_id column is
-- kept consistent with the payload: it must equal record->>'id' when passed,
-- and is backfilled from it when omitted.
CREATE FUNCTION v17_append_journal(p_world uuid, p_event jsonb,
                                   p_operation_id text DEFAULT NULL,
                                   p_generation int DEFAULT 0)
RETURNS bigint
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    v_seq bigint;
    v_op  text := p_operation_id;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM lisp_worlds WHERE world_id = p_world) THEN
        RAISE EXCEPTION 'v17: unknown world %', p_world;
    END IF;

    IF p_event ->> 'event' IN ('operation-start', 'operation-finish') THEN
        IF jsonb_typeof(p_event -> 'record') IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'v17: % event must carry a "record" object',
                p_event ->> 'event';
        END IF;
        IF jsonb_typeof(p_event -> 'record' -> 'id') IS DISTINCT FROM 'string'
           OR length(p_event -> 'record' ->> 'id') = 0 THEN
            RAISE EXCEPTION
                'v17: % event must carry a non-empty string record.id',
                p_event ->> 'event';
        END IF;
        IF jsonb_typeof(p_event -> 'record' -> 'status')
               IS DISTINCT FROM 'string'
           OR length(p_event -> 'record' ->> 'status') = 0 THEN
            RAISE EXCEPTION
                'v17: % event must carry a non-empty string record.status',
                p_event ->> 'event';
        END IF;
        IF v_op IS NOT NULL AND v_op <> (p_event -> 'record' ->> 'id') THEN
            RAISE EXCEPTION
                'v17: operation_id % disagrees with event record.id %',
                v_op, p_event -> 'record' ->> 'id';
        END IF;
        v_op := p_event -> 'record' ->> 'id';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtext(p_world::text));
    SELECT coalesce(max(j.seq), 0) + 1 INTO v_seq
      FROM lisp_journal j WHERE j.world_id = p_world;
    INSERT INTO lisp_journal (world_id, seq, operation_id, generation, event)
    VALUES (p_world, v_seq, v_op, p_generation, p_event);
    RETURN v_seq;
END;
$$;

-- Recover operations: port of jiti recover-operations. Walk the journal in
-- order; only operation-start / operation-finish events contribute their
-- "record". A record whose status is still "running" at recovery time is
-- folded to "interrupted". Later events supersede earlier ones with the same
-- record id. Output: newest first, at most 100, as a jsonb array.
CREATE FUNCTION v17_recover_operations(p_world uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
    WITH relevant AS (
        SELECT j.seq, j.event -> 'record' AS record
          FROM lisp_journal j
         WHERE j.world_id = p_world
           AND j.event ->> 'event' IN ('operation-start', 'operation-finish')
           AND j.event ? 'record'
    ), latest AS (
        SELECT DISTINCT ON (record ->> 'id')
               seq,
               CASE WHEN record ->> 'status' = 'running'
                    THEN jsonb_set(record, '{status}', '"interrupted"')
                    ELSE record
               END AS record
          FROM relevant
         ORDER BY record ->> 'id', seq DESC
    ), bounded AS (
        SELECT seq, record FROM latest ORDER BY seq DESC LIMIT 100
    )
    SELECT coalesce(jsonb_agg(record ORDER BY seq DESC), '[]'::jsonb)
      FROM bounded;
$$;
