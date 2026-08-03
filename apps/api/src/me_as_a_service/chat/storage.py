from __future__ import annotations

import os
from datetime import timedelta
from typing import Protocol
from uuid import UUID, uuid4

import psycopg

from me_as_a_service.chat.types import StoredMessage

DEFAULT_CONVERSATION_RETENTION_HOURS = 24


class ConversationStore(Protocol):
    async def initialize(self) -> None: ...

    async def healthcheck(self) -> None: ...

    async def create(self) -> UUID: ...

    async def exists(self, conversation_id: UUID) -> bool: ...

    async def history(self, conversation_id: UUID) -> tuple[StoredMessage, ...]: ...

    async def append_turn(
        self,
        conversation_id: UUID,
        user_message: StoredMessage,
        assistant_message: StoredMessage,
    ) -> None: ...

    async def clear(self) -> None: ...


class InMemoryConversationStore:
    """Process-local conversation state for tests and database-free development."""

    def __init__(self) -> None:
        self._conversations: dict[UUID, tuple[StoredMessage, ...]] = {}

    async def initialize(self) -> None:
        return None

    async def healthcheck(self) -> None:
        return None

    async def create(self) -> UUID:
        conversation_id = uuid4()
        self._conversations[conversation_id] = ()
        return conversation_id

    async def exists(self, conversation_id: UUID) -> bool:
        return conversation_id in self._conversations

    async def history(self, conversation_id: UUID) -> tuple[StoredMessage, ...]:
        return self._conversations[conversation_id]

    async def append_turn(
        self,
        conversation_id: UUID,
        user_message: StoredMessage,
        assistant_message: StoredMessage,
    ) -> None:
        self._conversations[conversation_id] = (
            *self._conversations[conversation_id],
            user_message,
            assistant_message,
        )

    async def clear(self) -> None:
        self._conversations.clear()


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    ordinal bigint NOT NULL,
    id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    generation_content text,
    PRIMARY KEY (conversation_id, ordinal),
    UNIQUE (id)
);

ALTER TABLE conversation_messages
    ADD COLUMN IF NOT EXISTS generation_content text;

CREATE INDEX IF NOT EXISTS conversations_expires_at_idx
    ON conversations (expires_at);
"""


class PostgresConversationStore:
    """Durable session-scoped conversations backed by PostgreSQL."""

    def __init__(
        self,
        database_url: str,
        *,
        retention: timedelta = timedelta(hours=24),
    ) -> None:
        if not database_url:
            raise ValueError("database_url must not be empty")
        if retention <= timedelta(0):
            raise ValueError("retention must be positive")
        self._database_url = database_url
        self._retention = retention

    async def initialize(self) -> None:
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            await conn.execute(_SCHEMA_SQL)
            await conn.execute("DELETE FROM conversations WHERE expires_at <= now()")

    async def healthcheck(self) -> None:
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            await conn.execute("SELECT 1")

    async def create(self) -> UUID:
        conversation_id = uuid4()
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            await conn.execute(
                """
                INSERT INTO conversations (id, expires_at)
                VALUES (%s, now() + %s)
                """,
                (conversation_id, self._retention),
            )
        return conversation_id

    async def exists(self, conversation_id: UUID) -> bool:
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            cursor = await conn.execute(
                """
                SELECT 1
                FROM conversations
                WHERE id = %s AND expires_at > now()
                """,
                (conversation_id,),
            )
            return await cursor.fetchone() is not None

    async def history(self, conversation_id: UUID) -> tuple[StoredMessage, ...]:
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            message_cursor = await conn.execute(
                """
                SELECT message.id, message.role, message.content,
                    message.generation_content
                FROM conversation_messages AS message
                JOIN conversations AS conversation
                    ON conversation.id = message.conversation_id
                WHERE message.conversation_id = %s
                    AND conversation.expires_at > now()
                ORDER BY ordinal
                """,
                (conversation_id,),
            )
            rows = await message_cursor.fetchall()

        return tuple(
            StoredMessage(
                id=row[0],
                role=row[1],
                content=row[2],
                generation_content=row[3],
            )
            for row in rows
        )

    async def append_turn(
        self,
        conversation_id: UUID,
        user_message: StoredMessage,
        assistant_message: StoredMessage,
    ) -> None:
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            await conn.execute(
                "SELECT id FROM conversations WHERE id = %s FOR UPDATE",
                (conversation_id,),
            )
            cursor = await conn.execute(
                """
                SELECT COALESCE(MAX(ordinal), -1)
                FROM conversation_messages
                WHERE conversation_id = %s
                """,
                (conversation_id,),
            )
            row = await cursor.fetchone()
            next_ordinal = int(row[0]) + 1 if row is not None else 0
            async with conn.cursor() as insert_cursor:
                await insert_cursor.executemany(
                    """
                    INSERT INTO conversation_messages
                        (conversation_id, ordinal, id, role, content,
                            generation_content)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            conversation_id,
                            next_ordinal,
                            user_message.id,
                            user_message.role,
                            user_message.content,
                            user_message.generation_content,
                        ),
                        (
                            conversation_id,
                            next_ordinal + 1,
                            assistant_message.id,
                            assistant_message.role,
                            assistant_message.content,
                            assistant_message.generation_content,
                        ),
                    ],
                )
            await conn.execute(
                """
                UPDATE conversations
                SET updated_at = now(), expires_at = now() + %s
                WHERE id = %s
                """,
                (self._retention, conversation_id),
            )

    async def clear(self) -> None:
        async with await psycopg.AsyncConnection.connect(self._database_url) as conn:
            await conn.execute("TRUNCATE conversations CASCADE")


def conversation_store_from_environment() -> ConversationStore:
    store_name = os.getenv("MAAS_CONVERSATION_STORE", "memory")
    if store_name == "memory":
        return InMemoryConversationStore()
    if store_name == "postgres":
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL is required when MAAS_CONVERSATION_STORE=postgres"
            )
        retention_hours = int(
            os.getenv(
                "MAAS_CONVERSATION_RETENTION_HOURS",
                str(DEFAULT_CONVERSATION_RETENTION_HOURS),
            )
        )
        return PostgresConversationStore(
            database_url,
            retention=timedelta(hours=retention_hours),
        )
    raise RuntimeError(f"Unsupported MAAS_CONVERSATION_STORE: {store_name}")
