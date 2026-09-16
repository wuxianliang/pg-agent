"""G1 gate: v8/canonical — canonical profile @v1 and named key derivation.

All expected bytes/hashes below are FROZEN golden vectors computed
independently of this module (a standalone hashlib/struct/uuid script derived
by hand from docs/designs/v8-dev.md section 1.3 and the s31b digest section 3),
then hardcoded here. Corresponds to the Conformance-10 canonical golden
vector requirement.
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT_ROOT = ROOT.parent.parent
sys.path.insert(0, str(AGENT_ROOT))

from v8.canonical.canonical import (  # noqa: E402
    TIME_FIELD_NAMES,
    CanonicalizationError,
    canonicalize,
    escape_dollar_keys,
    normalize_rfc3339,
    unescape_dollar_keys,
)
from v8.canonical.keys import (  # noqa: E402
    _i64be,
    _text_bytes,
    _u64be,
    canonical_integer_bytes,
    closer_event_key_v1,
    event_key_v1,
    identity_bytes,
    nonstream_event_key,
    provisional_unknown_effect_set_digest_v1,
    turn_end_key_v1,
)

U2028 = chr(0x2028)  # never spelled raw in source: it is a Python line boundary


def check(label: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        raise AssertionError(f"{label}: {detail}")


def rejects(label: str, payload, code: str) -> None:
    try:
        canonicalize(payload)
    except CanonicalizationError as exc:
        check(label, exc.code == code, f"got {exc.code} ({exc})")
        return
    check(label, False, "canonicalize unexpectedly succeeded")


# ---------------------------------------------------------------------------
# Frozen canonical golden vectors: (label, input, expected_text, expected_hash)
# ---------------------------------------------------------------------------

CANONICAL_GOLDEN = [
    # JCS member-order normalization.
    ("order", '{"b":1,"a":2}', '{"a":2,"b":1}',
     "d3626ac30a87e6f7a6428233b3c68299976865fa5508e4267c5415c76af7a772"),
    # Producer step-0 escape vectors (inputs are the escaped representations).
    ("esc2", {"$$int": "label"}, '{"$$int":"label"}',
     "95e316af5aa251566ddc4b6edec8e2828fa72db52c34ac93d5eade25fa4a2151"),
    ("esc3", {"$$$int": "label"}, '{"$$$int":"label"}',
     "a37fd130e77a6f642c916bd87e72c28f30b2cc98534bca576a5c6c86df15005c"),
    ("nested_esc", {"a": {"$$int": "label"}}, '{"a":{"$$int":"label"}}',
     "89e0bdcb72507d2ac56fd784268920631f4bbaee7dcf25bb6ce3f07042561203"),
    ("esc2_deep", {"b": [{"$$flag": True}], "a": {"$$int": "label"}},
     '{"a":{"$$int":"label"},"b":[{"$$flag":true}]}',
     "20bee1a49428aa26ddec34c3c04deb2b5e5f827d904f7f7dfa1aec3e98106c23"),
    # Tagged integers (unescaped single-$int reserved objects).
    ("tagged", '{"$int":"9007199254740993"}', '{"$int":"9007199254740993"}',
     "b2316b0e6156f56147323e61c23092825254b70222c2899d3aaf62067aa4885d"),
    ("tagged_max", '{"$int":"9223372036854775807"}',
     '{"$int":"9223372036854775807"}',
     "efc9f76360824e8b322f73f79a95d7ebfdb613197df9001f1d0f12a069b46cd6"),
    ("tagged_neg", '{"$int":"-9007199254740992"}',
     '{"$int":"-9007199254740992"}',
     "cca6fe8d4b170fa03bda3fa53103aa661ad022b8d1590b129a9cd28e4cb4d435"),
    # JCS string escaping: C0 control -> \uXXXX lowercase hex.
    ("ctrl", '{"k":"\\u0001"}', '{"k":"\\u0001"}',
     "b6f1faaa7ccf26dfeeb3bcc45708a6e4de9fe771f69aba9ccc1b6e5f3c3b60ef"),
    # U+2028 stays RAW in JCS output (not escaped).
    ("u2028", '{"k":"' + U2028 + '"}', '{"k":"' + U2028 + '"}',
     "460d7b4b88fe01d179a1febcbf6e038be99dc6d05d284425a463f688370e6541"),
    # Time normalization on the registered created_at field.
    ("time_z", '{"created_at":"2026-01-02T03:04:05Z"}',
     '{"created_at":"2026-01-02T03:04:05Z"}',
     "6c9e4bf65fa232577b1337224c88fd3303d38a5bdf7af0e8773f36cd70e8c802"),
    ("time_frac", '{"created_at":"2026-01-02T03:04:05.500Z"}',
     '{"created_at":"2026-01-02T03:04:05.5Z"}',
     "83d7710c15fa8d030cd4c59d0fb712e1a8ab559624b42dea1c721acdf7ed9d72"),
    ("time_123", '{"created_at":"2026-01-02T03:04:05.123000Z"}',
     '{"created_at":"2026-01-02T03:04:05.123Z"}',
     "ecceafe0a5704da772ee18e235eda4e748d3f65caac6b51689704abc43b83661"),
    # Unregistered fields are never rewritten, even when RFC-3339-shaped.
    ("note_untouched", '{"note":"2026-01-02T05:04:05+02:00"}',
     '{"note":"2026-01-02T05:04:05+02:00"}',
     "c40f928ea06037ede5463adb7ee95ec44da05e5c6a25b60cdd6b484667b54f52"),
    # Scalars, safe-integer boundaries, empty container, NFC pass.
    ("empty", "{}", "{}",
     "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"),
    ("scalars", '{"z":"x","a":[null,true,false]}',
     '{"a":[null,true,false],"z":"x"}',
     "7045c129bb5da1455a96338d86096376e7c98d8301779680a47583937995e1e7"),
    ("nums_sorted", '{"n":-9007199254740991,"m":0}',
     '{"m":0,"n":-9007199254740991}',
     "8a5f633cc072d663ba227573bde98d7097d6358cbd552bdc044c147eb995ce36"),
    ("safe_max", '{"n":9007199254740991}', '{"n":9007199254740991}',
     "e1da48c6a6089f06ecb4e0a2259e658e3786b2420f52baccdf929ec6460d7b41"),
    ("nfc_pass", '{"k":"é"}', '{"k":"é"}',
     "0ca09f1dffb485d259fc791100d48ad7ae9c17f52a2bb07b608c0e28fbca34a1"),
    # JCS orders members by UTF-16 code units: U+10000 (surrogate pair
    # D800 DC00) sorts BEFORE U+FFFF, unlike code-point order.
    ("utf16_order", {chr(0xFFFF): 1, chr(0x10000): 2},
     '{"' + chr(0x10000) + '":2,"' + chr(0xFFFF) + '":1}',
     "72406deb9e8efdb3b2d8b80c26ebd8d609a5338250baa8308cab44bbe7506499"),
    ("esc_flag", '{"$$flag":1}', '{"$$flag":1}',
     "f381877f3a6469f7cf8734ba352ac060ec88a8f5ccf313cd2ef9db4a6019a735"),
    # RFC 8785 non-integer number rendering (ES6 Number::toString): I-JSON
    # permits IEEE-754-expressible non-integer numbers and JCS fully
    # specifies their rendering; only NaN/Infinity are forbidden (spec 1.3
    # steps (1)/(5)). Integer-valued doubles render without any fraction.
    ("frac", '{"n":1.5}', '{"n":1.5}',
     "cb14d55cfe562fd6592d919f5dfacfa8708687b746a1d110c6dd5529c410e772"),
    ("frac_tenths", '{"n":0.1}', '{"n":0.1}',
     "c20c34ed16c837e86b4dcdb33f98c274c9f7da1231f64302082d2cd50743f951"),
    ("exp_form_int", '{"n":1e3}', '{"n":1000}',
     "fe1c788f83a7b21b9bb68ea3d588468319662e1ba670dceb5a83fc7d05a183a8"),
    ("exp_form_upper_E", '{"n":1E2}', '{"n":100}',
     "b39022c4ed96525c42cd0e7ce55308533962a655f1c19d5dac2f03e9dd995b2c"),
    ("frac_zero", '{"n":1.0}', '{"n":1}',
     "2bfd14f43d17fc7cea24e0917a8879b4b2f880b8baeec1b9d90fbaad655e71bd"),
    ("neg_zero", '{"n":-0.0}', '{"n":0}',
     "f3013f933b9fb80ab6d995e7ad9da36f683837ba1d81e950c943d40111eac2f0"),
    ("exp_neg", '{"n":1e-7}', '{"n":1e-7}',
     "747d6d23b64d1b2d579adb832b44de31c91c875bbef7a8e397f5d183a746b54b"),
    ("plain_small", '{"n":1e-6}', '{"n":0.000001}',
     "28343867a0be00aee19f81aa90cfd6c646878b9303fa15410d16bfd3f8894578"),
    ("jcs_round", '{"n":333333333.33333329}', '{"n":333333333.3333333}',
     "8e1aa496328ac7acbd045b34464ae11d72d8b525c355b85099382ffcb499143b"),
    ("quarter", '{"n":0.00025}', '{"n":0.00025}',
     "6b55f97afa0c6c46ba1512eba33285d4cdad8ec123b44a0c785dea04124083e9"),
]

# Equivalent RFC 3339 renderings of the same instant MUST canonicalize to the
# same bytes (registered field created_at).
TIME_EQUIVALENCE = {
    "6c9e4bf65fa232577b1337224c88fd3303d38a5bdf7af0e8773f36cd70e8c802": [
        "2026-01-02T03:04:05Z",
        "2026-01-02T05:04:05+02:00",
        "2026-01-02T01:04:05.000-02:00",
        "2026-01-01T22:04:05-05:00",
        "2026-01-02t03:04:05z",
    ],
    "83d7710c15fa8d030cd4c59d0fb712e1a8ab559624b42dea1c721acdf7ed9d72": [
        "2026-01-02T03:04:05.5Z",
        "2026-01-02T03:04:05.500Z",
        "2026-01-02T05:04:05.500+02:00",
    ],
}

EVENT_KEY_GOLDEN = [
    (("11111111-2222-3333-4444-555555555555", 1, "stream-alpha", 0),
     "08d4d88a926116bdd3da0d18d66603e4e596978cb98118f1401adb474a9170ac"),
    (("fx-tool-01", 12, "s/cred-77", 255),
     "91ca2a97f87f4128c082cd134f4d4b8f9c7cc337491193df50095728177ca3a2"),
    ((uuid.UUID("00000000-0000-0000-0000-000000000001"), 4294967296,
      "κρόνος-α", 9223372036854775807),
     "98cd155f2392e5a452101cf458370b3971626e374650980e17535e1f130f7dcb"),
    (("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", 2, "plain", 9007199254740992),
     "aa2573320eac80fe77e08a7a50c74e7bbf68c7277f2521ccba4ac5c9497930d7"),
]

TURN_END_KEY_GOLDEN = [
    (("99999999-9999-9999-9999-999999999999", "11111111-1111-1111-1111-111111111111"),
     "00e3e9eafa3a0873d76a80551dde0cfa30e6f215a7557f84d0f5b006d4ae9b2b"),
    (("sess-alpha", "turn-42"),
     "3a815e5dd3f39e6e9df064be7af40fd37e26ef77bdaabafaffa2458f1a190a8c"),
    ((uuid.UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"), "turn/mixed-α"),
     "571926f8c803736cd5931809dd26de8573ce88ca0a58502e0a09c1160cdf725e"),
]

CLOSER_KEY_GOLDEN = [
    (("ab" * 32, "cd" * 32, b'{"r":"ok"}'),
     "11103249f28da5c1dafb83734fbfbd82c1647e612306ae2a4870c642b041410d"),
    (("0f0e0d0c" * 8, "deadbeef" * 8, b'{"n":1}'),
     "c2a03696b4942f787a0a3f403a1c8f33062294d50ad5cae165e405f90d90fd1a"),
    (("0f33c05e33b2836b675538d11505ff4885790c92a90227ae0b134f5522b59f23",
      "44b52d07a1752ee7923baf080225533648f27d22e351e643a3f11bd2c2e21154",
      b'{"kind":"repair","v":2}'),
     "9a9e324e45015c3689de5471d4e36b04fe17da879a395b9473dd91ece8810795"),
]

PROVISIONAL_DIGEST_GOLDEN = [
    ((["11111111-2222-3333-4444-555555555555",
       "00000000-0000-0000-0000-000000000001"],),
     "d05e05d88005432176cf77c0938bfaa65429aa68bda533b65684dfd062d01dd9"),
    ((["zz-top", "11111111-2222-3333-4444-555555555555"],),
     "aa8c4154d77746f557d854740bd27bb6a6c354c8c89755c2d8e35123d346679b"),
    ((["00000000-0000-0000-0000-00000000000a", "aaaa",
       "00000000-0000-0000-0000-00000000000b"],),
     "7ea81eb5baaae05d84cc0ffca6e8acb17bfce033b6d321a90378bde4e389d14d"),
    ((["123e4567-e89b-12d3-a456-426614174000"],),
     "2166ecc51f1100c2ea5d5f7812326d3c240cc2a9f450a0c983ea048ec40944ba"),
]

NONSTREAM_KEY_GOLDEN = [
    # G3 reconciliation: ordinal encodes as canonical_integer_bytes and
    # command_id as raw UTF-8 (matching SQL v_nonstream_event_key and its G2
    # golden vector); vectors recomputed against the corrected reference.
    (("99999999-9999-9999-9999-999999999999", "user/message",
      "22222222-3333-4444-5555-666666666666", 0,
      "2e6709af8dbfe7cd5abb2f716924848e527b4486c30c4509b0e4aa8171987335"),
     "6b5c97a0584aae65b07d28593f60718211b10b35d083af6019562c54e543c609"),
    (("sess-alpha", "session/heartbeat", "cmd-7", 5,
      "bddd3a6e5dab59fa05fa8fb0d789a3c2ad3c9982dcc4a368f3d5719f421ffda8"),
     "4a03fa45da15cee635f3f40048f5dcd253edacca64bd82e99e73091c494acbb2"),
    ((uuid.UUID("abcdefab-cdef-abcd-efab-cdefabcdefab"), "agent/inject",
      "11111111-1111-1111-1111-111111111111", 9223372036854775807,
      "43bb00d0ce7790a53b91256b370c887b24791a5539a6fbfb70c5870e8c91ae5d"),
     "5dd8fe17659f441b3f27c070a942fe3992504456d438c83932a00992a6b20fee"),
]

CANONICAL_INTEGER_BYTES_GOLDEN = [
    (0, b"0"),
    (1, b"1"),
    (10, b"10"),
    (2 ** 63 - 1, b"9223372036854775807"),
]

SHA256_OF_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_canonical_golden() -> None:
    for label, payload, want_text, want_hash in CANONICAL_GOLDEN:
        text, got_hash = canonicalize(payload)
        check(f"golden[{label}] canonical text", text == want_text,
              f"got {text!r} want {want_text!r}")
        check(f"golden[{label}] payload hash", got_hash == want_hash,
              f"got {got_hash}")
    # bytes input takes the same path as text input.
    text, got_hash = canonicalize(b'{"b":1,"a":2}')
    check("bytes input equals text input",
          (text, got_hash) == ('{"a":2,"b":1}',
                               "d3626ac30a87e6f7a6428233b3c68299976865fa5508e4267c5415c76af7a772"))
    # Hash binding: payload_hash is always SHA-256 of the canonical UTF-8 bytes.
    text, got_hash = canonicalize({"$$int": "label"})
    check("hash binding rule",
          got_hash == hashlib.sha256(text.encode("utf-8")).hexdigest())
    # The three step-0 vectors produce pairwise-different hash inputs.
    by_label = {label: payload for label, payload, _, _ in CANONICAL_GOLDEN}
    hashes = {canonicalize(by_label[label])[1]
              for label in ("esc2", "esc3", "tagged")}
    check("escape vectors give distinct hash inputs", len(hashes) == 3, hashes)


def test_rejections() -> None:
    cases = [
        # Duplicate keys (top level and nested).
        ("duplicate key", '{"a":1,"a":2}', "DUPLICATE_KEY"),
        ("duplicate nested key", '{"o":{"x":1,"x":2}}', "DUPLICATE_KEY"),
        # NFC: e + U+0301 combining acute is rejected (value and key).
        ("non-NFC value", '{"k":"e\\u0301"}', "NOT_NFC"),
        ("non-NFC key", '{"e\\u0301":1}', "NOT_NFC"),
        # Bare-number boundaries.
        ("bare 2^53 rejected", '{"n":9007199254740992}', "UNSAFE_NUMBER"),
        ("bare -2^53 rejected", '{"n":-9007199254740992}', "UNSAFE_NUMBER"),
        # Integer-valued doubles beyond the safe range are bare out-of-range
        # integers: same tagged-$int partition as integer literals.
        ("integral float 2^53 rejected", '{"n":9007199254740992.0}', "UNSAFE_NUMBER"),
        ("integral float 1e300 rejected", '{"n":1e300}', "UNSAFE_NUMBER"),
        # Non-integer numbers are inside the I-JSON domain (golden vectors
        # above); only NaN/Infinity literals are forbidden.
        ("NaN rejected", '{"n":NaN}', "NON_IJSON"),
        ("Infinity rejected", '{"n":Infinity}', "NON_IJSON"),
        ("overflowing literal rejected", '{"n":1e400}', "NON_IJSON"),
        # Unescaped "$"-prefixed keys on the escaped representation.
        ("unescaped $flag", '{"$flag":1}', "UNESCAPED_DOLLAR_KEY"),
        ("reserved shape, bad lexicon", '{"$int":"label"}', "TAGGED_INT_INVALID"),
        ("multi-key $int is unescaped", '{"$int":"1","z":0}', "UNESCAPED_DOLLAR_KEY"),
        ("deep unescaped key", '{"a":[{"$x":1}]}', "UNESCAPED_DOLLAR_KEY"),
        # Tagged lexical violations.
        ("tagged leading zeros", '{"$int":"007"}', "TAGGED_INT_INVALID"),
        ("tagged plus sign", '{"$int":"+5"}', "TAGGED_INT_INVALID"),
        ("tagged -0", '{"$int":"-0"}', "TAGGED_INT_INVALID"),
        ("tagged fraction", '{"$int":"1.0"}', "TAGGED_INT_INVALID"),
        ("tagged exponent", '{"$int":"1e3"}', "TAGGED_INT_INVALID"),
        ("tagged empty", '{"$int":""}', "TAGGED_INT_INVALID"),
        ("tagged leading space", '{"$int":" 5"}', "TAGGED_INT_INVALID"),
        ("tagged non-string", '{"$int":42}', "TAGGED_INT_INVALID"),
        # Tagged range violations.
        ("tagged 2^63 rejected", '{"$int":"9223372036854775808"}', "TAGGED_INT_INVALID"),
        ("tagged -2^63 rejected", '{"$int":"-9223372036854775808"}', "TAGGED_INT_INVALID"),
        # In-range integers must be JSON numbers, never tagged.
        ("tagged 0 in-range", '{"$int":"0"}', "TAGGED_INT_INVALID"),
        ("tagged 42 in-range", '{"$int":"42"}', "TAGGED_INT_INVALID"),
        ("tagged 2^53-1 in-range", '{"$int":"9007199254740991"}', "TAGGED_INT_INVALID"),
        # Time typing on registered fields only.
        ("bad time value", '{"created_at":"not-a-time"}', "TIME_INVALID"),
        ("bad time month", '{"created_at":"2026-13-01T00:00:00Z"}', "TIME_INVALID"),
        ("time missing offset", '{"created_at":"2026-01-02T03:04:05"}', "TIME_INVALID"),
        ("time space separator", '{"created_at":"2026-01-02 03:04:05Z"}', "TIME_INVALID"),
        # Parse-level rejections.
        ("not JSON", 'not json', "NON_IJSON"),
        ("empty text", '', "NON_IJSON"),
        ("lone surrogate", '{"k":"\\ud800"}', "NON_IJSON"),
    ]
    for label, payload, code in cases:
        rejects(label, payload, code)


def test_number_equivalence() -> None:
    # Wire-equivalent spellings of the same double MUST canonicalize to the
    # same bytes (JCS renders the double, never the lexical form).
    equivalences = [
        ('{"n":1.5}', ['{"n":1.50}', '{"n":15e-1}', '{"n":0.15e1}',
                       '{"n":1500e-3}']),
        ('{"n":1000}', ['{"n":1e3}', '{"n":1E3}', '{"n":10.0e2}', '{"n":1000.0}']),
        ('{"n":0.1}', ['{"n":1e-1}', '{"n":0.10}', '{"n":100e-3}']),
    ]
    for canonical_form, variants in equivalences:
        want = canonicalize(canonical_form)
        for form in variants:
            check(f"number equivalence {form!r}",
                  canonicalize(form) == want,
                  (canonicalize(form), want))
    # Object inputs take the same path as text inputs for fractional values.
    check("float object input equals text input",
          canonicalize({"n": 1.5}) == canonicalize('{"n":1.5}'))
    check("integer-valued float object renders bare integer",
          canonicalize({"n": 1000.0})[0] == '{"n":1000}')


def test_escape_step0() -> None:
    check("escape $int->$$int",
          escape_dollar_keys({"$int": "label"}) == {"$$int": "label"})
    check("escape $$int->$$$int",
          escape_dollar_keys({"$$int": "label"}) == {"$$$int": "label"})
    # A valid tagged integer stays unescaped (boundary value above 2^53-1).
    check("tagged out-of-safe integer not escaped",
          escape_dollar_keys({"$int": "9007199254740993"})
          == {"$int": "9007199254740993"})
    check("tagged max 2^63-1 not escaped",
          escape_dollar_keys({"$int": "9223372036854775807"})
          == {"$int": "9223372036854775807"})
    # Beyond the tagged range the object is ordinary data and gets escaped.
    check("out-of-tagged-range value escaped",
          escape_dollar_keys({"$int": "9223372036854775808"})
          == {"$$int": "9223372036854775808"})
    # Decision order: only a valid decimal string keeps the tag.
    check("non-decimal value escaped",
          escape_dollar_keys({"$int": 42}) == {"$$int": 42})
    check("nested escape", escape_dollar_keys({"a": [{"$flag": True}]})
          == {"a": [{"$$flag": True}]})
    check("tagged deep untouched",
          escape_dollar_keys({"a": {"$int": "9007199254740993"}})
          == {"a": {"$int": "9007199254740993"}})
    # Input is not mutated.
    src = {"$int": "label"}
    escape_dollar_keys(src)
    check("escape does not mutate input", src == {"$int": "label"})
    # Full producer composition: escape -> serialize -> canonicalize.
    escaped_text = json.dumps(escape_dollar_keys({"$int": "label"}),
                              ensure_ascii=False)
    text, got_hash = canonicalize(escaped_text)
    check("composed pipeline hits esc2 golden",
          (text, got_hash) == ('{"$$int":"label"}',
                               "95e316af5aa251566ddc4b6edec8e2828fa72db52c34ac93d5eade25fa4a2151"))
    # Decode is display-only and inverts the escape.
    check("unescape inverts escape",
          unescape_dollar_keys(escape_dollar_keys({"$int": "label", "a": 1}))
          == {"$int": "label", "a": 1})
    check("unescape leaves tagged alone",
          unescape_dollar_keys({"$int": "9007199254740993"})
          == {"$int": "9007199254740993"})


def test_time_normalization() -> None:
    check("created_at is registered", "created_at" in TIME_FIELD_NAMES)
    for want_hash, forms in TIME_EQUIVALENCE.items():
        for form in forms:
            _, got_hash = canonicalize('{"created_at":"%s"}' % form)
            check(f"time equivalence {form!r}", got_hash == want_hash, got_hash)
    # Direct pure-function expectations.
    for text, want in [
        ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
        ("2026-01-01T23:00:00-05:00", "2026-01-02T04:00:00Z"),
        ("2026-01-02T03:04:05.000Z", "2026-01-02T03:04:05Z"),
        ("2026-01-02T03:04:05.123000Z", "2026-01-02T03:04:05.123Z"),
        ("2026-01-02t03:04:05z", "2026-01-02T03:04:05Z"),
    ]:
        check(f"normalize_rfc3339 {text!r}", normalize_rfc3339(text) == want)
    for bad in [
        "not-a-time", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z",
        "2026-01-02T24:00:00Z", "2026-01-02T03:04:60Z",
        "2026-01-02T03:04:05", "2026-01-02 03:04:05Z", "",
    ]:
        try:
            normalize_rfc3339(bad)
            check(f"normalize_rfc3339 rejects {bad!r}", False, "accepted")
        except CanonicalizationError as exc:
            check(f"normalize_rfc3339 rejects {bad!r}", exc.code == "TIME_INVALID",
                  exc.code)


def test_key_golden_vectors() -> None:
    for (effect_id, attempt_no, stream_id, chunk_index), want in EVENT_KEY_GOLDEN:
        got = event_key_v1(effect_id, attempt_no, stream_id, chunk_index)
        check(f"event_key_v1 golden {effect_id}#{attempt_no}", got == want, got)
    for (session_id, turn_id), want in TURN_END_KEY_GOLDEN:
        got = turn_end_key_v1(session_id, turn_id)
        check(f"turn_end_key_v1 golden {session_id}", got == want, got)
    for (tek, sek, resolution), want in CLOSER_KEY_GOLDEN:
        got = closer_event_key_v1(tek, sek, resolution)
        check("closer_event_key_v1 golden", got == want, got)
    for (effect_ids,), want in PROVISIONAL_DIGEST_GOLDEN:
        got = provisional_unknown_effect_set_digest_v1(effect_ids)
        check(f"provisional digest golden ({len(effect_ids)} ids)", got == want, got)
    for (session_id, event_type, command_id, ordinal, payload_hash), want \
            in NONSTREAM_KEY_GOLDEN:
        got = nonstream_event_key(session_id, event_type, command_id,
                                  ordinal, payload_hash)
        check(f"nonstream_event_key golden {event_type}", got == want, got)


def test_identity_representation() -> None:
    # Any text form of a UUID yields the same 16 RFC 9562 bytes and the same keys.
    u = "11111111-2222-3333-4444-555555555555"
    want_bytes = bytes.fromhex("11111111222233334444555555555555")
    check("identity_bytes UUID object", identity_bytes(uuid.UUID(u)) == want_bytes)
    check("identity_bytes hyphenated text", identity_bytes(u) == want_bytes)
    check("identity_bytes bare hex text",
          identity_bytes("11111111222233334444555555555555") == want_bytes)
    check("identity_bytes plain text", identity_bytes("plain-text") == b"plain-text")
    for bad_call, label in [
        (lambda: identity_bytes(None), "identity NULL"),
        (lambda: identity_bytes("\ud800"), "identity non-UTF-8"),
    ]:
        try:
            bad_call()
            check(f"{label} raises ValueError", False, "accepted")
        except ValueError:
            check(f"{label} raises ValueError", True)
    # UUID text forms agree on derived keys.
    check("event_key UUID text forms agree",
          event_key_v1(u, 1, "s", 0)
          == event_key_v1(uuid.UUID(u), 1, "s", 0)
          == event_key_v1("11111111222233334444555555555555", 1, "s", 0))
    check("turn_end_key UUID text forms agree",
          turn_end_key_v1(u, "t") == turn_end_key_v1(uuid.UUID(u), "t"))
    # stream_id stays RAW UTF-8 even when UUID-shaped (frozen identity clause).
    check("stream_id never UUID-parsed",
          _text_bytes("00000000-0000-0000-0000-000000000000")
          == b"00000000-0000-0000-0000-000000000000")
    check("turn_end_key differs on distinct turns",
          turn_end_key_v1("s", "t1") != turn_end_key_v1("s", "t2"))


def test_integer_encoding() -> None:
    for n, want in CANONICAL_INTEGER_BYTES_GOLDEN:
        check(f"canonical_integer_bytes({n})",
              canonical_integer_bytes(n) == want)
    # Representation independence: a value decoded from either legal wire form
    # yields byte-identical downstream keys (same integer -> same bytes).
    from_tagged = int(json.loads('{"$int":"9007199254740993"}')["$int"])
    from_bare = json.loads('{"c":255}')["c"]
    check("cib representation independence",
          canonical_integer_bytes(from_tagged) == b"9007199254740993")
    check("event_key representation independence",
          event_key_v1("e", 1, "s", from_tagged)
          == event_key_v1("e", 1, "s", 9007199254740993)
          and event_key_v1("e", 1, "s", from_bare)
          == event_key_v1("e", 1, "s", 255))
    # Provisional digest: set semantics and order irrelevance.
    d1 = ["11111111-2222-3333-4444-555555555555",
          "00000000-0000-0000-0000-000000000001"]
    check("provisional digest order-irrelevant",
          provisional_unknown_effect_set_digest_v1(d1)
          == provisional_unknown_effect_set_digest_v1(list(reversed(d1))))
    check("provisional digest dedupes",
          provisional_unknown_effect_set_digest_v1(["x", "x"])
          == provisional_unknown_effect_set_digest_v1(["x"]))
    check("provisional digest empty set",
          provisional_unknown_effect_set_digest_v1([]) == SHA256_OF_EMPTY)
    # Fixed-width encoders.
    check("u64be(0)", _u64be(0) == b"\x00" * 8)
    check("u64be(1)", _u64be(1) == b"\x00" * 7 + b"\x01")
    check("i64be(-1)", _i64be(-1) == b"\xff" * 8)
    check("i64be(2^63-1)", _i64be(2 ** 63 - 1) == b"\x7f" + b"\xff" * 7)
    for bad_call, label in [
        (lambda: _u64be(-1), "u64be negative"),
        (lambda: _u64be(2 ** 64), "u64be overflow"),
        (lambda: _i64be(2 ** 63), "i64be overflow"),
        (lambda: event_key_v1("e", -1, "s", 0), "event_key negative attempt_no"),
    ]:
        try:
            bad_call()
            check(f"{label} raises ValueError", False, "accepted")
        except ValueError:
            check(f"{label} raises ValueError", True)


def main() -> int:
    test_canonical_golden()
    test_rejections()
    test_number_equivalence()
    test_escape_step0()
    test_time_normalization()
    test_key_golden_vectors()
    test_identity_representation()
    test_integer_encoding()
    print("[G1] all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
