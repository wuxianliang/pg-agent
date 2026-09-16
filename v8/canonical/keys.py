"""v8 named versioned key derivation — byte-level frozen algorithms.

Contract: docs/designs/v8-dev.md section 3.1.2 key algorithms; implementation
digest docs/analysis/v8-impl-digest/s31b-command-table.md section 3
(event_key@v1, canonical_integer_bytes, turn_end_key@v1, closer_event_key@v1,
provisional_unknown_effect_set_digest@v1, identity field byte representation,
non-stream event key).

Identity field byte representation (frozen, clause (iv) of event_key@v1,
shared by all three portable keys): a UUID input — uuid.UUID object or any
text form of one — is taken as its 16-byte RFC 9562 binary representation
(no hyphens, no case ambiguity: every text form of the same UUID yields the
same derived key); any other text is taken as raw UTF-8 (no Unicode
normalization, no escaping); NULL or non-UTF-8 raises ValueError.

Every key is returned as the lower-case hex of its SHA-256 digest (the
64-byte lowercase-hex UTF-8 value used by the contract).
"""
from __future__ import annotations

import hashlib
import struct
import uuid

# Domain-separation prefixes: ASCII name + single NUL byte, part of the hash
# input (and therefore frozen with canonical_profile_version = @v1).
EVENT_KEY_DOMAIN = b"v8:event-key@v1\x00"
TURN_END_KEY_DOMAIN = b"v8:turn-end-key@v1\x00"
CLOSER_EVENT_KEY_DOMAIN = b"v8:closer-event-key@v1\x00"
# Database-internal (non-portable) non-stream event identity reference:
# SQL side and this Python reference MUST stay identical so tests can assert
# parity; not a cross-language golden-vector assertion object.
NONSTREAM_EVENT_KEY_DOMAIN = b"v8:nonstream-event-key@db1\x00"


