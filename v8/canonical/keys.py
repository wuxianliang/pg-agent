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


# ---------------------------------------------------------------------------
# G16: versioned raw-byte audit keys (spec 1.3 L78-L80)
#
# Five keys, all "version tag is part of the key NAME and MUST NOT enter the
# hash input":
#   rejection_fingerprint@v1            raw command payload bytes
#   transport_rejection_key@v1          raw ingress frame/report bytes
#   malformed_binding_fingerprint@v2    received-binding occurrence encoding
#   received_result_fingerprint@v2      received-result occurrence encoding
#   raw_invalid_digest@v1               full received-result bytes (corrupt)
# ---------------------------------------------------------------------------

# The five-value binding-side type-tag closed set (RAW is result-side only).
BINDING_TYPE_TAGS = ("TEXT", "NUMBER", "BOOLEAN", "JSON", "NULL")
# The six-value result-side closed set (RAW only on the corrupt single-row path).
RESULT_TYPE_TAGS = ("TEXT", "NUMBER", "BOOLEAN", "JSON", "NULL", "RAW")

# Fixed ten-column binding segment, in audit DDL order: internal receiving
# slot -> protocol input (wire) name. The wire name is what appears as
# `field_name_raw` for both real and synthesized occurrences (O05 table).
BINDING_FIXED_SLOTS = (
    ("received_session_id", "session_id"),
    ("received_step_id", "step_id"),
    ("received_effect_id", "effect_id"),
    ("received_attempt_no", "attempt_no"),
    ("received_driver", "driver"),
    ("received_driver_epoch", "driver_epoch"),
    ("received_dispatch_session_fence", "dispatch_session_fence"),
    ("received_job_fence", "job_fence"),
    ("received_request_hash", "request_hash"),
    ("received_idempotency_key_hash", "idempotency_key"),
)
# The sensitive-domain member name (unified recursive masking domain, N06):
# any decoded member name equal to this, at any nesting level.
SENSITIVE_MEMBER = "idempotency_key"

RAW_INVALID_FIELD_NAME = b"__raw_invalid__"


def occurrence_bytes(field_name_raw: bytes, type_tag: str, value_raw: bytes) -> bytes:
    """One occurrence encoding (frozen, @v2 field-name length delimiting):

    [8B big-endian name length][name raw bytes][tag ASCII]0x00
    [8B big-endian value length][value raw bytes]
    """
    if type_tag not in RESULT_TYPE_TAGS:
        raise ValueError(f"unknown occurrence type tag: {type_tag!r}")
    return (struct.pack(">Q", len(field_name_raw)) + field_name_raw
            + type_tag.encode("ascii") + b"\x00"
            + struct.pack(">Q", len(value_raw)) + value_raw)


def _occurrences_digest(occurrences) -> str:
    """SHA-256 over the ordered concatenation of occurrence encodings."""
    blob = b"".join(occurrence_bytes(n, t, v) for (n, t, v) in occurrences)
    return _digest(blob)


def rejection_fingerprint_v1(payload_raw: bytes) -> str:
    """rejection_fingerprint@v1 = SHA-256(command payload raw bytes).

    Structural separation: the raw payload bytes as received — no
    re-serialization, no byte stripping (the caller-declared hash travels on
    the transport metadata channel and is not part of the payload bytes).
    """
    return _digest(bytes(payload_raw))


def transport_rejection_key_v1(frame_raw: bytes) -> str:
    """transport_rejection_key@v1 = SHA-256(raw ingress report/frame bytes).

    Needs no payload boundary; MUST NOT reference the canonical hash or the
    rejection fingerprint.
    """
    return _digest(bytes(frame_raw))


def raw_invalid_digest_v1(result_raw: bytes) -> str:
    """raw_invalid_digest@v1 = SHA-256(full received result raw bytes).

    The corrupt path stores only this digest — never the raw original.
    """
    return _digest(bytes(result_raw))


def malformed_binding_fingerprint_v2(occurrences) -> str:
    """malformed_binding_fingerprint@v2 over binding-side occurrences.

    `occurrences` is the ordered sequence of `(field_name_raw: bytes,
    type_tag: str, value_raw: bytes)` triples in the frozen two-segment
    order (fixed ten-slot segment, then the unknown-fields segment). The
    binding type-tag domain is the five-value set (RAW forbidden).
    """
    for (_n, tag, _v) in occurrences:
        if tag not in BINDING_TYPE_TAGS:
            raise ValueError(
                f"binding occurrence tag {tag!r} outside the five-value set")
    return _occurrences_digest(occurrences)


