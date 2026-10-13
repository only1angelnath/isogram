"""
cache.py — a tiny in-process snapshot cache for the few expensive read endpoints.

Why it exists: GET /projects (and /stats) rebuild their answer from several Supabase tables on every
request. That took ~9 s on Render's free instance, long enough for the dashboard's /projects page to
time out. The underlying data only changes when the hourly ingestion run or the 4-hourly scoring run
finishes, so serving a snapshot that is at most a minute old loses nothing a reader could see.

Behaviour per key:
  * fresh  (age < ttl):                   serve the snapshot.
  * stale  (ttl <= age < max_stale):      serve the snapshot now and rebuild it in the background,
                                          so readers never wait on a refresh.
  * cold   (no snapshot, or too old):     rebuild in the foreground (one caller does the work, the
                                          others wait for it instead of piling on Supabase).
  * rebuild fails and an older snapshot exists: serve that and log, rather than turn a blip into a 500.
"""

import logging
import threading
import time
from typing import Callable, Dict, Tuple

log = logging.getLogger("isogram.cache")


class SnapshotCache:
    def __init__(self, ttl: float = 60.0, max_stale: float = 900.0, max_entries: int = 256,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl
        self.max_stale = max_stale
        self.max_entries = max_entries  # keys can embed caller-chosen values (days, token); never let them grow without bound
        self._clock = clock
        self._entries: Dict[str, Tuple[object, float]] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def _store(self, key: str, value: object) -> None:
        with self._guard:
            self._entries[key] = (value, self._clock())
            while len(self._entries) > self.max_entries:
                oldest = min(self._entries, key=lambda k: self._entries[k][1])
                del self._entries[oldest]
                lock = self._locks.get(oldest)
                if lock is not None and not lock.locked():
                    del self._locks[oldest]

    def clear(self) -> None:
        with self._guard:
            self._entries.clear()

    def get(self, key: str, compute: Callable[[], object]) -> object:
        entry = self._entries.get(key)
        if entry is not None:
            value, stamp = entry
            age = self._clock() - stamp
            if age < self.ttl:
                return value
            if age < self.max_stale:
                self._refresh_in_background(key, compute)
                return value
        return self._compute_blocking(key, compute)

    def _compute_blocking(self, key: str, compute: Callable[[], object]) -> object:
        with self._lock_for(key):
            entry = self._entries.get(key)
            if entry is not None and self._clock() - entry[1] < self.ttl:
                return entry[0]  # another caller rebuilt it while we waited for the lock
            try:
                value = compute()
            except Exception:
                if entry is not None:
                    log.exception("rebuild of %r failed; serving the previous snapshot", key)
                    return entry[0]
                raise
            self._store(key, value)
            return value

    def _refresh_in_background(self, key: str, compute: Callable[[], object]) -> None:
        lock = self._lock_for(key)
        if not lock.acquire(blocking=False):
            return  # a rebuild is already running

        def run() -> None:
            try:
                self._store(key, compute())
            except Exception:
                log.exception("background rebuild of %r failed; keeping the previous snapshot", key)
            finally:
                lock.release()

        threading.Thread(target=run, name=f"refresh-{key}", daemon=True).start()


snapshots = SnapshotCache()
