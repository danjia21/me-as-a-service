import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Self
from uuid import UUID, uuid4

import pytest

from me_as_a_service.chat import application as chat_application
from me_as_a_service.chat.application import Chat
from me_as_a_service.chat.memory import DEFAULT_CONTEXT_CHARACTER_LIMIT, ChatMemory
from me_as_a_service.chat.model import OpenAICompatibleChatModel
from me_as_a_service.chat.prompts import load_prompts
from me_as_a_service.chat.storage import InMemoryConversationStore
from me_as_a_service.chat.tracing import LangSmithTracing
from me_as_a_service.chat.types import (
    MAX_PAST_TURNS,
    ConversationContext,
    ConversationType,
    MessageClassification,
    StoredMessage,
)
from me_as_a_service.instance import Instance
from me_as_a_service.knowledge import Document


class RecordingModel(OpenAICompatibleChatModel):
    model = "recording-model"

    def __init__(self) -> None:
        self.classification_context: ConversationContext | None = None
        self.classification_system_prompt: str | None = None
        self.response_context: ConversationContext | None = None
        self.response_system_prompt: str | None = None

    async def classify_and_rewrite_message(
        self, context: ConversationContext, system_prompt: str
    ) -> MessageClassification:
        self.classification_context = context
        self.classification_system_prompt = system_prompt
        return MessageClassification(
            conversation_type=ConversationType.EVIDENCE_REQUIRED,
            retrieval_query="standalone query",
        )

    async def stream_response(
        self, context: ConversationContext, system_prompt: str
    ) -> AsyncIterator[tuple[str | None, int | None, int | None]]:
        self.response_context = context
        self.response_system_prompt = system_prompt
        yield "Response", None, None
        yield None, 10, 5

    async def close(self) -> None:
        return None


class CountingMemory(ChatMemory):
    def __init__(self, store: InMemoryConversationStore) -> None:
        super().__init__(store)
        self.assemble_calls = 0

    async def assemble_context(
        self,
        conversation_id: UUID,
        current_message: StoredMessage,
        *,
        past_turn_limit: int = MAX_PAST_TURNS,
        character_limit: int = DEFAULT_CONTEXT_CHARACTER_LIMIT,
    ) -> ConversationContext:
        self.assemble_calls += 1
        return await super().assemble_context(
            conversation_id,
            current_message,
            past_turn_limit=past_turn_limit,
            character_limit=character_limit,
        )


def build_instance(
    tmp_path: Path,
    *,
    display_name: str = "Test Profile",
    public_profile: str | None = None,
) -> Instance:
    directory = tmp_path / "profile"
    (directory / "index").mkdir(parents=True)
    links = (
        f"links:\n  public_profile: {public_profile}\n"
        if public_profile is not None
        else ""
    )
    (directory / "instance.yaml").write_text(
        f"display_name: {display_name}\n{links}",
        encoding="utf-8",
    )
    (directory / "index" / "records.json").write_text("[]", encoding="utf-8")
    return Instance(directory)


