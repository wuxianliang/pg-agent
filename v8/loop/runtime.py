"""v8/loop/runtime.py — G5: P0B minimal closed-loop driver.

Postgres-native loop with coordinator / effect-worker separation and
external IO strictly OUTSIDE transactions (spec section 3.1 six-step loop,
section 6 P0B):

    (1) claim session lease
    (2) single tx: assemble + initial decision seal (v_prepare_step creates
        step + LLM slot + the unique FIRST attempt in the same transaction)
    (3) commit
    (4) effect worker reads the persisted descriptor outside any tx
        (SELECT effect/attempt snapshot -> EffectDescriptor-shaped dict),
        executes the fake provider call outside any tx, then dispatch and
        complete each in their own single transaction
    (5) complete tx: evidence classification + SQL-generated
        assistant/message + step/session aggregation (G4)
    (6) coordinator claims again -> decision_only closed turn ->
        finish_session (completed) or wait/yield

No memory truth: every command envelope re-reads the authoritative
fence/epoch/next_seq from the database right before use (the worker holds
no session truth; spec "worker does not hold session truth").

Chaos support (kill-at-every-boundary): run_user_message(..., kill_after=b)
performs everything up to and including boundary b, then simulates process
death (ProcessDeath; all connections dropped, nothing rolled forward). The
two extra MID_TX_KILLS simulate a crash INSIDE the seal / complete
transaction (the open tx is rolled back exactly as a dead backend's would
be), which is why they sit "before" those boundaries' commits.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Callable

import psycopg2

from v8.canonical import canonicalize, escape_dollar_keys
from v8.effect.client import (
    claim_session,
    complete_effect,
    dispatch_effect,
    finish_session,
    prepare_step,
    recovery_claim_session,
    yield_session,
)
from v8.events.client import (
    build_entry,
    call_append_events,
    create_session,
)
from v8.tools.client import (
    build_tool_slots,
    complete_tool_effect,
    seal_batch,
)

SCHEMA_VERSION = "sv@1"
CANONICALIZER_VERSION = "canon@1"

# Chaos kill points (P0B acceptance): run until the boundary's commit has
# landed, then die. MID_TX_KILLS die inside the named transaction instead
# (before its commit) — a dead process leaves the same rolled-back state.
BOUNDARIES = [
    "after_user_append",
    "after_claim",
    "after_seal_commit",
    "after_worker_read",
    "after_fake_llm",
    "after_complete_commit",
    "after_finish_commit",
]
MID_TX_KILLS = [
    "mid_tx_before_seal_commit",
    "mid_tx_before_complete_commit",
]
# G6 adds the tools-phase boundaries. They are kept OUT of BOUNDARIES /
# MID_TX_KILLS / ALL_KILL_POINTS (whose shapes are asserted frozen by the
# G5 gate, and which the G5 chaos loop drives with plain no-tools messages
# that never reach the tools path): they only fire when a turn actually
# enters the tools path (user text carrying TOOL_MARKER), and the G6 gate
# exercises them via TOOLS_KILL_POINTS plus the shared worker boundaries.
TOOLS_BOUNDARIES = ["after_tools_seal_commit"]
TOOLS_MID_TX_KILLS = ["mid_tx_before_tools_seal_commit"]
TOOLS_KILL_POINTS = TOOLS_BOUNDARIES + TOOLS_MID_TX_KILLS
ALL_KILL_POINTS = BOUNDARIES + MID_TX_KILLS

TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_OPEN_SESSION_STATES = frozenset({
    "ready", "claimed", "waiting_effect", "waiting_event", "sleeping",
    "cancel_requested", "blocked_unknown_effect",
})

BoundaryHook = Callable[[dict], None]


class ProcessDeath(RuntimeError):
    """Simulated process death at a chaos kill point (connections dropped)."""

    def __init__(self, point: str):
        self.point = point
        super().__init__(f"simulated process death at {point}")


class _DyingConnection:
    """Connection proxy simulating process death mid-transaction.

    The first commit() rolls the real transaction back and raises
    ProcessDeath: a dead backend's open transaction is rolled back by the
    server, so the persisted state after this is exactly a mid-tx crash.
    """

    def __init__(self, conn, point: str):
        self._conn = conn
        self._point = point
        self.autocommit = conn.autocommit

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        self._conn.rollback()
        raise ProcessDeath(self._point)

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


class FakeLLM:
    """Deterministic fake provider (spec section 6 Conformance 12).

    generate() is the external-IO point and MUST run outside any open
    transaction. All outputs are seeded by the DB-truth prompt ONLY — never
    by run-specific ids — so a chaos rerun with a fresh process reproduces
    byte-equal semantic output.

    Two-decision shape (G6, "tools -> re-decide -> answer"): when the
    assembled prompt of the turn still has NO tool results and the user
    text carries TOOL_MARKER ("use_tool"), the decision returns a NON-EMPTY
    tools plan (decision_only=false, final_tools=true) referencing the fake
    tool — ``tool_calls`` identical calls (same tool, same arguments, only
    tool_call_id differing), exercising the slot-level occurrence identity
    of one batch. Once the turn carries tool results (the sealed tools
    batch settled), the decision returns the final answer with an EMPTY
    plan (decision_only=true, final_tools=false — the P0B closing shape).

    injected_fault: None | "provider_error" | "timeout". Both fault forms
    produce NO bound terminal provider receipt, so settlement classifies
    unknown (G4 unique evidence classification); P0B has no retry/deadline
    machinery, the difference is only the evidence payload.
    """

    TOOL_MARKER = "use_tool"

    def __init__(self, injected_fault: str | None = None,
                 tool_calls: int = 2):
        if injected_fault not in (None, "provider_error", "timeout"):
            raise ValueError(
                f"injected_fault must be None|provider_error|timeout, "
                f"got {injected_fault!r}")
        if tool_calls < 1:
            raise ValueError(f"tool_calls must be >= 1, got {tool_calls}")
        self.injected_fault = injected_fault
        self.tool_calls = tool_calls

    def generate(self, descriptor: dict) -> dict:
        prompt = (descriptor.get("prompt") or {})
        seed = prompt.get("seed_text") or ""
        if self.injected_fault is not None:
            return {
                "outcome": "unknown_outcome",
                "message": {"text": ""},
                "tools": [],
                "decision_only": False,
                "final_tools": False,
                "evidence": {"class": self.injected_fault,
                             "detail": "no bound terminal provider receipt"},
                "result_payload": {"error": {"kind": self.injected_fault}},
            }
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        # Second decision of a tools turn: the sealed tools batch has
        # settled (DB truth in the assembled prompt) -> final answer with
        # an empty plan.
        if prompt.get("tool_results"):
            message = {"text": f"fake-final:{seed}", "model": "fake-llm@1",
                       "seed": digest[:16]}
            return {
                "outcome": "succeeded",
                "message": message,
                "tools": [],                 # empty plan -> decision_only close
                "decision_only": True,
                "final_tools": False,
                "evidence": {"class": "known_success",
                             "provider_receipt": {"receipt_id": f"fake-pr-{digest[:24]}"}},
            }
        # First decision of a tools turn: non-empty plan referencing the
        # fake tool (tool_calls identical calls — only tool_call_id differs).
        if self.TOOL_MARKER in seed:
            tools = [
                {"tool_call_id": f"call-{digest[:16]}-{i}",
                 "tool": "fake_tool",
                 "arguments": {"echo": seed}}
                for i in range(self.tool_calls)
            ]
            message = {"text": f"fake-plan:{seed}", "model": "fake-llm@1",
                       "seed": digest[:16]}
            return {
                "outcome": "succeeded",
                "message": message,
                "tools": tools,
                "decision_only": False,
                "final_tools": True,
                "evidence": {"class": "known_success",
                             "provider_receipt": {"receipt_id": f"fake-pr-{digest[:24]}"}},
            }
        message = {"text": f"fake-final:{seed}", "model": "fake-llm@1",
                   "seed": digest[:16]}
        return {
            "outcome": "succeeded",
            "message": message,
            "tools": [],                 # empty plan -> decision_only close
            "decision_only": True,
            "final_tools": False,
            "evidence": {"class": "known_success",
                         "provider_receipt": {"receipt_id": f"fake-pr-{digest[:24]}"}},
        }


class FakeTool:
    """Deterministic fake tool executor (spec section 6 Conformance 12).

    execute() is the external-IO point and MUST run outside any open
    transaction. The output (and the provider receipt id) is seeded by the
    persisted slot identity ONLY (tool name, tool_call_id, canonical
    arguments) — never by run-specific ids — so a chaos rerun after a death
    between dispatch and complete reproduces byte-equal results.
    """

    def execute(self, descriptor: dict) -> dict:
        call = descriptor.get("tool_call") or {}
        tool = call.get("tool") or ""
        tool_call_id = call.get("tool_call_id") or ""
        arguments = call.get("arguments")
        args_canonical, _ = canonicalize(escape_dollar_keys(arguments))
        digest = hashlib.sha256(
            f"{tool}|{tool_call_id}|{args_canonical}".encode("utf-8")).hexdigest()
        return {
            "outcome": "succeeded",
            "output": {"echo": (arguments or {}).get("echo", ""),
                       "tool": tool, "kind": "fake-tool@1"},
            "evidence": {"class": "known_success",
                         "provider_receipt": {"receipt_id": f"tool-pr-{digest[:24]}"}},
        }


# ---------------------------------------------------------------------------
# connection + read helpers (every read leaves the connection IDLE)
# ---------------------------------------------------------------------------

def _connect(db_uri: str, *, autocommit: bool = False):
    conn = psycopg2.connect(db_uri)
    conn.autocommit = autocommit
    return conn


def _settle(conn) -> None:
    """Close the implicit read tx so the connection returns to IDLE."""
    try:
        conn.rollback()
    except psycopg2.Error:
        pass


def create_loop_session(db_uri: str, session_id: str | None = None,
                        driver: str = "drv") -> str:
    session_id = str(session_id or uuid.uuid4())
    conn = _connect(db_uri)
    try:
        create_session(conn, session_id, driver)
    finally:
        conn.close()
    return session_id


def read_session(conn, session_id) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state, session_fence, driver, driver_epoch, next_seq,"
            " active_step_id, lease_owner, lease_until"
            " FROM sessions WHERE session_id = %s", (str(session_id),))
        row = cur.fetchone()
    _settle(conn)
    if row is None:
        raise RuntimeError(f"session {session_id} not found")
    (state, fence, driver, epoch, next_seq, active_step, lease_owner,
     lease_until) = row
    return {"state": state, "session_fence": fence, "driver": driver,
            "driver_epoch": epoch, "next_seq": next_seq,
            "active_step_id": active_step, "lease_owner": lease_owner,
            "lease_until": lease_until}


def session_state(db_uri: str, session_id) -> str:
    conn = _connect(db_uri, autocommit=True)
    try:
        return read_session(conn, session_id)["state"]
    finally:
        conn.close()


def current_session_fence(conn, session_id) -> int:
    """Authoritative fence re-read (envelopes never trust memory)."""
    with conn.cursor() as cur:
        cur.execute("SELECT session_fence FROM sessions WHERE session_id = %s",
                    (str(session_id),))
        row = cur.fetchone()
    _settle(conn)
    if row is None:
        raise RuntimeError(f"session {session_id} not found")
    return row[0]


def open_turn_info(conn, session_id) -> dict:
    """DB-truth turn bookkeeping: which turn the session is on, whether it
    is closed (any turn/end persisted — known or provisional), whether its
    user/message is already appended, and the next public ordinal.

    The current turn is derived from the last event CARRYING a turn
    attribution, not from the last event: session/heartbeat (the one
    whitelisted type with fixed NULL turn attribution, P01) is legal on any
    non-terminal state, and a heartbeat landing mid-loop or between turns
    must never wedge the loop by masking the attributed tail. next_ordinal
    is session-wide (public ordinals are unique per session, not per turn).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT turn_id FROM session_events WHERE session_id = %s"
            " AND turn_id IS NOT NULL ORDER BY seq DESC LIMIT 1",
            (str(session_id),))
        row = cur.fetchone()
    _settle(conn)
    if row is None:
        return {"turn_id": None, "closed": True, "has_user_message": False,
                "next_ordinal": 1}
    turn = row[0]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM session_events WHERE session_id=%s"
            " AND turn_id=%s AND event_type='turn/end'),"
            " EXISTS(SELECT 1 FROM session_events WHERE session_id=%s"
            " AND turn_id=%s AND event_type='user/message'),"
            " coalesce(max(semantic_input_ordinal), 0) + 1"
            " FROM session_events WHERE session_id=%s",
            (str(session_id), str(turn), str(session_id), str(turn),
             str(session_id)))
        closed, has_user, next_ord = cur.fetchone()
    _settle(conn)
    return {"turn_id": str(turn), "closed": bool(closed),
            "has_user_message": bool(has_user), "next_ordinal": next_ord}


