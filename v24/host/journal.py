"""Durable single-writer JSONL journal for the v24 host.

Format rules (M-R, plan section "journal 格式"):

* the journal directory is private (``0700``) and the file is ``0600``;
* a POSIX advisory lock prevents a second writer in the same directory;
* records are append-only JSON lines with the fields
  ``v, seq, event_type, effect_id, run_id?, request_digest, claim?, payload``;
* ``event_type`` is the closed set below and the version is ``1``;
* each append is ``fsync``ed and read back byte-for-byte;
* a truncated tail line is treated as an unfinished write, while internal
  corruption stops the journal (it never silently resets);
* canonical JSON is used for requests/results, and API keys, Authorization
  headers and DSNs are never accepted.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from pathlib import Path

JOURNAL_VERSION = 1
EVENT_TYPES = frozenset({
    "command_prepared",
    "command_committed",
    "effect_prepared",
    "dispatch_started",
    "dispatch_finished",
    "settlement_committed",
})
_CORE_KEYS = frozenset({
    "v", "seq", "event_type", "effect_id", "request_digest", "claim", "payload",
})
_OPTIONAL_KEYS = frozenset({"run_id"})
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEYS = frozenset({
    "api_key", "apikey", "authorization", "dsn", "database_url",
    "deepseek_api_key", "openai_api_key", "access_token", "bearer",
})
_DSN_LIKE = re.compile(r"^(?:postgres(?:ql)?|postgresql)://", re.IGNORECASE)
_BEARER_LIKE = re.compile(r"^bearer\s+", re.IGNORECASE)


class JournalError(RuntimeError):
    """Base class for journal failures."""


class JournalVersionError(JournalError):
    """The journal knows only version 1; anything else fails closed."""


class JournalCorrupt(JournalError):
    """An internal record is damaged; execution for this journal stops."""


class JournalLocked(JournalError):
    """Another writer already owns this journal file."""


def canonical_json(value) -> str:
    """Canonical JSON used for request/result bytes and digests."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def request_digest(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _check_private_dir(path: Path) -> None:
    if not path.exists():
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
    if not path.is_dir():
        raise JournalError(f"journal parent is not a directory: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise JournalError(
            f"journal directory must be private (0700); got {mode:04o}: {path}")


