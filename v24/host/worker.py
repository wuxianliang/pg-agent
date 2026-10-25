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
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from v15.provider.errors import ProviderRejected, ProviderUncertain

from .db import HostContractError, HostDBError, is_error
from .deepseek import AdapterFailure, DeepSeekAdapter
from .journal import HostJournal, JournalCorrupt, canonical_json, request_digest

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
    scope_visits: int = 0
    new_opportunities: int = 0
    claim_conflicts: int = 0
    prepared_attempts: int = 0
    orphan_blocked: int = 0
    recovery_commands: int = 0
    recovery_applied: int = 0
    recovery_has_more: bool = False
    manual_debt_ids: set[str] = field(default_factory=set)
    pending_work: bool = False
    stop_reason: str | None = None

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
        self._next_scope_after = None
        self._fair_cursors = {}
        self._host_streak = {}
        self._resume_cursor = {}
        self._fair_scope_journal_ids = {}
        self._fair_active = False

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

    # -- fair multi-scope loop ------------------------------------------
    def run_scopes_until_idle(self, scope_ids: Iterable[str] | None = None,
                              max_rounds: int = 16) -> RoundStats:
        """Visit a fixed authorized roster in RR order, with separate recovery.

        Opportunities count discovery-originated claim attempts, not completed
        IO. State is process-local; restarting does not restore fairness debt.
        """
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or max_rounds < 1:
            raise ValueError("max_rounds must be a positive integer")
        if self._fair_active:
            raise HostContractError("fair worker is already running")
        self._fair_active = True
        try:
            return self._run_scopes(scope_ids, max_rounds)
        finally:
            self._fair_active = False

    def _run_scopes(self, scope_ids, max_rounds):
        self.db.assert_all_idle()
        roster = self._fair_roster(scope_ids)
        self._fair_scope_journal_ids = {}
        self._fair_ownership(roster)
        for mapping in (self._fair_cursors, self._host_streak, self._resume_cursor):
            for key in list(mapping):
                scope = key[0] if isinstance(key, tuple) else key
                if scope not in roster:
                    del mapping[key]
        total = RoundStats()
        if not roster:
            total.stop_reason = "idle"
            return total
        attempted = set()  # Every physical claim, including prepared-ready.
        visited, residual, debt, more = set(), {}, {}, {}
        pass_progress = False
        index = roster.index(self._next_scope(roster))
        for _ in range(max_rounds):
            scope = roster[index]
            index = (index + 1) % len(roster)
            self._next_scope_after = scope
            one, progressed = self._fair_visit(scope, attempted)
            total.merge(one)  # Preserve the legacy merge/progress contract.
            for name in ("new_opportunities", "claim_conflicts", "prepared_attempts",
                         "orphan_blocked", "recovery_commands", "recovery_applied"):
                setattr(total, name, getattr(total, name) + getattr(one, name))
            total.scope_visits += 1
            total.rounds = total.scope_visits
            residual[scope] = one.pending_work
            debt[scope] = one.manual_debt_ids
            more[scope] = one.recovery_has_more
            total.manual_debt_ids = set().union(*debt.values())
            total.recovery_has_more = any(more.values())
            visited.add(scope)
            pass_progress |= progressed
            if len(visited) == len(roster):
                total.pending_work = any(residual.values()) or bool(self._fair_journal_ids())
                if not total.pending_work:
                    total.idle = True
                    total.stop_reason = "idle"
                    return total
                if not pass_progress:
                    total.idle = False
                    total.stop_reason = "blocked_no_progress"
                    return total
                # A new pass starts at this invocation's actual RR origin.
                visited.clear()
                pass_progress = False
        total.idle = False
        total.pending_work = True  # A truncated pass cannot establish idleness.
        total.stop_reason = "budget_exhausted"
        return total

    @staticmethod
    def _uuid_text(value):
        if not isinstance(value, (str, UUID)):
            raise ValueError("invalid UUID")
        try:
            return str(UUID(str(value)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("invalid UUID") from exc

    @staticmethod
    def _fair_envelope(response, name):
        if not isinstance(response, dict) or type(response.get("v")) is not int or response["v"] != 1:
            raise HostContractError(f"{name} malformed envelope")
        if "error" in response:
            if not is_error(response) or not isinstance(response["error"].get("code"), str):
                raise HostContractError(f"{name} malformed error")
            raise HostDBError(response)

    @classmethod
    def _fair_page(cls, response, name):
        cls._fair_envelope(response, name)
        if (set(response) != {"v", "items", "limit", "has_more", "next_cursor"}
                or not isinstance(response.get("items"), list)
                or len(response["items"]) > 64
                or type(response.get("has_more")) is not bool
                or type(response.get("limit")) is not int or response["limit"] != 64
                or (not response["has_more"] and response.get("next_cursor") is not None)):
            raise HostContractError(f"{name} malformed page")
        return response["items"]

    def _fair_roster(self, scope_ids):
        if scope_ids is not None:
            if isinstance(scope_ids, (str, bytes, bytearray)):
                raise ValueError("scope_ids must be an iterable of UUIDs")
            try:
                return sorted({self._uuid_text(x) for x in scope_ids}, key=UUID)
            except TypeError as exc:
                raise ValueError("scope_ids must be iterable") from exc
        result, after = [], None
        while True:
            response = self.db.host_scopes(None, after, 64)
            page = self._fair_page(response, "host_scopes")
            previous = after
            for item in page:
                try:
                    value = self._uuid_text(item["scope_id"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise HostContractError("host_scopes malformed item") from exc
                if previous is not None and UUID(value) <= UUID(previous):
                    raise HostContractError("host_scopes did not advance")
                result.append(value)
                previous = value
            if not response["has_more"]:
                return result
            cursor = response.get("next_cursor")
            if not page or not isinstance(cursor, dict) or cursor != {"scope_id": previous}:
                raise HostContractError("host_scopes invalid cursor")
            after = previous

    def _fair_journal_ids(self):
        ids = set(self.journal.prepared_without_dispatch())
        ids.update(self.journal.pending_settlements())
        ids.update(self.journal.unfinished_dispatches())
        return ids - {r["effect_id"] for r in self.journal.records
                      if r["event_type"] == "settlement_committed"}

    def _fair_effect(self, effect_id):
        response = self.db.host_effect(effect_id)
        self._fair_envelope(response, "host_effect")
        effect = response.get("effect")
        self._fair_validate_effect(effect, effect_id)
        return effect

    def _fair_validate_effect(self, effect, effect_id=None, scope=None):
        if (not isinstance(effect, dict)
                or effect.get("status") not in ("ready", "claimed", "succeeded", "failed", "unknown", "cancelled")
                or effect.get("kind") not in EXTERNAL_KINDS
                or not isinstance(effect.get("request"), dict)
                or effect.get("replay_policy") not in ("replay_safe", "no_replay", "manual")):
            raise HostContractError("malformed external effect")
        try:
            actual_id = self._uuid_text(effect.get("effect_id"))
            actual_scope = self._uuid_text(effect.get("scope_id"))
        except ValueError as exc:
            raise HostContractError("malformed effect identity") from exc
        if effect_id is not None and actual_id != str(effect_id):
            raise HostContractError("effect identity mismatch")
        if scope is not None and actual_scope != scope:
            raise HostContractError("effect scope mismatch")
        if effect["status"] == "claimed":
            self._fair_token(self._effect_token(effect))
            lease = effect.get("lease_until")
            try:
                parsed = datetime.fromisoformat(lease) if isinstance(lease, str) else lease
                if not isinstance(parsed, datetime) or parsed.tzinfo is None:
                    raise ValueError("lease timestamp")
            except ValueError as exc:
                raise HostContractError("invalid claimed lease") from exc

    @staticmethod
    def _effect_token(effect):
        return {"attempt": effect.get("attempt_no"), "fence": effect.get("fence"),
                "owner": effect.get("claim_owner")}

    @staticmethod
    def _fair_token(token):
        if (not isinstance(token, dict) or set(token) != {"attempt", "fence", "owner"}
                or type(token.get("attempt")) is not int or token["attempt"] < 1
                or type(token.get("fence")) is not int or token["fence"] < 1
                or token["fence"] > token["attempt"]
                or not isinstance(token.get("owner"), str) or not token["owner"]):
            raise HostContractError("invalid claim token")
        return token

    def _fair_ownership(self, roster):
        # Validate the WHOLE startup set before appending even a conflict marker.
        effects = []
        for effect_id in sorted(self._fair_journal_ids()):
            try:
                effect = self._fair_effect(effect_id)
            except (HostDBError, HostContractError) as exc:
                raise HostContractError("journal ownership lookup failed") from exc
            if str(effect["scope_id"]) not in roster:
                raise HostContractError("journal effect outside roster")
            self._fair_scope_journal_ids.setdefault(str(effect["scope_id"]), set()).add(str(effect_id))
            effects.append(effect)
        for effect in effects:
            self._fair_close_orphan(effect)

    def _fair_close_orphan(self, effect):
        effect_id = str(effect["effect_id"])
        if (effect["status"] not in ("succeeded", "failed", "unknown", "cancelled")
                or self.journal.has("dispatch_finished", effect_id)
                or self.journal.has("settlement_committed", effect_id)
                or not self.journal.has("dispatch_started", effect_id)):
            return False
        started = self.journal.last("dispatch_started", effect_id)
        if started is None:
            raise JournalCorrupt("unfinished dispatch lacks started record")
        token = started.get("claim")
        if token is None:
            token = {}
        elif not isinstance(token, dict):
            raise JournalCorrupt("invalid original dispatch claim")
        if token:
            try:
                self._fair_token(token)
            except HostContractError as exc:
                raise JournalCorrupt("invalid original dispatch claim") from exc
        self._record_settlement(
            effect_id, started["request_digest"], started.get("run_id"), token,
            {"conflict": True, "reason": "database_terminal_no_outcome",
             "database_status": effect["status"]})
        return True

    def _next_scope(self, roster):
        for scope in roster:
            if self._next_scope_after is None or UUID(scope) > UUID(self._next_scope_after):
                return scope
        return roster[0]

    @staticmethod
    def _fair_key(item):
        try:
            created = item["created_at"]
            created = datetime.fromisoformat(created) if isinstance(created, str) else created
            if not isinstance(created, datetime) or created.tzinfo is None:
                raise ValueError("created_at")
            return created.astimezone(timezone.utc), UUID(str(item["effect_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise HostContractError("invalid effect ordering key") from exc

    def _fair_pick(self, scope, klass, candidates):
        key = self._fair_cursors.get((scope, klass))
        ordered = sorted(candidates, key=self._fair_key)
        chosen = next((x for x in ordered if key is None or self._fair_key(x) > key), ordered[0])
        self._fair_cursors[(scope, klass)] = self._fair_key(chosen)
        return chosen

    def _fair_scan(self, scope):
        items, cursor = [], None
        while True:
            response = self.db.host_effects(scope, *(cursor or (None, None)), 64)
            page = self._fair_page(response, "host_effects")
            previous = None if cursor is None else self._fair_key(
                {"created_at": cursor[0], "effect_id": cursor[1]})
            for effect in page:
                self._fair_validate_effect(effect, scope=scope)
                if effect["status"] not in ("ready", "claimed"):
                    raise HostContractError("terminal effect in discovery")
                key = self._fair_key(effect)
                if previous is not None and key <= previous:
                    raise HostContractError("host_effects did not advance")
                previous = key
                items.append(effect)
            if not response["has_more"]:
                return items
            nxt = response.get("next_cursor")
            if not page or not isinstance(nxt, dict) or set(nxt) != {"created_at", "effect_id"}:
                raise HostContractError("host_effects invalid cursor")
            if self._fair_key(nxt) != previous:
                raise HostContractError("host_effects cursor mismatch")
            cursor = nxt["created_at"], nxt["effect_id"]

    def _fair_reconcile(self, scope):
        count, progressed = 0, False
        for effect_id in list(self.journal.pending_settlements()):
            effect = self._fair_effect(effect_id)
            if str(effect["scope_id"]) != scope:
                continue
            finish = self.journal.last("dispatch_finished", effect_id)
            if finish is None or not isinstance(finish["payload"].get("outcome"), dict):
                raise JournalCorrupt("missing durable outcome")
            outcome = finish["payload"]["outcome"]
            stored = finish.get("claim") or {}
            if effect["status"] == "claimed" and self._effect_token(effect) == stored:
                self._fair_token(stored)
                response = self.db.settle(effect_id, outcome["class"], stored,
                                          outcome["body"]["kind"], outcome["body"]["result"])
                if self._fair_settle_response(response, effect_id):
                    self._record_settlement(effect_id, finish["request_digest"],
                        finish.get("run_id"), stored,
                        {"outcome": outcome, "response": response, "reconciled": True})
                    count += 1
                    progressed = True
            else:
                self._record_settlement(effect_id, finish["request_digest"],
                    finish.get("run_id"), stored,
                    {"conflict": effect.get("outcome") != outcome,
                     "reason": "database_terminal" if effect["status"] != "claimed"
                     else "claim_token_changed", "outcome": outcome})
                progressed = True  # Local debt cleared, not a successful settle.
        return count, progressed

    def _fair_orphan(self, scope):
        live = expired = progressed = False
        for effect_id in list(self.journal.unfinished_dispatches()):
            if self.journal.has("settlement_committed", effect_id):
                continue
            effect = self._fair_effect(effect_id)
            if str(effect["scope_id"]) != scope:
                continue
            progressed |= self._fair_close_orphan(effect)
            if effect["status"] == "claimed":
                if self.db.remaining_lease_ms(effect["lease_until"]) > 0:
                    live = True
                elif effect["replay_policy"] != "manual":
                    expired = True
        return live, expired, progressed

    def _fair_execute(self, effect, token):
        self.db.assert_all_idle()
        digest = request_digest(effect["request"])
        effect_id = str(effect["effect_id"])
        kind = effect["kind"]
        self._fair_scope_journal_ids.setdefault(str(effect["scope_id"]), set()).add(effect_id)
        if kind == "model_call":
            return self._execute_model(effect_id, effect, token, digest)
        if kind == "tool_call":
            return self._execute_tool(effect_id, effect, token, digest)
        return self._execute_resource(effect_id, effect, token, digest)

    def _fair_claim(self, item, attempted):
        effect_id = str(item["effect_id"])
        if effect_id in attempted:
            raise HostContractError("duplicate physical claim in fair invocation")
        attempted.add(effect_id)  # Before RPC, including malformed/lost replies.
        response = self.db.claim(effect_id, self._lease_for(item))
        if is_error(response) and response["error"].get("code") in ("invalid_args", "stale_claim"):
            self._fair_envelope({"v": response.get("v")}, "claim")
            current = self._fair_effect(effect_id)
            terminal = current["status"] in ("succeeded", "failed", "unknown", "cancelled")
            stale_business = (current["status"] == "claimed"
                and current["kind"] in ("model_call", "tool_call")
                and self.db.remaining_lease_ms(current["lease_until"]) <= 0)
            changed = any(current.get(k) != item.get(k) for k in
                          ("status", "attempt_no", "fence", "claim_owner"))
            if terminal or (response["error"]["code"] == "stale_claim" and (stale_business or changed)):
                return None
            raise HostDBError(response)
        self._fair_envelope(response, "claim")
        if str(response.get("effect_id")) != effect_id:
            raise HostContractError("claim identity mismatch")
        if response.get("disposition") == "deferred":
            if response.get("claim") not in (None, {}):
                raise HostContractError("deferred with token")
            return None
        if response.get("disposition") != "committed":
            raise HostContractError("unknown claim disposition")
        token = self._fair_token(response.get("claim"))
        effect = self._fair_effect(effect_id)
        if effect["status"] != "claimed" or self._effect_token(effect) != token:
            return None
        outcome = self._fair_execute(effect, token)
        outcome["claimed"] = True
        return outcome

    def _fair_prepared(self, scope, attempted):
        ids = [effect_id for effect_id in self.journal.prepared_without_dispatch()
               if not self.journal.has("dispatch_finished", effect_id)]
        candidates = []
        for effect_id in ids:
            record = self.journal.records_for(effect_id)[0]
            candidates.append(((record["seq"], effect_id), effect_id))
        candidates.sort()
        anchor = self._resume_cursor.get(scope)
        candidates = ([x for x in candidates if anchor is None or x[0] > anchor]
                      + [x for x in candidates if anchor is not None and x[0] <= anchor])
        progressed = False
        for key, effect_id in candidates:
            effect = self._fair_effect(effect_id)
            if str(effect["scope_id"]) != scope:
                continue
            self._resume_cursor[scope] = key
            prepared = self.journal.last("effect_prepared", effect_id)
            if effect["status"] in ("succeeded", "failed", "unknown", "cancelled"):
                self._record_settlement(effect_id, prepared["request_digest"],
                    prepared.get("run_id"), prepared.get("claim") or {},
                    {"conflict": True, "reason": "database_terminal_no_dispatch"})
                progressed = True
                continue
            if prepared["request_digest"] != request_digest(effect["request"]):
                raise JournalCorrupt("prepared request digest mismatch")
            if effect["status"] == "ready":
                if effect_id in attempted:
                    continue
                return True, self._fair_claim(effect, attempted), progressed
            token = self._effect_token(effect)
            if prepared.get("claim") != token:
                continue
            required = int(self.adapter.timeout_s * 1000) + 5000 if (
                effect["kind"] == "model_call" and self.adapter is not None) else 0
            if self.db.remaining_lease_ms(effect["lease_until"]) <= required:
                continue
            outcome = self._fair_execute(effect, token)
            outcome["claimed"] = False
            return True, outcome, progressed
        return False, None, progressed

    def _fair_recover(self, scope):
        self.recover_seq += 1
        key = f"{self.recover_key_prefix}:fair:{scope}:{self.recover_seq}:{uuid4().hex[:8]}"
        response = self.db.recover(scope, key, 16)
        self._fair_envelope(response, "command_recover")
        recovery = response.get("recovery")
        if (response.get("disposition") not in ("committed", "replay")
                or not isinstance(recovery, dict)
                or str(recovery.get("scope_id")) != scope
                or not isinstance(recovery.get("applied"), list)
                or not isinstance(recovery.get("skipped"), list)
                or len(recovery["applied"]) > 16
                or type(recovery.get("manual_debt")) is not int
                or recovery["manual_debt"] < 0
                or type(recovery.get("has_more")) is not bool):
            raise HostContractError("malformed recovery response")
        seen = set()
        for item in recovery["applied"]:
            if (not isinstance(item, dict) or item.get("kind") not in EXTERNAL_KINDS
                    or item.get("action") not in ("reset_ready", "settle_unknown")):
                raise HostContractError("malformed applied recovery row")
            try:
                effect_id = self._uuid_text(item.get("effect_id"))
            except ValueError as exc:
                raise HostContractError("malformed recovery effect identity") from exc
            if effect_id in seen:
                raise HostContractError("duplicate recovery effect identity")
            seen.add(effect_id)
        return recovery

    def _fair_settle_response(self, response, effect_id=None):
        if is_error(response) and response["error"].get("code") in ("receipt_conflict", "stale_claim"):
            self._fair_envelope({"v": response.get("v")}, "settle")
            return False
        self._fair_envelope(response, "settle")
        if (response.get("disposition") not in ("committed", "replay")
                or (effect_id is not None and str(response.get("effect_id")) != str(effect_id))
                or (effect_id is not None and (not isinstance(response.get("emitted"), list)
                    or type(response.get("revision")) is not int))):
            raise HostContractError("malformed settlement response")
        return True

    def _fair_visit(self, scope, attempted):
        stats = RoundStats(scope_visits=1)
        self.db.assert_all_idle()
        stats.reconciled, progressed = self._fair_reconcile(scope)
        live, expired, closed = self._fair_orphan(scope)
        progressed |= closed
        if live:
            stats.orphan_blocked = 1
            stats.skipped = 1
            stats.pending_work = True
            return stats, progressed
        resumed, outcome, closed = self._fair_prepared(scope, attempted)
        progressed |= closed
        if resumed:
            stats.prepared_attempts = 1
            self._fair_count(stats, outcome)
            progressed |= outcome is not None and bool(outcome.get("dispatched", outcome.get("executed")) or outcome.get("settled"))
        live, expired2, closed = self._fair_orphan(scope)
        progressed |= closed
        if live:
            stats.orphan_blocked = 1
            stats.pending_work = True
            return stats, progressed
        before = self._fair_scan(scope)
        expired |= expired2 or any(x["status"] == "claimed" and x["replay_policy"] != "manual"
                                 and self.db.remaining_lease_ms(x["lease_until"]) <= 0 for x in before)
        if expired:
            recovery = self._fair_recover(scope)
            stats.recovery_commands = 1
            stats.recovered = 1  # Legacy field remains the command count.
            stats.recovery_applied = len(recovery["applied"])
            stats.recovery_has_more = recovery["has_more"]
            progressed |= bool(recovery["applied"])
        live, _, closed = self._fair_orphan(scope)
        progressed |= closed
        if live:
            stats.orphan_blocked = 1
            stats.pending_work = True
            return stats, progressed
        discovered = self._fair_scan(scope)
        stats.manual_debt_ids = {str(x["effect_id"]) for x in discovered
            if x["status"] == "claimed" and x["replay_policy"] == "manual"
            and self.db.remaining_lease_ms(x["lease_until"]) <= 0}
        ready = [x for x in discovered if x["status"] == "ready" and str(x["effect_id"]) not in attempted]
        host = [x for x in ready if x["kind"] in HOST_KINDS]
        business = [x for x in ready if x["kind"] not in HOST_KINDS]
        streak = self._host_streak.get(scope, 0)
        klass = "business" if business and (not host or streak == 3) else "host"
        candidates = business if klass == "business" else host
        if candidates:
            effect = self._fair_pick(scope, klass, candidates)
            self._host_streak[scope] = 0 if klass == "business" else min(3, streak + 1)
            stats.new_opportunities = 1
            outcome = self._fair_claim(effect, attempted)
            self._fair_count(stats, outcome)
            progressed |= outcome is not None and bool(outcome.get("dispatched", outcome.get("executed")) or outcome.get("settled"))
        # Discovery precedes execution. Conservatively retain its observed work
        # until the following pass; do not add an unbudgeted third full scan.
        local_ids = self._fair_journal_ids()
        # Membership is known from this visit's journal reads or execution.
        # Do not charge B's durable debt to an otherwise empty A observation.
        local_ids &= self._fair_scope_journal_ids.get(scope, set())
        stats.pending_work = bool(discovered) or stats.recovery_has_more or bool(local_ids)
        return stats, progressed

    @staticmethod
    def _fair_count(stats, outcome):
        if outcome is None:
            stats.claim_conflicts += 1
            stats.skipped += 1
            return
        stats.claimed += int(bool(outcome.get("claimed")))
        stats.executed += int(bool(outcome.get("executed")))
        stats.settled += int(bool(outcome.get("settled")))
        if outcome.get("reply") is not None:
            stats.last_reply = outcome["reply"]

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
                if self._fair_active:
                    raise
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
                if self._fair_active:
                    raise
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
            if self._fair_active:
                page = self._fair_page(response, "host_run_pins")
                previous = None if cursor is None else UUID(cursor["pin_id"])
                for pin in page:
                    try:
                        key = UUID(self._uuid_text(pin["pin_id"]))
                    except (TypeError, KeyError, ValueError) as exc:
                        raise HostContractError("host_run_pins malformed identity") from exc
                    if previous is not None and key <= previous:
                        raise HostContractError("host_run_pins unordered page")
                    previous = key
                if response["has_more"] and (not page or response.get("next_cursor") != {
                        "pin_id": str(previous)}):
                    raise HostContractError("host_run_pins cursor mismatch")
            if is_error(response):
                return None
            pins.extend(pin for pin in response.get("items", [])
                        if pin.get("released_at") is None)
            if not response.get("has_more"):
                return pins
            nxt = response["next_cursor"]
            if self._fair_active:
                if not isinstance(nxt, dict) or set(nxt) != {"pin_id"}:
                    raise HostContractError("host_run_pins cursor")
                try:
                    next_id = self._uuid_text(nxt["pin_id"])
                    previous = None if cursor is None else self._uuid_text(cursor["pin_id"])
                except ValueError as exc:
                    raise HostContractError("host_run_pins cursor") from exc
                if previous is not None and UUID(next_id) <= UUID(previous):
                    raise HostContractError("host_run_pins cursor did not advance")
            cursor = nxt
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
        return {"executed": True, "dispatched": False, "settled": settled, "reply": None}

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
        return {"executed": True, "dispatched": False, "settled": settled, "reply": None}

    def _settle(self, effect_id, run_id, token, digest, kind, class_name,
                result, outcome) -> bool:
        if self._fair_active and not self.journal.has("dispatch_finished", effect_id):
            # A local preflight outcome also needs durable reconciliation if
            # settlement races. This records local completion, not dispatched IO.
            self.journal.append("dispatch_finished", effect_id, digest,
                {"kind": kind, "outcome": outcome, "no_io": True},
                run_id=run_id, claim=token)
        response = self.db.settle(effect_id, class_name, token, kind, result)
        self.db.assert_all_idle()
        if self._fair_active and not self._fair_settle_response(response, effect_id):
            return False
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
