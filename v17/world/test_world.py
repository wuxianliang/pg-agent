"""G2 gate: v17 world — the reference world adapter over pgstore.

Run: uv run python v17/world/test_world.py  (exit 0 = pass)

Scenarios (plan §5 G2), each driven by an SBCL subprocess while Python
asserts on process output and DB state:

- session scenarios (v17/world/lisp/session-scenarios.lisp): the twice
  example (develop (defun twice ...) -> execute (twice (twice 3)) = 12),
  preview restore (preview incf returns 1, state stays 0), error back to
  checkpoint (error pauses on the restart menu, abort restores, state
  unchanged), stale-generation rejection, and refusal of unrecorded
  definition changes (direct fmakunbound / fbind make the next
  managed-state capture fail loudly).
- managed-state cross-process byte identity: two independent SBCL
  processes build the same world from the same operation sequence and
  store their capture vectors in world_gate_captures; the gate compares
  them byte for byte.
- catalogue export->import identity: publish-world.lisp grows twice/thrice
  and publishes a revision; load-world.lisp in a fresh process imports it
  and calls the functions; catalogue text and call results must match.
- the fiveam world suite (v17/lisp/tests/world-suite.lisp) runs as part of
  this gate.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v17.world.setup_db import DB, main as setup_db

LISP = AGENT_ROOT / "v17" / "lisp"
STAGE_LISP = ROOT / "lisp"
RUN_WORLD_SUITE = LISP / "tests" / "run-world-suite.lisp"
SBCL_TIMEOUT = 300  # first run compiles postmodern/yason/fiveam FASLs


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def socket_dir(server) -> str:
    uri = server.get_uri(DB)
    host = parse_qs(urlparse(uri).query).get("host")
    check("env: pgembed uri carries a unix socket dir", bool(host), uri)
    return host[0]


def lisp_env(sockdir: str) -> dict:
    env = dict(os.environ)
    env["PGSOCKETDIR"] = sockdir
    env["PGDATABASE"] = DB
    return env


def run_sbcl(script: Path, env: dict, args: list[str] | None = None,
             timeout: int = SBCL_TIMEOUT) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["sbcl", "--script", str(script)] + (args or []),
        env=env, capture_output=True, text=True, timeout=timeout)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-4000:])
    return proc


def test_session_scenarios(env: dict) -> None:
    proc = run_sbcl(STAGE_LISP / "session-scenarios.lisp", env)
    check("scenarios: subprocess exited 0", proc.returncode == 0,
          f"exit {proc.returncode}")
    for expected in ("RESULT twice-execute 12",
                     "RESULT stale-generation rejected",
                     "RESULT preview value=1 state=0",
                     "RESULT error-restored state=0",
                     "RESULT unrecorded-fmakunbound refused",
                     "RESULT unrecorded-defun refused"):
        check(f"scenarios: {expected}", expected in proc.stdout)


def test_capture_byte_identity(cur, env: dict) -> None:
    for label in ("proc-a", "proc-b"):
        proc = run_sbcl(STAGE_LISP / "capture-bytes.lisp", env, [label])
        check(f"capture: {label} exited 0", proc.returncode == 0,
              f"exit {proc.returncode}")
    cur.execute("SELECT label, bytes FROM world_gate_captures ORDER BY label")
    rows = dict(cur.fetchall())
    check("capture: both processes stored a vector",
          set(rows) == {"proc-a", "proc-b"}, list(rows))
    a, b = rows.get("proc-a"), rows.get("proc-b")
    check("capture: vectors are non-empty",
          bool(a) and len(a) > 0 and len(a) == len(b),
          (len(a) if a else None, len(b) if b else None))
    check("capture: byte-identical across two independent processes",
          bytes(a) == bytes(b))


def test_publish_load_identity(cur, env: dict) -> None:
    proc = run_sbcl(STAGE_LISP / "publish-world.lisp", env, ["gate-publish"])
    check("publish: exited 0", proc.returncode == 0, f"exit {proc.returncode}")
    world_id = None
    for line in proc.stdout.splitlines():
        if line.startswith("WORLD-ID "):
            world_id = line.split(" ", 1)[1].strip()
    check("publish: world id reported", bool(world_id))
    check("publish: RESULT published", "RESULT published" in proc.stdout)

    cur.execute("SELECT seq, manifest->>'note' FROM lisp_revisions "
                "WHERE world_id = %s::uuid", (world_id,))
    row = cur.fetchone()
    check("publish: revision row seq 1 with manifest note",
          row == (1, "gate-publish"), row)

    proc = run_sbcl(STAGE_LISP / "load-world.lisp", env, [world_id])
    check("load: fresh process imported and called the world",
          proc.returncode == 0 and "RESULT loaded value=12" in proc.stdout,
          f"exit {proc.returncode}")

    cur.execute("SELECT label, payload FROM world_gate_texts")
    texts = dict(cur.fetchall())
    check("load: imported call result is 12",
          texts.get("load-value") == "12", texts.get("load-value"))
    check("load: catalogue identical across export->import",
          texts.get("publish-catalogue") is not None
          and texts.get("publish-catalogue") == texts.get("load-catalogue"))


def test_fiveam_suite(env: dict) -> None:
    proc = run_sbcl(RUN_WORLD_SUITE, env)
    check("fiveam: world suite green (policy gate, capture, session "
          "protocol, preview/error/unsafe restore, unrecorded-change "
          "refusal, export/import, pgstore round-trip)",
          proc.returncode == 0, f"exit {proc.returncode}")


def main() -> int:
    setup_db()
    server = get_server()
    uri = server.get_uri(DB)
    sockdir = socket_dir(server)
    env = lisp_env(sockdir)
    conn = psycopg2.connect(uri)
    cur = conn.cursor()

    # Gate-local comparison tables (not part of the stage SQL surface).
    cur.execute("CREATE TABLE world_gate_captures ("
                "label text PRIMARY KEY, bytes bytea NOT NULL)")
    cur.execute("CREATE TABLE world_gate_texts ("
                "label text PRIMARY KEY, payload text NOT NULL)")
    conn.commit()

    test_session_scenarios(env)
    test_capture_byte_identity(cur, env)
    test_publish_load_identity(cur, env)
    test_fiveam_suite(env)

    conn.commit()
    conn.close()
    print("[G2 world] ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
