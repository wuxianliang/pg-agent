"""G5 W1-W4: discovery, crash windows K1-K10 and the recovery command.

K1 runs first on the pristine fixture so its evidence is literally
requests/effects 0 -> 1; the remaining windows use their own scopes.  Every
crash recovery is performed by a fresh recover_worker.py OS process: the
parent only seeds, spawns, SIGKILLs and asserts.  W3 adds K6/K7/K9, the
cancel-late/no_replay model variants, the manual debt case and the §4.5.3
normal-vs-recovery control comparison.  W4 adds K4 (fixture-only SQL error
injection on the request insert, rollback and a replay of the same outcome) and
K5 (command_recover committed before the response is lost; two fresh replays
are byte-equal and zero-write).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parent
S1 = ROOT.parent / "s1"
S2 = ROOT.parent / "s2"
S5 = ROOT.parent / "s5"
for _path in (S1, S2, S5):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setup_db import _assert_closed_catalog, server_helper_scope, setup_db  # noqa: E402
from g5_support import (  # noqa: E402
    fingerprint,
    g5_snapshot,
    insert_row,
    jsonl_path,
    new_scope,
    one,
    read_jsonl,
    seed_claim,
    seed_run_with_model,
    snapshot_diff,
    wait_ready,
)
from test_g4 import (  # noqa: E402
    admit_install,
    effect_of,
    fiber_of,
    install_row,
    scope_closable,
)
from test_g3a import advance, claim  # noqa: E402

CRASH_WORKER = ROOT / "crash_worker.py"
RECOVER_WORKER = ROOT / "recover_worker.py"
WINDOWS = ("K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10")
W2_WINDOWS = ("K2", "K3", "K8", "K10")
KIND = "command_scope_control"
FORBIDDEN_IMPORTS = (
    "socket", "http", "urllib", "requests", "ftplib", "smtplib",
    "telnetlib", "ssl", "aiohttp", "httpx",
)
NOW = datetime.now(timezone.utc)
OLD = NOW - timedelta(hours=2)
FUTURE = NOW + timedelta(hours=2)


def _assert_no_network_imports() -> None:
    for path in sorted(ROOT.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for name in FORBIDDEN_IMPORTS:
            match = re.search(
                rf"(?m)^\s*(?:from|import)\s+{re.escape(name)}\b", source
            )
            assert match is None, (path.name, name)
        assert ("time." + "sleep") not in source, path.name


def discover(conn, scope_id, limit) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT effect_id::text, kind, replay_policy, attempt_no, fence,
                      claim_owner, lease_until
                 FROM v24.recoverable_effects(%s::uuid, %s::integer)""",
            (scope_id, limit),
        )
        columns = [column[0] for column in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def _ids(rows) -> list[str]:
    return [row["effect_id"] for row in rows]


def k1_payload() -> dict:
    return {"action": "create_root", "realm_routes": {}, "default_realm": None}


def _kill_and_reap(proc) -> tuple[bytes, bytes]:
    if proc.poll() is None:
        os.kill(proc.pid, signal.SIGKILL)
    try:
        out, err = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate(timeout=30)
    return out or b"", err or b""


def _stable_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sql_tree_digest() -> str:
    """Hash every product SQL file so the gate can prove it wrote none."""
    root = ROOT.parent / "sql"
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _wait_child_exit(child, ready_r, go_w, window):
    """K4 has no kill: read READY, then require a clean natural exit."""
    try:
        try:
            ready = wait_ready(ready_r, timeout=30)
        except BaseException as exc:
            _, child_stderr = _kill_and_reap(child)
            raise AssertionError(
                "crash child did not reach READY: "
                f"{exc}; stderr={child_stderr.decode(errors='replace')}"
            ) from None
        assert ready["window"] == window, ready
        out, err = child.communicate(timeout=30)
        assert child.returncode == 0, (
            child.returncode, err.decode(errors="replace"),
            out.decode(errors="replace"))
        return ready
    finally:
        os.close(ready_r)
        os.close(go_w)
        if child.returncode is None:
            _kill_and_reap(child)


K4_TRIGGER = "k4_inject"


def _create_k4_injection(owner) -> str:
    with owner.cursor() as cur:
        cur.execute(
            """CREATE FUNCTION v24_fake.raise_k4() RETURNS trigger
               LANGUAGE plpgsql AS $$
               BEGIN
                 RAISE EXCEPTION 'k4 injected request fault'
                   USING ERRCODE='P0001';
               END
               $$;
               CREATE TRIGGER k4_inject BEFORE INSERT ON v24.requests
               FOR EACH ROW EXECUTE FUNCTION v24_fake.raise_k4()"""
        )
        cur.execute("SELECT clock_timestamp()::text")
        created = cur.fetchone()[0]
    owner.commit()
    return created


def _drop_k4_injection(owner) -> str:
    owner.rollback()
    with owner.cursor() as cur:
        cur.execute("DROP TRIGGER IF EXISTS k4_inject ON v24.requests")
        cur.execute("DROP FUNCTION IF EXISTS v24_fake.raise_k4()")
        cur.execute("SELECT clock_timestamp()::text")
        dropped = cur.fetchone()[0]
    owner.commit()
    return dropped


def _k4_objects(owner) -> tuple[int, int]:
    owner.rollback()
    with owner.cursor() as cur:
        cur.execute(
            """SELECT
                 (SELECT count(*) FROM pg_catalog.pg_trigger t
                    JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
                    JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname='v24' AND c.relname='requests'
                     AND t.tgname=%s AND NOT t.tgisinternal),
                 (SELECT count(*) FROM pg_catalog.pg_proc p
                    JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
                   WHERE n.nspname='v24_fake' AND p.proname='raise_k4')""",
            (K4_TRIGGER,),
        )
        value = cur.fetchone()
    owner.rollback()
    return value


def k1(db, owner) -> None:
    key = f"g5-k1-{secrets.token_hex(8)}"
    journal_dir = tempfile.mkdtemp(prefix="v24-s6-g5-")
    journal = jsonl_path(journal_dir, "K1")
    success = False
    try:
        before = g5_snapshot(owner)
        assert all(rows == [] for rows in before.values()), before
        before_fp = fingerprint(before)

        admin = db.connect("admin")
        try:
            parent_backend_pid = one(admin, "SELECT pg_catalog.pg_backend_pid()")
            principal = one(admin, "SELECT v24.principal_id(session_user)")
            effect_id = one(
                admin,
                "SELECT v24.effect_id_for(%s::uuid, %s, %s)",
                (principal, key, KIND),
            )
            canonical = one(
                admin,
                "SELECT encode(convert_to(v24.canonical_json(%s), 'UTF8'), 'base64')",
                (Json(k1_payload()),),
            )
            admin.rollback()
            assert one(owner, "SELECT count(*) FROM v24.effects") == 0
            assert one(owner, "SELECT count(*) FROM v24.requests") == 0
            assert one(owner, "SELECT count(*) FROM v24.scopes") == 0

            ready_r, ready_w = os.pipe()
            go_r, go_w = os.pipe()
            env = dict(
                os.environ,
                V24_DSN=db.role_dsn("admin"),
                V24_WINDOW="K1",
                V24_JOURNAL=journal,
                V24_READY_FD=str(ready_w),
                V24_GO_FD=str(go_r),
                V24_REQUEST_KEY=key,
            )
            child = subprocess.Popen(
                [sys.executable, str(CRASH_WORKER)],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                pass_fds=(ready_w, go_r),
            )
            os.close(ready_w)
            os.close(go_r)
            try:
                try:
                    ready = wait_ready(ready_r, timeout=30)
                except BaseException as exc:
                    _, child_stderr = _kill_and_reap(child)
                    raise AssertionError(
                        "crash child did not reach READY: "
                        f"{exc}; stderr={child_stderr.decode(errors='replace')}"
                    ) from None
                assert ready["window"] == "K1", ready
                assert ready["request_key"] == key, ready
                assert ready["effect_id"] == str(effect_id), ready
                assert ready["canonical_bytes"] == canonical, ready
                assert ready["tx_status"] == "intrans", ready
                child_backend_pid = ready["backend_pid"]
                assert isinstance(child_backend_pid, int), ready

                # The pre-COMMIT command must be invisible to every other backend.
                owner.rollback()
                assert one(
                    owner,
                    "SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                    (str(effect_id),),
                ) == 0
                assert one(
                    owner,
                    "SELECT count(*) FROM v24.requests WHERE request_key=%s",
                    (key,),
                ) == 0
                assert one(owner, "SELECT count(*) FROM v24.scopes") == 0
                assert one(owner, "SELECT count(*) FROM v24.events") == 0

                os.kill(child.pid, signal.SIGKILL)
                _, child_stderr = child.communicate(timeout=30)
                assert child.returncode == -signal.SIGKILL, (
                    child.returncode, child_stderr.decode(errors="replace"))
            finally:
                if child.poll() is None:
                    os.kill(child.pid, signal.SIGKILL)
                if child.returncode is None:
                    child.communicate(timeout=30)
            os.close(ready_r)
            os.close(go_w)
        finally:
            admin.close()

        assert read_jsonl(journal) == []
        try:
            owner.rollback()
            assert one(owner, "SELECT count(*) FROM v24.effects") == 0
            assert one(owner, "SELECT count(*) FROM v24.requests") == 0
            assert one(owner, "SELECT count(*) FROM v24.scopes") == 0

            worker_env = dict(
                os.environ,
                V24_DSN=db.role_dsn("admin"),
                V24_WINDOW="K1",
                V24_JOURNAL=journal,
                V24_REQUEST_KEY=key,
                V24_EFFECT_ID=str(effect_id),
                V24_CANONICAL_BYTES=canonical,
            )
            worker = subprocess.Popen(
                [sys.executable, str(RECOVER_WORKER)],
                env=worker_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            out, err = worker.communicate(timeout=60)
            assert worker.returncode == 0, (worker.returncode, err, out)
            lines = [line for line in out.splitlines() if line.strip()]
            assert lines, (out, err)
            result = json.loads(lines[-1])
            assert result["window"] == "K1", result
            assert result["os_pid"] == worker.pid, result
            assert result["request_key"] == key, result
            assert result["effect_id"] == str(effect_id), result
            assert result["canonical_bytes"] == canonical, result
            assert result["response"]["disposition"] == "committed", result
            worker_backend_pid = result["backend_pid"]
            assert isinstance(worker_backend_pid, int), result
            assert len({child_backend_pid, worker_backend_pid, parent_backend_pid}) == 3, (
                child_backend_pid, worker_backend_pid, parent_backend_pid)
            assert child.pid != worker.pid

            emitted = result["response"]["emitted"]
            assert len(emitted) == 1, result
            scope_id = emitted[0]

            owner.rollback()
            with owner.cursor() as cur:
                cur.execute(
                    """SELECT effect_id::text, status, request_key, kind,
                              attempt_no, scope_id::text
                         FROM v24.effects"""
                )
                effects = cur.fetchall()
            assert effects == [(
                str(effect_id), "succeeded", key, KIND, 0, scope_id,
            )], effects
            assert one(owner, "SELECT count(*) FROM v24.effects") == 1

            with owner.cursor() as cur:
                cur.execute(
                    """SELECT principal_id::text, request_key, kind,
                              effect_id::text, request_bytes
                         FROM v24.requests"""
                )
                requests = [
                    (row[0], row[1], row[2], row[3], bytes(row[4]))
                    for row in cur.fetchall()
                ]
            assert requests == [(
                str(principal), key, KIND, str(effect_id),
                base64.b64decode(canonical),
            )], requests
            assert one(owner, "SELECT count(*) FROM v24.requests") == 1

            with owner.cursor() as cur:
                cur.execute(
                    """SELECT scope_id::text, owner_principal::text,
                              created_by_effect::text
                         FROM v24.scopes"""
                )
                scopes = cur.fetchall()
            assert scopes == [(scope_id, str(principal), str(effect_id))], scopes

            with owner.cursor() as cur:
                cur.execute(
                    """SELECT count(*), min(entity_type), min(entity_id::text)
                         FROM v24.events WHERE effect_id=%s""",
                    (str(effect_id),),
                )
                events = cur.fetchone()
            assert events == (1, "scope", scope_id), events
            for table in ("runs", "pins", "episodes", "fibers", "slots", "installs"):
                assert one(owner, f"SELECT count(*) FROM v24.{table}") == 0, table
            owner.commit()
            after = g5_snapshot(owner)
        finally:
            admin.close()

        assert len(after["scopes"]) == 1
        assert len(after["effects"]) == 1
        assert len(after["requests"]) == 1
        assert len(after["events"]) == 1
        for table in ("runs", "pins", "episodes", "fibers", "slots", "installs"):
            assert after[table] == [], (table, after[table])
        assert read_jsonl(journal) == []
        after_fp = fingerprint(after)
        success = True
        print(
            "[G5-K1] child_pid=%d child_backend_pid=%d worker_pid=%d "
            "worker_backend_pid=%d parent_backend_pid=%d journal=%s "
            "requests=0->1 effects=0->1 snapshot=%s->%s"
            % (
                child.pid, child_backend_pid, worker.pid, worker_backend_pid,
                parent_backend_pid, journal, before_fp, after_fp,
            )
        )
    finally:
        if success:
            shutil.rmtree(journal_dir, ignore_errors=True)
        else:
            print(f"[G5-K1] retained journal={journal}", file=sys.stderr)


def _effect_row(owner, effect_id):
    value = one(owner, "SELECT to_jsonb(e) FROM v24.effects e WHERE e.effect_id=%s",
                (str(effect_id),))
    owner.rollback()
    return value


def _install(owner, install_id):
    value = one(owner, "SELECT to_jsonb(i) FROM v24.installs i WHERE i.install_id=%s",
                (str(install_id),))
    owner.rollback()
    return value


def _run(owner, run_id):
    value = one(owner, "SELECT to_jsonb(r) FROM v24.runs r WHERE r.run_id=%s",
                (str(run_id),))
    owner.rollback()
    return value


def _count(owner, statement, params=()):
    value = one(owner, statement, params)
    owner.rollback()
    return value


def _snapshot(owner):
    value = g5_snapshot(owner)
    owner.rollback()
    return value


def _advance_commit(conn, effect_id, outcome):
    response = advance(conn, effect_id, outcome)
    conn.commit()
    return response


def _journal_rows(owner, reservation, op=None):
    if op is None:
        return _count(
            owner,
            "SELECT count(*) FROM v24_fake.journal WHERE payload->>'reservation'=%s",
            (reservation,),
        )
    return _count(
        owner,
        """SELECT count(*) FROM v24_fake.journal
            WHERE payload->>'reservation'=%s AND op=%s""",
        (reservation, op),
    )


def _spawn_window(db, window, journal, extra, role="service"):
    ready_r, ready_w = os.pipe()
    go_r, go_w = os.pipe()
    env = dict(
        os.environ,
        V24_DSN=db.role_dsn(role),
        V24_OWNER_DSN=db.role_dsn("owner"),
        V24_ADMIN_DSN=db.role_dsn("admin"),
        V24_WINDOW=window,
        V24_JOURNAL=journal,
        V24_READY_FD=str(ready_w),
        V24_GO_FD=str(go_r),
    )
    env.update({key: str(value) for key, value in extra.items()})
    child = subprocess.Popen(
        [sys.executable, str(CRASH_WORKER)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        pass_fds=(ready_w, go_r),
    )
    os.close(ready_w)
    os.close(go_r)
    return child, ready_r, go_w


def _kill_and_reap(child):
    if child.poll() is None:
        os.kill(child.pid, signal.SIGKILL)
    try:
        return child.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        child.kill()
        return child.communicate(timeout=30)


def _kill_at_boundary(child, ready_r, go_w, window):
    try:
        try:
            ready = wait_ready(ready_r, timeout=30)
        except BaseException as exc:
            _, child_stderr = _kill_and_reap(child)
            raise AssertionError(
                "crash child did not reach READY: "
                f"{exc}; stderr={child_stderr.decode(errors='replace')}"
            ) from None
        assert ready["window"] == window, ready
        os.kill(child.pid, signal.SIGKILL)
        _, child_stderr = child.communicate(timeout=30)
        assert child.returncode == -signal.SIGKILL, (
            child.returncode, child_stderr.decode(errors="replace"))
        return ready
    finally:
        os.close(ready_r)
        os.close(go_w)
        if child.returncode is None:
            _kill_and_reap(child)


def _run_worker(db, window, journal, extra, role="service"):
    env = dict(
        os.environ,
        V24_DSN=db.role_dsn(role),
        V24_OWNER_DSN=db.role_dsn("owner"),
        V24_ADMIN_DSN=db.role_dsn("admin"),
        V24_WINDOW=window,
        V24_JOURNAL=journal,
    )
    env.update({key: str(value) for key, value in extra.items()})
    worker = subprocess.Popen(
        [sys.executable, str(RECOVER_WORKER)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = worker.communicate(timeout=120)
    assert worker.returncode == 0, (worker.returncode, err, out)
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines, (out, err)
    result = json.loads(lines[-1])
    result["_os_pid"] = worker.pid
    return result


def _expire(owner, effect_ids):
    """Seeded fixture expiry: owner DML on lease_until, never a public path."""
    with owner.cursor() as cur:
        cur.execute(
            """-- seeded fixture: the crashed owner's lease is made stale
               UPDATE v24.effects SET lease_until = now() - interval '1 second'
                WHERE effect_id = ANY(%s::uuid[])""",
            ([str(value) for value in effect_ids],),
        )
        assert cur.rowcount == len(effect_ids), cur.rowcount
    owner.commit()


def _assert_pids(ready, worker, parent_backend):
    assert ready["os_pid"] != worker["_os_pid"]
    assert len({ready["backend_pid"], worker["backend_pid"], parent_backend}) == 3, (
        ready["backend_pid"], worker["backend_pid"], parent_backend)
    assert worker["service_backend_pid"] not in (
        ready["backend_pid"], parent_backend)


def _host_reservation(owner, effect_id):
    request = one(owner, "SELECT request FROM v24.effects WHERE effect_id=%s",
                  (str(effect_id),))
    owner.rollback()
    return request["reservation"]


def _make_installed(db, owner, admin, service, key, identity):
    """Public setup: admit a provider install and settle its host prepare."""
    from fake_host import FakeHost

    scope = new_scope(admin, key + "-root")
    admitted = admit_install(admin, scope, identity, key + "-install",
                             provides=[{"realm": identity, "key": "k"}])
    install_id, host_effect = admitted["emitted"]
    token = advance(service, host_effect, claim())["claim"]
    service.commit()
    journal = db.connect("owner")
    journal.autocommit = True
    try:
        receipt = FakeHost(journal, ["succeed"]).prepare(service, host_effect, token)
    finally:
        journal.close()
    settled = advance(service, host_effect, receipt)
    service.commit()
    assert settled.get("disposition") == "committed", settled
    assert _install(owner, install_id)["state"] == "installed"
    return scope, install_id


def _new_scope_routed(admin, key, default_realm):
    response = one(
        admin,
        "SELECT v24.scope_control('create_root',NULL,%s,%s,%s)",
        (Json({}), default_realm, key),
    )
    admin.commit()
    assert response.get("disposition") == "committed", response
    return response["emitted"][0]


def _settle_prepare(db, owner, admin, service, install_id):
    """Public host_prepare success for an already-admitted install."""
    from fake_host import FakeHost

    host_effect = effect_of(owner, install_id, "host_prepare")
    token = advance(service, host_effect, claim())["claim"]
    service.commit()
    journal = db.connect("owner")
    journal.autocommit = True
    try:
        receipt = FakeHost(journal, ["succeed"]).prepare(
            service, host_effect, token)
    finally:
        journal.close()
    settled = advance(service, host_effect, receipt)
    service.commit()
    assert settled.get("disposition") == "committed", settled
    assert install_row(owner, install_id)["state"] == "installed"
    return host_effect


def _admit_and_install(db, owner, admin, service, scope, identity, key,
                       provides=(), requires=(), owner_fiber=None):
    admitted = admit_install(
        admin, scope, identity, key, provides=provides, requires=requires,
        owner_fiber=owner_fiber)
    install_id = admitted["emitted"][0]
    if provides:
        host_effect = _settle_prepare(db, owner, admin, service, install_id)
    else:
        # No provides and an empty artifact: the install is born installed.
        assert install_row(owner, install_id)["state"] == "installed"
        host_effect = None
    return install_id, host_effect


def _fiber(owner, install_id):
    fiber_id = fiber_of(owner, install_id)
    value = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE f.fiber_id=%s",
                (fiber_id,))
    owner.rollback()
    return value


def _fiber_control(admin, owner, fiber_id, action, key):
    control_seq = one(
        owner, "SELECT control_seq FROM v24.fibers WHERE fiber_id=%s",
        (fiber_id,))
    owner.rollback()
    response = one(
        admin, "SELECT v24.fiber_control(%s,%s,%s,%s)",
        (fiber_id, action, control_seq, key))
    admin.commit()
    return response


def _activate(admin, owner, install_id, key):
    fiber_id = fiber_of(owner, install_id)
    response = _fiber_control(admin, owner, fiber_id, "on", key)
    assert response.get("disposition") in ("committed", "deferred"), response
    episode_id = one(
        owner, "SELECT current_episode_id FROM v24.fibers WHERE fiber_id=%s",
        (fiber_id,))
    assert episode_id is not None, response
    with owner.cursor() as cur:
        cur.execute(
            """SELECT to_jsonb(s) FROM v24.slots s
                WHERE s.episode_id=%s ORDER BY s.contribution_seq, s.slot_id
                LIMIT 1""",
            (episode_id,),
        )
        row = cur.fetchone()
        slot = row[0] if row else None
    owner.rollback()
    fiber = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE f.fiber_id=%s",
                (fiber_id,))
    owner.rollback()
    return {
        "fiber": fiber,
        "fiber_id": fiber_id,
        "episode_id": episode_id,
        "slot": slot,
        "response": response,
    }


def _provider_slot(db, owner, admin, service, key):
    """An activated provider install, used only as a pin target."""
    scope = new_scope(admin, key + "-root")
    realm = "g5prov-" + secrets.token_hex(4)
    install_id, _ = _admit_and_install(
        db, owner, admin, service, scope, key + "-provider", key + "-install",
        provides=[{"realm": realm, "key": "k"}])
    activated = _activate(admin, owner, install_id, key + "-on")
    return {"scope": scope, "install": install_id,
            "fiber": activated["fiber_id"],
            "episode": activated["episode_id"],
            "slot": activated["slot"]["slot_id"]}


def _seed_run_with_model_pin(owner, scope, provider, key="dep"):
    """Fixture run+model whose request digests include the live run pin.

    The request jsonb is immutable once inserted, so the pin must exist before
    the model row is created; this is the only shape the normal S4 settlement
    accepts for a pinned run.
    """
    run_id, parent = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    insert_row(
        owner, "runs", run_id=run_id, scope_id=scope, status="running",
        epoch_no=1, registration_generation=1, turn_no=0, driving_generation=1,
        remaining_steps=5, remaining_tokens=1000, remaining_tool_calls=3,
        remaining_wall_ms=10000, revision=1, created_at=now, updated_at=now,
    )
    insert_row(
        owner, "effects", effect_id=parent, requester_id=uuid4(),
        kind="command_start", status="succeeded", scope_id=scope,
        run_id=run_id, request=Json({"fixture": "command_start"}),
        request_digest=b"g5-model-parent", replay_policy="replay_safe",
        outcome=Json({"v": 1, "class": "command", "claim": None, "body": {}}),
        settled_at=now,
    )
    pin_id = _seed_run_pin(owner, run_id, provider, parent, key=key)
    model_id = one(
        owner, "SELECT md5(%s::text || ':model_call:0')::uuid", (str(parent),))
    digests = one(owner, "SELECT v24.model_digests(%s)", (run_id,))
    request = {
        "v": 1, "cause": "start", "run_id": str(run_id), "epoch_no": 1,
        "generation": 1, "input": {}, "budget": {},
        "reserve": {"tokens": 64}, "digests": digests,
    }
    insert_row(
        owner, "effects", effect_id=model_id, parent_effect_id=parent, ordinal=0,
        requester_id=uuid4(), scope_id=scope, run_id=run_id, epoch_no=1,
        generation=1, kind="model_call", status="ready", request=Json(request),
        request_digest=b"g5-model-request", replay_policy="no_replay",
    )
    owner.commit()
    return {
        "run_id": str(run_id),
        "parent_effect_id": str(parent),
        "model_effect_id": str(model_id),
        "pin_id": str(pin_id),
    }


def _seed_run_pin(owner, run_id, provider, creator, key="dep"):
    pin_id = uuid4()
    insert_row(
        owner, "pins", pin_id=pin_id, consumer_type="run",
        consumer_run_id=run_id, consumer_epoch=1, key=key,
        slot_id=provider["slot"], provider_fiber_id=provider["fiber"],
        provider_episode_id=provider["episode"],
        descriptor_digest=b"g5-run-pin", created_by_effect=creator,
    )
    return pin_id


def _scope_close(admin, scope_id, key):
    response = one(
        admin, "SELECT v24.scope_control('close',%s,NULL,NULL,%s)",
        (scope_id, key))
    admin.commit()
    return response


def _pin_row(owner, pin_id):
    value = one(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE p.pin_id=%s",
                (pin_id,))
    owner.rollback()
    return value


def _events(owner, entity_type, entity_id):
    value = one(
        owner,
        """SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.seq),'[]'::jsonb)
             FROM v24.events e
            WHERE e.entity_type=%s AND e.entity_id=%s""",
        (entity_type, str(entity_id)),
    )
    owner.rollback()
    return value


def _scope(owner, scope_id):
    value = one(owner, "SELECT to_jsonb(s) FROM v24.scopes s WHERE s.scope_id=%s",
                (scope_id,))
    owner.rollback()
    return value


def _episode(owner, episode_id):
    value = one(owner, "SELECT to_jsonb(e) FROM v24.episodes e WHERE e.episode_id=%s",
                (episode_id,))
    owner.rollback()
    return value


def _slot(owner, slot_id):
    value = one(owner, "SELECT to_jsonb(s) FROM v24.slots s WHERE s.slot_id=%s",
                (slot_id,))
    owner.rollback()
    return value


def w3_control(db, owner, admin, service) -> None:
    """§4.5.3 control comparison: normal unknown vs recovery unknown.

    The two runs are structurally identical fixtures.  Time-valued columns are
    the only runtime-dependent run fields; the wall budget is clamped to zero
    for both arms by seeding an old effect created_at, so it is compared
    byte-for-byte.  Run/effect identity is replaced by a sentinel because two
    distinct effects cannot share a UUID; every other column and every event
    payload value is compared exactly.
    """
    key = f"g5-k3control-{secrets.token_hex(8)}"
    owner.rollback()
    admin.rollback()
    service.rollback()
    scope = new_scope(admin, key + "-root")
    provider = _provider_slot(db, owner, admin, service, key + "-prov")
    normal_seed = _seed_run_with_model_pin(owner, scope, provider)
    recover_seed = _seed_run_with_model_pin(owner, scope, provider)
    normal_effect = normal_seed["model_effect_id"]
    recover_effect = recover_seed["model_effect_id"]
    normal_token = advance(service, normal_effect, claim())["claim"]
    service.commit()
    recover_token = advance(service, recover_effect, claim())["claim"]
    service.commit()
    normal_pin = normal_seed["pin_id"]
    recover_pin = recover_seed["pin_id"]
    with owner.cursor() as cur:
        cur.execute(
            """-- seeded fixture: identical zero wall budget in both arms
               UPDATE v24.effects SET created_at=%s
                WHERE effect_id = ANY(%s::uuid[])""",
            (OLD, [normal_effect, recover_effect]),
        )
        assert cur.rowcount == 2, cur.rowcount
    owner.commit()

    normal_outcome = {
        "v": 1, "class": "unknown", "claim": normal_token,
        "body": {"kind": "model_call", "result": {}},
    }
    normal_response = advance(service, normal_effect, normal_outcome)
    service.commit()
    assert normal_response.get("disposition") == "committed", normal_response

    _expire(owner, [recover_effect])
    text = one(admin, "SELECT v24.command_recover(%s,%s,16)::text",
               (scope, key + "-recover"))
    admin.commit()
    recovery = json.loads(text)
    assert recovery.get("disposition") == "committed", recovery
    applied = {item["effect_id"]: item for item in recovery["recovery"]["applied"]}
    assert applied[recover_effect]["action"] == "settle_unknown", applied

    normal_run = _run(owner, normal_seed["run_id"])
    recover_run = _run(owner, recover_seed["run_id"])
    time_columns = {"created_at", "updated_at", "ended_at"}

    def run_projection(row):
        projection = {
            name: value for name, value in row.items()
            if name not in time_columns and name != "run_id"
        }
        close = projection.get("close_intent")
        if close is not None:
            projection["close_intent"] = dict(
                close, effect_id="<effect>")
        return projection

    normal_projection = run_projection(normal_run)
    recover_projection = run_projection(recover_run)
    assert normal_projection == recover_projection, (
        normal_projection, recover_projection)
    assert normal_run["status"] == "blocked_unknown", normal_run
    assert recover_run["status"] == "blocked_unknown", recover_run
    assert normal_run["remaining_wall_ms"] == 0, normal_run
    assert recover_run["remaining_wall_ms"] == 0, recover_run

    def event_projection(run_id, own_effect):
        rows = []
        for event in _events(owner, "run", run_id):
            payload = dict(event["payload"])
            # Run/effect identity is the only value that cannot be shared by
            # two structurally identical fixtures; normalize those two ids.
            if payload.get("effect_id") == own_effect:
                payload["effect_id"] = "<effect>"
            if payload.get("run_id") == run_id:
                payload["run_id"] = "<run>"
            payload.pop("reason", None)
            rows.append((event["event_kind"],
                         json.dumps(payload, sort_keys=True)))
        return sorted(rows)

    assert event_projection(normal_seed["run_id"], normal_effect) == (
        event_projection(recover_seed["run_id"], recover_effect))
    assert [event["event_kind"] for event in
            _events(owner, "run", normal_seed["run_id"])] == [
                "model_call_unknown", "run_blocked_unknown"]
    assert [event["event_kind"] for event in
            _events(owner, "run", recover_seed["run_id"])] == [
                "model_call_unknown", "run_blocked_unknown"]
    # The per-action recovery event is provenance: the normal path has no
    # equivalent and its payload keys are asserted on the recovery side only.
    recovery_events = _events(owner, "effect", recover_effect)
    assert [event["event_kind"] for event in recovery_events] == [
        "effect_recovered_unknown"], recovery_events
    assert set(recovery_events[0]["payload"]) == {
        "effect_id", "kind", "replay_policy", "action", "reason",
        "attempt_no", "fence", "recovery_effect_id"}, recovery_events[0]
    assert _events(owner, "effect", normal_effect) == []

    normal_pin_row = _pin_row(owner, str(normal_pin))
    recover_pin_row = _pin_row(owner, str(recover_pin))
    assert normal_pin_row["released_at"] is not None, normal_pin_row
    assert recover_pin_row["released_at"] is not None, recover_pin_row
    assert normal_pin_row["released_by_effect"] == normal_effect, normal_pin_row
    assert recover_pin_row["released_by_effect"] == recover_effect, recover_pin_row
    assert normal_pin_row["key"] == recover_pin_row["key"] == "dep"

    def effect_projection(effect_id):
        row = _effect_row(owner, effect_id)
        return {
            "status": row["status"],
            "resource_quiesced_at": row["resource_quiesced_at"],
            "claim_owner": row["claim_owner"],
            "lease_until": row["lease_until"],
            "attempt_no": row["attempt_no"],
            "fence": row["fence"],
            "kind": row["kind"],
            "replay_policy": row["replay_policy"],
        }

    normal_effect_row = _effect_row(owner, normal_effect)
    recover_effect_row = _effect_row(owner, recover_effect)
    assert effect_projection(normal_effect) == effect_projection(recover_effect)
    # The caller's unknown receipt is preserved on the normal path; recovery
    # synthesises its own receipt.  §4.5.3 compares the four columns above and
    # allows the receipt provenance to differ.
    assert normal_effect_row["outcome"] == normal_outcome, normal_effect_row
    recovery_outcome = recover_effect_row["outcome"]
    assert normal_effect_row["outcome"]["class"] == "unknown", normal_effect_row
    assert recovery_outcome["class"] == "unknown", recovery_outcome
    assert normal_effect_row["outcome"]["claim"] == {
        "attempt": 1, "fence": 1, "owner": normal_token["owner"]}, normal_effect_row
    assert recovery_outcome["claim"] == {
        "attempt": 1, "fence": 1, "owner": recover_token["owner"]}, recovery_outcome
    assert recovery_outcome["claim"]["attempt"] == 1, recovery_outcome
    assert recovery_outcome["claim"]["fence"] == 1, recovery_outcome
    assert recovery_outcome["body"]["kind"] == "model_call", recovery_outcome
    assert recovery_outcome["body"]["result"]["observed"] == "unknown"
    assert recovery_outcome["body"]["result"]["reason"] == "lease_expired"
    assert recovery_outcome["body"]["result"]["recovery"]["effect_id"] == (
        recover_effect), recovery_outcome
    print(
        "[G5-control] K3 scope=%s run_fields=%d byte-equal pins_released=%s/%s "
        "run_events=%s/%s effect_columns=equal(4/4) outcome_provenance=allowed "
        "wall=%d/%d action_event=effect_recovered_unknown(provenance)"
        % (
            scope, len(normal_projection),
            normal_pin_row["released_at"] is not None,
            recover_pin_row["released_at"] is not None,
            len(_events(owner, "run", normal_seed["run_id"])),
            len(_events(owner, "run", recover_seed["run_id"])),
            normal_run["remaining_wall_ms"], recover_run["remaining_wall_ms"],
        )
    )


def k2(db, owner, admin, service) -> None:
    window = "K2"
    key = f"g5-k2-{secrets.token_hex(8)}"
    journal_dir = tempfile.mkdtemp(prefix="v24-s6-g5-")
    journal = jsonl_path(journal_dir, window)
    success = False
    try:
        owner.rollback()
        admin.rollback()
        service.rollback()
        scope = new_scope(admin, key + "-root")
        admitted = admit_install(admin, scope, "g5-k2-install", key + "-install",
                                 provides=[{"realm": "g5k2", "key": "k"}])
        install_id, host_effect = admitted["emitted"]
        seed = seed_run_with_model(owner, scope)
        model_effect = seed["model_effect_id"]
        reservation = f"v24:host_prepare:{host_effect}"
        assert _journal_rows(owner, reservation) == 0
        before_worker = _snapshot(owner)
        parent_backend = one(admin, "SELECT pg_catalog.pg_backend_pid()")
        admin.rollback()

        child, ready_r, go_w = _spawn_window(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_HOST_EFFECT_ID": host_effect,
            "V24_MODEL_EFFECT_ID": model_effect,
        })
        ready = _kill_at_boundary(child, ready_r, go_w, window)
        assert ready["tx_status"] == "idle", ready
        assert ready["host_effect_id"] == host_effect, ready
        assert ready["model_effect_id"] == model_effect, ready
        assert ready["host_token"]["attempt"] == 1 and ready["host_token"]["fence"] == 1
        assert ready["model_token"]["attempt"] == 1 and ready["model_token"]["fence"] == 1

        host_before = _effect_row(owner, host_effect)
        model_before = _effect_row(owner, model_effect)
        assert host_before["status"] == "claimed", host_before
        assert host_before["replay_policy"] == "replay_safe", host_before
        assert model_before["status"] == "claimed", model_before
        assert model_before["replay_policy"] == "no_replay", model_before
        assert _install(owner, install_id)["state"] == "preparing"
        # The claim COMMIT is the only committed fact: no IO ran before the kill.
        assert _journal_rows(owner, reservation) == 0
        assert read_jsonl(journal) == []

        _expire(owner, [host_effect, model_effect])
        worker = _run_worker(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_HOST_EFFECT_ID": host_effect,
            "V24_RECOVER_KEY": key + "-recover",
        })
        _assert_pids(ready, worker, parent_backend)
        assert worker["resolve"] == [], worker["resolve"]

        recovery = worker["recover"]
        assert recovery["disposition"] == "committed", recovery
        applied = {item["effect_id"]: item for item in recovery["recovery"]["applied"]}
        assert set(applied) == {host_effect, model_effect}, applied
        assert applied[host_effect]["action"] == "reset_ready", applied
        assert applied[host_effect]["reason"] == "lease_expired", applied
        assert applied[host_effect]["attempt_no"] == 1, applied
        assert applied[host_effect]["fence"] == 1, applied
        assert applied[model_effect]["action"] == "settle_unknown", applied
        assert recovery["recovery"]["has_more"] is False, recovery
        assert recovery["recovery"]["manual_debt"] == 0, recovery

        host_after = _effect_row(owner, host_effect)
        model_after = _effect_row(owner, model_effect)
        assert host_after["status"] == "succeeded", host_after
        assert host_after["attempt_no"] == 2 and host_after["fence"] == 2, host_after
        assert host_after["claim_owner"] is None and host_after["lease_until"] is None
        assert host_after["outcome"]["class"] == "success", host_after
        assert model_after["status"] == "unknown", model_after
        assert model_after["attempt_no"] == 1 and model_after["fence"] == 1, model_after
        assert model_after["claim_owner"] is None and model_after["lease_until"] is None
        assert model_after["outcome"]["class"] == "unknown", model_after
        assert model_after["outcome"]["body"]["result"]["observed"] == "unknown"
        assert model_after["outcome"]["body"]["result"]["reason"] == "lease_expired"
        assert _install(owner, install_id)["state"] == "installed"

        run_after = _run(owner, seed["run_id"])
        assert run_after["status"] == "blocked_unknown", run_after
        assert run_after["ended_at"] is not None, run_after
        assert run_after["interaction"] is None and run_after["pending_steer"] is None

        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='command_recover' AND scope_id=%s",
                      (scope,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_prepare' AND scope_id=%s",
                      (scope,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='model_call' AND scope_id=%s",
                      (scope,)) == 1
        after = _snapshot(owner)
        assert len(after["effects"]) == len(before_worker["effects"]) + 1, (
            len(before_worker["effects"]), len(after["effects"]))
        assert len(after["requests"]) == len(before_worker["requests"]) + 1
        for table in ("scopes", "pins", "episodes", "fibers", "slots"):
            assert after[table] == before_worker[table], table

        assert _journal_rows(owner, reservation, "host_prepare") == 1
        assert _journal_rows(owner, reservation) == 1
        lines = read_jsonl(journal)
        assert {line["op"] for line in lines} == {"host_prepare", "recover"}, lines
        assert len([line for line in lines if line["action"] == "started"]) == 1
        assert len([line for line in lines if line["action"] == "finished"]) == 1
        assert worker["metrics"]["journal_rows"] == 1, worker["metrics"]
        # K2's first IO runs under the post-recovery claim, so the journal
        # records attempt/fence 2/2, not the crashed pre-IO claim.
        assert worker["metrics"]["journal_attempt"] == 2, worker["metrics"]
        assert worker["metrics"]["journal_fence"] == 2, worker["metrics"]
        assert fingerprint(after) == worker["snapshot"], (
            fingerprint(after), worker["snapshot"])
        success = True
        print(
            "[G5-K2] child_pid=%d child_backend_pid=%d worker_pid=%d "
            "worker_backend_pid=%d parent_backend_pid=%d journal=%s "
            "applied=%s has_more=%s model=unknown run=blocked_unknown "
            "journal_rows=1 journal_attempt/fence=%d/%d effects=%d->%d "
            "snapshot=%s->%s"
            % (
                ready["os_pid"], ready["backend_pid"], worker["_os_pid"],
                worker["backend_pid"], parent_backend, journal,
                [applied[host_effect]["action"], applied[model_effect]["action"]],
                recovery["recovery"]["has_more"],
                worker["metrics"]["journal_attempt"],
                worker["metrics"]["journal_fence"],
                len(before_worker["effects"]), len(after["effects"]),
                fingerprint(before_worker), fingerprint(after),
            )
        )
    finally:
        if success:
            shutil.rmtree(journal_dir, ignore_errors=True)
        else:
            print(f"[G5-K2] retained journal={journal}", file=sys.stderr)


def k3(db, owner, admin, service) -> None:
    window = "K3"
    key = f"g5-k3-{secrets.token_hex(8)}"
    journal_dir = tempfile.mkdtemp(prefix="v24-s6-g5-")
    journal = jsonl_path(journal_dir, window)
    success = False
    try:
        owner.rollback()
        admin.rollback()
        service.rollback()
        scope = new_scope(admin, key + "-root")
        admitted = admit_install(admin, scope, "g5-k3-install", key + "-install",
                                 provides=[{"realm": "g5k3", "key": "k"}])
        install_id, host_effect = admitted["emitted"]
        seed = seed_run_with_model(owner, scope)
        model_effect = seed["model_effect_id"]
        reservation = f"v24:host_prepare:{host_effect}"

        # W3 K3 model variant: a second structurally valid no_replay model with
        # a live run pin, and a third run that cancel won before the crash.
        provider = _provider_slot(db, owner, admin, service, key + "-prov")
        variant = _seed_run_with_model_pin(owner, scope, provider)
        variant_model = variant["model_effect_id"]
        variant_pin = variant["pin_id"]
        variant_token = advance(service, variant_model, claim())["claim"]
        service.commit()
        cancelled = seed_run_with_model(owner, scope)
        cancel_model = cancelled["model_effect_id"]
        cancel_token = advance(service, cancel_model, claim())["claim"]
        service.commit()
        cancel_response = one(
            admin, "SELECT v24.cancel(%s,%s,%s)",
            (cancelled["run_id"], 1, key + "-cancel"))
        admin.commit()
        assert cancel_response.get("disposition") == "committed", cancel_response
        # Seeded fixture: a live run pin survives the cancel (it was created
        # after the cancel seal), so the late wall must release it with the
        # cancelled status while leaving the seal untouched.
        cancel_pin = _seed_run_pin(
            owner, cancelled["run_id"], provider, cancel_model)
        owner.commit()
        cancel_seal = _run(owner, cancelled["run_id"])
        assert cancel_seal["status"] == "cancelled", cancel_seal
        with owner.cursor() as cur:
            # Seeded fixture: make the elapsed-wall deduction exactly 0 in both
            # the control arms and in this sweep.
            cur.execute(
                """-- seeded fixture: both effects are already old
                   UPDATE v24.effects SET created_at=%s
                    WHERE effect_id = ANY(%s::uuid[])""",
                (OLD, [variant_model, cancel_model]),
            )
            assert cur.rowcount == 2, cur.rowcount
        owner.commit()

        # N13: sixteen manual claims plus one replay_safe claim.  Manual rows
        # must not consume the 16-row bound or keep has_more true.
        manual_scope = new_scope(admin, key + "-manual-root")
        manual_ids = [
            seed_claim(owner, manual_scope, kind="model_call",
                       replay_policy="manual", lease_until=OLD)
            for _ in range(16)
        ]
        manual_safe = seed_claim(
            owner, manual_scope, kind="inspect_resource", lease_until=OLD)
        owner.commit()

        before_worker = _snapshot(owner)
        parent_backend = one(admin, "SELECT pg_catalog.pg_backend_pid()")
        admin.rollback()

        child, ready_r, go_w = _spawn_window(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_HOST_EFFECT_ID": host_effect,
            "V24_MODEL_EFFECT_ID": model_effect,
        })
        ready = _kill_at_boundary(child, ready_r, go_w, window)
        assert ready["host_receipt"]["class"] == "success", ready
        assert _effect_row(owner, host_effect)["status"] == "claimed"
        assert _effect_row(owner, model_effect)["status"] == "claimed"
        assert _effect_row(owner, variant_model)["status"] == "claimed"
        assert _effect_row(owner, cancel_model)["status"] == "claimed"
        assert _effect_row(owner, cancel_model)["cancel_requested"] is True
        # Pure helper projection: a claimed host_prepare only rewrites a
        # preparing install, and never emits a run/pin row.
        helper_prepare = one(
            owner, "SELECT v24.unknown_wall_delta(%s,'lease_expired')",
            (host_effect,))
        owner.rollback()
        assert helper_prepare["runs"] == [], helper_prepare
        assert helper_prepare["pins"] == [], helper_prepare
        assert helper_prepare["installs"] == [{
            "key": {"install_id": install_id}, "set": {"state": "prepare_unknown"},
        }], helper_prepare
        assert helper_prepare["effects"][0]["set"]["status"] == "unknown", (
            helper_prepare)
        assert set(helper_prepare["effects"][0]["set"]) == {
            "status", "outcome", "settled_at", "claim_owner", "lease_until"}, (
                helper_prepare["effects"][0]["set"])
        # The host IO is durable; the DB receipt is not.
        assert _journal_rows(owner, reservation, "host_prepare") == 1
        lines = read_jsonl(journal)
        assert len([line for line in lines if line["action"] == "started"]) == 1
        assert len([line for line in lines if line["action"] == "finished"]) == 1
        assert len([line for line in lines if line["op"] == "model_call"]) == 0

        _expire(owner, [host_effect, model_effect, variant_model, cancel_model])
        worker = _run_worker(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_HOST_EFFECT_ID": host_effect,
            "V24_RECOVER_KEY": key + "-recover",
            "V24_MANUAL_SCOPE": manual_scope,
            "V24_MANUAL_KEY": key + "-manual",
            "V24_MANUAL_KEY2": key + "-manual-2",
        })
        _assert_pids(ready, worker, parent_backend)
        recovery = worker["recover"]
        applied = {item["effect_id"]: item for item in recovery["recovery"]["applied"]}
        assert applied[host_effect]["action"] == "reset_ready", applied
        assert applied[model_effect]["action"] == "settle_unknown", applied
        assert applied[variant_model]["action"] == "settle_unknown", applied
        assert applied[cancel_model]["action"] == "settle_unknown", applied
        assert applied[cancel_model]["reason"] == "cancel_late", applied
        assert recovery["recovery"]["has_more"] is False, recovery
        assert recovery["recovery"]["manual_debt"] == 0, recovery
        assert worker["host"]["token"]["attempt"] == 2
        assert worker["host"]["token"]["fence"] == 2
        assert worker["host"]["receipt"]["class"] == "success", worker["host"]
        assert _install(owner, install_id)["state"] == "installed"
        assert _effect_row(owner, model_effect)["status"] == "unknown"
        assert _journal_rows(owner, reservation, "host_prepare") == 1
        assert _journal_rows(owner, reservation) == 1
        assert worker["metrics"]["journal_attempt"] == 1, worker["metrics"]
        assert worker["metrics"]["journal_fence"] == 1, worker["metrics"]

        lines = read_jsonl(journal)
        assert len([line for line in lines if line["action"] == "started"]) == 1, lines
        assert len([line for line in lines if line["action"] == "finished"]) == 1, lines
        assert len([line for line in lines if line["action"] == "reuse"]) >= 1, lines
        assert len([line for line in lines if line["op"] == "model_call"]) == 0, lines

        # N7: a late success on the now-unknown model effect is a W0 conflict.
        service.rollback()
        late = {
            "v": 1, "class": "success", "claim": ready["model_token"],
            "body": {"kind": "model_call", "result": {"v": 1, "text": "late"}},
        }
        before_late = _snapshot(owner)
        late_response = advance(service, model_effect, late)
        service.commit()
        after_late = _snapshot(owner)
        assert late_response == {
            "v": 1, "error": {"code": "receipt_conflict", "detail": {}},
        }, late_response
        assert before_late == after_late, (fingerprint(before_late), fingerprint(after_late))
        model_after = _effect_row(owner, model_effect)
        assert model_after["status"] == "unknown", model_after
        assert model_after["outcome"]["body"]["result"]["observed"] == "unknown"

        # W3 model variant: expired no_replay claim -> unknown + full wall.
        variant_run = _run(owner, variant["run_id"])
        assert variant_run["status"] == "blocked_unknown", variant_run
        assert variant_run["turn_no"] == 1, variant_run
        assert variant_run["revision"] == 2, variant_run
        assert variant_run["remaining_steps"] == 5, variant_run
        assert variant_run["remaining_tokens"] == 1000, variant_run
        assert variant_run["remaining_tool_calls"] == 3, variant_run
        assert variant_run["remaining_wall_ms"] == 0, variant_run
        assert variant_run["interaction"] is None, variant_run
        assert variant_run["pending_steer"] is None, variant_run
        assert variant_run["close_intent"] == {
            "kind": "unknown", "reason": "outcome_unknown",
            "effect_id": variant_model,
        }, variant_run
        assert variant_run["result"] == {
            "v": 1, "close_reason": "unknown", "turn_no": 1,
        }, variant_run
        assert variant_run["ended_at"] is not None, variant_run
        variant_after = _effect_row(owner, variant_model)
        assert variant_after["status"] == "unknown", variant_after
        assert variant_after["settled_at"] is not None, variant_after
        assert variant_after["claim_owner"] is None, variant_after
        assert variant_after["lease_until"] is None, variant_after
        assert variant_after["resource_quiesced_at"] is None, variant_after
        assert variant_after["outcome"]["class"] == "unknown", variant_after
        assert variant_after["outcome"]["body"]["result"]["reason"] == "lease_expired"
        variant_pin_after = _pin_row(owner, str(variant_pin))
        assert variant_pin_after["released_at"] is not None, variant_pin_after
        assert variant_pin_after["released_by_effect"] == variant_model, variant_pin_after
        variant_events = _events(owner, "run", variant["run_id"])
        assert [event["event_kind"] for event in variant_events] == [
            "model_call_unknown", "run_blocked_unknown"], variant_events
        assert variant_events[0]["payload"] == {
            "run_id": variant["run_id"], "effect_id": variant_model,
            "turn_no": 1, "reason": "outcome_unknown"}, variant_events[0]
        assert variant_events[1]["payload"] == {
            "run_id": variant["run_id"], "reason": "outcome_unknown",
            "effect_id": variant_model}, variant_events[1]

        # N7 on the variant: late success after unknown is W0 receipt_conflict.
        before_variant_late = _snapshot(owner)
        variant_late = advance(service, variant_model, {
            "v": 1, "class": "success", "claim": variant_token,
            "body": {"kind": "model_call", "result": {"v": 1, "text": "late"}},
        })
        service.commit()
        after_variant_late = _snapshot(owner)
        assert variant_late == {
            "v": 1, "error": {"code": "receipt_conflict", "detail": {}},
        }, variant_late
        assert before_variant_late == after_variant_late, (
            fingerprint(before_variant_late), fingerprint(after_variant_late))
        assert _effect_row(owner, variant_model)["status"] == "unknown"

        # Cancel-late: the effect settles unknown, the cancel seal is untouched,
        # and only the late unknown fact is emitted.
        cancel_after = _run(owner, cancelled["run_id"])
        for column in ("status", "close_intent", "result", "interaction",
                       "pending_steer", "ended_at", "turn_no", "revision"):
            assert cancel_after[column] == cancel_seal[column], (
                column, cancel_after[column], cancel_seal[column])
        cancel_model_after = _effect_row(owner, cancel_model)
        assert cancel_model_after["status"] == "unknown", cancel_model_after
        assert cancel_model_after["outcome"]["body"]["result"]["reason"] == (
            "cancel_late"), cancel_model_after
        cancel_unknown_events = [
            event for event in _events(owner, "run", cancelled["run_id"])
            if event["event_kind"] in ("model_call_unknown", "run_blocked_unknown")
        ]
        assert [event["event_kind"] for event in cancel_unknown_events] == [
            "model_call_unknown"], cancel_unknown_events
        assert cancel_unknown_events[0]["payload"]["late"] is True, cancel_unknown_events[0]
        assert cancel_unknown_events[0]["payload"]["turn_no"] == 0, cancel_unknown_events[0]
        cancel_pin_after = _pin_row(owner, str(cancel_pin))
        assert cancel_pin_after["released_at"] is not None, cancel_pin_after
        assert cancel_pin_after["released_by_effect"] == cancel_model, cancel_pin_after

        # N13: manual rows are counted, never written, never bound-consuming.
        manual = worker["manual"]
        manual2 = worker["manual2"]
        assert [item["effect_id"] for item in
                manual["recovery"]["applied"]] == [manual_safe], manual
        assert manual["recovery"]["applied"][0]["action"] == "reset_ready", manual
        assert manual["recovery"]["manual_debt"] == 16, manual
        assert manual["recovery"]["has_more"] is False, manual
        assert manual2["recovery"]["applied"] == [], manual2
        assert manual2["recovery"]["manual_debt"] == 16, manual2
        assert manual2["recovery"]["has_more"] is False, manual2
        assert _effect_row(owner, manual_safe)["status"] == "ready"
        for manual_id in manual_ids:
            assert _effect_row(owner, manual_id)["status"] == "claimed", manual_id
        assert _count(
            owner,
            "SELECT count(*) FROM v24.effects WHERE kind='command_recover' AND scope_id=%s",
            (manual_scope,)) == 2
        assert _count(
            owner,
            """SELECT count(*) FROM v24.events e
                JOIN v24.effects ef ON ef.effect_id=e.effect_id
               WHERE ef.kind='command_recover' AND ef.scope_id=%s
                 AND e.event_kind='effect_recovered_unknown'""",
            (manual_scope,)) == 0

        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_prepare' AND scope_id=%s",
                      (scope,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='model_call' AND scope_id=%s",
                      (scope,)) == 3
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='command_recover' AND scope_id=%s",
                      (scope,)) == 1
        after = _snapshot(owner)
        assert len(after["effects"]) == len(before_worker["effects"]) + 3, (
            len(before_worker["effects"]), len(after["effects"]))
        assert fingerprint(after) == worker["snapshot"]
        # §4.5.3 control comparison, a K3 sub-assertion (no extra window).
        w3_control(db, owner, admin, service)
        success = True
        print(
            "[G5-K3] child_pid=%d child_backend_pid=%d worker_pid=%d "
            "worker_backend_pid=%d parent_backend_pid=%d journal=%s "
            "applied=reset_ready+settle_unknown(model/cancel-late) "
            "reservation=1 reuse=no-second-io "
            "late=receipt_conflict-w0 restore=%s model_variant=blocked_unknown+pin "
            "cancel_late=seal-preserved+late-only manual=16/0 has_more=False "
            "effects=%d->%d snapshot=%s->%s"
            % (
                ready["os_pid"], ready["backend_pid"], worker["_os_pid"],
                worker["backend_pid"], parent_backend, journal,
                fingerprint(before_late) == fingerprint(after_late),
                len(before_worker["effects"]), len(after["effects"]),
                fingerprint(before_worker), fingerprint(after),
            )
        )
    finally:
        if success:
            shutil.rmtree(journal_dir, ignore_errors=True)
        else:
            print(f"[G5-K3] retained journal={journal}", file=sys.stderr)


