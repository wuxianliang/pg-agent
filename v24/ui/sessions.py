"""Private, bounded conversation metadata. All I/O belongs to the hub thread."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

VERSION = 1
TERMINAL = frozenset({"completed", "failed", "cancelled", "blocked_unknown"})


def now():
    return datetime.now(timezone.utc).isoformat()


def valid_uuid(value):
    if not isinstance(value, str):
        raise ValueError("invalid_uuid")
    return uuid.UUID(value)


def atomic_json(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode())


def atomic_bytes(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        tmp.unlink(missing_ok=True)


class SessionStore:
    def __init__(self, data_dir, *, read_run=None):
        self.owner = threading.get_ident()
        self.path = Path(data_dir) / "sessions.json"
        self.turn_path = Path(data_dir) / "turns.jsonl"
        self.read_run = read_run
        self.conversations = []
        self.turns = []
        self.warnings = []
        self.active_conversation_id = None
        self.load()

    def _check(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError("session_thread_mismatch")

    def _quarantine(self, path, reason):
        path.rename(path.with_name(path.name + f".{reason}-{uuid.uuid4().hex}"))
        self.warnings.append(reason)

    def load(self):
        self._check()
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("format_version") != VERSION:
                    self._quarantine(self.path, "incompatible")
                else:
                    rows = data["conversations"]
                    if not isinstance(rows, list):
                        raise ValueError("invalid_sessions")
                    ids = set()
                    for row in rows:
                        if not isinstance(row, dict):
                            raise ValueError("invalid_conversation")
                        valid_uuid(row["conversation_id"])
                        token_hash = row["resume_token_hash"]
                        if not isinstance(token_hash, str) or len(token_hash) != 64 or any(c not in "0123456789abcdef" for c in token_hash):
                            raise ValueError("invalid_token_hash")
                        if row["conversation_id"] in ids or not isinstance(row["bindings"], list):
                            raise ValueError("invalid_conversation")
                        ids.add(row["conversation_id"])
                        for binding in row["bindings"]:
                            valid_uuid(binding["scope_id"])
                            valid_uuid(binding["run_id"])
                        row["bindings"] = row["bindings"][-200:]
                    self.conversations = rows
                    self.active_conversation_id = data.get("active_conversation_id")
            except (ValueError, KeyError, TypeError, UnicodeError):
                self.conversations = []
                self._quarantine(self.path, "corrupt")
        if self.turn_path.exists():
            # Skip malformed records independently, including invalid UTF-8.
            raw_turns = self.turn_path.read_bytes()
            repair = bool(raw_turns and not raw_turns.endswith(b"\n"))
            for line in raw_turns.splitlines():
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict) or not isinstance(row["user_text"], str) or type(row["seq"]) is not int:
                        raise ValueError("invalid_turn")
                    valid_uuid(row["conversation_id"])
                    valid_uuid(row["run_id"])
                    self.turns.append(row)
                except (ValueError, KeyError, TypeError, UnicodeError):
                    self.warnings.append("turn_corrupt")
                    repair = True
            previous = len(self.turns)
            self._bound_turns()
            if repair or len(self.turns) != previous:
                self._write_turns()

    def flush(self):
        self._check()
        atomic_json(self.path, {"format_version": VERSION, "active_conversation_id": self.active_conversation_id,
                                "conversations": self.conversations})

    def get(self, conversation_id):
        self._check()
        return next((row for row in self.conversations if row["conversation_id"] == conversation_id), None)

    def new_conversation(self, **scope_metadata):
        self._check()
        token = secrets.token_urlsafe(32)
        row = {"conversation_id": str(uuid.uuid4()), "resume_token_hash": hashlib.sha256(token.encode()).hexdigest(),
               "created_at": now(), "updated_at": now(), "bindings": [], "active_binding": None,
               **scope_metadata}
        self.conversations.append(row)
        self.active_conversation_id = row["conversation_id"]
        self.flush()
        return row, token

    def bind(self, conversation_id, scope_id, run_id, *, realm, workspace_root, toolset, catalog_digest):
        row = self.get(conversation_id)
        if row is None:
            raise RuntimeError("not_found_or_denied")
        binding = {"scope_id": scope_id, "run_id": run_id, "realm": realm,
                   "workspace_root": str(Path(workspace_root).resolve()), "toolset": toolset,
                   "catalog_digest": catalog_digest}
        row["bindings"] = [b for b in row["bindings"] if b["run_id"] != run_id] + [binding]
        row["bindings"] = row["bindings"][-200:]
        row["active_binding"] = binding
        row["updated_at"] = now()
        self.active_conversation_id = conversation_id
        self.flush()
        return binding

    def detach(self, conversation_id):
        row = self.get(conversation_id)
        if row:
            row["active_binding"] = None
            if self.active_conversation_id == conversation_id:
                self.active_conversation_id = None
            self.flush()

    def find_by_token(self, token):
        self._check()
        digest = hashlib.sha256(token.encode()).hexdigest()
        return next((row for row in self.conversations if hmac.compare_digest(row["resume_token_hash"], digest)), None)

    def remove(self, conversation_id):
        self._check()
        self.conversations = [r for r in self.conversations if r["conversation_id"] != conversation_id]
        if self.active_conversation_id == conversation_id:
            self.active_conversation_id = None
        self.turns = [r for r in self.turns if r["conversation_id"] != conversation_id]
        self._write_turns()
        self.flush()

    def _bound_turns(self):
        counts = {}
        kept = []
        for row in reversed(self.turns):
            cid = row["conversation_id"]
            counts[cid] = counts.get(cid, 0) + 1
            if counts[cid] <= 200:
                kept.append(row)
        self.turns = list(reversed(kept))

    def _write_turns(self):
        atomic_bytes(self.turn_path, b"".join((json.dumps(r, ensure_ascii=False) + "\n").encode() for r in self.turns))

    def append_turn(self, *, conversation_id, run_id, seq, user_text):
        self._check()
        row = dict(conversation_id=conversation_id, run_id=run_id, seq=seq, user_text=user_text, created_at=now())
        self.turns.append(row)
        previous = len(self.turns)
        self._bound_turns()
        if len(self.turns) != previous:
            self._write_turns()
        else:
            fd = os.open(self.turn_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "ab") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write((json.dumps(row, ensure_ascii=False) + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())

    def history(self, conversation_id, *, k=6):
        self._check()
        rows = [r for r in self.turns if r["conversation_id"] == conversation_id]
        # A steer/answer can add a turn with the same run; include its final once.
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
        turn_count = len({r["run_id"] for r in self.turns if r["conversation_id"] == conversation_id})
        if len(lines) < len(history) or turn_count > 6:
            lines.insert(0, "[older turns omitted]")
        return "<conversation_so_far>\n" + "\n".join(lines) + "\n</conversation_so_far>"
