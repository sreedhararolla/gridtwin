"""Pure staleness rule: a Device is stale after N missed Heartbeats (docs/SPEC.md Defaults)."""


def heartbeat_period_seconds(telemetry_period_replay_seconds: float, replay_speed: float) -> float:
    """Wall seconds between Heartbeats: one per replay-minute is 1 s wall at 60x."""
    return telemetry_period_replay_seconds / replay_speed


def stale_after_seconds(
    telemetry_period_replay_seconds: float,
    replay_speed: float,
    missed_heartbeats: int,
    flush_seconds: float,
) -> float:
    """Wall age past which a Device's latest Heartbeat means it is stale. The ingester's
    flush interval is added so batching alone can never make a live Device look stale."""
    period = heartbeat_period_seconds(telemetry_period_replay_seconds, replay_speed)
    return missed_heartbeats * period + flush_seconds
