"""Read-only chain, recall, fanout, and csi assertions. No network and no provider import."""
from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v15.protocol.split_sql import SplitFailure, classify_statement, split_sql

from task import (
    CSI_ANSWER,
    CSI_ERROR,
    CSI_FORMULA_RIGHT,
    CSI_FORMULA_WRONG,
    CSI_TASK_A,
    CSI_TASK_B,
    CSI_TASK_C,
    INVOKE_LIMIT,
    WARN_FLOOR,
    fanout_fragments,
    role_for,
)

_UNQUOTED = re.compile(r"(?i)\bjaz\s*\.\s*(return|raise)\s*\(")
_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_PRIOR_HISTORY = re.compile(r"\bjaz\s*\.\s*prior_history\s*\(", re.IGNORECASE)
_DIALECT = frozenset({"V15_DIALECT", "V15_DDL", "V15_VALUE_INVALID"})
_LIVE = frozenset({"suspended", "leased", "pending", "runnable"})
_MARKER = "\n[v15 truncated]\n"
_WARN_ID = "context_window_warning"


def money(value) -> str:
    return format(Decimal(value), "f")


def parse_json(value):
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def rows(cur, query, args=()):
    cur.execute(query, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def scalar(cur, query, args=()):
    cur.execute(query, args)
    found = cur.fetchone()
    return None if found is None else found[0]


def mentions_var(sql: str, name: str) -> bool:
    compact = "".join(sql.split())
    return ("jaz.var('" + name + "')" in compact) or ('jaz.var("' + name + '")' in compact)


def unquoted_control(sql: str) -> bool:
    classified = classify_statement(sql)
    if classified.reject_code != "V15_INVOKE_FORM":
        return False
    return _UNQUOTED.search(sql) is not None


def jsonb_equal(cur, query, expected, args) -> bool:
    cur.execute(query, (json.dumps(expected, ensure_ascii=False),) + tuple(args))
    found = cur.fetchone()
    return bool(found and found[0])


def input_equals(cur, invoke_id: str, name: str, expected) -> bool:
    return jsonb_equal(
        cur,
        """
        SELECT value = %s::jsonb
        FROM v15.bindings
        WHERE invoke_id = %s::uuid AND name = %s AND kind = 'input'
        """,
        expected,
        (invoke_id, name),
    )


def return_equals(cur, invoke_id: str, expected) -> bool:
    return jsonb_equal(
        cur,
        """
        SELECT return_value IS NOT NULL AND return_value = %s::jsonb
        FROM v15.invokes
        WHERE invoke_id = %s::uuid
        """,
        expected,
        (invoke_id,),
    )


def var_equals_child(cur, parent_id: str, child_id: str, name: str) -> bool | None:
    cur.execute(
        """
        SELECT b.value = c.return_value
        FROM v15.bindings b
        JOIN v15.invokes c ON c.invoke_id = %s::uuid
        WHERE b.invoke_id = %s::uuid AND b.name = %s AND b.kind = 'var'
        """,
        (child_id, parent_id, name),
    )
    found = cur.fetchone()
    if found is None or found[0] is None:
        return None
    return bool(found[0])


def transcript_of(messages: list[str]) -> dict:
    split_failures: dict[str, int] = {}
    classified: dict[str, int] = {}
    previews = []
    fences = 0
    empty = 0
    unquoted = False
    for content in messages:
        previews.append(content[:120])
        if "```" in content:
            fences += 1
        if content.strip() == "":
            empty += 1
        split = split_sql(content)
        if isinstance(split, SplitFailure):
            split_failures[split.reject_code] = split_failures.get(split.reject_code, 0) + 1
            continue
        for sql in split:
            result = classify_statement(sql)
            key = result.reject_code or ""
            classified[key] = classified.get(key, 0) + 1
            if result.reject_code == "V15_INVOKE_FORM" and unquoted_control(sql):
                unquoted = True
    legal = classified.get("", 0)
    total = sum(split_failures.values()) + sum(classified.values())
    rate = "0" if total == 0 else format(Decimal(legal) / Decimal(total), "f")
    return {
        "assistant_messages": len(messages),
        "markdown_fence_messages": fences,
        "split_failures": split_failures,
        "classified": classified,
        "legal_statement_rate": rate,
        "assistant_previews": previews,
        "empty_messages": empty,
        "unquoted": unquoted,
    }


def seq_continuous(seqs: list[int]) -> bool:
    if not seqs:
        return False
    return seqs == list(range(len(seqs)))


def pick_class(facts: dict) -> str:
    codes = facts["codes"]
    if facts["provider_rejected"]:
        return "provider_rejected"
    if facts["lease_skip"]:
        return "lease_skip"
    if "V15_BUDGET_EXHAUSTED" in codes:
        return "budget_cap"
    if "V15_ITERATION_EXCEEDED" in codes:
        return "iteration_ceiling"
    if "V15_RECURSION_EXCEEDED" in codes:
        return "recursion_ceiling"
    if "V15_IO_EXHAUSTED" in codes or (
        not facts["successful_bind"] and facts["unknown_attempts"] > 0
    ):
        return "provider_uncertain"
    if facts.get("finish_length") and not facts["shape_ok"]:
        return "finish_length"
    if "V15_CHILD_ERROR" in codes or facts["child_failed"]:
        return "child_error"
    if "V15_DELIVERY_CONFLICT" in codes:
        return "bind_name_collision"
    if "V15_PRINT_AND_RETURN" in codes:
        return "print_and_return"
    if facts.get("history_scope"):
        return "history_scope"
    if facts.get("root_id_literal_mismatch"):
        return "root_id_literal_mismatch"
    if facts.get("context_overflow_pasted"):
        return "context_overflow_pasted"
    if facts.get("context_overflow_budget"):
        return "context_overflow_budget"
    if not facts["has_child"]:
        return "no_delegation"
    if facts.get("depth_short"):
        return "shallow_chain"
    if not facts["shape_ok"]:
        return "bad_tail_shape"
    if facts["markdown"] > 0:
        return "markdown_fence"
    if facts["unquoted"]:
        return "unquoted_return"
    if facts["empty_messages"] > 0 or (
        facts["syntax_42601"] and not facts["successful_bind"]
    ):
        return "prose_or_empty"
    if facts["dialect_codes"]:
        return "dialect_reject"
    if facts["mission_not_forwarded"]:
        return "mission_not_forwarded"
    if facts.get("facts_leaked"):
        return "facts_leaked"
    if facts.get("far_recall_missed"):
        return "far_recall_missed"
    if facts.get("csi_meta_missed"):
        return "csi_meta_missed"
    if facts.get("chars_bug"):
        return "harness_bug"
    if facts.get("warning_missed"):
        return "warning_missed"
    if facts.get("unexpected_warning"):
        return "unexpected_warning"
    if facts["cost_missing"]:
        return "cost_missing"
    if facts.get("over_delegation"):
        return "over_delegation"
    return "harness_bug"


def _group(rows_in: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows_in:
        out.setdefault(row[key], []).append(row)
    return out


def _as_int(value) -> int | None:
    if type(value) is bool or value is None:
        return None
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _warning_hits(request) -> list[dict]:
    body = parse_json(request)
    if not isinstance(body, dict):
        return []
    found = []
    for item in body.get("messages") or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or ""
        if item.get("message_id") == _WARN_ID or (
            item.get("kind") == "transient_hook"
            and str(content).startswith("[v15 context_window_warning]")
        ):
            found.append(item)
    return found


def _ratio_ok(config) -> bool:
    body = parse_json(config)
    if not isinstance(body, dict) or set(body) != {"ratio"}:
        return False
    try:
        return Decimal(str(body["ratio"])) == Decimal("0.5")
    except Exception:
        return False


def assert_e2e(
    conn,
    *,
    root_id: str,
    seal: str,
    note: str,
    mode: str,
    pool_id: str | None,
    scenario: str = "chain",
    hops: int = 3,
    token: str | None = None,
    strict: bool = False,
    expect_calls: int | None = None,
    expect_cost_zero: bool = False,
    override_class: str | None = None,
) -> dict:
    cur = conn.cursor()
    invokes = rows(
        cur,
        """
        SELECT invoke_id::text AS invoke_id,
               parent_invoke_id::text AS parent,
               depth, status, fatal, return_value, recursion_available,
               error->>'code' AS error_code,
               scratch_schema,
               (resolved_config #>> '{protocol,max_invoke_input_length}') AS protocol_limit
        FROM v15.invokes
        WHERE root_invoke_id = %s::uuid
        ORDER BY depth, invoke_id
        """,
        (root_id,),
    )
    ids = [row["invoke_id"] for row in invokes]
    bindings = []
    statements = []
    iterations = []
    attempts = []
    events = []
    messages = []
    stored = []
    history = []
    hooks = []
    sends = []
    if ids:
        bindings = rows(
            cur,
            """
            SELECT b.invoke_id::text AS invoke_id, b.name, b.kind, b.value,
                   b.value::text AS value_text
            FROM v15.bindings b
            JOIN v15.invokes i ON i.invoke_id = b.invoke_id
            WHERE i.root_invoke_id = %s::uuid
            """,
            (root_id,),
        )
        statements = rows(
            cur,
            """
            SELECT s.invoke_id::text AS invoke_id, s.iteration, s.stmt_index, s.kind,
                   s.status, s.sql, s.bind_name,
                   s.child_invoke_id::text AS child_invoke_id,
                   s.error->>'code' AS error_code, s.error_sqlstate
            FROM v15.statements s
            JOIN v15.invokes i ON i.invoke_id = s.invoke_id
            WHERE i.root_invoke_id = %s::uuid
            ORDER BY s.invoke_id, s.iteration, s.stmt_index
            """,
            (root_id,),
        )
        iterations = rows(
            cur,
            """
            SELECT it.invoke_id::text AS invoke_id, it.iteration, it.status, it.result_kind
            FROM v15.iterations it
            JOIN v15.invokes i ON i.invoke_id = it.invoke_id
            WHERE i.root_invoke_id = %s::uuid
            ORDER BY it.invoke_id, it.iteration
            """,
            (root_id,),
        )
        attempts = rows(
            cur,
            """
            SELECT r.invoke_id::text AS invoke_id, r.iteration,
                   a.status, a.n, a.call_started, a.calls_charged,
                   a.prompt_tokens, a.cost_usd, a.response, a.request
            FROM v15.llm_attempts a
            JOIN v15.llm_requests r ON r.request_id = a.request_id
            JOIN v15.invokes i ON i.invoke_id = r.invoke_id
            WHERE i.root_invoke_id = %s::uuid
            """,
            (root_id,),
        )
        events = rows(
            cur,
            """
            SELECT e.invoke_id::text AS invoke_id, e.seq, e.event_class, e.span, e.phase,
                   e.payload->>'op' AS op,
                   e.payload->>'child_invoke_id' AS child_invoke_id
            FROM v15.invoke_events e
            JOIN v15.invokes i ON i.invoke_id = e.invoke_id
            WHERE i.root_invoke_id = %s::uuid
            ORDER BY e.invoke_id, e.seq
            """,
            (root_id,),
        )
        sends = rows(
            cur,
            """
            SELECT e.invoke_id::text AS invoke_id,
                   (e.payload->>'iteration')::int AS iteration,
                   (e.payload->>'input_chars')::int AS input_chars
            FROM v15.invoke_events e
            JOIN v15.invokes i ON i.invoke_id = e.invoke_id
            WHERE i.root_invoke_id = %s::uuid
              AND e.span = 'llm_query'
              AND e.phase = 'send'
            ORDER BY e.invoke_id, e.seq
            """,
            (root_id,),
        )
        stored = rows(
            cur,
            """
            SELECT m.invoke_id::text AS invoke_id, m.message_id, m.kind, m.content,
                   m.iteration
            FROM v15.llm_messages m
            JOIN v15.invokes i ON i.invoke_id = m.invoke_id
            WHERE i.root_invoke_id = %s::uuid
            ORDER BY m.invoke_id, m.msg_seq
            """,
            (root_id,),
        )
        history = rows(
            cur,
            """
            SELECT h.invoke_id::text AS invoke_id, h.iteration, h.repl_output,
                   h.llm_response
            FROM v15.repl_history h
            JOIN v15.invokes i ON i.invoke_id = h.invoke_id
            WHERE i.root_invoke_id = %s::uuid
            ORDER BY h.invoke_id, h.iteration
            """,
            (root_id,),
        )
        hooks = rows(
            cur,
            """
            SELECT i.invoke_id::text AS invoke_id, h.ordinal, h.channel, h.config
            FROM v15.invoke_hooks h
            JOIN v15.hook_defs d ON d.hook_def_id = h.hook_def_id
            JOIN v15.invokes i ON i.invoke_id = h.invoke_id
            WHERE i.root_invoke_id = %s::uuid
              AND d.hook_key = 'context_window_warning'
            """,
            (root_id,),
        )
        messages = [
            row["content"]
            for row in stored
            if row["kind"] == "assistant"
        ]
    running = int(
        scalar(cur, "SELECT count(*) FROM v15.statements WHERE status = 'running'") or 0
    )
    pool = None
    if pool_id:
        found = rows(
            cur,
            """
            SELECT calls_used, cost_used, calls_limit, cost_limit
            FROM v15.budget_pools
            WHERE pool_id = %s::uuid
            """,
            (pool_id,),
        )
        pool = found[0] if found else None
    by_id = {row["invoke_id"]: row for row in invokes}
    inputs_by = _group([row for row in bindings if row["kind"] == "input"], "invoke_id")
    all_bindings = _group(bindings, "invoke_id")
    stmts_by = _group(statements, "invoke_id")
    iters_by = _group(iterations, "invoke_id")
    attempts_by = _group(attempts, "invoke_id")
    events_by = _group(events, "invoke_id")
    sends_by = _group(sends, "invoke_id")
    stored_by = _group(stored, "invoke_id")
    history_by = _group(history, "invoke_id")
    children: dict[str, list[str]] = {}
    for row in invokes:
        if row["parent"]:
            children.setdefault(row["parent"], []).append(row["invoke_id"])
    expected_return = {"seal": seal, "hops": 1}
    if scenario == "recall":
        expected_return = {"seal": seal, "hops": 1, "token": token}
    expected_by_depth = {
        depth: (role_for(hops - depth + 1, hops), hops - depth + 1)
        for depth in range(1, hops + 1)
    }
    nodes = []
    delegator_ok = True
    delegator_count = 0
    bind_points = []
    multi_bind = False
    for row in invokes:
        iid = row["invoke_id"]
        parsed_inputs = {
            "note": None,
            "hops": None,
            "role": None,
            "seal": None,
            "root_id": None,
            "facts": None,
        }
        if scenario == "fanout":
            parsed_inputs["seal_a"] = None
            parsed_inputs["seal_b"] = None
        if scenario == "csi":
            parsed_inputs["task_a"] = None
            parsed_inputs["task_b"] = None
            parsed_inputs["task_c"] = None
            parsed_inputs["formula_wrong"] = None
            parsed_inputs["formula_right"] = None
            parsed_inputs["task_id"] = None
            parsed_inputs["formula"] = None
            parsed_inputs["diagnosed"] = None
            parsed_inputs["failed_task"] = None
        for binding in inputs_by.get(iid, []):
            if binding["name"] in parsed_inputs:
                parsed_inputs[binding["name"]] = parse_json(binding["value"])
        if iid != root_id:
            parsed_inputs["facts"] = None
        done_binds = [
            stmt
            for stmt in stmts_by.get(iid, [])
            if stmt["kind"] == "bind_invoke"
            and stmt["status"] == "done"
            and stmt["child_invoke_id"]
        ]
        invoke_attempts = attempts_by.get(iid, [])
        by_iter: dict[int, int] = {}
        for attempt in invoke_attempts:
            by_iter[int(attempt["iteration"])] = by_iter.get(int(attempt["iteration"]), 0) + 1
        if scenario == "fanout":
            if iid == root_id:
                frag_a, frag_b = fanout_fragments(seal)
                ret_expected = {"a": {"fragment": frag_a}, "b": {"fragment": frag_b}}
            else:
                ret_expected = {"fragment": parsed_inputs.get("seal")}
            return_matches = return_equals(cur, iid, ret_expected)
        elif scenario == "csi":
            return_matches = _csi_node_return_ok(
                iid == root_id, parsed_inputs, parse_json(row["return_value"])
            )
        else:
            return_matches = return_equals(cur, iid, expected_return)
        node = {
            "invoke_id": iid,
            "depth": int(row["depth"]),
            "parent": row["parent"],
            "status": row["status"],
            "fatal": bool(row["fatal"]),
            "error_code": row["error_code"],
            "recursion_available": bool(row["recursion_available"]),
            "return_value": parse_json(row["return_value"]),
            "inputs": parsed_inputs,
            "sqls": [stmt["sql"] for stmt in stmts_by.get(iid, [])],
            "bind_iteration": None,
            "settled_on_bind_iteration": 0,
            "max_n_on_bind_iteration": None,
            "settled_n": None,
            "unknown_attempts": sum(1 for a in invoke_attempts if a["status"] == "unknown"),
            "statement_count_on_bind_iteration": 0,
            "var_matches_child": None,
            "attempt_count": len(invoke_attempts),
            "attempts_by_iteration": [
                {"iteration": iteration, "count": count}
                for iteration, count in sorted(by_iter.items())
            ],
            "next_kind": None,
            "suspend_seq": None,
            "deliver_seq": None,
            "repl_exits_between": None,
            "return_matches": return_matches,
        }
        if scenario == "fanout" and iid == root_id:
            fanout_ok, fanout_meta = _fanout_root_bind(
                done_binds,
                stmts_by.get(iid, []),
                invoke_attempts,
                iters_by.get(iid, []),
                events_by.get(iid, []),
                cur,
                iid,
            )
            if done_binds:
                delegator_count += 1
            node.update(fanout_meta)
            if not fanout_ok:
                delegator_ok = False
                if len(done_binds) > 1:
                    multi_bind = True
        elif scenario == "csi" and iid == root_id:
            csi_bind_ok, csi_meta = _csi_root_bind(
                done_binds,
                stmts_by.get(iid, []),
                invoke_attempts,
                iters_by.get(iid, []),
                events_by.get(iid, []),
                cur,
                iid,
                attempts_by,
            )
            if done_binds:
                delegator_count += 1
            node.update(csi_meta)
            if not csi_bind_ok:
                delegator_ok = False
        elif len(done_binds) == 1:
            delegator_count += 1
            bind = done_binds[0]
            iteration = int(bind["iteration"])
            bind_name = bind["bind_name"]
            on_iter = [
                stmt for stmt in stmts_by.get(iid, []) if int(stmt["iteration"]) == iteration
            ]
            on_iter.sort(key=lambda stmt: int(stmt["stmt_index"]))
            req = [a for a in invoke_attempts if int(a["iteration"]) == iteration]
            settled = [a for a in req if a["status"] == "settled"]
            max_n = max((int(a["n"]) for a in req), default=None)
            settled_n = int(settled[0]["n"]) if len(settled) == 1 else None
            iter_rows = iters_by.get(iid, [])
            max_iter = max((int(item["iteration"]) for item in iter_rows), default=None)
            result_kind = next(
                (
                    item["result_kind"]
                    for item in iter_rows
                    if int(item["iteration"]) == iteration
                ),
                None,
            )
            ev = events_by.get(iid, [])
            suspend_seq, deliver_seq = _edge_pair(ev, bind["child_invoke_id"])
            exits = 0
            if suspend_seq is not None and deliver_seq is not None:
                exits = sum(
                    1
                    for item in ev
                    if item["event_class"] == "span"
                    and item["span"] == "repl_exec"
                    and item["phase"] == "exit"
                    and suspend_seq < int(item["seq"]) < deliver_seq
                )
            var_ok = None
            if bind["child_invoke_id"] and bind_name:
                var_ok = var_equals_child(cur, iid, bind["child_invoke_id"], bind_name)
            two = (
                len(on_iter) == 2
                and int(on_iter[0]["stmt_index"]) == 0
                and on_iter[0]["kind"] == "bind_invoke"
                and int(on_iter[1]["stmt_index"]) == 1
                and on_iter[1]["kind"] == "return"
                and on_iter[1]["status"] == "done"
                and mentions_var(on_iter[1]["sql"], bind_name or "")
            )
            attempt_ok = (
                len(settled) == 1
                and not any(a["status"] == "leased" for a in req)
                and max_n is not None
                and settled_n is not None
                and max_n == settled_n
            )
            iter_ok = result_kind == "return" and max_iter == iteration
            event_ok = (
                suspend_seq is not None
                and deliver_seq is not None
                and suspend_seq < deliver_seq
                and exits == 0
            )
            if not (two and attempt_ok and iter_ok and event_ok and var_ok is True):
                delegator_ok = False
            bind_points.append(
                {
                    "two": two,
                    "attempt_ok": attempt_ok,
                    "iter_ok": iter_ok,
                    "event_ok": event_ok,
                    "var_ok": var_ok is True,
                }
            )
            node.update(
                {
                    "bind_iteration": iteration,
                    "settled_on_bind_iteration": len(settled),
                    "max_n_on_bind_iteration": max_n,
                    "settled_n": settled_n,
                    "statement_count_on_bind_iteration": len(on_iter),
                    "var_matches_child": var_ok,
                    "next_kind": on_iter[1]["kind"] if len(on_iter) > 1 else None,
                    "suspend_seq": suspend_seq,
                    "deliver_seq": deliver_seq,
                    "repl_exits_between": exits,
                }
            )
        elif done_binds:
            delegator_ok = False
            delegator_count += 1
            multi_bind = True
        nodes.append(node)
    if scenario == "fanout":
        chain = _fanout_spine(nodes, root_id, completed_only=True)
        depth_chain = _fanout_spine(nodes, root_id, completed_only=False)
    elif scenario == "csi":
        chain = _csi_spine(nodes, root_id, completed_only=True)
        depth_chain = _csi_spine(nodes, root_id, completed_only=False)
    else:
        chain = _spine(nodes, root_id, hops, completed_only=True)
        depth_chain = _spine(nodes, root_id, hops, completed_only=False)
    deepest_ok = _deepest_ok(nodes, stmts_by, iters_by)
    events_ok = bool(nodes) and all(
        seq_continuous([int(item["seq"]) for item in events_by.get(node["invoke_id"], [])])
        for node in nodes
    )
    completed = [node for node in nodes if node["status"] == "completed"]
    scratch_names = [
        by_id[node["invoke_id"]]["scratch_schema"]
        for node in completed
        if node["invoke_id"] in by_id
    ]
    if any(name is None for name in scratch_names):
        scratch_clear = False
    elif scratch_names:
        scratch_left = int(
            scalar(
                cur,
                "SELECT count(*) FROM pg_namespace WHERE nspname = ANY(%s)",
                (scratch_names,),
            )
            or 0
        )
        scratch_clear = scratch_left == 0
    else:
        scratch_clear = True
    live = sum(1 for node in nodes if node["status"] in _LIVE)
    any_fatal = any(node["fatal"] for node in nodes)
    rejected = any(node["error_code"] == "V15_PROVIDER_REJECTED" for node in nodes)
    running_clear = running == 0 and live == 0
    chain_ok = chain is not None
    recall_root_shape = True
    root = next((node for node in nodes if node["invoke_id"] == root_id), None)
    if scenario == "recall":
        recall_root_shape = _recall_root_shape(root_id, stmts_by, iters_by, root)
    shape_ok = (
        chain_ok
        and delegator_ok
        and deepest_ok
        and events_ok
        and delegator_count >= 1
        and recall_root_shape
    )
    structural = (
        chain_ok
        and delegator_ok
        and deepest_ok
        and running_clear
        and not rejected
        and not any_fatal
        and events_ok
        and scratch_clear
        and delegator_count >= 1
        and recall_root_shape
    )
    flags: list[str] = []
    mission = False
    by_node = {node["invoke_id"]: node for node in nodes}
    for node in nodes:
        if not node["parent"]:
            continue
        if scenario in {"fanout", "csi"}:
            continue
        parent = by_node.get(node["parent"])
        parent_hops = None if parent is None else _as_int((parent["inputs"] or {}).get("hops"))
        expected_role = None if parent_hops is None else role_for(parent_hops - 1, hops)
        if _mission_gap(cur, node["parent"], node["invoke_id"], root_id, expected_role):
            mission = True
    if mission:
        flags.append("mission_not_forwarded")
    child_counts = {node["invoke_id"]: len(children.get(node["invoke_id"], [])) for node in nodes}
    if scenario == "fanout":
        if len(nodes) > 3 or any(
            child_counts[node["invoke_id"]] > (2 if node["invoke_id"] == root_id else 0)
            for node in nodes
        ):
            flags.append("over_delegation")
    elif scenario == "csi":
        if len(nodes) > 4 or any(
            child_counts[node["invoke_id"]] > (3 if node["invoke_id"] == root_id else 0)
            for node in nodes
        ):
            flags.append("over_delegation")
    elif len(nodes) > hops or any(count > 1 for count in child_counts.values()):
        flags.append("over_delegation")
    if any(not node["return_matches"] for node in nodes):
        flags.append("relay_value_mismatch")
    if any(node["unknown_attempts"] for node in nodes):
        flags.append("extra_unknown_attempts")
    finish_reasons: dict[str, int] = {}
    pricing_revision = None
    any_peak = None
    saw_provider = False
    settled_bad = False
    settled_n = 0
    settled_cost_checks = []
    for attempt in attempts:
        if attempt["status"] != "settled":
            continue
        settled_n += 1
        tokens = attempt["prompt_tokens"]
        cost = attempt["cost_usd"]
        row_ok = (
            tokens is not None
            and int(tokens) >= 1
            and cost is not None
            and Decimal(cost) > 0
        )
        if not row_ok:
            settled_bad = True
        settled_cost_checks.append(
            {
                "invoke_id": attempt["invoke_id"],
                "iteration": int(attempt["iteration"]),
                "n": None if attempt["n"] is None else int(attempt["n"]),
                "prompt_tokens": None if tokens is None else int(tokens),
                "cost_usd": None if cost is None else money(cost),
                "ok": row_ok,
            }
        )
        body = parse_json(attempt["response"])
        if isinstance(body, dict) and isinstance(body.get("provider"), dict):
            saw_provider = True
            provider = body["provider"]
            if pricing_revision is None and provider.get("pricing_revision") is not None:
                pricing_revision = provider.get("pricing_revision")
            if provider.get("peak") is True:
                any_peak = True
            elif any_peak is None and "peak" in provider:
                any_peak = bool(provider.get("peak"))
            reason = provider.get("finish_reason")
            if isinstance(reason, str):
                finish_reasons[reason] = finish_reasons.get(reason, 0) + 1
                if reason == "length" and "finish_length" not in flags:
                    flags.append("finish_length")
    text = transcript_of(messages)
    for stmt in statements:
        if stmt["error_code"] == "V15_INVOKE_FORM" and unquoted_control(stmt["sql"]):
            text["unquoted"] = True
    if scenario == "fanout":
        inputs_ok = _fanout_inputs_ok(cur, nodes, root_id, seal, note, statements)
    elif scenario == "csi":
        inputs_ok = _csi_inputs_ok(cur, nodes, root_id, seal, note, statements)
    else:
        inputs_ok = bool(nodes) and all(
            _inputs_ok(cur, node, seal, note, root_id, expected_by_depth) for node in nodes
        )
    if not inputs_ok and not mission:
        flags.append("input_mismatch")
    returns_ok = bool(nodes) and all(node["return_matches"] for node in nodes)
    if scenario == "fanout":
        relay_shape = (
            len(nodes) == 3
            and child_counts.get(root_id, 0) == 2
            and all(
                child_counts[node["invoke_id"]] == (2 if node["invoke_id"] == root_id else 0)
                for node in nodes
            )
            and all(
                node["depth"] == (1 if node["invoke_id"] == root_id else 2) for node in nodes
            )
        )
    elif scenario == "csi":
        relay_shape = (
            len(nodes) == 4
            and child_counts.get(root_id, 0) == 3
            and all(
                child_counts[node["invoke_id"]] == (3 if node["invoke_id"] == root_id else 0)
                for node in nodes
            )
            and all(
                node["depth"] == (1 if node["invoke_id"] == root_id else 2) for node in nodes
            )
        )
    else:
        relay_shape = len(nodes) == hops and all(
            child_counts[node["invoke_id"]] == (0 if node["depth"] == hops else 1)
            for node in nodes
        )
    if pool is None:
        calls_used = None
        cost_used = None
    else:
        calls_used = None if pool["calls_used"] is None else int(pool["calls_used"])
        cost_used = None if pool["cost_used"] is None else money(pool["cost_used"])
    calls_mismatch = False
    if expect_calls is not None and calls_used != expect_calls:
        calls_mismatch = True
    if pool is None or calls_used is None or cost_used is None:
        calls_mismatch = True
    elif expect_cost_zero and Decimal(cost_used) != 0:
        calls_mismatch = True
    relay_ok = relay_shape and inputs_ok and returns_ok and not calls_mismatch
    recall_flags: list[str] = []
    warning = _warning_view(root_id, nodes, sends_by, attempts_by)
    hook_ok = _hooks_ok(hooks, nodes, scenario)
    protocol_limit = None
    if root_id in by_id and by_id[root_id]["protocol_limit"] is not None:
        protocol_limit = int(by_id[root_id]["protocol_limit"])
    recall_ok = True
    chars_bug = False
    if scenario == "recall":
        recall_ok, recall_flags, chars_bug = _recall_ok(
            root_id,
            token,
            nodes,
            stmts_by,
            history_by,
            stored_by,
            all_bindings,
            attempts_by,
            sends_by,
            warning,
            hook_ok,
            protocol_limit,
            mode,
        )
    elif hooks:
        flags.append("unexpected_warning")
    csi_ok = True
    csi_flags: list[str] = []
    if scenario == "csi":
        csi_ok, csi_flags = _csi_meta_ok(root_id, nodes, stmts_by, stored_by)
    codes = set()
    for node in nodes:
        if node["error_code"]:
            codes.add(node["error_code"])
    for stmt in statements:
        if stmt["error_code"]:
            codes.add(stmt["error_code"])
    histogram_codes = set(text["classified"]) | set(text["split_failures"])
    dialect_codes = (codes | histogram_codes) & _DIALECT
    history_scope = "V15_HISTORY_SCOPE" in codes or any(
        stmt["error_sqlstate"] == "P1510" for stmt in statements
    )
    uuid_mismatch = any(
        _uuid_mismatch(stmt["sql"], root_id, stmt["error_sqlstate"]) for stmt in statements
    )
    overflow_pasted, overflow_budget = _overflow(root, nodes, stored_by, iters_by)
    max_depth = max((node["depth"] for node in nodes), default=0)
    depth_short = max_depth < hops or not any(node["depth"] == hops for node in nodes)
    cost_missing = mode == "real" and settled_n > 0 and settled_bad
    cost_checks_ok = (mode != "real") or (settled_n > 0 and not settled_bad)
    leaked = "facts_leaked" in recall_flags
    far_miss = any(
        name in recall_flags
        for name in (
            "prior_history_absent",
            "token_mismatch",
            "history_not_stored",
            "mid_prior_history",
        )
    )
    warning_missed = scenario == "recall" and structural and "warning_missed" in recall_flags
    unexpected = "unexpected_warning" in flags or "unexpected_warning" in recall_flags
    facts = {
        "codes": codes,
        "provider_rejected": rejected,
        "lease_skip": (not running_clear) and any(
            a["status"] == "leased" and a["call_started"] for a in attempts
        ),
        "successful_bind": any(
            stmt["kind"] == "bind_invoke" and stmt["status"] == "done" and stmt["child_invoke_id"]
            for stmt in statements
        ),
        "unknown_attempts": sum(node["unknown_attempts"] for node in nodes),
        "child_failed": any(node["status"] == "failed" and node["parent"] for node in nodes),
        "has_child": any(node["parent"] for node in nodes),
        "depth_short": depth_short,
        "shape_ok": shape_ok,
        "markdown": text["markdown_fence_messages"],
        "unquoted": text["unquoted"],
        "empty_messages": text["empty_messages"],
        "syntax_42601": any(stmt["error_sqlstate"] == "42601" for stmt in statements),
        "dialect_codes": dialect_codes,
        "mission_not_forwarded": mission,
        "cost_missing": cost_missing,
        "calls_mismatch": calls_mismatch,
        "finish_length": "finish_length" in flags,
        "history_scope": history_scope,
        "root_id_literal_mismatch": uuid_mismatch,
        "context_overflow_pasted": overflow_pasted,
        "context_overflow_budget": overflow_budget,
        "facts_leaked": leaked,
        "far_recall_missed": scenario == "recall" and far_miss and not depth_short,
        "chars_bug": chars_bug,
        "warning_missed": warning_missed,
        "unexpected_warning": unexpected,
        "over_delegation": "over_delegation" in flags,
        "csi_meta_missed": scenario == "csi" and not csi_ok,
    }
    hard = mode == "fake" or strict
    recall_hard_fail = scenario == "recall" and hard and not recall_ok
    csi_hard_fail = scenario == "csi" and hard and not csi_ok
    relay_hard_fail = hard and not relay_ok
    unexpected_hard = hard and unexpected
    if override_class:
        outcome = "fail"
        failure_class = override_class
    elif (
        structural
        and not cost_missing
        and not calls_mismatch
        and not relay_hard_fail
        and not recall_hard_fail
        and not csi_hard_fail
        and not unexpected_hard
    ):
        outcome = "tail_ok"
        failure_class = None
    else:
        outcome = "fail"
        failure_class = pick_class(facts)
    sum_cost = Decimal(0)
    charged = 0
    for attempt in attempts:
        if attempt["cost_usd"] is not None:
            sum_cost += Decimal(attempt["cost_usd"])
        if attempt["calls_charged"]:
            charged += 1
    text["finish_reasons"] = finish_reasons
    public_transcript = {
        "assistant_messages": text["assistant_messages"],
        "markdown_fence_messages": text["markdown_fence_messages"],
        "split_failures": text["split_failures"],
        "classified": text["classified"],
        "legal_statement_rate": text["legal_statement_rate"],
        "assistant_previews": text["assistant_previews"],
        "finish_reasons": finish_reasons,
    }
    bind_ready = bool(bind_points) and not multi_bind

    def bind_ok(key: str) -> bool:
        return bind_ready and all(item[key] for item in bind_points)

    assertions = [
        {"n": 1, "name": "depth_chain", "ok": depth_chain is not None},
        {"n": 2, "name": "chain_completed", "ok": chain is not None},
        {"n": 3, "name": "bind_exactly_one", "ok": bind_ready},
        {"n": 4, "name": "bind_iteration_two_statements", "ok": bind_ok("two")},
        {"n": 5, "name": "bind_iteration_return", "ok": bind_ok("iter_ok")},
        {"n": 6, "name": "bind_iteration_one_settled", "ok": bind_ok("attempt_ok")},
        {"n": 7, "name": "var_equals_child", "ok": bind_ok("var_ok")},
        {"n": 8, "name": "suspend_deliver_no_repl_exit", "ok": bind_ok("event_ok")},
        {"n": 9, "name": "deepest_return", "ok": deepest_ok},
        {"n": 10, "name": "quiescent", "ok": running_clear},
        {"n": 11, "name": "no_reject_no_fatal", "ok": (not rejected) and (not any_fatal)},
        {"n": 12, "name": "event_seq_continuous", "ok": events_ok},
        {"n": 13, "name": "scratch_clear", "ok": scratch_clear},
    ]
    if scenario == "fanout":
        root_node = next((node for node in nodes if node["invoke_id"] == root_id), None) or {}
        assertions = [
            {"n": 1, "name": "fanout_three_nodes", "ok": depth_chain is not None},
            {"n": 2, "name": "fanout_completed", "ok": chain is not None},
            {"n": 3, "name": "fanout_two_children", "ok": child_counts.get(root_id, 0) == 2},
            {"n": 4, "name": "fanout_iteration_three_statements", "ok": bool(root_node.get("fanout_three"))},
            {"n": 5, "name": "fanout_iteration_return", "ok": bool(root_node.get("fanout_iter_ok"))},
            {"n": 6, "name": "fanout_parent_one_settled", "ok": bool(root_node.get("fanout_attempt_ok"))},
            {"n": 7, "name": "fanout_var_a_and_b", "ok": bool(root_node.get("fanout_var_ok"))},
            {"n": 8, "name": "fanout_no_repl_exit", "ok": bool(root_node.get("fanout_pairs_ok"))},
            {"n": 9, "name": "fanout_deliver_a_before_b", "ok": bool(root_node.get("fanout_deliver_order_ok"))},
            {"n": 10, "name": "deepest_return", "ok": deepest_ok},
            {"n": 11, "name": "quiescent", "ok": running_clear},
            {"n": 12, "name": "no_reject_no_fatal", "ok": (not rejected) and (not any_fatal)},
            {"n": 13, "name": "event_seq_continuous", "ok": events_ok},
            {"n": 14, "name": "scratch_clear", "ok": scratch_clear},
        ]
    if scenario == "csi":
        root_node = next((node for node in nodes if node["invoke_id"] == root_id), None) or {}
        assertions = [
            {"n": 1, "name": "csi_four_nodes", "ok": depth_chain is not None},
            {"n": 2, "name": "csi_completed", "ok": chain is not None},
            {"n": 3, "name": "csi_three_children", "ok": child_counts.get(root_id, 0) == 3},
            {"n": 4, "name": "csi_batch1_a_before_b", "ok": bool(root_node.get("csi_batch1_order_ok"))},
            {"n": 5, "name": "csi_batch1_before_batch2", "ok": bool(root_node.get("csi_batch1_before_batch2_ok"))},
            {"n": 6, "name": "csi_bind_home_one_settled", "ok": bool(root_node.get("csi_home_settled_ok"))},
            {"n": 7, "name": "csi_children_one_settled", "ok": bool(root_node.get("csi_children_one_settled"))},
            {"n": 8, "name": "csi_var_a_b_c", "ok": bool(root_node.get("csi_var_ok"))},
            {"n": 9, "name": "csi_no_repl_exit", "ok": bool(root_node.get("csi_pairs_ok"))},
            {"n": 10, "name": "deepest_return", "ok": deepest_ok},
            {"n": 11, "name": "quiescent", "ok": running_clear},
            {"n": 12, "name": "no_reject_no_fatal", "ok": (not rejected) and (not any_fatal)},
            {"n": 13, "name": "event_seq_continuous", "ok": events_ok},
            {"n": 14, "name": "scratch_clear", "ok": scratch_clear},
        ]
    warning_ok = scenario != "recall" or (
        warning["root_tail_warned"]
        and warning["nonroot_warning_count"] == 0
        and warning["root_other_warnings"] == 0
    )
    return {
        "outcome": outcome,
        "failure_class": failure_class,
        "scenario": scenario,
        "hops": hops,
        "relay_ok": relay_ok,
        "relay_flags": flags,
        "recall_ok": recall_ok,
        "recall_flags": recall_flags,
        "csi_ok": csi_ok,
        "csi_flags": csi_flags,
        "warning_ok": warning_ok,
        "warning": warning,
        "hook_count": len(hooks),
        "protocol_limit": protocol_limit,
        "root_id": root_id,
        "nodes": nodes,
        "transcript": public_transcript,
        "cost": {
            "sum_cost_usd": format(sum_cost, "f"),
            "cost_used": cost_used,
            "calls_used": calls_used,
            "calls_charged": charged,
            "calls_limit": None if pool is None else int(pool["calls_limit"]) if pool["calls_limit"] is not None else None,
            "cost_limit": None if pool is None or pool["cost_limit"] is None else money(pool["cost_limit"]),
            "pricing_revision": pricing_revision,
            "any_peak": any_peak,
            "provider_meta": None if saw_provider else "absent",
        },
        "events_ok": events_ok,
        "scratch_clear": scratch_clear,
        "running": running,
        "leased": live,
        "assertions": assertions,
        "cost_checks_ok": cost_checks_ok,
        "cost_missing": cost_missing,
        "settled_cost_checks": settled_cost_checks,
        "tail_parts": {
            "chain_ok": chain_ok,
            "delegator_ok": delegator_ok,
            "deepest_ok": deepest_ok,
            "running_clear": running_clear,
            "rejected": rejected,
            "any_fatal": any_fatal,
            "events_ok": events_ok,
            "scratch_clear": scratch_clear,
            "delegator_count": delegator_count,
            "calls_mismatch": calls_mismatch,
            "recall_root_shape": recall_root_shape,
        },
    }


def _warning_view(root_id, nodes, sends_by, attempts_by) -> dict:
    root_sends = [
        {"iteration": int(item["iteration"]), "input_chars": int(item["input_chars"])}
        for item in sends_by.get(root_id, [])
        if item["iteration"] is not None and item["input_chars"] is not None
    ]
    nonroot = []
    for node in nodes:
        if node["invoke_id"] == root_id:
            continue
        for item in sends_by.get(node["invoke_id"], []):
            if item["input_chars"] is not None:
                nonroot.append(int(item["input_chars"]))
    root = next((node for node in nodes if node["invoke_id"] == root_id), None)
    bind_iter = None if root is None else root.get("bind_iteration")
    tail_warned = False
    nonroot_warnings = 0
    other_root = 0
    if bind_iter is not None:
        for attempt in attempts_by.get(root_id, []):
            if int(attempt["iteration"]) != bind_iter or attempt["status"] != "settled":
                continue
            hits = _warning_hits(attempt["request"])
            tail_warned = any(
                "jaz.prior_history" in str(item.get("content") or "")
                and "jaz.bind_invoke" in str(item.get("content") or "")
                for item in hits
            )
    for node in nodes:
        for attempt in attempts_by.get(node["invoke_id"], []):
            hits = _warning_hits(attempt["request"])
            if not hits:
                continue
            if node["invoke_id"] != root_id:
                nonroot_warnings += len(hits)
            elif bind_iter is None or int(attempt["iteration"]) != bind_iter:
                other_root += len(hits)
    return {
        "root_sends": root_sends,
        "nonroot_max": None if not nonroot else max(nonroot),
        "root_tail_warned": tail_warned,
        "nonroot_warning_count": nonroot_warnings,
        "root_other_warnings": other_root,
    }


def _hooks_ok(hooks, nodes, scenario) -> bool:
    if scenario != "recall":
        return len(hooks) == 0
    if len(hooks) != len(nodes) or not nodes:
        return False
    seen = {row["invoke_id"] for row in hooks}
    if seen != {node["invoke_id"] for node in nodes}:
        return False
    return all(
        int(row["ordinal"]) == 4
        and row["channel"] == "propagating"
        and _ratio_ok(row["config"])
        for row in hooks
    )


def _recall_ok(
    root_id,
    token,
    nodes,
    stmts_by,
    history_by,
    stored_by,
    all_bindings,
    attempts_by,
    sends_by,
    warning,
    hook_ok,
    protocol_limit,
    mode,
):
    flags = []
    leaf = next((node for node in nodes if node["depth"] == max(n["depth"] for n in nodes)), None)
    root_hist = history_by.get(root_id, [])
    iter0 = next((row for row in root_hist if int(row["iteration"]) == 0), None)
    history_text = "" if iter0 is None or iter0["repl_output"] is None else iter0["repl_output"]
    if token is None or f"token={token}" not in history_text:
        flags.append("history_not_stored")
    leaf_sql = "\n".join(leaf["sqls"]) if leaf else ""
    if (
        _PRIOR_HISTORY.search(leaf_sql) is None
        or root_id.casefold() not in leaf_sql.casefold()
    ):
        flags.append("prior_history_absent")
    for node in nodes:
        if node["inputs"].get("role") != "mid":
            continue
        if any(_PRIOR_HISTORY.search(sql or "") for sql in node["sqls"]):
            flags.append("mid_prior_history")
            break
    leaked = False
    for node in nodes:
        if node["invoke_id"] == root_id:
            continue
        names = {row["name"] for row in all_bindings.get(node["invoke_id"], [])}
        if "facts" in names:
            leaked = True
        blob = "\n".join(
            row["value_text"] or ""
            for row in all_bindings.get(node["invoke_id"], [])
            if row["kind"] == "input"
        )
        seed = "\n".join(
            row["content"] or ""
            for row in stored_by.get(node["invoke_id"], [])
            if row["message_id"] == "seed:inputs"
        )
        if token and (token in blob or token in seed):
            leaked = True
    if leaked:
        flags.append("facts_leaked")
    token_mismatch = any(
        not isinstance(node["return_value"], dict)
        or node["return_value"].get("token") != token
        for node in nodes
    )
    if token_mismatch:
        flags.append("token_mismatch")
    if not warning["root_tail_warned"]:
        flags.append("warning_missed")
    if warning["nonroot_warning_count"] or warning["root_other_warnings"]:
        flags.append("unexpected_warning")
    clean_messages = not any(row["message_id"] == _WARN_ID for row in _flat(stored_by))
    if not clean_messages:
        flags.append("warning_persisted")
    truncated = any(_MARKER in (row["content"] or "") for row in _flat(stored_by))
    if truncated:
        flags.append("truncated")
    root_sends = {item["iteration"]: item["input_chars"] for item in warning["root_sends"]}
    bind_iter = next(
        (node["bind_iteration"] for node in nodes if node["invoke_id"] == root_id),
        None,
    )
    chars_ok = (
        0 in root_sends
        and root_sends[0] < WARN_FLOOR
        and bind_iter in root_sends
        and WARN_FLOOR <= root_sends[bind_iter] <= INVOKE_LIMIT
        and warning["nonroot_max"] is not None
        and warning["nonroot_max"] < WARN_FLOOR
        and not truncated
    )
    nonroot_ids = [node["invoke_id"] for node in nodes if node["invoke_id"] != root_id]
    if nonroot_ids and any(not sends_by.get(iid) for iid in nonroot_ids):
        chars_ok = False
    if not chars_ok:
        flags.append("chars_out_of_range")
    if not hook_ok or protocol_limit != INVOKE_LIMIT:
        flags.append("hook_shape")
    ok = not flags
    chars_bug = mode == "fake" and "chars_out_of_range" in flags
    return ok, flags, chars_bug


def _flat(grouped) -> list[dict]:
    out = []
    for items in grouped.values():
        out.extend(items)
    return out


def _overflow(root, nodes, stored_by, iters_by):
    if root is None or root["error_code"] != "V15_VALUE_INVALID":
        return False, False
    if any(node["parent"] == root["invoke_id"] for node in nodes):
        return False, False
    continues = [
        item
        for item in iters_by.get(root["invoke_id"], [])
        if item["result_kind"] == "continue" and item["status"] == "done"
    ]
    if not continues:
        return False, False
    longest = 0
    for item in continues:
        for row in stored_by.get(root["invoke_id"], []):
            if row["kind"] == "assistant" and row["iteration"] is not None and int(row["iteration"]) == int(item["iteration"]):
                longest = max(longest, len(row["content"] or ""))
    if longest > 500:
        return True, False
    return False, True


def _uuid_mismatch(sql: str, root_id: str, sqlstate) -> bool:
    if _PRIOR_HISTORY.search(sql or "") is None:
        return False
    if sqlstate == "22P02":
        return True
    found = _UUID.findall(sql or "")
    return any(item.lower() != root_id.lower() for item in found)


def _recall_root_shape(root_id, stmts_by, iters_by, root) -> bool:
    if root is None or root.get("bind_iteration") != 1:
        return False
    iter0 = [stmt for stmt in stmts_by.get(root_id, []) if int(stmt["iteration"]) == 0]
    done = [stmt for stmt in iter0 if stmt["status"] == "done"]
    prints = [stmt for stmt in done if stmt["kind"] == "print"]
    binds = [stmt for stmt in iter0 if stmt["kind"] == "bind_invoke"]
    kind = next(
        (item["result_kind"] for item in iters_by.get(root_id, []) if int(item["iteration"]) == 0),
        None,
    )
    return kind == "continue" and len(done) == 1 and len(prints) == 1 and not binds


def _same_child(left, right) -> bool:
    if left is None or right is None or left == "" or right == "":
        return False
    return str(left).lower() == str(right).lower()


def _edge_pair(ev: list[dict], child_id: str) -> tuple[int | None, int | None]:
    def seq(item: dict) -> int:
        return int(item["seq"])

    suspends = [item for item in ev if item.get("op") == "suspend"]
    delivers = [item for item in ev if item.get("op") == "deliver"]
    named_s = [item for item in suspends if _same_child(item.get("child_invoke_id"), child_id)]
    named_d = [item for item in delivers if _same_child(item.get("child_invoke_id"), child_id)]
    if named_s:
        suspend_seq = min(seq(item) for item in named_s)
        later = [seq(item) for item in named_d if seq(item) > suspend_seq]
        if later:
            return suspend_seq, min(later)
        nxt = min((seq(item) for item in suspends if seq(item) > suspend_seq), default=None)
        interval = [
            seq(item)
            for item in delivers
            if seq(item) > suspend_seq
            and (nxt is None or seq(item) < nxt)
            and _deliver_matches(item, child_id)
        ]
        if interval:
            return suspend_seq, min(interval)
        return None, None
    if (
        len(suspends) == 1
        and len(delivers) == 1
        and seq(suspends[0]) < seq(delivers[0])
        and _deliver_matches(delivers[0], child_id)
    ):
        return seq(suspends[0]), seq(delivers[0])
    return None, None


def _deliver_matches(item: dict, child_id: str) -> bool:
    cid = item.get("child_invoke_id")
    if cid is None or cid == "":
        return True
    return _same_child(cid, child_id)


def _mission_gap(cur, parent_id: str, child_id: str, root_id: str, expected_role: str | None) -> bool:
    missing_note = not scalar(
        cur,
        """
        SELECT EXISTS (
          SELECT 1
          FROM v15.bindings
          WHERE invoke_id = %s::uuid
            AND kind = 'input'
            AND name = 'note'
            AND value IS NOT NULL
            AND jsonb_typeof(value) <> 'null'
        )
        """,
        (child_id,),
    )
    hops_ok = scalar(
        cur,
        """
        SELECT EXISTS (
          SELECT 1
          FROM v15.bindings c
          JOIN v15.bindings p
            ON p.invoke_id = %s::uuid
           AND p.kind = 'input'
           AND p.name = 'hops'
          WHERE c.invoke_id = %s::uuid
            AND c.kind = 'input'
            AND c.name = 'hops'
            AND CASE
                  WHEN jsonb_typeof(p.value) = 'number'
                   AND jsonb_typeof(c.value) = 'number'
                  THEN (c.value #>> '{}')::numeric = (p.value #>> '{}')::numeric - 1
                  ELSE false
                END
        )
        """,
        (parent_id, child_id),
    )
    root_ok = scalar(
        cur,
        """
        SELECT EXISTS (
          SELECT 1
          FROM v15.bindings
          WHERE invoke_id = %s::uuid
            AND kind = 'input'
            AND name = 'root_id'
            AND value = to_jsonb(%s::text)
        )
        """,
        (child_id, root_id),
    )
    role_ok = False if expected_role is None else scalar(
        cur,
        """
        SELECT EXISTS (
          SELECT 1
          FROM v15.bindings
          WHERE invoke_id = %s::uuid
            AND kind = 'input'
            AND name = 'role'
            AND value = to_jsonb(%s::text)
        )
        """,
        (child_id, expected_role),
    )
    return bool(missing_note or not hops_ok or not root_ok or not role_ok)


def _inputs_ok(cur, node: dict, seal: str, note: str, root_id: str, expected_by_depth: dict) -> bool:
    depth = node["depth"]
    if depth not in expected_by_depth:
        return False
    role, hops = expected_by_depth[depth]
    iid = node["invoke_id"]
    return (
        input_equals(cur, iid, "role", role)
        and input_equals(cur, iid, "hops", hops)
        and input_equals(cur, iid, "seal", seal)
        and input_equals(cur, iid, "note", note)
        and input_equals(cur, iid, "root_id", root_id)
    )


def _spine(nodes: list[dict], root_id: str, hops: int, *, completed_only: bool):
    by_parent: dict[str | None, list[dict]] = {}
    for node in nodes:
        by_parent.setdefault(node["parent"], []).append(node)
    current = next(
        (node for node in nodes if node["invoke_id"] == root_id and node["depth"] == 1),
        None,
    )
    if current is None:
        return None
    if completed_only and not _completed(current):
        return None
    chain = [current]
    for depth in range(2, hops + 1):
        kids = [
            child
            for child in by_parent.get(current["invoke_id"], [])
            if child["depth"] == depth
        ]
        if len(kids) != 1:
            return None
        current = kids[0]
        if completed_only and not _completed(current):
            return None
        chain.append(current)
    return chain


def _completed(node: dict) -> bool:
    return (
        node["status"] == "completed"
        and node["fatal"] is False
        and node["return_value"] is not None
    )


def _deepest_ok(nodes: list[dict], stmts_by: dict, iters_by: dict) -> bool:
    if not nodes:
        return False
    max_depth = max(node["depth"] for node in nodes)
    deepest = [node for node in nodes if node["depth"] == max_depth]
    if not deepest:
        return False
    for node in deepest:
        if any(other["parent"] == node["invoke_id"] for other in nodes):
            return False
        iter_rows = iters_by.get(node["invoke_id"], [])
        if not iter_rows:
            return False
        max_iter = max(int(item["iteration"]) for item in iter_rows)
        kind = next(
            item["result_kind"]
            for item in iter_rows
            if int(item["iteration"]) == max_iter
        )
        if kind != "return":
            return False
        done_bind = any(
            stmt["kind"] == "bind_invoke"
            and stmt["status"] == "done"
            and int(stmt["iteration"]) == max_iter
            for stmt in stmts_by.get(node["invoke_id"], [])
        )
        if done_bind:
            return False
    return True


def _fanout_spine(nodes: list[dict], root_id: str, *, completed_only: bool):
    root = next(
        (node for node in nodes if node["invoke_id"] == root_id and node["depth"] == 1),
        None,
    )
    if root is None:
        return None
    if completed_only and not _completed(root):
        return None
    leaves = [node for node in nodes if node["parent"] == root_id]
    if len(leaves) != 2 or len(nodes) != 3:
        return None
    if any(node["depth"] != 2 for node in leaves):
        return None
    if any(other["parent"] == leaf["invoke_id"] for leaf in leaves for other in nodes):
        return None
    if completed_only and any(not _completed(leaf) for leaf in leaves):
        return None
    return [root, *sorted(leaves, key=lambda node: node["invoke_id"])]


def _fanout_inputs_ok(cur, nodes: list[dict], root_id: str, seal: str, note: str, statements: list[dict]) -> bool:
    if len(nodes) != 3:
        return False
    frag_a, frag_b = fanout_fragments(seal)
    if not (
        input_equals(cur, root_id, "role", "root")
        and input_equals(cur, root_id, "hops", 1)
        and input_equals(cur, root_id, "seal", seal)
        and input_equals(cur, root_id, "note", note)
        and input_equals(cur, root_id, "root_id", root_id)
        and input_equals(cur, root_id, "seal_a", frag_a)
        and input_equals(cur, root_id, "seal_b", frag_b)
    ):
        return False
    named = {
        stmt["bind_name"]: stmt["child_invoke_id"]
        for stmt in statements
        if stmt["invoke_id"] == root_id
        and stmt["kind"] == "bind_invoke"
        and stmt["status"] == "done"
        and stmt["bind_name"] in {"a", "b"}
        and stmt["child_invoke_id"]
    }
    if set(named) != {"a", "b"}:
        return False
    for name, frag in (("a", frag_a), ("b", frag_b)):
        child_id = named[name]
        if not (
            input_equals(cur, child_id, "role", "leaf")
            and input_equals(cur, child_id, "hops", 1)
            and input_equals(cur, child_id, "seal", frag)
            and input_equals(cur, child_id, "note", note)
            and input_equals(cur, child_id, "root_id", root_id)
        ):
            return False
    return True


def _fanout_root_bind(
    done_binds: list[dict],
    stmts: list[dict],
    invoke_attempts: list[dict],
    iter_rows: list[dict],
    ev: list[dict],
    cur,
    iid: str,
) -> tuple[bool, dict]:
    empty = {}
    if len(done_binds) != 2:
        return False, empty
    ordered = sorted(done_binds, key=lambda stmt: int(stmt["stmt_index"]))
    if (
        ordered[0]["bind_name"] != "a"
        or ordered[1]["bind_name"] != "b"
        or int(ordered[0]["iteration"]) != int(ordered[1]["iteration"])
        or int(ordered[0]["stmt_index"]) != 0
        or int(ordered[1]["stmt_index"]) != 1
    ):
        return False, empty
    iteration = int(ordered[0]["iteration"])
    on_iter = [stmt for stmt in stmts if int(stmt["iteration"]) == iteration]
    on_iter.sort(key=lambda stmt: int(stmt["stmt_index"]))
    three = (
        len(on_iter) == 3
        and on_iter[0]["kind"] == "bind_invoke"
        and on_iter[1]["kind"] == "bind_invoke"
        and on_iter[2]["kind"] == "return"
        and on_iter[2]["status"] == "done"
        and mentions_var(on_iter[2]["sql"], "a")
        and mentions_var(on_iter[2]["sql"], "b")
    )
    req = [attempt for attempt in invoke_attempts if int(attempt["iteration"]) == iteration]
    settled = [attempt for attempt in req if attempt["status"] == "settled"]
    max_n = max((int(attempt["n"]) for attempt in req), default=None)
    settled_n = int(settled[0]["n"]) if len(settled) == 1 else None
    max_iter = max((int(item["iteration"]) for item in iter_rows), default=None)
    result_kind = next(
        (item["result_kind"] for item in iter_rows if int(item["iteration"]) == iteration),
        None,
    )
    attempt_ok = (
        len(settled) == 1
        and not any(attempt["status"] == "leased" for attempt in req)
        and max_n is not None
        and settled_n is not None
        and max_n == settled_n
    )
    iter_ok = result_kind == "return" and max_iter == iteration
    edges = []
    var_ok_all = True
    for bind in ordered:
        suspend_seq, deliver_seq = _edge_pair(ev, bind["child_invoke_id"])
        exits = 0
        if suspend_seq is not None and deliver_seq is not None:
            exits = sum(
                1
                for item in ev
                if item["event_class"] == "span"
                and item["span"] == "repl_exec"
                and item["phase"] == "exit"
                and suspend_seq < int(item["seq"]) < deliver_seq
            )
        event_ok = (
            suspend_seq is not None
            and deliver_seq is not None
            and suspend_seq < deliver_seq
            and exits == 0
        )
        var_ok = None
        if bind["child_invoke_id"] and bind["bind_name"]:
            var_ok = var_equals_child(cur, iid, bind["child_invoke_id"], bind["bind_name"])
        if var_ok is not True:
            var_ok_all = False
        edges.append(
            {
                "bind_name": bind["bind_name"],
                "child_invoke_id": bind["child_invoke_id"],
                "suspend_seq": suspend_seq,
                "deliver_seq": deliver_seq,
                "repl_exits_between": exits,
                "event_ok": event_ok,
                "var_ok": var_ok is True,
            }
        )
    pairs_ok = bool(edges) and all(edge["event_ok"] for edge in edges)
    order_ok = (
        len(edges) == 2
        and edges[0]["deliver_seq"] is not None
        and edges[1]["deliver_seq"] is not None
        and edges[0]["deliver_seq"] < edges[1]["deliver_seq"]
    )
    ok = three and attempt_ok and iter_ok and pairs_ok and order_ok and var_ok_all
    meta = {
        "bind_iteration": iteration,
        "settled_on_bind_iteration": len(settled),
        "max_n_on_bind_iteration": max_n,
        "settled_n": settled_n,
        "statement_count_on_bind_iteration": len(on_iter),
        "var_matches_child": var_ok_all,
        "next_kind": on_iter[2]["kind"] if len(on_iter) > 2 else None,
        "suspend_seq": edges[0]["suspend_seq"] if edges else None,
        "deliver_seq": edges[0]["deliver_seq"] if edges else None,
        "repl_exits_between": edges[0]["repl_exits_between"] if edges else None,
        "fanout_three": three,
        "fanout_attempt_ok": attempt_ok,
        "fanout_iter_ok": iter_ok,
        "fanout_pairs_ok": pairs_ok,
        "fanout_var_ok": var_ok_all,
        "fanout_deliver_order_ok": order_ok,
        "fanout_edges": edges,
    }
    return ok, meta


def _contains_value(body, expected) -> bool:
    if body == expected:
        return True
    if isinstance(body, dict):
        return any(_contains_value(item, expected) for item in body.values())
    if isinstance(body, list):
        return any(_contains_value(item, expected) for item in body)
    return False


def _csi_node_return_ok(is_root: bool, inputs: dict, ret) -> bool:
    if is_root:
        return _contains_value(ret, CSI_ANSWER)
    if not isinstance(ret, dict) or not isinstance(ret.get("history"), list):
        return False
    task_id = inputs.get("task_id")
    if task_id == CSI_TASK_A:
        return (
            ret.get("ok") is False
            and ret.get("error") == CSI_ERROR
            and ret.get("task_id") == CSI_TASK_A
        )
    if task_id == CSI_TASK_B:
        return (
            ret.get("ok") is False
            and ret.get("error") == CSI_ERROR
            and ret.get("task_id") == CSI_TASK_B
        )
    if task_id == CSI_TASK_C:
        return (
            ret.get("ok") is True
            and ret.get("answer") == CSI_ANSWER
            and ret.get("task_id") == CSI_TASK_C
        )
    return False


def _csi_spine(nodes: list[dict], root_id: str, *, completed_only: bool):
    root = next(
        (node for node in nodes if node["invoke_id"] == root_id and node["depth"] == 1),
        None,
    )
    if root is None:
        return None
    if completed_only and not _completed(root):
        return None
    leaves = [node for node in nodes if node["parent"] == root_id]
    if len(leaves) != 3 or len(nodes) != 4:
        return None
    if any(node["depth"] != 2 for node in leaves):
        return None
    if any(other["parent"] == leaf["invoke_id"] for leaf in leaves for other in nodes):
        return None
    if completed_only and any(not _completed(leaf) for leaf in leaves):
        return None
    return [root, *sorted(leaves, key=lambda node: node["invoke_id"])]


def _csi_inputs_ok(cur, nodes: list[dict], root_id: str, seal: str, note: str, statements: list[dict]) -> bool:
    if len(nodes) != 4:
        return False
    if not (
        input_equals(cur, root_id, "role", "root")
        and input_equals(cur, root_id, "hops", 1)
        and input_equals(cur, root_id, "seal", seal)
        and input_equals(cur, root_id, "note", note)
        and input_equals(cur, root_id, "root_id", root_id)
        and input_equals(cur, root_id, "task_a", CSI_TASK_A)
        and input_equals(cur, root_id, "task_b", CSI_TASK_B)
        and input_equals(cur, root_id, "task_c", CSI_TASK_C)
        and input_equals(cur, root_id, "formula_wrong", CSI_FORMULA_WRONG)
        and input_equals(cur, root_id, "formula_right", CSI_FORMULA_RIGHT)
    ):
        return False
    named = {
        stmt["bind_name"]: stmt["child_invoke_id"]
        for stmt in statements
        if stmt["invoke_id"] == root_id
        and stmt["kind"] == "bind_invoke"
        and stmt["status"] == "done"
        and stmt["bind_name"] in {"a", "b", "c"}
        and stmt["child_invoke_id"]
    }
    if set(named) != {"a", "b", "c"}:
        return False
    specs = (
        ("a", CSI_TASK_A, CSI_FORMULA_WRONG),
        ("b", CSI_TASK_B, CSI_FORMULA_WRONG),
        ("c", CSI_TASK_C, CSI_FORMULA_RIGHT),
    )
    for name, task_id, formula in specs:
        child_id = named[name]
        if not (
            input_equals(cur, child_id, "role", "leaf")
            and input_equals(cur, child_id, "hops", 1)
            and input_equals(cur, child_id, "seal", seal)
            and input_equals(cur, child_id, "note", note)
            and input_equals(cur, child_id, "root_id", root_id)
            and input_equals(cur, child_id, "task_id", task_id)
            and input_equals(cur, child_id, "formula", formula)
        ):
            return False
    return True


def _csi_home_settled(invoke_attempts: list[dict], iteration: int) -> bool:
    req = [attempt for attempt in invoke_attempts if int(attempt["iteration"]) == iteration]
    settled = [attempt for attempt in req if attempt["status"] == "settled"]
    max_n = max((int(attempt["n"]) for attempt in req), default=None)
    settled_n = int(settled[0]["n"]) if len(settled) == 1 else None
    return (
        len(settled) == 1
        and not any(attempt["status"] == "leased" for attempt in req)
        and max_n is not None
        and settled_n is not None
        and max_n == settled_n
    )


def _csi_root_bind(
    done_binds: list[dict],
    stmts: list[dict],
    invoke_attempts: list[dict],
    iter_rows: list[dict],
    ev: list[dict],
    cur,
    iid: str,
    attempts_by: dict,
) -> tuple[bool, dict]:
    empty = {}
    if len(done_binds) != 3:
        return False, empty
    ordered = sorted(
        done_binds, key=lambda stmt: (int(stmt["iteration"]), int(stmt["stmt_index"]))
    )
    if [stmt["bind_name"] for stmt in ordered] != ["a", "b", "c"]:
        return False, empty
    batch1_iter = int(ordered[0]["iteration"])
    if int(ordered[1]["iteration"]) != batch1_iter:
        return False, empty
    if int(ordered[0]["stmt_index"]) != 0 or int(ordered[1]["stmt_index"]) != 1:
        return False, empty
    batch2_iter = int(ordered[2]["iteration"])
    if batch2_iter <= batch1_iter:
        return False, empty
    on_b1 = [stmt for stmt in stmts if int(stmt["iteration"]) == batch1_iter]
    on_b1.sort(key=lambda stmt: int(stmt["stmt_index"]))
    batch1_two = (
        len(on_b1) == 2
        and on_b1[0]["kind"] == "bind_invoke"
        and on_b1[1]["kind"] == "bind_invoke"
        and on_b1[0]["bind_name"] == "a"
        and on_b1[1]["bind_name"] == "b"
        and on_b1[0]["status"] == "done"
        and on_b1[1]["status"] == "done"
    )
    on_b2 = [stmt for stmt in stmts if int(stmt["iteration"]) == batch2_iter]
    on_b2.sort(key=lambda stmt: int(stmt["stmt_index"]))
    binds_b2 = [stmt for stmt in on_b2 if stmt["kind"] == "bind_invoke"]
    batch2_one = (
        bool(on_b2)
        and all(stmt["status"] == "done" for stmt in on_b2)
        and len(binds_b2) == 1
        and binds_b2[0]["bind_name"] == "c"
        and binds_b2[0]["status"] == "done"
        and on_b2[-1]["kind"] == "bind_invoke"
    )
    home_ok = _csi_home_settled(invoke_attempts, batch1_iter) and _csi_home_settled(
        invoke_attempts, batch2_iter
    )
    b1_kind = next(
        (item["result_kind"] for item in iter_rows if int(item["iteration"]) == batch1_iter),
        None,
    )
    b2_kind = next(
        (item["result_kind"] for item in iter_rows if int(item["iteration"]) == batch2_iter),
        None,
    )
    max_iter = max((int(item["iteration"]) for item in iter_rows), default=None)
    final_kind = None
    if max_iter is not None:
        final_kind = next(
            (item["result_kind"] for item in iter_rows if int(item["iteration"]) == max_iter),
            None,
        )
    iter_ok = (
        b1_kind == "continue"
        and b2_kind == "continue"
        and final_kind == "return"
        and max_iter is not None
        and max_iter > batch2_iter
    )
    edges = []
    var_ok_all = True
    for bind in ordered:
        suspend_seq, deliver_seq = _edge_pair(ev, bind["child_invoke_id"])
        exits = 0
        if suspend_seq is not None and deliver_seq is not None:
            exits = sum(
                1
                for item in ev
                if item["event_class"] == "span"
                and item["span"] == "repl_exec"
                and item["phase"] == "exit"
                and suspend_seq < int(item["seq"]) < deliver_seq
            )
        event_ok = (
            suspend_seq is not None
            and deliver_seq is not None
            and suspend_seq < deliver_seq
            and exits == 0
        )
        var_ok = None
        if bind["child_invoke_id"] and bind["bind_name"]:
            var_ok = var_equals_child(cur, iid, bind["child_invoke_id"], bind["bind_name"])
        if var_ok is not True:
            var_ok_all = False
        edges.append(
            {
                "bind_name": bind["bind_name"],
                "child_invoke_id": bind["child_invoke_id"],
                "iteration": int(bind["iteration"]),
                "suspend_seq": suspend_seq,
                "deliver_seq": deliver_seq,
                "repl_exits_between": exits,
                "event_ok": event_ok,
                "var_ok": var_ok is True,
            }
        )
    pairs_ok = bool(edges) and all(edge["event_ok"] for edge in edges)
    order_ab = (
        len(edges) == 3
        and edges[0]["deliver_seq"] is not None
        and edges[1]["deliver_seq"] is not None
        and edges[0]["deliver_seq"] < edges[1]["deliver_seq"]
    )
    batch1_before_batch2 = (
        len(edges) == 3
        and edges[0]["deliver_seq"] is not None
        and edges[1]["deliver_seq"] is not None
        and edges[2]["suspend_seq"] is not None
        and edges[0]["deliver_seq"] < edges[2]["suspend_seq"]
        and edges[1]["deliver_seq"] < edges[2]["suspend_seq"]
    )
    children_settled_ok = True
    for bind in ordered:
        child_id = bind["child_invoke_id"]
        child_attempts = attempts_by.get(child_id, []) if child_id else []
        settled = [attempt for attempt in child_attempts if attempt["status"] == "settled"]
        if len(settled) != 1 or len(child_attempts) != 1:
            children_settled_ok = False
            break
    ok = (
        batch1_two
        and batch2_one
        and home_ok
        and iter_ok
        and pairs_ok
        and order_ab
        and batch1_before_batch2
        and var_ok_all
        and children_settled_ok
    )
    req0 = [attempt for attempt in invoke_attempts if int(attempt["iteration"]) == batch1_iter]
    settled0 = [attempt for attempt in req0 if attempt["status"] == "settled"]
    max_n = max((int(attempt["n"]) for attempt in req0), default=None)
    settled_n = int(settled0[0]["n"]) if len(settled0) == 1 else None
    meta = {
        "bind_iteration": batch1_iter,
        "settled_on_bind_iteration": len(settled0),
        "max_n_on_bind_iteration": max_n,
        "settled_n": settled_n,
        "statement_count_on_bind_iteration": len(on_b1),
        "var_matches_child": var_ok_all,
        "next_kind": None,
        "suspend_seq": edges[0]["suspend_seq"] if edges else None,
        "deliver_seq": edges[0]["deliver_seq"] if edges else None,
        "repl_exits_between": edges[0]["repl_exits_between"] if edges else None,
        "csi_batch1_two": batch1_two,
        "csi_batch2_one": batch2_one,
        "csi_home_settled_ok": home_ok,
        "csi_iter_ok": iter_ok,
        "csi_pairs_ok": pairs_ok,
        "csi_var_ok": var_ok_all,
        "csi_batch1_order_ok": order_ab,
        "csi_batch1_before_batch2_ok": batch1_before_batch2,
        "csi_children_one_settled": children_settled_ok,
        "csi_batch2_iteration": batch2_iter,
        "csi_edges": edges,
    }
    return ok, meta


def _csi_meta_ok(root_id: str, nodes: list[dict], stmts_by: dict, stored_by: dict) -> tuple[bool, list[str]]:
    flags: list[str] = []
    root = next((node for node in nodes if node["invoke_id"] == root_id), None)
    if root is None:
        return False, ["csi_root_missing"]
    batch2 = root.get("csi_batch2_iteration")
    blob = ""
    if batch2 is not None:
        blob = "\n".join(
            stmt["sql"] or ""
            for stmt in stmts_by.get(root_id, [])
            if int(stmt["iteration"]) == int(batch2)
        )
        for row in stored_by.get(root_id, []):
            if (
                row["kind"] == "assistant"
                and row["iteration"] is not None
                and int(row["iteration"]) == int(batch2)
            ):
                blob += "\n" + (row["content"] or "")
    if CSI_ERROR not in blob and CSI_TASK_A not in blob and CSI_TASK_B not in blob:
        flags.append("cites_missed")
    if not _contains_value(root.get("return_value"), CSI_ANSWER):
        flags.append("answer_missed")
    return not flags, flags