def k4(db, owner, admin) -> None:
    """K4: fixture-only SQL error on the request insert, rollback, replay."""
    window = "K4"
    key = f"g5-k4-{secrets.token_hex(8)}"
    journal_dir = tempfile.mkdtemp(prefix="v24-s6-g5-")
    journal = jsonl_path(journal_dir, window)
    success = False
    trigger_created = None
    trigger_dropped = None
    sql_before = _sql_tree_digest()
    try:
        owner.rollback()
        admin.rollback()
        before = _snapshot(owner)
        before_fp = fingerprint(before)
        parent_backend_pid = one(admin, "SELECT pg_catalog.pg_backend_pid()")
        principal = one(admin, "SELECT v24.principal_id(session_user)")
        effect_id = one(
            admin,
            "SELECT v24.effect_id_for(%s::uuid, %s, %s)",
            (principal, key, KIND),
        )
        canonical = one(
            admin,
            "SELECT encode(convert_to(v24.canonical_json(%s), 'UTF8'), 'base64')",
            (Json(k1_payload()),),
        )
        admin.rollback()
        assert _count(owner, "SELECT count(*) FROM v24.requests WHERE request_key=%s",
                      (key,)) == 0
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                      (str(effect_id),)) == 0
        assert _count(owner, "SELECT count(*) FROM v24.scopes WHERE created_by_effect=%s",
                      (str(effect_id),)) == 0

        trigger_created = _create_k4_injection(owner)
        assert _k4_objects(owner) == (1, 1), "K4 fixture trigger/function missing"
        child, ready_r, go_w = _spawn_window(db, window, journal, {
            "V24_REQUEST_KEY": key,
        }, role="admin")
        ready = _wait_child_exit(child, ready_r, go_w, window)
        assert ready["phase"] == "rolled_back", ready
        assert ready["tx_status"] == "idle", ready
        assert ready["sqlstate"] == "P0001", ready
        assert "k4 injected request fault" in ready["error"], ready
        assert ready["request_key"] == key, ready
        assert ready["effect_id"] == str(effect_id), ready
        assert ready["canonical_bytes"] == canonical, ready
        child_backend_pid = ready["backend_pid"]
        assert isinstance(child_backend_pid, int), ready

        after_rollback = _snapshot(owner)
        after_rollback_fp = fingerprint(after_rollback)
        assert after_rollback == before, snapshot_diff(before, after_rollback)
        assert _count(owner, "SELECT count(*) FROM v24.requests WHERE request_key=%s",
                      (key,)) == 0
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                      (str(effect_id),)) == 0
        assert _count(owner, "SELECT count(*) FROM v24.scopes WHERE created_by_effect=%s",
                      (str(effect_id),)) == 0
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE parent_effect_id=%s",
                      (str(effect_id),)) == 0
        assert read_jsonl(journal) == []

        trigger_dropped = _drop_k4_injection(owner)
        assert _k4_objects(owner) == (0, 0), "K4 trigger/function survived the drop"
        assert _count(owner, "SELECT count(*) FROM v24.requests WHERE request_key=%s",
                      (key,)) == 0
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE effect_id=%s",
                      (str(effect_id),)) == 0

        worker = _run_worker(db, window, journal, {
            "V24_REQUEST_KEY": key,
            "V24_EFFECT_ID": str(effect_id),
            "V24_CANONICAL_BYTES": canonical,
        }, role="admin")
        assert worker["window"] == "K4", worker
        assert worker["request_key"] == key, worker
        assert worker["effect_id"] == str(effect_id), worker
        assert worker["canonical_bytes"] == canonical, worker
        assert worker["response"]["disposition"] == "committed", worker
        assert len(worker["response"]["emitted"]) == 1, worker
        scope_id = worker["response"]["emitted"][0]
        worker_backend_pid = worker["backend_pid"]
        assert len({child_backend_pid, worker_backend_pid, parent_backend_pid}) == 3, (
            child_backend_pid, worker_backend_pid, parent_backend_pid)
        assert worker["_os_pid"] != child.pid

        assert _count(owner, "SELECT count(*) FROM v24.requests WHERE request_key=%s",
                      (key,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects "
                             "WHERE request_key=%s AND kind=%s",
                      (key, KIND)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.scopes WHERE created_by_effect=%s",
                      (str(effect_id),)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE parent_effect_id=%s",
                      (str(effect_id),)) == 0
        assert _count(owner, "SELECT count(*) FROM v24.events WHERE effect_id=%s",
                      (str(effect_id),)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='command_recover' "
                             "AND scope_id=%s", (scope_id,)) == 0

        after = _snapshot(owner)
        after_fp = fingerprint(after)
        diff = snapshot_diff(before, after)
        assert set(diff) == {"scopes", "effects", "requests", "events"}, diff
        assert len(after["scopes"]) == len(before["scopes"]) + 1
        assert len(after["effects"]) == len(before["effects"]) + 1
        assert len(after["requests"]) == len(before["requests"]) + 1
        assert len(after["events"]) == len(before["events"]) + 1
        sql_after = _sql_tree_digest()
        assert sql_after == sql_before, (sql_before, sql_after)
        assert _k4_objects(owner) == (0, 0)
        assert read_jsonl(journal) == []
        success = True
        print(
            "[G5-K4] child_pid=%d child_backend_pid=%d worker_pid=%d "
            "worker_backend_pid=%d parent_backend_pid=%d request_key=%s "
            "effect_id=%s sqlstate=P0001 tx=rollback->idle trigger=%s "
            "trigger_created=%s trigger_dropped=%s journal=%s "
            "requests=0->1 effects=0->1 "
            "response=committed snapshot_before=%s snapshot_after_rollback=%s "
            "snapshot_after_resubmit=%s snapshot_before_eq_after_rollback=true "
            "sql_digest=%s k4_objects_after=0/0 sql_unchanged=true"
            % (
                ready["os_pid"], child_backend_pid, worker["_os_pid"],
                worker_backend_pid, parent_backend_pid, key, effect_id,
                K4_TRIGGER, trigger_created, trigger_dropped, journal,
                before_fp, after_rollback_fp, after_fp, sql_before,
            )
        )
    finally:
        if trigger_dropped is None:
            owner.rollback()
            trigger_dropped = _drop_k4_injection(owner)
        objects = _k4_objects(owner)
        assert objects == (0, 0), objects
        sql_after = _sql_tree_digest()
        assert sql_after == sql_before, (sql_before, sql_after)
        if success:
            shutil.rmtree(journal_dir, ignore_errors=True)
        else:
            print(f"[G5-K4] retained journal={journal}", file=sys.stderr)


def k5(db, owner, admin) -> None:
    """K5: command_recover committed, response lost, two byte-equal replays."""
    window = "K5"
    key = f"g5-k5-{secrets.token_hex(8)}"
    journal_dir = tempfile.mkdtemp(prefix="v24-s6-g5-")
    journal = jsonl_path(journal_dir, window)
    success = False
    try:
        owner.rollback()
        admin.rollback()
        scope = new_scope(admin, key + "-root")
        seed = seed_claim(
            owner, scope, kind="inspect_resource", replay_policy="replay_safe",
            lease_until=FUTURE)
        owner.commit()
        _expire(owner, [seed])
        canonical = one(
            admin,
            "SELECT encode(convert_to(v24.canonical_json(%s), 'UTF8'), 'base64')",
            (Json({"v": 1, "scope_id": scope, "limit": 16}),),
        )
        admin.rollback()
        before = _snapshot(owner)
        before_fp = fingerprint(before)
        seed_before = _effect_row(owner, seed)
        assert seed_before["status"] == "claimed", seed_before
        assert seed_before["attempt_no"] == 1 and seed_before["fence"] == 1, seed_before
        parent_backend_pid = one(admin, "SELECT pg_catalog.pg_backend_pid()")
        admin.rollback()

        child, ready_r, go_w = _spawn_window(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_REQUEST_KEY": key,
            "V24_LIMIT": "16",
        }, role="admin")
        ready = _kill_at_boundary(child, ready_r, go_w, window)
        assert ready["phase"] == "committed", ready
        assert ready["tx_status"] == "idle", ready
        assert ready["scope_id"] == scope, ready
        assert ready["request_key"] == key, ready
        assert ready["limit"] == 16, ready
        assert ready["canonical_bytes"] == canonical, ready
        assert ready["disposition"] == "committed", ready
        assert not ({"response", "response_text", "response_sha256"}
                    & set(ready)), ready
        child_backend_pid = ready["backend_pid"]
        assert isinstance(child_backend_pid, int), ready

        post_kill = _snapshot(owner)
        post_kill_fp = fingerprint(post_kill)
        assert post_kill != before
        diff = snapshot_diff(before, post_kill)
        assert set(diff) == {"effects", "events", "requests"}, diff

        seed_after = _effect_row(owner, seed)
        assert seed_after["status"] == "ready", seed_after
        assert seed_after["claim_owner"] is None and seed_after["lease_until"] is None
        assert seed_after["attempt_no"] == 1 and seed_after["fence"] == 1, seed_after
        seed_events = _events(owner, "effect", seed)
        assert [event["event_kind"] for event in seed_events] == [
            "effect_recovered_replay"], seed_events
        assert seed_events[0]["payload"]["action"] == "reset_ready", seed_events[0]

        recovery_effect = one(
            owner,
            "SELECT effect_id::text FROM v24.effects "
            "WHERE request_key=%s AND kind='command_recover'", (key,))
        owner.rollback()
        request_bytes = one(
            owner, "SELECT encode(request_bytes, 'base64') FROM v24.requests "
                   "WHERE effect_id=%s", (recovery_effect,))
        owner.rollback()
        assert request_bytes == canonical, (request_bytes, canonical)
        stored_text = one(
            owner, "SELECT response::text FROM v24.requests WHERE effect_id=%s",
            (recovery_effect,))
        owner.rollback()
        stored = json.loads(stored_text)
        assert stored["disposition"] == "committed", stored
        stored_stable = _stable_json(stored)
        stored_sha = _sha256_text(stored_stable)
        stored_bytes = len(stored_stable.encode("utf-8"))

        assert _count(owner, "SELECT count(*) FROM v24.requests WHERE request_key=%s",
                      (key,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects "
                             "WHERE request_key=%s AND kind='command_recover'",
                      (key,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.events WHERE effect_id=%s",
                      (recovery_effect,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE parent_effect_id=%s",
                      (recovery_effect,)) == 0
        assert _count(owner, "SELECT count(*) FROM v24.runs WHERE scope_id=%s",
                      (scope,)) == 0
        assert read_jsonl(journal) == []

        base_extra = {
            "V24_SCOPE_ID": scope,
            "V24_REQUEST_KEY": key,
            "V24_LIMIT": "16",
            "V24_CANONICAL_BYTES": canonical,
        }
        replays = []
        for index in (1, 2):
            replay = _run_worker(
                db, window, journal,
                {**base_extra, "V24_REPLAY_INDEX": str(index)}, role="admin")
            assert replay["window"] == "K5", replay
            assert replay["replay_index"] == index, replay
            assert replay["scope_id"] == scope, replay
            assert replay["request_key"] == key, replay
            assert replay["effect_id"] == recovery_effect, replay
            assert replay["canonical_bytes"] == canonical, replay
            assert replay["request_bytes"] == canonical, replay
            assert replay["response_text"] == stored_stable, replay
            assert replay["response_sha256"] == stored_sha, replay
            assert replay["response_bytes"] == stored_bytes, replay
            assert replay["snapshot_unchanged"] is True, replay
            assert replay["before"] == replay["after"] == post_kill_fp, replay
            assert replay["counts"] == {
                "requests": 1, "effects": 1, "events": 1, "successors": 0,
            }, replay
            assert replay["_os_pid"] != child.pid
            assert len({child_backend_pid, replay["backend_pid"],
                        parent_backend_pid}) == 3, (
                child_backend_pid, replay["backend_pid"], parent_backend_pid)
            replays.append(replay)
        replay1, replay2 = replays
        assert replay1["response_text"] == replay2["response_text"]
        assert replay1["response_sha256"] == replay2["response_sha256"]
        assert replay1["response_bytes"] == replay2["response_bytes"]

        replay1_snapshot = _snapshot(owner)
        replay1_fp = fingerprint(replay1_snapshot)
        replay2_snapshot = _snapshot(owner)
        replay2_fp = fingerprint(replay2_snapshot)
        assert replay1_fp == replay2_fp == post_kill_fp, (
            post_kill_fp, replay1_fp, replay2_fp)
        assert _count(owner, "SELECT count(*) FROM v24.requests WHERE request_key=%s",
                      (key,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects "
                             "WHERE request_key=%s AND kind='command_recover'",
                      (key,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.events WHERE effect_id=%s",
                      (recovery_effect,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE parent_effect_id=%s",
                      (recovery_effect,)) == 0
        assert _count(owner, "SELECT count(*) FROM v24.runs WHERE scope_id=%s",
                      (scope,)) == 0
        assert read_jsonl(journal) == []
        success = True
        canonical_plain = canonical.replace("\n", "")
        canonical_raw_sha = hashlib.sha256(
            base64.b64decode(canonical)).hexdigest()
        print(
            "[G5-K5] child_pid=%d child_backend_pid=%d worker1_pid=%d "
            "worker1_backend_pid=%d worker2_pid=%d worker2_backend_pid=%d "
            "parent_backend_pid=%d request_key=%s effect_id=%s seed_effect_id=%s "
            "journal=%s "
            "canonical_b64=%s "
            "canonical_sha256=%s first_commit_sha256=%s first_commit_bytes=%d "
            "replay1_sha256=%s replay1_bytes=%d replay2_sha256=%s replay2_bytes=%d "
            "byte_equal=true requests=1 effects=1 sweep_events=1 "
            "sweep_action=reset_ready successors=0 "
            "budget=inapplicable(no-run) snapshot_before=%s snapshot_post_kill=%s "
            "snapshot_replay1=%s snapshot_replay2=%s second_replay_zero_write=true"
            % (
                ready["os_pid"], child_backend_pid, replay1["_os_pid"],
                replay1["backend_pid"], replay2["_os_pid"],
                replay2["backend_pid"], parent_backend_pid, key, recovery_effect,
                seed, journal, canonical_plain, canonical_raw_sha, stored_sha,
                stored_bytes,
                replay1["response_sha256"], replay1["response_bytes"],
                replay2["response_sha256"], replay2["response_bytes"],
                before_fp, post_kill_fp, replay1_fp, replay2_fp,
            )
        )
    finally:
        if success:
            shutil.rmtree(journal_dir, ignore_errors=True)
        else:
            print(f"[G5-K5] retained journal={journal}", file=sys.stderr)


def k6(db, owner, admin, service) -> None:
    """Provider withdraw committed; slot/pin release still outstanding."""
    window = "K6"
    key = f"g5-k6-{secrets.token_hex(8)}"
    journal_dir = tempfile.mkdtemp(prefix="v24-s6-g5-")
    journal = jsonl_path(journal_dir, window)
    success = False
    try:
        owner.rollback()
        admin.rollback()
        service.rollback()
        scope = _new_scope_routed(admin, key + "-root", "g5k6")
        provider_install, _ = _admit_and_install(
            db, owner, admin, service, scope, key + "-provider",
            key + "-provider-install",
            provides=[{"realm": "g5k6", "key": "k"}])
        provider = _activate(admin, owner, provider_install, key + "-provider-on")
        consumer_install, _ = _admit_and_install(
            db, owner, admin, service, scope, key + "-consumer",
            key + "-consumer-install",
            requires=[{"realm": "g5k6", "key": "k"}])
        consumer = _activate(admin, owner, consumer_install, key + "-consumer-on")
        # A terminal run is already committed before the crash; the retire must
        # not rewrite it or release anything it does not hold.
        terminal_run = uuid4()
        terminal_now = datetime.now(timezone.utc)
        insert_row(
            owner, "runs", run_id=terminal_run, scope_id=scope,
            status="blocked_unknown", epoch_no=1, registration_generation=1,
            turn_no=2, driving_generation=1, remaining_steps=3,
            remaining_tokens=100, remaining_tool_calls=0,
            remaining_wall_ms=100, revision=3,
            close_intent=Json({"kind": "unknown", "reason": "outcome_unknown"}),
            result=Json({"v": 1, "close_reason": "unknown", "turn_no": 2}),
            created_at=terminal_now, updated_at=terminal_now,
            ended_at=terminal_now,
        )
        owner.commit()
        terminal_before = _run(owner, terminal_run)
        pin = one(owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE consumer_episode_id=%s",
                  (consumer["episode_id"],))
        owner.rollback()
        assert pin is not None and pin["released_at"] is None, pin
        pin_id = pin["pin_id"]
        before_worker = _snapshot(owner)
        parent_backend = one(admin, "SELECT pg_catalog.pg_backend_pid()")
        admin.rollback()

        child, ready_r, go_w = _spawn_window(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_PROVIDER_FIBER_ID": provider["fiber_id"],
            "V24_CONSUMER_FIBER_ID": consumer["fiber_id"],
            "V24_WITHDRAW_KEY": key + "-withdraw",
        })
        ready = _kill_at_boundary(child, ready_r, go_w, window)
        assert ready["withdraw"]["disposition"] in ("committed", "deferred"), ready
        provider_ep = _episode(owner, provider["episode_id"])
        provider_slot = _slot(owner, provider["slot"]["slot_id"])
        assert provider_ep["state"] == "retiring", provider_ep
        assert provider_slot["withdrawn_at"] is not None, provider_slot
        assert provider_slot["released_at"] is None, provider_slot
        assert _pin_row(owner, str(pin_id))["released_at"] is None
        assert _install(owner, provider_install)["disposed_at"] is None
        assert _install(owner, consumer_install)["disposed_at"] is None
        assert _scope(owner, scope)["closed_at"] is None
        assert _fiber(owner, provider_install)["disposed_at"] is None

        worker = _run_worker(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_RECOVER_KEY": key + "-recover",
            "V24_CONSUMER_FIBER_ID": consumer["fiber_id"],
            "V24_PROVIDER_FIBER_ID": provider["fiber_id"],
        })
        _assert_pids(ready, worker, parent_backend)
        assert len(worker["resolve"]) == 1, worker["resolve"]
        assert worker["resolve"][0]["live"] is False, worker["resolve"]
        recovery = worker["recover"]
        assert recovery["disposition"] == "committed", recovery
        assert recovery["recovery"]["applied"] == [], recovery
        assert recovery["recovery"]["has_more"] is False, recovery
        assert worker["actions"]["consumer"]["disposition"] in (
            "committed", "deferred"), worker["actions"]
        assert worker["actions"]["provider"]["disposition"] in (
            "committed", "deferred"), worker["actions"]
        assert _count(owner,
                      "SELECT count(*) FROM v24.effects WHERE kind='command_recover' AND scope_id=%s",
                      (scope,)) == 1
        assert _count(owner,
                      "SELECT count(*) FROM v24.effects WHERE kind='command_fiber_control' AND scope_id=%s",
                      (scope,)) == 5, _count(
                          owner,
                          "SELECT count(*) FROM v24.effects WHERE kind='command_fiber_control' AND scope_id=%s",
                          (scope,))

        provider_ep_after = _episode(owner, provider["episode_id"])
        consumer_ep_after = _episode(owner, consumer["episode_id"])
        provider_slot_after = _slot(owner, provider["slot"]["slot_id"])
        pin_after = _pin_row(owner, str(pin_id))
        assert provider_ep_after["state"] == "closed", provider_ep_after
        assert consumer_ep_after["state"] == "closed", consumer_ep_after
        assert provider_slot_after["released_at"] is not None, provider_slot_after
        assert pin_after["released_at"] is not None, pin_after
        assert _install(owner, provider_install)["state"] == "installed"
        assert _install(owner, provider_install)["disposed_at"] is None
        assert _install(owner, consumer_install)["disposed_at"] is None
        assert _fiber(owner, provider_install)["current_episode_id"] is None
        assert _scope(owner, scope)["closed_at"] is None
        assert _run(owner, terminal_run) == terminal_before, _run(owner, terminal_run)
        provider_events = [event["event_kind"] for event in
                           _events(owner, "episode", provider["episode_id"])]
        slot_events = [event["event_kind"] for event in
                       _events(owner, "slot", provider["slot"]["slot_id"])]
        assert provider_events == [
            "episode_opened", "episode_retire_started", "episode_closed"], provider_events
        assert slot_events == [
            "slot_contributed", "slot_withdrawn", "slot_released"], slot_events
        assert _count(owner,
                      "SELECT count(*) FROM v24.events WHERE event_kind='pin_released' AND entity_id=%s",
                      (pin_id,)) == 1
        journal_ops = [line["op"] for line in read_jsonl(journal)]
        assert journal_ops.count("recover") == 1, journal_ops
        assert journal_ops.count("fiber_control") == 2, journal_ops
        after = _snapshot(owner)
        assert fingerprint(after) == worker["snapshot"], (
            fingerprint(after), worker["snapshot"])
        success = True
        print(
            "[G5-K6] child_pid=%d child_backend_pid=%d worker_pid=%d "
            "worker_backend_pid=%d parent_backend_pid=%d journal=%s "
            "resolve_live=False pin_live_at_crash=True pin_released_after=True "
            "run_terminal=preserved episode=%s->closed "
            "slot=%s->released journal=recover+fiber_control "
            "install_disposed=%s/%s scope_closed_at=%s effects=%d->%d "
            "snapshot=%s->%s"
            % (
                ready["os_pid"], ready["backend_pid"], worker["_os_pid"],
                worker["backend_pid"], parent_backend, journal,
                provider_ep["state"], provider_slot["withdrawn_at"] is not None,
                _install(owner, provider_install)["disposed_at"],
                _install(owner, consumer_install)["disposed_at"],
                _scope(owner, scope)["closed_at"],
                len(before_worker["effects"]), len(after["effects"]),
                fingerprint(before_worker), fingerprint(after),
            )
        )
    finally:
        if success:
            shutil.rmtree(journal_dir, ignore_errors=True)
        else:
            print(f"[G5-K6] retained journal={journal}", file=sys.stderr)


def k7(db, owner, admin, service) -> None:
    """Child subtree disposed; the parent retire is still incomplete."""
    window = "K7"
    key = f"g5-k7-{secrets.token_hex(8)}"
    journal_dir = tempfile.mkdtemp(prefix="v24-s6-g5-")
    journal = jsonl_path(journal_dir, window)
    success = False
    try:
        owner.rollback()
        admin.rollback()
        service.rollback()
        scope = _new_scope_routed(admin, key + "-root", "g5k7p")
        parent_install, _ = _admit_and_install(
            db, owner, admin, service, scope, key + "-parent",
            key + "-parent-install",
            provides=[{"realm": "g5k7p", "key": "k"}])
        parent = _activate(admin, owner, parent_install, key + "-parent-on")
        child_install, _ = _admit_and_install(
            db, owner, admin, service, scope, key + "-child",
            key + "-child-install",
            provides=[{"realm": "g5k7c", "key": "c"}],
            requires=[{"realm": "g5k7p", "key": "k"}],
            owner_fiber=parent["fiber_id"])
        child = _activate(admin, owner, child_install, key + "-child-on")
        child_pin = one(
            owner, "SELECT to_jsonb(p) FROM v24.pins p WHERE consumer_episode_id=%s",
            (child["episode_id"],))
        owner.rollback()
        assert child_pin is not None, child_pin
        child_pin_id = child_pin["pin_id"]
        # The parent retire stops at the child install/pin barrier.
        parent_withdraw = _fiber_control(
            admin, owner, parent["fiber_id"], "off", key + "-parent-off")
        assert parent_withdraw["disposition"] in ("committed", "deferred"), parent_withdraw
        parent_ep = _episode(owner, parent["episode_id"])
        parent_slot = _slot(owner, parent["slot"]["slot_id"])
        assert parent_ep["state"] == "retiring", parent_ep
        assert parent_slot["withdrawn_at"] is not None, parent_slot
        assert parent_slot["released_at"] is None, parent_slot
        before_worker = _snapshot(owner)
        parent_backend = one(admin, "SELECT pg_catalog.pg_backend_pid()")
        admin.rollback()

        child_row, ready_r, go_w = _spawn_window(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_CHILD_INSTALL_ID": child_install,
            "V24_CHILD_FIBER_ID": child["fiber_id"],
            "V24_CHILD_OFF_KEY": key + "-child-off",
            "V24_CHILD_DISPOSE_KEY": key + "-child-dispose",
        })
        ready = _kill_at_boundary(child_row, ready_r, go_w, window)
        assert ready["release_receipt"]["class"] == "success", ready
        child_install_row = _install(owner, child_install)
        child_fiber_row = _fiber(owner, child_install)
        child_ep_row = _episode(owner, child["episode_id"])
        child_slot_row = _slot(owner, child["slot"]["slot_id"])
        assert child_install_row["state"] == "disposed", child_install_row
        assert child_install_row["disposed_at"] is not None, child_install_row
        assert child_fiber_row["disposed_at"] is not None, child_fiber_row
        assert child_ep_row["state"] == "closed", child_ep_row
        assert child_slot_row["released_at"] is not None, child_slot_row
        assert _pin_row(owner, str(child_pin_id))["released_at"] is not None
        assert _install(owner, parent_install)["disposed_at"] is None
        parent_ep_mid = _episode(owner, parent["episode_id"])
        parent_slot_mid = _slot(owner, parent["slot"]["slot_id"])
        parent_fiber_mid = _fiber(owner, parent_install)
        assert parent_ep_mid["state"] == "retiring", parent_ep_mid
        assert parent_slot_mid["released_at"] is None, parent_slot_mid
        assert parent_fiber_mid["current_episode_id"] == str(parent["episode_id"]), (
            parent_fiber_mid)
        assert child_install_row["owner_fiber_id"] == str(parent["fiber_id"])
        assert child_install_row["owner_episode_id"] == str(parent["episode_id"])
        assert _scope(owner, scope)["closed_at"] is None

        worker = _run_worker(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_RECOVER_KEY": key + "-recover",
            "V24_PARENT_FIBER_ID": parent["fiber_id"],
        })
        _assert_pids(ready, worker, parent_backend)
        assert len(worker["resolve"]) == 1, worker["resolve"]
        assert worker["resolve"][0]["live"] is False, worker["resolve"]
        recovery = worker["recover"]
        assert recovery["recovery"]["applied"] == [], recovery
        assert recovery["recovery"]["has_more"] is False, recovery
        assert worker["actions"]["parent"]["disposition"] in (
            "committed", "deferred"), worker["actions"]

        child_install_after = _install(owner, child_install)
        assert child_install_after["disposed_at"] == child_install_row["disposed_at"]
        assert child_install_after["owner_fiber_id"] == str(parent["fiber_id"])
        assert child_install_after["owner_episode_id"] == str(parent["episode_id"])
        parent_ep_after = _episode(owner, parent["episode_id"])
        parent_slot_after = _slot(owner, parent["slot"]["slot_id"])
        parent_fiber_after = _fiber(owner, parent_install)
        assert parent_ep_after["state"] == "closed", parent_ep_after
        assert parent_slot_after["released_at"] is not None, parent_slot_after
        assert parent_slot_after["released_at"] > child_install_row["disposed_at"], (
            parent_slot_after["released_at"], child_install_row["disposed_at"])
        assert parent_fiber_after["current_episode_id"] is None, parent_fiber_after
        assert _install(owner, parent_install)["disposed_at"] is None
        parent_events = [event["event_kind"] for event in
                         _events(owner, "episode", parent["episode_id"])]
        assert parent_events == [
            "episode_opened", "episode_retire_started", "episode_closed"], parent_events
        journal_ops = [line["op"] for line in read_jsonl(journal)]
        assert journal_ops.count("recover") == 1, journal_ops
        assert journal_ops.count("fiber_control") == 1, journal_ops
        assert journal_ops.count("host_release") == 2, journal_ops
        after = _snapshot(owner)
        assert fingerprint(after) == worker["snapshot"], (
            fingerprint(after), worker["snapshot"])
        success = True
        print(
            "[G5-K7] child_pid=%d child_backend_pid=%d worker_pid=%d "
            "worker_backend_pid=%d parent_backend_pid=%d journal=%s "
            "resolve_live=False child_disposed_at=%s unchanged=True "
            "parent_episode=%s->closed parent_slot_released=%s>child_disposed "
            "owner_pair=%s/%s scope_closed_at=%s effects=%d->%d snapshot=%s->%s"
            % (
                ready["os_pid"], ready["backend_pid"], worker["_os_pid"],
                worker["backend_pid"], parent_backend, journal,
                child_install_row["disposed_at"], parent_ep["state"],
                parent_slot_after["released_at"] is not None,
                child_install_after["owner_fiber_id"] == str(parent["fiber_id"]),
                child_install_after["owner_episode_id"] == str(parent["episode_id"]),
                _scope(owner, scope)["closed_at"],
                len(before_worker["effects"]), len(after["effects"]),
                fingerprint(before_worker), fingerprint(after),
            )
        )
    finally:
        if success:
            shutil.rmtree(journal_dir, ignore_errors=True)
        else:
            print(f"[G5-K7] retained journal={journal}", file=sys.stderr)


def k9(db, owner, admin, service) -> None:
    """Scope closing with prepare_unknown; no closed_at before inspect."""
    window = "K9"
    key = f"g5-k9-{secrets.token_hex(8)}"
    journal_dir = tempfile.mkdtemp(prefix="v24-s6-g5-")
    journal = jsonl_path(journal_dir, window)
    success = False
    try:
        owner.rollback()
        admin.rollback()
        service.rollback()
        scope = new_scope(admin, key + "-root")
        before_worker = _snapshot(owner)
        parent_backend = one(admin, "SELECT pg_catalog.pg_backend_pid()")
        admin.rollback()

        child, ready_r, go_w = _spawn_window(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_INSTALL_IDENTITY": "g5-k9-provider",
            "V24_INSTALL_KEY": key + "-install",
            "V24_CLOSE_KEY": key + "-close",
        })
        ready = _kill_at_boundary(child, ready_r, go_w, window)
        install_id = ready["install_id"]
        host_effect = ready["host_effect_id"]
        scope_row = _scope(owner, scope)
        install_before = _install(owner, install_id)
        host_before = _effect_row(owner, host_effect)
        assert scope_row["close_requested_at"] is not None, scope_row
        assert scope_row["closed_at"] is None, scope_row
        assert install_before["state"] == "prepare_unknown", install_before
        assert host_before["status"] == "unknown", host_before
        assert host_before["resource_quiesced_at"] is None, host_before
        closable = scope_closable(owner, scope)
        assert closable["ok"] is False, closable
        assert closable["pending"]["installs"] > 0, closable

        worker = _run_worker(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_RECOVER_KEY": key + "-recover",
            "V24_CLOSE_KEY": key + "-close-loop",
        })
        _assert_pids(ready, worker, parent_backend)
        assert worker["resolve"] == [], worker["resolve"]
        recovery = worker["recover"]
        assert recovery["recovery"]["applied"] == [], recovery
        assert recovery["recovery"]["has_more"] is False, recovery
        assert worker["metrics"]["recovery_effects"] == 1, worker["metrics"]
        steps = worker["actions"]["steps"]
        assert len(steps) >= 4, len(steps)
        inspect_steps = [
            (step, executed)
            for step in steps
            for executed in step["executed"]
            if executed["kind"] == "inspect_resource"
        ]
        assert len(inspect_steps) == 1, inspect_steps
        inspect_step, inspect_executed = inspect_steps[0]
        assert inspect_step["closed_at"] is None, inspect_step
        assert inspect_executed["receipt"]["body"]["result"]["observed"] in (
            "known", "absent"), inspect_executed
        assert inspect_executed["receipt"]["body"]["result"]["observed"] == (
            "absent"), inspect_executed
        # No step may set closed_at before the install is disposed: every step
        # but the last has closed_at NULL, and the final step's install is gone.
        for step in steps[:-1]:
            assert step["closed_at"] is None, step
        assert steps[-1]["closed_at"] is not None, steps[-1]
        assert all(row["state"] == "disposed" for row in steps[-1]["installs"]), (
            steps[-1]["installs"])
        install_after = _install(owner, install_id)
        host_after = _effect_row(owner, host_effect)
        scope_after = _scope(owner, scope)
        assert install_after["state"] == "disposed", install_after
        assert install_after["disposed_at"] is not None, install_after
        assert host_after["resource_quiesced_at"] is not None, host_after
        assert scope_after["closed_at"] is not None, scope_after
        assert _count(
            owner,
            """SELECT count(*) FROM v24.events
                WHERE entity_type='scope' AND entity_id=%s
                  AND event_kind='scope_closed'""",
            (scope,)) == 1
        control_count = _count(
            owner,
            "SELECT count(*) FROM v24.effects WHERE kind='command_scope_control' AND scope_id=%s",
            (scope,))
        # create_root + the child's first close + one close per worker step.
        assert control_count == 2 + len(steps), (control_count, len(steps))
        assert _count(
            owner,
            "SELECT count(*) FROM v24.effects WHERE kind='inspect_resource' AND scope_id=%s",
            (scope,)) == 1
        journal_ops = [line["op"] for line in read_jsonl(journal)]
        assert journal_ops.count("recover") == 1, journal_ops
        assert journal_ops.count("inspect_resource") == 2, journal_ops
        after = _snapshot(owner)
        assert fingerprint(after) == worker["snapshot"], (
            fingerprint(after), worker["snapshot"])
        success = True
        print(
            "[G5-K9] child_pid=%d child_backend_pid=%d worker_pid=%d "
            "worker_backend_pid=%d parent_backend_pid=%d journal=%s "
            "child_state=closing/prepare_unknown/unknown-unquiesced "
            "closed_at_before_inspect=None scope_closable_ok=False "
            "inspect_observed=%s install=%s host_quiesced=%s "
            "closed_at_after_steps=%s scope_closed=1 close_steps=%d "
            "effects=%d->%d snapshot=%s->%s"
            % (
                ready["os_pid"], ready["backend_pid"], worker["_os_pid"],
                worker["backend_pid"], parent_backend, journal,
                inspect_executed["receipt"]["body"]["result"]["observed"],
                install_after["state"],
                host_after["resource_quiesced_at"] is not None,
                scope_after["closed_at"] is not None, len(steps),
                len(before_worker["effects"]), len(after["effects"]),
                fingerprint(before_worker), fingerprint(after),
            )
        )
    finally:
        if success:
            shutil.rmtree(journal_dir, ignore_errors=True)
        else:
            print(f"[G5-K9] retained journal={journal}", file=sys.stderr)