def test_one_assembled_context_drives_classification_generation_and_persistence(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        memory = CountingMemory(store)
        model = RecordingModel()
        chat = Chat(
            model=model,
            memory=memory,
            prompts=load_prompts(),
            tracing=LangSmithTracing(False, None, "test", (), {}),
            instance=build_instance(tmp_path),
        )
        conversation_id = await chat.create_conversation()
        context = await chat.assemble_context(conversation_id, "What happened next?")

        classification = await chat.classify_and_rewrite_message(context)
        events = [
            event
            async for event in chat.stream_response(
                conversation_id=conversation_id,
                message_id=uuid4(),
                context=context,
                classification=classification,
                documents=(
                    Document(
                        id="source-one",
                        subject="Project outcome",
                        body="The documented outcome.",
                        url="https://example.com/project",
                    ),
                ),
            )
        ]

        assert events
        assert memory.assemble_calls == 1
        assert model.classification_context is context
        assert model.response_context is not None
        assert model.response_context.completed_turns == context.completed_turns
        assert model.response_context.messages[-1].id == context.messages[-1].id
        generation_message = model.response_context.messages[-1].content
        assert "The documented outcome." in generation_message
        assert '"subject": "Project outcome"' in generation_message
        assert '"url": "https://example.com/project"' in generation_message
        assert "source-one" not in generation_message
        history = await store.history(conversation_id)
        assert history[0] == context.messages[-1]
        assert history[0].content == "What happened next?"

    asyncio.run(exercise())


def test_chat_uses_display_name_from_current_instance_manifest(tmp_path: Path) -> None:
    async def exercise() -> None:
        instance = build_instance(tmp_path, display_name="Ada Example")
        model = RecordingModel()
        chat = Chat(
            model=model,
            memory=ChatMemory(InMemoryConversationStore()),
            prompts=load_prompts(),
            tracing=LangSmithTracing(False, None, "test", (), {}),
            instance=instance,
        )
        conversation_id = await chat.create_conversation()
        context = await chat.assemble_context(conversation_id, "Hello")

        classification = await chat.classify_and_rewrite_message(context)
        _ = [
            event
            async for event in chat.stream_response(
                conversation_id=conversation_id,
                message_id=uuid4(),
                context=context,
                classification=classification,
            )
        ]

        assert model.classification_system_prompt is not None
        assert "Ada Example" in model.classification_system_prompt
        assert "Profile-specific vocabulary" not in model.classification_system_prompt
        assert model.response_system_prompt is not None
        assert "Ada Example" in model.response_system_prompt

    asyncio.run(exercise())


def test_chat_traces_the_two_model_stages_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace_names: list[str] = []

    class RecordingTrace:
        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        def end(self, **_: object) -> None:
            return None

    def record_trace(name: str, **_: object) -> RecordingTrace:
        trace_names.append(name)
        return RecordingTrace()

    monkeypatch.setattr(chat_application, "trace", record_trace)

    async def exercise() -> None:
        chat = Chat(
            model=RecordingModel(),
            memory=ChatMemory(InMemoryConversationStore()),
            prompts=load_prompts(),
            tracing=LangSmithTracing(False, None, "test", (), {}),
            instance=build_instance(tmp_path),
        )
        conversation_id = await chat.create_conversation()
        context = await chat.assemble_context(conversation_id, "Hello")

        classification = await chat.classify_and_rewrite_message(context)
        _ = [
            event
            async for event in chat.stream_response(
                conversation_id=conversation_id,
                message_id=uuid4(),
                context=context,
                classification=classification,
            )
        ]

    asyncio.run(exercise())

    assert trace_names == [
        "classify_and_rewrite_message (step 1/2)",
        "generate_chat_response (step 2/2)",
    ]


@pytest.mark.parametrize(
    ("conversation_type", "prompt_name", "uses_history"),
    [
        (ConversationType.EVIDENCE_REQUIRED, "answer-evidence-required", True),
        (ConversationType.CONVERSATION, "answer-conversation", True),
        (ConversationType.IRRELEVANT, "answer-irrelevant", False),
        (ConversationType.DISCUSS_IN_PERSON, "answer-discuss-in-person", False),
        (ConversationType.INAPPROPRIATE, "answer-inappropriate", False),
    ],
)
def test_chat_selects_route_prompt_and_history(
    tmp_path: Path,
    conversation_type: ConversationType,
    prompt_name: str,
    uses_history: bool,
) -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        model = RecordingModel()
        prompts = load_prompts()
        chat = Chat(
            model=model,
            memory=ChatMemory(store),
            prompts=prompts,
            tracing=LangSmithTracing(False, None, "test", (), {}),
            instance=build_instance(tmp_path),
        )
        conversation_id = await chat.create_conversation()
        await store.append_turn(
            conversation_id,
            StoredMessage(id=uuid4(), role="user", content="Earlier question"),
            StoredMessage(id=uuid4(), role="assistant", content="Earlier answer"),
        )
        context = await chat.assemble_context(conversation_id, "Current message")
        classification = MessageClassification(
            conversation_type=conversation_type,
            retrieval_query=(
                "standalone query"
                if conversation_type is ConversationType.EVIDENCE_REQUIRED
                else None
            ),
        )
        documents = (
            (
                Document(
                    id="source-one",
                    subject="Relevant subject",
                    body="Relevant evidence.",
                ),
            )
            if conversation_type is ConversationType.EVIDENCE_REQUIRED
            else ()
        )

        _ = [
            event
            async for event in chat.stream_response(
                conversation_id=conversation_id,
                message_id=uuid4(),
                context=context,
                classification=classification,
                documents=documents,
            )
        ]

        assert model.response_system_prompt == prompts.render(
            prompt_name,
            {"display_name": "Test Profile", "public_profile": "null"},
        )
        assert model.response_context is not None
        expected_message_count = 3 if uses_history else 1
        assert len(model.response_context.messages) == expected_message_count
        if conversation_type is ConversationType.EVIDENCE_REQUIRED:
            assert "Relevant evidence." in model.response_context.messages[-1].content
        else:
            assert model.response_context.messages[-1].content == "Current message"

    asyncio.run(exercise())


def test_discuss_in_person_prompt_receives_configured_public_profile(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        profile_url = "https://www.linkedin.com/in/ada-example/"
        model = RecordingModel()
        chat = Chat(
            model=model,
            memory=ChatMemory(InMemoryConversationStore()),
            prompts=load_prompts(),
            tracing=LangSmithTracing(False, None, "test", (), {}),
            instance=build_instance(tmp_path, public_profile=profile_url),
        )
        conversation_id = await chat.create_conversation()
        context = await chat.assemble_context(
            conversation_id,
            "What kind of role would you consider next?",
        )

        _ = [
            event
            async for event in chat.stream_response(
                conversation_id=conversation_id,
                message_id=uuid4(),
                context=context,
                classification=MessageClassification(
                    conversation_type=ConversationType.DISCUSS_IN_PERSON,
                    retrieval_query=None,
                ),
            )
        ]

        assert model.response_system_prompt is not None
        assert f"Configured public profile: {profile_url}." in (
            model.response_system_prompt
        )

    asyncio.run(exercise())


def test_chat_rejects_missing_display_name(tmp_path: Path) -> None:
    instance = build_instance(tmp_path)
    instance.manifest_path.write_text("welcome_message: Hello\n", encoding="utf-8")
    (instance.index_path).write_text(json.dumps([]), encoding="utf-8")
    reloaded_instance = Instance(instance.directory)

    with pytest.raises(ValueError, match="display_name"):
        Chat(
            model=RecordingModel(),
            memory=ChatMemory(InMemoryConversationStore()),
            prompts=load_prompts(),
            tracing=LangSmithTracing(False, None, "test", (), {}),
            instance=reloaded_instance,
        )
