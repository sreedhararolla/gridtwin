"""Single settings module. Every variable here must have a matching entry in .env.example."""

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # The one shard ticket 02 dispatches to. Ticket 04 spreads many shards across
    # simulator replicas; `shard_ids` (plural) is which of those a simulator hosts.
    shard_id: str = "shard-0"
    shard_ids: str = ""
    device_count: int = 10
    device_energy_kwh: float = 39.2
    device_max_power_kw: float = 10.0
    device_round_trip_efficiency: float = 0.9
    reserve_floor_pct: float = 0.20
    initial_soc_pct: float = 0.50

    naive_discharge_threshold_usd: float = 90.0
    naive_charge_threshold_usd: float = 20.0

    dispatch_timeout_seconds: float = 5.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def shard_id_list(self) -> list[str]:
        return [shard.strip() for shard in self.shard_ids.split(",") if shard.strip()]

    @property
    def device_ids(self) -> list[str]:
        return [f"battery-{i}" for i in range(self.device_count)]


settings = Settings()