def k8(db, owner, admin, service) -> None:
    window = "K8"
    key = f"g5-k8-{secrets.token_hex(8)}"
    journal_dir = tempfile.mkdtemp(prefix="v24-s6-g5-")
    journal = jsonl_path(journal_dir, window)
    success = False
    try:
        owner.rollback()
        admin.rollback()
        service.rollback()
        scope = new_scope(admin, key + "-root")
        before_worker = _snapshot(owner)
        parent_backend = one(admin, "SELECT pg_catalog.pg_backend_pid()")
        admin.rollback()

        child, ready_r, go_w = _spawn_window(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_INSTALL_IDENTITY": "g5-k8-provider",
            "V24_INSTALL_KEY": key + "-install",
        })
        ready = _kill_at_boundary(child, ready_r, go_w, window)
        install_id = ready["install_id"]
        host_effect = ready["host_effect_id"]
        reservation = f"v24:host_prepare:{host_effect}"
        assert _install(owner, install_id)["state"] == "preparing"
        host_before = _effect_row(owner, host_effect)
        assert host_before["status"] == "claimed", host_before
        assert host_before["attempt_no"] == 1 and host_before["fence"] == 1
        assert _journal_rows(owner, reservation, "host_prepare") == 1

        _expire(owner, [host_effect])
        before_worker = _snapshot(owner)
        worker = _run_worker(db, window, journal, {
            "V24_SCOPE_ID": scope,
            "V24_HOST_EFFECT_ID": host_effect,
            "V24_RECOVER_KEY": key + "-recover",
            "V24_REFUSED_KEY": key + "-refused",
            "V24_ACTIVATION_KEY": key + "-activate",
        })
        _assert_pids(ready, worker, parent_backend)
        assert worker["refused"]["before"] == fingerprint(before_worker), (
            worker["refused"]["before"], fingerprint(before_worker))
        refused = worker["refused"]["response"]
        assert refused == {
            "v": 1, "error": {"code": "install_not_ready", "detail": {}},
        }, refused
        diff = worker["refused"]["diff"]
        # W0 for the activation domain: the refused command writes only its own
        # failed receipt and the frozen fiber failure stamp, never install/
        # episode/slot/pin state.
        assert set(diff) == {"effects", "requests", "fibers"}, diff
        refused_effects = {row["kind"]: row for row in diff["effects"]["added"]}
        assert set(refused_effects) == {"command_fiber_control", "fiber_reconcile"}
        refused_effect = refused_effects["command_fiber_control"]
        assert refused_effect["status"] == "failed", refused_effect
        reconcile = refused_effects["fiber_reconcile"]
        assert reconcile["status"] == "failed", reconcile
        assert reconcile["outcome"]["code"] == "install_not_ready", reconcile
        assert len(diff["requests"]["added"]) == 1
        assert diff["requests"]["added"][0]["kind"] == "command_fiber_control"
        assert diff["requests"]["added"][0]["response"]["error"]["code"] == (
            "install_not_ready"), diff["requests"]["added"][0]
        assert len(diff["fibers"]["changed"]) == 1, diff["fibers"]
        fiber_change = diff["fibers"]["changed"][0]
        assert fiber_change["before"]["want_on"] is False, fiber_change
        assert fiber_change["after"]["want_on"] is True, fiber_change
        assert fiber_change["after"]["control_seq"] == 1, fiber_change
        assert fiber_change["after"]["failure"]["code"] == "install_not_ready"
        for table in ("installs", "episodes", "slots", "pins"):
            assert table not in diff, (table, diff.get(table))

        recovery = worker["recover"]
        applied = {item["effect_id"]: item for item in recovery["recovery"]["applied"]}
        assert applied[host_effect]["action"] == "reset_ready", applied
        assert recovery["recovery"]["has_more"] is False, recovery
        assert worker["host"]["receipt"]["class"] == "success", worker["host"]
        assert _install(owner, install_id)["state"] == "installed"
        host_after = _effect_row(owner, host_effect)
        assert host_after["status"] == "succeeded", host_after
        assert host_after["attempt_no"] == 2 and host_after["fence"] == 2, host_after
        assert _journal_rows(owner, reservation, "host_prepare") == 1
        assert _journal_rows(owner, reservation) == 1
        assert worker["metrics"]["journal_attempt"] == 1, worker["metrics"]
        assert worker["metrics"]["journal_fence"] == 1, worker["metrics"]

        activation = worker["activation"]
        assert activation["disposition"] == "committed", activation
        assert len(activation["emitted"]) == 1, activation
        episode_id = activation["emitted"][0]
        assert _count(owner, "SELECT count(*) FROM v24.episodes WHERE episode_id=%s",
                      (episode_id,)) == 1
        fiber = one(owner, "SELECT to_jsonb(f) FROM v24.fibers f WHERE f.install_id=%s",
                    (install_id,))
        owner.rollback()
        assert fiber["want_on"] is True and fiber["current_episode_id"] is not None
        assert fiber["current_episode_id"] == episode_id
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_prepare' AND scope_id=%s",
                      (scope,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='command_recover' AND scope_id=%s",
                      (scope,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='command_fiber_control' AND scope_id=%s",
                      (scope,)) == 2
        lines = read_jsonl(journal)
        assert len([line for line in lines if line["action"] == "started"]) == 1, lines
        assert len([line for line in lines if line["action"] == "finished"]) == 1, lines
        assert len([line for line in lines if line["action"] == "reuse"]) >= 1, lines
        after = _snapshot(owner)
        assert fingerprint(after) == worker["snapshot"]
        success = True
        print(
            "[G5-K8] child_pid=%d child_backend_pid=%d worker_pid=%d "
            "worker_backend_pid=%d parent_backend_pid=%d journal=%s "
            "refused=install_not_ready-w0(activation-domain) "
            "diff=%s preparing->installed reservation=1 journal_attempt/fence=%d/%d "
            "activation=%s snapshot=%s->%s"
            % (
                ready["os_pid"], ready["backend_pid"], worker["_os_pid"],
                worker["backend_pid"], parent_backend, journal,
                {table: {key_: len(value) for key_, value in diff[table].items()}
                 for table in sorted(diff)},
                worker["metrics"]["journal_attempt"],
                worker["metrics"]["journal_fence"],
                episode_id, fingerprint(before_worker), fingerprint(after),
            )
        )
    finally:
        if success:
            shutil.rmtree(journal_dir, ignore_errors=True)
        else:
            print(f"[G5-K8] retained journal={journal}", file=sys.stderr)


def k10(db, owner, admin, service) -> None:
    window = "K10"
    key = f"g5-k10-{secrets.token_hex(8)}"
    journal_dir = tempfile.mkdtemp(prefix="v24-s6-g5-")
    success = False
    try:
        owner.rollback()
        admin.rollback()
        service.rollback()

        # ---- K10a: the release receipt is durable; replay returns it. ----
        journal = jsonl_path(journal_dir, "K10")
        scope_a, install_a = _make_installed(
            db, owner, admin, service, key + "-a", "g5-k10-a")
        parent_backend = one(admin, "SELECT pg_catalog.pg_backend_pid()")
        admin.rollback()
        before_a = _snapshot(owner)
        child, ready_r, go_w = _spawn_window(db, window, journal, {
            "V24_SCOPE_ID": scope_a,
            "V24_INSTALL_ID": install_a,
            "V24_DISPOSE_KEY": key + "-a-dispose",
        })
        ready_a = _kill_at_boundary(child, ready_r, go_w, window)
        release_a = ready_a["host_effect_id"]
        reservation_a = f"v24:host_release:{release_a}"
        assert ready_a["host_receipt"]["class"] == "success", ready_a
        assert _install(owner, install_a)["state"] == "dispose_pending"
        release_before = _effect_row(owner, release_a)
        assert release_before["status"] == "claimed", release_before
        assert release_before["attempt_no"] == 1 and release_before["fence"] == 1
        assert _journal_rows(owner, reservation_a, "host_release") == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_release' AND scope_id=%s",
                      (scope_a,)) == 1
        helper_release = one(
            owner, "SELECT v24.unknown_wall_delta(%s,'state_mismatch')",
            (release_a,))
        owner.rollback()
        assert helper_release["installs"] == [], helper_release
        assert helper_release["runs"] == [] and helper_release["pins"] == [], (
            helper_release)
        assert helper_release["effects"][0]["set"]["status"] == "unknown", (
            helper_release)

        _expire(owner, [release_a])
        worker_a = _run_worker(db, window, journal, {
            "V24_SCOPE_ID": scope_a,
            "V24_HOST_EFFECT_ID": release_a,
            "V24_RECOVER_KEY": key + "-a-recover",
        })
        _assert_pids(ready_a, worker_a, parent_backend)
        recovery_a = worker_a["recover"]
        applied_a = {item["effect_id"]: item for item in recovery_a["recovery"]["applied"]}
        assert applied_a[release_a]["action"] == "reset_ready", applied_a
        assert worker_a["host"]["token"]["attempt"] == 2
        assert worker_a["host"]["token"]["fence"] == 2
        assert worker_a["host"]["receipt"]["class"] == "success", worker_a["host"]
        install_after = _install(owner, install_a)
        assert install_after["state"] == "disposed", install_after
        assert install_after["disposed_at"] is not None, install_after
        release_after = _effect_row(owner, release_a)
        assert release_after["status"] == "succeeded", release_after
        assert release_after["attempt_no"] == 2 and release_after["fence"] == 2
        assert release_after["resource_quiesced_at"] is not None, release_after
        assert _journal_rows(owner, reservation_a, "host_release") == 1
        assert _journal_rows(owner, reservation_a) == 1
        assert worker_a["metrics"]["journal_attempt"] == 1, worker_a["metrics"]
        assert worker_a["metrics"]["journal_fence"] == 1, worker_a["metrics"]
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_release' AND scope_id=%s",
                      (scope_a,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='command_recover' AND scope_id=%s",
                      (scope_a,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='inspect_resource' AND scope_id=%s",
                      (scope_a,)) == 0
        lines_a = read_jsonl(journal)
        assert len([line for line in lines_a if line["action"] == "started"]) == 1
        assert len([line for line in lines_a if line["action"] == "finished"]) == 1
        assert len([line for line in lines_a if line["action"] == "reuse"]) >= 1
        after_a = _snapshot(owner)
        assert fingerprint(after_a) == worker_a["snapshot"]

        # ---- K10b: the durable receipt was lost; inspect the same
        # reservation, never send a second release. ----
        journal_b = jsonl_path(journal_dir, "K10b")
        scope_b, install_b = _make_installed(
            db, owner, admin, service, key + "-b", "g5-k10-b")
        before_b = _snapshot(owner)
        child, ready_r, go_w = _spawn_window(db, "K10b", journal_b, {
            "V24_SCOPE_ID": scope_b,
            "V24_INSTALL_ID": install_b,
            "V24_DISPOSE_KEY": key + "-b-dispose",
        })
        ready_b = _kill_at_boundary(child, ready_r, go_w, "K10b")
        release_b = ready_b["host_effect_id"]
        reservation_b = f"v24:host_release:{release_b}"
        assert ready_b["host_receipt"]["class"] == "unknown", ready_b
        assert _install(owner, install_b)["state"] == "dispose_pending"
        assert _journal_rows(owner, reservation_b, "host_release") == 1
        lost_row = one(owner, """SELECT result FROM v24_fake.journal
                                  WHERE payload->>'reservation'=%s AND op='host_release'""",
                       (reservation_b,))
        owner.rollback()
        assert lost_row is None, lost_row
        lines_b = read_jsonl(journal_b)
        assert len([line for line in lines_b if line["action"] == "started"]) == 1
        assert not [line for line in lines_b if line["action"] == "finished"], lines_b

        _expire(owner, [release_b])
        worker_b = _run_worker(db, "K10b", journal_b, {
            "V24_SCOPE_ID": scope_b,
            "V24_HOST_EFFECT_ID": release_b,
            "V24_RECOVER_KEY": key + "-b-recover",
            "V24_INSPECT_DISPOSE_KEY": key + "-b-inspect-dispose",
        })
        _assert_pids(ready_b, worker_b, parent_backend)
        recovery_b = worker_b["recover"]
        applied_b = {item["effect_id"]: item for item in recovery_b["recovery"]["applied"]}
        assert applied_b[release_b]["action"] == "reset_ready", applied_b
        assert worker_b["host"]["receipt"]["class"] == "unknown", worker_b["host"]
        inspect = worker_b["inspect"]
        assert inspect["request"]["target"] == "host_release", inspect
        assert inspect["request"]["target_effect_id"] == release_b, inspect
        assert inspect["request"]["target_reservation"] == reservation_b, inspect
        release_digest = one(owner,
            "SELECT encode(request_digest,'hex') FROM v24.effects WHERE effect_id=%s",
            (release_b,))
        owner.rollback()
        assert inspect["request"]["target_request_digest"] == release_digest, inspect
        assert inspect["receipt"]["body"]["result"]["observed"] == "known", inspect
        assert _journal_rows(owner, reservation_b, "host_release") == 1
        assert _journal_rows(owner, reservation_b, "inspect_resource") == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='host_release' AND scope_id=%s",
                      (scope_b,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='inspect_resource' AND scope_id=%s",
                      (scope_b,)) == 1
        assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='command_recover' AND scope_id=%s",
                      (scope_b,)) == 1
        install_b_after = _install(owner, install_b)
        assert install_b_after["state"] == "disposed", install_b_after
        assert install_b_after["disposed_at"] is not None
        release_b_after = _effect_row(owner, release_b)
        assert release_b_after["status"] == "unknown", release_b_after
        assert release_b_after["resource_quiesced_at"] is not None, release_b_after
        inspect_after = _effect_row(owner, inspect["effect_id"])
        assert inspect_after["status"] == "succeeded", inspect_after
        lines_b = read_jsonl(journal_b)
        assert len([line for line in lines_b if line["op"] == "inspect_resource"
                    and line["action"] == "finished"]) == 1, lines_b
        after_b = _snapshot(owner)
        assert fingerprint(after_b) == worker_b["snapshot"]
        success = True
        print(
            "[G5-K10] child_pid=%d child_backend_pid=%d worker_pid=%d "
            "worker_backend_pid=%d parent_backend_pid=%d journals=%s,%s "
            "release_a=success->disposed release_rows_a=%s "
            "release_b=lost->inspect target_reservation=%s disposed=%s "
            "release_rows_b=%s inspect_rows_b=%s snapshot_a=%s->%s snapshot_b=%s->%s"
            % (
                ready_a["os_pid"], ready_a["backend_pid"], worker_a["_os_pid"],
                worker_a["backend_pid"], parent_backend, journal, journal_b,
                _count(owner, "SELECT count(*) FROM v24_fake.journal WHERE payload->>'reservation'=%s AND op='host_release'",
                       (reservation_a,)),
                inspect["request"]["target_reservation"],
                install_b_after["state"],
                _journal_rows(owner, reservation_b, "host_release"),
                _journal_rows(owner, reservation_b, "inspect_resource"),
                fingerprint(before_a), fingerprint(after_a),
                fingerprint(before_b), fingerprint(after_b),
            )
        )
    finally:
        if success:
            shutil.rmtree(journal_dir, ignore_errors=True)
        else:
            print(f"[G5-K10] retained journal={journal_dir}", file=sys.stderr)


