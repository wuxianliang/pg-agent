-- v12 M2 (G2): the decision plane's lifecycle.
--
-- open -> (add questions) -> seal -> ready | cached
-- ready -> record_answers (validated, one tx) -> answered
--
-- request_hash is the sha256 of the canonical request payload (jsonb text
-- form is deterministic within a PG version). Sealing a batch whose exact
-- payload was already answered copies the answers instead of asking again:
-- Jev calls are pure, so replay-by-hash is the cache, and it is also the
-- audit key — the raw request/answer/usage always stay in the tables.

-- The exact object sent to the model: {"state":..., "questions": {...}}.
CREATE FUNCTION v12_request_payload(p_batch uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT jsonb_build_object(
        'state', b.state,
        'questions', (SELECT jsonb_object_agg(
                            q.question_id,
                            jsonb_build_object('type', q.kind,
                                               'instructions', q.instructions,
                                               'criteria', q.criteria))
                      FROM jev_questions q
                     WHERE q.batch_id = p_batch))
    FROM jev_batches b
    WHERE b.batch_id = p_batch;
$$;

CREATE FUNCTION v12_open_batch(p_session_id uuid, p_purpose text, p_state jsonb)
RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
    v_batch uuid;
BEGIN
    INSERT INTO jev_batches (session_id, purpose, state)
    VALUES (p_session_id, p_purpose, p_state)
    RETURNING batch_id INTO v_batch;
    RETURN v_batch;
END;
$$;

CREATE FUNCTION v12_add_question(p_batch uuid, p_question_id text, p_kind text,
                                 p_instructions text,
                                 p_criteria jsonb DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM jev_batches
                   WHERE batch_id = p_batch AND status = 'open') THEN
        RAISE EXCEPTION 'v12: batch % is not open', p_batch;
    END IF;
    INSERT INTO jev_questions (batch_id, question_id, kind, instructions, criteria)
    VALUES (p_batch, p_question_id, p_kind, p_instructions, p_criteria);
END;
$$;

-- Seal: compute the hash, then either replay from an answered twin (cached)
-- or mark ready for the worker. Refuses empty batches and non-open batches.
CREATE FUNCTION v12_seal_batch(p_batch uuid) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
    v_hash text;
    v_src  uuid;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM jev_batches
                   WHERE batch_id = p_batch AND status = 'open') THEN
        RAISE EXCEPTION 'v12: seal requires an open batch (%)', p_batch;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM jev_questions WHERE batch_id = p_batch) THEN
        RAISE EXCEPTION 'v12: refusing to seal an empty batch (%)', p_batch;
    END IF;

    UPDATE jev_batches
       SET request_hash = encode(digest(v12_request_payload(p_batch)::text,
                                        'sha256'), 'hex')
     WHERE batch_id = p_batch
    RETURNING request_hash INTO v_hash;

    SELECT b.batch_id INTO v_src
      FROM jev_batches b
     WHERE b.request_hash = v_hash
       AND b.status IN ('answered', 'cached')
       AND b.batch_id <> p_batch
     ORDER BY b.created_at, b.batch_id
     LIMIT 1;

    IF v_src IS NOT NULL THEN
        INSERT INTO jev_decisions (batch_id, question_id, kind, answer)
        SELECT p_batch, d.question_id, d.kind, d.answer
          FROM jev_decisions d
         WHERE d.batch_id = v_src;
        UPDATE jev_batches
           SET status = 'cached', cached_from = v_src, latency_ms = 0,
               usage = (SELECT usage FROM jev_batches WHERE batch_id = v_src)
         WHERE batch_id = p_batch;
    ELSE
        UPDATE jev_batches SET status = 'ready' WHERE batch_id = p_batch;
    END IF;

    RETURN (SELECT status FROM jev_batches WHERE batch_id = p_batch);
END;
$$;

-- Numeric field fetch that fails closed on garbage instead of casting noise.
CREATE FUNCTION v12_num(p_obj jsonb, p_key text) RETURNS numeric
LANGUAGE plpgsql AS $$
BEGIN
    IF p_obj IS NULL OR p_obj -> p_key IS NULL
       OR coalesce(jsonb_typeof(p_obj -> p_key), '') <> 'number' THEN
        RAISE EXCEPTION 'v12: answer field % missing or not a number', p_key;
    END IF;
    RETURN (p_obj ->> p_key)::numeric;
EXCEPTION
    WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'v12: answer field % not numeric', p_key;
END;
$$;

-- Per-kind answer validation against the question's own shape. Anything
-- malformed rejects the whole record call (single transaction).
CREATE FUNCTION v12_validate_answer(p_kind text, p_answer jsonb,
                                    p_criteria jsonb) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    v numeric;
