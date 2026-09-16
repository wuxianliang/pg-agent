-- v9 W4-W7: pack lifecycle
CREATE OR REPLACE FUNCTION _ctx_error(p_problem text, p_solution text)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
SELECT jsonb_build_object('success',false,'Type','CTX_PACK_ERROR','Problem',p_problem,'Solution',p_solution)
$$;

CREATE OR REPLACE FUNCTION ctx_current_head(p_repo text)
RETURNS text LANGUAGE sql STABLE SECURITY INVOKER AS $$
SELECT head_commit FROM repo_heads WHERE repo_path = p_repo
$$;

CREATE OR REPLACE FUNCTION _ctx_enqueue_op(p_pack_id text, p_op_kind text, p_trigger text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_status   text;
    v_seq      bigint;
    v_task_run text;
    v_repo     text;
    v_req      text;
    v_msg      bigint;
BEGIN
    SELECT status, next_op_seq, task_run_id, repo_path
      INTO v_status, v_seq, v_task_run, v_repo
      FROM context_packs WHERE pack_id = p_pack_id FOR UPDATE;
    IF NOT FOUND THEN
        RETURN _ctx_error(format('unknown context pack: %s', p_pack_id), '先通过 ctx_ensure_pack 创建 pack。');
    END IF;
    IF v_status IN ('RETIRED','FAILED') THEN
        RETURN _ctx_error(format('context pack %s is %s', p_pack_id, v_status),
                          'RETIRED/FAILED pack 不再入队操作；需要上下文时新建任务。');
    END IF;
    -- v_seq already holds next_op_seq from the SELECT above.
    UPDATE context_packs SET
        next_op_seq = next_op_seq + 1,
        status = CASE WHEN status = 'FRESH' THEN 'REFRESHING'
                      WHEN status = 'BUILDING' THEN 'BUILDING'
                      ELSE status END,
        updated_at = now()
     WHERE pack_id = p_pack_id;
    v_req := gen_random_uuid()::text;
    INSERT INTO ctx_operations(request_id, pack_id, op_kind, op_seq, status, built_at_commit)
    VALUES (v_req, p_pack_id, p_op_kind, v_seq, 'QUEUED', COALESCE(ctx_current_head(v_repo), 'INIT'));
    SELECT pgmq.send('ctx_heavy_requests', jsonb_build_object(
            'request_id', v_req,
            'pack_id', p_pack_id,
            'task_run_id', v_task_run,
            'op_kind', p_op_kind,
            'op_seq', v_seq,
            'repo_path', v_repo,
            'trigger', p_trigger))
      INTO v_msg;
    RETURN jsonb_build_object('success', true, 'request_id', v_req, 'op_seq', v_seq, 'msg_id', v_msg);
END;
$$;

CREATE OR REPLACE FUNCTION ctx_create_task(p_question text)
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_run text;
BEGIN
    -- parked run: a run row with zero steps and no LLM enqueue.
    INSERT INTO agent_runs(run_id, question, max_steps)
    VALUES (gen_random_uuid()::text, p_question, 10)
    RETURNING run_id INTO v_run;
    RETURN v_run;
END;
$$;

CREATE OR REPLACE FUNCTION ctx_ensure_pack(p_task_run_id text, p_repo_path text DEFAULT 'default')
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_pack    text;
    v_status  text;
    v_out     jsonb;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM agent_runs WHERE run_id = p_task_run_id) THEN
        RETURN _ctx_error(format('unknown agent run: %s', p_task_run_id),
                          '先用 ctx_create_task 创建 parked run。');
    END IF;
    SELECT pack_id, status INTO v_pack, v_status
      FROM context_packs WHERE task_run_id = p_task_run_id;
    IF FOUND THEN
        -- idempotent per task, including a RETIRED pack: no new op.
        RETURN jsonb_build_object('success', true, 'pack_id', v_pack,
                                  'status', v_status, 'replayed', true);
    END IF;
    v_pack := gen_random_uuid()::text;
    INSERT INTO context_packs(pack_id, task_run_id, repo_path, base_commit)
    VALUES (v_pack, p_task_run_id, p_repo_path,
            COALESCE(ctx_current_head(p_repo_path), 'INIT'));
    v_out := _ctx_enqueue_op(v_pack, 'build', 'ensure');
    RETURN v_out || jsonb_build_object('pack_id', v_pack);
