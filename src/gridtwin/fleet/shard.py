"""Shard simulator: owns a group of Devices in memory and answers Command batches.

This is the IO/stateful shell around the pure device model. `simulator/main.py` wraps it
in a NATS request/reply responder for compose; `transport/memory.py` calls it directly
for the in-process Scenario Runner.
"""

from gridtwin.fleet.device import apply_command
from gridtwin.fleet.models import Ack, Command, DeviceState


class ShardSimulator:
    def __init__(self, devices: list[DeviceState]) -> None:
        self._devices: dict[str, DeviceState] = {d.device_id: d for d in devices}

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
            new_state, ack = apply_command(state, command)
            self._devices[command.device_id] = new_state
            acks.append(ack)
        return acks

    def snapshot(self) -> list[DeviceState]:
        return list(self._devices.values())
