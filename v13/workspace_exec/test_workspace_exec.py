"""Phase B workspace_exec gate.

Run: UV_FROZEN=1 uv run python v13/workspace_exec/test_workspace_exec.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_READ_COMMITTED, TRANSACTION_STATUS_IDLE

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v13.load import run_psql
from v13.workspace_exec.driver import Driver
from v13.workspace_exec.adapter import Escape
from v13.workspace_exec.setup_db import DB, main as setup_db
import v13.workspace_exec.setup_db as setup_mod

N = 0
SEEN = set()
HEX = "ab" * 32
REPO = str(AGENT_ROOT)
REQUIRED = {
    "single_tree",
    "open_session_version_2",
    "workspace_not_repo",
    "io_outside_txn",
    "no_advisory_lock_across_io",
    "workspace_request_not_in_tool_calls",
    "write_full_bytes",
    "write_does_not_truncate_file_bytes",
    "write_hash_mismatch_keeps_bytes",
    "edit_hash_mismatch_keeps_bytes",
    "edit_bad_utf8_keeps_bytes",
    "edit_not_unique_keeps_bytes",
    "edit_replaces_once",
    "read_only_edit_writes_nothing",
    "bash_rm_one_file",
    "rm_hash_mismatch_keeps_bytes",
    "cp_source_hash_mismatch_keeps_bytes",
    "mv_source_hash_mismatch_keeps_bytes",
    "mv_target_exists",
    "bash_operand_not_in_paths_rejected",
    "bash_shell_rejected",
    "bash_mkdir_not_recursive",
    "grep_fixed_string_truncates_result",
    "find_no_exec",
    "find_depth_limited_not_truncated",
    "find_empty_depth_limited",
    "find_traverses_unlisted_child",
    "temp_under_declared_parent",
    "temp_namespace_rejected",
    "ls_names_only",
    "symlink_escape",
    "changed_after_admit_does_not_overwrite",
    "special_file_rejected",
    "pre_effect_io_error_fails",
    "fixture_bound_only",
    "temp_cleanup_fail_is_ambiguous",
    "ambiguous_rm_leaves_claimed",
    "replay_succeeded_does_not_reexecute",
    "cancel_during_io_does_not_succeed",
    "retry_bound_2",
    "static_check",
    "real_chain_deny_unchanged",
    "no_real_provider",
    "no_material_spent_insert",
    "tool_result_without_tool_call",
    "temp_component_closed",
    "root_fd_rechecked",
    "idle_after_on_io",
}


def check(label, condition, detail=""):
    global N
    N += 1
    SEEN.add(label)
    mark = "PASS" if condition else "FAIL"
    extra = f": {detail}" if detail and (not condition or len(str(detail)) < 300) else ""
    print(f"[{mark}] {label}{extra}")
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def u():
    return str(uuid.uuid4())


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def as_obj(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def q1(cur, sql, params=None):
    cur.execute(sql, params)
    row = cur.fetchone()
    return None if row is None else row[0]


def fails(fn, needle, label):
    try:
        fn()
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or str(exc).splitlines()[0]
        check(label, needle in msg, msg)
        return msg
    raise AssertionError(f"{label}: expected failure")


def ascii_rel(rel):
    for part in rel.split("/"):
        if any(ord(ch) >= 128 for ch in part):
            raise AssertionError(f"non-ascii path {rel!r}")


def c_sort(items):
    return sorted(items, key=lambda s: s.encode("utf-8"))


def paths_for(*rels):
    acc = []
    for rel in rels:
        ascii_rel(rel)
        acc.extend(parents(rel))
    return c_sort(list(dict.fromkeys(acc)))


def audit_tree(root):
    seen = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        listed = [entry.name.encode("utf-8") for entry in os.scandir(dirpath)]
        for name in list(dirnames) + list(filenames):
            if any(ord(ch) >= 128 for ch in name):
                raise AssertionError(f"non-ascii name {name!r}")
            if name.encode("utf-8") not in listed:
                raise AssertionError(f"roundtrip {name!r}")
            path = os.path.join(dirpath, name)
            st = os.lstat(path)
            key = (st.st_dev, st.st_ino)
            rel = os.path.relpath(path, root)
            prior = seen.get(key)
            if prior is not None and prior != rel:
                raise AssertionError(f"inode collision {prior} {rel}")
            seen[key] = rel
    return True


def parents(rel):
    parts = rel.split("/")
    out = []
    acc = []
    for part in parts:
        acc.append(part)
        out.append("/".join(acc))
    return out


def req(tool, rel, payload, key=None):
    ascii_rel(rel)
    for item in parents(rel):
        ascii_rel(item)
    body = {
        "schema_version": 1,
        "tool": tool,
        "label": "workspace_edit",
        "paths": c_sort(parents(rel) if isinstance(rel, str) else list(rel)),
        "payload": payload,
    }
    if key:
        body["attempt_key"] = key
    return body


def write_req(rel, content, expected, key=None):
    return req("write", rel, {
        "path": rel, "content": content, "expected_sha256": expected,
    }, key)


def file_bytes(root, rel):
    with open(os.path.join(root, rel), "rb") as fh:
        return fh.read()


def file_sha(root, rel):
    return hashlib.sha256(file_bytes(root, rel)).hexdigest()


def roundtrip(root, rel):
    parent = os.path.dirname(os.path.join(root, rel))
    name = os.path.basename(rel)
    listed = [entry.name.encode("utf-8") for entry in os.scandir(parent)]
    return name.encode("utf-8") in listed


class Volume:
    def __init__(self):
        self.tag = f"v13wsx_{os.getpid()}_{secrets.token_hex(3)}"
        tmp = os.environ.get("TMPDIR") or "/tmp"
        self.image = os.path.join(tmp, self.tag + ".sparseimage")
        self.base = os.path.join(tmp, self.tag)
        self.mount = os.path.join(self.base, "ws")
        self.image_created = False
        self.attached = False
        self.cleanup_fail = False

    def up(self):
        if os.path.exists(self.image) or os.path.exists(self.base):
            raise RuntimeError("image exists, not overwriting")
        os.makedirs(self.mount)
        subprocess.run(
            ["hdiutil", "create", "-size", "64m", "-fs", "Case-sensitive APFS",
             "-volname", "v13wsx", "-type", "SPARSE", self.image],
            check=True, stdin=subprocess.DEVNULL,
        )
        self.image_created = True
        try:
            subprocess.run(
                ["hdiutil", "attach", self.image, "-mountpoint", self.mount, "-nobrowse"],
                check=True, stdin=subprocess.DEVNULL,
            )
        except Exception:
            self._delete_image()
            raise
        self.attached = True
        for part in self.mount.split(os.sep):
            if part and any(ord(ch) >= 128 for ch in part):
                raise RuntimeError("non-ascii mount")
        self._probe()

    def _probe(self):
        flags = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY
        foo = os.path.join(self.mount, "Foo")
        bar = os.path.join(self.mount, "foo")
        os.close(os.open(foo, flags, 0o644))
        os.close(os.open(bar, flags, 0o644))
        names = [entry.name.encode("utf-8") for entry in os.scandir(self.mount)]
        st_foo = os.lstat(foo)
        st_bar = os.lstat(bar)
        ok = (
            b"Foo" in names and b"foo" in names
            and (st_foo.st_dev, st_foo.st_ino) != (st_bar.st_dev, st_bar.st_ino)
        )
        os.unlink(foo)
        os.unlink(bar)
        leftover = [e.name.encode("utf-8") for e in os.scandir(self.mount)]
        if not ok or b"Foo" in leftover or b"foo" in leftover:
            raise RuntimeError("name probe failed")
        a = os.path.join(self.mount, "a")
        ab = os.path.join(self.mount, "ab")
        os.close(os.open(a, flags, 0o644))
        os.close(os.open(ab, flags, 0o644))
        sa = os.lstat(a)
        sb = os.lstat(ab)
        if (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino):
            raise RuntimeError("inode collision")
        os.unlink(a)
        os.unlink(ab)

    def down(self):
        if self.attached:
            try:
                subprocess.run(
                    ["hdiutil", "detach", self.mount],
                    check=True, stdin=subprocess.DEVNULL,
                )
                self.attached = False
            except Exception as exc:
                print("[cleanup-fail]", exc)
                self.cleanup_fail = True
        self._delete_image()
        for path in (self.mount, self.base):
            try:
                if os.path.isdir(path):
                    os.rmdir(path)
            except Exception as exc:
                print("[cleanup-fail]", exc)
                self.cleanup_fail = True

    def _delete_image(self):
        if not self.image_created:
            return
        try:
            os.remove(self.image)
            self.image_created = False
        except FileNotFoundError:
            self.image_created = False
        except Exception as exc:
            print("[cleanup-fail]", exc)
            self.cleanup_fail = True


def connect(server):
    conn = psycopg2.connect(server.get_uri(DB))
    conn.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)
    return conn


def open_v2(cur):
    return str(q1(
        cur,
        "SELECT v13_open_session(%s::jsonb)",
        (json.dumps({"route_policy_name": "default", "version": 2}),),
    ))


def plant(cur, sid):
    q1(
        cur,
        "SELECT v13_append_event(%s, %s, 'user/message', %s::jsonb)",
        (sid, u(), json.dumps({"text": "workspace exec"})),
    )
    tid = u()
    text = "pending advancement"
    body = {
        "schema_version": 1,
        "call_kind": "plan_commit",
        "based_on_seq": q1(cur, "SELECT max(seq) FROM events WHERE session_id=%s", (sid,)),
        "supersedes": None,
        "todos": [{
            "todo_id": tid,
            "text": text,
            "text_hash": sha(text),
            "task_class": "advancement_task",
            "status": "pending",
            "due": None,
            "verb": "add_new",
        }],
    }
    cur.execute(
        "SELECT v13_plan_writer(%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s::timestamptz)",
        (None, sid, u(), "plan_commit", json.dumps(body), None),
    )
    cur.fetchone()


def n_events(cur, sid, kind):
    return q1(
        cur,
        "SELECT count(*) FROM events WHERE session_id=%s AND type=%s",
        (sid, kind),
    )


def n_effects(cur):
    return q1(cur, "SELECT count(*) FROM effects")


def effect_status(cur, eid):
    return q1(cur, "SELECT status FROM effects WHERE effect_id=%s", (eid,))


def static_names(src):
    kept = []
    i = 0
    while i < len(src):
        if src[i] == "#":
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        kept.append(src[i])
        i += 1
    return set(re.findall(r"v13_[A-Za-z0-9_]+(?=\()", "".join(kept)))


def test_static():
    driver_src = (ROOT / "driver.py").read_text()
    adapter_src = (ROOT / "adapter.py").read_text()
    test_src = (ROOT / "test_workspace_exec.py").read_text()
    allow = {"v13_workspace_policy", "v13_tool_effect_open", "v13_tool_result_accept"}
    names = static_names(driver_src)
    banned_sql = tuple(
        "INSERT INTO " + name for name in ("effects", "events", "sessions", "artifacts")
    )
    check(
        "static_check",
        names <= allow and names >= allow
        and not any(item in test_src for item in banned_sql)
        and not list(ROOT.glob("*.sql"))
        and "realpath" not in driver_src and "realpath" not in adapter_src
        and "subprocess" not in adapter_src and "shell=True" not in adapter_src,
        names,
    )
    chain = (AGENT_ROOT / "v13/real_chain/test_real_chain.py").read_text()
    diff = subprocess.check_output(
        ["git", "diff", "HEAD", "--", "v13/real_chain"], cwd=AGENT_ROOT)
    check(
        "real_chain_deny_unchanged",
        "deny_edit_write_bash" in chain and diff == b"",
        len(diff),
    )
    blob = driver_src + adapter_src
    check(
        "no_real_provider",
        "urllib" not in blob and "httpx" not in blob and "openai" not in blob
        and not os.environ.get("V13_REAL_PROVIDER_AUTHORIZATION"),
    )
    parent_src = adapter_src.split("def _parent", 1)[1].split("def _map_open", 1)[0]
    check(
        "root_fd_rechecked",
        "fstat" in parent_src and "self._dev" in parent_src and "self._ino" in parent_src,
    )


def run_cases(cur, driver, mount):
    sid = driver.session
    check(
        "single_tree",
        q1(cur, "SELECT count(*) FROM sessions WHERE parent_session_id IS NULL") == 1,
    )
    ver = q1(cur, "SELECT route_policy_version FROM sessions WHERE session_id=%s", (sid,))
    driver_src = (ROOT / "driver.py").read_text()
    check(
        "open_session_version_2",
        ver == 2 and "v13_open_session(" not in static_names(driver_src)
        and "v13_plan_commit_entry(" not in static_names(driver_src),
        ver,
    )
    blocked = True
    for key in ("a/b", "x\0y", ".", "..", "", "foo\\bar"):
        try:
            driver.adapter._temp_name(key)
            blocked = False
            break
        except Escape:
            pass
    good = driver.adapter._temp_name("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    check(
        "temp_component_closed",
        blocked and good == ".v13tmp-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        good,
    )
    materials = n_events(cur, sid, "turn/material_spent")
    calls = n_events(cur, sid, "tool/call")

    fails(
        lambda: driver.execute("workspace_edit", write_req("nope", "z", None),
                               workspace_root="/", allowed_roots=[mount]),
        "v13: workspace open: canonical",
        "workspace_not_repo",
    )
    fails(
        lambda: driver.execute(
            "workspace_edit", write_req("nope", "z", None),
            workspace_root=REPO, allowed_roots=[mount]),
        "v13: workspace open: canonical",
        "workspace_not_repo",
    )
    check(
        "workspace_root_is_mount",
        driver.root == mount and mount != "/" and not mount.startswith("/Volumes")
        and REPO not in mount and mount.startswith(os.environ.get("TMPDIR") or "/tmp")
        and audit_tree(mount),
    )

    idle = {}

    def on_io(conn):
        idle["status"] = conn.info.transaction_status
        other = psycopg2.connect(conn.dsn if hasattr(conn, "dsn") else get_server().get_uri(DB))
        try:
            other.autocommit = True
            ocur = other.cursor()
            ocur.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND pid=%s",
                (conn.info.backend_pid,),
            )
            idle["adv"] = ocur.fetchone()[0]
        finally:
            other.close()

    out = driver.execute(
        "workspace_edit", write_req("hello.txt", "hello", None), hooks={"on_io": on_io})
    check(
        "write_full_bytes",
        out["status"] == "succeeded" and file_bytes(mount, "hello.txt") == b"hello"
        and roundtrip(mount, "hello.txt"),
        out["status"],
    )
    check(
        "io_outside_txn",
        idle.get("status") == TRANSACTION_STATUS_IDLE,
        idle.get("status"),
    )
    check("no_advisory_lock_across_io", idle.get("adv") == 0, idle.get("adv"))
    child_idle = str(q1(cur, "SELECT v13_fork(%s::uuid, 0, 'fresh_fork')", (sid,)))
    cur.connection.commit()
    d_idle = Driver(driver.conn, child_idle, mount, [mount])
    d_idle.policy = driver.policy
    d_idle.adapter = driver.adapter

    def begin_txn(conn):
        conn.cursor().execute("SELECT 1")

    raised = False
    try:
        d_idle.execute(
            "workspace_edit", write_req("idlehook.txt", "x", None),
            hooks={"on_io": begin_txn},
        )
    except RuntimeError as exc:
        raised = "io inside transaction" in str(exc)
        driver.conn.rollback()
    check(
        "idle_after_on_io",
        raised is True and d_idle.adapter_calls == 0,
        (raised, d_idle.adapter_calls),
    )
    check(
        "workspace_request_not_in_tool_calls",
        n_events(cur, sid, "tool/call") == calls,
    )
    long = "x" * 60000
    out = driver.execute("workspace_edit", write_req("long.txt", long, None))
    stored = as_obj(q1(cur, "SELECT result FROM effects WHERE effect_id=%s", (out["effect_id"],)))
    check(
        "write_does_not_truncate_file_bytes",
        file_bytes(mount, "long.txt") == long.encode("utf-8")
        and len(stored["text"]) < 51200 and stored["text"] != long,
        len(file_bytes(mount, "long.txt")),
    )
    os.mkdir(os.path.join(mount, "sub"))
    existing = os.path.join(mount, "keep.txt")
    open(existing, "wb").write(b"KEEP")
    digest = file_sha(mount, "keep.txt")
    out = driver.execute(
        "workspace_edit", write_req("keep.txt", "NEW", "cd" * 32))
    check(
        "write_hash_mismatch_keeps_bytes",
        out["status"] == "failed" and out["result"]["error_token"] == "hash_mismatch"
        and file_bytes(mount, "keep.txt") == b"KEEP",
        out["result"]["error_token"],
    )
    out = driver.execute(
        "workspace_edit",
        req("edit", "keep.txt", {
            "path": "keep.txt", "old": "KEEP", "new": "ZZ", "expected_sha256": "cd" * 32,
        }),
    )
    check(
        "edit_hash_mismatch_keeps_bytes",
        out["status"] == "failed" and out["result"]["error_token"] == "hash_mismatch"
        and file_bytes(mount, "keep.txt") == b"KEEP",
    )
    raw = os.path.join(mount, "bad.bin")
    open(raw, "wb").write(b"\xff\xfe")
    bad_hash = hashlib.sha256(b"\xff\xfe").hexdigest()
    out = driver.execute(
        "workspace_edit",
        req("edit", "bad.bin", {
            "path": "bad.bin", "old": "x", "new": "y", "expected_sha256": bad_hash,
        }),
    )
    check(
        "edit_bad_utf8_keeps_bytes",
        out["status"] == "failed" and out["result"]["error_token"] == "bad_utf8"
        and file_bytes(mount, "bad.bin") == b"\xff\xfe",
        out["result"]["error_token"],
    )
    open(os.path.join(mount, "twice.txt"), "wb").write(b"OLD OLD")
    twice = file_sha(mount, "twice.txt")
    out = driver.execute(
        "workspace_edit",
        req("edit", "twice.txt", {
            "path": "twice.txt", "old": "OLD", "new": "NEW", "expected_sha256": twice,
        }),
    )
    check(
        "edit_not_unique_keeps_bytes",
        out["status"] == "failed" and out["result"]["error_token"] == "edit_not_unique"
        and file_bytes(mount, "twice.txt") == b"OLD OLD",
    )
    out = driver.execute(
        "workspace_edit",
        req("edit", "keep.txt", {
            "path": "keep.txt", "old": "KEEP", "new": "KEPT", "expected_sha256": digest,
        }),
    )
    check(
        "edit_replaces_once",
        out["status"] == "succeeded" and file_bytes(mount, "keep.txt") == b"KEPT",
        file_bytes(mount, "keep.txt"),
    )
    before = file_bytes(mount, "keep.txt")
    n0 = n_effects(cur)
    fails(
        lambda: driver.execute("read_only", req("edit", "keep.txt", {
            "path": "keep.txt", "old": "KEPT", "new": "NO", "expected_sha256": digest,
        })),
        "v13: workspace open: subset",
        "read_only_edit_writes_nothing",
    )
    check("read_only bytes", file_bytes(mount, "keep.txt") == before and n_effects(cur) == n0)

    victim = os.path.join(mount, "gone.txt")
    open(victim, "wb").write(b"gone")
    gone = file_sha(mount, "gone.txt")
    out = driver.execute(
        "workspace_edit",
        req("bash", "gone.txt", {"argv": ["rm", "gone.txt"], "expected_sha256": gone}),
    )
    check(
        "bash_rm_one_file",
        out["status"] == "succeeded" and not os.path.exists(victim)
        and out["result"]["text"] == "" and out["result"]["byte_length"] == 0,
    )
    open(victim, "wb").write(b"stay")
    out = driver.execute(
        "workspace_edit",
        req("bash", "gone.txt", {"argv": ["rm", "gone.txt"], "expected_sha256": HEX}),
    )
    check(
        "rm_hash_mismatch_keeps_bytes",
        out["status"] == "failed" and out["result"]["error_token"] == "hash_mismatch"
        and file_bytes(mount, "gone.txt") == b"stay",
    )
    open(os.path.join(mount, "src.txt"), "wb").write(b"SRC")
    src_hash = file_sha(mount, "src.txt")
    out = driver.execute(
        "workspace_edit",
        {
            "schema_version": 1, "tool": "bash", "label": "workspace_edit",
            "paths": paths_for("src.txt", "dst.txt"),
            "payload": {"argv": ["cp", "src.txt", "dst.txt"], "expected_sha256": HEX},
        },
    )
    check(
        "cp_source_hash_mismatch_keeps_bytes",
        out["status"] == "failed" and out["result"]["error_token"] == "hash_mismatch"
        and file_bytes(mount, "src.txt") == b"SRC" and not os.path.exists(os.path.join(mount, "dst.txt")),
    )
    out = driver.execute(
        "workspace_edit",
        {
            "schema_version": 1, "tool": "bash", "label": "workspace_edit",
            "paths": paths_for("src.txt", "dst.txt"),
            "payload": {"argv": ["mv", "src.txt", "dst.txt"], "expected_sha256": HEX},
        },
    )
    check(
        "mv_source_hash_mismatch_keeps_bytes",
        out["status"] == "failed" and file_bytes(mount, "src.txt") == b"SRC"
        and not os.path.exists(os.path.join(mount, "dst.txt")),
    )
    open(os.path.join(mount, "dst.txt"), "wb").write(b"DST")
    out = driver.execute(
        "workspace_edit",
        {
            "schema_version": 1, "tool": "bash", "label": "workspace_edit",
            "paths": paths_for("src.txt", "dst.txt"),
            "payload": {"argv": ["mv", "src.txt", "dst.txt"], "expected_sha256": src_hash},
        },
    )
    check(
        "mv_target_exists",
        out["status"] == "failed" and out["result"]["error_token"] == "exists"
        and file_bytes(mount, "src.txt") == b"SRC" and file_bytes(mount, "dst.txt") == b"DST",
        out["result"]["error_token"],
    )
    n0 = n_effects(cur)
    fails(
        lambda: driver.execute("workspace_edit", {
            "schema_version": 1, "tool": "bash", "label": "workspace_edit",
            "paths": ["other.txt"],
            "payload": {"argv": ["rm", "secret.txt"], "expected_sha256": HEX},
        }),
        "v13: workspace open: payload",
        "bash_operand_not_in_paths_rejected",
    )
    fails(
        lambda: driver.execute("workspace_edit", {
            "schema_version": 1, "tool": "bash", "label": "workspace_edit",
            "paths": ["gone.txt"],
            "payload": {"argv": ["rm", "-rf", "gone.txt"], "expected_sha256": HEX},
        }),
        "v13: workspace open: payload",
        "bash_operand_not_in_paths_rejected",
    )
    check("operand zero new", n_effects(cur) == n0)
    fails(
        lambda: driver.execute("workspace_edit", {
            "schema_version": 1, "tool": "bash", "label": "workspace_edit",
            "paths": ["gone.txt"],
            "payload": {"argv": ["bash", "gone.txt"]},
        }),
        "v13: workspace open: verb_closed",
        "bash_shell_rejected",
    )
    fails(
        lambda: driver.execute("workspace_edit", {
            "schema_version": 1, "tool": "bash", "label": "workspace_edit",
            "paths": ["gone.txt"],
            "payload": {"argv": ["mkdir", "gone.txt"], "shell": True},
        }),
        "v13: workspace open: payload",
        "bash_shell_rejected",
    )
    out = driver.execute("workspace_edit", {
        "schema_version": 1, "tool": "bash", "label": "workspace_edit",
        "paths": paths_for("missing", "missing/child"),
        "payload": {"argv": ["mkdir", "missing/child"]},
    })
    check(
        "bash_mkdir_not_recursive",
        out["status"] == "failed" and out["result"]["error_token"] == "missing"
        and not os.path.exists(os.path.join(mount, "missing")),
        out["result"]["error_token"],
    )

    blob = ("hit\n" * 13000)
    open(os.path.join(mount, "grep.txt"), "w").write(blob + "a.b\naxb\n")
    before = file_bytes(mount, "grep.txt")
    out = driver.execute("read_only", {
        "schema_version": 1, "tool": "grep", "label": "read_only",
        "paths": ["grep.txt"],
        "payload": {"path": "grep.txt", "pattern": "hit"},
    })
    stored = as_obj(q1(cur, "SELECT result FROM effects WHERE effect_id=%s", (out["effect_id"],)))
    check(
        "grep_fixed_string_truncates_result",
        out["status"] == "succeeded" and stored["truncated"] is True
        and stored["byte_length"] > 51200
        and len(stored["text"].encode("utf-8")) <= 51200
        and file_bytes(mount, "grep.txt") == before
        and "axb" not in stored["text"],
        stored["byte_length"],
    )

    os.mkdir(os.path.join(mount, "tree"))
    cursor_dir = os.path.join(mount, "tree")
    for i in range(6):
        cursor_dir = os.path.join(cursor_dir, f"d{i}")
        os.mkdir(cursor_dir)
    open(os.path.join(mount, "tree", "hit.txt"), "w").write("hit")
    open(os.path.join(mount, "tree", "touch pwned"), "w").write("nope")
    out = driver.execute("read_only", {
        "schema_version": 1, "tool": "find", "label": "read_only",
        "paths": ["tree"],
        "payload": {"path": "tree"},
    })
    stored = out["result"]
    check(
        "find_no_exec",
        out["status"] == "succeeded" and "touch pwned" in stored["text"]
        and not os.path.exists(os.path.join(mount, "pwned")),
    )
    check(
        "find_depth_limited_not_truncated",
        stored["depth_limited"] is True and stored["truncated"] is False
        and stored["byte_length"] <= 51200 and "hit.txt" in stored["text"],
        (stored["depth_limited"], stored["truncated"], stored["byte_length"]),
    )
    out = driver.execute("read_only", {
        "schema_version": 1, "tool": "find", "label": "read_only",
        "paths": ["tree"],
        "payload": {"path": "tree", "name_fixed": "no-such-name"},
    })
    stored = out["result"]
    check(
        "find_empty_depth_limited",
        stored["text"] == "" and stored["byte_length"] == 0
        and stored["truncated"] is False and stored["depth_limited"] is True,
        stored,
    )
    os.mkdir(os.path.join(mount, "box"))
    open(os.path.join(mount, "box", "kid.txt"), "w").write("kid")
    os.symlink("kid.txt", os.path.join(mount, "box", "link"))
    out = driver.execute("read_only", {
        "schema_version": 1, "tool": "find", "label": "read_only",
        "paths": ["box"],
        "payload": {"path": "box"},
    })
    check(
        "find_traverses_unlisted_child",
        "box/kid.txt" in out["result"]["text"] and "SECRET" not in out["result"]["text"],
        out["result"]["text"],
    )
    open(os.path.join(mount, "box", "kid.txt"), "w").write("SECRETCONTENT")
    out = driver.execute("read_only", {
        "schema_version": 1, "tool": "ls", "label": "read_only",
        "paths": ["box"],
        "payload": {"path": "box"},
    })
    check(
        "ls_names_only",
        "kid.txt" in out["result"]["text"] and "SECRETCONTENT" not in out["result"]["text"]
        and "link" in out["result"]["text"],
        out["result"]["text"],
    )

    seen = {}

    def before_replace(temp, key, parent):
        seen["temp"] = temp
        seen["key"] = key
        listed = [entry.encode("utf-8") for entry in os.listdir(parent)]
        seen["listed"] = temp.encode("utf-8") in listed
        seen["parent_ok"] = True

    out = driver.execute(
        "workspace_edit", write_req("sub/file.txt", "X", None),
        hooks={"before_replace": before_replace},
    )
    check(
        "temp_under_declared_parent",
        out["status"] == "succeeded" and seen.get("temp", "").startswith(".v13tmp-")
        and seen.get("listed") and file_bytes(mount, "sub/file.txt") == b"X"
        and not os.path.exists(os.path.join(mount, seen.get("temp", "missing"))),
        seen.get("temp"),
    )

    started = threading.Event()
    resume = threading.Event()

    def pause(temp, key, parent):
        started.set()
        resume.wait(10)

    box = {}

    def runner():
        try:
            box["out"] = driver.execute(
                "workspace_edit", write_req("note.txt", "X", None),
                hooks={"before_replace": pause},
            )
        except Exception as exc:
            box["err"] = exc

    other = psycopg2.connect(get_server().get_uri(DB))
    other.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)
    try:
        thread = threading.Thread(target=runner)
        thread.start()
        started.wait(10)
        temps = [name for name in os.listdir(mount) if name.startswith(".v13tmp-")]
        ocur = other.cursor()
        n_mid = q1(ocur, "SELECT count(*) FROM effects")
        msg = ""
        if temps:
            try:
                ocur.execute(
                    "SELECT v13_tool_effect_open(%s::uuid, %s::uuid, %s, %s, %s::text[], %s::jsonb)",
                    (None, sid, "workspace_edit", mount, [mount], json.dumps(
                        req("ls", temps[0], {"path": temps[0]}, key=u()))),
                )
            except psycopg2.Error as exc:
                msg = exc.diag.message_primary or ""
                other.rollback()
        resume.set()
        thread.join(10)
    finally:
        other.close()
    check(
        "temp_namespace_rejected",
        bool(temps) and (not thread.is_alive()) and "temp_namespace" in msg
        and n_effects(cur) == n_mid and file_bytes(mount, "note.txt") == b"X"
        and box.get("out", {}).get("status") == "succeeded",
        (msg, temps, n0, n_mid, n_effects(cur)),
    )

    open(os.path.join(mount, "flip.txt"), "wb").write(b"AAAA")
    flip = file_sha(mount, "flip.txt")

    def mutate():
        open(os.path.join(mount, "flip.txt"), "wb").write(b"BBBB")

    out = driver.execute(
        "workspace_edit", write_req("flip.txt", "CCCC", flip),
        hooks={"before_recheck": mutate},
    )
    check(
        "changed_after_admit_does_not_overwrite",
        out["status"] == "failed" and out["result"]["error_token"] in ("hash_mismatch", "exists")
        and file_bytes(mount, "flip.txt") == b"BBBB",
        out["result"]["error_token"] if out.get("result") else out,
    )

    os.mkfifo(os.path.join(mount, "pipe1"))
    sock_path = os.path.join(mount, "sock1")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(sock_path)
    out_fifo = driver.execute("read_only", {
        "schema_version": 1, "tool": "grep", "label": "read_only",
        "paths": ["pipe1"], "payload": {"path": "pipe1", "pattern": "x"},
    })
    out_sock = driver.execute("workspace_edit", write_req("sock1", "no", None))
    open(os.path.join(mount, "plain.txt"), "wb").write(b"plain")
    out_dir = driver.execute("read_only", {
        "schema_version": 1, "tool": "ls", "label": "read_only",
        "paths": ["plain.txt"], "payload": {"path": "plain.txt"},
    })
    dev_ok = True
    try:
        os.mknod(os.path.join(mount, "dev1"), stat.S_IFCHR | 0o600, os.makedev(1, 3))
        out_dev = driver.execute("workspace_edit", write_req("dev1", "no", None))
        dev_ok = out_dev["result"]["error_token"] == "not_a_file"
    except OSError:
        dev_ok = True
    sock.close()
    check(
        "special_file_rejected",
        out_fifo["result"]["error_token"] == "not_a_file"
        and out_sock["result"]["error_token"] == "not_a_file"
        and out_dir["result"]["error_token"] == "not_a_dir"
        and dev_ok,
        (out_fifo["result"]["error_token"], out_sock["result"]["error_token"],
         out_dir["result"]["error_token"], dev_ok),
    )

    open(os.path.join(mount, "locked.txt"), "wb").write(b"LOCK")
    os.chmod(os.path.join(mount, "locked.txt"), 0)
    try:
        out = driver.execute("read_only", {
            "schema_version": 1, "tool": "grep", "label": "read_only",
            "paths": ["locked.txt"],
            "payload": {"path": "locked.txt", "pattern": "L"},
        })
    finally:
        os.chmod(os.path.join(mount, "locked.txt"), 0o644)
    check(
        "pre_effect_io_error_fails",
        out["status"] == "failed" and out["result"]["error_token"] == "io_error"
        and file_bytes(mount, "locked.txt") == b"LOCK",
        out["result"]["error_token"],
    )
    keys = set(as_obj(q1(cur, "SELECT v13_workspace_policy()")).keys())
    check(
        "fixture_bound_only",
        keys == {
            "argv_len_cap", "bash_verbs", "find_depth_cap", "labels",
            "paths_cap", "result_text_cap_bytes", "schema_version", "tool_open_attempts",
        } and len(file_bytes(mount, "long.txt")) == 60000 and audit_tree(mount),
        sorted(keys),
    )

    sentinel = os.path.join(mount, "sentinel.txt")
    open(sentinel, "wb").write(b"KEEP")
    os.symlink("sentinel.txt", os.path.join(mount, "link.txt"))
    out = driver.execute("workspace_edit", write_req("link.txt", "PWN", None))
    check(
        "symlink_escape",
        out["status"] != "succeeded" and file_bytes(mount, "sentinel.txt") == b"KEEP"
        and stat.S_ISLNK(os.lstat(os.path.join(mount, "link.txt")).st_mode),
        out.get("result"),
    )

    child = str(q1(cur, "SELECT v13_fork(%s::uuid, 0, 'fresh_fork')", (sid,)))
    cur.connection.commit()
    child_driver = Driver(driver.conn, child, mount, [mount])
    child_driver.policy = driver.policy
    child_driver.adapter = driver.adapter
    out = child_driver.execute(
        "workspace_edit", write_req("ambig.txt", "Z", None),
        hooks={"fail_install": True, "fail_temp_unlink": True},
    )
    check(
        "temp_cleanup_fail_is_ambiguous",
        out.get("ambiguous") is True and not os.path.exists(os.path.join(mount, "ambig.txt"))
        and effect_status(cur, out["effect_id"]) == "claimed"
        and child_driver.accept_calls == 0,
        out.get("ambiguous"),
    )

    open(os.path.join(mount, "rmamb.txt"), "wb").write(b"RM")
    rm_hash = file_sha(mount, "rmamb.txt")
    child2 = str(q1(cur, "SELECT v13_fork(%s::uuid, 0, 'fresh_fork')", (sid,)))
    cur.connection.commit()
    d2 = Driver(driver.conn, child2, mount, [mount])
    d2.policy = driver.policy
    d2.adapter = driver.adapter
    out = d2.execute(
        "workspace_edit",
        req("bash", "rmamb.txt", {"argv": ["rm", "rmamb.txt"], "expected_sha256": rm_hash}),
        hooks={"unlink_raises": True},
    )
    check(
        "ambiguous_rm_leaves_claimed",
        out.get("ambiguous") is True and effect_status(cur, out["effect_id"]) == "claimed"
        and d2.accept_calls == 0 and os.path.exists(os.path.join(mount, "rmamb.txt")),
    )

    key = u()
    first = driver.execute("workspace_edit", write_req("replay.txt", "R", None, key=key))
    calls_before = driver.adapter_calls
    accept_before = driver.accept_calls
    second = driver.execute("workspace_edit", write_req("replay.txt", "R", None, key=key))
    check(
        "replay_succeeded_does_not_reexecute",
        second["replayed"] is True and second["status"] == "succeeded"
        and second["result"] == first["result"]
        and driver.adapter_calls == calls_before
        and driver.accept_calls == accept_before,
        second["replayed"],
    )

    used = driver.execute(
        "workspace_edit", write_req("retry.txt", "NO", HEX), attempts=5)
    check("retry_bound_2", used["attempts_used"] == 2, used["attempts_used"])

    child3 = str(q1(cur, "SELECT v13_fork(%s::uuid, 0, 'fresh_fork')", (sid,)))
    cur.connection.commit()

    def cancel(conn, opened):
        c2 = conn.cursor()
        c2.execute("SELECT v13_cancel(%s)", (child3,))
        c2.fetchone()
        conn.commit()

    d3 = Driver(driver.conn, child3, mount, [mount])
    d3.policy = driver.policy
    d3.adapter = driver.adapter
    msg = ""
    try:
        d3.execute(
            "workspace_edit", write_req("cancel.txt", "C", None),
            hooks={"before_accept": cancel},
        )
    except psycopg2.Error as exc:
        msg = exc.diag.message_primary or ""
    eid = q1(
        cur,
        "SELECT effect_id FROM effects WHERE session_id=%s AND tool_name='write' "
        "ORDER BY created_at DESC LIMIT 1",
        (child3,),
    )
    check(
        "cancel_during_io_does_not_succeed",
        ("cancel" in msg or "lock_mismatch" in msg)
        and effect_status(cur, eid) != "succeeded",
        (msg, effect_status(cur, eid)),
    )
    check(
        "no_material_spent_insert",
        n_events(cur, sid, "turn/material_spent") == materials,
    )
    check(
        "tool_result_without_tool_call",
        n_events(cur, sid, "tool/result") > 0 and n_events(cur, sid, "tool/call") == 0,
    )


def main() -> int:
    print("[db]", DB)
    test_static()
    volume = Volume()
    server = None
    try:
        server = get_server()
        if setup_db() != 0:
            return 1
        try:
            volume.up()
        except Exception as exc:
            print("[probe-fail]", exc)
            volume.down()
            return 1
        conn = connect(server)
        try:
            cur = conn.cursor()
            sid = open_v2(cur)
            plant(cur, sid)
            conn.commit()
            driver = Driver(conn, sid, volume.mount, [volume.mount])
            driver.load_policy()
            run_cases(cur, driver, volume.mount)
        finally:
            conn.close()
    finally:
        volume.down()
        if setup_mod.CREATED and server is not None:
            run_psql(server, "postgres", 'DROP DATABASE "%s" WITH (FORCE);' % DB)
            setup_mod.CREATED = False
            print("[dropped]", DB)
    if volume.cleanup_fail:
        print("[cleanup-fail] not exit_0")
        return 1
    missing = sorted(REQUIRED - SEEN)
    if missing:
        print("[FAIL] missing assertions", missing)
        return 1
    print("[ok] %s checks" % N)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("[FAIL]", exc)
        raise SystemExit(1)
