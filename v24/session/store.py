"""Private session store v2.

The store is deliberately headless: it owns no Chainlit, database, provider or
runtime imports.  The UI keeps its old ``conversation_id`` call shape through
aliases, while new code addresses the same UUID as ``session_id``.

v2 is fail-closed.  A corrupt or unknown file is never replaced by an empty
store; callers must recover or restore a backup explicitly.  A v1 file is
migrated once to v2 after an O_EXCL ``.v1.bak`` copy is durably written.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

VERSION = 2
TERMINAL = frozenset({"completed", "failed", "cancelled", "blocked_unknown"})
MAX_BINDINGS = 200
MAX_RECEIPTS = 256
_STATES = frozenset({"starting", "active", "closed"})


class StoreError(RuntimeError):
    """A durable session-store invariant or migration failed."""


def now():
    return datetime.now(timezone.utc).isoformat()


def valid_uuid(value):
    if not isinstance(value, str):
        raise ValueError("invalid_uuid")
    return uuid.UUID(value)


def _fsync_directory(path):
    directory = os.open(Path(path).parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _copy_exclusive(source, target):
    """Copy source to target only if target does not exist, mode 0600."""
    target = Path(target)
    if target.exists():
        return False
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with source.open("rb") as stream, os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), 0o600)
            shutil.copyfileobj(stream, out)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    _fsync_directory(target)
    return True


def _preserve_prev(path):
    path = Path(path)
    if not path.exists():
        return
    prev = path.with_name(path.name + ".prev")
    tmp = prev.with_name(prev.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with path.open("rb") as stream, os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), 0o600)
            shutil.copyfileobj(stream, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, prev)
        _fsync_directory(prev)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_bytes(path, data, *, keep_prev=True):
    path = Path(path)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    if keep_prev:
        _preserve_prev(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        _fsync_directory(path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path, value, *, keep_prev=True):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode(), keep_prev=keep_prev)


class SessionStore:
    """Owner-thread session registry with v1 migration and v2 fail-closed load."""

    def __init__(self, data_dir, *, read_run=None):
        self.owner = threading.get_ident()
        self.path = Path(data_dir) / "sessions.json"
        self.turn_path = Path(data_dir) / "turns.jsonl"
        self.read_run = read_run
        self.sessions = []
        self.turns = []
        self.warnings = []
        self.active_session_id = None
        self.owner_epoch = 0
        self.failed = None
        self.load()

    # ---- v1 UI compatibility -------------------------------------------------

    @property
    def conversations(self):
        return self.sessions

    @conversations.setter
    def conversations(self, value):
        self.sessions = value

    @property
    def active_conversation_id(self):
        return self.active_session_id

    @active_conversation_id.setter
    def active_conversation_id(self, value):
        self.active_session_id = value

    # ---- lifecycle -----------------------------------------------------------

    def _check(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("session_thread_mismatch")

    def _fail(self, reason):
        self.failed = reason
        if reason not in self.warnings:
            self.warnings.append(reason)

    def load(self):
        self._check()
        self._load_turns()
        if not self.path.exists():
            return
        try:
            raw = self.path.read_bytes()
            data = json.loads(raw)
        except (OSError, ValueError, TypeError, UnicodeError):
            self._fail("session_store_corrupt")
            return
        if not isinstance(data, dict):
            self._fail("session_store_corrupt")
            return
        version = data.get("format_version")
        if version == 1:
            try:
                self._migrate_v1(data, raw)
            except (ValueError, KeyError, TypeError, OSError, StoreError) as exc:
                self._fail("session_migration_failed")
                raise StoreError("session_migration_failed") from exc
            return
        if version != VERSION:
            self._fail("session_store_incompatible")
            return
        rows = data.get("sessions", data.get("conversations"))
        try:
            self._validate_rows(rows)
        except (ValueError, KeyError, TypeError):
            self._fail("session_store_corrupt")
            return
        self.sessions = rows
        self.active_session_id = data.get("active_session_id", data.get("active_conversation_id"))
        self.owner_epoch = data.get("owner_epoch", 0)
        if not isinstance(self.owner_epoch, int) or self.owner_epoch < 0:
            self.owner_epoch = 0

    def _load_turns(self):
        self.turns = []
        if not self.turn_path.exists():
            return
        raw_turns = self.turn_path.read_bytes()
        repair = bool(raw_turns and not raw_turns.endswith(b"\n"))
        for line in raw_turns.splitlines():
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row["user_text"], str) or type(row["seq"]) is not int:
                    raise ValueError("invalid_turn")
                identifier = row.get("session_id", row.get("conversation_id"))
                valid_uuid(identifier)
                valid_uuid(row["run_id"])
                row["session_id"] = identifier
                row["conversation_id"] = identifier
                self.turns.append(row)
            except (ValueError, KeyError, TypeError, UnicodeError):
                self.warnings.append("turn_corrupt")
                repair = True
        previous = len(self.turns)
        self._bound_turns()
        if repair or len(self.turns) != previous:
            self._write_turns()

    def _validate_rows(self, rows):
        if not isinstance(rows, list):
            raise ValueError("invalid_sessions")
        ids = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid_session")
            sid = row.get("session_id", row.get("conversation_id"))
            valid_uuid(sid)
            if row.get("conversation_id", sid) != sid:
                raise ValueError("invalid_session_alias")
            if sid in ids:
                raise ValueError("duplicate_session")
            ids.add(sid)
            token_hash = row.get("resume_token_hash", "")
            if not isinstance(token_hash, str) or len(token_hash) != 64 or any(c not in "0123456789abcdef" for c in token_hash):
                raise ValueError("invalid_token_hash")
            if row.get("state", "starting") not in _STATES:
                raise ValueError("invalid_state")
            if not isinstance(row.get("bindings"), list):
                raise ValueError("invalid_bindings")
            for binding in row["bindings"]:
                valid_uuid(binding["scope_id"])
                valid_uuid(binding["run_id"])
            row["bindings"] = row["bindings"][-MAX_BINDINGS:]
            for field in ("run_no", "user_turn_no", "session_revision"):
                value = row.get(field, 0)
                if type(value) is not int or value < 0:
                    raise ValueError("invalid_counter")
                row[field] = value
            if not isinstance(row.get("start_index", {}), dict):
                raise ValueError("invalid_start_index")
            if not isinstance(row.get("receipts", []), list):
                raise ValueError("invalid_receipts")
            if row.get("pending_intent") is not None and not isinstance(row.get("pending_intent"), dict):
                raise ValueError("invalid_intent")
            row.setdefault("start_index", {})
            row.setdefault("receipts", [])
            row.setdefault("pending_intent", None)
            row.setdefault("counter_origin", "native_v2")
            row.setdefault("owner_principal_id", "local")
            row.setdefault("active_run_id", None)
            row.setdefault("name", sid)
            row.setdefault("model", "deepseek-flash")
            row.setdefault("created_at", now())
            row.setdefault("updated_at", row["created_at"])

    def _migrate_v1(self, data, raw):
        rows = data.get("conversations")
        if not isinstance(rows, list):
            raise ValueError("invalid_sessions")
        bak = self.path.with_name(self.path.name + ".v1.bak")
        if not bak.exists():
            atomic_bytes(bak, raw, keep_prev=False)
        if self.turn_path.exists():
            turn_bak = self.turn_path.with_name(self.turn_path.name + ".v1.bak")
            if not turn_bak.exists():
                atomic_bytes(turn_bak, self.turn_path.read_bytes(), keep_prev=False)
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid_session")
            sid = row.get("conversation_id")
            valid_uuid(sid)
            row["session_id"] = sid
            row["conversation_id"] = sid
            row.setdefault("name", sid)
            row.setdefault("state", "active" if row.get("bindings") else "starting")
            row["run_no"] = len(row.get("bindings") or [])
            row["user_turn_no"] = sum(1 for turn in self.turns if turn.get("session_id") == sid)
            row["session_revision"] = 0
            row["counter_origin"] = "legacy_approx"
            row["owner_principal_id"] = "local"
            row["start_index"] = {}
            row["receipts"] = []
            row["pending_intent"] = None
            row.setdefault("active_run_id", (row.get("active_binding") or {}).get("run_id"))
            row.setdefault("model", "deepseek-flash")
        self._validate_rows(rows)
        self.sessions = rows
        self.active_session_id = data.get("active_conversation_id")
        self.owner_epoch = 0
        self.flush()

    def flush(self):
        self._check()
        if self.failed:
            raise StoreError(self.failed)
        atomic_json(self.path, {
            "format_version": VERSION,
            "owner_epoch": self.owner_epoch,
            "active_session_id": self.active_session_id,
            "conversations": self.sessions,
        })

    # ---- lookup --------------------------------------------------------------

    def get(self, identifier):
        self._check()
        if not isinstance(identifier, str):
            return None
        return next((row for row in self.sessions
                     if row.get("session_id") == identifier or row.get("conversation_id") == identifier), None)

    def find_by_token(self, token):
        self._check()
        digest = hashlib.sha256(token.encode()).hexdigest()
        return next((row for row in self.sessions if hmac.compare_digest(row["resume_token_hash"], digest)), None)

    def start_index_key(self, principal_id, key_hash):
        return f"{principal_id}|{key_hash}"

    def get_start(self, principal_id, key_hash):
        self._check()
        return next((row["start_index"].get(self.start_index_key(principal_id, key_hash))
                     for row in self.sessions
                     if self.start_index_key(principal_id, key_hash) in row.get("start_index", {})), None)

    def get_receipt(self, session_id, op, key_hash):
        row = self.get(session_id)
        if row is None:
            return None
        for receipt in reversed(row.get("receipts", [])):
            if receipt.get("op") == op and receipt.get("key_hash") == key_hash:
                return receipt
        return None

    def begin_command(self, session_id, *, principal_id, op, key_hash, command_id,
                      normalized_request, digest, target_run_id=None,
                      pending_intent=None):
        """Persist a control intent before the backend is called."""
        self._check()
        row = self.get(session_id)
        if row is None:
            raise StoreError("not_found_or_denied")
        if row.get("owner_principal_id") != principal_id:
            raise StoreError("owner_fenced")
        for receipt in reversed(row.get("receipts", [])):
            if receipt.get("op") == op and receipt.get("key_hash") == key_hash:
                return receipt
        completed = sum(1 for receipt in row.get("receipts", [])
                        if receipt.get("phase") in ("completed", "rejected"))
        if completed >= MAX_RECEIPTS:
            self._prune_receipts(row, limit=MAX_RECEIPTS - 1)
        receipt = {
            "command_id": command_id,
            "op": op,
            "key_hash": key_hash,
            "principal_id": principal_id,
            "normalized_request": normalized_request,
            "digest": digest,
            "phase": "intent",
            "outcome": None,
            "target_run_id": target_run_id,
            "resolved_variant": None,
            "original_envelope": None,
            "frozen_deferred": False,
            "at": now(),
        }
        row.setdefault("receipts", []).append(receipt)
        if pending_intent is not None:
            row["pending_intent"] = pending_intent
        row["updated_at"] = now()
        self.flush()
        return receipt

    def complete_command(self, session_id, command_id, envelope, *, outcome="committed",
                         target_run_id=None, state=None):
        self._check()
        row = self.get(session_id)
        if row is None:
            raise StoreError("not_found_or_denied")
        receipt = next((r for r in reversed(row.get("receipts", []))
                        if r.get("command_id") == command_id), None)
        if receipt is None:
            raise StoreError("receipt_missing")
        receipt["phase"] = "completed"
        receipt["outcome"] = outcome
        receipt["original_envelope"] = envelope
        receipt["frozen_deferred"] = False
        if target_run_id is not None:
            receipt["target_run_id"] = target_run_id
        if state is not None:
            row["state"] = state
            if state == "closed":
                row["pending_intent"] = None
                row["active_run_id"] = None
        row["updated_at"] = now()
        self._prune_receipts(row)
        self.flush()

    def freeze_command(self, session_id, command_id, envelope, *, outcome="deferred",
                       state=None):
        self._check()
        row = self.get(session_id)
        if row is None:
            raise StoreError("not_found_or_denied")
        receipt = next((r for r in reversed(row.get("receipts", []))
                        if r.get("command_id") == command_id), None)
        if receipt is None:
            raise StoreError("receipt_missing")
        receipt["phase"] = "deferred"
        intent = row.get("pending_intent")
        if isinstance(intent, dict) and intent.get("command_id") == command_id:
            intent["phase"] = "deferred"
        receipt["outcome"] = outcome
        receipt["original_envelope"] = envelope
        receipt["frozen_deferred"] = True
        if state is not None:
            row["state"] = state
            if state == "closed":
                row["pending_intent"] = None
                row["active_run_id"] = None
        row["updated_at"] = now()
        self.flush()

    def complete_steer_active(self, session_id, command_id, run_id, message,
                              envelope_factory):
        self._check()
        row = self.get(session_id)
        if row is None:
            raise StoreError("not_found_or_denied")
        receipt = next((r for r in reversed(row.get("receipts", []))
                        if r.get("command_id") == command_id), None)
        if receipt is None or receipt.get("op") != "steer":
            raise StoreError("receipt_missing")
        row["user_turn_no"] = int(row.get("user_turn_no", 0)) + 1
        row["session_revision"] = int(row.get("session_revision", 0)) + 1
        row["updated_at"] = now()
        self._append_turn_memory(conversation_id=session_id, run_id=run_id,
                                 seq=self.next_turn_seq(), user_text=message)
        receipt["target_run_id"] = run_id
        receipt["resolved_variant"] = "steer_active"
        receipt["phase"] = "completed"
        receipt["outcome"] = "committed"
        receipt["original_envelope"] = envelope_factory(row)
        receipt["frozen_deferred"] = False
        self._write_turns()
        self.flush()

    def complete_steer_run(self, session_id, command_id, run_id, binding, message,
                           envelope_factory):
        self._check()
        row = self.get(session_id)
        if row is None:
            raise StoreError("not_found_or_denied")
        intent = row.get("pending_intent")
        if not isinstance(intent, dict) or intent.get("command_id") != command_id:
            raise StoreError("owner_fenced")
        row["bindings"] = [b for b in row.get("bindings", []) if b.get("run_id") != run_id] + [binding]
        row["bindings"] = row["bindings"][-MAX_BINDINGS:]
        row["active_binding"] = binding
        row["active_run_id"] = run_id
        row["run_no"] = int(row.get("run_no", 0)) + 1
        row["user_turn_no"] = int(row.get("user_turn_no", 0)) + 1
        row["state"] = "active"
        row["session_revision"] = int(row.get("session_revision", 0)) + 1
        row["updated_at"] = now()
        self._append_turn_memory(conversation_id=session_id, run_id=run_id,
                                 seq=self.next_turn_seq(), user_text=message)
        receipt = next((r for r in reversed(row.get("receipts", []))
                        if r.get("command_id") == command_id), None)
        if receipt is None or receipt.get("op") != "steer":
            raise StoreError("receipt_missing")
        receipt["target_run_id"] = run_id
        receipt["resolved_variant"] = "steer_new_run"
        receipt["phase"] = "completed"
        receipt["outcome"] = "committed"
        receipt["original_envelope"] = envelope_factory(row)
        receipt["frozen_deferred"] = False
        row["pending_intent"] = None
        self._prune_receipts(row)
        self._write_turns()
        self.flush()

    def next_turn_seq(self):
        return max((turn["seq"] for turn in self.turns), default=0) + 1

    # ---- creation / migration -------------------------------------------------

    def _new_session(self, *, session_id=None, name=None, owner_principal_id="local", **metadata):
        sid = str(valid_uuid(session_id)) if session_id else str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        row = {
            "session_id": sid,
            "conversation_id": sid,
            "name": (name or sid)[:120],
            "state": "starting",
            "resume_token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "created_at": now(),
            "updated_at": now(),
            "bindings": [],
            "active_binding": None,
            "active_run_id": None,
            "run_no": 0,
            "user_turn_no": 0,
            "counter_origin": "native_v2",
            "session_revision": 1,
            "owner_principal_id": owner_principal_id,
            "start_index": {},
            "receipts": [],
            "pending_intent": None,
            "model": "deepseek-flash",
            **metadata,
        }
        return row, token

    def new_conversation(self, *, mode=None, limits_digest=None, **scope_metadata):
        self._check()
        if self.failed:
            raise StoreError(self.failed)
        row, token = self._new_session(**scope_metadata)
        if mode is not None:
            row["mode"] = mode
        if limits_digest is not None:
            row["limits_digest"] = limits_digest
        self.sessions.append(row)
        self.active_session_id = row["session_id"]
        self.flush()
        return row, token

    def begin_start(self, *, session_id, principal_id, key_hash, command_id, run_key,
                    normalized_request, digest, name=None, metadata=None):
        """Create session + intent + start-index + receipt in one atomic write."""
        self._check()
        if self.failed:
            raise StoreError(self.failed)
        if self.get(session_id) is not None:
            raise StoreError("duplicate_session")
        row, token = self._new_session(session_id=session_id, name=name,
                                       owner_principal_id=principal_id,
                                       **(metadata or {}))
        self.owner_epoch += 1
        intent = {
            "session_id": row["session_id"],
            "command_id": command_id,
            "run_key": run_key,
            "digest": digest,
            "owner_epoch": self.owner_epoch,
            "phase": "intent",
            "started_at": now(),
        }
        row["pending_intent"] = intent
        row["start_index"][self.start_index_key(principal_id, key_hash)] = {
            "session_id": row["session_id"],
            "run_key": run_key,
            "command_id": command_id,
            "digest": digest,
            "phase": "intent",
        }
        row["receipts"].append({
            "command_id": command_id,
            "op": "start",
            "key_hash": key_hash,
            "digest": digest,
            "normalized_request": normalized_request,
            "resolved_variant": "start",
            "target_run_id": None,
            "run_request_key": run_key,
            "phase": "intent",
            "outcome": None,
            "original_envelope": None,
            "frozen_deferred": False,
            "owner_epoch": self.owner_epoch,
            "at": now(),
        })
        self.sessions.append(row)
        self.active_session_id = row["session_id"]
        self.flush()
        return row, token

    def freeze_deferred(self, session_id, command_id, envelope):
        self._check()
        row = self.get(session_id)
        if row is None:
            raise StoreError("not_found_or_denied")
        receipt = next((r for r in reversed(row.get("receipts", []))
                        if r.get("command_id") == command_id), None)
        if receipt is None or receipt.get("op") != "start":
            raise StoreError("receipt_missing")
        receipt["original_envelope"] = envelope
        receipt["frozen_deferred"] = True
        receipt["phase"] = "deferred"
        intent = row.get("pending_intent")
        if isinstance(intent, dict) and intent.get("command_id") == command_id:
            intent["phase"] = "deferred"
        receipt["outcome"] = envelope.get("error", {}).get("code") if isinstance(envelope, dict) else "deferred"
        intent = row.get("pending_intent")
        if isinstance(intent, dict):
            intent["phase"] = "deferred"
        for value in row.get("start_index", {}).values():
            if value.get("command_id") == receipt.get("command_id"):
                value["phase"] = "deferred"
        row["updated_at"] = now()
        self.flush()

    def complete_start(self, *, session_id, owner_epoch, run_id, binding, message, envelope_factory):
        """Commit bind/counters/turn/receipt/start-index in one atomic write.

        ``envelope_factory(row, run_id)`` runs after the in-memory counters and
        state are updated, so the frozen envelope carries the post-commit
        snapshot while the file is still replaced only once.
        """
        self._check()
        row = self.get(session_id)
        if row is None:
            raise StoreError("not_found_or_denied")
        intent = row.get("pending_intent")
        if not isinstance(intent, dict) or intent.get("owner_epoch") != owner_epoch:
            raise StoreError("owner_fenced")
        if not run_id:
            raise StoreError("invalid_run")
        row["bindings"] = [b for b in row.get("bindings", []) if b.get("run_id") != run_id] + [binding]
        row["bindings"] = row["bindings"][-MAX_BINDINGS:]
        row["active_binding"] = binding
        row["active_run_id"] = run_id
        row["run_no"] = int(row.get("run_no", 0)) + 1
        row["user_turn_no"] = int(row.get("user_turn_no", 0)) + 1
        row["state"] = "active"
        row["session_revision"] = int(row.get("session_revision", 0)) + 1
        row["updated_at"] = now()
        self._append_turn_memory(conversation_id=session_id, run_id=run_id,
                                 seq=self.next_turn_seq(), user_text=message)
        receipt = next((r for r in reversed(row.get("receipts", []))
                        if r.get("command_id") == intent.get("command_id")), None)
        if receipt is None:
            raise StoreError("receipt_missing")
        receipt["target_run_id"] = run_id
        receipt["phase"] = "completed"
        receipt["outcome"] = "committed"
        receipt["original_envelope"] = envelope_factory(row, run_id)
        receipt["frozen_deferred"] = False
        for value in row.get("start_index", {}).values():
            if value.get("command_id") == intent.get("command_id"):
                value["phase"] = "completed"
                value["run_id"] = run_id
        row["pending_intent"] = None
        self._prune_receipts(row)
        self._write_turns()
        self.flush()

    # ---- bind / turn compatibility -------------------------------------------

    def bind(self, conversation_id, scope_id, run_id, *, realm, workspace_root, toolset, catalog_digest,
             mode=None, limits_digest=None):
        self._check()
        row = self.get(conversation_id)
        if row is None:
            raise RuntimeError("not_found_or_denied")
        binding = {"scope_id": scope_id, "run_id": run_id, "realm": realm,
                   "workspace_root": str(Path(workspace_root).resolve()), "toolset": toolset,
                   "catalog_digest": catalog_digest, "at": now()}
        if mode is not None:
            binding["mode"] = mode
        if limits_digest is not None:
            binding["limits_digest"] = limits_digest
        known = {b.get("run_id") for b in row.get("bindings", [])}
        row["bindings"] = [b for b in row.get("bindings", []) if b.get("run_id") != run_id] + [binding]
        row["bindings"] = row["bindings"][-MAX_BINDINGS:]
        row["active_binding"] = binding
        row["active_run_id"] = run_id
        if run_id not in known:
            row["run_no"] = int(row.get("run_no", 0)) + 1
        row["state"] = "active"
        row["session_revision"] = int(row.get("session_revision", 0)) + 1
        row["updated_at"] = now()
        self.active_session_id = row["session_id"]
        self.flush()
        return binding

    def detach(self, conversation_id):
        self._check()
        row = self.get(conversation_id)
        if row:
            row["active_binding"] = None
            row["active_run_id"] = None
            row["session_revision"] = int(row.get("session_revision", 0)) + 1
            row["updated_at"] = now()
            if self.active_session_id == row["session_id"]:
                self.active_session_id = None
            self.flush()

    def remove(self, conversation_id):
        self._check()
        row = self.get(conversation_id)
        sid = row["session_id"] if row else conversation_id
        self.sessions = [r for r in self.sessions if r.get("session_id") != sid]
        if self.active_session_id == sid:
            self.active_session_id = None
        self.turns = [r for r in self.turns if r.get("session_id") != sid]
        self._write_turns()
        self.flush()

    def _bound_turns(self):
        counts = {}
        kept = []
        for row in reversed(self.turns):
            cid = row.get("session_id", row.get("conversation_id"))
            counts[cid] = counts.get(cid, 0) + 1
            if counts[cid] <= 200:
                kept.append(row)
        self.turns = list(reversed(kept))

    def _write_turns(self):
        self._check()
        atomic_bytes(self.turn_path, b"".join(
            (json.dumps(r, ensure_ascii=False) + "\n").encode() for r in self.turns))

    def _append_turn_memory(self, *, conversation_id, run_id, seq, user_text):
        row = dict(session_id=conversation_id, conversation_id=conversation_id,
                   run_id=run_id, seq=seq, user_text=user_text, created_at=now())
        self.turns.append(row)
        self._bound_turns()

    def append_turn(self, *, conversation_id, run_id, seq, user_text):
        self._check()
        previous = len(self.turns)
        self._append_turn_memory(conversation_id=conversation_id, run_id=run_id,
                                 seq=seq, user_text=user_text)
        row = self.get(conversation_id)
        if row is not None:
            row["user_turn_no"] = int(row.get("user_turn_no", 0)) + 1
            row["session_revision"] = int(row.get("session_revision", 0)) + 1
            row["updated_at"] = now()
            self.flush()
        if len(self.turns) != previous:
            self._write_turns()
        else:
            fd = os.open(self.turn_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "ab") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write((json.dumps(self.turns[-1], ensure_ascii=False) + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())

    def _prune_receipts(self, row, limit=MAX_RECEIPTS):
        receipts = row.get("receipts", [])
        completed = [r for r in receipts if r.get("phase") in ("completed", "rejected")]
        other = [r for r in receipts if r.get("phase") not in ("completed", "rejected")]
        row["receipts"] = other + completed[-limit:]

    # ---- history -------------------------------------------------------------

    def history(self, conversation_id, *, k=6):
        self._check()
        rows = [r for r in self.turns if r.get("session_id", r.get("conversation_id")) == conversation_id]
        grouped = {}
        for row in rows:
            grouped.setdefault(row["run_id"], []).append(row["user_text"])
        history = []
        for run_id, users in list(grouped.items())[-k:]:
            history.append({"role": "user", "content": "\n".join(users)})
            run = self.read_run(run_id) if self.read_run else {}
            final = (run.get("result") or {}).get("final_text")
            if isinstance(final, str):
                history.append({"role": "assistant", "content": final})
        return history

    def history_block(self, conversation_id):
        history = self.history(conversation_id)
        lines = []
        total = len("<conversation_so_far>\n</conversation_so_far>")
        for row in reversed(history):
            cap = 600 if row["role"] == "user" else 800
            content = row["content"]
            if len(content) > cap:
                content = content[:cap - len("[…truncated]")] + "[…truncated]"
            line = row["role"] + ": " + content
            if total + len(line) + 1 > 3950:
                break
            lines.insert(0, line)
            total += len(line) + 1
        turn_count = len({r["run_id"] for r in self.turns
                          if r.get("session_id", r.get("conversation_id")) == conversation_id})
        if len(lines) < len(history) or turn_count > 6:
            lines.insert(0, "[older turns omitted]")
        return "<conversation_so_far>\n" + "\n".join(lines) + "\n</conversation_so_far>"
