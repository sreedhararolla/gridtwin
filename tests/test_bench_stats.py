"""Seam B: the bench's pure statistics - percentiles, the per-size verdict, bisection for
the maximum sustainable fleet, and the flat-memory verdict."""

from gridtwin.bench.stats import (
    MemorySample,
    SizeResult,
    max_sustainable,
    memory_verdicts,
    next_probe,
    percentile,
    shard_count,
    simulator_count,
)


def size(devices: int, max_ms: float = 900.0, completed: int = 6, error: str = "") -> SizeResult:
    return SizeResult(
        devices=devices,
        shards=shard_count(devices, 250),
        simulators=2,
        intervals=6,
        completed=completed,
        budget_ms=15_000.0,
        max_ms=max_ms,
        min_online_devices=devices,
        error=error,
    )


def test_percentile_is_nearest_rank():
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 0.50) == 50.0
    assert percentile(values, 0.99) == 99.0
    assert percentile([3.0, 1.0, 2.0], 0.99) == 3.0  # few samples: p99 is the max
    assert percentile([], 0.5) == 0.0


def test_shards_and_simulators_scale_with_the_fleet():
    assert shard_count(20_000, 250) == 80
    assert shard_count(1_001, 250) == 5
    assert simulator_count(80, 20) == 4
    assert simulator_count(4, 20) == 2  # never fewer than two, as in compose


def test_a_size_holds_only_if_every_interval_is_done_in_budget():
    assert size(1_000).sustained
    assert not size(1_000, max_ms=15_001.0).sustained
    assert not size(1_000, completed=5).sustained
    assert not size(1_000, error="BlobSizeLimitError").sustained
    dropped = size(1_000).model_copy(update={"min_online_devices": 990})
    assert not dropped.sustained


def test_max_sustainable_stops_at_the_first_failure():
    results = [size(1_000), size(5_000), size(10_000, error="x"), size(20_000)]
    assert max_sustainable(results) == 5_000
    assert max_sustainable([size(1_000, error="x")]) == 0


def test_bisection_narrows_to_the_resolution():
    results = [size(10_000), size(20_000, error="payload too large")]
    assert next_probe(results, 2_500) == 15_000
    results.append(size(15_000, error="payload too large"))
    assert next_probe(results, 2_500) == 12_500
    results.append(size(12_500))
    assert next_probe(results, 2_500) is None  # 12,500..15,000 is within resolution
    assert max_sustainable(results) == 12_500
    assert next_probe([size(1_000), size(5_000)], 2_500) is None  # nothing failed


def test_memory_verdict_ignores_warm_up_and_flags_growth():
    samples = [
        MemorySample(elapsed_s=0, rss_mb={"worker": 50.0, "sims": 50.0}),
        MemorySample(elapsed_s=60, rss_mb={"worker": 100.0, "sims": 100.0}),
        MemorySample(elapsed_s=1800, rss_mb={"worker": 104.0, "sims": 150.0}),
    ]
    verdicts = {v.process: v for v in memory_verdicts(samples, 60, 10.0)}
    assert verdicts["worker"].flat and verdicts["worker"].growth_pct == 4.0
    assert not verdicts["sims"].flat and verdicts["sims"].max_mb == 150.0
