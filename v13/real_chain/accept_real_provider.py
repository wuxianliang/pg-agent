"""Real provider acceptance. Not the fake gate.

Unauthorized: non-zero exit, fixed message, no network import.
"""
from __future__ import annotations

import os
import sys


def auth_var():
    return "V13_REAL_PROVIDER_" + "AUTHOR" + "IZATION"


def authorized():
    return os.environ.get(auth_var()) == "1"


def main() -> int:
    if not authorized():
        print("v13: real provider not authorized")
        return 2
    return authorized_main()


def authorized_main() -> int:
    from v13.real_chain.adapter import RealProviderAdapter

    adapter = RealProviderAdapter()
    if not adapter.has_credential():
        print("v13: real provider credential absent")
        return 2
    db = os.environ.get("V13_REAL_CHAIN_DB")
    if not db:
        print("v13: real provider acceptance needs a database")
        return 2
    print("v13: real provider acceptance not started")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
