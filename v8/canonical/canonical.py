"""v8 canonical profile @v1 — the byte-level foundation of the V8 behavior contract.

Frozen contract: docs/designs/v8-dev.md section 1.3 (canonical JSON and render).
Implementation digest: docs/analysis/v8-impl-digest/s31b-command-table.md section 3.

Pipeline (order frozen, MUST NOT be reordered/skipped/merged):

  raw payload -> step 0 boundary escape (escape_dollar_keys, producer side)
             -> (1) JSON parse under I-JSON constraints (duplicate keys,
                  NaN/Infinity rejected)
             -> (2) NFC check on every string (reject, never silently convert)
             -> (3) tagged-integer / dollar-key / number-range validation on the
                  escaped representation
             -> (4) RFC 3339 normalization, only on registered time-typed fields
             -> (5) RFC 8785 (JCS) serialization — the only serialization
             -> (6) payload_hash = SHA-256 of the canonical UTF-8 bytes

The canonicalizer's formal input is the ALREADY-ESCAPED representation
(spec section 1.3): canonicalize() applies steps (1)-(6) and does not escape.
Producers compose step 0 themselves:

    escaped = escape_dollar_keys(payload_object)
    text, payload_hash = canonicalize(escaped)  # or its serialized form
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timedelta

# Frozen canonical profile name. Any change to any rule below MUST bump this.
CANONICAL_PROFILE_VERSION = "@v1"

# Integers with |v| <= 2^53-1 MUST be JSON numbers; beyond that they MUST use
# the tagged {"$int": "<decimal>"} reserved object (bare out-of-range numbers
# are rejected as UNSAFE_NUMBER).
SAFE_INTEGER_LIMIT = 9007199254740991  # 2^53 - 1

# Tagged integer value range: |v| <= 2^63 - 1.
TAGGED_INTEGER_LIMIT = 9223372036854775807  # 2^63 - 1

# Frozen tagged-integer lexical form: optional leading '-', then "0" or a
# digit string with a nonzero leading digit. ASCII digits only.
_TAGGED_DECIMAL_RE = re.compile(r"^-?(0|[1-9][0-9]*)$")

# P0B stand-in registry of schema time-typed field names: RFC 3339
# normalization applies exactly to these keys, at any object depth. Fields
# not in the registry are never rewritten even when they look like RFC 3339.
# As frozen schemas land, their explicit time-typed field names are
# registered here (this registry is the P0B simplification of "schema
# explicit time-typed fields" allowed by the G1 task).
TIME_FIELD_NAMES = frozenset({
    "created_at",
    "updated_at",
    "occurred_at",
    "started_at",
    "finished_at",
    "expires_at",
})


class CanonicalizationError(Exception):
    """Rejection with a stable machine-readable code (closed set per stage)."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


# ---------------------------------------------------------------------------
# Step 0: producer input boundary escape (prefix doubling, collision-free)
# ---------------------------------------------------------------------------

def _is_valid_tagged_decimal(value: str) -> bool:
    """Lexical + tagged-range validity of a $int value string."""
    if _TAGGED_DECIMAL_RE.match(value) is None or value == "-0":
        return False
    return abs(int(value)) <= TAGGED_INTEGER_LIMIT


def _is_tagged_integer_object(obj: object) -> bool:
    """Exactly one key "$int" whose value is a decimal string with
    |v| <= 2^63-1 (the protocol-annotated tagged integer reserved object)."""
    if not isinstance(obj, dict) or len(obj) != 1 or "$int" not in obj:
        return False
    value = obj["$int"]
    return isinstance(value, str) and _is_valid_tagged_decimal(value)


def escape_dollar_keys(obj):
    """Step 0 (producer input boundary escape), prefix doubling.

    Recursively prepend one more "$" to every key that starts with "$"
    ($int -> $$int, $$int -> $$$int, ...). Valid tagged integers (exactly one
    "$int" key whose value is a decimal string with |v| <= 2^63-1) are left
    untouched — decision order: recognize the valid tagged integer first,
    then escape the remaining "$"-prefixed keys. The input is not mutated.
    """
    if isinstance(obj, dict):
        if _is_tagged_integer_object(obj):
            return dict(obj)
        out = {}
        for key, value in obj.items():
            if isinstance(key, str) and key.startswith("$"):
                key = "$" + key
            out[key] = escape_dollar_keys(value)
        return out
    if isinstance(obj, list):
        return [escape_dollar_keys(item) for item in obj]
    return obj