def _last_user_text(conn, session_id, turn_id) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM session_events WHERE session_id = %s"
            " AND turn_id = %s AND event_type = 'user/message'"
            " ORDER BY semantic_input_ordinal DESC LIMIT 1",
            (str(session_id), str(turn_id)))
        row = cur.fetchone()
    _settle(conn)
    return None if row is None else json.loads(row[0]).get("text")


def _no_open_step(conn, session_id) -> bool:
    """True when create_step's guard would pass (no non-terminal step)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT s.active_step_id IS NULL"
            " OR st.status IN ('succeeded','failed_terminal','cancelled')"
            " FROM sessions s LEFT JOIN steps st ON st.step_id = s.active_step_id"
            " WHERE s.session_id = %s", (str(session_id),))
        ok = cur.fetchone()[0]
    _settle(conn)
    return bool(ok)


def _executable_effect(conn, session_id) -> tuple[str, str] | None:
    """The active step's pending effect (ready or dispatch_started)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT er.effect_id, er.status FROM effect_requests er"
            " WHERE er.session_id = %s"
            " AND er.step_id = (SELECT active_step_id FROM sessions"
            "                    WHERE session_id = %s)"
            " AND er.status IN ('ready', 'dispatch_started')"
            " ORDER BY er.dispatch_ordinal LIMIT 1",
            (str(session_id), str(session_id)))
        row = cur.fetchone()
    _settle(conn)
    return None if row is None else (str(row[0]), row[1])


