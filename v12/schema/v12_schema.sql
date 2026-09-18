-- v12 M1 (G1): the three planes — journal / decision / action.
--
-- Division of labor (plan §0): SQL owns arithmetic, order and durability;
-- Jev owns semantic judgment; LLM owns generation. The decision plane makes
-- "asking" and "answering" rows, so every judgment is auditable, cacheable
-- by request_hash, and routed by thresholds that are data, not code.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- Plane 1: journal — the single history (v12 inherits the append-only,
-- no-hole-seq discipline in its minimal form).
-- ---------------------------------------------------------------------------

CREATE TABLE sessions (
    session_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id text NOT NULL,
    status       text NOT NULL DEFAULT 'idle'
                 CHECK (status IN ('idle', 'awaiting_human', 'closed')),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE events (
    session_id uuid NOT NULL REFERENCES sessions (session_id),
    seq        bigint NOT NULL CHECK (seq >= 1),
    type       text NOT NULL,
    payload    jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, seq)
);

CREATE FUNCTION v12_events_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'v12: events is append-only (% on % seq %)', TG_OP,
        TG_TABLE_NAME, OLD.seq;
END;
$$;

CREATE TRIGGER trg_events_append_only
    BEFORE UPDATE OR DELETE ON events
    FOR EACH ROW EXECUTE FUNCTION v12_events_append_only();

-- No-hole seq allocation under the session row lock. Concurrency on one
-- session serializes here; the max+1 read happens while the lock is held.
CREATE FUNCTION v12_append_event(p_session_id uuid, p_type text,
                                 p_payload jsonb DEFAULT '{}')
RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    v_seq bigint;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sessions WHERE session_id = p_session_id
                   FOR UPDATE) THEN
        RAISE EXCEPTION 'v12: unknown session %', p_session_id;
    END IF;
    SELECT coalesce(max(seq), 0) + 1 INTO v_seq
      FROM events WHERE session_id = p_session_id;
    INSERT INTO events (session_id, seq, type, payload)
    VALUES (p_session_id, v_seq, p_type, p_payload);
    RETURN v_seq;
END;
$$;

-- Session status is control state (not history): a tiny guarded setter.
CREATE FUNCTION v12_set_status(p_session_id uuid, p_status text)
RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE sessions SET status = p_status WHERE session_id = p_session_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v12: unknown session %', p_session_id;
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- Plane 2: decision — Jev questions and answers as rows.
--
-- Signal semantics (frozen here, consumed by the routing view in M2):
--   choice -> answer.confidence ; score -> answer.score (0..levels-1) ;
--   noul   -> answer.noul
-- Verdict semantics: signal >= act_min -> 'act'; >= review_min -> 'review';
-- else -> thresholds.fallback. Per-question thresholds only; the system
-- never combines a probability with its complement (Jev gives no identity
-- guarantees between separate questions).
-- ---------------------------------------------------------------------------

