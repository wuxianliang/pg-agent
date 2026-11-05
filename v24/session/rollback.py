"""Archive v2 state and restore the v1 snapshot written by migration.

The v2 store keeps ``sessions.json.v1.bak`` and ``turns.jsonl.v1.bak``.  A
rollback is a data operation, not a feature switch: archive the v2 files first,
then atomically replace both stores with the v1 copies.  The archive is
create-once and content-hashed so an interrupted run cannot overwrite evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .store import atomic_bytes, atomic_json, now


class RollbackError(RuntimeError):
    pass


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def archive_v2(data_dir, *, label=None):
    data_dir = Path(data_dir)
    source = data_dir / "sessions.json"
    if not source.exists():
        raise RollbackError("sessions_missing")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = re.sub(r"[^A-Za-z0-9_.-]", "_", label or "")[:48]
    name = f"v2-archive-{stamp}-{suffix + '-' if suffix else ''}{uuid.uuid4().hex[:8]}"
    target = data_dir / name
    try:
        os.mkdir(target, 0o700)
    except FileExistsError:
        raise RollbackError("archive_exists") from None
    files = {}
    try:
        for filename in ("sessions.json", "turns.jsonl", "sessions.json.prev",
                         "turns.jsonl.prev"):
            path = data_dir / filename
            if not path.exists():
                continue
            copy = target / filename
            shutil.copyfile(path, copy)
            os.chmod(copy, 0o600)
            files[filename] = {"sha256": _digest(copy), "bytes": copy.stat().st_size}
        manifest = {"format": "v24-rollback-archive-1", "created_at": now(),
                    "source": str(data_dir), "files": files}
        atomic_json(target / "manifest.json", manifest, keep_prev=False)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def _validate_v1(raw, turns_raw):
    if not isinstance(raw, dict) or raw.get("format_version") != 1:
        raise RollbackError("v1_format_invalid")
    rows = raw.get("conversations")
    if not isinstance(rows, list):
        raise RollbackError("v1_sessions_invalid")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RollbackError("v1_session_invalid")
        sid = row.get("conversation_id")
        try:
            uuid.UUID(sid)
        except (TypeError, ValueError, AttributeError):
            raise RollbackError("v1_session_invalid") from None
        if sid in seen:
            raise RollbackError("v1_session_duplicate")
        seen.add(sid)
        if not isinstance(row.get("bindings", []), list):
            raise RollbackError("v1_bindings_invalid")
        for binding in row.get("bindings", []):
            if not isinstance(binding, dict) or "run_id" not in binding or "scope_id" not in binding:
                raise RollbackError("v1_bindings_invalid")
    if turns_raw:
        for line in turns_raw.splitlines():
            try:
                turn = json.loads(line)
            except (ValueError, TypeError):
                raise RollbackError("v1_turns_invalid") from None
            if not isinstance(turn, dict) or not isinstance(turn.get("user_text"), str):
                raise RollbackError("v1_turns_invalid")
            if turn.get("session_id", turn.get("conversation_id")) not in seen:
                raise RollbackError("v1_turns_invalid")


def restore_v1(data_dir, *, confirm=False):
    data_dir = Path(data_dir)
    if not confirm:
        raise RollbackError("confirmation_required")
    sessions = data_dir / "sessions.json.v1.bak"
    turns = data_dir / "turns.jsonl.v1.bak"
    if not sessions.exists():
        raise RollbackError("v1_backup_missing")
    raw = sessions.read_bytes()
    turn_raw = turns.read_bytes() if turns.exists() else b""
    try:
        _validate_v1(json.loads(raw), turn_raw)
    except (ValueError, TypeError):
        raise RollbackError("v1_format_invalid") from None
    archive = archive_v2(data_dir, label="pre-rollback")
    try:
        atomic_bytes(data_dir / "sessions.json", raw, keep_prev=True)
        atomic_bytes(data_dir / "turns.jsonl", turn_raw, keep_prev=True)
    except BaseException:
        raise RollbackError("rollback_write_failed") from None
    return {"status": "rolled_back", "archive": str(archive)}