def _scan_secrets(value, trail="payload") -> None:
    """Reject credential-shaped keys/values before they can reach the file."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise JournalError(f"non-string journal key under {trail}")
            if key.lower() in _SECRET_KEYS:
                raise JournalError(
                    f"credentials must never be written to the journal ({trail}.{key})")
            _scan_secrets(item, f"{trail}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_secrets(item, f"{trail}[{index}]")
    elif isinstance(value, str):
        if _DSN_LIKE.match(value):
            raise JournalError(f"DSN must never be written to the journal ({trail})")
        if _BEARER_LIKE.match(value):
            raise JournalError(f"bearer token must never be written to the journal ({trail})")


class HostJournal:
    """Append-only journal.  One instance owns one file and its POSIX lock."""

    def __init__(self, path: Path, fd: int, records: list[dict]):
        self.path = path
        self._fd = fd
        self._records = records
        self._seq = len(records)

    # -- lifecycle -------------------------------------------------------
    @classmethod
    def open(cls, path: str | Path) -> "HostJournal":
        path = Path(path)
        _check_private_dir(path.parent)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise JournalLocked(f"journal already has a writer: {path}") from exc
            created = os.fstat(fd).st_size == 0
            records = cls._load(fd)
            if created:
                # The file was created by this process; sync the directory entry.
                os.fsync(fd)
                dir_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            return cls(path, fd, records)
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _load(fd: int) -> list[dict]:
        os.lseek(fd, 0, os.SEEK_SET)
        chunks = []
        while True:
            block = os.read(fd, 65536)
            if not block:
                break
            chunks.append(block)
        raw = b"".join(chunks)
        if raw and not raw.endswith(b"\n"):
            # A crash may leave a partially written final line.  It is not a
            # committed record; trim it so a later append stays parseable.
            cut = raw.rfind(b"\n") + 1
            os.ftruncate(fd, cut)
            os.fsync(fd)
            raw = raw[:cut]
        records = []
        for number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                raise JournalCorrupt(f"blank journal line {number}")
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise JournalCorrupt(f"journal line {number} is not JSON") from exc
            HostJournal._validate(record, number)
            if record["seq"] != number:
                raise JournalCorrupt(
                    f"journal line {number} has seq {record['seq']}")
            records.append(record)
        return records

    @staticmethod
    def _validate(record, number: int) -> None:
        if not isinstance(record, dict):
            raise JournalCorrupt(f"journal line {number} is not an object")
        if record.get("v") != JOURNAL_VERSION:
            raise JournalVersionError(
                f"unknown journal version {record.get('v')!r} at line {number}")
        if record.get("event_type") not in EVENT_TYPES:
            raise JournalCorrupt(
                f"unknown event_type {record.get('event_type')!r} at line {number}")
        keys = set(record)
        if not (set(record) >= _CORE_KEYS - {"claim"}) or keys - _CORE_KEYS - _OPTIONAL_KEYS:
            raise JournalCorrupt(f"journal line {number} has an invalid key set")
        if not isinstance(record.get("effect_id"), str) or not record["effect_id"]:
            raise JournalCorrupt(f"journal line {number} has no effect_id")
        if not isinstance(record.get("request_digest"), str) or not _HEX64.fullmatch(
                record["request_digest"]):
            raise JournalCorrupt(f"journal line {number} has no request_digest")
        if not isinstance(record.get("payload"), dict):
            raise JournalCorrupt(f"journal line {number} payload is not an object")
        if "run_id" in record and not isinstance(record["run_id"], str):
            raise JournalCorrupt(f"journal line {number} run_id is not a string")
        claim = record.get("claim")
        if claim is not None and not isinstance(claim, dict):
            raise JournalCorrupt(f"journal line {number} claim is not an object")

    def close(self) -> None:
        fd = self._fd
        self._fd = -1
        if fd >= 0:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __enter__(self) -> "HostJournal":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -- append / read ---------------------------------------------------
    def append(self, event_type: str, effect_id: str, digest: str, payload: dict,
               *, run_id: str | None = None, claim: dict | None = None) -> dict:
        if self._fd < 0:
            raise JournalError("journal is closed")
        if event_type not in EVENT_TYPES:
            raise JournalCorrupt(f"unknown event_type {event_type!r}")
        if not isinstance(effect_id, str) or not effect_id:
            raise JournalError("effect_id is required")
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise JournalError("request_digest must be 64 lowercase hex characters")
        if not isinstance(payload, dict):
            raise JournalError("payload must be an object")
        _scan_secrets(payload)
        record = {
            "v": JOURNAL_VERSION,
            "seq": self._seq + 1,
            "event_type": event_type,
            "effect_id": effect_id,
            "request_digest": digest,
            "claim": claim,
            "payload": payload,
        }
        if run_id is not None:
            record["run_id"] = run_id
        self._validate(record, record["seq"])
        line = (canonical_json(record) + "\n").encode("utf-8")
        offset = os.lseek(self._fd, 0, os.SEEK_END)
        os.write(self._fd, line)
        os.fsync(self._fd)
        back = os.pread(self._fd, len(line), offset)
        if back != line:
            raise JournalCorrupt("journal read-back differs from the appended bytes")
        self._records.append(record)
        self._seq += 1
        return record

    @property
    def records(self) -> tuple[dict, ...]:
        return tuple(self._records)

    def records_for(self, effect_id: str) -> list[dict]:
        return [r for r in self._records if r["effect_id"] == effect_id]

    def records_for_run(self, run_id: str) -> list[dict]:
        return [r for r in self._records if r.get("run_id") == run_id]

    def has(self, event_type: str, effect_id: str) -> bool:
        return any(r["event_type"] == event_type and r["effect_id"] == effect_id
                   for r in self._records)

    def last(self, event_type: str, effect_id: str) -> dict | None:
        for record in reversed(self._records):
            if record["event_type"] == event_type and record["effect_id"] == effect_id:
                return record
        return None

    def prepared_without_dispatch(self) -> list[str]:
        """``effect_prepared`` records that never reached ``dispatch_started``."""
        started = {r["effect_id"] for r in self._records
                   if r["event_type"] == "dispatch_started"}
        done = {r["effect_id"] for r in self._records
                if r["event_type"] == "settlement_committed"}
        ordered = []
        seen = set()
        for record in self._records:
            effect_id = record["effect_id"]
            if effect_id in started or effect_id in done or effect_id in seen:
                continue
            if record["event_type"] == "effect_prepared":
                seen.add(effect_id)
                ordered.append(effect_id)
        return ordered

    def pending_settlements(self) -> list[str]:
        done = {r["effect_id"] for r in self._records
                if r["event_type"] == "settlement_committed"}
        ordered = []
        seen = set()
        for record in self._records:
            effect_id = record["effect_id"]
            if effect_id in done or effect_id in seen:
                continue
            if record["event_type"] == "dispatch_finished":
                seen.add(effect_id)
                ordered.append(effect_id)
        return ordered

    def unfinished_dispatches(self) -> list[str]:
        done = {r["effect_id"] for r in self._records
                if r["event_type"] == "dispatch_finished"}
        ordered = []
        seen = set()
        for record in self._records:
            effect_id = record["effect_id"]
            if effect_id in done or effect_id in seen:
                continue
            if record["event_type"] == "dispatch_started":
                seen.add(effect_id)
                ordered.append(effect_id)
        return ordered
