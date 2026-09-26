"""Pure circuit breaker on the replay feed (Seam B).

closed --K consecutive failures--> open --cooldown--> half-open --success--> closed
                                     ^                    |
                                     +------failure-------+

Time is replay time (the interval being decided), so the breaker is deterministic inside
a Temporal workflow and independent of replay speed."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

BreakerStatus = Literal["closed", "open", "half_open"]
INTERVAL = timedelta(minutes=15)


class BreakerConfig(BaseModel, frozen=True):
    failure_threshold: int = Field(default=3, ge=1)  # K consecutive failures open it
    cooldown_intervals: int = Field(default=2, ge=1)  # then one trial call is let through


class CircuitBreaker(BaseModel, frozen=True):
    status: BreakerStatus = "closed"
    failures: int = 0  # consecutive
    opened_at: datetime | None = None


def allow(breaker: CircuitBreaker, now: datetime, config: BreakerConfig) -> CircuitBreaker:
    """Before a feed call: an open breaker whose cooldown has passed goes half-open. The
    call may go ahead unless the returned breaker is still open."""
    if breaker.status == "open" and breaker.opened_at is not None:
        if now >= breaker.opened_at + config.cooldown_intervals * INTERVAL:
            return breaker.model_copy(update={"status": "half_open"})
    return breaker


def record_success(breaker: CircuitBreaker) -> CircuitBreaker:
    return CircuitBreaker()


def record_failure(breaker: CircuitBreaker, now: datetime, config: BreakerConfig) -> CircuitBreaker:
    failures = breaker.failures + 1
    if breaker.status == "half_open" or failures >= config.failure_threshold:
        return CircuitBreaker(status="open", failures=failures, opened_at=now)
    return breaker.model_copy(update={"failures": failures})
