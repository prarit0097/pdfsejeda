"""Per-IP hourly task quota (Sejda: 3 tasks/hour per IP, 402 "tasks-per-hour").

TASKS_PER_HOUR=0 disables the quota. Window is a sliding hour.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from .config import settings

WINDOW = 3600


class TaskQuota:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] >= WINDOW:
            q.popleft()

    def consume(self, ip: str) -> tuple[bool, int, int]:
        """Try to use one task. Returns (allowed, remaining, wait_seconds)."""
        limit = settings.tasks_per_hour
        if limit <= 0:
            return True, 9999, 0
        now = time.time()
        with self._lock:
            q = self._hits[ip]
            self._prune(q, now)
            wait = int(WINDOW - (now - q[0])) if q else WINDOW
            if len(q) >= limit:
                return False, -1, wait
            q.append(now)
            wait = int(WINDOW - (now - q[0]))
            return True, limit - len(q), wait

    def refund(self, ip: str) -> None:
        """Give back the last task (it was rejected before it could run)."""
        with self._lock:
            q = self._hits.get(ip)
            if q:
                q.pop()

    def prune(self) -> None:
        """Forget IPs with no task in the last hour (keeps memory bounded)."""
        now = time.time()
        with self._lock:
            for ip in list(self._hits):
                q = self._hits[ip]
                self._prune(q, now)
                if not q:
                    del self._hits[ip]


quota = TaskQuota()
