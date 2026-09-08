from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock


@dataclass(slots=True)
class _ClientWindow:
    started_at: float
    request_count: int


class FixedWindowRateLimiter:
    """In-process fixed-window limiter keyed by Integration Client ID."""

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._clock = clock
        self._lock = Lock()
        self._windows: dict[str, _ClientWindow] = {}

    def consume(self, client_id: str) -> int | None:
        """Consume one request, returning Retry-After seconds when rejected."""
        with self._lock:
            now = self._clock()
            self._remove_expired_windows(now)
            window = self._windows.get(client_id)
            if window is None:
                self._windows[client_id] = _ClientWindow(
                    started_at=now,
                    request_count=1,
                )
                return None
            if window.request_count < self._max_requests:
                window.request_count += 1
                return None
            remaining = window.started_at + self._window_seconds - now
            return max(1, math.ceil(remaining))

    def _remove_expired_windows(self, now: float) -> None:
        expired = [
            client_id
            for client_id, window in self._windows.items()
            if now - window.started_at >= self._window_seconds
        ]
        for client_id in expired:
            del self._windows[client_id]
