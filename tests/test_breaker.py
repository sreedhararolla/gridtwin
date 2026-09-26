"""Seam B: the replay feed's circuit breaker - open after K failures, half-open after the
cooldown, and back to closed or open on the probe's outcome."""

from datetime import UTC, datetime, timedelta

from gridtwin.replay.breaker import (
    BreakerConfig,
    CircuitBreaker,
    allow,
    record_failure,
    record_success,
)

T0 = datetime(2025, 12, 10, 18, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)
CONFIG = BreakerConfig(failure_threshold=3, cooldown_intervals=2)


def fail_times(n: int) -> CircuitBreaker:
    breaker = CircuitBreaker()
    for i in range(n):
        breaker = record_failure(allow(breaker, T0 + i * STEP, CONFIG), T0 + i * STEP, CONFIG)
    return breaker


def test_stays_closed_below_the_failure_threshold():
    breaker = fail_times(2)
    assert breaker.status == "closed"
    assert breaker.failures == 2


def test_opens_after_k_consecutive_failures():
    breaker = fail_times(3)
    assert breaker.status == "open"
    assert breaker.opened_at == T0 + 2 * STEP


def test_success_resets_the_failure_count():
    breaker = record_success(fail_times(2))
    assert breaker == CircuitBreaker()
    assert record_failure(breaker, T0, CONFIG).status == "closed"


def test_open_breaker_blocks_calls_until_the_cooldown_passes():
    opened = fail_times(3)  # opened at T0 + 2 steps
    assert allow(opened, T0 + 3 * STEP, CONFIG).status == "open"


def test_goes_half_open_after_the_cooldown():
    opened = fail_times(3)
    assert allow(opened, T0 + 4 * STEP, CONFIG).status == "half_open"


def test_half_open_probe_success_closes_it():
    probe = allow(fail_times(3), T0 + 4 * STEP, CONFIG)
    assert record_success(probe).status == "closed"


def test_half_open_probe_failure_reopens_it_with_a_fresh_cooldown():
    probe_at = T0 + 4 * STEP
    reopened = record_failure(allow(fail_times(3), probe_at, CONFIG), probe_at, CONFIG)
    assert reopened.status == "open"
    assert reopened.opened_at == probe_at
    assert allow(reopened, probe_at + STEP, CONFIG).status == "open"
    assert allow(reopened, probe_at + 2 * STEP, CONFIG).status == "half_open"