CREATE TABLE jev_batches (
    batch_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   uuid NOT NULL REFERENCES sessions (session_id),
    purpose      text NOT NULL
                 CHECK (purpose IN ('turn', 'guardrail', 'fanout', 'adhoc')),
    state        jsonb NOT NULL,
    -- set at seal time; the idempotent cache key for the whole request
    request_hash text,
    status       text NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open', 'ready', 'answered', 'cached', 'failed')),
    cached_from  uuid REFERENCES jev_batches (batch_id),
    usage        jsonb,
    latency_ms   int,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE jev_questions (
    batch_id     uuid NOT NULL REFERENCES jev_batches (batch_id) ON DELETE CASCADE,
    question_id  text NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('choice', 'score', 'noul')),
    -- English only: Jev's primary training language is English; CJK state
    -- content is fine, CJK inside questions measurably degrades accuracy.
    instructions text NOT NULL
                 CHECK (instructions ~ '^[[:ascii:]]*$'
                        AND length(btrim(instructions)) > 0),
    -- choice: object of option -> description (description may be null);
    -- score: array of >= 2 ordered level descriptions; noul: null or an
    -- object with true/false clarifications.
    criteria     jsonb,
    PRIMARY KEY (batch_id, question_id),
    CONSTRAINT jev_questions_choice_shape
        CHECK (kind <> 'choice'
               OR (jsonb_typeof(criteria) = 'object'
                   AND criteria <> '{}'::jsonb)),
    CONSTRAINT jev_questions_score_shape
        CHECK (kind <> 'score'
               OR (jsonb_typeof(criteria) = 'array'
                   AND jsonb_array_length(criteria) >= 2)),
    CONSTRAINT jev_questions_noul_shape
        CHECK (kind <> 'noul' OR criteria IS NULL
               OR jsonb_typeof(criteria) = 'object'),
    CONSTRAINT jev_questions_criteria_ascii
        CHECK (criteria IS NULL OR criteria::text ~ '^[[:ascii:]]*$')
);

COMMENT ON COLUMN jev_questions.instructions IS
    'English/ASCII only by design; enforced by CHECK, asserted by G1/G2 gates.';

CREATE TABLE jev_decisions (
    batch_id    uuid NOT NULL REFERENCES jev_batches (batch_id),
    question_id text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('choice', 'score', 'noul')),
    -- raw answer object: choice -> {choice, probabilities, confidence};
    -- score -> {score, legend?, probabilities?, confidence}; noul -> {noul}
    answer      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, question_id)
);

CREATE TABLE thresholds (
    purpose     text NOT NULL,
    question_id text NOT NULL,
    -- upper bounds intentionally not pinned to 1: score signals live on the
    -- level range (e.g. risk 0..3); noul/confidence signals live on 0..1.
    act_min     numeric NOT NULL CHECK (act_min >= 0),
    review_min  numeric NOT NULL CHECK (review_min >= 0),
    fallback    text NOT NULL DEFAULT 'human',
    PRIMARY KEY (purpose, question_id),
    CHECK (act_min >= review_min)
);

-- ---------------------------------------------------------------------------
-- Plane 3: action — the only place that keeps effect discipline, because
-- only real side effects (external tools, LLM generation) need it. Jev
-- calls are pure: retrying or replaying them is free by construction.
-- ---------------------------------------------------------------------------

CREATE TABLE tools (
    name         text PRIMARY KEY,
    description  text NOT NULL CHECK (description ~ '^[[:ascii:]]*$'),
    effect_class text NOT NULL CHECK (effect_class IN ('read_only', 'side_effect', 'llm')),
    -- read_only: name of a SQL function the worker may call (catalog-
    -- controlled allowlist); side_effect/llm: worker handler key.
    handler      text NOT NULL,
    -- closed-set parameter spec; each param p maps to a Choice question
    -- (spec->p->options) plus a Noul "stated" question (spec->p->stated).
    -- Params absent from the user request are omitted, defaults stand.
    param_spec   jsonb NOT NULL DEFAULT '{}'::jsonb
                 CHECK (jsonb_typeof(param_spec) = 'object'),
    enabled      boolean NOT NULL DEFAULT true
);

CREATE TABLE jobs (
    job_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES sessions (session_id),
    -- stable logical identity: retries reuse it, new calls never do
    effect_id  uuid NOT NULL UNIQUE,
    kind       text NOT NULL,
    payload    jsonb NOT NULL DEFAULT '{}',
    status     text NOT NULL DEFAULT 'queued'
               CHECK (status IN ('queued', 'claimed', 'succeeded', 'failed',
                                 'unknown', 'resolved_ok', 'resolved_abandoned')),
    -- fenced completion: only the current fence may settle the job
    fence      int NOT NULL DEFAULT 0 CHECK (fence >= 0),
    claimed_by text,
    lease_until timestamptz,
    result     jsonb,
    error      text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