def _recover_text(conn, scope, key, limit):
    text = one(conn, "SELECT v24.command_recover(%s, %s, %s)::text",
               (scope, key, limit))
    conn.commit()
    return text, json.loads(text)


def _w0(owner, action, label):
    before = _snapshot(owner)
    value = action()
    after = _snapshot(owner)
    before_fp, after_fp = fingerprint(before), fingerprint(after)
    assert before == after, (label, before_fp, after_fp)
    return value, before_fp, after_fp


def w2_contract(db, owner, admin, service) -> None:
    """W2 done-when contract: replay bytes, conflicts, reset, limits, ACL."""
    key = f"g5-w2-{secrets.token_hex(8)}"
    owner.rollback()
    admin.rollback()
    service.rollback()
    admin_pid = one(admin, "SELECT pg_catalog.pg_backend_pid()")
    service_pid = one(service, "SELECT pg_catalog.pg_backend_pid()")
    admin.rollback()
    service.rollback()
    scope = new_scope(admin, key + "-root")
    admitted = admit_install(admin, scope, "g5-w2-install", key + "-install",
                             provides=[{"realm": "g5w2", "key": "k"}])
    install_id, host_effect = admitted["emitted"]
    token = advance(service, host_effect, claim())["claim"]
    service.commit()
    _expire(owner, [host_effect])

    request_key = key + "-recover"
    response_text, response = _recover_text(admin, scope, request_key, 16)
    applied = {item["effect_id"]: item for item in response["recovery"]["applied"]}
    assert applied[host_effect]["action"] == "reset_ready", applied
    assert applied[host_effect]["reason"] == "lease_expired", applied
    assert applied[host_effect]["attempt_no"] == 1, applied
    assert applied[host_effect]["fence"] == 1, applied
    reset_row = _effect_row(owner, host_effect)
    assert reset_row["status"] == "ready", reset_row
    assert reset_row["claim_owner"] is None and reset_row["lease_until"] is None
    assert reset_row["attempt_no"] == 1 and reset_row["fence"] == 1, reset_row
    stored_response = one(owner,
        "SELECT response::text FROM v24.requests WHERE request_key=%s", (request_key,))
    owner.rollback()
    assert stored_response == response_text

    # 1. same key + same canonical bytes -> byte-equal replay, zero new rows.
    replay, replay_before, replay_after = _w0(
        owner, lambda: _recover_text(admin, scope, request_key, 16),
        "same-key replay")
    assert replay[0] == response_text, (replay[0], response_text)
    assert replay[1] == response, replay
    assert _count(owner, "SELECT count(*) FROM v24.requests WHERE request_key=%s",
                  (request_key,)) == 1

    # 2. same key + different limit/scope -> request_conflict, zero writes.
    limit_conflict, _, _ = _w0(
        owner, lambda: _recover_text(admin, scope, request_key, 1),
        "different limit")
    assert limit_conflict[1] == {
        "v": 1, "error": {"code": "request_conflict", "detail": {}}}, limit_conflict
    other_scope = new_scope(admin, key + "-other-root")
    scope_conflict, _, _ = _w0(
        owner, lambda: _recover_text(admin, other_scope, request_key, 16),
        "different scope")
    assert scope_conflict[1] == {
        "v": 1, "error": {"code": "request_conflict", "detail": {}}}, scope_conflict

    # 3. same key + different candidates still replays the first response.
    extra = seed_claim(owner, scope, kind="host_prepare", lease_until=OLD)
    owner.commit()
    candidates, _, _ = _w0(
        owner, lambda: _recover_text(admin, scope, request_key, 16),
        "different candidates")
    assert candidates[0] == response_text, candidates
    assert _effect_row(owner, extra)["status"] == "claimed"
    assert _count(owner, "SELECT count(*) FROM v24.effects WHERE kind='command_recover' AND scope_id=%s",
                  (scope,)) == 1

    # 4. reset preserved attempt/fence; old token is stale; the ordinary claim
    #    is the only writer that bumps them.
    stale, _, _ = _w0(owner, lambda: _advance_commit(service, host_effect, {
        "v": 1, "class": "success", "claim": token,
        "body": {"kind": "host_prepare", "result": {"v": 1}}}),
        "old token settlement")
    assert stale == {"v": 1, "error": {"code": "stale_claim", "detail": {}}}, stale
    new_token = advance(service, host_effect, claim())["claim"]
    service.commit()
    assert new_token == {
        "attempt": 2, "fence": 2, "owner": token["owner"]}, new_token
    claimed_row = _effect_row(owner, host_effect)
    assert claimed_row["status"] == "claimed", claimed_row

    # 5. N3 limits and N1 service on an admin scope are both W0.
    for limit in (0, 17, None):
        refused, _, _ = _w0(owner,
                            lambda limit=limit: _recover_text(
                                admin, scope, key + f"-limit-{limit}", limit),
                            f"limit {limit}")
        assert refused[1] == {
            "v": 1, "error": {"code": "invalid_args", "detail": {}}}, refused
    denied, _, _ = _w0(owner, lambda: _recover_text(
        service, scope, key + "-service", 16), "service on admin scope")
    assert denied[1] == {
        "v": 1, "error": {"code": "not_found_or_denied", "detail": {}}}, denied

    # N9: has_more is a per-call hint, not a cursor.
    n9_scope = new_scope(admin, key + "-n9-root")
    seed_claim(owner, n9_scope, kind="host_prepare", lease_until=OLD)
    seed_claim(owner, n9_scope, kind="host_prepare", lease_until=OLD)
    owner.commit()
    first_text, first = _recover_text(admin, n9_scope, key + "-n9-a", 1)
    second_text, second = _recover_text(admin, n9_scope, key + "-n9-b", 1)
    assert len(first["recovery"]["applied"]) == 1 and first["recovery"]["has_more"] is True, first
    assert len(second["recovery"]["applied"]) == 1 and second["recovery"]["has_more"] is False, second
    assert first_text != second_text

    print(
        "[G5-W2] scope=%s admin_backend_pid=%d service_backend_pid=%d "
        "journal=n/a(contract-suite) replay=%s zero_write=%s/%s "
        "applied=%s conflict_limit=%s conflict_scope=%s candidates_replay=%s "
        "reset=ready/attempt1/fence1 stale=stale_claim-w0 "
        "next_claim=attempt2/fence2 limits=invalid_args-w0 "
        "service=not_found_or_denied-w0 has_more=%s->%s snapshot=%s"
        % (
            scope, admin_pid, service_pid,
            replay[1]["effect_id"] == response["effect_id"],
            replay_before == replay_after, replay_before,
            applied[host_effect]["action"],
            limit_conflict[1]["error"]["code"],
            scope_conflict[1]["error"]["code"],
            candidates[1]["effect_id"] == response["effect_id"],
            first["recovery"]["has_more"], second["recovery"]["has_more"],
            replay_before,
        )
    )


