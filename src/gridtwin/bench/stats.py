"""Pure benchmark statistics (Seam B): latency percentiles, the per-size verdict, the
maximum sustainable device count, and whether memory stayed flat over a soak."""

from math import ceil

from pydantic import BaseModel


class SizeResult(BaseModel):
    """One fleet size of the matrix: a Replay Run of `intervals` Market Intervals."""

    devices: int
    shards: int
    simulators: int
    intervals: int  # Market Intervals the run was asked to replay
    completed: int  # Interval Results recorded
    budget_ms: float
    p50_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    commands_per_s: float = 0.0  # Commands dispatched / wall time spent dispatching
    commands_per_interval: int = 0
    min_online_devices: int = 0
    recovery_s: float | None = None  # worker kill -> interrupted interval's result
    kill_interval_ms: float | None = None  # latency of the interval the kill hit
    fleet_state_mb: float = 0.0  # Fleet State payload size through Temporal
    error: str = ""

    @property
    def sustained(self) -> bool:
        """Every interval replayed, each inside its wall budget, nothing failed."""
        return (
            not self.error
            and self.completed == self.intervals
            and self.max_ms <= self.budget_ms
            and self.min_online_devices == self.devices
        )


class MemorySample(BaseModel, frozen=True):
    elapsed_s: float
    rss_mb: dict[str, float]  # process role -> resident set size


class MemoryVerdict(BaseModel, frozen=True):
    process: str
    warm_mb: float  # after warm-up
    end_mb: float
    max_mb: float
    growth_pct: float  # end vs warm
    flat: bool


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..1): the smallest value with at least q of the
    sample at or below it. With fewer than 100 samples p99 is the maximum."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(ceil(q * len(ordered)), 1)
    return ordered[rank - 1]


def shard_count(devices: int, devices_per_shard: int) -> int:
    return max(ceil(devices / devices_per_shard), 1)


def simulator_count(shards: int, shards_per_simulator: int) -> int:
    """At least two simulator processes, as in compose."""
    return max(ceil(shards / shards_per_simulator), 2)


def max_sustainable(results: list[SizeResult]) -> int:
    """The largest device count at which a run was sustained, provided no smaller size
    failed (0 if even the smallest did not hold)."""
    best = 0
    for result in sorted(results, key=lambda r: r.devices):
        if not result.sustained:
            break
        best = result.devices
    return best


def next_probe(results: list[SizeResult], resolution: int) -> int | None:
    """Bisection step between the largest sustained size and the smallest failed one
    above it, rounded down to `resolution`; None once they are within it."""
    best = max_sustainable(results)
    failed = sorted(r.devices for r in results if not r.sustained and r.devices > best)
    if not failed:
        return None
    lo, hi = best, failed[0]
    if hi - lo <= resolution:
        return None
    mid = (lo + hi) // 2 // resolution * resolution
    return mid if lo < mid < hi else None


def memory_verdicts(
    samples: list[MemorySample], warmup_s: float, max_growth_pct: float
) -> list[MemoryVerdict]:
    """Per process: RSS after warm-up vs at the end of the soak. Flat = grew less than
    `max_growth_pct` (heaps and caches settle during warm-up, so it is excluded)."""
    warm = [s for s in samples if s.elapsed_s >= warmup_s] or samples
    if not warm:
        return []
    verdicts = []
    for process in warm[0].rss_mb:
        series = [s.rss_mb[process] for s in warm if process in s.rss_mb]
        start, end = series[0], series[-1]
        growth = (end - start) / start * 100 if start > 0 else 0.0
        verdicts.append(
            MemoryVerdict(
                process=process,
                warm_mb=start,
                end_mb=end,
                max_mb=max(series),
                growth_pct=growth,
                flat=growth < max_growth_pct,
            )
        )
    return verdicts