def _wait_out_lease(conn, session_id, max_seconds: float = 15.0) -> None:
    """Wait until the lease slot is vacant/expired (DB-side comparison, no
    app/DB clock-skew window)."""
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT lease_until IS NULL OR lease_until <= now()"
                " FROM sessions WHERE session_id = %s", (str(session_id),))
            vacant = cur.fetchone()[0]
        _settle(conn)
        if vacant:
            return
        time.sleep(0.05)


def _fire(on_boundary: BoundaryHook | None, info: dict) -> None:
    if on_boundary is not None:
        on_boundary(info)


def _die_or_fire(point: str, kill_after: str | None,
                 on_boundary: BoundaryHook | None, info: dict) -> None:
    """Fire the boundary hook, then simulate death if this is the kill point."""
    _fire(on_boundary, {"boundary": point, **info})
    if kill_after == point:
        raise ProcessDeath(point)


# ---------------------------------------------------------------------------
# phase A: user input append (+turn/start when the turn is not open yet)
# ---------------------------------------------------------------------------

def append_user_message(
    db_uri: str, session_id, text: str, *, driver: str = "drv",
    driver_epoch: int = 1, command_id: str | None = None,
    on_boundary: BoundaryHook | None = None, kill_after: str | None = None,
) -> dict:
    """Append user/message — with turn/start first when a new turn opens.

    Idempotent for chaos reruns: when the still-open turn already carries
    its user/message (a previous run died right after the append), nothing
    is appended; the caller continues from the persisted truth.
    """
    conn = _connect(db_uri)
    try:
        info = open_turn_info(conn, session_id)
        if info["turn_id"] is not None and not info["closed"] \
                and info["has_user_message"]:
            return {"appended": False, "turn_id": info["turn_id"],
                    "command_id": None, "receipt": None}
        if info["turn_id"] is not None and info["closed"] \
                and _last_user_text(conn, session_id,
                                    info["turn_id"]) == text:
            # The closed turn already delivered THIS text but the loop has
            # not finished (a chaos rerun of the same message): no new
            # turn — the caller only needs to drive the loop to completion.
            # A DIFFERENT text is a genuinely new turn (multi-turn).
            return {"appended": False, "turn_id": info["turn_id"],
                    "command_id": None, "receipt": None}
        next_seq = read_session(conn, session_id)["next_seq"]
        turn = info["turn_id"] if not info["closed"] else str(uuid.uuid4())
        ordinal = info["next_ordinal"]
        entries = []
        if info["closed"]:
            # previous turn closed (or none yet): open a new turn first
            entries.append(build_entry(
                "turn/start", {"reason": "user_message"},
                schema_version=SCHEMA_VERSION,
                canonicalizer_version=CANONICALIZER_VERSION,
                turn_id=turn, semantic_input_ordinal=ordinal))
            ordinal += 1
        entries.append(build_entry(
            "user/message", {"text": text},
            schema_version=SCHEMA_VERSION,
            canonicalizer_version=CANONICALIZER_VERSION,
            turn_id=turn, semantic_input_ordinal=ordinal))
        cmd = command_id or f"usr-{uuid.uuid4()}"
        r = call_append_events(conn, session_id, cmd, driver, driver_epoch,
                               next_seq, entries)
        if r["outcome"] != "accepted":
            raise RuntimeError(f"user append rejected: {r}")
        _die_or_fire("after_user_append", kill_after, on_boundary,
                     {"append": r, "turn_id": turn})
        return {"appended": True, "turn_id": turn, "command_id": cmd,
                "receipt": r}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# phase B step (1): claim / recovery claim
