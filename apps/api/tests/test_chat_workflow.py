import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from me_as_a_service.chat.application import Chat
from me_as_a_service.chat.memory import ChatMemory
from me_as_a_service.chat.model import OpenAICompatibleChatModel
from me_as_a_service.chat.prompts import load_prompts
from me_as_a_service.chat.storage import InMemoryConversationStore
from me_as_a_service.chat.tracing import LangSmithTracing
from me_as_a_service.chat.types import (
    ConversationContext,
    ConversationType,
    MessageClassification,
    StoredMessage,
)
from me_as_a_service.chat_workflow import ChatWorkflow
from me_as_a_service.instance import Instance
from me_as_a_service.knowledge import Knowledge
from me_as_a_service.operations.token_usage import InMemoryUsageLedger


class RecordingModel(OpenAICompatibleChatModel):
    model = "recording-model"

    def __init__(self, classification: MessageClassification) -> None:
        self.classification = classification
        self.response_context: ConversationContext | None = None
        self.response_system_prompt: str | None = None

    async def classify_and_rewrite_message(
        self, context: ConversationContext, system_prompt: str
    ) -> MessageClassification:
        return self.classification

    async def stream_response(
        self, context: ConversationContext, system_prompt: str
    ) -> AsyncIterator[tuple[str | None, int | None, int | None]]:
        self.response_context = context
        self.response_system_prompt = system_prompt
        yield "Response", None, None
        yield None, 10, 5

    async def close(self) -> None:
        return None


class FailingConversationStore(InMemoryConversationStore):
    async def append_turn(
        self,
        conversation_id: UUID,
        user_message: StoredMessage,
        assistant_message: StoredMessage,
    ) -> None:
        raise RuntimeError("persistence failed")


def build_workflow(
    tmp_path: Path,
    *,
    classification: MessageClassification,
    fail_persistence: bool = False,
) -> tuple[ChatWorkflow, Chat, RecordingModel, InMemoryUsageLedger]:
    directory = tmp_path / "profile"
    (directory / "index").mkdir(parents=True)
    (directory / "instance.yaml").write_text(
        "display_name: Test Profile\n",
        encoding="utf-8",
    )
    (directory / "index" / "records.json").write_text(
        json.dumps(
            [
                {
                    "id": "standalone-result",
                    "subject": "Standalone result",
                    "body": "A fact from the current knowledge index.",
                }
            ]
        ),
        encoding="utf-8",
    )
    instance = Instance(directory)
    model = RecordingModel(classification)
    store = (
        FailingConversationStore() if fail_persistence else InMemoryConversationStore()
    )
    chat = Chat(
        model=model,
        memory=ChatMemory(store),
        prompts=load_prompts(),
        tracing=LangSmithTracing(False, None, "test", (), {}),
        instance=instance,
    )
    ledger = InMemoryUsageLedger()
    return (
        ChatWorkflow(chat=chat, knowledge=Knowledge(instance), usage_ledger=ledger),
        chat,
        model,
        ledger,
    )


def test_workflow_retrieves_current_documents_and_records_usage(tmp_path: Path) -> None:
    async def exercise() -> None:
        workflow, chat, model, ledger = build_workflow(
            tmp_path,
            classification=MessageClassification(
                conversation_type=ConversationType.EVIDENCE_REQUIRED,
                retrieval_query="standalone",
            ),
        )
        conversation_id = await workflow.create_conversation()
        message_id = uuid4()

        response = await workflow.complete_turn(
            conversation_id=conversation_id,
            message="What is the result?",
            message_id=message_id,
        )

        assert response.content == "Response"
        assert model.response_context is not None
        assert (
            "A fact from the current knowledge index."
            in model.response_context.messages[-1].content
        )
        assert await ledger.tokens_since(datetime.now(UTC)) == 15
        assert chat.pop_usage(message_id) is None

    asyncio.run(exercise())


def test_workflow_conversation_route_skips_knowledge(tmp_path: Path) -> None:
    async def exercise() -> None:
        workflow, _, model, _ = build_workflow(
            tmp_path,
            classification=MessageClassification(
                conversation_type=ConversationType.CONVERSATION,
                retrieval_query=None,
            ),
        )
        conversation_id = await workflow.create_conversation()

        await workflow.complete_turn(
            conversation_id=conversation_id,
            message="Hello",
            message_id=uuid4(),
        )

        assert model.response_context is not None
        assert model.response_context.messages[-1].content == "Hello"
        assert model.response_system_prompt == load_prompts().render(
            "answer-conversation",
            {"display_name": "Test Profile"},
        )

    asyncio.run(exercise())


def test_workflow_falls_back_when_evidence_retrieval_is_empty(tmp_path: Path) -> None:
    async def exercise() -> None:
        workflow, _, model, _ = build_workflow(
            tmp_path,
            classification=MessageClassification(
                conversation_type=ConversationType.EVIDENCE_REQUIRED,
                retrieval_query="absentterm",
            ),
        )
        conversation_id = await workflow.create_conversation()

        await workflow.complete_turn(
            conversation_id=conversation_id,
            message="What did you think about it?",
            message_id=uuid4(),
        )

        assert model.response_context is not None
        assert model.response_context.messages[-1].content == (
            "What did you think about it?"
        )
        assert model.response_system_prompt == load_prompts().render(
            "answer-discuss-in-person",
            {"display_name": "Test Profile", "public_profile": "null"},
        )

    asyncio.run(exercise())


def test_workflow_records_and_clears_usage_when_persistence_fails(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        workflow, chat, _, ledger = build_workflow(
            tmp_path,
            classification=MessageClassification(
                conversation_type=ConversationType.CONVERSATION,
                retrieval_query=None,
            ),
            fail_persistence=True,
        )
        conversation_id = await workflow.create_conversation()
        message_id = uuid4()

        with pytest.raises(RuntimeError, match="persistence failed"):
            await workflow.complete_turn(
                conversation_id=conversation_id,
                message="Hello",
                message_id=message_id,
            )

        assert await ledger.tokens_since(datetime.now(UTC)) == 15
        assert chat.pop_usage(message_id) is None

    asyncio.run(exercise())
