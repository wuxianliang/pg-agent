"""S6 crash child: drive one window to its named boundary, then block.

DSN, journal path and window arrive only through the environment.  READY is
written as one JSON line to V24_READY_FD; the process then blocks until one
byte arrives on V24_GO_FD.  The parent SIGKILLs this process at the boundary.

K1 is the W1 pre-COMMIT command window.  W2 adds the committed-claim windows:
K2 (claim committed, before IO), K3 (host IO done, before settlement), K8
(install preparing/host_prepare IO done) and K10 (host release CAS done).
W3 adds the S5 lifecycle boundaries: K6 (provider retire starts, then stops at
the live consumer pin), K7 (child subtree disposed, parent retire unfinished)
and K9 (scope closing with prepare_unknown and an unquiesced host effect).
W4 adds K4 (a fixture-only SQL error injected on the request insert: the child
catches P0001, rolls back and exits) and K5 (command_recover committed, the
response deliberately never sent; the child reports COMMITTED and blocks for
the parent's SIGKILL).  K4 is the only window that exits without a kill: the
error injection itself is the recovery boundary.
"""
from __future__ import annotations

import base64
import json
import os
import sys

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE, TRANSACTION_STATUS_INTRANS
from psycopg2.extras import Json

from fake_crash_host import CrashHost

KIND = "command_scope_control"


