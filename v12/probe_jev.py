"""One-shot probe: learn which OpenRouter request mode jev-1.13 speaks.

NOT a gate — this is a manual, network-calling utility (gates stay offline
by repo rule). Run it once with your key:

    OPENROUTER_API_KEY=sk-or-... uv run python v12/probe_jev.py

It sends one minimal Noul question through each candidate mode
(wrapped / native / system_user), prints what comes back, and tells you
which mode to pin via V12_JEV_OPENROUTER_MODE=... for JevClient.
Cost: three tiny requests (~300 tokens each at $0.042/M ≈ $0.00004 total).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v12.jev_client import OpenRouterBackend, JevError

STATE = {"note": "The meeting was moved to Thursday."}
QUESTIONS = {
    "moved": {"type": "noul",
              "instructions": "Was the meeting rescheduled according to `note`?"},
}


def try_mode(mode: str) -> bool:
    print(f"\n=== mode: {mode} ===")
    be = OpenRouterBackend(mode=mode)
    try:
        resp = be.ask(STATE, QUESTIONS)
    except JevError as exc:
        print("FAILED:", str(exc)[:500])
        return False
    print("OK — answers:", json.dumps(resp.get("answers"), ensure_ascii=False))
    print("    usage:", resp.get("usage"))
    return True


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("set OPENROUTER_API_KEY first (this script talks to the network)")
        return 2
    winners = [m for m in ("wrapped", "native", "system_user") if try_mode(m)]
    if not winners:
        print("\nNo mode worked. Raw formats may have changed — inspect the "
              "error payloads above and extend OpenRouterBackend._body.")
        return 1
    print(f"\nPin it: export V12_JEV_OPENROUTER_MODE={winners[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