# ---------------------------------------------------------------------------

def acquire_lease(conn, session_id, *, driver: str = "drv",
                  driver_epoch: int = 1, lease_owner: str | None = None,
                  lease_seconds: int = 2, attempts: int = 4) -> dict:
    """Step (1): claim the coordination lease.

    Normal claim covers ready -> claimed. A non-ready business state
    (waiting_effect: the seal already revoked the lease) or a lease held by
    a dead holder falls back to the recovery claim (any non-terminal state,
    lease slot vacant/expired only, business state untouched). Returns the
    claimed result dict extended with the lease_owner actually used (or the
    terminal rejection as-is).
    """
    owner = lease_owner or f"{driver}#{uuid.uuid4().hex[:8]}"
    for _ in range(attempts):
        # Old-fence CAS (v_claim_session optional check): the expected fence
        # is re-read from the DB right before the claim, so a lease taken
        # after a concurrent fence bump is refused as stale instead of
        # silently succeeding; the retry loop re-reads and converges.
        r = claim_session(conn, session_id, driver, driver_epoch,
                          lease_owner=owner, lease_seconds=lease_seconds,
                          expected_session_fence=current_session_fence(
                              conn, session_id))
        if r["outcome"] == "claimed":
            return {**r, "lease_owner": owner}
        if r.get("code") == "SESSION_TERMINAL":
            return {**r, "lease_owner": owner}
        if r.get("code") not in ("LEASE_HELD", "SESSION_NOT_READY",
                                 "SESSION_FENCE_STALE"):
            raise RuntimeError(f"claim failed: {r}")
        _wait_out_lease(conn, session_id)
        rr = recovery_claim_session(conn, session_id, driver, driver_epoch,
                                    lease_owner=owner,
                                    lease_seconds=lease_seconds)
        if rr["outcome"] == "claimed":
            return {**rr, "lease_owner": owner}
        if rr.get("code") != "LEASE_HELD":
            raise RuntimeError(f"recovery claim failed: {rr}")
    raise RuntimeError("lease acquisition did not converge")


def yield_lease(conn, session_id, *, driver: str = "drv",
                driver_epoch: int = 1, lease_owner: str | None = None) -> dict:
    """G11: the coordinator's EXPLICIT yield. The NO_ACTIVE_GENERATION
    assemble rejection never releases the lease itself (zero control-state
    change); a rejected coordinator calls this independently to return the
    session to ready and wait for the operator's pointer disposition."""
    st = read_session(conn, session_id)
    return yield_session(conn, session_id, driver, driver_epoch,
                         st["session_fence"],
                         lease_owner or st["lease_owner"])


# ---------------------------------------------------------------------------
# phase B steps (2)+(3): assemble + initial decision seal (one tx)
# ---------------------------------------------------------------------------

def assemble_generation(conn, session_id) -> dict:
    """G11 §4 assemble-side pointer resolution: a new assemble binds the
    session's active_catalog_generation to the CURRENT catalog active
    pointer. While the pointer is cleared (operator explicit disposition)
    the assemble is STABLY rejected NO_ACTIVE_GENERATION with ZERO
    control-state change — the session keeps its state, coordination lease
    and fence exactly as the requesting transaction found them; the
    coordinator returns to ready only through an EXPLICIT yield
    (yield_lease below)."""
    with conn.cursor() as cur:
        cur.execute("SELECT v_assemble_bind_generation(%s::uuid)",
                    (str(session_id),))
        out = cur.fetchone()[0]
    conn.commit()
    return out


