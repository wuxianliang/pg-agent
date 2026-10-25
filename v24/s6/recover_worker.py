"""S6 recovery process: a fresh OS process that converges one window.

K1 re-submits the pre-COMMIT command with the same effect id, request key and
canonical bytes; K4 repeats exactly that submission after the injected SQL
error and its rollback.  W2 windows first call the read-only resolver, then the
single ``command_recover`` entry point, then replay the trusted host reservation
under a fresh ordinary claim.  K5 only replays an already committed
``command_recover`` request: one invocation compares the returned response with
the committed request row and commits no write.
No recovery state is created outside the ten tables.

Three login connections are opened for the W2 windows plus the recovery-command
connection: owner (snapshot reads and the fake host journal), admin (the scope
owner, the only principal allowed to sweep an admin scope) and service (claims
and settlements).  The journal connection is the owner login in autocommit mode.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import Json

from fake_crash_host import CrashHost, append_jsonl
from g5_support import fingerprint, g5_snapshot, snapshot_diff

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


def _row(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchone()


def _all(conn, statement, params=()):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        columns = [column[0] for column in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def _claim(conn, effect_id: str, lease_ms: int = 300000):
    response = _one(conn, "SELECT v24.advance(%s, %s)", (effect_id, Json({
        "v": 1, "class": "claim", "claim": None,
        "body": {"lease_ms": lease_ms},
    })))
    if response.get("claim") is None:
        raise SystemExit(f"recovery claim did not commit: {response}")
    return response["claim"]


def _advance(conn, effect_id: str, outcome: dict):
    response = _one(conn, "SELECT v24.advance(%s, %s)", (effect_id, Json(outcome)))
    conn.commit()
    if response.get("disposition") != "committed" or "error" in response:
        raise SystemExit(f"recovery settlement did not commit: {response}")
    return response


def k1_payload() -> dict:
    return {"action": "create_root", "realm_routes": {}, "default_realm": None}


def submit_k1(conn, request_key: str):
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
    expected_id = _require("V24_EFFECT_ID")
    expected_bytes = _require("V24_CANONICAL_BYTES")
    if str(effect_id) != expected_id:
        raise SystemExit(f"effect id changed across restart: {effect_id} != {expected_id}")
    if canonical != expected_bytes:
        raise SystemExit("canonical bytes changed across restart")
    response = _one(
        conn,
        "SELECT v24.scope_control('create_root', NULL, %s, NULL, %s)",
        (Json({}), request_key),
    )
    if response.get("disposition") != "committed":
        raise SystemExit(f"recovery command did not commit: {response}")
    return effect_id, canonical, response


def run_k1(service, window: str) -> dict:
    request_key = _require("V24_REQUEST_KEY")
    with service.cursor() as cur:
        cur.execute("SET statement_timeout = '30s'")
    backend_pid = _one(service, "SELECT pg_catalog.pg_backend_pid()")
    effect_id, canonical, response = submit_k1(service, request_key)
    service.commit()
    return {
        "window": window,
        "os_pid": os.getpid(),
        "backend_pid": backend_pid,
        "request_key": request_key,
        "effect_id": str(effect_id),
        "canonical_bytes": canonical,
        "response": response,
    }


def run_k5(admin, owner, window: str) -> dict:
    """K5: one fresh process replays a committed command_recover request.

    The canonical bytes are recomputed from ``{v,scope_id,limit}`` and must
    equal the request row's bytes.  The call itself must be a byte-for-byte
    replay: the snapshot before and after this transaction is identical and
    the response equals the first committed response.
    """
    scope_id = _require("V24_SCOPE_ID")
    request_key = _require("V24_REQUEST_KEY")
    limit = int(os.environ.get("V24_LIMIT", "16"))
    canonical = _one(
        admin,
        "SELECT encode(convert_to(v24.canonical_json(%s), 'UTF8'), 'base64')",
        (Json({"v": 1, "scope_id": scope_id, "limit": limit}),),
    )
    expected_bytes = _require("V24_CANONICAL_BYTES")
    if canonical != expected_bytes:
        raise SystemExit("K5 canonical bytes changed across restart")

    owner.rollback()
    admin.rollback()
    request_row = _row(
        owner,
        """SELECT encode(request_bytes, 'base64'), effect_id::text
             FROM v24.requests
            WHERE request_key=%s AND kind='command_recover'""",
        (request_key,),
    )
    owner.rollback()
    if request_row is None:
        raise SystemExit("K5 committed request row is missing")
    request_bytes, recovery_effect = request_row
    if request_bytes != canonical:
        raise SystemExit("K5 request_bytes differ from the canonical bytes")

    before = g5_snapshot(owner)
    owner.rollback()
    before_fp = fingerprint(before)
    backend_pid = _one(admin, "SELECT pg_catalog.pg_backend_pid()")
    response_text = _one(
        admin,
        "SELECT v24.command_recover(%s::uuid, %s, %s)::text",
        (scope_id, request_key, limit),
    )
    admin.commit()
    owner.rollback()
    after = g5_snapshot(owner)
    owner.rollback()
    after_fp = fingerprint(after)

    response = json.loads(response_text)
    stable = json.dumps(response, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False)
    stable_bytes = stable.encode("utf-8")
    owner.rollback()
    counts = {
        "requests": _one(
            owner, "SELECT count(*) FROM v24.requests WHERE request_key=%s",
            (request_key,)),
        "effects": _one(
            owner,
            "SELECT count(*) FROM v24.effects "
            "WHERE request_key=%s AND kind='command_recover'", (request_key,)),
        "events": _one(
            owner, "SELECT count(*) FROM v24.events WHERE effect_id=%s",
            (recovery_effect,)),
        "successors": _one(
            owner, "SELECT count(*) FROM v24.effects WHERE parent_effect_id=%s",
            (recovery_effect,)),
    }
    owner.rollback()
    return {
        "window": window,
        "os_pid": os.getpid(),
        "backend_pid": backend_pid,
        "replay_index": int(os.environ.get("V24_REPLAY_INDEX", "1")),
        "scope_id": scope_id,
        "request_key": request_key,
        "limit": limit,
        "canonical_bytes": canonical,
        "request_bytes": request_bytes,
        "effect_id": recovery_effect,
        "response": response,
        "response_text": stable,
        "response_sha256": hashlib.sha256(stable_bytes).hexdigest(),
        "response_bytes": len(stable_bytes),
        "before": before_fp,
        "after": after_fp,
        "snapshot_unchanged": before == after,
        "counts": counts,
    }


def _recovery_metrics(owner, scope_id, reservation):
    owner.rollback()
    with owner.cursor() as cur:
        cur.execute(
            """SELECT count(*), coalesce(max(attempt),0), coalesce(max(fence),0)
                 FROM v24_fake.journal WHERE payload->>'reservation'=%s""",
            (reservation,),
        )
        journal_rows, journal_attempt, journal_fence = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM v24.effects WHERE kind='command_recover' AND scope_id=%s",
            (scope_id,),
        )
        recovery_effects = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM v24.effects WHERE scope_id=%s", (scope_id,))
        effects = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM v24.requests WHERE kind='command_recover'")
        recovery_requests = cur.fetchone()[0]
    owner.rollback()
    return {
        "journal_rows": journal_rows,
        "journal_attempt": journal_attempt,
        "journal_fence": journal_fence,
        "recovery_effects": recovery_effects,
        "recovery_requests": recovery_requests,
        "effects": effects,
    }


def run_window(owner, admin, service, host: CrashHost, window: str) -> dict:
    scope_id = _require("V24_SCOPE_ID")
    host_effect = _require("V24_HOST_EFFECT_ID")
    recover_key = _require("V24_RECOVER_KEY")
    owner.rollback()
    if not service.autocommit:
        service.rollback()
    for conn in (owner, admin, service):
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '60s'")
    admin_backend = _one(admin, "SELECT pg_catalog.pg_backend_pid()")
    service_backend = _one(service, "SELECT pg_catalog.pg_backend_pid()")

    # 1. The only discovery entry for restart: resolve(scope, keys).
    keys = _one(
        owner,
        """SELECT coalesce(array_agg(value->>'key'), '{}'::text[])
             FROM v24.installs i, jsonb_array_elements(i.requires) value
            WHERE i.scope_id=%s""",
        (scope_id,),
    )
    owner.rollback()
    with service.cursor() as cur:
        cur.execute("SELECT key, slot_id::text, live FROM v24.resolve(%s, %s)",
                    (scope_id, keys))
        resolved = [{"key": row[0], "slot_id": row[1], "live": row[2]}
                    for row in cur.fetchall()]
    service.rollback()

    # 2. K8 first proves activation is refused while the install is preparing.
    refused = None
    if window == "K8":
        install_id = _one(
            owner,
            "SELECT request->>'install_id' FROM v24.effects WHERE effect_id=%s",
            (host_effect,),
        )
        owner.rollback()
        fiber_id, control_seq = _row(
            owner,
            "SELECT f.fiber_id::text, f.control_seq FROM v24.fibers f WHERE f.install_id=%s",
            (install_id,),
        )
        owner.rollback()
        before = g5_snapshot(owner)
        owner.rollback()
        refused_text = _one(
            service,
            "SELECT v24.fiber_control(%s::uuid,'on',%s,%s)::text",
            (fiber_id, control_seq, _require("V24_REFUSED_KEY")),
        )
        service.commit()
        after = g5_snapshot(owner)
        owner.rollback()
        refused = {
            "fiber_id": fiber_id,
            "expected_control_seq": control_seq,
            "response": json.loads(refused_text),
            "before": fingerprint(before),
            "after": fingerprint(after),
            "diff": snapshot_diff(before, after),
        }

    # 3. The single recovery command: one request, one receipt, one delta.
    recovery_text = _one(
        admin,
        "SELECT v24.command_recover(%s, %s, 16)::text",
        (scope_id, recover_key),
    )
    admin.commit()
    recovery = json.loads(recovery_text)
    if recovery.get("disposition") != "committed" or "recovery" not in recovery:
        raise SystemExit(f"command_recover did not commit: {recovery}")
    append_jsonl(_require("V24_JOURNAL"), {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "window": window,
        "op": "recover",
        "action": "command_recover",
        "effect_id": recovery["effect_id"],
        "attempt": 0,
        "fence": 0,
        "reservation": None,
        "result": {
            "applied": len(recovery["recovery"]["applied"]),
            "has_more": recovery["recovery"]["has_more"],
            "manual_debt": recovery["recovery"]["manual_debt"],
        },
    })

    # 4. Replay the trusted host reservation under a fresh ordinary claim.
    host_after = None
    inspect = None
    activation = None
    install_id = _one(
        owner,
        "SELECT request->>'install_id' FROM v24.effects WHERE effect_id=%s",
        (host_effect,),
    )
    owner.rollback()
    host_token = _claim(service, host_effect)
    service.commit()
    if window in ("K2", "K3", "K8"):
        receipt = host.prepare(service, host_effect, host_token)
    else:
        receipt = host.release(service, host_effect, host_token)
    settled = _advance(service, host_effect, receipt)
    host_after = {
        "token": host_token,
        "receipt": receipt,
        "settle": settled,
    }
    if window == "K10b":
        # The durable result was never recorded: inspect the same reservation,
        # never issue a second release.
        release_request = _one(
            owner, "SELECT request FROM v24.effects WHERE effect_id=%s", (host_effect,))
        owner.rollback()
        dispose = _one(
            service,
            "SELECT v24.dispose(%s, %s)::text",
            (install_id, _require("V24_INSPECT_DISPOSE_KEY")),
        )
        service.commit()
        dispose = json.loads(dispose)
        if dispose.get("disposition") != "committed" or not dispose["emitted"]:
            raise SystemExit(f"inspect dispose did not commit: {dispose}")
        inspect_effect = dispose["emitted"][0]
        inspect_request = _one(
            owner, "SELECT request FROM v24.effects WHERE effect_id=%s", (inspect_effect,))
        owner.rollback()
        if inspect_request["target_reservation"] != release_request["reservation"]:
            raise SystemExit("inspect target reservation differs from the release")
        inspect_token = _claim(service, inspect_effect)
        service.commit()
        inspect_receipt = host.inspect(service, inspect_effect, inspect_token)
        inspect_settle = _advance(service, inspect_effect, inspect_receipt)
        inspect = {
            "effect_id": inspect_effect,
            "dispose": dispose,
            "request": inspect_request,
            "token": inspect_token,
            "receipt": inspect_receipt,
            "settle": inspect_settle,
        }
    if window == "K8":
        fiber_id, control_seq = _row(
            owner,
            "SELECT f.fiber_id::text, f.control_seq FROM v24.fibers f WHERE f.install_id=%s",
            (install_id,),
        )
        owner.rollback()
        activation_text = _one(
            service,
            "SELECT v24.fiber_control(%s::uuid,'on',%s,%s)::text",
            (fiber_id, control_seq, _require("V24_ACTIVATION_KEY")),
        )
        service.commit()
        activation = json.loads(activation_text)

    manual = None
    manual2 = None
    if window == "K3" and os.environ.get("V24_MANUAL_SCOPE"):
        for label, key_name in (("manual", "V24_MANUAL_KEY"),
                                ("manual2", "V24_MANUAL_KEY2")):
            text = _one(
                admin, "SELECT v24.command_recover(%s,%s,16)::text",
                (os.environ["V24_MANUAL_SCOPE"], _require(key_name)))
            admin.commit()
            response = json.loads(text)
            if response.get("disposition") != "committed":
                raise SystemExit(f"manual sweep did not commit: {response}")
            if label == "manual":
                manual = response
            else:
                manual2 = response

    owner.rollback()
    host_request = _one(
        owner, "SELECT request FROM v24.effects WHERE effect_id=%s", (host_effect,))
    owner.rollback()
    reservation = host_request.get("reservation") or host_request.get("target_reservation")
    metrics = _recovery_metrics(owner, scope_id, reservation)
    final = g5_snapshot(owner)
    owner.rollback()
    return {
        "window": window,
        "os_pid": os.getpid(),
        "backend_pid": admin_backend,
        "service_backend_pid": service_backend,
        "scope_id": scope_id,
        "install_id": install_id,
        "host_effect_id": host_effect,
        "reservation": reservation,
        "resolve": resolved,
        "recover": recovery,
        "recover_text": recovery_text,
        "refused": refused,
        "host": host_after,
        "inspect": inspect,
        "activation": activation,
        "manual": manual,
        "manual2": manual2,
        "metrics": metrics,
        "snapshot": fingerprint(final),
    }


def _fiber_action(admin, owner, fiber_id: str, key: str) -> dict:
    control_seq = _one(
        owner, "SELECT control_seq FROM v24.fibers WHERE fiber_id=%s", (fiber_id,))
    owner.rollback()
    text = _one(
        admin, "SELECT v24.fiber_control(%s,'off',%s,%s)::text",
        (fiber_id, control_seq, key))
    admin.commit()
    response = json.loads(text)
    if response.get("disposition") not in ("committed", "deferred") or "error" in response:
        raise SystemExit(f"fiber_control failed in recovery: {response}")
    return response


def _scope_close(admin, scope_id: str, key: str) -> dict:
    text = _one(
        admin, "SELECT v24.scope_control('close',%s,NULL,NULL,%s)::text",
        (scope_id, key))
    admin.commit()
    response = json.loads(text)
    if "error" in response:
        raise SystemExit(f"scope close failed in recovery: {response}")
    return response


def _execute_emitted(owner, service, host, effect_ids) -> list[dict]:
    executed = []
    for effect_id in effect_ids:
        owner.rollback()
        kind = _one(owner, "SELECT kind FROM v24.effects WHERE effect_id=%s",
                    (effect_id,))
        if kind == "inspect_resource":
            token = _claim(service, effect_id)
            service.commit()
            receipt = host.inspect(service, effect_id, token)
        elif kind == "host_release":
            token = _claim(service, effect_id)
            service.commit()
            receipt = host.release(service, effect_id, token)
        else:
            raise SystemExit(f"close emitted unsupported effect kind: {kind}")
        settled = _advance(service, effect_id, receipt)
        executed.append({
            "effect_id": effect_id, "kind": kind, "token": token,
            "receipt": receipt, "settle": settled,
        })
    return executed


def run_lifecycle(owner, admin, service, host: CrashHost, window: str) -> dict:
    """K6/K7/K9: resolve, the noop recovery sweep, then new-key lifecycle work."""
    scope_id = _require("V24_SCOPE_ID")
    recover_key = _require("V24_RECOVER_KEY")
    owner.rollback()
    for conn in (owner, admin, service):
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '60s'")
    admin_backend = _one(admin, "SELECT pg_catalog.pg_backend_pid()")
    service_backend = _one(service, "SELECT pg_catalog.pg_backend_pid()")
    owner.rollback()

    keys = _one(
        owner,
        """SELECT coalesce(array_agg(value->>'key'), '{}'::text[])
             FROM v24.installs i, jsonb_array_elements(i.requires) value
            WHERE i.scope_id=%s""",
        (scope_id,),
    )
    owner.rollback()
    with service.cursor() as cur:
        cur.execute("SELECT key, slot_id::text, live FROM v24.resolve(%s, %s)",
                    (scope_id, keys))
        resolved = [{"key": row[0], "slot_id": row[1], "live": row[2]}
                    for row in cur.fetchall()]
    service.rollback()

    recovery_text = _one(
        admin, "SELECT v24.command_recover(%s, %s, 16)::text",
        (scope_id, recover_key))
    admin.commit()
    recovery = json.loads(recovery_text)
    if recovery.get("disposition") != "committed" or "recovery" not in recovery:
        raise SystemExit(f"lifecycle command_recover did not commit: {recovery}")
    append_jsonl(_require("V24_JOURNAL"), {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "window": window,
        "op": "recover",
        "action": "command_recover",
        "effect_id": recovery["effect_id"],
        "attempt": 0,
        "fence": 0,
        "reservation": None,
        "result": {
            "applied": len(recovery["recovery"]["applied"]),
            "has_more": recovery["recovery"]["has_more"],
            "manual_debt": recovery["recovery"]["manual_debt"],
        },
    })

    def record_control(label: str, response: dict) -> None:
        append_jsonl(_require("V24_JOURNAL"), {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "window": window,
            "op": "fiber_control",
            "action": "off",
            "label": label,
            "effect_id": response.get("effect_id"),
            "attempt": 0,
            "fence": 0,
            "reservation": None,
            "result": {
                "disposition": response.get("disposition"),
                "emitted": response.get("emitted"),
            },
        })

    actions: dict = {}
    if window == "K6":
        actions["consumer"] = _fiber_action(
            admin, owner, _require("V24_CONSUMER_FIBER_ID"),
            recover_key + ":consumer")
        record_control("consumer", actions["consumer"])
        actions["provider"] = _fiber_action(
            admin, owner, _require("V24_PROVIDER_FIBER_ID"),
            recover_key + ":provider")
        record_control("provider", actions["provider"])
    elif window == "K7":
        actions["parent"] = _fiber_action(
            admin, owner, _require("V24_PARENT_FIBER_ID"), recover_key + ":parent")
        record_control("parent", actions["parent"])
    elif window == "K9":
        steps = []
        closed_at = None
        for index in range(16):
            response = _scope_close(
                admin, scope_id, recover_key + f":close:{index}")
            executed = _execute_emitted(
                owner, service, host, response.get("emitted") or [])
            owner.rollback()
            scope_row = _row(
                owner, "SELECT close_requested_at, closed_at FROM v24.scopes "
                       "WHERE scope_id=%s", (scope_id,))
            owner.rollback()
            install_rows = [
                {
                    "install_id": row["install_id"],
                    "state": row["state"],
                    "disposed_at": (row["disposed_at"].isoformat()
                                    if row["disposed_at"] is not None else None),
                }
                for row in _all(
                    owner,
                    """SELECT install_id::text, state, disposed_at
                         FROM v24.installs WHERE scope_id=%s
                         ORDER BY install_id""",
                    (scope_id,))
            ]
            owner.rollback()
            steps.append({
                "index": index,
                "response": response,
                "executed": executed,
                "close_requested_at": scope_row[0].isoformat() if scope_row[0] else None,
                "closed_at": scope_row[1].isoformat() if scope_row[1] else None,
                "installs": install_rows,
            })
            closed_at = scope_row[1]
            if closed_at is not None:
                break
        if closed_at is None:
            raise SystemExit("scope close did not converge within 16 keys")
        actions["steps"] = steps
    else:
        raise SystemExit(f"window {window} is not a lifecycle window")

    owner.rollback()
    metrics = {
        "recovery_effects": _one(
            owner, "SELECT count(*) FROM v24.effects "
                   "WHERE kind='command_recover' AND scope_id=%s", (scope_id,)),
        "effects": _one(
            owner, "SELECT count(*) FROM v24.effects WHERE scope_id=%s",
            (scope_id,)),
        "command_scope_control": _one(
            owner, "SELECT count(*) FROM v24.effects "
                   "WHERE kind='command_scope_control' AND scope_id=%s",
            (scope_id,)),
    }
    owner.rollback()
    final = g5_snapshot(owner)
    owner.rollback()
    return {
        "window": window,
        "os_pid": os.getpid(),
        "backend_pid": admin_backend,
        "service_backend_pid": service_backend,
        "scope_id": scope_id,
        "resolve": resolved,
        "recover": recovery,
        "recover_text": recovery_text,
        "actions": actions,
        "metrics": metrics,
        "snapshot": fingerprint(final),
    }


def main() -> int:
    window = _require("V24_WINDOW")
    dsn = _require("V24_DSN")
    _require("V24_JOURNAL")

    if window in ("K1", "K4"):
        service = psycopg2.connect(dsn)
        service.autocommit = False
        try:
            result = run_k1(service, window)
            print(json.dumps(result, sort_keys=True))
            return 0
        finally:
            service.close()

    if window == "K5":
        admin = psycopg2.connect(dsn)
        owner = psycopg2.connect(_require("V24_OWNER_DSN"))
        admin.autocommit = False
        owner.autocommit = False
        try:
            result = run_k5(admin, owner, window)
            print(json.dumps(result, sort_keys=True))
            return 0
        finally:
            owner.close()
            admin.close()

    if window not in ("K2", "K3", "K6", "K7", "K8", "K9", "K10", "K10b"):
        raise SystemExit(f"window {window} is not implemented in W4")

    owner = psycopg2.connect(_require("V24_OWNER_DSN"))
    admin = psycopg2.connect(_require("V24_ADMIN_DSN"))
    service = psycopg2.connect(dsn)
    journal = psycopg2.connect(_require("V24_OWNER_DSN"))
    journal.autocommit = True
    owner.autocommit = False
    admin.autocommit = False
    service.autocommit = False
    host = CrashHost(journal, _require("V24_JOURNAL"), window)
    try:
        if window in ("K6", "K7", "K9"):
            result = run_lifecycle(owner, admin, service, host, window)
        else:
            result = run_window(owner, admin, service, host, window)
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        for conn in (journal, service, admin, owner):
            conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        print(f"[recover-worker] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
