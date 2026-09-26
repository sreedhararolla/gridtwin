"""Single settings module. Every variable here must have a matching entry in .env.example."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from gridtwin.dispatch.ladder import LadderConfig
from gridtwin.fleet.models import FleetConfig
from gridtwin.fleet.reallocate import ReallocationConfig
from gridtwin.planner.lp import LpConfig
from gridtwin.replay.breaker import BreakerConfig
from gridtwin.replay.feed import ValidatorConfig
from gridtwin.telemetry.staleness import stale_after_seconds


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_dsn: str = "postgresql://gridtwin:gridtwin@localhost:5432/gridtwin"
    nats_url: str = "nats://localhost:4222"
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"

    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    worker_replicas: int = 2
    simulator_replicas: int = 2
    heartbeat_interval_seconds: float = 1.0
    heartbeat_stale_seconds: float = 5.0

    service_name: str = ""
    instance_id: str = ""

    task_queue: str = "gridtwin-dispatch"
    settlement_point: str = "LZ_HOUSTON"
    fixture_path: str = "data/fixtures/rtm_spp_lz_houston_2025-12-10.csv"
    replay_speed: float = 60.0

    # The fleet: DEVICE_COUNT devices in SHARD_COUNT shards (shard-0..N-1), spread across
    # simulator replicas; `shard_ids` is which of those shards one simulator hosts.
    shard_ids: str = ""
    shard_count: int = 20
    device_count: int = 2000
    device_energy_kwh: float = 39.2
    device_max_power_kw: float = 10.0
    device_round_trip_efficiency: float = 0.9
    reserve_floor_pct: float = 0.20
    initial_soc_pct: float = 0.50
    device_response_noise_pct: float = 0.02
    device_fault_rate: float = 0.001
    fleet_seed: int = 42

    # Telemetry: one Heartbeat per replay-minute; stale after N missed Heartbeats.
    telemetry_period_replay_seconds: float = 60.0
    telemetry_stale_heartbeats: int = 3
    telemetry_flush_seconds: float = 1.0

    naive_discharge_threshold_usd: float = 90.0
    naive_charge_threshold_usd: float = 20.0
    # LP planner (ticket 09): the Strategy a Replay Run uses unless the Live tab picks one,
    # the rolling horizon, and the degradation cost per MWh discharged.
    strategy: str = "naive"
    planner_horizon_intervals: int = 96
    planner_degradation_usd_per_mwh: float = 10.0

    dispatch_timeout_seconds: float = 5.0
    tolerance_pct: float = 0.05
    # Reallocation (ticket 07): at most N seq+1 rounds, started only in the first
    # REALLOCATION_DEADLINE_PCT of the interval's wall budget; REALLOCATION_RESERVE_PCT of
    # Fleet State headroom is held back from the planner so a Shortfall has somewhere to go.
    reallocation_max_rounds: int = 2
    reallocation_deadline_pct: float = 0.5
    reallocation_reserve_pct: float = 0.10
    # Degradation Ladder (ticket 08). A cached plan stays usable for N intervals, the last
    # valid price for the Safe Rule for M; N clean intervals take the ladder back to L0.
    # The feed's circuit breaker opens after K failures and probes after a cooldown.
    ladder_cached_plan_intervals: int = 2
    ladder_safe_rule_max_age_intervals: int = 8
    ladder_recover_after_clean: int = 2
    feed_breaker_failures: int = 3
    feed_breaker_cooldown_intervals: int = 2
    feed_outlier_z: float = 100.0
    feed_outlier_mad_floor_usd: float = 50.0

    # Chaos controller (ticket 05). The Docker socket mount is for local demos only.
    chaos_controller_url: str = "http://localhost:8001"
    api_url: str = "http://localhost:8000"  # where `make chaos` reaches the API
    scenarios_dir: str = "scenarios"
    docker_socket_path: str = "/var/run/docker.sock"
    compose_project: str = "gridtwin"
    chaos_restart_delay_seconds: float = 20.0
    chaos_dispatch_wait_seconds: float = 30.0
    chaos_recovery_slo_seconds: float = 15.0
    # Device partition / telemetry delay (ticket 07): the share of Devices hit, and how
    # late delayed Heartbeats arrive (wall seconds; > the stale threshold makes them stale).
    chaos_partition_pct: float = 0.20
    chaos_telemetry_delay_seconds: float = 10.0
    chaos_telemetry_delay_pct: float = 0.30

    # Ticket 03 appends the market data ingest settings below this line.
    marketdata_cache_dir: str = "data/cache"
    marketdata_start_date: str = "2025-12-05"
    marketdata_include_pre_rtcb: bool = False
    ercot_throttle_per_minute: int = 30
    ercot_api_username: str = ""
    ercot_api_password: str = ""
    ercot_api_subscription_key: str = ""

    @property
    def ercot_api_configured(self) -> bool:
        return bool(
            self.ercot_api_username and self.ercot_api_password and self.ercot_api_subscription_key
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def shard_id_list(self) -> list[str]:
        return [shard.strip() for shard in self.shard_ids.split(",") if shard.strip()]

    @property
    def stale_after_seconds(self) -> float:
        return stale_after_seconds(
            self.telemetry_period_replay_seconds,
            self.replay_speed,
            self.telemetry_stale_heartbeats,
            self.telemetry_flush_seconds,
        )

    def lp_config(self) -> LpConfig:
        return LpConfig(
            degradation_usd_per_mwh=self.planner_degradation_usd_per_mwh,
            horizon_intervals=self.planner_horizon_intervals,
        )

    def reallocation_config(self) -> ReallocationConfig:
        return ReallocationConfig(
            tolerance_pct=self.tolerance_pct,
            max_rounds=self.reallocation_max_rounds,
            deadline_pct=self.reallocation_deadline_pct,
            reserve_pct=self.reallocation_reserve_pct,
        )

    def ladder_config(self) -> LadderConfig:
        return LadderConfig(
            cached_plan_intervals=self.ladder_cached_plan_intervals,
            safe_rule_max_age_intervals=self.ladder_safe_rule_max_age_intervals,
            recover_after_clean=self.ladder_recover_after_clean,
            breaker=BreakerConfig(
                failure_threshold=self.feed_breaker_failures,
                cooldown_intervals=self.feed_breaker_cooldown_intervals,
            ),
            validator=ValidatorConfig(
                outlier_z=self.feed_outlier_z,
                outlier_mad_floor_usd=self.feed_outlier_mad_floor_usd,
            ),
        )

    def fleet_config(self) -> FleetConfig:
        return FleetConfig(
            device_count=self.device_count,
            shard_count=self.shard_count,
            energy_kwh=self.device_energy_kwh,
            max_power_kw=self.device_max_power_kw,
            round_trip_efficiency=self.device_round_trip_efficiency,
            reserve_floor_pct=self.reserve_floor_pct,
            initial_soc_pct=self.initial_soc_pct,
            response_noise_pct=self.device_response_noise_pct,
            fault_rate=self.device_fault_rate,
            seed=self.fleet_seed,
        )


settings = Settings()
