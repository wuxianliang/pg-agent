-- v6 W6 enqueue-only DuckDB named tools.
CREATE OR REPLACE FUNCTION _duck_tool_error(p_problem text, p_solution text)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
SELECT jsonb_build_object('success',false,'Type','DUCK_ARGUMENT_ERROR','Phase','Validation','Problem',p_problem,'Solution',p_solution)
$$;

CREATE OR REPLACE FUNCTION _duck_enqueue_operation(p_op_kind text, p_artifact_name text, p_payload jsonb)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$
DECLARE
    v_run text := agent_current_run_id();
    v_req text := gen_random_uuid()::text;
    v_seq bigint;
    v_msg bigint;
    v_mode text;
    v_status text;
    v_hash text;
    v_message jsonb;
BEGIN
    IF v_run IS NULL THEN RETURN _duck_tool_error('DuckDB 工具只能在 agent apply 事务内调用','通过 named tool 调用，不要从任意 SQL 会话传入 run_id。'); END IF;
    SELECT session_mode INTO v_mode FROM agent_runs WHERE run_id=v_run;
    IF NOT FOUND THEN RETURN _duck_tool_error('unknown current run','重新启动 agent run。'); END IF;
    INSERT INTO duck_workbench_sessions(run_id,session_mode) VALUES(v_run,COALESCE(v_mode,'temp')) ON CONFLICT DO NOTHING;
    SELECT status,next_op_seq INTO v_status,v_seq FROM duck_workbench_sessions WHERE run_id=v_run FOR UPDATE;
    IF v_status IN ('LOST','TERMINAL') THEN RETURN _duck_tool_error(format('DuckDB session is %s',v_status),'temp 丢失时启动新 run；run_schema 由 worker 重放。'); END IF;
    v_hash := md5(p_payload::text);
    INSERT INTO duck_operations(request_id,run_id,op_seq,op_kind,artifact_name,request_payload,definition_hash)
    VALUES(v_req,v_run,v_seq,p_op_kind,p_artifact_name,p_payload,v_hash);
    v_message := jsonb_build_object('run_id',v_run,'request_id',v_req,'op_seq',v_seq,'op_kind',p_op_kind,'payload_hash',v_hash) || p_payload;
    SELECT pgmq.send('duck_heavy_requests',v_message,jsonb_build_object('x-pgmq-group',v_run)) INTO v_msg;
    UPDATE duck_operations SET queue_msg_id=v_msg WHERE request_id=v_req;
    UPDATE duck_workbench_sessions SET next_op_seq=v_seq+1 WHERE run_id=v_run;
    RETURN jsonb_build_object('success',true,'defer',true,'wait_kind','duck_heavy','queue','duck_heavy_requests','request_id',v_req,'op_seq',v_seq,'msg_id',v_msg);
END;
$$;

