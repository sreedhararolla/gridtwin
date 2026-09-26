"""Clock interface: wall-anchored in compose, manual in tests (see CONTEXT.md: Replay Clock)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass
class WallAnchoredClock:
    """Replay time = replay start + (wall now - wall start) * speed, broadcast once per run."""

    replay_start: datetime
    wall_start: datetime
    speed: float

    def now(self) -> datetime:
        elapsed = datetime.now(UTC) - self.wall_start
        return self.replay_start + elapsed * self.speed


@dataclass
class ManualClock:
    """Advanced explicitly by the Scenario Runner; never reads the wall clock."""

    _current: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=UTC))

    def now(self) -> datetime:
        return self._current

    def advance(self, delta: timedelta) -> None:
        self._current += delta

    def set(self, when: datetime) -> None:
        self._current = when
