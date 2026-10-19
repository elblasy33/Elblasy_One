"""Sliding-window limiter. In-process only: replace with a shared store (Redis) when the API
runs with more than one worker. Documented limitation."""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_s: float) -> None:
        self.limit, self.window = limit, window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


login_limiter = RateLimiter(limit=10, window_s=300)