def _d1(owner, admin) -> str:
    scope = new_scope(admin, "g5-d1-root")
    expired = seed_claim(owner, scope, kind="host_prepare", lease_until=OLD)
    unexpired = seed_claim(owner, scope, kind="host_release", lease_until=FUTURE)
    succeeded = seed_claim(
        owner, scope, kind="host_prepare", status="succeeded",
        outcome={"ok": True}, settled_at=OLD,
    )
    wrong_kind = seed_claim(
        owner, scope, kind="fiber_reconcile", lease_until=OLD,
    )
    owner.commit()
    with owner.cursor() as cur:
        cur.execute("SELECT effect_id::text FROM v24.effects WHERE scope_id=%s", (scope,))
        seeded = {row[0] for row in cur.fetchall()}
    # new_scope's own create_root command effect also lives in this scope.
    assert {expired, unexpired, succeeded, wrong_kind} <= seeded, seeded
    assert len(seeded) == 5, seeded
    before = g5_snapshot(owner)
    rows = discover(admin, scope, 16)
    after = g5_snapshot(owner)
    assert _ids(rows) == [expired], rows
    assert before == after
    print(
        "[G5-D1] only claimed+expired survives: expired=%s unexpired/succeeded/"
        "wrong-kind excluded" % expired
    )
    return scope


