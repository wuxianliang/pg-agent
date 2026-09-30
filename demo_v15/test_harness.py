"""Fake fixtures and a keyless real-mode subprocess. Deletes its own database."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DEMO))

from server import get_server

from db import DEFAULT_DB, database_exists, drop_database
from drive import run
from script import continue_then_tail
from task import (
    HopsInvalid,
    NoteInvalid,
    ScenarioInvalid,
    CSI_ANSWER,
    CSI_ERROR,
    CSI_FORMULA_RIGHT,
    CSI_FORMULA_WRONG,
    CSI_TASK_A,
    CSI_TASK_B,
    CSI_TASK_C,
    fanout_fragments,
    note_for,
    solve_n,
    validate_hops,
    validate_note,
    validate_scenario,
)

HARNESS_DB = "agent_demo_v15_harness"
BOUND_DB = "agent_demo_v15_bound"
DRIVE = DEMO / "drive.py"
_STRIP = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_API_URI",
    "OPENAI_MODEL",
    "UV_ENV_FILE",
)


def check(label: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise SystemExit(f"FAIL {label}: {detail}")


def _node(result: dict, depth: int) -> dict:
    return next(node for node in result["nodes"] if node["depth"] == depth)


def _run(scenario: str, hops: int, replies=None) -> dict:
    out = run(
        dbname=HARNESS_DB,
        mode="fake",
        scenario=scenario,
        hops=hops,
        note=note_for(scenario),
        replies=replies,
        expect_cost_zero=True,
    )
    result = out["result"] or {}
    check(
        f"{scenario}-{hops}",
        out["exit_code"] == 0 and result.get("outcome") == "tail_ok" and result.get("relay_ok"),
        {
            "exit": out["exit_code"],
            "line": out["line"],
            "class": result.get("failure_class"),
            "flags": result.get("relay_flags"),
            "recall": result.get("recall_flags"),
            "parts": result.get("tail_parts"),
            "calls": (result.get("cost") or {}).get("calls_used"),
        },
    )
    return result


def chain_cases() -> None:
    happy = _run("chain", 3)
    roles = [_node(happy, depth)["inputs"]["role"] for depth in (1, 2, 3)]
    check("chain3 roles", roles == ["root", "mid", "leaf"], roles)
    check("chain3 calls", happy["cost"]["calls_used"] == 3, happy["cost"])
    check("chain3 hooks", happy.get("hook_count") == 0, happy.get("hook_count"))
    mid = _run("chain", 5)
    check("chain5 calls", mid["cost"]["calls_used"] == 5, mid["cost"])
    check(
        "chain5 mids",
        all(_node(mid, depth)["inputs"]["role"] == "mid" for depth in (2, 3, 4)),
        [_node(mid, depth)["inputs"]["role"] for depth in (2, 3, 4)],
    )
    check("chain5 leaf recursion", _node(mid, 5)["recursion_available"] is True, _node(mid, 5))
    deep = _run("chain", 8)
    leaf = _node(deep, 8)
    check("chain8 calls", deep["cost"]["calls_used"] == 8, deep["cost"])
    check("chain8 leaf depth", leaf["depth"] == 8, leaf["depth"])
    check("chain8 recursion", leaf["recursion_available"] is False, leaf["recursion_available"])
    check(
        "chain8 return",
        leaf["return_value"] == {"seal": leaf["inputs"]["seal"], "hops": 1},
        leaf["return_value"],
    )


def continue_case() -> None:
    out = run(
        dbname=HARNESS_DB,
        mode="fake",
        scenario="chain",
        hops=5,
        note=note_for("chain"),
        reply_factory=lambda note, seal, hops, root_id, token: continue_then_tail(
            note, seal, hops, root_id
        ),
    )
    result = out["result"] or {}
    check(
        "continue",
        out["exit_code"] == 0 and result.get("outcome") == "tail_ok" and result.get("relay_ok"),
        {
            "exit": out["exit_code"],
            "line": out["line"],
            "class": result.get("failure_class"),
            "flags": result.get("relay_flags"),
            "parts": result.get("tail_parts"),
        },
    )
    root = _node(result, 1)
    check("continue attempts", root["attempt_count"] == 2, root["attempt_count"])
    check("continue settled", root["settled_on_bind_iteration"] == 1, root)
    check("continue bind", root["bind_iteration"] not in (None, 0), root["bind_iteration"])
    check("continue calls", result["cost"]["calls_used"] == 6, result["cost"])


def recall_case() -> None:
    result = _run("recall", 5)
    check("recall calls", result["cost"]["calls_used"] == 6, result["cost"])
    check("recall ok", result.get("recall_ok") is True, result.get("recall_flags"))
    root = _node(result, 1)
    leaf = _node(result, 5)
    check("recall bind", root["bind_iteration"] == 1, root["bind_iteration"])
    check("recall print", root["sqls"] and "jaz.print" in root["sqls"][0], root["sqls"])
    leaf_sql = "\n".join(leaf["sqls"])
    check("recall fn", "jaz.prior_history" in leaf_sql and result["root_id"] in leaf_sql, leaf_sql[:200])
    token = (leaf["return_value"] or {}).get("token")
    for node in result["nodes"]:
        if node["invoke_id"] == result["root_id"]:
            continue
        check("recall no facts", node["inputs"].get("facts") in (None, ""), node["inputs"])
        check(
            "recall no token",
            token not in "\n".join(node["sqls"]),
            node["invoke_id"],
        )
    warning = result.get("warning") or {}
    check("recall warned", warning.get("root_tail_warned") is True, warning)
    check("recall quiet", warning.get("nonroot_warning_count") == 0, warning)
    sends = {item["iteration"]: item["input_chars"] for item in warning.get("root_sends") or []}
    check("recall iter0", sends.get(0, 9999) < 4500, sends)
    check("recall iter1", 4500 <= sends.get(1, 0) <= 9000, sends)
    check("recall nonroot", warning.get("nonroot_max") is not None and warning["nonroot_max"] < 4500, warning)
    check("recall hooks", result.get("hook_count") == 5, result.get("hook_count"))
    check("recall limit", result.get("protocol_limit") == 9000, result.get("protocol_limit"))


def fanout_case() -> None:
    result = _run("fanout", 1)
    check("fanout calls", result["cost"]["calls_used"] == 3, result["cost"])
    check("fanout nodes", len(result["nodes"]) == 3, len(result["nodes"]))
    check("fanout hops", result.get("hops") == 1, result.get("hops"))
    check("fanout scenario", result.get("scenario") == "fanout", result.get("scenario"))
    root = _node(result, 1)
    leaves = [node for node in result["nodes"] if node["depth"] == 2]
    check("fanout two leaves", len(leaves) == 2, len(leaves))
    check("fanout parent attempts", root["attempt_count"] == 1, root["attempt_count"])
    check("fanout settled", root["settled_on_bind_iteration"] == 1, root)
    check(
        "fanout three statements",
        root["statement_count_on_bind_iteration"] == 3,
        root["statement_count_on_bind_iteration"],
    )
    frag_a, frag_b = fanout_fragments(root["inputs"]["seal"])
    check("fanout fragments differ", frag_a != frag_b, (frag_a, frag_b))
    check(
        "fanout root fragments",
        root["inputs"].get("seal_a") == frag_a and root["inputs"].get("seal_b") == frag_b,
        root["inputs"],
    )
    by_seal = {leaf["inputs"]["seal"]: leaf for leaf in leaves}
    check("fanout leaf seals", set(by_seal) == {frag_a, frag_b}, set(by_seal))
    check(
        "fanout leaf returns",
        by_seal[frag_a]["return_value"] == {"fragment": frag_a}
        and by_seal[frag_b]["return_value"] == {"fragment": frag_b},
        {seal: leaf["return_value"] for seal, leaf in by_seal.items()},
    )
    check(
        "fanout parent return",
        root["return_value"] == {"a": {"fragment": frag_a}, "b": {"fragment": frag_b}},
        root["return_value"],
    )
    check("fanout hooks", result.get("hook_count") == 0, result.get("hook_count"))
    names = {item["name"]: item["ok"] for item in result.get("assertions") or []}
    for name in (
        "fanout_two_children",
        "fanout_parent_one_settled",
        "fanout_var_a_and_b",
        "fanout_deliver_a_before_b",
        "fanout_no_repl_exit",
        "fanout_iteration_three_statements",
    ):
        check(f"fanout {name}", names.get(name) is True, names)


def csi_case() -> None:
    result = _run("csi", 1)
    check("csi calls", result["cost"]["calls_used"] == 6, result["cost"])
    check("csi nodes", len(result["nodes"]) == 4, len(result["nodes"]))
    check("csi hops", result.get("hops") == 1, result.get("hops"))
    check("csi scenario", result.get("scenario") == "csi", result.get("scenario"))
    check("csi ok", result.get("csi_ok") is True, result.get("csi_flags"))
    root = _node(result, 1)
    leaves = [node for node in result["nodes"] if node["depth"] == 2]
    check("csi three leaves", len(leaves) == 3, len(leaves))
    check("csi parent attempts", root["attempt_count"] == 3, root["attempt_count"])
    check("csi settled", root["settled_on_bind_iteration"] == 1, root)
    check(
        "csi batch1 two statements",
        root["statement_count_on_bind_iteration"] == 2,
        root["statement_count_on_bind_iteration"],
    )
    check(
        "csi root tasks",
        root["inputs"].get("task_a") == CSI_TASK_A
        and root["inputs"].get("task_b") == CSI_TASK_B
        and root["inputs"].get("task_c") == CSI_TASK_C,
        root["inputs"],
    )
    check(
        "csi root formulas",
        root["inputs"].get("formula_wrong") == CSI_FORMULA_WRONG
        and root["inputs"].get("formula_right") == CSI_FORMULA_RIGHT,
        root["inputs"],
    )
    by_task = {leaf["inputs"].get("task_id"): leaf for leaf in leaves}
    check("csi leaf tasks", set(by_task) == {CSI_TASK_A, CSI_TASK_B, CSI_TASK_C}, set(by_task))
    check(
        "csi fail a",
        by_task[CSI_TASK_A]["return_value"].get("ok") is False
        and by_task[CSI_TASK_A]["return_value"].get("error") == CSI_ERROR,
        by_task[CSI_TASK_A]["return_value"],
    )
    check(
        "csi fail b",
        by_task[CSI_TASK_B]["return_value"].get("ok") is False
        and by_task[CSI_TASK_B]["return_value"].get("error") == CSI_ERROR,
        by_task[CSI_TASK_B]["return_value"],
    )
    check(
        "csi ok c",
        by_task[CSI_TASK_C]["return_value"].get("ok") is True
        and by_task[CSI_TASK_C]["return_value"].get("answer") == CSI_ANSWER,
        by_task[CSI_TASK_C]["return_value"],
    )
    check(
        "csi parent answer",
        (root["return_value"] or {}).get("answer") == CSI_ANSWER,
        root["return_value"],
    )
    check("csi hooks", result.get("hook_count") == 0, result.get("hook_count"))
    names = {item["name"]: item["ok"] for item in result.get("assertions") or []}
    for name in (
        "csi_three_children",
        "csi_batch1_a_before_b",
        "csi_batch1_before_batch2",
        "csi_bind_home_one_settled",
        "csi_children_one_settled",
        "csi_var_a_b_c",
        "csi_no_repl_exit",
    ):
        check(f"csi {name}", names.get(name) is True, names)


def bounds() -> None:
    server = get_server()
    drop_database(server, BOUND_DB)
    cases = (
        ("hops_invalid", {"hops": 2}),
        ("hops_invalid", {"hops": 9}),
        ("hops_invalid", {"scenario": "fanout", "hops": 2}),
        ("hops_invalid", {"scenario": "fanout", "hops": 3}),
        ("hops_invalid", {"scenario": "fanout", "hops": 8}),
        ("hops_invalid", {"scenario": "csi", "hops": 2}),
        ("hops_invalid", {"scenario": "csi", "hops": 3}),
        ("hops_invalid", {"scenario": "csi", "hops": 8}),
        ("scenario_invalid", {"scenario": "nope"}),
        ("note_invalid", {"note": "has;semicolon"}),
    )
    for label, kwargs in cases:
        out = run(dbname=BOUND_DB, mode="fake", **kwargs)
        check(label, out["exit_code"] == 2 and out["line"] == label and out["result"] is None, out)
        check(label + " no db", not database_exists(server, BOUND_DB), label)
    try:
        validate_hops(2, "chain")
        raise SystemExit("FAIL hops 2 accepted")
    except HopsInvalid:
        pass
    try:
        validate_hops(9, "recall")
        raise SystemExit("FAIL hops 9 accepted")
    except HopsInvalid:
        pass
    try:
        validate_hops(2, "fanout")
        raise SystemExit("FAIL fanout hops 2 accepted")
    except HopsInvalid:
        pass
    try:
        validate_hops(8, "fanout")
        raise SystemExit("FAIL fanout hops 8 accepted")
    except HopsInvalid:
        pass
    check("fanout hops 1", validate_hops(1, "fanout") == 1)
    try:
        validate_hops(2, "csi")
        raise SystemExit("FAIL csi hops 2 accepted")
    except HopsInvalid:
        pass
    try:
        validate_hops(8, "csi")
        raise SystemExit("FAIL csi hops 8 accepted")
    except HopsInvalid:
        pass
    check("csi hops 1", validate_hops(1, "csi") == 1)
    try:
        validate_scenario("fanout")
    except ScenarioInvalid:
        raise SystemExit("FAIL fanout scenario rejected")
    try:
        validate_scenario("csi")
    except ScenarioInvalid:
        raise SystemExit("FAIL csi scenario rejected")
    try:
        validate_scenario("nope")
        raise SystemExit("FAIL scenario accepted")
    except ScenarioInvalid:
        pass
    try:
        validate_note("bad;note", "chain")
        raise SystemExit("FAIL note accepted")
    except NoteInvalid:
        pass
    check("sizer 3400", solve_n(3400) is not None, solve_n(3400))
    check("sizer 4000", solve_n(4000) is None, solve_n(4000))
    check("bound absent", not database_exists(server, BOUND_DB), BOUND_DB)
    check("default absent", not database_exists(server, DEFAULT_DB), DEFAULT_DB)


def keyless() -> None:
    server = get_server()
    drop_database(server, DEFAULT_DB)
    drop_database(server, HARNESS_DB)
    env = os.environ.copy()
    for name in _STRIP:
        env.pop(name, None)
    env["UV_NO_ENV_FILE"] = "1"
    env["DEMO_MODE"] = "real"
    proc = subprocess.run(
        [sys.executable, str(DRIVE)],
        env=env,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    check(
        "keyless",
        proc.returncode == 2 and proc.stdout.strip() == "credentials_absent",
        (proc.returncode, proc.stdout, proc.stderr),
    )
    check("keyless default", not database_exists(server, DEFAULT_DB), DEFAULT_DB)
    check("keyless harness", not database_exists(server, HARNESS_DB), HARNESS_DB)


def main() -> int:
    try:
        bounds()
        keyless()
        chain_cases()
        continue_case()
        recall_case()
        fanout_case()
        csi_case()
        print("bounds hops/scenario/note exit=2")
        print("sizer fixed=3400 solved fixed=4000 rejected")
        print("chain 3/5/8 tail_ok relay_ok")
        print("continue-then-tail calls_used=6")
        print("recall tail_ok relay_ok recall_ok")
        print("fanout hops=1 tail_ok relay_ok")
        print("csi hops=1 tail_ok relay_ok csi_ok")
        print("keyless exit=2")
        return 0
    finally:
        server = get_server()
        drop_database(server, HARNESS_DB)
        drop_database(server, BOUND_DB)


if __name__ == "__main__":
    raise SystemExit(main())
