import asyncio

import pytest
from prometheus_client.parser import text_string_to_metric_families
from starlette.requests import Request

from me_as_a_service.traffic import (
    ConcurrencyGate,
    PrivacyKeyHasher,
    QueueSaturated,
    RateLimitExceeded,
    SlidingWindowRateLimiter,
    TrafficMonitor,
    resolve_client_address,
)


def test_sliding_window_rate_limiter_expires_old_requests() -> None:
    now = [100.0]
    limiter = SlidingWindowRateLimiter(
        limit=2,
        window_seconds=10,
        clock=lambda: now[0],
    )

    limiter.check("visitor")
    limiter.check("visitor")
    with pytest.raises(RateLimitExceeded) as error:
        limiter.check("visitor")

    assert error.value.retry_after_seconds == 10
    now[0] = 111.0
    limiter.check("visitor")


def test_concurrency_gate_bounds_the_waiting_queue() -> None:
    async def exercise() -> None:
        gate = ConcurrencyGate(
            max_active=1,
            max_queued=1,
            queue_timeout_seconds=1,
        )
        first = await gate.acquire()
        second_task = asyncio.create_task(gate.acquire())

        for _ in range(10):
            if await gate.snapshot() == (1, 1):
                break
            await asyncio.sleep(0)

        with pytest.raises(QueueSaturated):
            await gate.acquire()

        await first.release()
        second = await second_task
        assert await gate.snapshot() == (1, 0)
        await second.release()
        assert await gate.snapshot() == (0, 0)

    asyncio.run(exercise())


def test_traffic_metrics_do_not_expose_the_visitor_address() -> None:
    address = "203.0.113.42"
    visitor_key = PrivacyKeyHasher(key=b"x" * 32).digest("visitor", address)
    monitor = TrafficMonitor()
    monitor.observe_chat_client(visitor_key)

    rendered = monitor.render_prometheus(
        inference_active=0,
        inference_queued=0,
        daily_tokens=12,
        daily_token_budget=100,
        persistence_ready=True,
    )

    assert monitor.registry.get_sample_value("maas_unique_chat_clients_today") == 1
    assert monitor.registry.get_sample_value("maas_model_tokens_today") == 12
    parsed_names = {
        family.name
        for family in text_string_to_metric_families(rendered.decode("utf-8"))
    }
    assert "maas_http_requests" in parsed_names
    assert address.encode() not in rendered
    assert visitor_key.encode() not in rendered


def test_forwarded_client_address_requires_the_shared_proxy_secret() -> None:
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"x-maas-client-ip", b"203.0.113.42"),
                (b"x-maas-proxy-secret", b"correct-secret"),
            ],
            "client": ("10.0.0.8", 1234),
        }
    )

    assert resolve_client_address(request, "correct-secret") == "203.0.113.42"
    assert resolve_client_address(request, "wrong-secret") == "10.0.0.8"
