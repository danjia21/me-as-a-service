"""Track aggregate model-token usage without conversational content."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime
from typing import Protocol, cast

import psycopg


class UsageLedger(Protocol):
    async def initialize(self) -> None: ...

    async def healthcheck(self) -> None: ...

    async def tokens_since(self, utc_boundary: datetime) -> int: ...

    async def record(
        self,
        completed_at: datetime,
        input_tokens: int,
        output_tokens: int,
    ) -> None: ...

    async def clear(self) -> None: ...


def _validate_usage(
    completed_at: datetime, input_tokens: int, output_tokens: int
) -> date:
    if completed_at.tzinfo is None:
        raise ValueError("completed_at must be timezone-aware")
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts must not be negative")
    return completed_at.astimezone(UTC).date()


class InMemoryUsageLedger:
    """Process-local daily aggregates for tests and database-free development."""

    def __init__(self) -> None:
        self._daily_tokens: dict[date, int] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        return None

    async def healthcheck(self) -> None:
        return None

    async def tokens_since(self, utc_boundary: datetime) -> int:
        if utc_boundary.tzinfo is None:
            raise ValueError("utc_boundary must be timezone-aware")
        boundary_date = utc_boundary.astimezone(UTC).date()
        async with self._lock:
            return sum(
                tokens
                for usage_date, tokens in self._daily_tokens.items()
                if usage_date >= boundary_date
            )

    async def record(
        self,
        completed_at: datetime,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        usage_date = _validate_usage(completed_at, input_tokens, output_tokens)
        async with self._lock:
            self._daily_tokens[usage_date] = (
                self._daily_tokens.get(usage_date, 0) + input_tokens + output_tokens
            )

    async def clear(self) -> None:
        async with self._lock:
            self._daily_tokens.clear()


_USAGE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS daily_model_usage (
    usage_date date PRIMARY KEY,
    token_count bigint NOT NULL CHECK (token_count >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""


class PostgresUsageLedger:
    """Durable atomic daily token aggregates without conversational content."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url must not be empty")
        self._database_url = database_url

    async def initialize(self) -> None:
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            await conn.execute(_USAGE_SCHEMA_SQL)

    async def healthcheck(self) -> None:
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            await conn.execute("SELECT 1")

    async def tokens_since(self, utc_boundary: datetime) -> int:
        if utc_boundary.tzinfo is None:
            raise ValueError("utc_boundary must be timezone-aware")
        boundary_date = utc_boundary.astimezone(UTC).date()
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            cursor = await conn.execute(
                """
                SELECT COALESCE(SUM(token_count), 0)
                FROM daily_model_usage
                WHERE usage_date >= %s
                """,
                (boundary_date,),
            )
            row = await cursor.fetchone()
        return cast(int, row[0]) if row is not None else 0

    async def record(
        self,
        completed_at: datetime,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        usage_date = _validate_usage(completed_at, input_tokens, output_tokens)
        token_count = input_tokens + output_tokens
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            await conn.execute(
                """
                INSERT INTO daily_model_usage (usage_date, token_count)
                VALUES (%s, %s)
                ON CONFLICT (usage_date) DO UPDATE
                SET
                    token_count = daily_model_usage.token_count
                        + EXCLUDED.token_count,
                    updated_at = now()
                """,
                (usage_date, token_count),
            )

    async def clear(self) -> None:
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            await conn.execute("TRUNCATE daily_model_usage")


def usage_ledger_from_environment() -> UsageLedger:
    store_name = os.getenv("MAAS_CONVERSATION_STORE", "memory")
    if store_name == "memory":
        return InMemoryUsageLedger()
    if store_name == "postgres":
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is required when MAAS_CONVERSATION_STORE=postgres"
            )
        return PostgresUsageLedger(database_url)
    raise RuntimeError(f"Unsupported MAAS_CONVERSATION_STORE: {store_name}")