def received_result_fingerprint_v2(occurrences) -> str:
    """received_result_fingerprint@v2 over result-side occurrences.

    Same framing as the binding key; the result-side tag domain adds RAW
    (produced only by the single `RAW_INVALID` occurrence of the corrupt
    path).
    """
    return _occurrences_digest(occurrences)


# ---------------------------------------------------------------------------
# JSON scanning that preserves arrival order and raw key lexemes
# ---------------------------------------------------------------------------

class _JsonScanner:
    """Minimal order-preserving JSON scanner over raw bytes.

    Yields the structure needed for occurrence extraction: for every object
    member, the raw key lexeme (bytes between the quotes, escapes as on the
    wire) and the decoded member name; for every value, its raw byte span and
    its JSON type. Deliberately strict: any malformed input raises
    `JsonScanError` (the corrupt path).
    """

    def __init__(self, raw: bytes):
        self.raw = raw
        self.pos = 0

    def _ws(self) -> None:
        while self.pos < len(self.raw) and self.raw[self.pos] in b" \t\r\n":
            self.pos += 1

    def _fail(self, why: str) -> None:
        raise JsonScanError(why)

    def parse(self):
        self._ws()
        value = self._value()
        self._ws()
        if self.pos != len(self.raw):
            self._fail("trailing bytes after the JSON value")
        return value

    def _value(self):
        if self.pos >= len(self.raw):
            self._fail("truncated input")
        ch = self.raw[self.pos:self.pos + 1]
        if ch == b"{":
            start = self.pos
            node = self._object()
            node["span"] = (start, self.pos)
            return node
        if ch == b"[":
            start = self.pos
            node = self._array()
            node["span"] = (start, self.pos)
            return node
        if ch == b'"':
            start = self.pos
            text = self._string()
            return {"kind": "scalar", "tag": "TEXT", "decoded": text,
                    "span": (start, self.pos), "raw": self.raw[start:self.pos]}
        if ch == b"t" or ch == b"f":
            lit = b"true" if ch == b"t" else b"false"
            if self.raw[self.pos:self.pos + len(lit)] != lit:
                self._fail("bad literal")
            start, self.pos = self.pos, self.pos + len(lit)
            return {"kind": "scalar", "tag": "BOOLEAN", "decoded": ch == b"t",
                    "span": (start, self.pos), "raw": lit}
        if ch == b"n":
            if self.raw[self.pos:self.pos + 4] != b"null":
                self._fail("bad literal")
            start, self.pos = self.pos, self.pos + 4
            return {"kind": "scalar", "tag": "NULL", "decoded": None,
                    "span": (start, self.pos), "raw": b"null"}
        # number
        start = self.pos
        if ch == b"-":
            self.pos += 1
        while self.pos < len(self.raw) and self.raw[self.pos:self.pos + 1] in b"0123456789.eE+-":
            self.pos += 1
        if self.pos == start:
            self._fail("not a value")
        return {"kind": "scalar", "tag": "NUMBER", "decoded": None,
                "span": (start, self.pos), "raw": self.raw[start:self.pos]}

    def _string(self) -> str:
        """Consume a JSON string; return the decoded text. Raw lexeme stays
        available to the caller via the span."""
        import json as _json
        start = self.pos
        self.pos += 1
        while True:
            if self.pos >= len(self.raw):
                self._fail("unterminated string")
            b = self.raw[self.pos]
            if b == 0x5C:  # backslash
                self.pos += 2
                continue
            if b == 0x22:  # closing quote
                self.pos += 1
                break
            self.pos += 1
        lexeme = self.raw[start:self.pos]
        try:
            return _json.loads(lexeme.decode("utf-8"))
        except Exception:
            self._fail("string is not decodable")

    def _object(self):
        members = []
        self.pos += 1  # '{'
        self._ws()
        if self.pos < len(self.raw) and self.raw[self.pos:self.pos + 1] == b"}":
            self.pos += 1
            return {"kind": "object", "members": members}
        while True:
            self._ws()
            if self.pos >= len(self.raw) or self.raw[self.pos:self.pos + 1] != b'"':
                self._fail("object key must be a string")
            key_start = self.pos
            name = self._string()
            key_lexeme = self.raw[key_start + 1:self.pos - 1]
            self._ws()
            if self.pos >= len(self.raw) or self.raw[self.pos:self.pos + 1] != b":":
                self._fail("expected ':' after object key")
            self.pos += 1
            self._ws()
            val = self._value()
            members.append({"name": name, "name_raw": key_lexeme, "value": val})
            self._ws()
            if self.pos >= len(self.raw):
                self._fail("unterminated object")
            ch = self.raw[self.pos:self.pos + 1]
            if ch == b",":
                self.pos += 1
                continue
            if ch == b"}":
                self.pos += 1
                return {"kind": "object", "members": members}
            self._fail("expected ',' or '}' in object")

    def _array(self):
        items = []
        self.pos += 1  # '['
        self._ws()
        if self.pos < len(self.raw) and self.raw[self.pos:self.pos + 1] == b"]":
            self.pos += 1
            return {"kind": "array", "items": items}
        while True:
            self._ws()
            items.append(self._value())
            self._ws()
            if self.pos >= len(self.raw):
                self._fail("unterminated array")
            ch = self.raw[self.pos:self.pos + 1]
            if ch == b",":
                self.pos += 1
                continue
            if ch == b"]":
                self.pos += 1
                return {"kind": "array", "items": items}
            self._fail("expected ',' or ']' in array")