def assemble_prompt(conn, session_id, turn_id) -> dict:
    """P0B assemble: the open turn's DB-truth context.

    User texts (public input), the turn's SQL-generated assistant final
    messages and the seal-generated tool/call slots plus their tool/result
    settlements — everything read from the persisted event log, in internal
    semantic order. The second decision of a tools turn therefore assembles
    with the settled tool results present, which is what tells the fake
    provider to answer instead of re-planning.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM session_events WHERE session_id = %s"
            " AND turn_id = %s AND event_type = 'user/message'"
            " ORDER BY semantic_input_ordinal",
            (str(session_id), str(turn_id)))
        texts = [json.loads(row[0]).get("text", "") for row in cur.fetchall()]
        cur.execute(
            "SELECT payload FROM session_events WHERE session_id = %s"
            " AND turn_id = %s AND event_type = 'assistant/message'"
            " ORDER BY internal_semantic_ordinal",
            (str(session_id), str(turn_id)))
        finals = [json.loads(row[0]).get("text", "") for row in cur.fetchall()]
        cur.execute(
            "SELECT payload FROM session_events WHERE session_id = %s"
            " AND turn_id = %s AND event_type = 'tool/call'"
            " ORDER BY internal_semantic_ordinal",
            (str(session_id), str(turn_id)))
        calls = [json.loads(row[0]) for row in cur.fetchall()]
        cur.execute(
            "SELECT payload FROM session_events WHERE session_id = %s"
            " AND turn_id = %s AND event_type = 'tool/result'"
            " ORDER BY internal_semantic_ordinal",
            (str(session_id), str(turn_id)))
        results = [json.loads(row[0]) for row in cur.fetchall()]
    _settle(conn)
    seed = "\n".join(texts)
    return {"messages": [{"role": "user", "text": t} for t in texts],
            "seed_text": seed,
            "assistant_messages": finals,
            "tool_calls": calls,
            "tool_results": results}


def _slot_identity(prompt: dict) -> tuple[str, str]:
    """Deterministic request_hash / idempotency_key from the assembled
    prompt (chaos reruns reproduce identical slot identity)."""
    text, _ = canonicalize(escape_dollar_keys(prompt))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"llm-req-{digest[:40]}", f"llm-ik-{digest[:40]}"


def seal_decision_step(
    conn, session_id, turn_id, *, driver: str, driver_epoch: int,
    session_fence: int, prompt: dict, command_id: str | None = None,
    step_id=None, effect_id=None,
) -> dict:
    """Single-tx initial decision seal (v_prepare_step): create_step + LLM
    slot + unique first attempt + publish-as-ready, committed together."""
    step_id = str(step_id or uuid.uuid4())
    effect_id = str(effect_id or uuid.uuid4())
    request_hash, idempotency_key = _slot_identity(prompt)
    cmd = command_id or f"seal-{uuid.uuid4()}"
    r = prepare_step(conn, session_id, cmd, driver, driver_epoch,
                     session_fence, step_id, turn_id, effect_id,
                     effect_kind="llm", execution_mode="non_streaming",
                     retry_class="unsafe", max_attempts=1,
                     request_hash=request_hash,
                     idempotency_key=idempotency_key)
    return {"command_id": cmd, "result": r, "step_id": step_id,
            "effect_id": effect_id}


# ---------------------------------------------------------------------------
# G6: tools seal phase — a step holding an accepted tools-plan decision
# result (status=ready, stage=decision) waits for its sealed tools batch
# ---------------------------------------------------------------------------

def tools_sealable_step(conn, session_id) -> dict | None:
    """The active step awaiting the tools seal (ready + stage=decision)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT st.step_id, st.sealed_batch_no, st.plan_canonical,"
            " st.plan_hash FROM steps st"
            " JOIN sessions s ON s.active_step_id = st.step_id"
            " WHERE s.session_id = %s AND st.status = 'ready'"
            " AND st.stage = 'decision'",
            (str(session_id),))
        row = cur.fetchone()
    _settle(conn)
    if row is None:
        return None
    return {"step_id": str(row[0]), "sealed_batch_no": row[1],
            "plan_canonical": row[2], "plan_hash": row[3]}


def decision_result_identity(conn, session_id, step_id) -> dict:
    """The accepted decision result identity of a step's decision batch:
    (effect_id, attempt_no, result_hash, event_key) — the event_key of the
    SQL-generated assistant/message event, all read from persisted truth."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT er.effect_id, er.attempt_no, er.result_hash,"
            " (SELECT se.event_key FROM session_events se"
            "  WHERE se.session_id = %s AND se.event_type = 'assistant/message'"
            "  AND se.effect_id = er.effect_id"
            "  AND se.attempt_no = er.attempt_no LIMIT 1)"
            " FROM effect_requests er JOIN batches b ON b.batch_id = er.batch_id"
            " WHERE er.step_id = %s AND b.kind = 'decision'",
            (str(session_id), str(step_id)))
        row = cur.fetchone()
    _settle(conn)
    if row is None or row[3] is None:
        raise RuntimeError(
            f"no accepted decision result identity for step {step_id}")
    return {"effect_id": str(row[0]), "attempt_no": row[1],
            "result_hash": row[2], "event_key": row[3]}


def seal_tools_step(
    conn, session_id, *, driver: str, driver_epoch: int,
    session_fence: int, step: dict, command_id: str | None = None,
) -> dict:
    """Single-tx tools seal (v_seal_batch): manifest built from the
    PERSISTED plan (DB truth, never memory), decision identity verified,
    batch + tool effects + first attempts + tool/call events committed
    together."""
    plan = json.loads(step["plan_canonical"])
    slots = build_tool_slots(plan)
    decision = decision_result_identity(conn, session_id, step["step_id"])
    cmd = command_id or f"tseal-{uuid.uuid4()}"
    r = seal_batch(conn, session_id, cmd, driver, driver_epoch,
                   session_fence, step["step_id"], step["sealed_batch_no"],
                   decision, step["plan_hash"], slots)
    return {"command_id": cmd, "result": r, "slots": slots,
            "decision": decision}


# ---------------------------------------------------------------------------
# phase B steps (4)+(5): effect worker (read + provider IO outside tx,
# dispatch + complete each a single tx on a separate write connection)
# ---------------------------------------------------------------------------

def read_effect_descriptor(conn, session_id, effect_id) -> dict | None:
    """SELECT effect/attempt snapshot -> EffectDescriptor-shaped dict.

    This read (plus the prompt assembled from persisted events) is the
    worker's ONLY truth; it runs outside any transaction.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT er.effect_id, er.session_id, er.step_id, er.batch_id,"
            " st.turn_id, er.dispatch_ordinal, er.effect_kind,"
            " er.execution_mode, er.driver, er.driver_epoch, er.session_fence,"
            " er.dispatch_session_fence, er.current_job_fence,"
            " er.request_hash, er.idempotency_key, er.status, er.attempt_no,"
            " er.retry_class, er.max_attempts,"
            " a.status AS attempt_status, a.dispatch_job_fence"
            " FROM effect_requests er"
            " JOIN steps st ON st.step_id = er.step_id"
            " LEFT JOIN effect_attempts a"
            " ON a.effect_id = er.effect_id AND a.attempt_no = er.attempt_no"
            " WHERE er.session_id = %s AND er.effect_id = %s",
            (str(session_id), str(effect_id)))
        row = cur.fetchone()
    _settle(conn)
    if row is None:
        return None
    keys = ["effect_id", "session_id", "step_id", "batch_id", "turn_id",
            "dispatch_ordinal", "effect_kind", "execution_mode", "driver",
            "driver_epoch", "session_fence", "dispatch_session_fence",
            "current_job_fence", "request_hash", "idempotency_key", "status",
            "attempt_no", "retry_class", "max_attempts", "attempt_status",
            "dispatch_job_fence"]
    descriptor = dict(zip(keys, row))
    descriptor["effect_id"] = str(descriptor["effect_id"])
    descriptor["session_id"] = str(descriptor["session_id"])
    descriptor["step_id"] = str(descriptor["step_id"])
    descriptor["batch_id"] = str(descriptor["batch_id"])
    descriptor["turn_id"] = str(descriptor["turn_id"])
    descriptor["prompt"] = assemble_prompt(
        conn, session_id, descriptor["turn_id"])
    if descriptor["effect_kind"] == "tool":
        # The sealed slot's tool/call payload is the worker's execution
        # input (tool name, arguments, tool_call_id) — read from the
        # seal-generated event, outside any transaction.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM session_events WHERE session_id = %s"
                " AND event_type = 'tool/call' AND effect_id = %s"
                " ORDER BY seq LIMIT 1",
                (str(session_id), str(effect_id)))
            trow = cur.fetchone()
        _settle(conn)
        if trow is None:
            raise RuntimeError(
                f"tool effect {effect_id} has no persisted tool/call event")
        descriptor["tool_call"] = json.loads(trow[0])
    return descriptor


