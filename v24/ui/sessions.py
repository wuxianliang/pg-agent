"""Compatibility facade for the headless v2 session store.

The implementation lives in :mod:`v24.session.store`; this module keeps the
existing ``v24.ui.sessions`` import surface stable for the Chainlit frontend
and the v24 gates.
"""
from __future__ import annotations

from v24.session.store import (  # noqa: F401
    MAX_BINDINGS,
    MAX_RECEIPTS,
    TERMINAL,
    VERSION,
    SessionStore,
    StoreError,
    atomic_bytes,
    atomic_json,
    now,
    valid_uuid,
)

__all__ = [
    "MAX_BINDINGS",
    "MAX_RECEIPTS",
    "TERMINAL",
    "VERSION",
    "SessionStore",
    "StoreError",
    "atomic_bytes",
    "atomic_json",
    "now",
    "valid_uuid",
]
