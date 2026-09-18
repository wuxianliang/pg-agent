-- v12 M3 (G3): effect discipline for the action plane.
--
-- Only real side effects and LLM generation pass through here (Jev calls
-- are pure and live entirely in the decision plane). The discipline is the
-- minimal honest core inherited from v8's invariants 5-7:
--   * stable effect_id — retries reuse identity, new calls never do;
--   * at-most-once local commit — claim bumps the fence, completion is a
--     CAS on (job, fence, live lease): an expired or superseded worker can
--     never settle the job;
--   * unknown is a wall — an outcome the worker cannot classify must be
--     resolved explicitly before anything can retry or re-enqueue it.

-- Idempotent enqueue keyed by the stable effect identity.
--   succeeded / resolved_ok        -> return the existing job (pure replay)
--   queued / claimed               -> return the existing job (dedupe)
--   failed / resolved_abandoned    -> reset to queued (retry REUSES identity)
--   unknown                        -> REJECTED until v12_resolve_unknown runs
CREATE FUNCTION v12_enqueue_effect(p_session_id uuid, p_effect_id uuid,
                                   p_kind text, p_payload jsonb)
RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
    v_job uuid;
    v_status text;
BEGIN
    SELECT job_id, status INTO v_job, v_status
      FROM jobs WHERE effect_id = p_effect_id;
    IF v_job IS NOT NULL THEN
        IF v_status IN ('succeeded', 'resolved_ok', 'queued', 'claimed') THEN
            RETURN v_job;
        ELSIF v_status IN ('failed', 'resolved_abandoned') THEN
            UPDATE jobs
               SET status = 'queued', payload = p_payload, error = NULL,
                   claimed_by = NULL, lease_until = NULL, updated_at = now()
             WHERE job_id = v_job;
            RETURN v_job;
        ELSE  -- unknown: cannot judge the external side effect; never blind-retry
            RAISE EXCEPTION
                'v12: effect % is unknown — resolve explicitly before re-enqueue',
                p_effect_id;
        END IF;
    END IF;
    INSERT INTO jobs (session_id, effect_id, kind, payload)
    VALUES (p_session_id, p_effect_id, p_kind, p_payload)
    RETURNING job_id INTO v_job;
    RETURN v_job;
END;
$$;

-- Claim: fresh jobs, or leases that expired. The fence increments on every
-- claim, so a stale worker's completion no longer matches.
CREATE FUNCTION v12_claim_job(p_job_id uuid, p_worker text,
                              p_lease_seconds int DEFAULT 60)
RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
    v_fence int;
BEGIN
    UPDATE jobs
       SET fence = fence + 1,
           status = 'claimed',
           claimed_by = p_worker,
           lease_until = clock_timestamp() + make_interval(secs => p_lease_seconds),
           updated_at = now()
     WHERE job_id = p_job_id
       AND (status = 'queued'
            OR (status = 'claimed'
                AND (lease_until IS NULL OR lease_until < clock_timestamp())))
    RETURNING fence INTO v_fence;
    IF v_fence IS NULL THEN
        RAISE EXCEPTION
            'v12: job % not claimable (status/lease)', p_job_id;
    END IF;
    RETURN v_fence;
END;
$$;

-- Complete: outcome in (succeeded, failed, unknown). CAS on fence AND a
-- still-live lease AND claimed state — an expired lease means the worker
-- lost its mandate even if nobody took over yet.
CREATE FUNCTION v12_complete_job(p_job_id uuid, p_fence int, p_outcome text,
                                 p_result jsonb DEFAULT NULL,
                                 p_error text DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF p_outcome NOT IN ('succeeded', 'failed', 'unknown') THEN
        RAISE EXCEPTION 'v12: bad outcome %', p_outcome;
    END IF;
    UPDATE jobs
       SET status = p_outcome, result = p_result, error = p_error,
           updated_at = now()
     WHERE job_id = p_job_id
       AND fence = p_fence
       AND status = 'claimed'
       AND lease_until IS NOT NULL
       AND lease_until >= clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'v12: complete rejected for job % (fence/lease/state)',
            p_job_id;
    END IF;
END;
$$;

-- Unknown is a wall with exactly one gate: an explicit operator decision.
CREATE FUNCTION v12_resolve_unknown(p_job_id uuid, p_resolution text,
                                    p_note text DEFAULT NULL)
RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF p_resolution NOT IN ('resolved_ok', 'resolved_abandoned') THEN
        RAISE EXCEPTION 'v12: bad resolution %', p_resolution;
    END IF;
    UPDATE jobs
       SET status = p_resolution,
           result = coalesce(result, jsonb_build_object('resolution_note', p_note)),
           updated_at = now()
     WHERE job_id = p_job_id AND status = 'unknown';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'v12: only unknown jobs can be resolved (%)', p_job_id;
    END IF;
END;
$$;