def worker_execute(
    db_uri: str, session_id, effect_id, *, driver: str = "drv",
    driver_epoch: int = 1, fake_llm: FakeLLM | None = None,
    fake_tool: FakeTool | None = None,
    command_ids: dict[str, str] | None = None,
    on_boundary: BoundaryHook | None = None, kill_after: str | None = None,
) -> dict:
    """Steps (4)+(5) for one persisted effect (LLM decision or sealed tool
    slot).

    read (autocommit conn, outside tx) -> external provider IO outside tx
    (FakeLLM for decision slots, FakeTool for tool slots) -> dispatch
    (single tx) -> complete (single tx). Read and write use two separate
    connections; the complete transaction contains nothing but the
    settlement command. A rerun after a death between dispatch and complete
    resumes at the provider call (dispatch_started effects skip the gate).
    """
    fake_llm = fake_llm or FakeLLM()
    fake_tool = fake_tool or FakeTool()
    command_ids = command_ids or {}
    read_conn = _connect(db_uri, autocommit=True)
    write_conn = _connect(db_uri)
    try:
        descriptor = read_effect_descriptor(read_conn, session_id, effect_id)
        if descriptor is None:
            raise RuntimeError(f"effect {effect_id} not persisted")
        _die_or_fire("after_worker_read", kill_after, on_boundary, {
            "descriptor": descriptor, "read_conn": read_conn,
            "write_conn": write_conn,
            "read_autocommit": read_conn.autocommit,
            "read_status": read_conn.status,
            "write_status": write_conn.status})

        # External IO point: no connection of this worker holds a tx here.
        tx_status_at_llm = (read_conn.status, write_conn.status)
        if descriptor["effect_kind"] == "tool":
            result = fake_tool.execute(descriptor)
        else:
            result = fake_llm.generate(descriptor)
        _die_or_fire("after_fake_llm", kill_after, on_boundary, {
            "result": result, "descriptor": descriptor,
            "read_conn": read_conn, "write_conn": write_conn,
            "read_autocommit": read_conn.autocommit,
            "tx_status_at_llm": tx_status_at_llm})

        if descriptor["status"] == "ready":
            fence = current_session_fence(write_conn, session_id)
            dispatch_cmd = command_ids.get(
                "dispatch") or f"dsp-{uuid.uuid4()}"
            rd = dispatch_effect(write_conn, session_id, dispatch_cmd,
                                 effect_id, driver, driver_epoch, fence,
                                 descriptor["current_job_fence"])
            if rd["outcome"] != "accepted":
                raise RuntimeError(f"dispatch rejected: {rd}")
        elif descriptor["status"] == "dispatch_started":
            rd = None  # a previous (dead) worker already passed the gate
        else:
            raise RuntimeError(
                f"effect not executable: {descriptor['status']}")

        complete_conn = (
            _DyingConnection(_connect(db_uri), kill_after)
            if kill_after == "mid_tx_before_complete_commit" else write_conn)
        try:
            status_before_complete = write_conn.status
            complete_cmd = command_ids.get(
                "complete") or f"cmp-{uuid.uuid4()}"
            if descriptor["effect_kind"] == "tool":
                rc = complete_tool_effect(
                    complete_conn, session_id, complete_cmd, effect_id,
                    descriptor["driver"], descriptor["driver_epoch"],
                    dispatch_session_fence=descriptor["dispatch_session_fence"],
                    job_fence=descriptor["current_job_fence"],
                    attempt_no=descriptor["attempt_no"],
                    step_id=descriptor["step_id"],
                    request_hash=descriptor["request_hash"],
                    idempotency_key=descriptor["idempotency_key"],
                    outcome=result["outcome"],
                    tool_call_id=descriptor["tool_call"]["tool_call_id"],
                    output=result["output"],
                    evidence=result["evidence"])
            else:
                rc = complete_effect(
                    complete_conn, session_id, complete_cmd, effect_id,
                    descriptor["driver"], descriptor["driver_epoch"],
                    dispatch_session_fence=descriptor["dispatch_session_fence"],
                    job_fence=descriptor["current_job_fence"],
                    attempt_no=descriptor["attempt_no"],
                    step_id=descriptor["step_id"],
                    request_hash=descriptor["request_hash"],
                    idempotency_key=descriptor["idempotency_key"],
                    outcome=result["outcome"],
                    message=result["message"], tools=result["tools"],
                    decision_only=result["decision_only"],
                    final_tools=result["final_tools"],
                    evidence=result["evidence"],
                    result_payload=result.get("result_payload"))
            if rc["outcome"] != "accepted":
                raise RuntimeError(f"complete rejected: {rc}")
        finally:
            if kill_after == "mid_tx_before_complete_commit":
                complete_conn.close()
        status_after_complete = write_conn.status
        _die_or_fire("after_complete_commit", kill_after, on_boundary, {
            "dispatch": rd, "complete": rc, "descriptor": descriptor,
            "write_conn": write_conn,
            "status_before_complete": status_before_complete,
            "status_after_complete": status_after_complete})
        return {"descriptor": descriptor, "dispatch": rd, "complete": rc}
    finally:
        read_conn.close()
        write_conn.close()


