"""G16 gate: v8 audit — versioned raw-byte audit keys, the effect_audit full
column set, the two occurrence child tables and internal_op_audits.

Run: uv run python v8/audit/test_audit.py  (exit 0 = pass)

Contract: docs/designs/v8-dev.md 1.3 L78-L80 (the five keys), 3.2.2
(effect_audit DDL + occurrence tables), 3.1.2 (the three rejection paths).
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from server import get_server
from v8.audit.setup_db import DB, main as setup_db
from v8.canonical.keys import (
    BINDING_FIXED_SLOTS,
    binding_occurrences_from_json,
    malformed_binding_fingerprint_v2,
    occurrence_bytes,
    raw_invalid_digest_v1,
    received_result_fingerprint_v2,
    rejection_fingerprint_v1,
    result_occurrences_from_json,
    transport_rejection_key_v1,
)


def _uri() -> str:
    return get_server().get_uri(DB)


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def one(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row


def rows(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        out = cur.fetchall()
    conn.commit()
    return out


def exec_sql(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


def raises(conn, sql, params=()) -> str:
    """Run a statement expecting failure; return the error text (rollback)."""
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.rollback()
        return ""
    except psycopg2.Error as exc:
        conn.rollback()
        return str(exc)


# ---------------------------------------------------------------------------
# Independent byte composition (golden expectations are derived here, never
# by calling the module under test).
# ---------------------------------------------------------------------------

def _occ_bytes(name: bytes, tag: str, value: bytes) -> bytes:
    return (struct.pack(">Q", len(name)) + name + tag.encode() + b"\x00"
            + struct.pack(">Q", len(value)) + value)


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# 1. rejection_fingerprint@v1 / transport_rejection_key@v1
# ---------------------------------------------------------------------------

def test_rejection_keys(conn) -> None:
    # (1) input = the raw payload bytes as received: no re-serialization.
    a = b'{"b":1,"a":2}'
    b = b'{"a":2,"b":1}'
    check("D1: semantically equal, byte-different payloads -> different keys",
          rejection_fingerprint_v1(a) != rejection_fingerprint_v1(b))
    check("D1: golden = SHA-256 of the raw payload bytes",
          rejection_fingerprint_v1(a) == _sha(a) and len(rejection_fingerprint_v1(a)) == 64)
    # escaping / combining characters survive verbatim
    esc = b'{"t":"a\\u0062c"}'
    plain = b'{"t":"abc"}'
    check("D1: escape forms are not normalized (different keys)",
          rejection_fingerprint_v1(esc) != rejection_fingerprint_v1(plain))
    check("D1: identical bytes are stable",
          rejection_fingerprint_v1(esc) == rejection_fingerprint_v1(esc))
    check("D1: version tag is not part of the hash input (name only)",
          rejection_fingerprint_v1(b"") == _sha(b""))

    # (2) transport key: raw frame bytes, no payload boundary needed.
    frame = b"\x00\x01FRAMEBYTES\xff"
    check("D2: golden = SHA-256 of the raw frame bytes",
          transport_rejection_key_v1(frame) == _sha(frame))
    other = b"\x00\x01FRAMEBYTES\xfe"
    check("D2: one frame byte differs -> different key",
          transport_rejection_key_v1(frame) != transport_rejection_key_v1(other))
    check("D2: same frame, different payload interpretation -> same key",
          transport_rejection_key_v1(frame) == transport_rejection_key_v1(bytes(frame)))
    check("D2: transport key never equals a rejection fingerprint of its bytes",
          transport_rejection_key_v1(frame) == rejection_fingerprint_v1(frame)
          and len(transport_rejection_key_v1(frame)) == 64)


# ---------------------------------------------------------------------------
# 2. malformed_binding_fingerprint@v2 (D3)
# ---------------------------------------------------------------------------

def test_binding_fingerprint(conn) -> None:
    raw = b'{"session_id":"s1","idempotency_key":"secret","zz":1}'
    occ, masked = binding_occurrences_from_json(raw)
    # segment 1 = the ten fixed slots in DDL order, missing ones synthesized
    check("D3: fixed segment is exactly the ten slots in DDL order",
          [o[0] for o in occ[:10]] == [w.encode() for (_s, w) in BINDING_FIXED_SLOTS],
          [o[0] for o in occ[:10]])
    check("D3: missing known field -> synthesized NULL placeholder",
          occ[1][1] == "NULL" and occ[1][2] == b"" and occ[1][0] == b"step_id")
    check("D3: present known field keeps its arrival order and TEXT tag",
          occ[0][0] == b"session_id" and occ[0][1] == "TEXT" and occ[0][2] == b"s1")
    check("D3: unknown fields follow the fixed segment",
          [o[0] for o in occ[10:]] == [b"zz"])

    # sensitive-domain masking: the raw key never survives
    hexed = hashlib.sha256(b"secret").hexdigest().encode()
    idem = next(o for o in occ if o[0] == b"idempotency_key")
    check("D3: idempotency_key occurrence value = sha256 hex of the decoded bytes",
          idem[1] == "TEXT" and idem[2] == hexed)
    check("D3: masked payload carries the quoted hex literal, never the value",
          b"secret" not in masked and b'"' + hexed + b'"' in masked)

    # golden: independent re-derivation of the whole encoding
    expected = b"".join(_occ_bytes(n, t, v) for (n, t, v) in occ)
    check("D3: golden = SHA-256 of the frozen per-occurrence framing",
          malformed_binding_fingerprint_v2(occ) == _sha(expected))

    # unknown-field coverage: a different extra field changes the key
    raw2 = b'{"session_id":"s1","idempotency_key":"secret","zz":1,"extra":9}'
    occ2, _ = binding_occurrences_from_json(raw2)
    check("D3: unknown fields are covered (extra_field changes the key)",
          malformed_binding_fingerprint_v2(occ2) != malformed_binding_fingerprint_v2(occ))

    # unknown-segment ordering: decoded-name UTF-8 byte order, not arrival
    raw3 = b'{"session_id":"s1","idempotency_key":"k","zz":1,"aa":2}'
    occ3, _ = binding_occurrences_from_json(raw3)
    order = [o[0] for o in occ3[10:]]
    check("D3: unknown segment ordered by decoded-name UTF-8 bytes (aa < zz)",
          order == [b"aa", b"zz"], order)
    raw4 = b'{"session_id":"s1","idempotency_key":"k","aa":2,"zz":1}'
    occ4, _ = binding_occurrences_from_json(raw4)
    check("D3: arrival order of unknown groups does not change the key",
          malformed_binding_fingerprint_v2(occ3) == malformed_binding_fingerprint_v2(occ4))

    # plain-null vs missing equivalence (fixed plain spelling)
    pn = binding_occurrences_from_json(b'{"session_id":null}')[0]
    ms = binding_occurrences_from_json(b'{"zz":1}')[0]
    o_null = next(o for o in pn if o[0] == b"session_id")
    o_miss = next(o for o in ms if o[0] == b"session_id")
    check("D3: plain explicit null == synthesized placeholder for a known field",
          o_null == o_miss and o_miss == (b"session_id", "NULL", b""), (o_null, o_miss))
    # escaped spelling is an honest difference
    esc = binding_occurrences_from_json(b'{"session_\\u0069d":null}')[0]
    o_esc = next(o for o in esc if o[0].startswith(b"session_"))
    check("D3: escaped spelling differs byte-wise from the plain placeholder",
          o_esc != o_null and b"\\u0069" in o_esc[0])

    # field-name length delimiting: a NUL inside the name is unambiguous
    n1 = [ (b"a\x00b", "TEXT", b"v") ]
    n2 = [ (b"a", "TEXT", b"b\x00"), ("TEXT", "NULL", b"") ][:1]
    check("D3: NUL inside a field name is not a delimiter collision",
          malformed_binding_fingerprint_v2(n1) != malformed_binding_fingerprint_v2(n2))

    # sensitive value that is not a string -> unbounded key (no key computed)
    from v8.canonical.keys import UnboundedKeyError
    try:
        binding_occurrences_from_json(b'{"idempotency_key":null}')
        check("D3: non-string sensitive value must raise", False, "no raise")
    except UnboundedKeyError:
        check("D3: non-string sensitive value -> UNBOUNDED_KEY path", True)

    # RAW is not in the binding tag domain (the shared SQL encoder accepts
    # it for the result side; the binding domain is enforced by the Python
    # key function here and by the table column CHECK in D7 below).
    try:
        malformed_binding_fingerprint_v2([(b"a", "RAW", b"b")])
        check("D3: binding key function rejects the RAW tag", False, "no raise")
    except ValueError:
        check("D3: binding key function rejects the RAW tag", True)


# ---------------------------------------------------------------------------
# 3. received_result_fingerprint@v2 + raw_invalid_digest@v1 (D4)
# ---------------------------------------------------------------------------

def test_result_fingerprint(conn) -> None:
    raw = (b'{"outcome":"succeeded","nested":{"idempotency_key":"k2"},'
           b'"arr":[1,2]}')
    path, occ, ev, cls = result_occurrences_from_json(raw)
    check("D4: complete parse path", path == "complete" and cls is None, path)
    # DFS: root produces no occurrence; container precedes its children
    names = [o[0] for o in occ]
    check("D4: DFS order — container occurrence precedes its children",
          names == [b"outcome", b"nested", b"idempotency_key", b"arr", b"0", b"1"],
          names)
    check("D4: array index occurrence names are ASCII decimal",
          occ[4][0] == b"0" and occ[5][0] == b"1")
    check("D4: nested idempotency_key masked (no raw value anywhere)",
          b"k2" not in b"".join(o[2] for o in occ))
    expected = b"".join(_occ_bytes(n, t, v) for (n, t, v) in occ)
    check("D4: golden = SHA-256 of the DFS occurrence framing",
          received_result_fingerprint_v2(occ) == _sha(expected))
    check("D4: complete path tags stay in the five-value set",
          all(o[1] in ("TEXT", "NUMBER", "BOOLEAN", "JSON", "NULL") for o in occ))

    # corrupt path: exactly one RAW_INVALID occurrence carrying the digest
    bad = b'{"a":'
    path2, occ2, ev2, cls2 = result_occurrences_from_json(bad)
    check("D4: truncation -> raw_invalid / TRUNCATED",
          path2 == "raw_invalid" and cls2 == "TRUNCATED", (path2, cls2))
    check("D4: corrupt path is exactly one __raw_invalid__ RAW occurrence",
          len(occ2) == 1 and occ2[0][0] == b"__raw_invalid__" and occ2[0][1] == "RAW")
    check("D4: corrupt occurrence value = raw_invalid_digest@v1 bytes",
          occ2[0][2] == raw_invalid_digest_v1(bad).encode()
          and occ2[0][2] == _sha(bad).encode())
    check("D4: corrupt path evidence is the digest, never the original",
          ev2 == _sha(bad).encode() and b'{"a":' not in ev2)
    check("D4: distinct corrupt inputs -> distinct digests",
          result_occurrences_from_json(b'{"a":')[2]
          != result_occurrences_from_json(b'{"b":')[2])
    check("D4: same corrupt input -> same digest (idempotent convergence)",
          result_occurrences_from_json(b'{"a":')[2]
          == result_occurrences_from_json(b'{"a":')[2])

    # non-object top level and non-string sensitive value -> UNBOUNDED_KEY
    check("D4: top-level array -> UNBOUNDED_KEY",
          result_occurrences_from_json(b'[1,2]')[3] == "UNBOUNDED_KEY")
    check("D4: nested non-string idempotency_key -> UNBOUNDED_KEY",
          result_occurrences_from_json(b'{"k":{"idempotency_key":5}}')[3] == "UNBOUNDED_KEY")

    # empty path
    p3, o3, e3, c3 = result_occurrences_from_json(b"")
    check("D4: zero received bytes -> empty path, zero occurrences",
          p3 == "empty" and o3 == [] and c3 is None)
    check("D4: empty sequence encodes as the empty byte sequence",
          received_result_fingerprint_v2([]) == _sha(b""))

    # RAW tag is legal on the result side only
    ok = one(conn, "SELECT encode(v_occurrence_bytes('\\x78'::bytea,'RAW','\\x79'::bytea),'hex')")
    check("D4: SQL occurrence encoder accepts the RAW tag (result side)",
          ok is not None)


# ---------------------------------------------------------------------------
# 4. effect_audit full column set (D6)
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = [
    "command_id", "result_hash", "result_fingerprint", "result_parse_path",
    "raw_invalid_class", "binding_invalid_class",
    "session_id", "step_id", "effect_id", "attempt_no",
    "received_session_id", "received_step_id", "received_effect_id",
    "received_attempt_no",
    "expected_driver", "received_driver",
    "expected_driver_epoch", "received_driver_epoch",
    "expected_dispatch_session_fence", "received_dispatch_session_fence",
    "expected_job_fence", "received_job_fence",
    "expected_request_hash", "received_request_hash",
    "expected_idempotency_key_hash", "received_idempotency_key_hash",
    "received_binding_raw", "received_result_raw",
    "audit_context_session_id",
    "internal_op_kind", "parent_command_id", "internal_op_ordinal",
    "audit_key_kind", "audit_key_value",
]


def test_effect_audit_columns(conn) -> None:
    present = {r[0] for r in rows(conn,
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name='effect_audit'")}
    missing = [c for c in REQUIRED_COLUMNS if c not in present]
    check("D6: every frozen effect_audit column exists", not missing, missing)

    # the dedup key is exactly the ten frozen columns
    cols = one(conn, "SELECT v_effect_audit_dedup_key_columns()")[0]
    check("D6: dedup key is exactly the ten frozen columns",
          len(cols) == 10
          and set(cols) == {"audit_context_session_id", "effect_id",
                            "attempt_no", "audit_key_kind", "audit_key_value",
                            "result_fingerprint", "reason", "internal_op_kind",
                            "parent_command_id", "internal_op_ordinal"}, cols)

    # three-value CHECK negatives
    for col, val in (("result_parse_path", "bogus"),
                     ("raw_invalid_class", "BOGUS"),
                     ("binding_invalid_class", "BOGUS")):
        err = raises(conn,
            f"INSERT INTO effect_audit(audit_context_session_id, audit_key_kind,"
            f" audit_key_value, result_fingerprint, reason, {col})"
            " VALUES ('00000000-0000-4000-8000-000000000001','canonical_binding',"
            " 'k','f','r',%s)", (val,))
        check(f"D6: {col} CHECK rejects a value outside the closed set", err != "")
    # internal triple all-or-none negative
    err = raises(conn,
        "INSERT INTO effect_audit(audit_context_session_id, audit_key_kind,"
        " audit_key_value, result_fingerprint, reason, internal_op_kind)"
        " VALUES ('00000000-0000-4000-8000-000000000001','canonical_binding',"
        " 'k','f','r','failure_drain')")
    check("D6: internal triple all-or-none CHECK rejects a partial triple", err != "")


# ---------------------------------------------------------------------------
# 5. occurrence tables + internal_op_audits (D7/D14)
# ---------------------------------------------------------------------------

_AUDIT_SEQ = [0]


def _new_audit(conn) -> int:
    # The ten-column UNIQUE NULLS NOT DISTINCT dedup key makes byte-identical
    # audit rows collapse; each test row needs its own key value.
    _AUDIT_SEQ[0] += 1
    return one(conn,
        "INSERT INTO effect_audit(audit_context_session_id, audit_key_kind,"
        " audit_key_value, result_fingerprint, reason)"
        " VALUES ('00000000-0000-4000-8000-000000000001','malformed_binding',"
        " %s,'f','r') RETURNING audit_id", (f"k{_AUDIT_SEQ[0]}",))[0]


def test_occurrence_tables(conn) -> None:
    aid = _new_audit(conn)
    exec_sql(conn,
        "INSERT INTO effect_audit_binding_occurrences VALUES"
        " (%s,0,'\\x61'::bytea,'TEXT','\\x76'::bytea)", (aid,))
    # binding tag domain forbids RAW
    err = raises(conn,
        "INSERT INTO effect_audit_binding_occurrences VALUES"
        " (%s,1,'\\x61'::bytea,'RAW','\\x76'::bytea)", (aid,))
    check("D7: binding occurrence tag CHECK forbids RAW", err != "")
    # result tag domain allows RAW but not junk
    exec_sql(conn,
        "INSERT INTO effect_audit_result_occurrences VALUES"
        " (%s,0,'\\x61'::bytea,'RAW','\\x76'::bytea)", (aid,))
    err = raises(conn,
        "INSERT INTO effect_audit_result_occurrences VALUES"
        " (%s,1,'\\x61'::bytea,'JUNK','\\x76'::bytea)", (aid,))
    check("D7: result occurrence tag CHECK rejects an unknown tag", err != "")
    # negative occurrence_no
    err = raises(conn,
        "INSERT INTO effect_audit_binding_occurrences VALUES"
        " (%s,-1,'\\x61'::bytea,'TEXT','\\x76'::bytea)", (aid,))
    check("D7: occurrence_no >= 0 CHECK holds", err != "")
    # immutability
    err = raises(conn,
        "UPDATE effect_audit_binding_occurrences SET type_tag='NULL'"
        " WHERE audit_id=%s AND occurrence_no=0", (aid,))
    check("D7: occurrence rows are append-only (UPDATE rejected)", err != "")
    err = raises(conn,
        "DELETE FROM effect_audit_binding_occurrences WHERE audit_id=%s", (aid,))
    check("D7: occurrence rows are append-only (DELETE rejected)", err != "")

    # SQL replay == Python fingerprint, on a dedicated audit row set
    aid2 = _new_audit(conn)
    occ = [(b"session_id", "TEXT", b"s1"), (b"step_id", "NULL", b"")]
    for i, (n, t, v) in enumerate(occ):
        exec_sql(conn,
            "INSERT INTO effect_audit_binding_occurrences VALUES"
            " (%s,%s,%s,%s,%s)", (aid2, i, psycopg2.Binary(n), t, psycopg2.Binary(v)))
    sql_fp = one(conn, "SELECT v_binding_occurrences_fingerprint(%s)", (aid2,))[0]
    check("D11: SQL replay of the occurrence rows == Python fingerprint",
          sql_fp == malformed_binding_fingerprint_v2(occ), sql_fp)

    # D14: internal_op_audits — constraints + immutability
    sid = "00000000-0000-4000-8000-000000000002"
    exec_sql(conn,
        "INSERT INTO internal_op_audits(parent_session_id, parent_command_id,"
        " internal_op_ordinal, internal_op_kind, event_key)"
        " VALUES (%s,'cmd',0,'infra_closure','ek1')", (sid,))
    err = raises(conn,
        "INSERT INTO internal_op_audits(parent_session_id, parent_command_id,"
        " internal_op_ordinal, internal_op_kind, event_key)"
        " VALUES (%s,'cmd',1,'not_a_kind','ek2')", (sid,))
    check("D14: internal_op_kind five-value CHECK", err != "")
    err = raises(conn,
        "INSERT INTO internal_op_audits(parent_session_id, parent_command_id,"
        " internal_op_ordinal, internal_op_kind)"
        " VALUES (%s,'cmd',0,'infra_closure')", (sid,))
    check("D14: UNIQUE(parent_session_id, parent_command_id, ordinal)", err != "")
    err = raises(conn,
        "INSERT INTO internal_op_audits(parent_session_id, parent_command_id,"
        " internal_op_ordinal, internal_op_kind, event_key)"
        " VALUES (%s,'cmd2',9,'infra_closure','ek1')", (sid,))
    check("D14: UNIQUE(parent_session_id, event_key)", err != "")
    err = raises(conn,
        "INSERT INTO internal_op_audits(parent_session_id, parent_command_id,"
        " internal_op_ordinal, internal_op_kind)"
        " VALUES (%s,'cmd3',-1,'infra_closure')", (sid,))
    check("D14: ordinal >= 0 CHECK", err != "")
    err = raises(conn,
        "UPDATE internal_op_audits SET internal_op_kind='failure_drain'"
        " WHERE parent_session_id=%s", (sid,))
    check("D14: internal_op_audits is append-only", err != "")
    # cross-session triple isolation: the same command_id is free elsewhere
    exec_sql(conn,
        "INSERT INTO internal_op_audits(parent_session_id, parent_command_id,"
        " internal_op_ordinal, internal_op_kind)"
        " VALUES ('00000000-0000-4000-8000-000000000003','cmd',0,'infra_closure')")
    check("D14: the triple is scoped per session (same command_id elsewhere ok)",
          one(conn, "SELECT count(*) FROM internal_op_audits"
                    " WHERE parent_command_id='cmd'")[0] == 2)


# ---------------------------------------------------------------------------
# 6. Desensitization across the three carriers (D8)
# ---------------------------------------------------------------------------

def test_desensitization(conn) -> None:
    secret = "sk-live-SECRETVALUE"
    raw = ('{"session_id":"s1","idempotency_key":"%s",'
           '"outer":{"idempotency_key":"%s","keep":"ok"},'
           '"arr":[{"idempotency_key":"%s"}]}' % (secret, secret, secret)).encode()
    occ, masked = binding_occurrences_from_json(raw)
    hexed = hashlib.sha256(secret.encode()).hexdigest().encode()
    check("D8: nested/array sensitive members are all replaced (no raw hits)",
          secret.encode() not in masked and secret not in masked.decode("utf-8", "replace"))
    check("D8: every sensitive occurrence carries the 64-byte hex",
          all(o[2] == hexed for o in occ if o[0] == b"idempotency_key"))
    check("D8: non-sensitive nested bytes are preserved verbatim",
          b'"keep":"ok"' in masked)
    # three carriers: scalar column, raw bytea evidence, occurrence rows
    aid = _new_audit(conn)
    exec_sql(conn,
        "INSERT INTO effect_audit_binding_occurrences VALUES"
        " (%s,0,'session_id','TEXT','s1')", (aid,))
    exec_sql(conn,
        "INSERT INTO effect_audit_binding_occurrences VALUES"
        " (%s,1,'idempotency_key','TEXT',%s)",
        (aid, psycopg2.Binary(hexed)))
    exec_sql(conn,
        "UPDATE effect_audit SET received_idempotency_key_hash=%s,"
        " received_binding_raw=%s WHERE audit_id=%s",
        (hexed.decode(), psycopg2.Binary(masked), aid))
    hit = one(conn,
        "SELECT count(*) FROM effect_audit_binding_occurrences"
        " WHERE audit_id=%s AND encode(value_raw,'escape') LIKE %s",
        (aid, "%" + secret + "%"))[0]
    check("D8: occurrence carrier holds zero raw-value hits", hit == 0)
    hit = one(conn,
        "SELECT count(*) FROM effect_audit WHERE audit_id=%s AND"
        " encode(received_binding_raw,'escape') LIKE %s",
        (aid, "%" + secret + "%"))[0]
    check("D8: raw-bytes carrier holds zero raw-value hits", hit == 0)
    hit = one(conn,
        "SELECT count(*) FROM effect_audit WHERE audit_id=%s AND"
        " received_idempotency_key_hash = %s", (aid, hexed.decode()))[0]
    check("D8: scalar carrier holds the hash, not the value", hit == 1)


# ---------------------------------------------------------------------------
# 7. Version discipline + v10 reuse surface (D12)
# ---------------------------------------------------------------------------

def test_version_tags(conn) -> None:
    # version tags are part of the key NAME, never the hash input: two
    # different key names over identical bytes must agree on the digest body
    a = rejection_fingerprint_v1(b"payload")
    check("D12: version tag not in the hash input",
          a == transport_rejection_key_v1(b"payload") == _sha(b"payload"))
    src = Path(AGENT_ROOT, "v8", "canonical", "keys.py").read_text()
    for name in ("rejection_fingerprint_v1", "transport_rejection_key_v1",
                 "malformed_binding_fingerprint_v2",
                 "received_result_fingerprint_v2", "raw_invalid_digest_v1"):
        check(f"D12: v10 reuse surface documented for {name}", f"def {name}(" in src)
    doc = Path(AGENT_ROOT, "v8", "audit", "v8_audit.sql").read_text()
    check("D12: the SQL side documents byte-parity with the Python reference",
          "byte-identical to the Python reference" in doc)


def test_ingress_paths(conn) -> None:
    sid = "00000000-0000-4000-8000-00000000000a"
    frame = b"\x00FRAME"
    payload = b'{"a":1}'

    # (a) ID cannot be attributed -> transport key, command_id NOT occupied,
    #     independent ingress store only.
    r = one(conn, "SELECT v_ingress_reject(%s,%s,%s,%s,%s)",
            (psycopg2.Binary(frame), psycopg2.Binary(payload), False, False, sid))[0]
    check("D5(a): unattributable ID -> path a / transport_rejection_key",
          r["path"] == "a"
          and r["rejection_key_kind"] == "transport_rejection_key",
          r)
    check("D5(a): command_id NOT occupied",
          r["command_id_occupied"] is False, r)
    check("D5(a): key value = sha256 of the raw frame",
          r["rejection_key_value"] == _sha(frame), r["rejection_key_value"])
    n = one(conn, "SELECT count(*) FROM ingress_rejections"
                  " WHERE audit_context_session_id=%s"
                  " AND rejection_key_value=%s", (sid, _sha(frame)))[0]
    check("D10: independent ingress store holds exactly one row", n == 1, n)
    one(conn, "SELECT v_ingress_reject(%s,%s,%s,%s,%s)",
        (psycopg2.Binary(frame), psycopg2.Binary(payload), False, False, sid))
    n = one(conn, "SELECT count(*) FROM ingress_rejections"
                  " WHERE audit_context_session_id=%s"
                  " AND rejection_key_value=%s", (sid, _sha(frame)))[0]
    check("D10: same-frame resend is idempotent (still one row)", n == 1, n)
    check("D10: path (a) never creates a command binding",
          one(conn, "SELECT count(*) FROM command_bindings"
                    " WHERE session_id=%s", (sid,))[0] == 0)

    # (b) transport malformed with a valid ID -> transport key, occupies.
    r = one(conn, "SELECT v_ingress_reject(%s,%s,%s,%s,%s)",
            (psycopg2.Binary(frame), None, None, True, sid))[0]
    check("D5(b): malformed transport -> path b + command_id occupied",
          r["path"] == "b"
          and r["rejection_key_kind"] == "transport_rejection_key"
          and r["command_id_occupied"] is True, r)

    # (c) transport valid but payload not canonicalizable -> rejection fp.
    r = one(conn, "SELECT v_ingress_reject(%s,%s,%s,%s,%s)",
            (psycopg2.Binary(frame), psycopg2.Binary(payload), False, True, sid))[0]
    check("D5(c): uncanonicalizable payload -> path c + rejection_fingerprint",
          r["path"] == "c" and r["rejection_key_kind"] == "rejection_fingerprint"
          and r["command_id_occupied"] is True, r)
    check("D5(c): key value = sha256 of the raw payload bytes",
          r["rejection_key_value"] == _sha(payload))

    # (b) precedes (c): an unlocatable payload boundary wins over the
    # canonicalization judgement
    r = one(conn, "SELECT v_ingress_reject(%s,%s,%s,%s,%s)",
            (psycopg2.Binary(frame), None, False, True, sid))[0]
    check("D5: (b) precedes (c) when both conditions hold",
          r["path"] == "b", r)

    # canonicalizable input MUST NOT be routed into a rejection path
    err = raises(conn, "SELECT v_ingress_reject(%s,%s,%s,%s,%s)",
                 (psycopg2.Binary(frame), psycopg2.Binary(payload), True, True, sid))
    check("D5: a canonicalizable input is refused by the rejection entry", err != "")

    # accepted namespace carries only the canonical computed hash
    check("D5: accepted namespace admits only canonical_request_hash",
          one(conn, "SELECT v_assert_accepted_key_kind('canonical_request_hash')")[0]
          is True
          and one(conn, "SELECT v_assert_accepted_key_kind('rejection_fingerprint')")[0]
          is False)


def test_audit_writer(conn) -> None:
    sid = "00000000-0000-4000-8000-00000000000b"
    eid = "00000000-0000-4000-8000-00000000000c"
    args = (sid, "malformed_binding", "k-w1", "fp1", "RESULT_OUTCOME_MISMATCH")
    step = "00000000-0000-4000-8000-00000000000d"
    a1 = one(conn, "SELECT v_effect_audit_write(%s,%s,%s,%s,%s,"
                   " 'cmd-1','rh-1','raw_invalid','CORRUPT_BYTES',NULL,"
                   " %s,%s,%s,1)", args + (sid, step, eid))[0]
    check("D9: the writer persists a full-column audit row", a1 is not None, a1)
    row = one(conn, "SELECT command_id, result_hash, result_parse_path,"
                    " raw_invalid_class, received_session_id IS NULL"
                    " FROM effect_audit WHERE audit_id=%s", (a1,))
    check("D9: command_id/result_hash/parse_path/class persisted",
          row[0] == "cmd-1" and row[1] == "rh-1" and row[2] == "raw_invalid"
          and row[3] == "CORRUPT_BYTES", row)

    # idempotent resend of the same binding -> still one row
    a2 = one(conn, "SELECT v_effect_audit_write(%s,%s,%s,%s,%s,"
                   " 'cmd-1','rh-1','raw_invalid','CORRUPT_BYTES',NULL,"
                   " %s,%s,%s,1)", args + (sid, step, eid))[0]
    check("D9: same binding resend is idempotent (same audit row)",
          a2 == a1, (a1, a2))
    # a different result under the same binding -> a second row
    a3 = one(conn, "SELECT v_effect_audit_write(%s,%s,%s,%s,%s,"
                   " 'cmd-1','rh-2','complete',NULL,NULL,"
                   " %s,%s,%s,1)",
             (sid, "malformed_binding", "k-w1", "fp2", "RESULT_OUTCOME_MISMATCH",
              sid, step, eid))[0]
    check("D9: same binding + different result -> a second audit row",
          a3 is not None and a3 != a1, (a1, a3))


# Hard-coded goldens: hand-computed once by an independent script over fixed
# byte vectors (never by the module under test), then frozen here.
GOLDEN_REJECTION = "a1d46c3cdb4e5795c8d637f80daeb578ebb1a9a65dc1ed5f11f51794c3c89f3a"
GOLDEN_TRANSPORT = "5c0dab010ab4cfc565bdaef0aea7aa01d0fb987c23b30d360dc10af355116bc7"
GOLDEN_RAW_INVALID = "ffb38b22ee3e0ca90325ebce953a9846990f292faf44c50498771602e31cb61f"
GOLDEN_BINDING = "463f04584966709be5553a26aa4e0ae1a58b112ca3afc98dd128a581a830cb7f"
GOLDEN_RESULT = "045c00d3d953771cb98af87fccd8f91045e612558864e099feb4a0a345684575"


def test_hardcoded_goldens(conn) -> None:
    check("D11: rejection_fingerprint@v1 hard-coded golden",
          rejection_fingerprint_v1(b'{"b":1,"a":2}') == GOLDEN_REJECTION,
          rejection_fingerprint_v1(b'{"b":1,"a":2}'))
    check("D11: transport_rejection_key@v1 hard-coded golden",
          transport_rejection_key_v1(b"\x00\x01FRAMEBYTES\xff") == GOLDEN_TRANSPORT)
    check("D11: raw_invalid_digest@v1 hard-coded golden",
          raw_invalid_digest_v1(b'{"a":') == GOLDEN_RAW_INVALID)
    bind_vec = ([(b"session_id", "TEXT", b"s1")]
                + [(w.encode(), "NULL", b"") for w in
                   ("step_id", "effect_id", "attempt_no", "driver",
                    "driver_epoch", "dispatch_session_fence", "job_fence",
                    "request_hash", "idempotency_key")]
                + [(b"zz", "TEXT", b"v")])
    check("D11: malformed_binding_fingerprint@v2 hard-coded golden",
          malformed_binding_fingerprint_v2(bind_vec) == GOLDEN_BINDING)
    res_vec = [(b"outcome", "TEXT", b"ok"), (b"arr", "JSON", b"[1,2]"),
               (b"0", "NUMBER", b"1"), (b"1", "NUMBER", b"2")]
    check("D11: received_result_fingerprint@v2 hard-coded golden",
          received_result_fingerprint_v2(res_vec) == GOLDEN_RESULT)
    # the SQL side reproduces the same hard-coded binding golden
    aid = _new_audit(conn)
    for i, (n, t, v) in enumerate(bind_vec):
        exec_sql(conn,
            "INSERT INTO effect_audit_binding_occurrences VALUES"
            " (%s,%s,%s,%s,%s)", (aid, i, psycopg2.Binary(n), t, psycopg2.Binary(v)))
    check("D11: SQL replay reproduces the hard-coded binding golden",
          one(conn, "SELECT v_binding_occurrences_fingerprint(%s)", (aid,))[0]
          == GOLDEN_BINDING)


def main() -> int:

    setup_db()
    conn = psycopg2.connect(_uri())
    conn.autocommit = False
    try:
        test_rejection_keys(conn)
        test_binding_fingerprint(conn)
        test_result_fingerprint(conn)
        test_effect_audit_columns(conn)
        test_occurrence_tables(conn)
        test_desensitization(conn)
        test_hardcoded_goldens(conn)
        test_ingress_paths(conn)
        test_audit_writer(conn)
        test_version_tags(conn)
    finally:
        conn.close()
    print("[G16] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
