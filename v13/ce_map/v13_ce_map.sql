BEGIN;

CREATE FUNCTION public.v13_ce_map()
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $fn$
SELECT '{
  "schema_version": 1,
  "map": {
    "observe_poll": "v13_agentctl_observe(uuid,jsonb)",
    "startOrResume": "v13_enqueue_effect(uuid,text,jsonb,text)",
    "sendUserMessage": "v13_append_event(uuid,uuid,text,jsonb,uuid)",
    "steerUserTurn": "v13_agentctl_steer(uuid,jsonb)",
    "interruptTurn": "v13_cancel(uuid,uuid)",
    "respondToPermissionRequest": "v13_complete(uuid,uuid,integer,bigint,text,jsonb)",
    "shutdown": "unsupported"
  },
  "lease_columns": ["lease_owner", "lease_until"],
  "chains": [
    {"id": "agent_run_poll", "call": "executeWait", "forcePoll": true, "file": "repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentRunMCPToolService.swift", "lines": "425-426"},
    {"id": "session_link_poll", "call": "executePoll", "file": "repoprompt-ce/Sources/RepoPrompt/Infrastructure/MCP/Agent/AgentSessionLinkMCPToolService.swift", "call_line": 124, "def_line": 366}
  ],
  "notes": {
    "observe_poll": "pg_readonly_state_observe; hint_is_not_wake",
    "startOrResume": "not_stage42_session_create_path; lease_columns_are_not_task_lease"
  },
  "not_claimed": ["worktree_bind", "worktree_merge", "auto_wake", "oracle_lanes", "claimedProcessID", "request_attention", "v13_ce_shutdown", "v13_requeue_stale", "v13_renew_lease"]
}'::jsonb
$fn$;

REVOKE EXECUTE ON FUNCTION public.v13_ce_map() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v13_ce_map() TO v13_route;

COMMENT ON FUNCTION public.v13_ce_map() IS
  'STABLE read; returns the closed static CE primitive map; does not execute or query; not a tools row; does not raise.';

COMMIT;
