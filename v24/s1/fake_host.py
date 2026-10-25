"""In-process scripted host; receives existing DB handles, opens no sockets.

The worker connection must be idle (claim COMMIT completed). The separate,
fixture-owner journal connection must be autocommit. Each journal SQL statement
finishes before the simulated IO executes; domain settlement is a later advance.
Reservation retries reuse the first result; unfinished journals remain unknown.
"""
from __future__ import annotations

from copy import deepcopy

from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import Json


class HostCrash(RuntimeError):
    pass


class FakeHost:
    OUTCOMES = frozenset({"succeed", "fail", "unknown", "crash_before_journal", "crash_after_journal"})

    def __init__(self, journal_conn, script):
        if not journal_conn.autocommit:
            raise ValueError("FakeHost journal connection must be autocommit")
        self.journal = journal_conn
        self.script = iter(script)

    def prepare(self, worker_conn, effect_id, token):
        if worker_conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
            raise RuntimeError("FakeHost requires claim COMMIT and an idle worker connection")
        if self.journal.get_transaction_status() != TRANSACTION_STATUS_IDLE:
            raise RuntimeError("FakeHost journal connection must be idle")
        # Read through another connection: uncommitted qualification is invisible.
        with self.journal.cursor() as cur:
            cur.execute("SELECT kind,status,attempt_no,fence,claim_owner,request FROM v24.effects WHERE effect_id=%s", (effect_id,))
            row = cur.fetchone()
        if row is None or row[:5] != ("host_prepare", "claimed", token["attempt"], token["fence"], token["owner"]):
            raise RuntimeError("FakeHost requires a committed matching host_prepare claim")
        payload = row[5]
        if payload.get("reservation") != f"v24:host_prepare:{effect_id}":
            raise ValueError("reservation must be bound to the effect id")
        with self.journal.cursor() as cur:
            cur.execute("SELECT id,effect_id::text,op,payload,result FROM v24_fake.journal WHERE payload->>'reservation'=%s", (payload["reservation"],))
            previous = cur.fetchone()
        if previous:
            if previous[1:4] != (str(effect_id), "host_prepare", payload):
                raise ValueError("reservation payload conflict")
            result = previous[4] or {"class": "unknown", "result": "unfinished_journal"}
        else:
            action = next(self.script)
            if action not in self.OUTCOMES:
                raise ValueError(f"unsupported FakeHost action: {action}")
            if action == "crash_before_journal":
                raise HostCrash(action)
            with self.journal.cursor() as cur:
                cur.execute("""INSERT INTO v24_fake.journal(effect_id,attempt,fence,op,payload)
                    VALUES(%s,%s,%s,'host_prepare',%s) RETURNING id""",
                    (effect_id, token["attempt"], token["fence"], Json(payload)))
                journal_id = cur.fetchone()[0]
            if action == "crash_after_journal":
                raise HostCrash(action)
            # This is the simulated external operation. Both connections are idle.
            assert worker_conn.get_transaction_status() == TRANSACTION_STATUS_IDLE
            assert self.journal.get_transaction_status() == TRANSACTION_STATUS_IDLE
            result = {"class": {"succeed": "success", "fail": "failure", "unknown": "unknown"}[action], "result": action}
            with self.journal.cursor() as cur:
                cur.execute("UPDATE v24_fake.journal SET result=%s,finished_at=clock_timestamp() WHERE id=%s", (Json(result), journal_id))
        return {"v": 1, "class": result["class"], "claim": deepcopy(token), "body": {"result": result["result"]}}
