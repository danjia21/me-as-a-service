import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from me_as_a_service.chat.storage import (
    InMemoryConversationStore,
    PostgresConversationStore,
    conversation_store_from_environment,
)
from me_as_a_service.chat.types import StoredMessage
from me_as_a_service.chat.usage import (
    InMemoryUsageLedger,
    PostgresUsageLedger,
    usage_ledger_from_environment,
)


def make_turn(index: int) -> tuple[StoredMessage, StoredMessage]:
    return (
        StoredMessage(
            id=uuid4(),
            role="user",
            content=f"question {index}",
            generation_content=f"evidence {index}\n\nUser question:\nquestion {index}",
        ),
        StoredMessage(
            id=uuid4(),
            role="assistant",
            content=f"answer {index}",
        ),
    )


def test_in_memory_store_retains_the_complete_session_history() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        for index in range(7):
            await store.append_turn(conversation_id, *make_turn(index))

        history = await store.history(conversation_id)
        assert len(history) == 14
        assert history[0].content == "question 0"
        assert history[0].generation_content == (
            "evidence 0\n\nUser question:\nquestion 0"
        )
        assert history[-1].content == "answer 6"

    asyncio.run(exercise())


def test_conversation_store_factory_defaults_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAAS_CONVERSATION_STORE", raising=False)

    assert isinstance(conversation_store_from_environment(), InMemoryConversationStore)
    assert isinstance(usage_ledger_from_environment(), InMemoryUsageLedger)


def test_conversation_store_factory_requires_a_postgres_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAAS_CONVERSATION_STORE", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        conversation_store_from_environment()
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        usage_ledger_from_environment()


def test_postgres_store_factories_share_the_configured_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAAS_CONVERSATION_STORE", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://database.test/maas")

    assert isinstance(conversation_store_from_environment(), PostgresConversationStore)
    assert isinstance(usage_ledger_from_environment(), PostgresUsageLedger)


@pytest.mark.skipif(
    "MAAS_TEST_DATABASE_URL" not in os.environ,
    reason="MAAS_TEST_DATABASE_URL is not configured",
)
def test_postgres_store_survives_store_recreation() -> None:
    async def exercise() -> None:
        database_url = os.environ["MAAS_TEST_DATABASE_URL"]
        first_store = PostgresConversationStore(
            database_url, retention=timedelta(hours=1)
        )
        await first_store.initialize()
        await first_store.clear()
        conversation_id = await first_store.create()
        user_message, assistant_message = make_turn(1)
        await first_store.append_turn(conversation_id, user_message, assistant_message)

        recreated_store = PostgresConversationStore(database_url)
        history = await recreated_store.history(conversation_id)

        assert await recreated_store.exists(conversation_id)
        assert history == (user_message, assistant_message)

        usage_ledger = PostgresUsageLedger(database_url)
        await usage_ledger.initialize()
        await usage_ledger.clear()
        await asyncio.gather(
            *(usage_ledger.record(datetime.now(UTC), 20, 10) for _ in range(20))
        )

        recreated_usage_ledger = PostgresUsageLedger(database_url)
        assert (
            await recreated_usage_ledger.tokens_since(datetime.min.replace(tzinfo=UTC))
            == 600
        )

    asyncio.run(exercise())
