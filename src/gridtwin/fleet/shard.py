"""Shard simulator: owns a group of Devices in memory and answers Command batches.

This is the stateful shell around the pure device model: it draws the (seeded) response
noise and faults, remembers which Idempotency Keys each Device has acted on (so an
at-least-once transport gives exactly-once effects), and produces Heartbeats.
`simulator/main.py` wraps it in NATS request/reply for compose; `transport/memory.py`
calls it directly for the in-process Scenario Runner.
"""

import random
import zlib
from collections import Counter
from datetime import UTC, datetime

from gridtwin.fleet.device import apply_command, ignored_ack, screen_command
from gridtwin.fleet.models import Ack, BatchReply, Command, DeviceState, Heartbeat, ShardReset

# Duplicate-commands scenario: besides delivering every batch twice, replay the previous
# batch before this one on this share of batches.
OLD_BATCH_REPLAY_RATE = 0.3


class ShardSimulator:
    """Empty until `reset` hands it a run's Devices."""

    def __init__(self) -> None:
        self._run_id = ""
        self._devices: dict[str, DeviceState] = {}
        self._power_mw: dict[str, float] = {}
        self._noise_pct = 0.0
        self._fault_rate = 0.0
        self._rng = random.Random(0)
        self._chaos_rng = random.Random(0)
        self._duplicates = False
        self._reset_memory()

    def _reset_memory(self) -> None:
        self._received: set[str] = set()  # every key delivered to this shard this run
        self._acks: dict[str, Ack] = {}  # key -> the Device's one answer (applied or failed)
        self._effects: Counter[str] = Counter()  # key -> times a Device acted on it
        self._clock: dict[str, datetime] = {}  # device -> latest interval it acted in
        self._seq: dict[tuple[str, datetime], int] = {}  # (device, interval) -> highest seq
        self._previous_batch: list[Command] = []

    def reset(self, reset: ShardReset) -> None:
        """Start a Replay Run: replace this shard's Devices and reseed its randomness, so a
        run is reproducible and never inherits SoC (or key memory) from the previous run."""
        self._run_id = reset.run_id
        self._devices = {d.device_id: d for d in reset.devices}
        self._power_mw = {}
        self._noise_pct = reset.response_noise_pct
        self._fault_rate = reset.fault_rate
        shard_seed = reset.seed ^ zlib.crc32(reset.shard_id.encode())
        self._rng = random.Random(shard_seed)
        self._chaos_rng = random.Random(shard_seed ^ 0xD0B1E)
        self._reset_memory()

    def set_duplicates(self, active: bool) -> None:
        """The duplicate-commands Chaos Scenario: deliver each batch twice, and sometimes
        replay the previous batch first."""
        self._duplicates = active

    @property
    def duplicates(self) -> bool:
        return self._duplicates

    def handle_batch(self, commands: list[Command]) -> BatchReply:
        counts: Counter[str] = Counter()
        if (
            self._duplicates
            and self._previous_batch
            and self._chaos_rng.random() < OLD_BATCH_REPLAY_RATE
        ):
            self._deliver(self._previous_batch, counts)  # its Acks go nowhere
        acks = self._deliver(commands, counts)
        if self._duplicates:
            acks = self._deliver(commands, counts)
        self._previous_batch = commands
        return BatchReply(
            acks=acks,
            duplicate_deliveries=counts["duplicate_deliveries"],
            duplicate_effects=counts["duplicate_effects"],
        )

    def _deliver(self, commands: list[Command], counts: Counter[str]) -> list[Ack]:
        acks = []
        for command in commands:
            key = command.idempotency_key
            if key in self._received:
                counts["duplicate_deliveries"] += 1
            self._received.add(key)
            acks.append(self._act(command))
            if self._effects[key] > 1:
                counts["duplicate_effects"] += 1
        return acks

    def _act(self, command: Command) -> Ack:
        state = self._devices.get(command.device_id)
        # A newer run has taken over this shard: the old run's Commands must not act on
        # the new run's Devices.
        if state is None or command.run_id != self._run_id:
            return Ack(
                idempotency_key=command.idempotency_key,
                device_id=command.device_id,
                applied=False,
                delivered_mw=0.0,
                soc_pct_after=0.0,
                outcome="failed",
            )
        verdict = screen_command(
            command,
            already_answered=command.idempotency_key in self._acks,
            device_clock=self._clock.get(command.device_id),
            latest_seq=self._seq.get((command.device_id, command.interval_start)),
        )
        if verdict == "duplicate":
            return self._acks[command.idempotency_key]
        if verdict != "apply":
            return ignored_ack(state, command, verdict)

        faulted = self._fault_rate > 0 and self._rng.random() < self._fault_rate
        factor = 1.0 + self._rng.gauss(0.0, self._noise_pct) if self._noise_pct > 0 else 1.0
        new_state, ack = apply_command(state, command, factor, faulted)
        # The Device's answer to a key is final: a redelivery gets this Ack back, so
        # duplicates change nothing, not even whether a faulted Command acts later.
        self._acks[command.idempotency_key] = ack
        if faulted:
            return ack
        self._devices[command.device_id] = new_state
        self._power_mw[command.device_id] = ack.delivered_mw
        self._effects[command.idempotency_key] += 1
        clock = self._clock.get(command.device_id)
        if clock is None or command.interval_start > clock:
            self._clock[command.device_id] = command.interval_start
        self._seq[(command.device_id, command.interval_start)] = command.seq
        return ack

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