# ---------------------------------------------------------------------------
# phase B step (6): claim again -> finish (or wait)
# ---------------------------------------------------------------------------

def finish_loop(conn, session_id, *, driver: str, driver_epoch: int,
                session_fence: int, command_id: str | None = None) -> dict:
    """finish_session wrapper (claimed -> completed; the ONLY completed
    entry in the transition table)."""
    cmd = command_id or f"fin-{uuid.uuid4()}"
    r = finish_session(conn, session_id, cmd, driver, driver_epoch,
                       session_fence)
    return {"command_id": cmd, "result": r}


# ---------------------------------------------------------------------------
# advance_session — one section 3.1 six-step iteration
# ---------------------------------------------------------------------------

def advance_session(
    db_uri: str, session_id, *, driver: str = "drv", driver_epoch: int = 1,
    fake_llm: FakeLLM | None = None, fake_tool: FakeTool | None = None,
    finish: bool = True,
    kill_after: str | None = None, on_boundary: BoundaryHook | None = None,
    lease_seconds: int = 2, lease_owner: str | None = None,
) -> dict:
    """One six-step iteration over (at most) one sealed batch.

    Step (1)'s claim exists to protect the seal (the coordination write):
    when the iteration only RESUMES the worker phase on an already-sealed
    effect (a chaos rerun after after_seal_commit), dispatch/complete are
    fence-guarded and need no lease — the worker phase runs lease-free and
    step (6) claims fresh from ready. G6 adds the tools-seal iteration: a
    step holding an accepted tools-plan decision result (ready,
    stage=decision) is sealed as a tools batch by the coordinator (claim ->
    v_seal_batch in one tx), and after a final_tools batch settles the loop
    continues with the NEXT decision step (an extra decision is always a
    NEW step) until a decision_only step closes the turn. Returns
    {"state", "progress", "actions"}: progress False means the iteration
    found no work (loop guard — e.g. blocked_unknown_effect after an
    unknown settlement, which P0B cannot repair).
    """
    fake_llm = fake_llm or FakeLLM()
    fake_tool = fake_tool or FakeTool()
    coord = _connect(db_uri)
    actions: list[str] = []
    try:
        st = read_session(coord, session_id)
        if st["state"] in TERMINAL_STATES:
            return {"state": st["state"], "progress": False,
                    "actions": actions}
        turn_info = open_turn_info(coord, session_id)

        # loop guard: is there anything this iteration can do?
        sealable = (not turn_info["closed"]
                    and _no_open_step(coord, session_id))
        tools = tools_sealable_step(coord, session_id)
        effect = _executable_effect(coord, session_id)
        finishable = (turn_info["closed"] and st["state"] == "ready"
                      and finish)
        if not (sealable or tools is not None or effect is not None
                or finishable):
            return {"state": st["state"], "progress": False,
                    "actions": actions}

        if sealable:
            # (1) claim lease
            claim = acquire_lease(coord, session_id, driver=driver,
                                  driver_epoch=driver_epoch,
                                  lease_owner=lease_owner,
                                  lease_seconds=lease_seconds)
            if claim["outcome"] != "claimed":
                raise RuntimeError(f"lease acquisition failed: {claim}")
            actions.append("claim")
            _die_or_fire("after_claim", kill_after, on_boundary,
                         {"claim": claim})

            # G11 §4: the assemble resolves the catalog active generation
            # first — a cleared pointer is a STABLE NO_ACTIVE_GENERATION
            # rejection with zero control-state change (the session keeps
            # its claimed state, lease and fence; only an explicit yield
            # returns it to ready).
            gen_guard = assemble_generation(coord, session_id)
            if gen_guard.get("code") == "NO_ACTIVE_GENERATION":
                actions.append("assemble_rejected")
                st_guard = read_session(coord, session_id)
                return {"state": st_guard["state"], "progress": False,
                        "actions": actions,
                        "assemble_rejection": gen_guard}

            # (2)+(3) single tx: assemble + initial decision seal
            prompt = assemble_prompt(coord, session_id,
                                     open_turn_info(coord,
                                                    session_id)["turn_id"])
            if kill_after == "mid_tx_before_seal_commit":
                real = _connect(db_uri)
                dying = _DyingConnection(real, kill_after)
                try:
                    seal_decision_step(
                        dying, session_id, turn_info["turn_id"],
                        driver=driver, driver_epoch=driver_epoch,
                        session_fence=claim["session_fence"], prompt=prompt)
                finally:
                    real.close()
                raise RuntimeError("dying seal unexpectedly committed")
            seal = seal_decision_step(
                coord, session_id, turn_info["turn_id"], driver=driver,
                driver_epoch=driver_epoch,
                session_fence=claim["session_fence"], prompt=prompt)
            if seal["result"]["outcome"] != "accepted":
                raise RuntimeError(f"seal rejected: {seal['result']}")
            actions.append("seal")
            _die_or_fire("after_seal_commit", kill_after, on_boundary,
                         {"seal": seal})

        if tools is not None:
            # G6 tools seal: claim -> v_seal_batch in one tx (manifest from
            # the persisted plan; the seal itself revokes the lease).
            claim = acquire_lease(coord, session_id, driver=driver,
                                  driver_epoch=driver_epoch,
                                  lease_owner=lease_owner,
                                  lease_seconds=lease_seconds)
            if claim["outcome"] != "claimed":
                raise RuntimeError(f"lease acquisition failed: {claim}")
            actions.append("claim")
            _die_or_fire("after_claim", kill_after, on_boundary,
                         {"claim": claim})
            if kill_after == "mid_tx_before_tools_seal_commit":
                real = _connect(db_uri)
                dying = _DyingConnection(real, kill_after)
                try:
                    seal_tools_step(
                        dying, session_id, driver=driver,
                        driver_epoch=driver_epoch,
                        session_fence=claim["session_fence"], step=tools)
                finally:
                    real.close()
                raise RuntimeError("dying tools seal unexpectedly committed")
            tseal = seal_tools_step(
                coord, session_id, driver=driver, driver_epoch=driver_epoch,
                session_fence=claim["session_fence"], step=tools)
            if tseal["result"]["outcome"] != "accepted":
                raise RuntimeError(f"tools seal rejected: {tseal['result']}")
            actions.append("tools_seal")
            _die_or_fire("after_tools_seal_commit", kill_after, on_boundary,
                         {"tools_seal": tseal})

        # (4)+(5) effect worker: read + provider IO outside tx, dispatch +
        # complete each one tx (separate worker connections; no lease)
        effect = _executable_effect(coord, session_id)
        if effect is not None:
            worker_execute(db_uri, session_id, effect[0], driver=driver,
                           driver_epoch=driver_epoch, fake_llm=fake_llm,
                           fake_tool=fake_tool,
                           on_boundary=on_boundary, kill_after=kill_after)
            actions.append("worker")

        # (6) claim again -> decision_only closed turn -> finish (or wait)
        st = read_session(coord, session_id)
        turn_info = open_turn_info(coord, session_id)
        if turn_info["closed"] and st["state"] == "ready" and finish:
            claim2 = acquire_lease(coord, session_id, driver=driver,
                                   driver_epoch=driver_epoch,
                                   lease_owner=lease_owner,
                                   lease_seconds=lease_seconds)
            if claim2["outcome"] != "claimed":
                raise RuntimeError(f"finish claim failed: {claim2}")
            fin = finish_loop(coord, session_id, driver=driver,
                              driver_epoch=driver_epoch,
                              session_fence=claim2["session_fence"])
            if fin["result"]["outcome"] != "accepted":
                raise RuntimeError(f"finish rejected: {fin['result']}")
            actions.append("finish")
            _die_or_fire("after_finish_commit", kill_after, on_boundary,
                         {"finish": fin})

        st = read_session(coord, session_id)
        return {"state": st["state"], "progress": True, "actions": actions}
    finally:
        coord.close()