END;
$$;

CREATE OR REPLACE FUNCTION ctx_on_commit(p_repo_path text, p_new_commit text, p_changed_uris text[],
                                         p_trigger_kind text DEFAULT 'git_hook')
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_marked text[];
    v_packs  text[];
    v_pack   text;
    v_status text;
BEGIN
    INSERT INTO context_commits(repo_path, commit_id)
    VALUES (p_repo_path, p_new_commit)
    ON CONFLICT DO NOTHING;
    INSERT INTO context_commit_files(repo_path, commit_id, dep_uri)
    SELECT p_repo_path, p_new_commit, u
      FROM unnest(COALESCE(p_changed_uris, '{}'::text[])) AS u
    ON CONFLICT DO NOTHING;

    INSERT INTO repo_heads(repo_path, head_commit)
    VALUES (p_repo_path, p_new_commit)
    ON CONFLICT (repo_path) DO UPDATE SET
        head_commit = EXCLUDED.head_commit, updated_at = now();

    -- capture the dirty detail BEFORE the update (only freshly-staled slices)
    SELECT array_agg(DISTINCT s.pack_id || ':' || s.slice_id
                     ORDER BY s.pack_id || ':' || s.slice_id)
      INTO v_marked
      FROM context_slices s
      JOIN slice_dependencies d ON d.pack_id = s.pack_id AND d.slice_id = s.slice_id
     WHERE d.dep_uri = ANY(COALESCE(p_changed_uris, '{}'::text[]))
       AND s.stale = false;

    UPDATE context_slices s SET stale = true, updated_at = now()
      FROM slice_dependencies d
     WHERE d.pack_id = s.pack_id AND d.slice_id = s.slice_id
       AND d.dep_uri = ANY(COALESCE(p_changed_uris, '{}'::text[]))
       AND s.stale = false;

    -- affected packs: any pack holding a dependency on a changed uri,
    -- regardless of whether this call marked anything new.
    SELECT array_agg(DISTINCT d.pack_id ORDER BY d.pack_id)
      INTO v_packs
      FROM slice_dependencies d
     WHERE d.dep_uri = ANY(COALESCE(p_changed_uris, '{}'::text[]));

    FOREACH v_pack IN ARRAY COALESCE(v_packs, '{}'::text[]) LOOP
        SELECT status INTO v_status FROM context_packs WHERE pack_id = v_pack;
        IF v_status NOT IN ('RETIRED','FAILED') THEN
            UPDATE context_packs SET status = 'STALE', updated_at = now()
             WHERE pack_id = v_pack;
            IF NOT EXISTS (SELECT 1 FROM ctx_operations
                            WHERE pack_id = v_pack
                              AND status IN ('QUEUED','RUNNING')) THEN
                PERFORM _ctx_enqueue_op(v_pack, 'refresh', p_new_commit);
            ELSE
                -- an op is already in flight: latch a tail refresh instead.
                UPDATE context_packs SET pending_refresh = true, updated_at = now()
                 WHERE pack_id = v_pack;
            END IF;
        END IF;
    END LOOP;

    RETURN jsonb_build_object('success', true, 'commit', p_new_commit,
                              'marked_slices', to_jsonb(COALESCE(v_marked, '{}'::text[])),
                              'affected_packs', to_jsonb(COALESCE(v_packs, '{}'::text[])));
END;
$$;

CREATE OR REPLACE FUNCTION ctx_gate(p_task_run_id text, p_sync_threshold int DEFAULT 3)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_pack        context_packs%ROWTYPE;
    v_repo        text;
    v_base        text;
    v_head        text;
    v_base_seq    bigint;
    v_head_seq    bigint;
    v_changed     text[];
    v_dirty       jsonb;
    v_drift       jsonb;
    v_dirty_count int;