def _require(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        raise SystemExit(f"missing {name}")
    return value


def _one(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchone()[0]


def k1_payload() -> dict:
    # Exactly the payload v24.scope_control constructs for create_root.
    return {"action": "create_root", "realm_routes": {}, "default_realm": None}


def issue(conn, request_key: str):
    """W1 K1: call the ordinary command wrapper inside an open transaction."""
    payload = k1_payload()
    effect_id = _one(
        conn,
        "SELECT v24.effect_id_for(v24.principal_id(session_user), %s, %s)",
        (request_key, KIND),
    )
    canonical = _one(
        conn,
        "SELECT encode(convert_to(v24.canonical_json(%s), 'UTF8'), 'base64')",
        (Json(payload),),
    )
    response = _one(
        conn,
        "SELECT v24.scope_control('create_root', NULL, %s, NULL, %s)",
        (Json({}), request_key),
    )
    if response.get("disposition") != "committed":
        raise SystemExit(f"command did not commit in the child: {response}")
    return effect_id, canonical, response


def run_k4(conn, request_key: str) -> dict:
    """K4: the ordinary command dies on the injected request-insert P0001.

    The effect id and canonical bytes are computed before the call, exactly as
    K1 does.  The fault fires after the domain/effect writes and before the
    request row, so only a real ROLLBACK can leave the snapshot untouched.  The
    child never continues inside the aborted transaction: after the rollback it
    re-checks that the backend is idle before reporting READY.
    """
    payload = k1_payload()
    effect_id = _one(
        conn,
        "SELECT v24.effect_id_for(v24.principal_id(session_user), %s, %s)",
        (request_key, KIND),
    )
    canonical = _one(
        conn,
        "SELECT encode(convert_to(v24.canonical_json(%s), 'UTF8'), 'base64')",
        (Json(payload),),
    )
    try:
        _one(
            conn,
            "SELECT v24.scope_control('create_root', NULL, %s, NULL, %s)",
            (Json({}), request_key),
        )
    except psycopg2.Error as exc:
        sqlstate = exc.pgcode
        if sqlstate != "P0001":
            raise
        message = str(exc).strip()
        conn.rollback()
        if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
            raise SystemExit("K4 rollback did not return the backend to idle")
        return {
            "phase": "rolled_back",
            "tx_status": "idle",
            "request_key": request_key,
            "effect_id": str(effect_id),
            "canonical_bytes": canonical,
            "sqlstate": sqlstate,
            "error": message,
        }
    raise SystemExit("K4 injection did not fire on the request insert")


def run_k5(conn, scope_id: str, request_key: str, limit: int) -> dict:
    """K5: command_recover commits, then the response is deliberately dropped.

    Only the one-word disposition is read back (never the response payload).
    The full response stays committed in v24.requests; the parent reconstructs
    it after SIGKILL and compares every replay with it byte-for-byte.
    """
    canonical = _one(
        conn,
        "SELECT encode(convert_to(v24.canonical_json(%s), 'UTF8'), 'base64')",
        (Json({"v": 1, "scope_id": scope_id, "limit": limit}),),
    )
    disposition = _one(
        conn,
        "SELECT v24.command_recover(%s::uuid, %s, %s)->>'disposition'",
        (scope_id, request_key, limit),
    )
    if disposition != "committed":
        raise SystemExit(f"K5 command_recover did not commit: {disposition!r}")
    conn.commit()
    if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
        raise SystemExit("K5 command_recover did not commit")
    return {
        "phase": "committed",
        "tx_status": "idle",
        "scope_id": scope_id,
        "request_key": request_key,
        "limit": limit,
        "canonical_bytes": canonical,
        "disposition": disposition,
    }


def _claim(conn, effect_id: str, lease_ms: int):
    response = _one(conn, "SELECT v24.advance(%s, %s)", (effect_id, Json({
        "v": 1, "class": "claim", "claim": None,
        "body": {"lease_ms": lease_ms},
    })))
    if response.get("claim") is None:
        raise SystemExit(f"claim did not commit in the child: {response}")
    return response["claim"]


def _manifest_bytes(identity: str) -> bytes:
    return json.dumps({
        "identity": identity, "version": "1", "requires": [],
        "provides": [{"realm": "s6", "key": identity}],
        "adapter_digest": "\\x",
    }).encode("utf-8")


def run_k1(conn, request_key: str) -> dict:
    effect_id, canonical, response = issue(conn, request_key)
    if conn.get_transaction_status() != TRANSACTION_STATUS_INTRANS:
        raise SystemExit("named boundary is not inside an open transaction")
    return {
        "tx_status": "intrans",
        "request_key": request_key,
        "effect_id": str(effect_id),
        "canonical_bytes": canonical,
        "response": response,
    }


def run_claims(conn, host: CrashHost, window: str, lease_ms: int) -> dict:
    """K2/K3: claim the replay_safe host effect and the no_replay model effect."""
    host_effect = _require("V24_HOST_EFFECT_ID")
    model_effect = _require("V24_MODEL_EFFECT_ID")
    host_token = _claim(conn, host_effect, lease_ms)
    model_token = _claim(conn, model_effect, lease_ms)
    conn.commit()
    ready = {
        "tx_status": "idle",
        "scope_id": _require("V24_SCOPE_ID"),
        "host_effect_id": host_effect,
        "host_token": host_token,
        "model_effect_id": model_effect,
        "model_token": model_token,
    }
    if window == "K3":
        # The host IO (journal + JSONL) completes before the crash; the model
        # receipt is deliberately never written.
        ready["host_receipt"] = host.prepare(conn, host_effect, host_token)
    return ready


def _admit_install_admin(conn, scope_id: str, identity: str, request_key: str):
    """Admin-side admission for an admin-owned scope (the wrapper is service-only)."""
    payload = {
        "scope_id": scope_id,
        "owner_fiber_id": None,
        "manifest_bytes": base64.b64encode(_manifest_bytes(identity)).decode("ascii"),
        "artifact_digest": "\\x",
    }
    effect_id = _one(
        conn,
        "SELECT v24.effect_id_for(v24.principal_id(session_user), %s, 'command_install')",
        (request_key,),
    )
    canonical = _one(
        conn,
        "SELECT encode(convert_to(v24.canonical_json(%s), 'UTF8'), 'base64')",
        (Json(payload),),
    )
    outcome = {
        "v": 1, "class": "command", "claim": None,
        "body": {"op": "admit_and_apply", "kind": "command_install",
                 "request_key": request_key, "payload": payload,
                 "canonical_bytes": canonical},
    }
    return _one(conn, "SELECT v24.advance(%s, %s)", (effect_id, Json(outcome)))


def run_k8(conn, admin, host: CrashHost, lease_ms: int) -> dict:
    """K8: install is preparing, host_prepare is claimed, IO is journaled."""
    scope_id = _require("V24_SCOPE_ID")
    identity = _require("V24_INSTALL_IDENTITY")
    response = _admit_install_admin(
        admin, scope_id, identity, _require("V24_INSTALL_KEY"))
    admin.commit()
    if response.get("disposition") != "committed" or len(response["emitted"]) != 2:
        raise SystemExit(f"install admission failed in the child: {response}")
    install_id, host_effect = response["emitted"]
    token = _claim(conn, host_effect, lease_ms)
    conn.commit()
    return {
        "tx_status": "idle",
        "scope_id": scope_id,
        "install_id": install_id,
        "host_effect_id": host_effect,
        "host_token": token,
        "host_receipt": host.prepare(conn, host_effect, token),
    }


def run_k10(conn, host: CrashHost, lease_ms: int, lost: bool) -> dict:
    """K10: dispose_pending, host_release claimed, release CAS already done."""
    install_id = _require("V24_INSTALL_ID")
    response = _one(
        conn,
        "SELECT v24.dispose(%s, %s)",
        (install_id, _require("V24_DISPOSE_KEY")),
    )
    if response.get("disposition") != "committed" or not response["emitted"]:
        raise SystemExit(f"dispose failed in the child: {response}")
    release_id = response["emitted"][0]
    token = _claim(conn, release_id, lease_ms)
    conn.commit()
    return {
        "tx_status": "idle",
        "scope_id": _require("V24_SCOPE_ID"),
        "install_id": install_id,
        "host_effect_id": release_id,
        "host_token": token,
        "host_receipt": host.release(
            conn, release_id, token, action="succeed", lost=lost),
    }


def _fiber_action(conn, owner, fiber_id: str, action: str, key: str) -> dict:
    control_seq = _one(
        owner, "SELECT control_seq FROM v24.fibers WHERE fiber_id=%s", (fiber_id,))
    response = _one(
        conn, "SELECT v24.fiber_control(%s,%s,%s,%s)",
        (fiber_id, action, control_seq, key))
    if response.get("disposition") not in ("committed", "deferred"):
        raise SystemExit(f"fiber_control failed in the child: {response}")
    return response


def run_k6(conn, admin, owner) -> dict:
    """K6: the provider retire starts and stops at the live consumer pin."""
    provider_fiber = _require("V24_PROVIDER_FIBER_ID")
    response = _fiber_action(
        admin, owner, provider_fiber, "off", _require("V24_WITHDRAW_KEY"))
    admin.commit()
    # The service connection's backend_pid read opened a transaction this
    # window never uses; leave it idle before READY.
    conn.rollback()
    return {
        "tx_status": "idle",
        "scope_id": _require("V24_SCOPE_ID"),
        "provider_fiber_id": provider_fiber,
        "withdraw": response,
    }


def run_k7(conn, admin, owner, host: CrashHost, lease_ms: int) -> dict:
    """K7: the child subtree is disposed; the parent retire is still incomplete."""
    child_install = _require("V24_CHILD_INSTALL_ID")
    child_fiber = _require("V24_CHILD_FIBER_ID")
    off = _fiber_action(
        admin, owner, child_fiber, "off", _require("V24_CHILD_OFF_KEY"))
    admin.commit()
    dispose = _one(
        admin, "SELECT v24.dispose(%s,%s)::text",
        (child_install, _require("V24_CHILD_DISPOSE_KEY")))
    admin.commit()
    dispose = json.loads(dispose)
    if dispose.get("disposition") != "committed" or not dispose["emitted"]:
        raise SystemExit(f"child dispose failed in the child: {dispose}")
    release_id = dispose["emitted"][0]
    token = _claim(conn, release_id, lease_ms)
    conn.commit()
    receipt = host.release(conn, release_id, token)
    settled = _one(
        conn, "SELECT v24.advance(%s,%s)", (release_id, Json(receipt)))
    conn.commit()
    if settled.get("disposition") != "committed":
        raise SystemExit(f"child release settlement failed: {settled}")
    return {
        "tx_status": "idle",
        "scope_id": _require("V24_SCOPE_ID"),
        "install_id": child_install,
        "child_fiber_id": child_fiber,
        "child_off": off,
        "dispose": dispose,
        "release_effect_id": release_id,
        "release_token": token,
        "release_receipt": receipt,
    }


def run_k9(conn, admin, lease_ms: int) -> dict:
    """K9: close requested, install prepare_unknown, host_prepare unknown."""
    scope_id = _require("V24_SCOPE_ID")
    admitted = _admit_install_admin(
        admin, scope_id, _require("V24_INSTALL_IDENTITY"),
        _require("V24_INSTALL_KEY"))
    admin.commit()
    if (admitted.get("disposition") != "committed"
            or len(admitted.get("emitted", [])) != 2):
        raise SystemExit(f"install admission failed in the child: {admitted}")
    install_id, host_effect = admitted["emitted"]
    token = _claim(conn, host_effect, lease_ms)
    conn.commit()
    outcome = {
        "v": 1, "class": "unknown", "claim": token,
        "body": {"kind": "host_prepare",
                 "result": {"v": 1, "observed": "unknown"}},
    }
    settled = _one(
        conn, "SELECT v24.advance(%s,%s)", (host_effect, Json(outcome)))
    conn.commit()
    if settled.get("disposition") != "committed":
        raise SystemExit(f"host_prepare unknown failed in the child: {settled}")
    close = _one(
        admin, "SELECT v24.scope_control('close',%s,NULL,NULL,%s)",
        (scope_id, _require("V24_CLOSE_KEY")))
    admin.commit()
    if close.get("disposition") != "committed":
        raise SystemExit(f"scope close request failed in the child: {close}")
    return {
        "tx_status": "idle",
        "scope_id": scope_id,
        "install_id": install_id,
        "host_effect_id": host_effect,
        "host_token": token,
        "close": close,
    }


def main() -> int:
    window = _require("V24_WINDOW")
    dsn = _require("V24_DSN")
    journal = _require("V24_JOURNAL")
    ready_fd = int(_require("V24_READY_FD"))
    go_fd = int(_require("V24_GO_FD"))
    lease_ms = int(os.environ.get("V24_LEASE_MS", "300000"))

    if window in ("K1", "K4", "K5"):
        conn = psycopg2.connect(dsn)
        conn.autocommit = False
        try:
            backend_pid = _one(conn, "SELECT pg_catalog.pg_backend_pid()")
            request_key = _require("V24_REQUEST_KEY")
            if window == "K1":
                ready = run_k1(conn, request_key)
            elif window == "K4":
                ready = run_k4(conn, request_key)
            else:
                ready = run_k5(
                    conn,
                    _require("V24_SCOPE_ID"),
                    request_key,
                    int(os.environ.get("V24_LIMIT", "16")),
                )
            ready.update(window=window, os_pid=os.getpid(),
                         backend_pid=backend_pid)
            os.write(ready_fd, (json.dumps(ready, sort_keys=True) + "\n").encode("utf-8"))
            if window == "K4":
                # The injected SQL error was the boundary; the rollback is
                # complete and there is no commit to race with.  Exit cleanly.
                return 0
            # The parent kills this process here.  A go byte is only for
            # windows that must commit; reaching it means the kill raced past
            # the boundary.
            go = os.read(go_fd, 1)
            if go != b"g":
                raise SystemExit("go pipe closed without a byte")
            if window == "K1":
                conn.commit()
                print(json.dumps({"committed": str(ready["effect_id"])}, sort_keys=True))
            return 0
        finally:
            conn.close()

    if window not in ("K2", "K3", "K6", "K7", "K8", "K9", "K10", "K10b"):
        raise SystemExit(f"window {window} is not implemented in W4")

    owner_dsn = _require("V24_OWNER_DSN")
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    journal_conn = psycopg2.connect(owner_dsn)
    journal_conn.autocommit = True
    host = CrashHost(journal_conn, journal, window)
    admin = None
    try:
        backend_pid = _one(conn, "SELECT pg_catalog.pg_backend_pid()")
        if window == "K8":
            # The admin login owns the scope and admits the install; the
            # service login performs the claim and the host action.
            admin = psycopg2.connect(_require("V24_ADMIN_DSN"))
            admin.autocommit = False
            ready = run_k8(conn, admin, host, lease_ms)
        elif window in ("K2", "K3"):
            ready = run_claims(conn, host, window, lease_ms)
        elif window == "K6":
            admin = psycopg2.connect(_require("V24_ADMIN_DSN"))
            admin.autocommit = False
            ready = run_k6(conn, admin, journal_conn)
        elif window == "K7":
            admin = psycopg2.connect(_require("V24_ADMIN_DSN"))
            admin.autocommit = False
            ready = run_k7(conn, admin, journal_conn, host, lease_ms)
        elif window == "K9":
            admin = psycopg2.connect(_require("V24_ADMIN_DSN"))
            admin.autocommit = False
            ready = run_k9(conn, admin, lease_ms)
        else:
            ready = run_k10(conn, host, lease_ms, lost=(window == "K10b"))
        if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
            raise SystemExit("named window did not commit before READY")
        ready.update(window=window, os_pid=os.getpid(), backend_pid=backend_pid)
        os.write(ready_fd, (json.dumps(ready, sort_keys=True) + "\n").encode("utf-8"))
        go = os.read(go_fd, 1)
        if go != b"g":
            raise SystemExit("go pipe closed without a byte")
        return 0
    finally:
        conn.close()
        journal_conn.close()
        if admin is not None:
            admin.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        print(f"[crash-worker] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