def _d2(owner, admin) -> str:
    scope = new_scope(admin, "g5-d2-root")
    t1 = OLD
    t2 = OLD + timedelta(minutes=5)
    t3 = OLD + timedelta(minutes=10)
    a = UUID("00000000-0000-0000-0000-0000000000a1")
    b = UUID("00000000-0000-0000-0000-0000000000b2")
    c = UUID("00000000-0000-0000-0000-0000000000c3")
    d = UUID("00000000-0000-0000-0000-0000000000d4")
    seed_claim(owner, scope, effect_id=a, lease_until=t2)
    seed_claim(owner, scope, effect_id=b, lease_until=t1)
    seed_claim(owner, scope, effect_id=c, lease_until=t1)
    seed_claim(owner, scope, effect_id=d, lease_until=t3)
    owner.commit()
    rows = discover(admin, scope, 16)
    assert _ids(rows) == [str(b), str(c), str(a), str(d)], rows
    assert rows[0]["lease_until"] == rows[1]["lease_until"], rows
    assert rows[1]["lease_until"] < rows[2]["lease_until"] < rows[3]["lease_until"], rows
    print(
        "[G5-D2] order=(lease_until,effect_id): %s" % [row["effect_id"] for row in rows]
    )
    return scope


def _d3(owner, admin) -> str:
    scope = new_scope(admin, "g5-d3-root")
    expected = [str(UUID(int=value)) for value in range(1, 21)]
    for value in range(1, 21):
        seed_claim(owner, scope, effect_id=UUID(int=value), lease_until=OLD)
    owner.commit()
    assert discover(admin, scope, None) == []
    assert discover(admin, scope, 0) == []
    assert discover(admin, scope, -7) == []
    rows17 = discover(admin, scope, 17)
    assert len(rows17) == 16, rows17
    assert _ids(rows17) == expected[:16], rows17
    assert len(discover(admin, scope, 16)) == 16
    print("[G5-D3] limits NULL/0/-7/17/16 -> %d/%d/%d/%d/%d rows"
          % (0, 0, 0, len(rows17), 16))
    return scope