# ---------------------------------------------------------------------------
# run_user_message — full round: append -> advance loop until completed
# ---------------------------------------------------------------------------

def run_user_message(
    db_uri: str, session_id, text: str, *, driver: str = "drv",
    driver_epoch: int = 1, fake_llm: FakeLLM | None = None,
    fake_tool: FakeTool | None = None, finish: bool = True,
    kill_after: str | None = None,
    on_boundary: BoundaryHook | None = None, lease_seconds: int = 2,
    max_iterations: int = 8, command_id: str | None = None,
) -> dict:
    """One full round: append user/message (+turn/start for a new turn),
    then advance until the session completes (or stalls: blocked session /
    finish deferred). Multi-turn: when the previous turn is closed and the
    session not terminal, a new turn opens on the next call.

    kill_after (chaos): die right after the named boundary's commit (or
    inside the tx for MID_TX_KILLS); ProcessDeath propagates to the caller.
    """
    fake_llm = fake_llm or FakeLLM()
    state = session_state(db_uri, session_id)
    if state in TERMINAL_STATES:
        return {"state": state, "appended": False, "iterations": 0}
    append = append_user_message(db_uri, session_id, text, driver=driver,
                                 driver_epoch=driver_epoch,
                                 command_id=command_id,
                                 on_boundary=on_boundary,
                                 kill_after=kill_after)
    iterations = 0
    last_state = session_state(db_uri, session_id)
    for _ in range(max_iterations):
        if last_state in TERMINAL_STATES:
            break
        r = advance_session(db_uri, session_id, driver=driver,
                            driver_epoch=driver_epoch, fake_llm=fake_llm,
                            fake_tool=fake_tool, finish=finish,
                            kill_after=kill_after, on_boundary=on_boundary,
                            lease_seconds=lease_seconds)
        iterations += 1
        last_state = r["state"]
        if not r["progress"]:
            break
    return {"state": last_state, "appended": append["appended"],
            "iterations": iterations, "turn_id": append["turn_id"]}
