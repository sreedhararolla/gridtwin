"""Single settings module. Every variable here must have a matching entry in .env.example."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from gridtwin.fleet.models import FleetConfig
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

    dispatch_timeout_seconds: float = 5.0
    tolerance_pct: float = 0.05

    # Chaos controller (ticket 05). The Docker socket mount is for local demos only.
    chaos_controller_url: str = "http://localhost:8001"
    api_url: str = "http://localhost:8000"  # where `make chaos` reaches the API
    scenarios_dir: str = "scenarios"
    docker_socket_path: str = "/var/run/docker.sock"
    compose_project: str = "gridtwin"
    chaos_restart_delay_seconds: float = 20.0
    chaos_dispatch_wait_seconds: float = 30.0
    chaos_recovery_slo_seconds: float = 15.0

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
