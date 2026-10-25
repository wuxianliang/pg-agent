"""Small deterministic model and fakes for the v24 fair-worker checks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4


class FakeJournal:
    def __init__(self, records=None):
        self.records = list(records or [])
        self._seq = len(self.records)

    def append(self, event_type, effect_id, digest, payload, *, run_id=None, claim=None):
        self._seq += 1
        record = {"v": 1, "seq": self._seq, "event_type": event_type,
                  "effect_id": str(effect_id), "request_digest": digest,
                  "claim": claim, "payload": payload}
        if run_id is not None:
            record["run_id"] = run_id
        self.records.append(record)
        return record

    def has(self, event_type, effect_id):
        return any(r["event_type"] == event_type and str(r["effect_id"]) == str(effect_id)
                   for r in self.records)

    def last(self, event_type, effect_id):
        for record in reversed(self.records):
            if record["event_type"] == event_type and str(record["effect_id"]) == str(effect_id):
                return record
        return None

    def records_for(self, effect_id):
        return [r for r in self.records if str(r["effect_id"]) == str(effect_id)]

    def prepared_without_dispatch(self):
        prepared = {str(r["effect_id"]) for r in self.records if r["event_type"] == "effect_prepared"}
        started = {str(r["effect_id"]) for r in self.records if r["event_type"] == "dispatch_started"}
        settled = {str(r["effect_id"]) for r in self.records if r["event_type"] == "settlement_committed"}
        return [x for x in prepared if x not in started | settled]

    def pending_settlements(self):
        finished = {str(r["effect_id"]) for r in self.records if r["event_type"] == "dispatch_finished"}
        settled = {str(r["effect_id"]) for r in self.records if r["event_type"] == "settlement_committed"}
        return [x for x in finished if x not in settled]

    def unfinished_dispatches(self):
        started = {str(r["effect_id"]) for r in self.records if r["event_type"] == "dispatch_started"}
        finished = {str(r["effect_id"]) for r in self.records if r["event_type"] == "dispatch_finished"}
        return [x for x in started if x not in finished]


class FakeDB:
    def __init__(self, scopes, effects, *, deferred_once=()):
        self.scopes = sorted({str(x) for x in scopes}, key=UUID)
        self.effects = {str(e["effect_id"]): dict(e) for e in effects}
        self.deferred = set(map(str, deferred_once))
        self.rpc_log = []
        self._clock = datetime.now(timezone.utc)

    def assert_all_idle(self):
        return None

    def host_scopes(self, scope=None, after=None, limit=64):
        self.rpc_log.append("host_scopes")
        values = [x for x in self.scopes if after is None or UUID(x) > UUID(str(after))]
        page = values[:limit]
        return {"v": 1, "items": [{"scope_id": x} for x in page], "limit": limit,
                "has_more": len(values) > len(page),
                "next_cursor": {"scope_id": page[-1]} if len(values) > len(page) else None}

    def host_effects(self, scope, after_created_at=None, after_effect_id=None, limit=64):
        self.rpc_log.append("host_effects")
        values = [e for e in self.effects.values()
                  if str(e["scope_id"]) == str(scope)
                  and e["status"] in ("ready", "claimed")]
        values.sort(key=lambda e: (e["created_at"], str(e["effect_id"])))
        if after_created_at is not None:
            values = [e for e in values if (e["created_at"], str(e["effect_id"])) >
                      (after_created_at, str(after_effect_id))]
        page = values[:limit]
        return {"v": 1, "items": [dict(e) for e in page], "limit": limit,
                "has_more": len(values) > len(page),
                "next_cursor": {"created_at": page[-1]["created_at"],
                                "effect_id": page[-1]["effect_id"]}
                if len(values) > len(page) else None}

    def host_effect(self, effect_id):
        self.rpc_log.append("host_effect")
        e = self.effects.get(str(effect_id))
        if e is None:
            return {"v": 1, "error": {"code": "not_found_or_denied"}}
        return {"v": 1, "effect": dict(e)}

    def claim(self, effect_id, lease_ms):
        self.rpc_log.append("advance")
        e = self.effects[str(effect_id)]
        if str(effect_id) in self.deferred:
            self.deferred.remove(str(effect_id))
            return {"v": 1, "disposition": "deferred", "effect_id": str(effect_id),
                    "claim": None}
        if e["status"] != "ready":
            return {"v": 1, "error": {"code": "invalid_args"}}
        e["status"] = "claimed"
        e["attempt_no"] += 1
        e["fence"] += 1
        e["claim_owner"] = "fake-worker"
        e["lease_until"] = self._clock + timedelta(milliseconds=lease_ms)
        token = {"attempt": e["attempt_no"], "fence": e["fence"], "owner": e["claim_owner"]}
        return {"v": 1, "disposition": "committed", "effect_id": str(effect_id), "claim": token}

    def settle(self, effect_id, class_name, claim, kind, result):
        self.rpc_log.append("advance")
        e = self.effects[str(effect_id)]
        e["status"] = {"success": "succeeded", "failure": "failed", "unknown": "unknown"}[class_name]
        e["outcome"] = {"class": class_name, "body": {"kind": kind, "result": result}}
        return {"v": 1, "disposition": "committed", "effect_id": str(effect_id)}

    def recover(self, scope, request_key, limit=16):
        self.rpc_log.append("command_recover")
        return {"v": 1, "disposition": "committed", "recovery":
                {"scope_id": str(scope), "limit": limit, "candidates": [],
                 "applied": [], "skipped": [], "manual_debt": 0, "has_more": False}}

    @staticmethod
    def remaining_lease_ms(lease_until):
        if isinstance(lease_until, str):
            lease_until = datetime.fromisoformat(lease_until)
        return int((lease_until - datetime.now(timezone.utc)).total_seconds() * 1000)


def effect(scope, *, kind="host_prepare", ordinal=0, created_at=None):
    effect_id = str(uuid4())
    return {"effect_id": effect_id, "scope_id": str(scope), "run_id": None,
            "kind": kind, "status": "ready", "replay_policy": "replay_safe",
            "attempt_no": 0, "fence": 0, "claim_owner": None,
            "lease_until": None, "request": {"ordinal": ordinal},
            "created_at": created_at or "2026-01-01T00:00:00+00:00",
            "outcome": None}


def fresh_scope():
    return str(uuid4())


def reference_choice(host_ids, business_ids, streak, cursor):
    """Independent finite reference rule: lists are already ordered IDs."""
    if business_ids and (not host_ids or streak == 3):
        klass, ids, next_streak = "business", business_ids, 0
    elif host_ids:
        klass, ids, next_streak = "host", host_ids, min(3, streak + 1)
    else:
        return None, None, streak
    # Reference uses index rotation; production compares ordering-key anchors.
    index = 0
    if cursor in ids:
        index = (ids.index(cursor) + 1) % len(ids)
    elif cursor is not None:
        index = next((i for i, value in enumerate(ids) if value > cursor), 0)
    return klass, ids[index], next_streak