class JsonScanError(Exception):
    """Malformed raw JSON — drives the corrupt/RAW_INVALID path."""


class UnboundedKeyError(Exception):
    """A sensitive-domain member value is not a string (or the input cannot
    be delimited) — the invalid_binding / UNBOUNDED_KEY path."""


def _mask_replacements(node, replacements) -> None:
    """Collect byte-level masking replacements for every decoded member name
    equal to the sensitive member name (unified recursive domain).

    `replacements` receives `(value_raw_span, replacement_bytes)` pairs where
    the span is the FULL JSON literal (including quotes) of the string value.
    A sensitive member whose value is not a string raises UnboundedKeyError.
    """
    if node["kind"] == "object":
        for m in node["members"]:
            if m["name"] == SENSITIVE_MEMBER:
                v = m["value"]
                if v["kind"] != "scalar" or v["tag"] != "TEXT":
                    raise UnboundedKeyError(
                        f"{SENSITIVE_MEMBER} value is not a string")
                import json as _json
                decoded = v["decoded"].encode("utf-8")
                hexed = hashlib.sha256(decoded).hexdigest().encode("ascii")
                replacements.append((v["span"], b'"' + hexed + b'"'))
                continue
            _mask_replacements(m["value"], replacements)
    elif node["kind"] == "array":
        for item in node["items"]:
            _mask_replacements(item, replacements)


def _masked_bytes(raw: bytes, span, replacements) -> bytes:
    """Apply the collected replacements to a raw byte span (container
    occurrence value). Bytes outside the replacement domain are kept
    verbatim — never re-serialized."""
    lo, hi = span
    chunk = raw[lo:hi]
    out = bytearray()
    cursor = lo
    for (rspan, repl) in sorted(replacements):
        rlo, rhi = rspan
        if rlo < lo or rhi > hi:
            continue
        out += raw[cursor:rlo]
        out += repl
        cursor = rhi
    out += raw[cursor:hi]
    return bytes(out)


def binding_occurrences_from_json(raw: bytes):
    """Build binding-side occurrences (frozen two-segment order).

    Returns `(occurrences, masked_raw)` where occurrences is the ordered list
    of `(field_name_raw, type_tag, value_raw)` triples:
      * segment 1 — the fixed ten slots in DDL order; every wire name present
        in the top-level object contributes its occurrences in arrival order,
        a missing one contributes the fixed synthesized placeholder
        (`field_name_raw` = the WIRE name bytes, tag NULL, zero-length value);
      * segment 2 — unknown top-level members, grouped by decoded name, the
        groups ordered by decoded-name UTF-8 byte order (byte order, never
        locale), within a group by arrival order.

    Raises `UnboundedKeyError` when the sensitive domain value is not a
    string (=> invalid_binding / UNBOUNDED_KEY summary path).
    """
    node = _JsonScanner(bytes(raw)).parse()
    if node["kind"] != "object":
        raise JsonScanError("binding must be a top-level object")
    replacements = []
    _mask_replacements(node, replacements)
    wire_names = {wire for (_slot, wire) in BINDING_FIXED_SLOTS}

    # Group top-level members by decoded name (arrival order preserved).
    grouped = {}
    for m in node["members"]:
        grouped.setdefault(m["name"], []).append(m)

    occurrences = []
    for (_slot, wire) in BINDING_FIXED_SLOTS:
        bucket = grouped.pop(wire, None)
        if not bucket:
            occurrences.append((wire.encode("utf-8"), "NULL", b""))
            continue
        for m in bucket:
            occurrences.append(_member_occurrence(m, replacements, bytes(raw)))
    # Unknown segment: groups ordered by decoded-name UTF-8 byte order.
    for name in sorted(grouped.keys(), key=lambda s: s.encode("utf-8")):
        for m in grouped[name]:
            occurrences.append(_member_occurrence(m, replacements, bytes(raw)))
    return occurrences, _masked_bytes(bytes(raw), (0, len(raw)), replacements)


