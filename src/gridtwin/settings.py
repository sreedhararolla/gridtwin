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

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