def _d4(owner, admin) -> str:
    scope = new_scope(admin, "g5-d4-root")
    manual = seed_claim(
        owner, scope, kind="host_prepare", replay_policy="manual", lease_until=OLD,
    )
    safe = seed_claim(
        owner, scope, kind="host_prepare", replay_policy="replay_safe", lease_until=OLD,
    )
    owner.commit()
    rows = discover(admin, scope, 16)
    assert _ids(rows) == [safe], rows
    assert manual not in _ids(rows)
    assert one(
        owner,
        "SELECT count(*) FROM v24.effects WHERE scope_id=%s AND replay_policy='manual'",
        (scope,),
    ) == 1
    print("[G5-D4] manual claim %s excluded; replay_safe %s returned" % (manual, safe))
    return scope


def _d5(owner, admin, service) -> str:
    scope = new_scope(admin, "g5-d5-root")
    effect_id = seed_claim(owner, scope, lease_until=OLD)
    owner.commit()
    assert _ids(discover(admin, scope, 16)) == [effect_id]
    assert discover(service, scope, 16) == []
    assert not one(
        service,
        "SELECT pg_catalog.pg_has_role(session_user, 'v24_admin', 'USAGE')",
    )
    print("[G5-D5] service sees 0 rows for an admin-created scope %s" % scope)
    return scope


