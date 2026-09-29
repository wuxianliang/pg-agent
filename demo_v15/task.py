"""Task text, ceilings, inputs, and the recall sizer. No database."""
from __future__ import annotations

import json
import re
import secrets

from v15.protocol.render_prompt import render_system

NOTE_MAX = 1500
NOTE_CHAIN_V1 = (
    "Copy this note to the child unchanged as the note input. The quotes around "
    "a value are syntax and are not part of the value. You are the hop given by "
    "role. hops counts the hops left, including you. seal is the leaf seal. "
    "root_id is the root invoke id. Pass seal, root_id, and this note down "
    "unchanged. When hops is greater than 1, delegate to one child bound as down "
    "and return that child result unchanged. The child input object must have "
    "note (this same text), hops (your hops minus one), role (leaf when the "
    "child hops is 1, otherwise mid), seal (unchanged), and root_id (unchanged). "
    "When hops is 1, do not delegate. Return a JSON object with keys seal and "
    "hops, using your seal and hops 1. A literal JSON return while hops is "
    "greater than 1 is wrong. No markdown. No prose."
)
NOTE_RECALL_V1 = (
    "Copy this note to the child unchanged as the note input. The quotes around "
    "a value are syntax and are not part of the value. You are the hop given by "
    "role. hops counts the hops left, including you. seal is the leaf seal. "
    "root_id is the root invoke id. facts exists only on the root. Never copy "
    "facts into a child. Pass seal, root_id, and this note down unchanged. When "
    "role is root and hops is greater than 1, the first reply is only a print of "
    "the facts text and the next reply delegates. When role is mid and hops is "
    "greater than 1, delegate on the first reply and do not read ancestor "
    "history. Delegate to one child bound as down and return that child result "
    "unchanged. The child object has only note, hops set to your hops minus one, "
    "role set to leaf when the child hops is 1 and otherwise mid, seal, and "
    "root_id. When hops is 1, do not delegate. Read the finished history of "
    "root_id with jaz.prior_history and return a JSON object with keys seal, "
    "hops, and token. Use your seal, hops 1, and the 16 hex digits after token= "
    "in that history text. Do not invent the token. No markdown. No prose."
)
PRINT_SQL = "SELECT jaz.print((jaz.var('facts') #>> '{}'));"
FACTS_PREFIX = "token=" + ("0" * 16) + " "
SYSTEM_CHARS = 1855
WARN_FLOOR = 4500
WARN_LO = 4700
WARN_PRINT_HI = 4300
WARN_HI = 8000
INVOKE_LIMIT = 9000
BIND_NAME = "down"
CALLS_LIMIT = 32
COST_LIMIT_TEXT = "2.00"
SEAL_RE = re.compile(r"^[0-9a-f]{6}$")
_BANNED = frozenset(";\"'\\")
_SHARED_PHRASES = ("down", "root_id", "No markdown", "No prose")
_CHAIN_PHRASE = "keys seal and hops"
_RECALL_PHRASES = ("jaz.prior_history", "facts", "token=")
_PLACEHOLDER_SEAL = "abcdef"
_PLACEHOLDER_ROOT = "00000000-0000-0000-0000-000000000000"


class NoteInvalid(ValueError):
    pass


class SealInvalid(ValueError):
    pass


class HopsInvalid(ValueError):
    pass


class ScenarioInvalid(ValueError):
    pass


class FactsUnsized(ValueError):
    def __init__(self, fixed: int, system_chars: int, note_len: int) -> None:
        super().__init__(fixed)
        self.fixed = fixed
        self.system_chars = system_chars
        self.note_len = note_len


class SystemDrift(ValueError):
    def __init__(self, measured: int) -> None:
        super().__init__(measured)
        self.measured = measured


def ceilings() -> dict:
    return {
        "max_iterations": 4,
        "max_depth": 8,
        "max_io_attempts": 2,
        "max_statement_ms": 30000,
    }


def note_for(scenario: str) -> str:
    if scenario == "chain":
        return NOTE_CHAIN_V1
    if scenario == "recall":
        return NOTE_RECALL_V1
    raise ScenarioInvalid(scenario)


def note_revision(scenario: str) -> str:
    if scenario == "chain":
        return "NOTE_CHAIN_V1"
    if scenario == "recall":
        return "NOTE_RECALL_V1"
    raise ScenarioInvalid(scenario)


def default_hops(scenario: str) -> int:
    if scenario == "chain":
        return 8
    if scenario == "recall":
        return 5
    raise ScenarioInvalid(scenario)


def role_for(hops_left: int, root_hops: int) -> str:
    if hops_left == root_hops:
        return "root"
    if hops_left == 1:
        return "leaf"
    return "mid"


def role_sequence(hops: int) -> list[str]:
    return [role_for(hops - depth + 1, hops) for depth in range(1, hops + 1)]


def validate_scenario(scenario: str) -> str:
    if scenario not in {"chain", "recall"}:
        raise ScenarioInvalid(scenario)
    return scenario


