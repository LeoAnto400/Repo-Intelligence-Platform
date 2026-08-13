import time
from collections import defaultdict, deque
from typing import Deque, Dict


class InMemoryRateLimiter:
    """
    Per-key sliding-window rate limiter, in-memory and single-process.

    Tracks request timestamps per key (e.g. client IP) over a trailing
    window and rejects a request once the count within that window would
    exceed ``max_requests``. Keeps no shared state across processes, so a
    multi-worker/multi-instance deployment would need a shared store (e.g.
    Redis) instead - fine for this single-process FastAPI app.
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()

        if len(hits) >= self.max_requests:
            return False

        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()
