"""`make bench`: the scale benchmark matrix. For each fleet size it starts a fresh set of
host processes (two workers, the telemetry ingester, the simulators) against the bench
infra, replays Market Intervals at REPLAY_SPEED, kills the worker running a dispatch
mid-flight, and reads the Interval Results back from the ledger. Then it times the LP
planner, soaks the largest sustainable size for BENCH_SOAK_MINUTES while sampling every
process's memory, and writes BENCHMARKS.md.

Run through `make bench`, which starts docker-compose.bench.yml and points POSTGRES_DSN,
NATS_URL, TEMPORAL_ADDRESS and TASK_QUEUE at it, so this never touches the demo stack."""

import asyncio
import json
import logging
import platform
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psutil
import psycopg
from temporalio.client import Client, WorkflowFailureError

from gridtwin.bench.procs import BenchFleet
from gridtwin.bench.report import render_markdown
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
from gridtwin.chaos.temporal_probe import NoDispatchSeen, RunNotRunning, wait_for_dispatch
from gridtwin.dispatch.workflows import INTERVAL_SECONDS, WORKFLOW_TASK_TIMEOUT, ReplayRunWorkflow
from gridtwin.fleet.fleet import build_fleet, fleet_state_from_telemetry, shard_ids
from gridtwin.fleet.models import FleetConfig, Heartbeat
from gridtwin.ledger.db import init_schema
from gridtwin.ledger.postgres_repo import PostgresLedgerRepo
from gridtwin.marketdata.prices import load_day_prices
from gridtwin.planner.lp import lp_strategy
from gridtwin.replay.cli import build_run_input, connect_temporal
from gridtwin.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bench")

LOG_DIR = Path(settings.marketdata_cache_dir) / "bench"
READY_TIMEOUT_S = 90.0
POLL_S = 0.05
SEED_GRACE_S = 60.0  # a run's first interval also waits for the fleet to be seeded
PLANNER_SOLVES = 20


def _fleet_config(devices: int) -> FleetConfig:
    return settings.fleet_config().model_copy(
        update={
            "device_count": devices,
            "shard_count": shard_count(devices, settings.bench_devices_per_shard),
        }
    )


def fleet_state_mb(devices: int) -> float:
    """The Fleet State payload `get_fleet_state` hands the workflow, as Temporal sees it."""
    config = _fleet_config(devices)
    now = datetime.now(UTC)
    beats = [
        Heartbeat(run_id="bench", state=d, power_mw=0.0, healthy=True, sent_at=now)
        for shard in build_fleet(config).values()
        for d in shard
    ]
    state = fleet_state_from_telemetry(beats, now, settings.stale_after_seconds)
    return len(state.model_dump_json()) / 1e6


def _instances_seen_since(started: datetime) -> set[str]:
    with psycopg.connect(settings.postgres_dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT instance_id FROM service_heartbeats WHERE last_seen > %s", (started,)
        ).fetchall()
    return {r[0] for r in rows}


async def _wait_ready(fleet: BenchFleet, started: datetime) -> None:
    expected = {"bench-telemetry", *fleet.workers, *(f"bench-{s.role}" for s in fleet.simulators)}
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        seen = await asyncio.to_thread(_instances_seen_since, started)
        if expected <= seen:
            await asyncio.sleep(2.0)  # workers poll right after their first liveness beat
            return
        await asyncio.sleep(0.5)
    raise TimeoutError(f"bench processes not ready: missing {sorted(expected - seen)}")


def _results(run_id: str):
    return PostgresLedgerRepo().list_interval_results(run_id)


