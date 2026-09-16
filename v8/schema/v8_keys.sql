-- v8 G2: SQL key derivation / hashing helpers.
--
-- Mirrors the Python side byte-for-byte so later stages can derive keys
-- inside transactions. sha256(bytea) is the PostgreSQL builtin; pgcrypto is
-- not available and not needed.
--
-- Byte conventions (frozen, event_key@v1 clause (iv)):
--   * UUID identity fields take the RFC 9562 16-byte binary form.
--   * Non-UUID text identifiers take their UTF-8 bytes verbatim.
--   * Variable-length segments are prefixed with an 8-byte big-endian length.
--   * Integers inside hash inputs use canonical_integer_bytes (decimal
--     ASCII digits, no leading zeros); attempt_no/chunk_index ordinals are
--     always non-negative. Fixed-width counters use plain uint64be.

-- 8-byte big-endian length prefix for a byte segment.
CREATE FUNCTION v_len8(b bytea) RETURNS bytea
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN decode(lpad(to_hex(octet_length(b)), 16, '0'), 'hex');

-- 8-byte big-endian unsigned encoding of a non-negative bigint.
-- (Two's-complement big-endian equals unsigned big-endian for [0, 2^63-1],
-- the only domain these keys ever encode.)
CREATE FUNCTION v_u64be(n bigint) RETURNS bytea
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN decode(lpad(to_hex(n), 16, '0'), 'hex');

-- Decimal-digit ASCII bytes, no leading zeros; 0 encodes as single 0x30.
CREATE FUNCTION v_canonical_integer_bytes(n bigint) RETURNS bytea
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN convert_to(n::text, 'UTF8');

-- UTF-8 bytes of a text identifier, verbatim.
CREATE FUNCTION v_identity_bytes(t text) RETURNS bytea
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN convert_to(t, 'UTF8');

-- RFC 9562 16-byte binary form of a UUID (hex without hyphens).
CREATE FUNCTION v_uuid16(id uuid) RETURNS bytea
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN decode(replace(id::text, '-', ''), 'hex');

-- Lowercase hex SHA-256 of a text value's UTF-8 bytes.
CREATE FUNCTION v_sha256_hex(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN encode(sha256(convert_to(t, 'UTF8')), 'hex');

-- event_key@v1 for the streaming event type (assistant/chunk):
--   SHA-256("v8:event-key@v1\0"
--        || len8(effect_id bytes) || effect_id bytes
--        || uint64be(attempt_no)
--        || len8(stream_id bytes) || stream_id bytes
--        || canonical_integer_bytes(chunk_index)) as lowercase hex.
CREATE FUNCTION v_event_key_streaming(
    p_effect_id uuid, p_attempt_no bigint, p_stream_id text, p_chunk_index bigint
) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN encode(sha256(
    convert_to('v8:event-key@v1', 'UTF8') || '\x00'::bytea
    || v_len8(v_uuid16(p_effect_id)) || v_uuid16(p_effect_id)
    || v_u64be(p_attempt_no)
    || v_len8(v_identity_bytes(p_stream_id)) || v_identity_bytes(p_stream_id)
    || v_canonical_integer_bytes(p_chunk_index)
), 'hex');

-- turn_end_key@v1: canonical end slot key, one per turn, never caller-set:
--   SHA-256("v8:turn-end-key@v1\0"
--        || len8(session_id bytes) || session_id bytes
--        || len8(turn_id bytes) || turn_id bytes) as lowercase hex.
CREATE FUNCTION v_turn_end_key(p_session_id uuid, p_turn_id uuid) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN encode(sha256(
    convert_to('v8:turn-end-key@v1', 'UTF8') || '\x00'::bytea
    || v_len8(v_uuid16(p_session_id)) || v_uuid16(p_session_id)
    || v_len8(v_uuid16(p_turn_id)) || v_uuid16(p_turn_id)
), 'hex');

-- Database-internal derived event key for non-stream events (public append
-- path, bound to the raw occurrence identity):
--   SHA-256("v8:nonstream-event-key@db1\0"
--        || len8(session_id bytes) || session_id bytes
--        || len8(event_type bytes) || event_type bytes
--        || len8(command_id bytes) || command_id bytes
--        || canonical_integer_bytes(batch_item_ordinal)
--        || len8(payload_hash bytes) || payload_hash bytes) as lowercase hex.
CREATE FUNCTION v_nonstream_event_key(
    p_session_id uuid, p_event_type text, p_command_id text,
    p_batch_item_ordinal bigint, p_payload_hash text
) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
RETURN encode(sha256(
    convert_to('v8:nonstream-event-key@db1', 'UTF8') || '\x00'::bytea
    || v_len8(v_uuid16(p_session_id)) || v_uuid16(p_session_id)
    || v_len8(v_identity_bytes(p_event_type)) || v_identity_bytes(p_event_type)
    || v_len8(v_identity_bytes(p_command_id)) || v_identity_bytes(p_command_id)
    || v_canonical_integer_bytes(p_batch_item_ordinal)
    || v_len8(v_identity_bytes(p_payload_hash)) || v_identity_bytes(p_payload_hash)
), 'hex');