def validate_hops(value: object, scenario: str = "chain") -> int:
    validate_scenario(scenario)
    lo, hi = (3, 8) if scenario == "chain" else (5, 8)
    if type(value) is not int or value < lo or value > hi:
        raise HopsInvalid(value)
    return value


def _printable(note: str) -> bool:
    return all(32 <= ord(ch) <= 126 for ch in note)


def validate_note(note: str, scenario: str | None = None) -> None:
    if not isinstance(note, str) or note == "":
        raise NoteInvalid("empty")
    if len(note) > NOTE_MAX or not _printable(note) or any(ch in note for ch in _BANNED):
        raise NoteInvalid("chars")
    if "jaz.bind_invoke" in note or 'jaz."return"' in note:
        raise NoteInvalid("forbidden")
    if scenario is None:
        return
    validate_scenario(scenario)
    missing = [phrase for phrase in _SHARED_PHRASES if phrase not in note]
    if scenario == "chain" and _CHAIN_PHRASE not in note:
        missing.append(_CHAIN_PHRASE)
    if scenario == "recall":
        missing.extend(phrase for phrase in _RECALL_PHRASES if phrase not in note)
    if missing:
        raise NoteInvalid("phrase")


def check_canonical_notes() -> None:
    validate_note(NOTE_CHAIN_V1, "chain")
    validate_note(NOTE_RECALL_V1, "recall")


def validate_seal(seal: str) -> None:
    if not isinstance(seal, str) or SEAL_RE.fullmatch(seal) is None:
        raise SealInvalid(seal)


def system_chars() -> int:
    measured = len(render_system(recursion_available=True, bindings=[]))
    if measured != SYSTEM_CHARS:
        raise SystemDrift(measured)
    return measured


def input_binding(name: str, value: object) -> dict:
    return {
        "name": name,
        "kind": "input",
        "value": value,
        "show_in_prompt": True,
        "provenance": "explicit",
    }


def jsonb_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def compose_inputs(pairs: list[tuple[str, str]]) -> str:
    ordered = sorted(pairs, key=lambda item: item[0].encode("utf-8"))
    lines = ["inputs:"]
    for name, text in ordered:
        lines.append(f"{name}: {text}")
    return "\n".join(lines)


def estimate_fixed(note: str, hops: int = 5, seal: str = _PLACEHOLDER_SEAL, root_id: str = _PLACEHOLDER_ROOT) -> int:
    seed = compose_inputs(
        [
            ("facts", jsonb_text("")),
            ("hops", jsonb_text(hops)),
            ("note", jsonb_text(note)),
            ("role", jsonb_text("root")),
            ("root_id", jsonb_text(root_id)),
            ("seal", jsonb_text(seal)),
        ]
    )
    return system_chars() + len(seed)


def child_seed_len(note: str, hops: int = 1, role: str = "leaf", seal: str = _PLACEHOLDER_SEAL, root_id: str = _PLACEHOLDER_ROOT) -> int:
    return len(
        compose_inputs(
            [
                ("hops", jsonb_text(hops)),
                ("note", jsonb_text(note)),
                ("role", jsonb_text(role)),
                ("root_id", jsonb_text(root_id)),
                ("seal", jsonb_text(seal)),
            ]
        )
    )


def nonroot_headroom(note: str) -> bool:
    return system_chars() + child_seed_len(note) + 200 < WARN_FLOOR


def solve_n(fixed: int, print_len: int | None = None) -> int | None:
    if type(fixed) is not int or fixed >= 3900:
        return None
    width = len(PRINT_SQL) if print_len is None else print_len
    prefix = len(FACTS_PREFIX)
    lower_span = WARN_LO - fixed - width
    b_lo = 0 if lower_span <= 0 else (lower_span + 1) // 2
    b_hi = min(WARN_PRINT_HI - fixed, (WARN_HI - fixed - width) // 2)
    b_lo = max(b_lo, prefix)
    if b_lo > b_hi:
        return None
    return b_lo - prefix


def facts_body(token: str, n: int) -> str:
    return f"token={token} " + ("p" * n)


def build_facts(note: str, hops: int = 5) -> tuple[str, str, int]:
    fixed = estimate_fixed(note, hops)
    found = solve_n(fixed)
    if found is None:
        raise FactsUnsized(fixed, system_chars(), len(note))
    token = secrets.token_hex(8)
    return token, facts_body(token, found), found


def child_payload(note: str, hops: int, role: str, seal: str, root_id: str) -> dict:
    return {
        "note": note,
        "hops": hops,
        "role": role,
        "seal": seal,
        "root_id": root_id,
    }


def root_inputs(
    seal: str,
    note: str,
    hops: int,
    root_id: str,
    facts: str | None = None,
) -> list[dict]:
    validate_note(note)
    validate_seal(seal)
    rows = [
        input_binding("hops", hops),
        input_binding("role", "root"),
        input_binding("seal", seal),
        input_binding("note", note),
        input_binding("root_id", root_id),
    ]
    if facts is not None:
        rows.append(input_binding("facts", facts))
    return rows
