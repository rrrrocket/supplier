from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.integration_rate_limit import FixedWindowRateLimiter


DATABASE_URL = "postgresql+psycopg://supplier:secret@db:6432/supplier"


class MutableClock:
    def __init__(self, initial: float = 0.0) -> None:
        self.current = initial

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def test_client_reopens_after_ceiling_rounded_retry_window() -> None:
    clock = MutableClock(initial=20.0)
    limiter = FixedWindowRateLimiter(
        max_requests=2,
        window_seconds=10,
        clock=clock,
    )

    assert limiter.consume("client-a") is None
    assert limiter.consume("client-a") is None

    clock.advance(3.2)
    assert limiter.consume("client-a") == 7

    clock.advance(6.8)
    assert limiter.consume("client-a") is None


def test_different_clients_have_independent_windows() -> None:
    limiter = FixedWindowRateLimiter(
        max_requests=1,
        window_seconds=60,
        clock=MutableClock(),
    )

    assert limiter.consume("client-a") is None
    assert limiter.consume("client-a") == 60
    assert limiter.consume("client-b") is None


def test_concurrent_requests_cannot_exceed_the_configured_budget() -> None:
    max_requests = 5
    worker_count = 24
    barrier = Barrier(worker_count)
    limiter = FixedWindowRateLimiter(
        max_requests=max_requests,
        window_seconds=60,
        clock=MutableClock(),
    )

    def consume_together(_: int) -> int | None:
        barrier.wait()
        return limiter.consume("shared-client")

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(consume_together, range(worker_count)))

    assert results.count(None) == max_requests
    assert results.count(60) == worker_count - max_requests


def test_expired_client_windows_are_removed_opportunistically() -> None:
    clock = MutableClock()
    limiter = FixedWindowRateLimiter(
        max_requests=1,
        window_seconds=10,
        clock=clock,
    )

    assert limiter.consume("expired-a") is None
    assert limiter.consume("expired-b") is None
    clock.advance(10)
    assert limiter.consume("current") is None

    assert set(limiter._windows) == {"current"}


def test_rate_limit_settings_default_to_600_requests_per_60_seconds() -> None:
    settings = Settings(database_url=DATABASE_URL)

    assert settings.integration_rate_limit_requests == 600
    assert settings.integration_rate_limit_window_seconds == 60


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("integration_rate_limit_requests", 0),
        ("integration_rate_limit_window_seconds", 0),
    ],
)
def test_rate_limit_settings_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=DATABASE_URL, **{field: value})
