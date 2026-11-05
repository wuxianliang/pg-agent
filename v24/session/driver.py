"""Serial owner domain for one session store.

The v2 store is single-thread owned.  All control mutations, cursor reads and
driver finishes go through this context manager; it is not a per-run lock and
must never wrap a provider call.  Wait loops release it around sleep/backoff.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager


class SessionSerialDomain:
    """One short-read lock plus a waiter condition.

    The condition is notified only after a state-changing operation has
    committed; waiters re-read the backend projection after every wake, so a
    lost notification degrades to the bounded sleep rather than a lost wake.
    """

    def __init__(self, store):
        self.store = store
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)

    @contextmanager
    def enter(self):
        with self._lock:
            self.store._check()
            yield

    def notify(self):
        with self._changed:
            self._changed.notify_all()

    def pause(self, seconds):
        with self._changed:
            self._changed.wait(seconds)

    def assert_owner(self):
        self.store._check()
