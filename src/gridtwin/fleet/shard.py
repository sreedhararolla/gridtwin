"""Shard simulator: owns a group of Devices in memory and answers Command batches.

This is the stateful shell around the pure device model: it draws the (seeded) response
noise and faults, and produces Heartbeats. `simulator/main.py` wraps it in NATS
request/reply for compose; `transport/memory.py` calls it directly for the in-process
Scenario Runner.
"""

import random
import zlib
from datetime import UTC, datetime

from gridtwin.fleet.device import apply_command
from gridtwin.fleet.models import Ack, Command, DeviceState, Heartbeat, ShardReset


class ShardSimulator:
    def __init__(self, devices: list[DeviceState] | None = None, run_id: str = "") -> None:
        self._run_id = run_id
        self._devices: dict[str, DeviceState] = {d.device_id: d for d in devices or []}
        self._power_mw: dict[str, float] = {}
        self._noise_pct = 0.0
        self._fault_rate = 0.0
        self._rng = random.Random(0)

    def reset(self, reset: ShardReset) -> None:
        """Start a Replay Run: replace this shard's Devices and reseed its randomness, so a
        run is reproducible and never inherits SoC from the previous run."""
        self._run_id = reset.run_id
        self._devices = {d.device_id: d for d in reset.devices}
        self._power_mw = {}
        self._noise_pct = reset.response_noise_pct
        self._fault_rate = reset.fault_rate
        self._rng = random.Random(reset.seed ^ zlib.crc32(reset.shard_id.encode()))

    def handle_batch(self, commands: list[Command]) -> list[Ack]:
        acks = []
        for command in commands:
            state = self._devices.get(command.device_id)
            if state is None:
                acks.append(
                    Ack(
                        idempotency_key=command.idempotency_key,
                        device_id=command.device_id,
                        applied=False,
                        delivered_mw=0.0,
                        soc_pct_after=0.0,
                    )
                )
                continue
            faulted = self._fault_rate > 0 and self._rng.random() < self._fault_rate
            factor = 1.0 + self._rng.gauss(0.0, self._noise_pct) if self._noise_pct > 0 else 1.0
            new_state, ack = apply_command(state, command, factor, faulted)
            self._devices[command.device_id] = new_state
            self._power_mw[command.device_id] = ack.delivered_mw
            acks.append(ack)
        return acks

    def heartbeats(self, now: datetime | None = None) -> list[Heartbeat]:
        sent_at = now or datetime.now(UTC)
        return [
            Heartbeat(
                run_id=self._run_id,
                state=state,
                power_mw=self._power_mw.get(device_id, 0.0),
                healthy=True,
                sent_at=sent_at,
            )
            for device_id, state in self._devices.items()
        ]

    def snapshot(self) -> list[DeviceState]:
        return list(self._devices.values())