BEGIN
    SELECT p.* INTO v_pack FROM context_packs p
     WHERE p.task_run_id = p_task_run_id AND p.status <> 'RETIRED';
    IF NOT FOUND THEN
        IF EXISTS (SELECT 1 FROM context_packs
                    WHERE task_run_id = p_task_run_id AND status = 'RETIRED') THEN
            RETURN jsonb_build_object('success', false, 'Type', 'CTX_PACK_RETIRED',
                'Problem', format('task %s 的 context pack 已 RETIRED', p_task_run_id),
                'Solution', 'RETIRED 是终态；需要上下文时用 ctx_create_task 新建任务。');
        END IF;
        RETURN jsonb_build_object('success', false, 'Type', 'CTX_PACK_NOT_FOUND',
            'Problem', format('task %s 没有 context pack', p_task_run_id),
            'Solution', '先调用 ctx_ensure_pack 投机构建上下文。');
    END IF;
    v_repo := v_pack.repo_path;
    v_base := v_pack.base_commit;
    v_head := COALESCE(ctx_current_head(v_repo), 'INIT');
    IF v_base = v_head THEN
        RETURN jsonb_build_object('success', true, 'fresh', true, 'action', 'none',
            'pack_id', v_pack.pack_id, 'generation', v_pack.generation,
            'base_commit', v_base, 'head', v_head, 'drift', '[]'::jsonb);
    END IF;

    SELECT seq INTO v_base_seq FROM context_commits
     WHERE repo_path = v_repo AND commit_id = v_base;
    v_base_seq := COALESCE(v_base_seq, 0);  -- base 'INIT' has no row: full history
    SELECT seq INTO v_head_seq FROM context_commits
     WHERE repo_path = v_repo AND commit_id = v_head;

    SELECT array_agg(DISTINCT f.dep_uri) INTO v_changed
      FROM context_commit_files f
      JOIN context_commits c ON c.repo_path = f.repo_path AND c.commit_id = f.commit_id
     WHERE f.repo_path = v_repo
       AND c.seq > v_base_seq
       AND c.seq <= v_head_seq;

    SELECT COALESCE(jsonb_agg(jsonb_build_object('slice_id', s.slice_id, 'dep_uri', s.dep_uri)
                              ORDER BY s.slice_id), '[]'::jsonb)
      INTO v_dirty
      FROM context_slices s
     WHERE s.pack_id = v_pack.pack_id
       AND (s.stale = true
            OR s.dep_uri = ANY(COALESCE(v_changed, '{}'::text[])));
    v_dirty_count := jsonb_array_length(v_dirty);

    IF v_dirty_count <= p_sync_threshold THEN
        RETURN jsonb_build_object('success', true, 'fresh', false, 'action', 'sync_refresh',
            'pack_id', v_pack.pack_id, 'generation', v_pack.generation,
            'dirty_slices', v_dirty,
            'changed_uris', to_jsonb(COALESCE(v_changed, '{}'::text[])),
            'base_commit', v_base, 'head', v_head);
    END IF;

    SELECT COALESCE(jsonb_agg(jsonb_build_object('commit', f.commit_id, 'dep_uri', f.dep_uri)
                              ORDER BY f.commit_id, f.dep_uri), '[]'::jsonb)
      INTO v_drift
      FROM context_commit_files f
      JOIN context_commits c ON c.repo_path = f.repo_path AND c.commit_id = f.commit_id
     WHERE f.repo_path = v_repo
       AND c.seq > v_base_seq
       AND c.seq <= v_head_seq;

    RETURN jsonb_build_object('success', true, 'fresh', false, 'action', 'drift_delta',
        'pack_id', v_pack.pack_id, 'generation', v_pack.generation,
        'drift', v_drift, 'dirty_count', v_dirty_count,
        'dirty_slices', v_dirty,
        'changed_uris', to_jsonb(COALESCE(v_changed, '{}'::text[])),
        'base_commit', v_base, 'head', v_head);
END;
$$;

CREATE OR REPLACE FUNCTION ctx_retire_pack(p_task_run_id text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_pack text;
BEGIN
    UPDATE context_packs SET status = 'RETIRED', updated_at = now()
     WHERE task_run_id = p_task_run_id
     RETURNING pack_id INTO v_pack;
    IF NOT FOUND THEN
        RETURN _ctx_error(format('task %s 没有 context pack', p_task_run_id),
                          '确认 task_run_id；ctx_retire_pack 只作用于已有 pack。');
    END IF;
    RETURN jsonb_build_object('success', true, 'pack_id', v_pack, 'status', 'RETIRED');
END;
$$;
