"""Single-threaded v24 host worker.

One process, at most one in-flight effect.  It reconciles the durable journal
before touching new work, discovers ready work only through the nine public
host readers, claims/settles only through the service login, and never permits
external I/O while a database transaction is open.

Ordering per round (plan M-R):

1. resubmit a journaled outcome whose database claim is still the same token;
2. if an orphan dispatch is still inside its lease, isolate it and do not sweep;
3. otherwise perform at most one ``command_recover`` sweep;
4. discover ready external effects, host resources before model/tool, same
   class by effect UUID; claim one, re-read it, then execute exactly once.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from uuid import uuid4

from v15.provider.errors import ProviderRejected, ProviderUncertain

from .db import HostDBError, is_error
from .deepseek import AdapterFailure, DeepSeekAdapter
from .journal import HostJournal, canonical_json, request_digest

HOST_KINDS = ("host_prepare", "host_release", "inspect_resource")
MODEL_KINDS = ("model_call",)
EXTERNAL_KINDS = HOST_KINDS + ("model_call", "tool_call")
_NOTHING = object()


class HostCrash(RuntimeError):
    """Scripted crash marker used by the extension check."""


@dataclass
class RoundStats:
    rounds: int = 0
    claimed: int = 0
    executed: int = 0
    settled: int = 0
    reconciled: int = 0
    recovered: int = 0
    skipped: int = 0
    idle: bool = True
    last_reply: dict | None = None

    def merge(self, other: "RoundStats") -> None:
        self.claimed += other.claimed
        self.executed += other.executed
        self.settled += other.settled
        self.reconciled += other.reconciled
        self.recovered += other.recovered
        self.skipped += other.skipped
        if other.last_reply is not None:
            self.last_reply = other.last_reply

    @property
    def progress(self) -> int:
        return self.claimed + self.executed + self.settled + self.reconciled + self.recovered


def _encode_raw(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


class HostWorker:
    def __init__(self, db: HostDB, journal: HostJournal, *, adapter=None,
                 tool_handler=None, resource_handler=None,
                 default_lease_ms: int = 30000, crash_after: str | None = None,
                 recover_key_prefix: str = "v24-host-recover"):
        if crash_after not in (None, "prepared", "started", "finished"):
            raise ValueError("crash_after")
        self.db = db
        self.journal = journal
        self.adapter = adapter
        self.tool_handler = tool_handler
        self.resource_handler = resource_handler
        self.default_lease_ms = default_lease_ms
        self.crash_after = crash_after
        self.recover_key_prefix = recover_key_prefix
        self.recover_seq = 0

    # -- public loop -----------------------------------------------------
    def run_until_idle(self, scope, max_rounds: int = 16) -> RoundStats:
        if max_rounds < 1:
            raise ValueError("max_rounds")
        total = RoundStats()
        for _ in range(max_rounds):
            one = self.run_once(scope)
            total.merge(one)
            total.rounds += 1
            if one.progress == 0:
                total.idle = True
                return total
        total.idle = False
        return total

    def run_once(self, scope) -> RoundStats:
        stats = RoundStats()
        self.db.assert_all_idle()
        stats.reconciled = self._reconcile(scope)
        if stats.reconciled > 0:
            self.db.assert_all_idle()

        resumed = self._resume_prepared(scope)
        if resumed is not _NOTHING:
            if resumed is None:
                stats.skipped += 1
                stats.idle = False
                return stats
            stats.claimed += 1 if resumed.get("claimed") else 0
            stats.executed = 1 if resumed.get("executed") else 0
            stats.settled += 1 if resumed.get("settled") else 0
            if resumed.get("reply") is not None:
                stats.last_reply = resumed["reply"]
            stats.idle = False
            return stats

        live, expired = self._orphan_state(scope)
        if live:
            stats.skipped += 1
            stats.idle = False
            return stats
        if expired or self._expired_claims(scope):
            stats.recovered = self._recover(scope)
            stats.settled += stats.recovered
            if stats.recovered:
                stats.idle = False

        ready = self._discover_ready(scope)
        if not ready:
            return stats
        effect = ready[0]
        outcome = self._claim_and_execute(effect)
        if outcome is None:
            stats.skipped += 1
            stats.idle = False
            return stats
        stats.claimed += 1
        stats.executed = 1 if outcome.get("executed") else 0
        stats.settled += 1 if outcome.get("settled") else 0
        if outcome.get("reply") is not None:
            stats.last_reply = outcome["reply"]
        stats.idle = False
        return stats

    # -- prepared-but-not-started restart window ------------------------
    def _resume_prepared(self, scope):
        """Re-read DB eligibility for an ``effect_prepared`` without a start.

        No external I/O happened in this window, so the original token may
        execute once its lease and preconditions still hold.  A live but
        insufficient lease is left alone; expiry turns it into ``unknown`` via
        the normal recovery sweep.
        """
        for effect_id in self.journal.prepared_without_dispatch():
            response = self.db.host_effect(effect_id)
            if is_error(response):
                continue
            effect = response["effect"]
            if str(effect.get("scope_id")) != str(scope):
                continue
            status = effect.get("status")
            if status == "ready":
                return self._claim_and_execute(effect)
            if status != "claimed":
                prepared = self.journal.last("effect_prepared", effect_id)
                if prepared is not None:
                    self._record_settlement(
                        effect_id, prepared["request_digest"],
                        prepared.get("run_id"), prepared.get("claim") or {},
                        {"conflict": True, "reason": "database_terminal_no_dispatch"})
                continue
            prepared = self.journal.last("effect_prepared", effect_id)
            if prepared is None:
                continue
            token = {"attempt": effect["attempt_no"], "fence": effect["fence"],
                     "owner": effect["claim_owner"]}
            if prepared.get("claim") != token:
                continue
            remaining = self.db.remaining_lease_ms(effect.get("lease_until"))
            kind = effect.get("kind")
            if kind == "model_call" and self.adapter is not None:
                required = int(self.adapter.timeout_s * 1000) + 5000
            else:
                required = 0
            if remaining <= required:
                continue
            digest = request_digest(effect.get("request") or {})
            if kind == "model_call":
                outcome = self._execute_model(effect_id, effect, token, digest)
            elif kind == "tool_call":
                outcome = self._execute_tool(effect_id, effect, token, digest)
            else:
                outcome = self._execute_resource(effect_id, effect, token, digest)
            outcome["claimed"] = False
            return outcome
        return _NOTHING

    # -- reconciliation --------------------------------------------------
    def _reconcile(self, scope) -> int:
        settled = 0
        for effect_id in self.journal.pending_settlements():
            response = self.db.host_effect(effect_id)
            if is_error(response):
                continue
            effect = response["effect"]
            if str(effect.get("scope_id")) != str(scope):
                continue
            finish = self.journal.last("dispatch_finished", effect_id)
            if finish is None:
                continue
            outcome = finish["payload"]["outcome"]
            status = effect.get("status")
            if status == "claimed":
                token = {"attempt": effect["attempt_no"], "fence": effect["fence"],
                         "owner": effect["claim_owner"]}
                stored = finish.get("claim")
                if stored != token:
                    # A different incarnation owns the claim; never settle with
                    # an old token.
                    self._record_settlement(effect_id, finish.get("request_digest",
                        self._digest_for(effect_id)), finish.get("run_id"), token,
                        {"conflict": True, "reason": "claim_token_changed",
                         "outcome": outcome, "stored_claim": stored})
                    continue
                result = self.db.settle(effect_id, outcome["class"], token,
                                        outcome["body"]["kind"],
                                        outcome["body"]["result"])
                if is_error(result):
                    continue
                self._record_settlement(effect_id, finish["request_digest"],
                                        finish.get("run_id"), token,
                                        {"outcome": outcome, "response": result,
                                         "reconciled": True})
                settled += 1
            else:
                stored_outcome = finish["payload"].get("outcome")
                same = effect.get("outcome") == stored_outcome
                self._record_settlement(
                    effect_id, finish["request_digest"], finish.get("run_id"),
                    finish.get("claim") or {},
                    {"conflict": not same, "reason": "database_terminal",
                     "outcome": stored_outcome})
        return settled

    def _record_settlement(self, effect_id, digest, run_id, claim, payload) -> None:
        if self.journal.has("settlement_committed", effect_id):
            return
        self.journal.append("settlement_committed", effect_id, digest,
                            payload, run_id=run_id, claim=claim)

    def _digest_for(self, effect_id) -> str:
        response = self.db.host_effect(effect_id)
        if is_error(response):
            return hashlib.sha256(str(effect_id).encode()).hexdigest()
        return request_digest(response["effect"].get("request") or {})

    def _orphan_state(self, scope):
        live = False
        expired = False
        for effect_id in self.journal.unfinished_dispatches():
            response = self.db.host_effect(effect_id)
            if is_error(response):
                continue
            effect = response["effect"]
            if str(effect.get("scope_id")) != str(scope):
                continue
            if effect.get("status") != "claimed":
                continue
            remaining = self.db.remaining_lease_ms(effect["lease_until"])
            if remaining > 0:
                live = True
            else:
                expired = True
        return live, expired

    def _expired_claims(self, scope) -> bool:
        """A claimed effect past its lease, found through a public reader."""
        cursor = None
        while True:
            if cursor is None:
                response = self.db.host_effects(scope, None, None, 64)
            else:
                response = self.db.host_effects(
                    scope, cursor["created_at"], cursor["effect_id"], 64)
            if is_error(response):
                return False
            for item in response.get("items", []):
                if item.get("status") == "claimed" and self.db.remaining_lease_ms(
                        item.get("lease_until")) <= 0:
                    return True
            if not response.get("has_more"):
                return False
            cursor = response["next_cursor"]
            if not isinstance(cursor, dict):
                return False

    def _recover(self, scope) -> int:
        if self.recover_seq == 0:
            self.recover_seq = 0
        self.recover_seq += 1
        key = f"{self.recover_key_prefix}:{scope}:{self.recover_seq}:{uuid4().hex[:8]}"
        response = self.db.recover(scope, key, 16)
        if is_error(response):
            return 0
        return 1

    # -- discovery / ordering -------------------------------------------
    def _discover_ready(self, scope) -> list[dict]:
        items = []
        cursor = None
        while True:
            if cursor is None:
                response = self.db.host_effects(scope, None, None, 64)
            else:
                response = self.db.host_effects(
                    scope, cursor["created_at"], cursor["effect_id"], 64)
            if is_error(response):
                raise HostDBError(response)
            items.extend(item for item in response.get("items", [])
                         if item.get("status") == "ready"
                         and item.get("kind") in EXTERNAL_KINDS)
            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]
            if not isinstance(cursor, dict):
                raise HostDBError({"error": {"code": "next_cursor_invalid"}})
        return sorted(items, key=self._order_key)

    @staticmethod
    def _order_key(item):
        kind = item.get("kind")
        klass = 0 if kind in HOST_KINDS else 1
        return (klass, str(item.get("effect_id")))

    # -- claim / execute / settle ---------------------------------------
    def _claim_and_execute(self, item) -> dict | None:
        effect_id = item["effect_id"]
        kind = item["kind"]
        lease = self._lease_for(item)
        response = self.db.claim(effect_id, lease)
        if is_error(response):
            return None
        if response.get("disposition") != "committed" or not response.get("claim"):
            return None
        token = response["claim"]
        self.db.assert_all_idle()

        committed = self.db.host_effect(effect_id)
        if is_error(committed):
            return None
        effect = committed["effect"]
        if (effect.get("status") != "claimed"
                or {"attempt": effect["attempt_no"], "fence": effect["fence"],
                    "owner": effect["claim_owner"]} != token):
            return None
        digest = request_digest(effect.get("request") or {})

        if kind == "model_call":
            return self._execute_model(effect_id, effect, token, digest)
        if kind == "tool_call":
            return self._execute_tool(effect_id, effect, token, digest)
        return self._execute_resource(effect_id, effect, token, digest)

    def _lease_for(self, item) -> int:
        if item.get("kind") == "model_call" and self.adapter is not None:
            return DeepSeekAdapter.lease_ms(self.adapter.timeout_s)
        return self.default_lease_ms

    def _base_payload(self, kind, request, token, **extra) -> dict:
        payload = {"kind": kind, "request": request, "claim": token}
        payload.update(extra)
        return payload

    def _execute_model(self, effect_id, effect, token, digest) -> dict:
        run_id = effect.get("run_id")
        request = effect.get("request") or {}
        kind = "model_call"
        already_prepared = self.journal.has("effect_prepared", effect_id)
        if self.adapter is None:
            return self._no_http_failure(
                effect_id, run_id, token, digest, kind, "adapter_absent",
                request=request, journaled=already_prepared)
        preflight = self.adapter.preflight()
        if preflight is not None:
            return self._no_http_failure(
                effect_id, run_id, token, digest, kind,
                preflight.get("class", "preflight"), request=request,
                journaled=already_prepared)
        history = self._history(run_id)
        pins = self._run_pins(run_id)
        if pins is None:
            return self._no_http_failure(
                effect_id, run_id, token, digest, kind, "pins_unavailable",
                request=request, journaled=already_prepared)
        try:
            prepared = self.adapter.build(effect, history, pins)
        except AdapterFailure as exc:
            return self._no_http_failure(
                effect_id, run_id, token, digest, kind, exc.reason,
                request=request, journaled=already_prepared)
        cause = request.get("cause")
        seed_messages = prepared.messages if cause in ("start", "spawn") else None
        appended = []
        if cause == "steer" and isinstance(request.get("instruction"), str):
            appended = [{"role": "user", "content": request["instruction"]}]
        elif cause == "respond" and isinstance(request.get("response"), dict):
            appended = [{"role": "user", "content": canonical_json(request["response"])}]
        if not already_prepared:
            self.journal.append(
                "effect_prepared", effect_id, digest,
                self._base_payload(kind, request, token,
                                   seed_messages=seed_messages,
                                   appended_messages=appended),
                run_id=run_id, claim=token)
        if self.crash_after == "prepared":
            raise HostCrash("scripted crash after effect_prepared")

        remaining = self.db.remaining_lease_ms(effect["lease_until"])
        required = int(self.adapter.timeout_s * 1000) + 5000
        if remaining < required:
            return self._no_http_failure(effect_id, run_id, token, digest, kind,
                                         "lease_insufficient", request=request,
                                         journaled=True)

        self.journal.append(
            "dispatch_started", effect_id, digest,
            self._base_payload(kind, request, token, prepared=prepared.to_journal()),
            run_id=run_id, claim=token)
        self.db.assert_all_idle()
        if self.crash_after == "started":
            raise HostCrash("scripted crash after dispatch_started")

        try:
            status, raw, wall_ms = self.adapter.send(prepared)
            mapped = self.adapter.interpret(prepared, status, raw, wall_ms)
        except ProviderRejected as exc:
            mapped = {"class": "failure", "result": {"text": None,
                      "usage": {"tokens": 0, "wall_ms": 0}},
                      "reply": None, "assistant_message": None,
                      "tool_calls": None, "reason": exc.detail.get("class")}
            status, raw, wall_ms = None, b"", 0
        except ProviderUncertain as exc:
            mapped = {"class": "unknown", "result": {"text": None},
                      "reply": None, "assistant_message": None,
                      "tool_calls": None, "reason": exc.detail.get("class")}
            status, raw, wall_ms = None, b"", 0
        except OSError:
            mapped = {"class": "unknown", "result": {"text": None},
                      "reply": None, "assistant_message": None,
                      "tool_calls": None, "reason": "transport"}
            status, raw, wall_ms = None, b"", 0

        outcome = {"v": 1, "class": mapped["class"], "claim": token,
                   "body": {"kind": kind, "result": mapped["result"]}}
        self.journal.append(
            "dispatch_finished", effect_id, digest,
            self._base_payload(
                kind, request, token, outcome=outcome,
                http_status=status, raw_response_base64=_encode_raw(raw),
                wall_ms=wall_ms, mapping=mapped,
                assistant_message=mapped.get("assistant_message"),
                tool_calls=mapped.get("tool_calls"),
                reason=mapped.get("reason")),
            run_id=run_id, claim=token)
        if self.crash_after == "finished":
            raise HostCrash("scripted crash after dispatch_finished")
        settled = self._settle(effect_id, run_id, token, digest, kind,
                               mapped["class"], mapped["result"], outcome)
        return {"executed": True, "settled": settled,
                "reply": mapped.get("reply")}

    def _execute_tool(self, effect_id, effect, token, digest) -> dict:
        run_id = effect.get("run_id")
        request = effect.get("request") or {}
        kind = "tool_call"
        parent = self._parent_tool_call(effect)
        if parent is None:
            return self._no_http_unknown(
                effect_id, run_id, token, digest, kind, "tool_call_id_missing",
                request=request,
                journaled=self.journal.has("effect_prepared", effect_id))
        if not self.journal.has("effect_prepared", effect_id):
            self.journal.append(
                "effect_prepared", effect_id, digest,
                self._base_payload(kind, request, token),
                run_id=run_id, claim=token)
        self.journal.append(
            "dispatch_started", effect_id, digest,
            self._base_payload(kind, request, token,
                               provider_tool_call_id=parent["id"]),
            run_id=run_id, claim=token)
        self.db.assert_all_idle()
        if self.crash_after == "started":
            raise HostCrash("scripted crash after dispatch_started")
        if self.tool_handler is None:
            class_name, result, reason = "unknown", {
                "status": "error", "output": {"code": "tool_handler_absent"},
                "usage": {"wall_ms": 0}}, "tool_handler_absent"
        else:
            try:
                class_name, result = _call_tool_handler(self.tool_handler, effect)
                reason = None
            except Exception:
                class_name, result, reason = "unknown", {
                    "status": "error", "output": {"code": "tool_executor_error"},
                    "usage": {"wall_ms": 0}}, "tool_executor_error"
        outcome = {"v": 1, "class": class_name, "claim": token,
                   "body": {"kind": kind, "result": result}}
        tool_message = {
            "role": "tool",
            "tool_call_id": parent["id"],
            "content": canonical_json(result.get("output", {})),
        }
        self.journal.append(
            "dispatch_finished", effect_id, digest,
            self._base_payload(kind, request, token, outcome=outcome,
                               tool_result=result, tool_message=tool_message,
                               parent_effect_id=effect.get("parent_effect_id"),
                               ordinal=effect.get("ordinal"), reason=reason),
            run_id=run_id, claim=token)
        if self.crash_after == "finished":
            raise HostCrash("scripted crash after dispatch_finished")
        settled = self._settle(effect_id, run_id, token, digest, kind,
                               class_name, result, outcome)
        return {"executed": True, "settled": settled, "reply": None}

    def _execute_resource(self, effect_id, effect, token, digest) -> dict:
        run_id = effect.get("run_id")
        request = effect.get("request") or {}
        kind = effect.get("kind")
        if not self.journal.has("effect_prepared", effect_id):
            self.journal.append(
                "effect_prepared", effect_id, digest,
                self._base_payload(kind, request, token),
                run_id=run_id, claim=token)
        self.journal.append(
            "dispatch_started", effect_id, digest,
            self._base_payload(kind, request, token),
            run_id=run_id, claim=token)
        self.db.assert_all_idle()
        if self.crash_after == "started":
            raise HostCrash("scripted crash after dispatch_started")
        if self.resource_handler is not None:
            try:
                class_name, result = _call_tool_handler(self.resource_handler, effect)
                reason = None
            except Exception:
                class_name, result, reason = "unknown", {"v": 1, "observed": "unknown"}, \
                    "resource_executor_error"
        else:
            class_name, result, reason = "unknown", {"v": 1, "observed": "unknown"}, \
                "resource_handler_absent"
        outcome = {"v": 1, "class": class_name, "claim": token,
                   "body": {"kind": kind, "result": result}}
        self.journal.append(
            "dispatch_finished", effect_id, digest,
            self._base_payload(kind, request, token, outcome=outcome,
                               resource_result=result, reason=reason),
            run_id=run_id, claim=token)
        if self.crash_after == "finished":
            raise HostCrash("scripted crash after dispatch_finished")
        settled = self._settle(effect_id, run_id, token, digest, kind,
                               class_name, result, outcome)
        return {"executed": True, "settled": settled, "reply": None}

    def _parent_tool_call(self, effect) -> dict | None:
        parent_id = effect.get("parent_effect_id")
        ordinal = effect.get("ordinal")
        if not isinstance(parent_id, str) or isinstance(ordinal, bool) or not isinstance(
                ordinal, int):
            return None
        finish = self.journal.last("dispatch_finished", parent_id)
        if finish is None:
            return None
        assistant = finish["payload"].get("assistant_message")
        calls = assistant.get("tool_calls") if isinstance(assistant, dict) else None
        if isinstance(calls, list) and 0 <= ordinal < len(calls):
            return calls[ordinal]
        explicit = finish["payload"].get("tool_calls")
        if isinstance(explicit, list) and 0 <= ordinal < len(explicit):
            item = explicit[ordinal]
            if isinstance(item, dict) and isinstance(item.get("provider_id"), str):
                return {"id": item["provider_id"],
                        "name": item.get("provider_name"),
                        "arguments": item.get("arguments")}
        return None

    def _run_pins(self, run_id) -> list[dict] | None:
        pins = []
        cursor = None
        while True:
            if cursor is None:
                response = self.db.host_run_pins(run_id, None, 64)
            else:
                response = self.db.host_run_pins(run_id, cursor["pin_id"], 64)
            if is_error(response):
                return None
            pins.extend(pin for pin in response.get("items", [])
                        if pin.get("released_at") is None)
            if not response.get("has_more"):
                return pins
            cursor = response["next_cursor"]
            if not isinstance(cursor, dict):
                return None

    def _history(self, run_id: str) -> list[dict]:
        """Replay the journal into provider messages.

        Tool results are inserted immediately after their parent assistant in
        ordinal order, even though the worker executes same-class effects in
        effect-UUID order.  Provider tool-call order therefore survives.
        """
        seed = None
        timeline = []
        tools: dict[str, list[tuple[int, dict]]] = {}
        for record in self.journal.records_for_run(run_id):
            payload = record["payload"]
            if record["event_type"] == "effect_prepared":
                if seed is None and isinstance(payload.get("seed_messages"), list):
                    seed = payload["seed_messages"]
                appended = payload.get("appended_messages")
                if isinstance(appended, list):
                    for message in appended:
                        timeline.append(("message", message))
            elif record["event_type"] == "dispatch_finished":
                if payload.get("kind") == "model_call" and isinstance(
                        payload.get("assistant_message"), dict):
                    timeline.append(("assistant", record["effect_id"],
                                     payload["assistant_message"]))
                    tools.setdefault(record["effect_id"], [])
                elif payload.get("kind") == "tool_call" and isinstance(
                        payload.get("tool_message"), dict):
                    parent = payload.get("parent_effect_id")
                    ordinal = payload.get("ordinal")
                    if isinstance(parent, str) and isinstance(ordinal, int):
                        tools.setdefault(parent, []).append(
                            (ordinal, payload["tool_message"]))
        messages = []
        for item in timeline:
            if item[0] == "assistant":
                messages.append(item[2])
                for _, message in sorted(tools.get(item[1], []),
                                         key=lambda pair: pair[0]):
                    messages.append(message)
            else:
                messages.append(item[1])
        return (seed or []) + messages

    # -- no-I/O outcomes -------------------------------------------------
    def _no_http_failure(self, effect_id, run_id, token, digest, kind, reason,
                         *, request=None, journaled: bool = False) -> dict:
        result = {"text": None, "usage": {"tokens": 0, "wall_ms": 0}}
        outcome = {"v": 1, "class": "failure", "claim": token,
                   "body": {"kind": kind, "result": result}}
        if not journaled:
            self.journal.append(
                "effect_prepared", effect_id, digest,
                self._base_payload(kind, request or {}, token, local_failure=reason),
                run_id=run_id, claim=token)
        settled = self._settle(effect_id, run_id, token, digest, kind,
                               "failure", result, outcome)
        return {"executed": True, "settled": settled, "reply": None}

    def _no_http_unknown(self, effect_id, run_id, token, digest, kind, reason,
                         *, request=None, journaled: bool = False) -> dict:
        if kind == "tool_call":
            result = {"status": "error", "output": {"code": reason},
                      "usage": {"wall_ms": 0}}
        else:
            result = {"v": 1, "observed": "unknown"}
        outcome = {"v": 1, "class": "unknown", "claim": token,
                   "body": {"kind": kind, "result": result}}
        if not journaled:
            self.journal.append(
                "effect_prepared", effect_id, digest,
                self._base_payload(kind, request or {}, token, local_failure=reason),
                run_id=run_id, claim=token)
        settled = self._settle(effect_id, run_id, token, digest, kind,
                               "unknown", result, outcome)
        return {"executed": True, "settled": settled, "reply": None}

    def _settle(self, effect_id, run_id, token, digest, kind, class_name,
                result, outcome) -> bool:
        response = self.db.settle(effect_id, class_name, token, kind, result)
        self.db.assert_all_idle()
        if is_error(response):
            # Keep dispatch_finished pending: the next round/restart resubmits
            # the same outcome with the same token; do not pretend it committed.
            return False
        self.journal.append("settlement_committed", effect_id, digest,
                            {"outcome": outcome, "response": response},
                            run_id=run_id, claim=token)
        return True

    # -- lease helper ----------------------------------------------------
    def lease_ok(self, effect_id, token, timeout_s: float) -> bool:
        response = self.db.host_effect(effect_id)
        if is_error(response):
            return False
        effect = response["effect"]
        if effect.get("status") != "claimed":
            return False
        if {"attempt": effect["attempt_no"], "fence": effect["fence"],
                "owner": effect["claim_owner"]} != token:
            return False
        remaining = self.db.remaining_lease_ms(effect["lease_until"])
        return remaining >= int(timeout_s * 1000) + 5000


def _call_tool_handler(handler, effect):
    value = handler(effect)
    if isinstance(value, tuple) and len(value) == 2:
        return value
    if isinstance(value, dict) and "class" in value and "result" in value:
        return value["class"], value["result"]
    raise TypeError("handler must return (class, result) or {class, result}")
