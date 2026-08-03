import asyncio
from datetime import UTC, datetime, timedelta

from me_as_a_service.chat.usage import InMemoryUsageLedger


def test_in_memory_usage_ledger_records_atomic_daily_totals() -> None:
    async def exercise() -> None:
        ledger = InMemoryUsageLedger()
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        await asyncio.gather(
            *(ledger.record(today, 10, 5) for _ in range(20)),
            ledger.record(yesterday, 100, 50),
        )

        assert await ledger.tokens_since(today) == 300
        assert await ledger.tokens_since(yesterday) == 450

    asyncio.run(exercise())
