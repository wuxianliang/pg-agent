"""DB-only proof that one installed provider supplies two live run pins."""
from __future__ import annotations

import base64
import hashlib
import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

S1 = Path(__file__).resolve().parents[1] / "s1"
S2 = Path(__file__).resolve().parents[1] / "s2"
for _path in (S1, S2):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from setup_db import server_helper_scope, setup_db  # noqa: E402
from test_g3a import advance, command, one  # noqa: E402
from v24.host.db import HostDB, error_code  # noqa: E402
from v24.host.registry import pg_jsonb_text  # noqa: E402


def _manifest(identity: str, provides: list[dict]) -> bytes:
    return json.dumps(
        {
            "identity": identity,
            "version": "1",
            "requires": [],
            "provides": provides,
            "adapter_digest": "\\x",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _descriptor(label: str) -> dict:
    return {
        "v": 1,
        "tool": {
            "description": f"B0 multi-provides {label}",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }


def _assert_ok(response, label: str) -> dict:
    code = error_code(response)
    assert code is None, f"{label}: {code}; disposition={response.get('disposition')}"
    return response


def _new_root(admin, realm: str, request_key: str):
    response = one(admin, "SELECT v24.scope_control('create_root',NULL,'{}',%s,%s)",
                   (realm, request_key))
    assert response.get("disposition") == "committed", response
    admin.commit()
    return response["emitted"][0]


def _install(admin, scope_id, request_key: str, provides: list[dict]):
    identity = f"v24.b0.multi.{uuid4()}"
    manifest = _manifest(identity, provides)
    effect_id, outcome = command(admin, request_key, "command_install", {
        "scope_id": str(scope_id),
        "owner_fiber_id": None,
        "manifest_bytes": base64.b64encode(manifest).decode("ascii"),
        "artifact_digest": "\\x",
    })
    response = advance(admin, effect_id, outcome)
    _assert_ok(response, "command_install")
    admin.commit()
    install_id = response["emitted"][0]
    return install_id, manifest


def _effect_id(owner, install_id, kind: str):
    effect_id = one(
        owner,
        "SELECT effect_id FROM v24.effects WHERE kind=%s AND request->>'install_id'=%s",
        (kind, str(install_id)),
    )
    owner.rollback()
    assert effect_id is not None, (install_id, kind)
    return effect_id


def _activate(admin, owner, host_db: HostDB, install_id):
    effect_id = _effect_id(owner, install_id, "host_prepare")
    claim = host_db.claim(effect_id, 30000)
    _assert_ok(claim, "host_prepare claim")
    token = claim.get("claim")
    assert token is not None, claim
    settled = host_db.settle(effect_id, "success", token, "host_prepare", {})
    _assert_ok(settled, "host_prepare settle")
    fiber_id = one(owner, "SELECT fiber_id FROM v24.fibers WHERE install_id=%s", (install_id,))
    owner.rollback()
    assert fiber_id is not None, install_id
    activated = one(admin, "SELECT v24.fiber_control(%s,'on',0,%s)",
                    (fiber_id, f"b0-on-{uuid4()}"))
    assert activated.get("disposition") == "committed", activated
    admin.commit()
    assert activated.get("emitted"), activated
    episode_id = activated["emitted"][0]
    return fiber_id, episode_id


def _bytea_hex(value) -> str:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, str):
        return value[2:] if value.startswith("\\x") else value
    raise AssertionError(f"unexpected bytea representation: {type(value).__name__}")


def _slots(owner, fiber_id):
    rows = one(
        owner,
        """SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.contribution_seq), '[]'::jsonb)
             FROM v24.slots s
            WHERE s.fiber_id=%s AND s.released_at IS NULL AND s.withdrawn_at IS NULL""",
        (fiber_id,),
    )
    owner.rollback()
    return rows


def _start(admin, scope_id, owner_fiber_id, request_key: str, keys: tuple[str, ...]):
    payload = {"requires": [{"key": key} for key in keys]}
    with admin.cursor() as cur:
        cur.execute(
            "SELECT v24.start(%s,%s,%s,%s,%s)",
            (scope_id, owner_fiber_id, json.dumps(payload),
             json.dumps({"steps": 2, "tool_calls": 2, "tokens": 1000, "wall_ms": 60000}),
             request_key),
        )
        response = cur.fetchone()[0]
    admin.commit()
    return response


def _positive(db):
    admin = db.connect("admin")
    owner = db.connect("owner")
    host_db = HostDB(db.role_dsn("admin"), db.role_dsn("service"))
    try:
        realm = f"b0-positive-{uuid4().hex}"
        scope_id = _new_root(admin, realm, f"b0-root-{uuid4()}")
        descriptors = {key: _descriptor(key) for key in ("k0", "k1")}
        provides = [
            {"realm": realm, "key": key, "descriptor": descriptors[key]}
            for key in ("k0", "k1")
        ]
        install_id, _manifest_bytes = _install(
            admin, scope_id, f"b0-install-{uuid4()}", provides)
        fiber_id, episode_id = _activate(admin, owner, host_db, install_id)

        slots = _slots(owner, fiber_id)
        assert len(slots) == 2, slots
        assert [slot["key"] for slot in slots] == ["k0", "k1"], slots
        assert [slot["contribution_seq"] for slot in slots] == [0, 1], slots
        assert {slot["realm"] for slot in slots} == {realm}, slots
        assert [slot["descriptor"] for slot in slots] == [descriptors["k0"], descriptors["k1"]], slots
        expected_digests = {
            key: hashlib.sha256(pg_jsonb_text(descriptors[key]).encode("utf-8")).hexdigest()
            for key in ("k0", "k1")
        }
        actual_digests = {
            slot["key"]: _bytea_hex(slot["descriptor_digest"]) for slot in slots
        }
        assert actual_digests == expected_digests, (actual_digests, expected_digests)
        assert len(set(actual_digests.values())) == 2, actual_digests
        assert {str(slot["episode_id"]) for slot in slots} == {str(episode_id)}, slots

        resolved = one(
            owner,
            """SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.key), '[]'::jsonb)
                 FROM v24.resolve(%s, ARRAY['k0','k1']::text[]) r""",
            (scope_id,),
        )
        owner.rollback()
        assert [row["key"] for row in resolved] == ["k0", "k1"], resolved
        assert {str(row["slot_id"]) for row in resolved} == {str(slot["slot_id"]) for slot in slots}, resolved

        # Public start; do not run model, worker, or tool processing.
        start = _start(admin, scope_id, fiber_id,
                       f"b0-start-{uuid4()}", ("k0", "k1"))
        _assert_ok(start, "start")
        run_id = start["emitted"][0]
        pins_response = host_db.host_run_pins(run_id)
        _assert_ok(pins_response, "host_run_pins")
        pins = pins_response.get("items")
        assert isinstance(pins, list) and len(pins) == 2, pins_response
        by_key = {pin["key"]: pin for pin in pins}
        assert set(by_key) == {"k0", "k1"}, pins
        slots_by_key = {slot["key"]: slot for slot in slots}
        for key, pin in by_key.items():
            slot = slots_by_key[key]
            assert str(pin["slot_id"]) == str(slot["slot_id"]), pin
            assert str(pin["provider_fiber_id"]) == str(fiber_id), pin
            assert str(pin["provider_episode_id"]) == str(episode_id), pin
            assert str(pin["provider_install_id"]) == str(install_id), pin
            assert pin["descriptor"] == descriptors[key], pin
            assert pin["descriptor_digest"] == expected_digests[key], pin
            assert pin["consumer_type"] == "run" and pin["consumer_run_id"] == str(run_id), pin
            assert pin["consumer_epoch"] == 1 and pin["released_at"] is None, pin
        print("[pass] positive: one install -> two live slots -> one run -> two matching pins")
    finally:
        host_db.close()
        owner.close()
        admin.close()


def _negative_realm(db):
    admin = db.connect("admin")
    owner = db.connect("owner")
    host_db = HostDB(db.role_dsn("admin"), db.role_dsn("service"))
    try:
        realm = f"b0-negative-{uuid4().hex}"
        other_realm = realm + "-other"
        scope_id = _new_root(admin, realm, f"b0-neg-root-{uuid4()}")
        provides = [
            {"realm": realm, "key": "k0", "descriptor": _descriptor("negative-k0")},
            {"realm": other_realm, "key": "k1", "descriptor": _descriptor("negative-k1")},
        ]
        install_id, _manifest_bytes = _install(
            admin, scope_id, f"b0-neg-install-{uuid4()}", provides)
        fiber_id, _episode_id = _activate(admin, owner, host_db, install_id)
        slots = _slots(owner, fiber_id)
        assert {slot["key"] for slot in slots} == {"k0", "k1"}, slots
        start = _start(admin, scope_id, fiber_id, f"b0-neg-start-{uuid4()}", ("k0", "k1"))
        assert error_code(start) == "dependency_unresolved", start
        assert not start.get("emitted"), start
        runs = host_db.host_runs(scope_id)
        _assert_ok(runs, "negative host_runs")
        assert not any(run.get("request_key", "").startswith("b0-neg-start-") for run in runs.get("items", [])), runs
        # Explicit owner reads confirm the failed request left neither a run nor run pins.
        run_count = one(owner, "SELECT count(*) FROM v24.runs WHERE scope_id=%s", (scope_id,))
        owner.rollback()
        assert run_count == 0, run_count
        run_pin_count = one(
            owner,
            """SELECT count(*) FROM v24.pins p
                 JOIN v24.runs r ON r.run_id=p.consumer_run_id
                WHERE p.consumer_type='run' AND r.scope_id=%s""",
            (scope_id,),
        )
        owner.rollback()
        assert run_pin_count == 0, run_pin_count
        print("[pass] negative: cross-realm requirement is unresolved; no run or pin")
    finally:
        host_db.close()
        owner.close()
        admin.close()


def _deny_network(*_args, **_kwargs):
    raise AssertionError("B0 DB-only probe attempted to open a network socket")


def _deny_process(calls, *_args, **_kwargs):
    calls.append(1)
    raise AssertionError("B0 DB-only probe attempted to spawn a process")


def main() -> int:
    # The probe uses pgembed's Unix socket for PostgreSQL, but no Internet/TCP
    # socket and no plugin process. Guard Python network entry points after the
    # local DB helper has been provisioned.
    with server_helper_scope():
        db = setup_db()
        process_calls = []
        try:
            with patch.object(socket.socket, "connect", _deny_network), \
                 patch.object(socket, "create_connection", _deny_network), \
                 patch("v24.host.line_json.run_process",
                       side_effect=lambda *args, **kwargs: _deny_process(process_calls, *args, **kwargs)), \
                 patch("v24.host.process_io.run_process",
                       side_effect=lambda *args, **kwargs: _deny_process(process_calls, *args, **kwargs)):
                _positive(db)
                _negative_realm(db)
        finally:
            try:
                db.close()
            finally:
                assert len(process_calls) == 0, f"process sentinel called {len(process_calls)} time(s)"
    print("[pass] B0-2 DB-only multi-provides probe; zero process spawns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
