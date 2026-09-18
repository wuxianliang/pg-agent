"""One-shot live probe: confirm OpenRouter Jev access end to end.

NOT a gate — this is a manual, network-calling utility (gates stay offline
by repo rule). Run with the key in the environment:

    uv run python v12/probe_jev.py            # reads OPENROUTER_API_KEY

Sends ONE minimal request (a Noul + a Choice) to the decisions endpoint
via JevClient — the same code path production workers use — and prints
provider, resolved model, answers, usage and cost. A 200 with typed
answers means everything is wired correctly (~$0.00002 per run).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v12.jev_client import JevClient, JevError

STATE = {"ticket": "My flight was cancelled. Can I get a refund?",
         "policy": "Cancelled flights are eligible for a full refund."}
QUESTIONS = {
    "refund_requested": {"type": "noul",
                         "instructions": "Does `ticket` request a refund?"},
    "request_type": {"type": "choice",
                     "instructions": "What is the main request in `ticket`?",
                     "criteria": {
                         "refund": "The customer wants money returned.",
                         "rebooking": "The customer wants a replacement flight.",
                         "information": "The customer asks for information only."}},
}


def main() -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("set OPENROUTER_API_KEY first (this script talks to the network)")
        return 2
    client = JevClient()  # auto-selects openrouter with the key present
    try:
        resp = client.ask(STATE, QUESTIONS)
    except JevError as exc:
        print("FAILED:", exc)
        return 1
    print("provider :", client.provider)
    print("model    :", resp.get("model"))
    print("answers  :", json.dumps(resp.get("answers"), indent=1,
                                   ensure_ascii=False))
    print("usage    :", resp.get("usage"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
