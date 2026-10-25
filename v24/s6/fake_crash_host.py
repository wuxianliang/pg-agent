"""Fixture-only crash host for the v24 S6 windows.

``prepare``/``release``/``inspect`` share one durable journal: a reservation
that already has a journal row returns that first result and never performs a
second external action.  Every step is appended to a JSONL file with ``fsync``
and mirrored into ``v24_fake.journal``.  The module opens no sockets, reads no
clock beyond timestamps, never sleeps and never uses randomness.

There is no public recovery path here: the class only simulates the trusted
host side of the crash windows, exactly like ``v24/s1/fake_host.py``.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone

from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json

ACTIONS = ("succeed", "fail", "unknown")
CLASS_OF = {"succeed": "success", "fail": "failure", "unknown": "unknown"}
UNFINISHED = {"class": "unknown", "result": "unfinished_journal"}


class HostCrash(RuntimeError):
    """Scripted host crash marker (kept for FakeHost-compatible callers)."""


def append_jsonl(path, record: dict) -> None:
    """Append one JSON line and fsync it; the writer is the only ordering source."""
    line = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


class CrashHost:
    """Journaled host: reservation reuse first, external action at most once."""

    def __init__(self, journal_conn, journal_path, window: str):
        if not journal_conn.autocommit:
            raise ValueError("CrashHost journal connection must be autocommit")
        self.journal = journal_conn
        self.path = str(journal_path)
        self.window = window

    # -- evidence ---------------------------------------------------------
    def _record(self, op, action, effect_id, token, reservation, result, **extra):
        append_jsonl(self.path, {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "window": self.window,
            "op": op,
            "action": action,
            "effect_id": str(effect_id),
            "attempt": token["attempt"],
            "fence": token["fence"],
            "reservation": reservation,
            "result": result,
            **extra,
        })

    @staticmethod
    def _receipt(token, result):
        return {"v": 1, "class": result["class"], "claim": deepcopy(token),
                "body": {"result": result["result"]}}

    # -- claim/request validation ----------------------------------------
    def _claimed(self, worker_conn, effect_id, token, kind):
        if worker_conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
            raise RuntimeError("CrashHost requires claim COMMIT and an idle worker connection")
        if self.journal.get_transaction_status() != TRANSACTION_STATUS_IDLE:
            raise RuntimeError("CrashHost journal connection must be idle")
        with self.journal.cursor() as cur:
            cur.execute(
                """SELECT kind, status, attempt_no, fence, claim_owner, request
                     FROM v24.effects WHERE effect_id=%s""",
                (str(effect_id),),
            )
            row = cur.fetchone()
        if row is None or row[:5] != (
            kind, "claimed", token["attempt"], token["fence"], token["owner"],
        ):
            raise RuntimeError(f"CrashHost requires a committed matching {kind} claim")
        request = row[5]
        if kind == "inspect_resource":
            reservation = request.get("target_reservation")
            if not isinstance(reservation, str) or not reservation.startswith(
                f"v24:{request.get('target')}:"
            ):
                raise ValueError("inspect request must carry its target reservation")
        else:
            reservation = request.get("reservation")
            if reservation != f"v24:{kind}:{effect_id}":
                raise ValueError("reservation must be bound to the effect id")
        return request, reservation

    def _prior(self, op, reservation):
        with self.journal.cursor() as cur:
            cur.execute(
                """SELECT id, effect_id::text, op, payload, result
                     FROM v24_fake.journal
                    WHERE payload->>'reservation'=%s AND op=%s
                    ORDER BY id LIMIT 1""",
                (reservation, op),
            )
            return cur.fetchone()

    def _insert(self, effect_id, attempt, fence, op, payload):
        with self.journal.cursor() as cur:
            cur.execute(
                """INSERT INTO v24_fake.journal(effect_id, attempt, fence, op, payload)
                   VALUES(%s,%s,%s,%s,%s) RETURNING id""",
                (str(effect_id), attempt, fence, op, Json(payload)),
            )
            return cur.fetchone()[0]

    def _finish(self, journal_id, result):
        with self.journal.cursor() as cur:
            cur.execute(
                """UPDATE v24_fake.journal SET result=%s, finished_at=clock_timestamp()
                    WHERE id=%s""",
                (Json(result), journal_id),
            )

    # -- public host operations ------------------------------------------
    def prepare(self, worker_conn, effect_id, token, action="succeed"):
        if action not in ACTIONS:
            raise ValueError(f"unsupported crash-host action: {action}")
        request, reservation = self._claimed(
            worker_conn, effect_id, token, "host_prepare")
        result = self._act(effect_id, token, "host_prepare", reservation, request,
                           {"class": CLASS_OF[action], "result": action})
        return self._receipt(token, result)

    def release(self, worker_conn, effect_id, token, action="succeed", lost=False):
        if action not in ACTIONS:
            raise ValueError(f"unsupported crash-host action: {action}")
        request, reservation = self._claimed(
            worker_conn, effect_id, token, "host_release")
        result = self._act(effect_id, token, "host_release", reservation, request,
                           {"class": CLASS_OF[action], "result": action}, lost=lost)
        return self._receipt(token, result)

    def inspect(self, worker_conn, effect_id, token):
        request, reservation = self._claimed(
            worker_conn, effect_id, token, "inspect_resource")
        result = self._act(
            effect_id, token, "inspect_resource", reservation,
            {"reservation": reservation, "install_id": request.get("install_id"),
             "target": request.get("target"),
             "target_effect_id": request.get("target_effect_id")},
            self._inspect_result(effect_id, token, request, reservation),
        )
        receipt = self._receipt(token, result)
        receipt["body"] = {"kind": "inspect_resource", "result": result["result"]}
        return receipt

    def _inspect_result(self, effect_id, token, request, reservation):
        # A release journal row proves the CAS was attempted; the fixture treats
        # the reservation as observed-known and records the same target bytes.
        with self.journal.cursor() as cur:
            cur.execute(
                """SELECT count(*) FROM v24_fake.journal
                    WHERE payload->>'reservation'=%s AND op=%s""",
                (reservation, request["target"]),
            )
            known = cur.fetchone()[0] > 0
        return {
            "class": "success",
            "result": {
                "v": 1,
                "observed": "known" if known else "absent",
                "target_effect_id": str(request["target_effect_id"]),
                "target_reservation": reservation,
            },
        }

    # -- shared journal protocol -----------------------------------------
    def _act(self, effect_id, token, op, reservation, payload, result, lost=False):
        prior = self._prior(op, reservation)
        if prior is not None:
            if prior[1] != str(effect_id):
                raise ValueError("reservation payload conflict")
            stored = prior[4] or UNFINISHED
            self._record(op, "reuse", effect_id, token, reservation,
                         stored, prior_journal_id=prior[0])
            return stored
        # The started line is durable before the simulated external action.
        self._record(op, "started", effect_id, token, reservation, None)
        journal_id = self._insert(
            effect_id, token["attempt"], token["fence"], op, payload)
        if lost:
            # CAS may have happened; the durable result was not recorded.
            return UNFINISHED
        self._finish(journal_id, result)
        self._record(op, "finished", effect_id, token, reservation, result)
        return result
