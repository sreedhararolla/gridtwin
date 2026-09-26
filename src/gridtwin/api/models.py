"""Pydantic models at the API boundary. FastAPI's OpenAPI schema (generated from
these) is the single source of truth for the dashboard's TypeScript types."""

from pydantic import BaseModel


class DependencyStatus(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class ServiceCount(BaseModel):
    name: str
    ready: int
    total: int


class HealthResponse(BaseModel):
    ok: bool
    dependencies: list[DependencyStatus]
    services: list[ServiceCount]
