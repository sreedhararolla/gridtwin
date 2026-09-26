"""Seam B: exactly-once effects on the Device side. A Device applies each Idempotency Key
at most once, and ignores expired and superseded Commands; the Command Ledger summary."""

from datetime import UTC, datetime, timedelta

from gridtwin.fleet.device import screen_command
from gridtwin.fleet.models import Command, DeviceState, ShardReset
from gridtwin.fleet.shard import ShardSimulator
from gridtwin.ledger.memory_repo import InMemoryLedgerRepo
from gridtwin.ledger.models import summarize_ledger

T0 = datetime(2026, 1, 28, 13, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=15)


def command(interval_start: datetime, seq: int = 1, device_id: str = "battery-0") -> Command:
    return Command(
        idempotency_key=f"run:{interval_start.isoformat()}:{device_id}:{seq}",
        run_id="run",
        interval_start=interval_start,
        device_id=device_id,
        seq=seq,
        setpoint_mw=0.005,
        expires_at=interval_start + timedelta(minutes=15),
    )


def shard(duplicates: bool = False) -> ShardSimulator:
    sim = ShardSimulator()
    sim.reset(
        ShardReset(
            run_id="run",
            shard_id="shard-0",
            devices=[
                DeviceState(
                    device_id=f"battery-{i}",
                    soc_pct=0.8,
                    energy_kwh=39.2,
                    max_power_kw=10.0,
                    round_trip_efficiency=0.9,
                    reserve_floor_pct=0.2,
                    shard_id="shard-0",
                )
                for i in range(2)
            ],
            response_noise_pct=0.0,
            fault_rate=0.0,
            seed=7,
        )
    )
    sim.set_duplicates(duplicates)
    return sim


def soc(sim: ShardSimulator, device_id: str = "battery-0") -> float:
    return next(d.soc_pct for d in sim.snapshot() if d.device_id == device_id)


def test_screen_command_verdicts():
    c = command(T1, seq=1)
    assert screen_command(c, already_answered=False, device_clock=None, latest_seq=None) == "apply"
    assert screen_command(c, already_answered=True, device_clock=T1, latest_seq=1) == "duplicate"
    # The Device already acted in a later interval: this one's expiry has passed.
    late = command(T0)
    assert screen_command(late, False, device_clock=T1, latest_seq=None) == "expired"
    # A Reallocation (seq 2) already acted in this interval: seq 1 is superseded.
    assert screen_command(c, False, device_clock=T1, latest_seq=2) == "superseded"


def test_device_applies_each_key_at_most_once():
    sim = shard()
    first = sim.handle_batch([command(T0)])
    soc_after_first = soc(sim)
    again = sim.handle_batch([command(T0)])
    assert soc(sim) == soc_after_first  # no second effect
    assert again.acks == first.acks  # the original Ack comes back
    assert again.duplicate_deliveries == 1
    assert again.duplicate_effects == 0


def test_device_ignores_expired_command():
    sim = shard()
    sim.handle_batch([command(T1)])
    before = soc(sim)
    reply = sim.handle_batch([command(T0)])  # arrives after the Device moved on to T1
    assert reply.acks[0].outcome == "expired"
    assert not reply.acks[0].applied
    assert reply.acks[0].delivered_mw == 0.0
    assert soc(sim) == before


def test_device_ignores_superseded_command():
    sim = shard()
    sim.handle_batch([command(T0, seq=2)])
    before = soc(sim)
    reply = sim.handle_batch([command(T0, seq=1)])
    assert reply.acks[0].outcome == "superseded"
    assert soc(sim) == before


def test_duplicate_mode_delivers_twice_with_no_second_effect():
    plain, dup = shard(), shard(duplicates=True)
    batches = [[command(t, device_id=d) for d in ("battery-0", "battery-1")] for t in (T0, T1)]
    for batch in batches:
        plain.handle_batch(batch)
    replies = [dup.handle_batch(batch) for batch in batches]
    assert sum(r.duplicate_deliveries for r in replies) >= 4  # every batch arrives twice
    assert sum(r.duplicate_effects for r in replies) == 0
    assert dup.snapshot() == plain.snapshot()  # same SoC as a clean delivery


def test_key_memory_stays_bounded_over_a_long_run():
    sim = shard()
    for k in range(200):
        t = T0 + timedelta(minutes=15 * k)
        sim.handle_batch([command(t, device_id=d) for d in ("battery-0", "battery-1")])
    assert len(sim._acks) == 4  # two intervals x two Devices, not 400
    assert len(sim._received) == 4


def test_key_older_than_the_window_is_expired_and_never_acts_twice():
    sim = shard()
    first = command(T0)
    sim.handle_batch([first])
    # The Device sits out T1 (nothing for it), the fleet moves on to T2.
    sim.handle_batch([command(T0 + timedelta(minutes=30), device_id="battery-1")])
    before = soc(sim)
    reply = sim.handle_batch([first])  # a very late redelivery of an applied key
    assert reply.acks[0].outcome == "expired"
    assert not reply.acks[0].applied
    assert soc(sim) == before
    assert reply.duplicate_effects == 0


def test_reset_forgets_keys_of_the_previous_run():
    sim = shard()
    sim.handle_batch([command(T0)])
    sim = shard()
    assert sim.handle_batch([command(T0)]).duplicate_deliveries == 0


def test_reissued_key_never_creates_a_second_ledger_row():
    repo = InMemoryLedgerRepo()
    c = command(T0)
    repo.upsert_commands([c])
    repo.upsert_commands([c, command(T0, device_id="battery-1")])
    repo.upsert_commands([c])
    assert repo.command_counts("run") == (2, 0)


def test_ledger_summary_counts_by_status():
    rows = [
        (T0, "acked", 0.005),
        (T0, "acked", 0.005),
        (T0, "expired", 0.0),
        (T0, "failed", 0.0),
        (T0, "issued", 0.0),
        (T1, "acked", 0.01),
    ]
    first, second = summarize_ledger(rows)  # type: ignore[arg-type]
    assert (first.issued, first.acked, first.expired, first.failed, first.unacked) == (
        5,
        2,
        1,
        1,
        1,
    )
    assert first.delivered_mw == 0.01
    assert second.interval_start == T1 and second.acked == 1