async def _wait_for_results(run_id: str, count: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if len(await asyncio.to_thread(_results, run_id)) >= count:
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(f"{run_id}: fewer than {count} Interval Results after {timeout_s:.0f} s")


async def _kill_mid_dispatch(
    client: Client, fleet: BenchFleet, run_id: str
) -> tuple[datetime, float, str]:
    """Kill the worker running an in-flight dispatch; returns the interrupted interval,
    the kill time (monotonic) and the worker's identity."""
    dispatch = await wait_for_dispatch(client, run_id, None, settings.chaos_dispatch_wait_seconds)
    killed_at = time.monotonic()
    fleet.workers[dispatch.worker].kill()
    log.info("killed %s mid-dispatch (%s)", dispatch.worker, dispatch.activity_id)
    return dispatch.interval_start, killed_at, dispatch.worker


async def _measure_recovery(run_id: str, interval_start: datetime, killed_at: float) -> float:
    """Recovery Time: the kill until the interrupted interval's Interval Result exists."""
    deadline = killed_at + INTERVAL_SECONDS / settings.replay_speed * 4
    while time.monotonic() < deadline:
        results = await asyncio.to_thread(_results, run_id)
        if any(r.interval_start == interval_start for r in results):
            return time.monotonic() - killed_at
        await asyncio.sleep(POLL_S)
    raise TimeoutError(f"interval {interval_start.isoformat()} never recorded after the kill")


def _window(intervals: int) -> list[datetime]:
    rows = load_day_prices(settings.settlement_point, None, settings.fixture_path)
    return [interval_start for interval_start, _ in rows][:intervals]


def _error_text(exc: BaseException) -> str:
    parts = []
    while exc is not None and len(parts) < 6:
        parts.append(f"{type(exc).__name__}: {exc}")
        exc = exc.__cause__
    return " <- ".join(parts)[:400]


async def _start_run(client: Client, run_id: str, config: FleetConfig, intervals: int):
    run_input = build_run_input(run_id, None, settings.settlement_point, "naive").model_copy(
        update={"fleet": config, "interval_starts": _window(intervals)}
    )
    return await client.start_workflow(
        ReplayRunWorkflow.run,
        run_input,
        id=f"replay:{run_id}",
        task_queue=settings.task_queue,
        task_timeout=WORKFLOW_TASK_TIMEOUT,
    )


async def run_size(
    client: Client, devices: int, intervals: int, kill_at: int | None, soak_s: float = 0.0
) -> tuple[SizeResult, list[MemorySample]]:
    """One fleet size on fresh processes. With `soak_s`, Replay Runs follow each other on
    the same processes (a replay day has 96 intervals) until `soak_s` has passed; the
    latency figures then cover every run."""
    config = _fleet_config(devices)
    sims = simulator_count(config.shard_count, settings.bench_shards_per_simulator)
    budget_ms = INTERVAL_SECONDS / settings.replay_speed * 1000
    tag = f"bench-{devices}-{uuid.uuid4().hex[:6]}"
    run_ids: list[str] = []
    fleet = BenchFleet(
        {"DEVICE_COUNT": str(devices), "SHARD_COUNT": str(config.shard_count)},
        shard_ids(config.shard_count),
        sims,
        LOG_DIR / tag,
    )
    result = SizeResult(
        devices=devices,
        shards=config.shard_count,
        simulators=sims,
        intervals=intervals,
        completed=0,
        budget_ms=budget_ms,
        fleet_state_mb=fleet_state_mb(devices),
    )
    log.info(
        "size %d: %d shards on %d simulators, %d intervals (%s)",
        devices,
        config.shard_count,
        sims,
        intervals,
        tag,
    )
    samples: list[MemorySample] = []
    requested = 0
    started = datetime.now(UTC)
    fleet.start()
    killed: tuple[datetime, float, str] | None = None
    try:
        await _wait_ready(fleet, started)
        t0 = time.monotonic()
        sampler = asyncio.create_task(_sample_memory(fleet, t0, samples))
        try:
            remaining = intervals
            while remaining > 0:
                run_id = f"{tag}-{len(run_ids)}"
                run_ids.append(run_id)
                batch = min(remaining, 96)
                remaining -= batch
                requested += batch
                handle = await _start_run(client, run_id, config, batch)
                timeout_s = SEED_GRACE_S + batch * budget_ms / 1000 * 1.5
                if kill_at is not None and kill_at < batch and len(run_ids) == 1:
                    await _wait_for_results(run_id, kill_at, timeout_s)
                    killed = await _kill_mid_dispatch(client, fleet, run_id)
                    recovery = await _measure_recovery(run_id, killed[0], killed[1])
                    result.recovery_s = round(recovery, 2)
                    await asyncio.sleep(settings.chaos_restart_delay_seconds)
                    fleet.workers[killed[2]].start()
                await asyncio.wait_for(handle.result(), timeout=timeout_s)
                if soak_s and remaining <= 0 and time.monotonic() - t0 < soak_s:
                    remaining = int((soak_s - (time.monotonic() - t0)) // (budget_ms / 1000)) + 1
        finally:
            sampler.cancel()
    except (TimeoutError, WorkflowFailureError, RunNotRunning, NoDispatchSeen) as exc:
        result.error = _error_text(exc)
        log.warning("size %d failed: %s", devices, result.error)
        try:
            if run_ids:
                await client.get_workflow_handle(f"replay:{run_ids[-1]}").terminate("failed")
        except Exception:  # noqa: BLE001 - it may never have started or already ended
            pass
    finally:
        fleet.stop()

    results = [r for run_id in run_ids for r in await asyncio.to_thread(_results, run_id)]
    result.intervals = max(requested, intervals)
    _summarize(result, results, killed[0] if killed else None)
    log.info("size %d: %s", devices, result.model_dump_json())
    return result, samples


def _summarize(result: SizeResult, results: list, killed_interval: datetime | None) -> None:
    """Latency and throughput over the intervals the kill did not hit; the interrupted
    interval is reported on its own (it carries the retry)."""
    clean = [
        r for r in results if not (r.run_id.endswith("-0") and r.interval_start == killed_interval)
    ]
    latencies = [r.latency_ms for r in clean]
    dispatch_s = sum(latencies) / 1000
    result.completed = len(results)
    result.p50_ms = round(percentile(latencies, 0.50), 1)
    result.p99_ms = round(percentile(latencies, 0.99), 1)
    result.max_ms = round(max((r.latency_ms for r in results), default=0.0), 1)
    if dispatch_s:
        result.commands_per_s = round(sum(r.dispatched_count for r in clean) / dispatch_s)
    result.commands_per_interval = max((r.dispatched_count for r in results), default=0)
    result.min_online_devices = min((r.online_devices for r in results), default=0)
    if killed_interval is not None:
        hit = [
            r.latency_ms
            for r in results
            if r.run_id.endswith("-0") and r.interval_start == killed_interval
        ]
        result.kill_interval_ms = round(hit[0], 1) if hit else None


async def _sample_memory(fleet: BenchFleet, t0: float, samples: list[MemorySample]) -> None:
    while True:
        rss = await asyncio.to_thread(fleet.rss_by_role)
        samples.append(MemorySample(elapsed_s=round(time.monotonic() - t0, 1), rss_mb=rss))
        await asyncio.sleep(settings.bench_memory_sample_seconds)


def planner_solve_ms(devices: int) -> tuple[float, float]:
    """LP solve time (p50, p99 ms) on a Fleet State of `devices` over the fixture day's
    prices as a perfect 96-interval forecast. The LP sees only the aggregate."""
    config = _fleet_config(devices)
    now = datetime.now(UTC)
    beats = [
        Heartbeat(run_id="bench", state=d, power_mw=0.0, healthy=True, sent_at=now)
        for shard in build_fleet(config).values()
        for d in shard
    ]
    state = fleet_state_from_telemetry(beats, now, settings.stale_after_seconds)
    prices = [p for _, p in load_day_prices(settings.settlement_point, None, settings.fixture_path)]
    lp = settings.lp_config()
    timings = []
    for k in range(PLANNER_SOLVES):
        horizon = (prices[k:] + prices[:k])[: lp.horizon_intervals]
        t = time.perf_counter()
        lp_strategy(state, horizon, lp, "bench")
        timings.append((time.perf_counter() - t) * 1000)
    return round(percentile(timings, 0.5), 1), round(percentile(timings, 0.99), 1)


def machine_specs() -> dict[str, str]:
    mem = psutil.virtual_memory().total / 2**30
    return {
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "logical_cpus": str(psutil.cpu_count(logical=True)),
        "memory_gb": f"{mem:.1f}",
        "python": platform.python_version(),
    }


async def _connect_when_up() -> Client:
    """The bench's Temporal may have just started (auto-setup takes a while)."""
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        try:
            client = await connect_temporal()
            await client.count_workflows()
            return client
        except Exception:  # noqa: BLE001 - keep trying until the deadline
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(2.0)


async def main() -> None:
    init_schema()
    client = await _connect_when_up()
    # An interrupted bench leaves runs on its own Temporal; new workers must not inherit them.
    async for wf in client.list_workflows("ExecutionStatus = 'Running'"):
        await client.get_workflow_handle(wf.id, run_id=wf.run_id).terminate("stale bench run")
    sizes = settings.bench_size_list
    log.info("bench %s devices at %gx, queue %s", sizes, settings.replay_speed, settings.task_queue)

    results: list[SizeResult] = []
    for devices in sizes:
        result, _ = await run_size(
            client, devices, settings.bench_intervals, settings.bench_kill_at_interval
        )
        results.append(result)

    # Not every size held: bisect for the largest that does (no kill; latency and
    # completeness decide it).
    probes: list[SizeResult] = []
    while (probe := next_probe(results + probes, settings.bench_probe_resolution)) is not None:
        result, _ = await run_size(client, probe, settings.bench_probe_intervals, None)
        probes.append(result)

    sustainable = max_sustainable(results + probes)
    planner = {devices: planner_solve_ms(devices) for devices in sizes}

    soak_devices = sustainable or min(sizes)
    soak_s = settings.bench_soak_minutes * 60
    budget_s = INTERVAL_SECONDS / settings.replay_speed
    soak_intervals = int(soak_s // budget_s) + 1
    log.info(
        "soak: %d devices for %.0f min (%d intervals)", soak_devices, soak_s / 60, soak_intervals
    )
    soak, samples = await run_size(client, soak_devices, soak_intervals, None, soak_s)
    verdicts = memory_verdicts(
        samples, settings.bench_memory_warmup_seconds, settings.bench_memory_max_growth_pct
    )

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "replay_speed": settings.replay_speed,
        "machine": machine_specs(),
        "sizes": [r.model_dump() for r in results],
        "probes": [r.model_dump() for r in probes],
        "max_sustainable_devices": sustainable,
        "planner_ms": {str(k): v for k, v in planner.items()},
        "soak": {
            "devices": soak_devices,
            "minutes": settings.bench_soak_minutes,
            "run": soak.model_dump(),
            "samples": [s.model_dump() for s in samples],
            "verdicts": [v.model_dump() for v in verdicts],
        },
        "config": {
            "devices_per_shard": settings.bench_devices_per_shard,
            "shards_per_simulator": settings.bench_shards_per_simulator,
            "worker_max_concurrent_activities": settings.worker_max_concurrent_activities,
            "intervals_per_size": settings.bench_intervals,
            "kill_at_interval": settings.bench_kill_at_interval,
            "restart_delay_s": settings.chaos_restart_delay_seconds,
            "nats_pending_msgs_limit": settings.nats_pending_msgs_limit,
            "nats_pending_bytes_mb": settings.nats_pending_bytes_mb,
            "memory_max_growth_pct": settings.bench_memory_max_growth_pct,
        },
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "bench.json").write_text(json.dumps(report, indent=2, default=str))
    markdown = render_markdown(report)
    Path(settings.bench_output).write_text(markdown, encoding="utf-8")
    print(markdown.split("## Methodology")[0])
    log.info("wrote %s and %s", settings.bench_output, LOG_DIR / "bench.json")


if __name__ == "__main__":
    asyncio.run(main())