def canonical_integer_bytes(n: int) -> bytes:
    """Decimal ASCII digits of an integer value, no leading zeros, 0 -> b'0'.

    The value's wire form (JSON number vs tagged $int) never enters this
    encoding: both legal forms of the same integer value yield byte-identical
    downstream keys.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"canonical_integer_bytes expects int, got {type(n).__name__}")
    return str(n).encode("ascii")


def _len_prefixed(b: bytes) -> bytes:
    """8-byte big-endian length delimiter + the raw bytes."""
    return struct.pack(">Q", len(b)) + b


def _u64be(n: int) -> bytes:
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"u64be expects int, got {type(n).__name__}")
    if not 0 <= n < 2 ** 64:
        raise ValueError(f"u64be out of range: {n}")
    return struct.pack(">Q", n)


def _i64be(n: int) -> bytes:
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"i64be expects int, got {type(n).__name__}")
    if not -(2 ** 63) <= n < 2 ** 63:
        raise ValueError(f"i64be out of range: {n}")
    return struct.pack(">q", n)


def identity_bytes(value) -> bytes:
    """Identity field bytes (UUID-aware): UUID -> 16-byte RFC 9562 binary,
    other text -> raw UTF-8; NULL / non-UTF-8 -> ValueError."""
    if value is None:
        raise ValueError("identity field is NULL")
    if isinstance(value, uuid.UUID):
        return value.bytes
    if isinstance(value, str):
        try:
            return uuid.UUID(value).bytes
        except ValueError:
            pass
        try:
            return value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError(f"identity field is not valid UTF-8: {value!r}") from exc
    raise TypeError(
        f"identity field must be a UUID or str, got {type(value).__name__}")


def _text_bytes(value) -> bytes:
    """Raw-text identifier field (stream_id, event_type, hex keys/hashes):
    always UTF-8 as-is, never UUID-parsed (frozen identity clause — stream_id
    and other non-UUID text identifiers stay raw even if UUID-shaped)."""
    if value is None:
        raise ValueError("text field is NULL")
    if not isinstance(value, str):
        raise TypeError(f"text field must be str, got {type(value).__name__}")
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"text field is not valid UTF-8: {value!r}") from exc


def _digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def event_key_v1(effect_id, attempt_no: int, stream_id, chunk_index: int) -> str:
    """Streaming-event key (assistant/chunk), cross-runtime portable:

    SHA-256("v8:event-key@v1\\0"
        || len8(effect_id bytes) || uint64be(attempt_no)
        || len8(stream_id bytes) || canonical_integer_bytes(chunk_index))
    """
    blob = (EVENT_KEY_DOMAIN
            + _len_prefixed(identity_bytes(effect_id))
            + _u64be(attempt_no)
            + _len_prefixed(_text_bytes(stream_id))
            + canonical_integer_bytes(chunk_index))
    return _digest(blob)


def turn_end_key_v1(session_id, turn_id) -> str:
    """Canonical end slot key, one per turn, not caller-specifiable:

    SHA-256("v8:turn-end-key@v1\\0"
        || len8(session_id bytes) || len8(turn_id bytes))
    """
    blob = (TURN_END_KEY_DOMAIN
            + _len_prefixed(identity_bytes(session_id))
            + _len_prefixed(identity_bytes(turn_id)))
    return _digest(blob)


def closer_event_key_v1(turn_end_key_hex: str, supersedes_event_key_hex: str,
                        resolution_identity_canonical_bytes: bytes) -> str:
    """Repair-closer event key:

    SHA-256("v8:closer-event-key@v1\\0"
        || len8(turn_end_key UTF-8 bytes)
        || len8(supersedes_event_key UTF-8 bytes)
        || len8(resolution identity canonical bytes))

    Both key arguments are the 64-char lowercase-hex values; the resolution
    argument is the canonical JSON bytes of the structured resolution object.
    """
    resolution = bytes(resolution_identity_canonical_bytes)
    blob = (CLOSER_EVENT_KEY_DOMAIN
            + _len_prefixed(_text_bytes(turn_end_key_hex))
            + _len_prefixed(_text_bytes(supersedes_event_key_hex))
            + _len_prefixed(resolution))
    return _digest(blob)


def provisional_unknown_effect_set_digest_v1(effect_ids) -> str:
    """Portable projection component of a provisional unknown end.

    Input: the turn's full set of unknown-outcome effect_ids. Encoding: each
    identity's bytes (UUID -> 16-byte RFC 9562 binary) sorted ascending by
    byte order, each prefixed with the 8-byte big-endian length delimiter,
    concatenated. Digest: SHA-256 of the concatenation, lower-case hex.
    NOTE: no domain prefix — the version tag is part of the key NAME and
    MUST NOT enter the hash input (frozen). The input is a set: duplicates
    collapse. The empty set encodes as the empty byte sequence.
    """
    seen = set()
    unique = []
    for effect_id in effect_ids:
        blob = identity_bytes(effect_id)
        if blob not in seen:
            seen.add(blob)
            unique.append(blob)
    unique.sort()
    return _digest(b"".join(_len_prefixed(blob) for blob in unique))


def nonstream_event_key(session_id, event_type: str, command_id,
                        batch_item_ordinal: int, payload_hash: str) -> str:
    """Non-stream event key — Python-side reference of the database-internal
    derived identity (db-internal consistency tier, not a cross-language
    portable assertion object; the SQL side MUST match this byte-for-byte).

    Binds (session_id, event_type, raw occurrence identity
    (command_id, batch_item_ordinal), canonical payload hash):

    SHA-256("v8:nonstream-event-key@db1\\0"
        || len8(session_id bytes) || len8(event_type UTF-8 bytes)
        || len8(command_id UTF-8 bytes) || canonical_integer_bytes(batch_item_ordinal)
        || len8(payload_hash UTF-8 bytes))

    (G3 reconciliation: the ordinal encodes as canonical_integer_bytes — the
    frozen "every ordinal entering a hash input encodes as decimal ASCII
    bytes" convention, matching SQL v_nonstream_event_key and its G2 golden
    vector — and command_id is raw UTF-8 text like the SQL text column, never
    UUID-parsed; the earlier _u64be/UUID-parsed form diverged from the SQL
    side and was corrected.)
    """
    blob = (NONSTREAM_EVENT_KEY_DOMAIN
            + _len_prefixed(identity_bytes(session_id))
            + _len_prefixed(_text_bytes(event_type))
            + _len_prefixed(_text_bytes(command_id))
            + canonical_integer_bytes(batch_item_ordinal)
            + _len_prefixed(_text_bytes(payload_hash)))
    return _digest(blob)