def _d6(owner, admin, service, scopes, admin_scope) -> None:
    before = g5_snapshot(owner)
    before_fp = fingerprint(before)
    for scope in scopes:
        for limit in (None, 0, 1, 16, 17):
            discover(admin, scope, limit)
    assert discover(service, admin_scope, 16) == []
    after = g5_snapshot(owner)
    after_fp = fingerprint(after)
    assert before == after, (before_fp, after_fp)
    assert before_fp == after_fp
    print("[G5-D6] ten-table snapshot unchanged across every read: %s" % before_fp)


def discovery_suite(db, owner, admin, service) -> None:
    s1 = _d1(owner, admin)
    s2 = _d2(owner, admin)
    s3 = _d3(owner, admin)
    s4 = _d4(owner, admin)
    s5 = _d5(owner, admin, service)
    _d6(owner, admin, service, (s1, s2, s3, s4, s5), s5)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated windows; W4 implements %s" % ",".join(WINDOWS),
    )
    args = parser.parse_args(argv)
    requested = [item.strip() for item in args.only.split(",") if item.strip()]
    if not requested:
        requested = list(WINDOWS)
    unsupported = [item for item in requested if item not in WINDOWS]
    assert not unsupported, f"window(s) not implemented in W4: {unsupported}"

    _assert_no_network_imports()
    with server_helper_scope(), setup_db() as db:
        owner = db.connect()
        with owner.cursor() as cur:
            cur.execute("SET ROLE v24_owner")
        owner.commit()
        admin = db.connect("admin")
        service = db.connect("service")
        # K1 must run on the pristine fixture; the other windows are independent.
        if "K1" in requested:
            k1(db, owner)
        if "K2" in requested:
            k2(db, owner, admin, service)
        if "K3" in requested:
            k3(db, owner, admin, service)
        if "K4" in requested:
            k4(db, owner, admin)
        if "K5" in requested:
            k5(db, owner, admin)
        if "K6" in requested:
            k6(db, owner, admin, service)
        if "K7" in requested:
            k7(db, owner, admin, service)
        if "K8" in requested:
            k8(db, owner, admin, service)
        if "K9" in requested:
            k9(db, owner, admin, service)
        if "K10" in requested:
            k10(db, owner, admin, service)
        if set(W2_WINDOWS) & set(requested):
            w2_contract(db, owner, admin, service)
        discovery_suite(db, owner, admin, service)
        for connection in (admin, service):
            connection.rollback()
        _assert_closed_catalog(owner)
    print("[passed] v24 S6 W1-W4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