def _member_occurrence(member, replacements, raw):
    """Encode one object member occurrence (container members double-record:
    the JSON occurrence precedes its children)."""
    name_raw = member["name_raw"]
    v = member["value"]
    if v["kind"] in ("object", "array"):
        return (name_raw, "JSON", _masked_bytes(raw, v["span"], replacements))
    if v["tag"] == "TEXT":
        decoded = v["decoded"].encode("utf-8")
        if _is_masked(v["span"], replacements):
            h = hashlib.sha256(decoded).hexdigest().encode("ascii")
            return (name_raw, "TEXT", h)
        return (name_raw, "TEXT", decoded)
    if v["tag"] == "NULL":
        return (name_raw, "NULL", b"")
    return (name_raw, v["tag"], v["raw"])


def _is_masked(span, replacements) -> bool:
    return any(rspan == span for (rspan, _repl) in replacements)


def result_occurrences_from_json(raw: bytes):
    """Strict two-path result-side extraction.

    Returns `(parse_path, occurrences, raw_evidence)`:
      * `complete` — full ABI parse succeeded: DFS occurrence grammar (root
        produces no occurrence; object members and array indices each produce
        one; a container value ALSO produces its own JSON occurrence BEFORE
        its children — pre-order), values masked recursively;
      * `raw_invalid` — any parse failure: exactly one occurrence
        (`__raw_invalid__`, RAW, raw_invalid_digest@v1 bytes) and the digest
        as the evidence (never the original bytes);
      * `empty` — zero received result bytes: empty occurrence sequence.

    `raw_invalid_class` is returned as a fourth element on the corrupt path.
    """
    if raw is None or len(raw) == 0:
        return ("empty", [], b"", None)
    data = bytes(raw)
    try:
        node = _JsonScanner(data).parse()
        node["_root_raw"] = data
        if node["kind"] != "object":
            raise UnboundedKeyError("top-level result is not an object")
        replacements = []
        _mask_replacements(node, replacements)
        occurrences = []
        _result_walk(node, replacements, occurrences, data)
        masked = _masked_bytes(data, (0, len(data)), replacements)
        return ("complete", occurrences, masked, None)
    except JsonScanError as exc:
        return ("raw_invalid", _raw_invalid_occurrence(data),
                _raw_invalid_evidence(data), _raw_invalid_class(str(exc)))
    except UnboundedKeyError:
        return ("raw_invalid", _raw_invalid_occurrence(data),
                _raw_invalid_evidence(data), "UNBOUNDED_KEY")


def _raw_invalid_occurrence(data: bytes):
    return [(RAW_INVALID_FIELD_NAME, "RAW", raw_invalid_digest_v1(data).encode("ascii"))]


def _raw_invalid_evidence(data: bytes) -> bytes:
    return raw_invalid_digest_v1(data).encode("ascii")


def _raw_invalid_class(reason: str) -> str:
    """Ordered first-match classification: TRUNCATED, then CORRUPT_BYTES,
    then UNBOUNDED_KEY."""
    if "truncat" in reason or "unterminated" in reason:
        return "TRUNCATED"
    return "CORRUPT_BYTES"


def _result_walk(node, replacements, out, raw) -> None:
    """Pre-order DFS: container occurrence first, then children."""
    if node["kind"] == "object":
        for m in node["members"]:
            out.append(_member_occurrence(m, replacements, raw))
            _result_walk(m["value"], replacements, out, raw)
    elif node["kind"] == "array":
        for idx, item in enumerate(node["items"]):
            name = str(idx).encode("ascii")
            if item["kind"] in ("object", "array"):
                out.append((name, "JSON",
                            _masked_bytes(raw, item["span"], replacements)))
            elif item["tag"] == "TEXT":
                h = hashlib.sha256(item["decoded"].encode("utf-8")).hexdigest().encode("ascii")
                if _is_masked(item["span"], replacements):
                    out.append((name, "TEXT", h))
                else:
                    out.append((name, "TEXT", item["decoded"].encode("utf-8")))
            elif item["tag"] == "NULL":
                out.append((name, "NULL", b""))
            else:
                out.append((name, item["tag"], item["raw"]))
            _result_walk(item, replacements, out, raw)

