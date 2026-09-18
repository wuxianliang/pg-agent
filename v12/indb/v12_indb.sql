-- v12 M7 (G7): the decision plane moves in-DB via pg_typesafe.
--
-- pg_typesafe (bundled with local pgembed, commit bb491da) exposes the
-- native systemone ask as SQL: typesafe_ask(state jsonb, questions jsonb)
-- -> the full native response. Point it at OpenRouter with:
--   SET typesafe.endpoint = 'https://openrouter.ai/api/alpha/decisions';
--   SET typesafe.api_key  = '<OPENROUTER_API_KEY>';
--   SET typesafe.model    = 'typesafe/jev-1.13';
-- Gates never touch the network: typesafe.mock_response pins the reply.
--
-- Invariant note (conscious evolution of v8 invariant 4 for v12):
-- SIDE-EFFECTFUL external IO (tools, LLM generation) stays out of the
-- database, in the queue worker. PURE judgment IO (Jev: no side effects,
-- cheap, idempotent) is allowed inside transactions via pg_typesafe —
-- the trade-off is the locks held for the call's duration, documented
-- here and measured in the batch's latency_ms.

CREATE EXTENSION IF NOT EXISTS typesafe;

-- One ready batch -> one in-DB ask -> answers recorded, same transaction.
CREATE FUNCTION v12_ask_in_db(p_batch uuid) RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
    v_state jsonb;
    v_questions jsonb;
    v_resp jsonb;
    v_t0 timestamptz;
BEGIN
    SELECT p -> 'state', p -> 'questions'
      INTO v_state, v_questions
      FROM v12_request_payload(p_batch) p;
    IF v_state IS NULL THEN
        RAISE EXCEPTION 'v12: unknown batch %', p_batch;
    END IF;
    v_t0 := clock_timestamp();
    v_resp := typesafe_ask(v_state, v_questions);
    RETURN v12_record_answers(
        p_batch, v_resp -> 'answers', v_resp -> 'usage',
        (extract(epoch FROM (clock_timestamp() - v_t0)) * 1000)::int);
END;
$$;

-- A complete decide in ONE SQL call: fold -> open -> build -> seal
-- (hash cache applies) -> ask in-DB if ready -> deterministic route.
-- Returns the route; the turn/route event is durable on return.
CREATE FUNCTION v12_decide_in_db(p_session uuid) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    v_state jsonb;
    v_batch uuid;
    v_sealed text;
    v_route text;
BEGIN
    IF NOT v12_turn_open(p_session) THEN
        RAISE EXCEPTION 'v12: no open turn for %', p_session;
    END IF;
    IF v12_turn_cycles(p_session) >= 3 THEN
        PERFORM v12_set_status(p_session, 'awaiting_human');
        PERFORM v12_close_turn(p_session, false, 'budget_exhausted');
        RETURN 'human';
    END IF;

    v_state := v12_fold_state(p_session);
    v_batch := v12_open_batch(p_session, 'turn', v_state);
    PERFORM v12_build_turn_questions(v_batch, p_session);
    v_sealed := v12_seal_batch(v_batch);
    IF v_sealed = 'ready' THEN
        PERFORM v12_ask_in_db(v_batch);
    END IF;
    v_route := v12_route_turn(v_batch);
    RETURN v_route;
END;
$$;

-- The guardrail check, fully in-DB: build the three Noul questions over
-- the draft, ask via pg_typesafe, verdict from the threshold bands.
CREATE FUNCTION v12_guardrail_in_db(p_session uuid, p_state jsonb)
RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE
    v_batch uuid;
    v_sealed text;
BEGIN
    v_batch := v12_open_batch(p_session, 'guardrail', p_state);
    PERFORM v12_build_guardrail_questions(v_batch);
    v_sealed := v12_seal_batch(v_batch);
    IF v_sealed = 'ready' THEN
        PERFORM v12_ask_in_db(v_batch);
    END IF;
    RETURN v12_guardrail_ok(v_batch);
END;
$$;
