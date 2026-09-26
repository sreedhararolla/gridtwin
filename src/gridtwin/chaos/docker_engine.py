"""Docker Engine API over the mounted socket: kill and start compose services.

LOCAL DEMO ONLY. Mounting /var/run/docker.sock gives the chaos controller root-equivalent
control of the host's Docker daemon; never deploy it anywhere else (README)."""

import json

import httpx

API_VERSION = "v1.41"


class ServiceNotFound(Exception):
    pass


class DockerEngine:
    def __init__(self, socket_path: str, compose_project: str) -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket_path),
            base_url=f"http://docker/{API_VERSION}",
            timeout=10.0,
        )
        self._project = compose_project

    async def _container_id(self, service: str) -> str:
        labels = [
            f"com.docker.compose.project={self._project}",
            f"com.docker.compose.service={service}",
        ]
        res = await self._client.get(
            "/containers/json",
            params={"all": "true", "filters": json.dumps({"label": labels})},
        )
        res.raise_for_status()
        containers = res.json()
        if not containers:
            raise ServiceNotFound(f"no container for compose service {service!r}")
        return containers[0]["Id"]

    async def kill(self, service: str) -> None:
        """SIGKILL: the worker gets no chance to finish or hand back its activities."""
        res = await self._client.post(f"/containers/{await self._container_id(service)}/kill")
        res.raise_for_status()

    async def start(self, service: str) -> None:
        res = await self._client.post(f"/containers/{await self._container_id(service)}/start")
        # 304 = already running.
        if res.status_code != 304:
            res.raise_for_status()

    async def is_running(self, service: str) -> bool:
        res = await self._client.get(f"/containers/{await self._container_id(service)}/json")
        res.raise_for_status()
        return bool(res.json()["State"]["Running"])
