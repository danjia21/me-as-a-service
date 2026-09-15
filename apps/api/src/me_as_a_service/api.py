"""Expose the HTTP API and apply operational request controls."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from os import getenv
from pathlib import Path
from secrets import compare_digest
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST

from .chat.types import MAX_MESSAGE_LENGTH, ChatEvent, ChatRequest
from .chat_workflow import build_chat_workflow
from .instance import load_instance_from_environment
from .operations.traffic import (
    ConcurrencyGate,
    PrivacyKeyHasher,
    QueueSaturated,
    RateLimitExceeded,
    RequestMetricsMiddleware,
    SlidingWindowRateLimiter,
    TrafficMonitor,
    resolve_client_address,
)
from .operations.usage_limits import UsageLimitExceeded

NDJSON_MEDIA_TYPE = "application/x-ndjson"
__all__ = [
    "MAX_MESSAGE_LENGTH",
    "app",
    "chat_workflow",
]

load_dotenv()


def _secret_from_environment(name: str) -> str | None:
    secret_file = getenv(f"{name}_FILE")
    if secret_file:
        value = Path(secret_file).read_text(encoding="utf-8").strip()
        if not value:
            raise RuntimeError(f"{name}_FILE points to an empty secret")
        return value
    return getenv(name) or None


instance = load_instance_from_environment()
chat_workflow = build_chat_workflow(instance)
privacy_key_hasher = PrivacyKeyHasher()
traffic_monitor = TrafficMonitor()
ip_rate_limiter = SlidingWindowRateLimiter(
    limit=int(getenv("MAAS_IP_RATE_LIMIT_REQUESTS", "30")),
    window_seconds=int(getenv("MAAS_RATE_LIMIT_WINDOW_SECONDS", "60")),
)
session_rate_limiter = SlidingWindowRateLimiter(
    limit=int(getenv("MAAS_SESSION_RATE_LIMIT_REQUESTS", "12")),
    window_seconds=int(getenv("MAAS_RATE_LIMIT_WINDOW_SECONDS", "60")),
)
inference_gate = ConcurrencyGate(
    max_active=int(getenv("MAAS_MAX_CONCURRENT_TURNS", "4")),
    max_queued=int(getenv("MAAS_MAX_QUEUED_TURNS", "8")),
    queue_timeout_seconds=float(getenv("MAAS_QUEUE_TIMEOUT_SECONDS", "15")),
)
proxy_shared_secret = getenv("MAAS_PROXY_SHARED_SECRET") or None
metrics_bearer_token = _secret_from_environment("MAAS_METRICS_BEARER_TOKEN")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    application.state.ready = False
    await chat_workflow.initialize()
    application.state.ready = True
    try:
        yield
    finally:
        application.state.ready = False
        await chat_workflow.shutdown()


app = FastAPI(
    title="Me-as-a-Service API",
    description="Evidence-grounded interview agent API.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(RequestMetricsMiddleware, monitor=traffic_monitor)


@app.get("/health/live", include_in_schema=False)
async def health_live() -> JSONResponse:
    return JSONResponse(
        content={"status": "ok"},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/health/ready", include_in_schema=False)
async def health_ready(request: Request) -> JSONResponse:
    if not getattr(request.app.state, "ready", False):
        return _unavailable_health_response()
    try:
        await chat_workflow.healthcheck()
    except Exception:
        return _unavailable_health_response()
    return JSONResponse(
        content={"status": "ok"},
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(UsageLimitExceeded)
async def usage_limit_exceeded(_: Request, error: UsageLimitExceeded) -> JSONResponse:
    traffic_monitor.observe_chat_outcome("usage_limited")
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": str(error)},
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded(_: Request, error: RateLimitExceeded) -> JSONResponse:
    traffic_monitor.observe_chat_outcome("rate_limited")
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": str(error)},
        headers={
            "Cache-Control": "no-store",
            "Retry-After": str(error.retry_after_seconds),
        },
    )


@app.exception_handler(QueueSaturated)
async def queue_saturated(_: Request, error: QueueSaturated) -> JSONResponse:
    traffic_monitor.observe_chat_outcome("queue_saturated")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(error)},
        headers={"Cache-Control": "no-store", "Retry-After": "5"},
    )


@app.post("/api/v1/chat", response_model=None)
async def chat(
    request: Request,
    payload: ChatRequest,
    accept: str | None = Header(default=None),
) -> JSONResponse | StreamingResponse:
    """Append one user turn and return JSON or provider-neutral NDJSON events."""
    client_address = resolve_client_address(request, proxy_shared_secret)
    visitor_key = privacy_key_hasher.digest("visitor", client_address)
    traffic_monitor.observe_chat_client(visitor_key)
    ip_rate_limiter.check(visitor_key)
    if payload.conversation_id is not None:
        session_rate_limiter.check(
            privacy_key_hasher.digest("conversation", str(payload.conversation_id))
        )

    lease = await inference_gate.acquire()
    stream_owns_lease = False
    try:
        conversation_id = payload.conversation_id
        if conversation_id is None:
            conversation_id = await chat_workflow.create_conversation()
            traffic_monitor.conversation_created()
        elif not await chat_workflow.conversation_exists(conversation_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation was not found. Start a new conversation.",
            )

        message_id = uuid4()
        headers = {"Cache-Control": "no-store"}
        if accept == NDJSON_MEDIA_TYPE:
            stream_owns_lease = True
            return StreamingResponse(
                _ndjson_events(
                    chat_workflow.stream_turn(
                        conversation_id=conversation_id,
                        message=payload.message,
                        message_id=message_id,
                    ),
                    lease,
                ),
                media_type=NDJSON_MEDIA_TYPE,
                headers=headers,
            )

        try:
            chat_response = await chat_workflow.complete_turn(
                conversation_id=conversation_id,
                message=payload.message,
                message_id=message_id,
            )
        except UsageLimitExceeded:
            raise
        except Exception:
            traffic_monitor.observe_chat_outcome("failed")
            raise
        else:
            traffic_monitor.observe_chat_outcome("completed")
        return JSONResponse(
            content=chat_response.model_dump(mode="json"),
            headers=headers,
        )
    finally:
        if not stream_owns_lease:
            await lease.release()


@app.get("/metrics", response_model=None)
async def metrics(
    authorization: str | None = Header(default=None),
) -> Response:
    expected_authorization = (
        f"Bearer {metrics_bearer_token}" if metrics_bearer_token else None
    )
    if expected_authorization and (
        authorization is None
        or not compare_digest(authorization, expected_authorization)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Metrics authentication is required.",
        )
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    persistence_ready = True
    try:
        await chat_workflow.healthcheck()
        daily_tokens = await chat_workflow.tokens_since(today)
    except Exception:
        persistence_ready = False
        daily_tokens = 0
    inference_active, inference_queued = await inference_gate.snapshot()
    return Response(
        content=traffic_monitor.render_prometheus(
            inference_active=inference_active,
            inference_queued=inference_queued,
            daily_tokens=daily_tokens,
            daily_token_budget=chat_workflow.daily_token_budget,
            persistence_ready=persistence_ready,
        ),
        headers={
            "Cache-Control": "no-store",
            "Content-Type": CONTENT_TYPE_LATEST,
        },
    )


def _unavailable_health_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "unavailable"},
        headers={"Cache-Control": "no-store"},
    )


async def _ndjson_events(
    events: AsyncIterator[ChatEvent],
    lease: AbstractAsyncContextManager[None],
) -> AsyncIterator[str]:
    async with lease:
        try:
            async for event in events:
                yield f"{event.model_dump_json(exclude_none=True)}\n"
        except UsageLimitExceeded as error:
            traffic_monitor.observe_chat_outcome("usage_limited")
            yield (
                ChatEvent(type="error", detail=str(error)).model_dump_json(
                    exclude_none=True
                )
                + "\n"
            )
        except Exception:
            traffic_monitor.observe_chat_outcome("failed")
            yield '{"type":"error","detail":"The response stream failed."}\n'
        except BaseException:
            traffic_monitor.observe_chat_outcome("cancelled")
            raise
        else:
            traffic_monitor.observe_chat_outcome("completed")
