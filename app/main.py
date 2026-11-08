"""A small checkout service that exposes the numbers an SLO is built on.

Every request is counted by route and status code, and timed in a histogram whose
buckets include the 300 ms latency target. A chaos switch can make the service fail
or slow down on purpose, so alerts and the deploy gate can be tested for real.
"""

from __future__ import annotations

import asyncio
import hmac
import math
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

# The 0.3 s bucket matters: the latency SLO counts requests faster than 300 ms.
LATENCY_BUCKETS = (0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5)

# Requests to these paths are not user traffic, so they stay out of the SLO numbers.
UNTRACKED = {"/metrics", "/healthz"}


class ChaosSettings(BaseModel):
    """How badly the service should misbehave. Zero for both means healthy."""

    error_rate: float = Field(
        0.0, ge=0.0, le=1.0, description="Share of checkout requests that fail with 500"
    )
    latency_ms: int = Field(
        0, ge=0, le=5000, description="Extra delay added to each checkout request"
    )
    duration_s: int = Field(
        0,
        ge=0,
        le=3600,
        description="Switch chaos off by itself after this many seconds (0 = never)",
    )


class ChaosStatus(ChaosSettings):
    """The chaos settings plus how long they have left, if they expire."""

    expires_in_s: int | None = None


@dataclass
class State:
    chaos: ChaosSettings
    rng: random.Random
    clock: Callable[[], float]
    expires_at: float | None = None

    def current(self) -> ChaosSettings:
        """The chaos in force now. Expired chaos turns itself off, so a forgotten
        experiment cannot keep burning the error budget."""
        if self.expires_at is not None and self.clock() >= self.expires_at:
            self.chaos = ChaosSettings()
            self.expires_at = None
        return self.chaos

    def status(self) -> ChaosStatus:
        chaos = self.current()
        left = None
        if self.expires_at is not None:
            left = max(0, math.ceil(self.expires_at - self.clock()))
        return ChaosStatus(**chaos.model_dump(), expires_in_s=left)


def create_app(
    chaos_token: str | None = None,
    seed: int | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """Build the app. Tests pass a token, a seed, and a clock; production reads
    CHAOS_TOKEN."""
    token = (
        chaos_token if chaos_token is not None else os.environ.get("CHAOS_TOKEN", "")
    )
    registry = CollectorRegistry()
    requests_total = Counter(
        "http_requests_total",
        "Requests handled, by route, method, and status code.",
        ["route", "method", "code"],
        registry=registry,
    )
    duration = Histogram(
        "http_request_duration_seconds",
        "Time to handle a request, by route.",
        ["route", "method"],
        buckets=LATENCY_BUCKETS,
        registry=registry,
    )
    state = State(ChaosSettings(), random.Random(seed), clock)  # noqa: S311 (chaos, not crypto)
    app = FastAPI(title="Burn Rate checkout service", version="0.1.0")

    @app.middleware("http")
    async def record(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        # Label by route template, not raw URL, so label values stay a small fixed set.
        path = getattr(route, "path", "unmatched")
        if path not in UNTRACKED:
            requests_total.labels(path, request.method, str(response.status_code)).inc()
            duration.labels(path, request.method).observe(time.perf_counter() - start)
        return response

    def require_token(authorization: str = Header(default="")) -> None:
        # Without a token configured, chaos cannot be changed at all.
        expected = f"Bearer {token}"
        if not token or not hmac.compare_digest(
            authorization.encode(), expected.encode()
        ):
            raise HTTPException(
                status_code=401, detail="A valid chaos token is required"
            )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/checkout")
    async def checkout() -> dict[str, str]:
        chaos = state.current()
        if chaos.latency_ms:
            await asyncio.sleep(chaos.latency_ms / 1000)
        if chaos.error_rate and state.rng.random() < chaos.error_rate:
            raise HTTPException(status_code=500, detail="Injected failure")
        return {"status": "paid"}

    @app.get("/chaos")
    async def get_chaos() -> ChaosStatus:
        return state.status()

    @app.put("/chaos", dependencies=[Depends(require_token)])
    async def set_chaos(settings: ChaosSettings) -> ChaosStatus:
        state.chaos = settings
        state.expires_at = (
            state.clock() + settings.duration_s if settings.duration_s else None
        )
        return state.status()

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
