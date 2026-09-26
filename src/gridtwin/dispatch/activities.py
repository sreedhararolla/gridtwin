"""All IO for the dispatch workflow lives here. Workflows call these as activities and
never touch the ledger, the transport or the market-data fixture directly."""

import asyncio
from datetime import datetime, timedelta

from temporalio import activity

from gridtwin.dispatch.publish import ResultPublisher
from gridtwin.fleet.device import aggregate_headroom
from gridtwin.fleet.models import Ack, Command, DeviceState
from gridtwin.ledger.models import IntervalResult
from gridtwin.ledger.repo import LedgerRepo
from gridtwin.marketdata.fixtures import load_fixture_day
from gridtwin.planner.models import FleetPlan, FleetState
from gridtwin.planner.naive import naive_strategy
from gridtwin.replay.feed import validate_snapshot
from gridtwin.replay.models import MarketSnapshot
from gridtwin.transport.base import Transport

INTERVAL_MINUTES = 15


class DispatchActivities:
    """Bound to a concrete repo/transport/publisher: Postgres+NATS for the real worker,
    in-memory implementations for the Scenario Runner (Seam A)."""

    def __init__(self, repo: LedgerRepo, transport: Transport, publisher: ResultPublisher) -> None:
        self._repo = repo
        self._transport = transport
        self._publisher = publisher

    @activity.defn
    async def seed_devices(self, run_id: str, devices: list[DeviceState]) -> None:
        await asyncio.to_thread(self._repo.seed_devices, run_id, devices)

    @activity.defn
    async def list_interval_starts(
        self, settlement_point: str, fixture_path: str
    ) -> list[datetime]:
        rows = await asyncio.to_thread(load_fixture_day, settlement_point, fixture_path)
        return [interval_start for interval_start, _price in rows]

    @activity.defn
    async def get_market_snapshot(
        self, interval_start: datetime, settlement_point: str, fixture_path: str
    ) -> MarketSnapshot:
        rows = await asyncio.to_thread(load_fixture_day, settlement_point, fixture_path)
        prices = dict(rows)
        return validate_snapshot(interval_start, settlement_point, prices.get(interval_start))

    @activity.defn
    async def get_fleet_state(self, run_id: str) -> FleetState:
        devices = await asyncio.to_thread(self._repo.get_devices, run_id)
        discharge_mw, charge_mw = aggregate_headroom(devices)
        return FleetState(
            discharge_headroom_mw=discharge_mw, charge_headroom_mw=charge_mw, devices=devices
        )

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
    ) -> list[Ack]:
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
        for command in commands:
            await asyncio.to_thread(self._repo.upsert_command, command)

        activity.heartbeat("sending batch")
        acks = await self._transport.send_batch(shard_id, commands, timeout_seconds)

        for ack in acks:
            await asyncio.to_thread(self._repo.record_ack, ack)
            if ack.applied:
                await asyncio.to_thread(
                    self._repo.update_device_soc, run_id, ack.device_id, ack.soc_pct_after
                )
        return acks

    @activity.defn
    async def record_interval_result(self, result: IntervalResult) -> None:
        await asyncio.to_thread(self._repo.record_interval_result, result)
        await self._publisher.publish(result)
