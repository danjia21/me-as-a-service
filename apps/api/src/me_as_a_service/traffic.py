import asyncio
import hashlib
import ipaddress
import logging
import secrets
from collections import deque
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from math import ceil
from threading import Lock
from time import monotonic, perf_counter
from types import TracebackType

from fastapi import Request
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_REQUEST_DURATION_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_CHAT_OUTCOMES = frozenset(
    {
        "cancelled",
        "completed",
        "failed",
        "queue_saturated",
        "rate_limited",
        "usage_limited",
    }
)
_logger = logging.getLogger("me_as_a_service.traffic")


class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Too many requests. Please wait a moment and try again.")
        self.retry_after_seconds = retry_after_seconds


class QueueSaturated(RuntimeError):
    pass


class PrivacyKeyHasher:
    """Create process-local identifiers without retaining visitor addresses."""

    def __init__(self, key: bytes | None = None) -> None:
        self._key = key or secrets.token_bytes(32)

    def digest(self, namespace: str, value: str) -> str:
        return hashlib.blake2b(
            f"{namespace}:{value}".encode(),
            key=self._key,
            digest_size=16,
        ).hexdigest()


class SlidingWindowRateLimiter:
    """Bound requests per privacy-safe key using process-local state."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("rate limit and window must be positive")
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._requests: dict[str, deque[float]] = {}
        self._last_cleanup = clock()
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = self._clock()
        cutoff = now - self._window_seconds
        with self._lock:
            if now - self._last_cleanup >= self._window_seconds:
                expired_keys = [
                    request_key
                    for request_key, request_times in self._requests.items()
                    if not request_times or request_times[-1] <= cutoff
                ]
                for request_key in expired_keys:
                    del self._requests[request_key]
                self._last_cleanup = now
            timestamps = self._requests.setdefault(key, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self._limit:
                retry_after = max(1, ceil(timestamps[0] + self._window_seconds - now))
                raise RateLimitExceeded(retry_after)
            timestamps.append(now)

    def clear(self) -> None:
        with self._lock:
            self._requests.clear()
            self._last_cleanup = self._clock()


class _ConcurrencyLease(AbstractAsyncContextManager[None]):
    def __init__(self, gate: "ConcurrencyGate") -> None:
        self._gate = gate
        self._released = False

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.release()

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._gate.release()


class ConcurrencyGate:
    """Limit active turns and reject excess work beyond a bounded queue."""

    def __init__(
        self,
        *,
        max_active: int,
        max_queued: int,
        queue_timeout_seconds: float,
    ) -> None:
        if max_active < 1 or max_queued < 0 or queue_timeout_seconds <= 0:
            raise ValueError("concurrency limits must be positive")
        self._max_active = max_active
        self._max_queued = max_queued
        self._queue_timeout_seconds = queue_timeout_seconds
        self._active = 0
        self._queued = 0
        self._condition = asyncio.Condition()

    async def acquire(self) -> _ConcurrencyLease:
        async with self._condition:
            if self._active >= self._max_active:
                if self._queued >= self._max_queued:
                    raise QueueSaturated(
                        "The service is busy. Please wait a moment and try again."
                    )
                self._queued += 1
                try:
                    await asyncio.wait_for(
                        self._condition.wait_for(
                            lambda: self._active < self._max_active
                        ),
                        timeout=self._queue_timeout_seconds,
                    )
                except TimeoutError as error:
                    raise QueueSaturated(
                        "The service is busy. Please wait a moment and try again."
                    ) from error
                finally:
                    self._queued -= 1
            self._active += 1
        return _ConcurrencyLease(self)

    async def release(self) -> None:
        async with self._condition:
            if self._active < 1:
                raise RuntimeError("concurrency lease released without an active turn")
            self._active -= 1
            self._condition.notify(1)

    async def snapshot(self) -> tuple[int, int]:
        async with self._condition:
            return self._active, self._queued


class TrafficMonitor:
    """Collect bounded aggregate metrics in an isolated Prometheus registry."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._visitor_day = datetime.now(UTC).date()
        self._visitor_keys: set[str] = set()
        self._create_collectors()

    @property
    def registry(self) -> CollectorRegistry:
        return self._registry

    def _create_collectors(self) -> None:
        self._registry = CollectorRegistry()
        self._http_requests = Counter(
            "maas_http_requests_total",
            "Completed HTTP requests.",
            ("method", "path", "status"),
            registry=self._registry,
        )
        self._active_requests = Gauge(
            "maas_http_requests_active",
            "HTTP requests currently active.",
            registry=self._registry,
        )
        self._request_duration = Histogram(
            "maas_http_request_duration_seconds",
            "HTTP request duration.",
            ("method", "path"),
            buckets=_REQUEST_DURATION_BUCKETS,
            registry=self._registry,
        )
        self._chat_outcomes = Counter(
            "maas_chat_outcomes_total",
            "Chat request outcomes.",
            ("outcome",),
            registry=self._registry,
        )
        self._conversations_created = Counter(
            "maas_conversations_created_total",
            "Conversations created.",
            registry=self._registry,
        )
        self._unique_chat_clients = Gauge(
            "maas_unique_chat_clients_today",
            "Approximate process-local daily chat clients.",
            registry=self._registry,
        )
        self._inference_active = Gauge(
            "maas_inference_active",
            "Active chat turns.",
            registry=self._registry,
        )
        self._inference_queued = Gauge(
            "maas_inference_queued",
            "Queued chat turns.",
            registry=self._registry,
        )
        self._model_tokens_today = Gauge(
            "maas_model_tokens_today",
            "Completed generation tokens today.",
            registry=self._registry,
        )
        self._model_daily_token_budget = Gauge(
            "maas_model_daily_token_budget",
            "Configured daily token budget.",
            registry=self._registry,
        )
        self._persistence_ready = Gauge(
            "maas_persistence_ready",
            "Whether required application persistence is reachable.",
            registry=self._registry,
        )

    def request_started(self) -> None:
        self._active_requests.inc()

    def request_finished(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        self._active_requests.dec()
        self._http_requests.labels(
            method=method,
            path=path,
            status=str(status_code),
        ).inc()
        self._request_duration.labels(method=method, path=path).observe(
            duration_seconds
        )

    def observe_chat_client(self, visitor_key: str) -> None:
        today = datetime.now(UTC).date()
        with self._lock:
            if today != self._visitor_day:
                self._visitor_day = today
                self._visitor_keys.clear()
            self._visitor_keys.add(visitor_key)
            self._unique_chat_clients.set(len(self._visitor_keys))

    def observe_chat_outcome(self, outcome: str) -> None:
        if outcome not in _CHAT_OUTCOMES:
            raise ValueError(f"unsupported chat outcome: {outcome}")
        self._chat_outcomes.labels(outcome=outcome).inc()
        _logger.info("chat_outcome", extra={"outcome": outcome})

    def conversation_created(self) -> None:
        self._conversations_created.inc()

    def clear(self) -> None:
        with self._lock:
            self._visitor_day = datetime.now(UTC).date()
            self._visitor_keys.clear()
            self._create_collectors()

    def render_prometheus(
        self,
        *,
        inference_active: int,
        inference_queued: int,
        daily_tokens: int,
        daily_token_budget: int,
        persistence_ready: bool,
    ) -> bytes:
        self._inference_active.set(inference_active)
        self._inference_queued.set(inference_queued)
        self._model_tokens_today.set(daily_tokens)
        self._model_daily_token_budget.set(daily_token_budget)
        self._persistence_ready.set(int(persistence_ready))
        return generate_latest(self._registry)


class RequestMetricsMiddleware:
    def __init__(self, app: ASGIApp, monitor: TrafficMonitor) -> None:
        self._app = app
        self._monitor = monitor

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        started_at = perf_counter()
        status_code = 500
        self._monitor.request_started()

        async def observe_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self._app(scope, receive, observe_status)
        finally:
            duration_seconds = perf_counter() - started_at
            self._monitor.request_finished(
                method=scope["method"],
                path=_metric_path(scope["path"]),
                status_code=status_code,
                duration_seconds=duration_seconds,
            )
            _logger.info(
                "http_request",
                extra={
                    "method": scope["method"],
                    "path": _metric_path(scope["path"]),
                    "status": status_code,
                    "duration_ms": round(duration_seconds * 1_000, 3),
                },
            )


def resolve_client_address(request: Request, proxy_shared_secret: str | None) -> str:
    if proxy_shared_secret:
        supplied_secret = request.headers.get("x-maas-proxy-secret")
        forwarded_address = request.headers.get("x-maas-client-ip")
        if (
            supplied_secret
            and forwarded_address
            and secrets.compare_digest(supplied_secret, proxy_shared_secret)
        ):
            try:
                return ipaddress.ip_address(forwarded_address).compressed
            except ValueError:
                pass
    if request.client is None:
        return "unknown"
    return request.client.host


def _metric_path(path: str) -> str:
    if path in {
        "/api/v1/chat",
        "/health/live",
        "/health/ready",
        "/metrics",
    }:
        return path
    return "unmatched"
