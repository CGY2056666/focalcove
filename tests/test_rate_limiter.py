from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.middlewares.ratelimit import RateLimiter


def test_rate_limiter_is_atomic_across_threads() -> None:
    limiter = RateLimiter(10, 60, clock=lambda: 100.0)
    with ThreadPoolExecutor(max_workers=24) as pool:
        decisions = list(pool.map(lambda _: limiter.is_allowed("same-key"), range(100)))

    assert sum(decisions) == 10
    assert limiter.remaining("same-key") == 0


def test_rate_limiter_prunes_expired_keys_and_never_exceeds_capacity() -> None:
    now = [100.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0], max_keys=2)

    assert limiter.is_allowed('first') is True
    assert limiter.is_allowed('second') is True
    assert limiter.is_allowed('third') is False
    assert len(limiter._requests) == 2

    now[0] = 111.0
    assert limiter.is_allowed('third') is True
    assert set(limiter._requests) == {'third'}

    limiter.clear()
    assert limiter.remaining('unknown') == 2
    assert limiter._requests == {}


def test_rate_limiter_window_and_clear_are_deterministic() -> None:
    now = [100.0]
    limiter = RateLimiter(1, 10, clock=lambda: now[0])
    assert limiter.is_allowed("key") is True
    assert limiter.is_allowed("key") is False
    now[0] = 111.0
    assert limiter.is_allowed("key") is True
    limiter.clear()
    assert limiter.remaining("key") == 1
