"""线程安全的进程内滑动窗口限流器。"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        default_limit: int = 100,
        window_seconds: int = 3600,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 4096,
    ):
        self._requests: dict[str, list[float]] = {}
        self.default_limit = max(1, int(default_limit))
        self.window = max(1, int(window_seconds))
        self.max_keys = max(1, int(max_keys))
        self._clock = clock
        self._lock = threading.RLock()
        self._next_cleanup_at = 0.0

    def _prune_key_unlocked(self, key: str, window_start: float) -> list[float]:
        recent = [
            timestamp
            for timestamp in self._requests.get(key, ())
            if timestamp > window_start
        ]
        if recent:
            self._requests[key] = recent
        else:
            self._requests.pop(key, None)
        return recent

    def _prune_expired_unlocked(self, now: float) -> None:
        window_start = now - self.window
        for key in list(self._requests):
            self._prune_key_unlocked(key, window_start)
        self._next_cleanup_at = now + min(self.window, 60)

    def is_allowed(self, key: str, limit: int | None = None) -> bool:
        resolved_limit = self.default_limit if limit is None else max(1, int(limit))
        with self._lock:
            now = self._clock()
            window_start = now - self.window
            if now >= self._next_cleanup_at:
                self._prune_expired_unlocked(now)
            recent = self._prune_key_unlocked(key, window_start)
            if len(recent) >= resolved_limit:
                return False
            if key not in self._requests and len(self._requests) >= self.max_keys:
                self._prune_expired_unlocked(now)
                if len(self._requests) >= self.max_keys:
                    return False
            recent.append(now)
            self._requests[key] = recent
            return True

    def remaining(self, key: str, limit: int | None = None) -> int:
        resolved_limit = self.default_limit if limit is None else max(1, int(limit))
        with self._lock:
            now = self._clock()
            window_start = now - self.window
            if now >= self._next_cleanup_at:
                self._prune_expired_unlocked(now)
            recent = self._prune_key_unlocked(key, window_start)
            return max(0, resolved_limit - len(recent))

    def clear(self) -> None:
        """Clear process-local counters; primarily useful for deterministic tests."""
        with self._lock:
            self._requests.clear()
            self._next_cleanup_at = 0.0
