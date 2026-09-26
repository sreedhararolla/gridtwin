from gridtwin.marketdata.throttle import RateLimiter


class FakeClock:
    """A clock that advances by however long `sleep` was asked to wait."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_allows_calls_up_to_the_limit_without_sleeping():
    clock = FakeClock()
    limiter = RateLimiter(max_calls=30, period_seconds=60.0, clock=clock.time, sleep=clock.sleep)

    for _ in range(30):
        limiter.acquire()

    assert clock.slept == []


def test_blocks_the_31st_call_within_the_window():
    clock = FakeClock()
    limiter = RateLimiter(max_calls=30, period_seconds=60.0, clock=clock.time, sleep=clock.sleep)

    for _ in range(30):
        limiter.acquire()
    limiter.acquire()

    assert clock.slept == [60.0]
    assert clock.now == 60.0


def test_never_exceeds_the_configured_rate_over_a_burst_of_calls():
    clock = FakeClock()
    limiter = RateLimiter(max_calls=30, period_seconds=60.0, clock=clock.time, sleep=clock.sleep)
    call_times = []

    for _ in range(90):
        limiter.acquire()
        call_times.append(clock.now)

    for window_start in range(0, len(call_times)):
        window_end = call_times[window_start] + 60.0
        calls_in_window = sum(1 for t in call_times[window_start:] if t < window_end)
        assert calls_in_window <= 30


def test_does_not_sleep_once_the_window_has_passed():
    clock = FakeClock()
    limiter = RateLimiter(max_calls=30, period_seconds=60.0, clock=clock.time, sleep=clock.sleep)

    for _ in range(30):
        limiter.acquire()
    clock.now += 60.0
    limiter.acquire()

    assert clock.slept == []
