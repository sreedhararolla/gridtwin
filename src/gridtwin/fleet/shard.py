"""Shard simulator: owns a group of Devices in memory and answers Command batches.

This is the stateful shell around the pure device model: it draws the (seeded) response
noise and faults, remembers which Idempotency Keys each Device has acted on (so an
at-least-once transport gives exactly-once effects), and produces Heartbeats.
`simulator/main.py` wraps it in NATS request/reply for compose; `transport/memory.py`
calls it directly for the in-process Scenario Runner.
"""

import random
import zlib
from collections import Counter, deque
from datetime import UTC, datetime, timedelta

from gridtwin.fleet.device import apply_command, ignored_ack, screen_command
from gridtwin.fleet.models import Ack, BatchReply, Command, DeviceState, Heartbeat, ShardReset

# Duplicate-commands scenario: besides delivering every batch twice, replay the previous
# batch before this one on this share of batches.
OLD_BATCH_REPLAY_RATE = 0.3
# Idempotency Key memory spans this many Market Intervals (the current one and the one
# before it, which a replayed old batch or a late retry can still reach).
RETAINED_INTERVALS = 2
RETAINED_SPAN = timedelta(minutes=15 * (RETAINED_INTERVALS - 1))


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
        self._shard_seed = 0
        self._partitioned: set[str] = set()  # Devices whose Commands and Heartbeats drop
        self._delayed: set[str] = set()  # Devices whose Heartbeats arrive late
        self._delay = timedelta(0)
        self._delay_queue: deque[Heartbeat] = deque()
        self._reset_memory()

    def _reset_memory(self) -> None:
        # Key memory covers the newest RETAINED_INTERVALS Market Intervals this shard has
        # seen, so a long run's memory stays flat. A Command from before that window is
        # answered `expired` and never acts, so it cannot act twice either.
        self._received: set[str] = set()  # keys delivered to this shard (retained window)
        self._acks: dict[str, Ack] = {}  # key -> the Device's one answer (applied or failed)
        self._effects: Counter[str] = Counter()  # key -> times a Device acted on it
        self._keys_by_interval: dict[datetime, set[str]] = {}
        self._newest: datetime | None = None  # newest Market Interval delivered
        self._clock: dict[str, datetime] = {}  # device -> latest interval it acted in
        self._seq: dict[tuple[str, datetime], int] = {}  # (device, interval) -> highest seq
        # (device, interval) -> MW delivered so far in that interval, across seqs
        self._interval_mw: dict[tuple[str, datetime], float] = {}
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
        self._shard_seed = shard_seed
        self._partitioned = set()
        self._delayed = set()
        self._delay_queue.clear()
        self._reset_memory()

    def set_duplicates(self, active: bool) -> None:
        """The duplicate-commands Chaos Scenario: deliver each batch twice, and sometimes
        replay the previous batch first."""
        self._duplicates = active

    @property
    def duplicates(self) -> bool:
        return self._duplicates

    def _pick(self, pct: float, salt: int) -> set[str]:
        """A seeded `pct` share of this shard's Devices: the same run, seed and pct always
        pick the same Devices."""
        ids = sorted(self._devices)
        count = round(pct * len(ids))
        return set(random.Random(self._shard_seed ^ salt).sample(ids, count)) if count else set()

    def set_partition(self, pct: float) -> None:
        """The device-partition Chaos Scenario: `pct` of Devices go dark. Their Commands are
        dropped (no Ack) and they send no Heartbeats until the partition clears (pct 0)."""
        self._partitioned = self._pick(pct, 0x9A27) if pct > 0 else set()

    @property
    def partitioned(self) -> set[str]:
        return set(self._partitioned)

    def set_telemetry_delay(self, delay_s: float, pct: float = 1.0) -> None:
        """The telemetry-delay Chaos Scenario: `pct` of Devices' Heartbeats reach telemetry
        `delay_s` late, keeping their original `sent_at`. delay_s 0 clears it; whatever
        was held back is released on the next `heartbeats` call."""
        if delay_s > 0 and pct > 0:
            self._delayed = self._pick(pct, 0xDE1A)
            self._delay = timedelta(seconds=delay_s)
        else:
            self._delayed = set()
            self._delay = timedelta(0)

    @property
    def delayed(self) -> set[str]:
        return set(self._delayed)

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
            if command.device_id in self._partitioned:
                continue  # never reaches the Device, so no Ack comes back
            if self._before_window(command.interval_start):
                acks.append(self._expired(command))
                continue
            self._advance(command.interval_start)
            key = command.idempotency_key
            if key in self._received:
                counts["duplicate_deliveries"] += 1
            self._received.add(key)
            self._keys_by_interval.setdefault(command.interval_start, set()).add(key)
            acks.append(self._act(command))
            if self._effects[key] > 1:
                counts["duplicate_effects"] += 1
        return acks

    def _before_window(self, interval_start: datetime) -> bool:
        return self._newest is not None and interval_start < self._newest - RETAINED_SPAN

    def _expired(self, command: Command) -> Ack:
        state = self._devices.get(command.device_id)
        if state is None or command.run_id != self._run_id:
            return self._act(command)  # the not-in-this-run `failed` Ack
        return ignored_ack(state, command, "expired")

    def _advance(self, interval_start: datetime) -> None:
        """A newer Market Interval arrived: forget keys older than the retained window."""
        if self._newest is not None and interval_start <= self._newest:
            return
        self._newest = interval_start
        cutoff = interval_start - RETAINED_SPAN
        for old in [t for t in self._keys_by_interval if t < cutoff]:
            for key in self._keys_by_interval.pop(old):
                self._received.discard(key)
                self._acks.pop(key, None)
                self._effects.pop(key, None)
        self._seq = {k: v for k, v in self._seq.items() if k[1] >= cutoff}
        self._interval_mw = {k: v for k, v in self._interval_mw.items() if k[1] >= cutoff}

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
        interval_key = (command.device_id, command.interval_start)
        already_mw = self._interval_mw.get(interval_key, 0.0)
        new_state, ack = apply_command(state, command, factor, faulted, already_mw)
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
        self._seq[interval_key] = command.seq
        self._interval_mw[interval_key] = already_mw + ack.delivered_mw
        return ack

    def heartbeats(self, now: datetime | None = None) -> list[Heartbeat]:
        """This period's Heartbeats as they reach telemetry: none from partitioned Devices,
        and a delayed Device's Heartbeat only once it is `delay` old."""
        sent_at = now or datetime.now(UTC)
        out = []
        for device_id, state in self._devices.items():
            if device_id in self._partitioned:
                continue
            beat = Heartbeat(
                run_id=self._run_id,
                state=state,
                power_mw=self._power_mw.get(device_id, 0.0),
                healthy=True,
                sent_at=sent_at,
            )
            if device_id in self._delayed:
                self._delay_queue.append(beat)
            else:
                out.append(beat)
        while self._delay_queue and (
            not self._delayed or self._delay_queue[0].sent_at <= sent_at - self._delay
        ):
            out.append(self._delay_queue.popleft())
        return out

    def snapshot(self) -> list[DeviceState]:
        return list(self._devices.values())
