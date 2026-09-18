-- v12 M6 (G6): the queue mode — PGMQ carries wake-ups, PG stays the truth.
--
-- This is the v3-v6 architecture applied to the v12 planes: the driver
-- (in-process or another host) advances the turn state machine with SQL
-- only and drops a message per unit of external work; a queue worker
-- process polls PGMQ, does the IO (OpenRouter -> Jev, tools, LLM) and
-- applies results back as rows. Messages are wake-ups ONLY — losing them
-- can stall progress but never corrupt state; v12_requeue_stale rebuilds
-- the backlog from the tables themselves (repo invariant 8 heritage).

CREATE EXTENSION IF NOT EXISTS pgmq;
SELECT pgmq.create('v12_work');

-- Message shape: {"kind": "jev" | "job", "id": <uuid>} on queue v12_work.
CREATE FUNCTION v12_send_work(p_kind text, p_id uuid) RETURNS bigint
LANGUAGE sql VOLATILE AS $$
    SELECT pgmq.send('v12_work',
                     jsonb_build_object('kind', p_kind, 'id', p_id));
$$;

-- RFC 4122 v5 (SHA-1) UUID in pure SQL: this server's pgcrypto (PG18)
-- dropped uuid_generate_v5. Byte-for-byte equal to Python's uuid.uuid5
-- (asserted by the G6 gate) — digest(ns_bytes || name), version nibble 5,
-- RFC variant bits.
CREATE FUNCTION v12_uuid_v5(p_ns uuid, p_name text) RETURNS uuid
LANGUAGE sql IMMUTABLE AS $$
    WITH raw AS (
        SELECT substr(encode(digest(
            decode(replace(p_ns::text, '-', ''), 'hex')
            || convert_to(p_name, 'UTF8'), 'sha1'), 'hex'), 1, 32) AS h
    ), bits AS (
        SELECT h,
               lpad(to_hex((('x' || substr(h, 13, 2))::bit(8)::int & 15) | 80), 2, '0') AS b7,
               lpad(to_hex((('x' || substr(h, 17, 2))::bit(8)::int & 63) | 128), 2, '0') AS b9
          FROM raw
    )
    SELECT (substr(h2, 1, 8) || '-' || substr(h2, 9, 4) || '-' ||
            substr(h2, 13, 4) || '-' || substr(h2, 17, 4) || '-' ||
            substr(h2, 21, 12))::uuid
      FROM (SELECT substr(h, 1, 12) || b7 || substr(h, 15, 2) || b9
                   || substr(h, 19, 14) AS h2 FROM bits) s
$$;

-- Deterministic effect identity, SQL side. Same derivation as the inline
-- runner's uuid5(namespace=0, "<session>:<last_user_seq>:<kind>"), so both
-- modes collide on the same effect_id for the same logical action (G6
-- asserts the cross-mode equality).
CREATE FUNCTION v12_effect_id(p_session uuid, p_kind text) RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT v12_uuid_v5('00000000-0000-0000-0000-000000000000'::uuid,
                       p_session::text || ':' ||
                       v12_last_user_seq(p_session)::text || ':' || p_kind);
$$;

-- Scan-based recovery: whatever the tables say is pending gets a fresh
-- wake-up. Safe to run at any time; duplicate messages are deduped by the
-- state machine itself (record_answers requires 'ready', claim bumps fence).
CREATE FUNCTION v12_requeue_stale(p_batches boolean DEFAULT true,
                                  p_jobs boolean DEFAULT true) RETURNS int
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    n int := 0;
    r record;
BEGIN
    IF p_batches THEN
        FOR r IN SELECT batch_id FROM jev_batches WHERE status = 'ready' LOOP
            PERFORM v12_send_work('jev', r.batch_id);
            n := n + 1;
        END LOOP;
    END IF;
    IF p_jobs THEN
        FOR r IN SELECT job_id FROM jobs WHERE status = 'queued' LOOP
            PERFORM v12_send_work('job', r.job_id);
            n := n + 1;
        END LOOP;
    END IF;
    RETURN n;
END;
$$;
