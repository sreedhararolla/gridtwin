"""Pure sliding-window rate limiter for the ERCOT API's 30 req/min cap.

No IO: the clock and sleep are injected so the limiting logic is testable
without a real network call or a real wall-clock wait.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    max_calls: int
    period_seconds: float
    clock: Callable[[], float]
    sleep: Callable[[float], None]
    _call_times: deque[float] = field(default_factory=deque)

    def acquire(self) -> None:
        now = self.clock()
        while self._call_times and now - self._call_times[0] >= self.period_seconds:
            self._call_times.popleft()

        if len(self._call_times) >= self.max_calls:
            wait_for = self.period_seconds - (now - self._call_times[0])
            if wait_for > 0:
                self.sleep(wait_for)
            now = self.clock()
            while self._call_times and now - self._call_times[0] >= self.period_seconds:
                self._call_times.popleft()

        self._call_times.append(now)
