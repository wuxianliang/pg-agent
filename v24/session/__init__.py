"""Headless v24 session control plane (S0).

This package is intentionally independent of Chainlit and of ``v24.ui``.  The
UI adapter in ``v24/ui`` implements the ``SessionBackend`` protocol and owns
all runtime imports.
"""
from .driver import SessionSerialDomain
from .service import SessionService
from .store import SessionStore, StoreError
from .models import SessionBackend, StartResult

__all__ = [
    "SessionBackend",
    "SessionSerialDomain",
    "SessionService",
    "SessionStore",
    "StartResult",
    "StoreError",
]