CREATE OR REPLACE FUNCTION _duck_validate_common(p_brief text, p_name text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$ BEGIN
 IF p_brief IS NULL OR trim(p_brief)='' THEN RETURN _duck_tool_error('p_brief 为空','提供一句非空操作目的。'); END IF;
 IF length(p_brief)>1000 THEN RETURN _duck_tool_error('p_brief 超过 1000 字符','缩短目的说明。'); END IF;
 IF p_name IS NOT NULL AND p_name !~ '^[A-Za-z_][A-Za-z0-9_]{0,62}$' THEN RETURN _duck_tool_error(format('非法 artifact 名: %s',p_name),'使用字母或下划线开头、仅含字母数字下划线的名称。'); END IF;
 RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION wb_duck_register(p_brief text,p_source_id text,p_schema_name text,p_table_name text,p_view_name text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$ DECLARE e jsonb; BEGIN
 e:=_duck_validate_common(p_brief,p_view_name); IF e IS NOT NULL THEN RETURN e; END IF;
 IF p_source_id IS NULL OR trim(p_source_id)='' OR p_schema_name !~ '^[A-Za-z_][A-Za-z0-9_]{0,62}$' OR p_table_name !~ '^[A-Za-z_][A-Za-z0-9_]{0,62}$' THEN RETURN _duck_tool_error('source/schema/table 参数非法','使用配置的 source_id 和简单 PostgreSQL 标识符。'); END IF;
 RETURN _duck_enqueue_operation('register',p_view_name,jsonb_build_object('brief',p_brief,'source_id',p_source_id,'schema_name',p_schema_name,'table_name',p_table_name,'artifact_name',p_view_name)); END $$;
COMMENT ON FUNCTION wb_duck_register(text,text,text,text,text) IS $j${"plugin":{"name":"plugin_duck_tools"},"llm_tool":{"name":"wb_duck_register","description":"把允许的 PostgreSQL 表以注册时快照读入当前 run 的 DuckDB 工作台，并命名为 source artifact。","args":{"p_brief":"text","p_source_id":"text","p_schema_name":"text","p_table_name":"text","p_view_name":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"queue_submit","async":true}}$j$;

CREATE OR REPLACE FUNCTION wb_duck_query(p_brief text,p_view_name text,p_query text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$ DECLARE e jsonb; BEGIN e:=_duck_validate_common(p_brief,p_view_name); IF e IS NOT NULL THEN RETURN e; END IF; IF p_query IS NULL OR trim(p_query)='' OR length(p_query)>16000 THEN RETURN _duck_tool_error('p_query 为空或超过 16000 字符','提供一条有界 DuckDB SELECT。'); END IF; RETURN _duck_enqueue_operation('query',p_view_name,jsonb_build_object('brief',p_brief,'artifact_name',p_view_name,'query',p_query,'depends_on','[]'::jsonb)); END $$;
COMMENT ON FUNCTION wb_duck_query(text,text,text) IS $j${"plugin":{"name":"plugin_duck_tools"},"llm_tool":{"name":"wb_duck_query","description":"在当前 run 的 DuckDB 工作台执行一条只读查询，并把结果保存为显式命名的临时 view。","args":{"p_brief":"text","p_view_name":"text","p_query":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"queue_submit","async":true}}$j$;

CREATE OR REPLACE FUNCTION wb_duck_brief_query(p_brief text,p_view_name text,p_limit integer DEFAULT 20)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$ DECLARE e jsonb; l int:=COALESCE(p_limit,20); BEGIN e:=_duck_validate_common(p_brief,p_view_name); IF e IS NOT NULL THEN RETURN e; END IF; IF l<1 OR l>50 THEN RETURN _duck_tool_error('p_limit 必须是 1..50','使用默认 20 或指定 1..50。'); END IF; RETURN _duck_enqueue_operation('brief_query',p_view_name,jsonb_build_object('brief',p_brief,'artifact_name',p_view_name,'limit',l)); END $$;
COMMENT ON FUNCTION wb_duck_brief_query(text,text,integer) IS $j${"plugin":{"name":"plugin_duck_tools"},"llm_tool":{"name":"wb_duck_brief_query","description":"读取当前 run 的 DuckDB source/view 的有限预览；默认 20 行，最大 50 行。","args":{"p_brief":"text","p_view_name":"text","p_limit":"integer"},"returns":"jsonb","session_scope":"run_connection","capability":"queue_submit","async":true}}$j$;

CREATE OR REPLACE FUNCTION wb_duck_list(p_brief text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$ DECLARE e jsonb; BEGIN e:=_duck_validate_common(p_brief); IF e IS NOT NULL THEN RETURN e; END IF; RETURN _duck_enqueue_operation('list',NULL,jsonb_build_object('brief',p_brief)); END $$;
COMMENT ON FUNCTION wb_duck_list(text) IS $j${"plugin":{"name":"plugin_duck_tools"},"llm_tool":{"name":"wb_duck_list","description":"列出当前 run 的 DuckDB 工作台 source/view，不暴露其它 run 或内部系统 catalog。","args":{"p_brief":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"queue_submit","async":true}}$j$;

CREATE OR REPLACE FUNCTION wb_duck_columns(p_brief text,p_view_name text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$ DECLARE e jsonb; BEGIN e:=_duck_validate_common(p_brief,p_view_name); IF e IS NOT NULL THEN RETURN e; END IF; RETURN _duck_enqueue_operation('columns',p_view_name,jsonb_build_object('brief',p_brief,'artifact_name',p_view_name)); END $$;
COMMENT ON FUNCTION wb_duck_columns(text,text) IS $j${"plugin":{"name":"plugin_duck_tools"},"llm_tool":{"name":"wb_duck_columns","description":"查看当前 run 的 DuckDB artifact 的有序列名和类型。","args":{"p_brief":"text","p_view_name":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"queue_submit","async":true}}$j$;

CREATE OR REPLACE FUNCTION wb_duck_show_create(p_brief text,p_view_name text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$ DECLARE e jsonb; d text; BEGIN e:=_duck_validate_common(p_brief,p_view_name); IF e IS NOT NULL THEN RETURN e; END IF; SELECT definition_sql INTO d FROM duck_artifacts WHERE run_id=agent_current_run_id() AND artifact_name=p_view_name AND artifact_status='ACTIVE'; RETURN _duck_enqueue_operation('show_create',p_view_name,jsonb_build_object('brief',p_brief,'artifact_name',p_view_name,'definition_sql',d)); END $$;
COMMENT ON FUNCTION wb_duck_show_create(text,text) IS $j${"plugin":{"name":"plugin_duck_tools"},"llm_tool":{"name":"wb_duck_show_create","description":"返回当前 run 的 DuckDB artifact 注册来源或已保存的 view 定义与依赖。","args":{"p_brief":"text","p_view_name":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"queue_submit","async":true}}$j$;

CREATE OR REPLACE FUNCTION wb_duck_drop(p_brief text,p_view_name text)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY INVOKER AS $$ DECLARE e jsonb; n int; BEGIN e:=_duck_validate_common(p_brief,p_view_name); IF e IS NOT NULL THEN RETURN e; END IF; SELECT count(*) INTO n FROM duck_artifacts WHERE run_id=agent_current_run_id() AND artifact_status='ACTIVE' AND depends_on ? p_view_name; IF n>0 THEN RETURN jsonb_build_object('success',false,'Type','DUCK_DEPENDENCY_EXISTS','Phase','Validation','Problem',format('%s 个 active view 依赖 %s',n,p_view_name),'Solution','先删除依赖 view；v6 不执行 CASCADE。'); END IF; RETURN _duck_enqueue_operation('drop',p_view_name,jsonb_build_object('brief',p_brief,'artifact_name',p_view_name)); END $$;
COMMENT ON FUNCTION wb_duck_drop(text,text) IS $j${"plugin":{"name":"plugin_duck_tools"},"llm_tool":{"name":"wb_duck_drop","description":"删除当前 run 中没有 active 依赖者的 DuckDB artifact；不执行 CASCADE。","args":{"p_brief":"text","p_view_name":"text"},"returns":"jsonb","session_scope":"run_connection","capability":"queue_submit","async":true}}$j$;