BEGIN
    IF p_kind = 'choice' THEN
        IF coalesce(jsonb_typeof(p_answer -> 'probabilities'), '') <> 'object' THEN
            RAISE EXCEPTION 'v12: choice answer needs a probabilities object';
        END IF;
        IF NOT (p_answer -> 'probabilities') ? (p_answer ->> 'choice') THEN
            RAISE EXCEPTION 'v12: chosen option % not in probabilities',
                p_answer ->> 'choice';
        END IF;
        IF p_answer ->> 'choice' IS NULL
           OR NOT (p_criteria ? (p_answer ->> 'choice')) THEN
            RAISE EXCEPTION 'v12: chosen option % not in criteria',
                p_answer ->> 'choice';
        END IF;
        v := v12_num(p_answer, 'confidence');
        IF v < 0 OR v > 1 THEN
            RAISE EXCEPTION 'v12: confidence out of [0,1]: %', v;
        END IF;
    ELSIF p_kind = 'score' THEN
        v := v12_num(p_answer, 'score');
        IF v < 0 OR v >= jsonb_array_length(p_criteria) THEN
            RAISE EXCEPTION 'v12: score % outside level range [0,%)',
                v, jsonb_array_length(p_criteria);
        END IF;
        v := v12_num(p_answer, 'confidence');
        IF v < 0 OR v > 1 THEN
            RAISE EXCEPTION 'v12: confidence out of [0,1]: %', v;
        END IF;
    ELSIF p_kind = 'noul' THEN
        v := v12_num(p_answer, 'noul');
        IF v < 0 OR v > 1 THEN
            RAISE EXCEPTION 'v12: noul out of [0,1]: %', v;
        END IF;
    ELSE
        RAISE EXCEPTION 'v12: unknown answer kind %', p_kind;
    END IF;
END;
$$;

-- Record a full answer set: every question must be answered, every answer
-- must belong to a question, every answer must validate. All in one tx.
CREATE FUNCTION v12_record_answers(p_batch uuid, p_answers jsonb,
                                   p_usage jsonb DEFAULT NULL,
                                   p_latency_ms int DEFAULT NULL)
RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
    r      record;
    v_cnt  int := 0;
BEGIN
    UPDATE jev_batches
       SET status = 'answered', usage = p_usage, latency_ms = p_latency_ms
     WHERE batch_id = p_batch AND status = 'ready';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v12: record requires a ready batch (%)', p_batch;
    END IF;

    IF (SELECT count(*) FROM jsonb_object_keys(p_answers) k
         WHERE NOT EXISTS (SELECT 1 FROM jev_questions jq
                            WHERE jq.batch_id = p_batch
                              AND jq.question_id = k)) > 0 THEN
        RAISE EXCEPTION 'v12: answers contain unknown question ids';
    END IF;

    FOR r IN SELECT * FROM jev_questions
              WHERE batch_id = p_batch ORDER BY question_id LOOP
        IF p_answers -> r.question_id IS NULL THEN
            RAISE EXCEPTION 'v12: missing answer for %', r.question_id;
        END IF;
        PERFORM v12_validate_answer(r.kind, p_answers -> r.question_id,
                                    r.criteria);
        INSERT INTO jev_decisions (batch_id, question_id, kind, answer)
        VALUES (p_batch, r.question_id, r.kind, p_answers -> r.question_id);
        v_cnt := v_cnt + 1;
    END LOOP;
    RETURN v_cnt;
END;
$$;

-- Signal extraction (frozen semantics): the signal is the question's
-- MEASUREMENT, not its meta-quality —
--   choice -> confidence (the chosen option is categorical; confidence
--             is the only graded signal)
--   score  -> the score value itself (0..levels-1; e.g. risk 2.6/3)
--   noul   -> the noul probability
CREATE FUNCTION v12_signal(p_kind text, p_answer jsonb) RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
             WHEN p_kind = 'noul'   THEN (p_answer ->> 'noul')::numeric
             WHEN p_kind = 'score'  THEN (p_answer ->> 'score')::numeric
             ELSE                        (p_answer ->> 'confidence')::numeric
           END;
$$;

CREATE VIEW v12_routes AS
SELECT b.batch_id,
       b.session_id,
       b.purpose,
       d.question_id,
       d.kind,
       d.answer,
       v12_signal(d.kind, d.answer) AS signal,
       t.act_min,
       t.review_min,
       t.fallback,
       CASE
           WHEN v12_signal(d.kind, d.answer) >= t.act_min THEN 'act'
           WHEN v12_signal(d.kind, d.answer) >= t.review_min THEN 'review'
           ELSE t.fallback
       END AS verdict
  FROM jev_batches b
  JOIN jev_decisions d USING (batch_id)
  JOIN thresholds t
    ON t.purpose = b.purpose AND t.question_id = d.question_id;
