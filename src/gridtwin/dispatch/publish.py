"""Publish Interval Results for live consumers: the API's SSE stream to the dashboard.

The Scenario Runner (Seam A) doesn't need this - it reads the ledger's Interval Results
directly once the run completes - so it uses `NullPublisher`.
"""

from __future__ import annotations

from typing import Protocol

import nats

from gridtwin.ledger.models import IntervalResult


class ResultPublisher(Protocol):
    async def publish(self, result: IntervalResult) -> None: ...


class NullPublisher:
    async def publish(self, result: IntervalResult) -> None:
        return None


def result_subject(run_id: str) -> str:
    return f"interval.result.{run_id}"


class NatsResultPublisher:
    def __init__(self, nc) -> None:
        self._nc = nc

    @classmethod
    async def connect(cls, url: str) -> NatsResultPublisher:
        nc = await nats.connect(url)
        return cls(nc)

    async def publish(self, result: IntervalResult) -> None:
        await self._nc.publish(result_subject(result.run_id), result.model_dump_json().encode())

    async def close(self) -> None:
        await self._nc.close()