def unescape_dollar_keys(obj):
    """Display/restore-only decode (strip one leading "$" from "$$" keys).

    Explicitly NOT part of the validation or hash pipeline (spec section 1.3).
    """
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if isinstance(key, str) and key.startswith("$$"):
                key = key[1:]
            out[key] = unescape_dollar_keys(value)
        return out
    if isinstance(obj, list):
        return [unescape_dollar_keys(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Step 1: parse under I-JSON constraints
# ---------------------------------------------------------------------------

def _reject_constant(name: str):
    raise CanonicalizationError("NON_IJSON", f"{name} literal is forbidden")


def _object_pairs(pairs):
    seen = set()
    for key, _value in pairs:
        if key in seen:
            raise CanonicalizationError("DUPLICATE_KEY", f"duplicate object key {key!r}")
        seen.add(key)
    return dict(pairs)


def _parse_payload(payload):
    if isinstance(payload, (dict, list)):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalizationError("NON_IJSON", f"payload is not valid UTF-8: {exc}") from exc
    if isinstance(payload, str):
        try:
            return json.loads(
                payload,
                object_pairs_hook=_object_pairs,
                parse_constant=_reject_constant,
            )
        except CanonicalizationError:
            raise
        except ValueError as exc:
            raise CanonicalizationError("NON_IJSON", f"payload is not valid JSON: {exc}") from exc
    raise CanonicalizationError(
        "NON_IJSON", f"unsupported payload type {type(payload).__name__}")


def _reject_nonfinite(value) -> None:
    """Object-input equivalent of the parse-time NaN/Infinity rejection."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise CanonicalizationError("NON_IJSON", "NaN/Infinity value is forbidden")
    if isinstance(value, dict):
        for key in value:
            if isinstance(key, float) and (math.isnan(key) or math.isinf(key)):
                raise CanonicalizationError("NON_IJSON", "NaN/Infinity key is forbidden")
        for item in value.values():
            _reject_nonfinite(item)
    elif isinstance(value, list):
        for item in value:
            _reject_nonfinite(item)


# ---------------------------------------------------------------------------
# Step 2: NFC check (reject, never silently convert)
# ---------------------------------------------------------------------------

def _check_string_nfc(s: str, where: str) -> None:
    if unicodedata.normalize("NFC", s) != s:
        raise CanonicalizationError("NOT_NFC", f"string at {where} is not NFC")
    try:
        s.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError(
            "NON_IJSON", f"string at {where} is not valid Unicode: {exc}") from exc


def _check_nfc(value, path: str = "$") -> None:
    if isinstance(value, str):
        _check_string_nfc(value, path)
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                _check_string_nfc(key, f"{path}.<key>")
            _check_nfc(item, f"{path}.{key}" if isinstance(key, str) else path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_nfc(item, f"{path}[{index}]")


# ---------------------------------------------------------------------------
# Step 3: tagged integer / dollar-key / number-range validation
# (on the escaped representation)
# ---------------------------------------------------------------------------

def _check_structure(value, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        if value > SAFE_INTEGER_LIMIT or value < -SAFE_INTEGER_LIMIT:
            raise CanonicalizationError(
                "UNSAFE_NUMBER",
                f"integer at {path} exceeds +/-(2^53-1) and must use the tagged "
                f"$int encoding: {value}")
        return
    if isinstance(value, float):
        # Integral-valued doubles participate in the frozen integer
        # partition (step (4)): |v| <= 2^53-1 may be bare JSON numbers
        # (rendered without fraction by step 5), an integral value beyond
        # that MUST use the tagged $int encoding (bare out-of-range
        # integers are rejected). Non-integral IEEE-754 numbers are
        # ordinary I-JSON data, rendered by RFC 8785 at step 5.
        if value.is_integer() and not (
                -SAFE_INTEGER_LIMIT <= value <= SAFE_INTEGER_LIMIT):
            raise CanonicalizationError(
                "UNSAFE_NUMBER",
                f"integral number at {path} exceeds +/-(2^53-1) and must use "
                f"the tagged $int encoding: {value!r}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_structure(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        # Reserved-name rule: an UNESCAPED object with exactly one "$int" key
        # is interpreted as a tagged integer, whatever the value looks like.
        if len(value) == 1 and "$int" in value:
            _check_tagged_integer(value["$int"], path)
            return
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(
                    "NON_IJSON", f"object key at {path} is not a string: {key!r}")
            if key.startswith("$") and not key.startswith("$$"):
                raise CanonicalizationError(
                    "UNESCAPED_DOLLAR_KEY",
                    f"object key {key!r} at {path} starts with a single '$' but is "
                    f"neither a valid tagged integer nor an escaped '$$' form")
            _check_structure(item, f"{path}.{key}")
        return
    raise CanonicalizationError(
        "NON_IJSON", f"unsupported value type {type(value).__name__} at {path}")


def _check_tagged_integer(value, path: str) -> None:
    if not isinstance(value, str):
        raise CanonicalizationError(
            "TAGGED_INT_INVALID",
            f"tagged integer value at {path} must be a decimal string, got "
            f"{type(value).__name__}")
    if _TAGGED_DECIMAL_RE.match(value) is None or value == "-0":
        raise CanonicalizationError(
            "TAGGED_INT_INVALID",
            f"tagged integer value at {path} violates the frozen lexical form "
            f"(optional '-', no leading zeros, no '+'/fraction/exponent, "
            f"'-0' rejected): {value!r}")
    n = int(value)
    if n > TAGGED_INTEGER_LIMIT or n < -TAGGED_INTEGER_LIMIT:
        raise CanonicalizationError(
            "TAGGED_INT_INVALID",
            f"tagged integer value at {path} exceeds |v| <= 2^63-1: {value!r}")
    if -SAFE_INTEGER_LIMIT <= n <= SAFE_INTEGER_LIMIT:
        raise CanonicalizationError(
            "TAGGED_INT_INVALID",
            f"integer at {path} is within +/-(2^53-1) and must be a JSON number, "
            f"not the tagged encoding: {value!r}")


# ---------------------------------------------------------------------------
# Step 4: RFC 3339 normalization on registered time-typed fields
# ---------------------------------------------------------------------------

_RFC3339_RE = re.compile(
    r"^([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]"
    r"([0-9]{2}):([0-9]{2}):([0-9]{2})"
    r"(?:\.([0-9]+))?"
    r"([Zz]|[+-][0-9]{2}:[0-9]{2})$")


def normalize_rfc3339(text: str) -> str:
    """Pure RFC 3339 normalization (P0B profile).

    Converts to UTC, renders with a literal "Z", strips trailing zeros from
    the fractional seconds, and omits the fraction when nothing significant
    remains. Accepts lower-case "t"/"z" separators (RFC 3339 permits them) and
    normalizes them to upper case. Raises CanonicalizationError("TIME_INVALID")
    for anything that is not an RFC 3339 timestamp.
    """
    if not isinstance(text, str):
        raise CanonicalizationError("TIME_INVALID", f"not an RFC 3339 string: {text!r}")
    m = _RFC3339_RE.match(text)
    if m is None:
        raise CanonicalizationError("TIME_INVALID", f"not an RFC 3339 timestamp: {text!r}")
    year, month, day, hour, minute, second, fraction, offset = m.groups()
    try:
        base = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second))
    except ValueError as exc:
        raise CanonicalizationError(
            "TIME_INVALID", f"invalid RFC 3339 timestamp {text!r}: {exc}") from exc
    if offset in ("Z", "z"):
        delta = timedelta(0)
    else:
        offset_hours, offset_minutes = int(offset[1:3]), int(offset[4:6])
        if offset_hours > 23 or offset_minutes > 59:
            raise CanonicalizationError(
                "TIME_INVALID", f"invalid UTC offset in {text!r}")
        magnitude = timedelta(hours=offset_hours, minutes=offset_minutes)
        delta = magnitude if offset[0] == "+" else -magnitude
    try:
        utc = base - delta
    except OverflowError as exc:
        raise CanonicalizationError(
            "TIME_INVALID", f"timestamp out of range: {text!r}") from exc
    fraction_digits = (fraction or "").rstrip("0")
    rendered = (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}"
        f"T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}")
    if fraction_digits:
        rendered += "." + fraction_digits
    return rendered + "Z"


def _normalize_time_fields(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in TIME_FIELD_NAMES and isinstance(item, str):
                out[key] = normalize_rfc3339(item)
            else:
                out[key] = _normalize_time_fields(item)
        return out
    if isinstance(value, list):
        return [_normalize_time_fields(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Step 5: RFC 8785 (JCS) serialization
# ---------------------------------------------------------------------------

_SHORT_ESCAPES = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
}


def _es6_exponent(e: int) -> str:
    """ES6 exponent text: explicit sign, no leading zeros ('e+21', 'e-7')."""
    return ("+" if e >= 0 else "-") + str(abs(e))


def _es6_number_text(x: float) -> str:
    """RFC 8785 number rendering = ECMAScript Number::toString (ECMA-262
    7.1.12.1) for a finite double.

    Python's repr() already yields the shortest round-tripping digit string
    — the same "k as small as possible" digit choice the ES6 algorithm
    specifies — so this reformats those digits under the ES6 plain/exponent
    thresholds: plain decimal notation for 1e-6 <= |x| < 1e21, otherwise
    'e+NN' / 'e-N' exponent notation. Integer-valued doubles inside the
    plain-notation range are handled by the caller via str(int(x)), which
    equals the ES6 rendering.
    """
    text = repr(x)
    neg = text.startswith("-")
    if neg:
        text = text[1:]
    if "e" in text:
        mantissa, _, exponent = text.partition("e")
        exp = int(exponent)
    else:
        mantissa, exp = text, 0
    if "." in mantissa:
        int_part, _, frac_part = mantissa.partition(".")
    else:
        int_part, frac_part = mantissa, ""
    combined = int_part + frac_part
    digits = combined.lstrip("0")
    leading_zeros = len(combined) - len(digits)
    digits = digits.rstrip("0")  # defensive; shortest repr has none
    k = len(digits)
    n = len(int_part) + exp - leading_zeros  # value = digits * 10^(n-k)
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    elif k == 1:
        out = digits + "e" + _es6_exponent(n - 1)
    else:
        out = digits[0] + "." + digits[1:] + "e" + _es6_exponent(n - 1)
    return ("-" if neg else "") + out


def _escape_jcs_string(s: str) -> str:
    parts = ['"']
    for ch in s:
        if ch == '"':
            parts.append('\\"')
        elif ch == "\\":
            parts.append("\\\\")
        else:
            code = ord(ch)
            if code < 0x20:
                parts.append(_SHORT_ESCAPES.get(code) or "\\u%04x" % code)
            else:
                # Everything else (incl. U+2028/U+2029 and DEL) stays literal:
                # JCS escapes only quotation mark, backslash and C0 controls.
                parts.append(ch)
    parts.append('"')
    return "".join(parts)


def _serialize(value, out: list) -> None:
    if value is None:
        out.append("null")
    elif isinstance(value, bool):
        out.append("true" if value else "false")
    elif isinstance(value, str):
        out.append(_escape_jcs_string(value))
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError(
                "NON_IJSON", "NaN/Infinity value is forbidden")
        if value.is_integer():
            # Integer-valued double in the safe range: ES6 renders it
            # without any fraction ("1.0" -> "1", "-0.0" -> "0"); values
            # beyond the safe range were rejected at step (3).
            out.append(str(int(value)))
        else:
            out.append(_es6_number_text(value))
    elif isinstance(value, list):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _serialize(item, out)
        out.append("]")
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError(
                    "NON_IJSON", f"object key is not a string: {key!r}")
        out.append("{")
        first = True
        # RFC 8785 orders object members by the UTF-16 code units of the key
        # (which byte-sorts the UTF-16-BE encoding); identical to code-point
        # order for BMP-only keys.
        for key in sorted(value, key=lambda k: k.encode("utf-16-be")):
            if not first:
                out.append(",")
            first = False
            out.append(_escape_jcs_string(key))
            out.append(":")
            _serialize(value[key], out)
        out.append("}")
    else:
        raise CanonicalizationError(
            "NON_IJSON", f"unsupported value type {type(value).__name__}")


def jcs_serialize(value) -> str:
    """RFC 8785 (JCS) serialization for the I-JSON domain of this contract."""
    out: list = []
    _serialize(value, out)
    return "".join(out)


# ---------------------------------------------------------------------------
# Steps (1)-(6) entry point
# ---------------------------------------------------------------------------

def canonicalize(payload):
    """Run the frozen canonical profile pipeline over the ESCAPED payload.

    ``payload`` is the already-escaped representation: a JSON text/bytes
    string of it, or the parsed object itself. Producers apply step 0 first
    (escape_dollar_keys). Returns ``(canonical_text, payload_hash)`` where
    payload_hash is the lower-case hex SHA-256 of the canonical UTF-8 bytes.
    """
    value = _parse_payload(payload)        # (1) parse, I-JSON constraints
    _reject_nonfinite(value)               # (1) NaN/Infinity (object inputs)
    _check_nfc(value)                      # (2) NFC, reject silently-never
    _check_structure(value)                # (3) tagged/$keys/number ranges
    value = _normalize_time_fields(value)  # (4) registered time fields only
    text = jcs_serialize(value)            # (5) RFC 8785 JCS (ES6 numbers)
    payload_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()  # (6)
    return text, payload_hash
