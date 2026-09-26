"""All IO for the dispatch workflow lives here. Workflows call these as activities and
never touch the ledger, the transport, telemetry or the market-data cache directly."""

import asyncio
from datetime import UTC, date, datetime, timedelta

from temporalio import activity

from gridtwin.dispatch.publish import ResultPublisher
from gridtwin.dispatch.workflows import ShardDispatchResult
from gridtwin.fleet.fleet import build_fleet, fleet_state_from_telemetry
from gridtwin.fleet.models import Command, FleetConfig, ShardReset
from gridtwin.ledger.models import IntervalResult
from gridtwin.ledger.repo import LedgerRepo
from gridtwin.marketdata.prices import load_day_prices
from gridtwin.planner.models import FleetPlan, FleetState
from gridtwin.planner.naive import naive_strategy
from gridtwin.replay.feed import validate_snapshot
from gridtwin.replay.models import MarketSnapshot
from gridtwin.telemetry.repo import TelemetryRepo
from gridtwin.transport.base import Transport

INTERVAL_MINUTES = 15
HEARTBEAT_EVERY_SECONDS = 0.5


async def _heartbeat_until_cancelled(detail: str) -> None:
    while True:
        activity.heartbeat(detail)
        await asyncio.sleep(HEARTBEAT_EVERY_SECONDS)


class DispatchActivities:
    """Bound to a concrete repo/telemetry/transport/publisher: Postgres+NATS for the real
    worker, in-memory implementations for the Scenario Runner (Seam A)."""

    def __init__(
        self,
        repo: LedgerRepo,
        telemetry: TelemetryRepo,
        transport: Transport,
        publisher: ResultPublisher,
    ) -> None:
        self._repo = repo
        self._telemetry = telemetry
        self._transport = transport
        self._publisher = publisher

    def all(self) -> list:
        return [
            self.seed_fleet,
            self.list_interval_starts,
            self.get_market_snapshot,
            self.get_fleet_state,
            self.build_plan,
            self.dispatch_shard,
            self.record_interval_result,
        ]

    @activity.defn
    async def seed_fleet(self, run_id: str, fleet: FleetConfig, timeout_seconds: float) -> None:
        """Hand every Shard its Devices for this run, and record their first Heartbeats so
        Fleet State is complete from the very first interval."""
        shards = build_fleet(fleet)
        heartbeat_batches = await asyncio.gather(
            *(
                self._transport.reset_shard(
                    ShardReset(
                        run_id=run_id,
                        shard_id=shard_id,
                        devices=devices,
                        response_noise_pct=fleet.response_noise_pct,
                        fault_rate=fleet.fault_rate,
                        seed=fleet.seed,
                    ),
                    timeout_seconds,
                )
                for shard_id, devices in shards.items()
            )
        )
        heartbeats = [hb for batch in heartbeat_batches for hb in batch]
        await asyncio.to_thread(self._telemetry.upsert_heartbeats, heartbeats)
        devices = [d for batch in shards.values() for d in batch]
        await asyncio.to_thread(self._repo.seed_devices, run_id, devices)

    @activity.defn
    async def list_interval_starts(
        self, settlement_point: str, day: date | None, fixture_path: str
    ) -> list[datetime]:
        rows = await asyncio.to_thread(load_day_prices, settlement_point, day, fixture_path)
        return [interval_start for interval_start, _price in rows]

    @activity.defn
    async def get_market_snapshot(
        self, interval_start: datetime, settlement_point: str, day: date | None, fixture_path: str
    ) -> MarketSnapshot:
        rows = await asyncio.to_thread(load_day_prices, settlement_point, day, fixture_path)
        prices = dict(rows)
        return validate_snapshot(interval_start, settlement_point, prices.get(interval_start))

    @activity.defn
    async def get_fleet_state(self, run_id: str, stale_after_seconds: float) -> FleetState:
        heartbeats = await asyncio.to_thread(self._telemetry.latest, run_id)
        return fleet_state_from_telemetry(heartbeats, datetime.now(UTC), stale_after_seconds)

    @activity.defn
    async def build_plan(
        self,
        fleet_state: FleetState,
        snapshot: MarketSnapshot,
        discharge_threshold_usd: float,
        charge_threshold_usd: float,
    ) -> FleetPlan:
        return naive_strategy(fleet_state, snapshot, discharge_threshold_usd, charge_threshold_usd)

    @activity.defn
    async def dispatch_shard(
        self,
        run_id: str,
        interval_start: datetime,
        shard_id: str,
        setpoints: dict[str, float],
        seq: int,
        timeout_seconds: float,
    ) -> ShardDispatchResult:
        # Keys are a pure function of the inputs, so a retry after a partial send re-sends
        # the same keys and the Devices dedupe them (exactly-once effects).
        expires_at = interval_start + timedelta(minutes=INTERVAL_MINUTES)
        commands = [
            Command(
                idempotency_key=f"{run_id}:{interval_start.isoformat()}:{device_id}:{seq}",
                run_id=run_id,
                interval_start=interval_start,
                device_id=device_id,
                seq=seq,
                setpoint_mw=setpoint_mw,
                expires_at=expires_at,
            )
            for device_id, setpoint_mw in setpoints.items()
        ]
        # Heartbeat throughout, not only between steps: a batch that waits on acks must not
        # look like a dead worker, and a dead worker must be noticed within the heartbeat
        # timeout so the retry lands on the surviving worker.
        heartbeats = asyncio.create_task(_heartbeat_until_cancelled(shard_id))
        try:
            await asyncio.to_thread(self._repo.upsert_commands, commands)
            reply = await self._transport.send_batch(shard_id, commands, timeout_seconds)
            await asyncio.to_thread(self._repo.record_acks, reply.acks)
        finally:
            heartbeats.cancel()
        acks = reply.acks
        attempt = activity.info().attempt
        return ShardDispatchResult(
            shard_id=shard_id,
            dispatched_count=len(commands),
            acked_count=sum(1 for a in acks if a.applied),
            delivered_mw=sum(a.delivered_mw for a in acks),
            reserve_violations=sum(1 for a in acks if a.floor_violation),
            duplicate_deliveries=reply.duplicate_deliveries,
            duplicate_effects=reply.duplicate_effects,
            attempt=attempt,
        )

    @activity.defn
    async def record_interval_result(self, result: IntervalResult) -> None:
        await asyncio.to_thread(self._repo.record_interval_result, result)
        await self._publisher.publish(result)
