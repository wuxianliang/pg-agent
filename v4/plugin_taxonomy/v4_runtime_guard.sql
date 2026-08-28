-- ============================================================
-- PG-Agent v4 · runtime guard
--
-- Loaded immediately after v3/pg_agent_pgmq.sql.
-- Replaces SQL-side model HTTP entrypoints so later overlays cannot
-- accidentally call the inherited synchronous path.
-- ============================================================

CREATE OR REPLACE FUNCTION http_call_llm(p_messages jsonb)
RETURNS jsonb
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    RAISE EXCEPTION 'v4 forbids SQL-side model HTTP; use the out-of-DB worker';
END;
$$;

CREATE OR REPLACE FUNCTION agent_run(p_question text, p_max_steps int DEFAULT 10)
RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    RAISE EXCEPTION 'v4 forbids SQL-side model HTTP; use the out-of-DB worker';
END;
$$;
