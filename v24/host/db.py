"""Synchronous host RPC client for the frozen v24 public surface.

Exactly two connections are used:

* ``control`` - an admin or scope-owner LOGIN.  It may call the nine public
  ``v24.host_*`` readers and ``command_recover``.
* ``service`` - a ``v24_service`` LOGIN.  It may only claim and settle through
  ``v24.advance``.

Host code never reads an owner table.  Every method commits (or rolls back on
error) before returning, and the worker asserts both connections are IDLE
before any external I/O.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import psycopg2
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json

_SESSION_SETTINGS = (
    ("default_transaction_isolation", "read committed"),
    ("statement_timeout", "30s"),
    ("lock_timeout", "5s"),
    ("idle_in_transaction_session_timeout", "5s"),
)

_READS = {
    "host_scopes": "SELECT v24.host_scopes(%s,%s,%s)",
    "host_runs": "SELECT v24.host_runs(%s,%s,%s,%s)",
    "host_effects": "SELECT v24.host_effects(%s,%s,%s,%s)",
    "host_run_effects": "SELECT v24.host_run_effects(%s,%s,%s,%s)",
    "host_effect": "SELECT v24.host_effect(%s)",
    "host_scope_installs": "SELECT v24.host_scope_installs(%s,%s,%s)",
    "host_install_fibers": "SELECT v24.host_install_fibers(%s,%s,%s)",
    "host_run_pins": "SELECT v24.host_run_pins(%s,%s,%s)",
    "host_request": "SELECT v24.host_request(%s)",
}
_READ_ARGS = {
    "host_scopes": ("p_scope", "p_after", "p_limit"),
    "host_runs": ("p_scope", "p_after_created_at", "p_after_run_id", "p_limit"),
    "host_effects": ("p_scope", "p_after_created_at", "p_after_effect_id", "p_limit"),
    "host_run_effects": ("p_run", "p_after_created_at", "p_after_effect_id", "p_limit"),
    "host_effect": ("p_effect",),
    "host_scope_installs": ("p_scope", "p_after", "p_limit"),
    "host_install_fibers": ("p_install", "p_after", "p_limit"),
    "host_run_pins": ("p_run", "p_after", "p_limit"),
    "host_request": ("p_request_key",),
}
_ALLOWED_SQL_FUNCTIONS = frozenset({
    "v24.host_scopes", "v24.host_runs", "v24.host_effects",
    "v24.host_run_effects", "v24.host_effect", "v24.host_scope_installs",
    "v24.host_install_fibers", "v24.host_run_pins", "v24.host_request",
    "v24.advance", "v24.command_recover",
})


class HostDBError(RuntimeError):
    def __init__(self, response: dict):
        self.response = response
        error = response.get("error") if isinstance(response, dict) else None
        self.code = error.get("code") if isinstance(error, dict) else "unknown"
        super().__init__(f"v24 RPC error: {self.code}")


class HostContractError(RuntimeError):
    """A host-side precondition failed; no external I/O may follow."""


def _connect(source):
    if isinstance(source, str):
        conn = psycopg2.connect(source)
    else:
        conn = source
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute(
            "SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED")
        for name, value in _SESSION_SETTINGS:
            cur.execute(f"SET {name} = %s", (value,))
    conn.commit()
    return conn


class HostDB:
    def __init__(self, control, service):
        self.control = _connect(control)
        self.service = _connect(service)
        self.rpc_log: list[str] = []
        self._closed = False

    # -- lifecycle / contract -------------------------------------------
    @staticmethod
    def idle(conn) -> bool:
        return conn.get_transaction_status() == TRANSACTION_STATUS_IDLE

    def assert_all_idle(self) -> None:
        for name, conn in (("control", self.control), ("service", self.service)):
            if not self.idle(conn):
                raise HostContractError(
                    f"{name} connection is not IDLE before external I/O")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for conn in (self.control, self.service):
            try:
                if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                    conn.rollback()
            finally:
                conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # -- read surface ----------------------------------------------------
    def read(self, name: str, **kwargs) -> dict:
        if name not in _READS:
            raise HostContractError(f"not a public host read: {name}")
        params = [kwargs.get(arg) for arg in _READ_ARGS[name]]
        if len(params) != _READS[name].count("%s"):
            raise HostContractError(f"wrong argument count for {name}")
        value = self._call(self.control, _READS[name], tuple(params))
        self.rpc_log.append(name)
        if not isinstance(value, dict):
            raise HostContractError(f"{name} did not return an envelope")
        return value

    def host_scopes(self, scope=None, after=None, limit=64) -> dict:
        return self.read("host_scopes", p_scope=scope, p_after=after, p_limit=limit)

    def host_runs(self, scope, after_created_at=None, after_run_id=None,
                  limit=64) -> dict:
        return self.read("host_runs", p_scope=scope,
                         p_after_created_at=after_created_at,
                         p_after_run_id=after_run_id, p_limit=limit)

    def host_effects(self, scope, after_created_at=None, after_effect_id=None,
                     limit=64) -> dict:
        return self.read("host_effects", p_scope=scope,
                         p_after_created_at=after_created_at,
                         p_after_effect_id=after_effect_id, p_limit=limit)

    def host_run_effects(self, run, after_created_at=None, after_effect_id=None,
                         limit=64) -> dict:
        return self.read("host_run_effects", p_run=run,
                         p_after_created_at=after_created_at,
                         p_after_effect_id=after_effect_id, p_limit=limit)

    def host_effect(self, effect) -> dict:
        return self.read("host_effect", p_effect=effect)

    def host_scope_installs(self, scope, after=None, limit=64) -> dict:
        return self.read("host_scope_installs", p_scope=scope, p_after=after,
                         p_limit=limit)

    def host_install_fibers(self, install, after=None, limit=64) -> dict:
        return self.read("host_install_fibers", p_install=install, p_after=after,
                         p_limit=limit)

    def host_run_pins(self, run, after=None, limit=64) -> dict:
        return self.read("host_run_pins", p_run=run, p_after=after, p_limit=limit)

    def host_request(self, request_key) -> dict:
        return self.read("host_request", p_request_key=request_key)

    # -- write surface (service LOGIN only) ------------------------------
    def claim(self, effect_id, lease_ms: int) -> dict:
        if isinstance(lease_ms, bool) or not isinstance(lease_ms, int):
            raise HostContractError("lease_ms must be an integer")
        outcome = {"v": 1, "class": "claim", "claim": None,
                   "body": {"lease_ms": lease_ms}}
        value = self._call(self.service, "SELECT v24.advance(%s,%s)",
                           (effect_id, Json(outcome)))
        self.rpc_log.append("advance")
        return value

    def settle(self, effect_id, class_name: str, claim: dict, kind: str,
               result: dict) -> dict:
        if class_name not in ("success", "failure", "unknown"):
            raise HostContractError(f"invalid outcome class {class_name!r}")
        outcome = {"v": 1, "class": class_name, "claim": claim,
                   "body": {"kind": kind, "result": result}}
        value = self._call(self.service, "SELECT v24.advance(%s,%s)",
                           (effect_id, Json(outcome)))
        self.rpc_log.append("advance")
        return value

    def recover(self, scope, request_key: str, limit: int = 16) -> dict:
        value = self._call(
            self.control, "SELECT v24.command_recover(%s,%s,%s)",
            (scope, request_key, limit))
        self.rpc_log.append("command_recover")
        return value

    # -- scalar helpers --------------------------------------------------
    @staticmethod
    def remaining_lease_ms(lease_until) -> int:
        """Remaining lease from a host_effect timestamp, without another RPC."""
        if isinstance(lease_until, str):
            try:
                lease_until = datetime.fromisoformat(lease_until)
            except ValueError:
                return 0
        if not isinstance(lease_until, datetime):
            return 0
        if lease_until.tzinfo is None:
            lease_until = lease_until.replace(tzinfo=timezone.utc)
        return int((lease_until - datetime.now(timezone.utc)).total_seconds() * 1000)

    # -- internals -------------------------------------------------------
    def _call(self, conn, sql, params, *, many: bool = False, scalar: bool = False):
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if many:
                    value = [row[0] for row in cur.fetchall()]
                elif scalar or cur.description is None:
                    value = cur.fetchone()[0] if cur.description is not None else None
                else:
                    value = cur.fetchone()[0]
            conn.commit()
            return value
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            if conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
                try:
                    conn.rollback()
                except Exception:
                    pass


def is_error(response) -> bool:
    return isinstance(response, dict) and isinstance(response.get("error"), dict)


def error_code(response) -> str | None:
    if not is_error(response):
        return None
    return response["error"].get("code")


def require_ok(response) -> dict:
    if is_error(response):
        raise HostDBError(response)
    return response


def lease_requirement_ms(timeout_s: float) -> int:
    """Minimum remaining lease before an HTTP dispatch."""
    return int(math.ceil(timeout_s * 1000)) + 5000
