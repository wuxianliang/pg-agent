"""Serial owner domain for one session store.

The v2 store is single-thread owned.  All control mutations, cursor reads and
driver finishes go through this context manager; it is not a per-run lock and
must never wrap a provider call.  Wait loops release it around sleep/backoff.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager


class SessionSerialDomain:
    def __init__(self, store):
        self.store = store
        self._lock = threading.RLock()

    @contextmanager
    def enter(self):
        with self._lock:
            self.store._check()
            yield

    def assert_owner(self):
        self.store._check()
