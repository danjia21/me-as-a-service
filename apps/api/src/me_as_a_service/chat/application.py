"""Coordinate one conversation turn within the chat domain.

This module combines instance-specific prompts, bounded conversation memory,
hosted-model calls, response persistence, and model tracing. It accepts optional
retrieved documents from its caller but does not retrieve knowledge, enforce
usage limits, record aggregate usage, or define HTTP behavior.
"""

from collections.abc import AsyncIterator
from json import dumps
from typing import Self
from uuid import UUID, uuid4

from langsmith import trace

from ..instance import Instance
from ..knowledge import Document
from .memory import ChatMemory
from .model import OpenAICompatibleChatModel, chat_model_from_environment
from .prompts import PromptTemplates, load_prompts
from .storage import conversation_store_from_environment
from .tracing import LangSmithTracing, tracing_from_environment
from .types import (
    ChatEvent,
    ConversationContext,
    ConversationType,
    MessageClassification,
    StoredMessage,
)

CLASSIFY_AND_REWRITE_TRACE_NAME = "classify_and_rewrite_message (step 1/2)"
CHAT_RESPONSE_TRACE_NAME = "generate_chat_response (step 2/2)"

_GENERATION_PROMPTS = {
    ConversationType.EVIDENCE_REQUIRED: "answer-evidence-required",
    ConversationType.CONVERSATION: "answer-conversation",
    ConversationType.IRRELEVANT: "answer-irrelevant",
    ConversationType.DISCUSS_IN_PERSON: "answer-discuss-in-person",
    ConversationType.INAPPROPRIATE: "answer-inappropriate",
}
_CURRENT_MESSAGE_ONLY_TYPES = frozenset(
    {
        ConversationType.IRRELEVANT,
        ConversationType.DISCUSS_IN_PERSON,
        ConversationType.INAPPROPRIATE,
    }
)


def _serialize_documents(documents: tuple[Document, ...]) -> str:
    """Serialize retrieved documents for the untrusted-context prompt slot."""

    candidates: list[dict[str, str]] = []
    for document in documents:
        candidate = {
            "subject": document.subject,
            "body": document.body,
        }
        if document.url is not None:
            candidate["url"] = document.url
        candidates.append(candidate)
    return dumps(candidates, ensure_ascii=False, indent=2)


class Chat:
    """Coordinate prompts, conversation memory, and hosted-model calls with tracing.

    Knowledge retrieval and operational policy are intentionally owned by the
    caller. This service classifies a prepared turn, optionally rewrites it as a
    search query, selects a response policy, and generates a response from optional
    caller-supplied documents.
    """

    def __init__(
        self,
        *,
        model: OpenAICompatibleChatModel,
        memory: ChatMemory,
        prompts: PromptTemplates,
        tracing: LangSmithTracing,
        instance: Instance,
    ) -> None:
        """Bind chat-owned dependencies and render instance-specific prompts."""

        self._memory = memory
        self._model = model
        self._prompts = prompts
        self._tracing = tracing
        self._display_name = instance.display_name
        self._public_profile = instance.public_profile
        self._usage_by_message: dict[UUID, tuple[int, int]] = {}

    @classmethod
    def from_environment(cls, *, instance: Instance) -> Self:
        """Construct the production chat service from environment settings."""

        prompts = load_prompts()
        model = chat_model_from_environment()
        tracing = tracing_from_environment(
            instance_id=instance.directory.name,
            model=model.model,
            prompt_revision=prompts.revision,
        )
        return cls(
            model=tracing.wrap_chat_model(model),
            memory=ChatMemory(conversation_store_from_environment()),
            prompts=prompts,
            tracing=tracing,
            instance=instance,
        )

    async def initialize(self) -> None:
        """Initialize conversation persistence owned by chat memory."""

        await self._memory.initialize()

    async def healthcheck(self) -> None:
        """Verify that conversation persistence is available."""

        await self._memory.healthcheck()

    async def shutdown(self) -> None:
        """Close the hosted-model client and flush pending model traces."""

        try:
            await self._model.close()
            await self._tracing.flush()
        finally:
            self._usage_by_message.clear()

    async def create_conversation(self) -> UUID:
        """Create and return an empty persisted conversation."""

        return await self._memory.store.create()

    async def conversation_exists(self, conversation_id: UUID) -> bool:
        """Return whether an unexpired conversation exists in the store."""

        return await self._memory.store.exists(conversation_id)

    async def clear(self) -> None:
        """Remove all conversation state from the configured store."""

        await self._memory.store.clear()
        self._usage_by_message.clear()

    def pop_usage(self, message_id: UUID) -> tuple[int, int] | None:
        """Return and remove completed model usage for ``message_id``, if present."""

        return self._usage_by_message.pop(message_id, None)

    async def assemble_context(
        self, conversation_id: UUID, message: str
    ) -> ConversationContext:
        """Return bounded history with ``message`` appended as the latest item."""

        current_message = StoredMessage(id=uuid4(), role="user", content=message)
        return await self._memory.assemble_context(
            conversation_id,
            current_message,
        )

    async def classify_and_rewrite_message(
        self, context: ConversationContext
    ) -> MessageClassification:
        """Classify the latest message and rewrite evidence-required queries."""

        system_prompt = self._prompts.render(
            "classify-and-rewrite-message",
            {"display_name": self._display_name},
        )

        with self._tracing.activate():
            async with trace(
                CLASSIFY_AND_REWRITE_TRACE_NAME,
                inputs={
                    "message": context.messages[-1].content,
                    "history": context.messages[:-1],
                    "system_prompt": system_prompt,
                },
            ) as run:
                classification = await self._model.classify_and_rewrite_message(
                    context,
                    system_prompt,
                )
                run.end(outputs=classification.model_dump(mode="json"))
                return classification

    async def stream_response(
        self,
        *,
        conversation_id: UUID,
        message_id: UUID,
        context: ConversationContext,
        classification: MessageClassification,
        documents: tuple[Document, ...] = (),
    ) -> AsyncIterator[ChatEvent]:
        """Generate, stream, and persist a response with optional documents.

        Documents are rendered only for the current model request. Raw visitor
        text remains the conversational history used by later turns. The stream
        must provide final usage before the completed turn is persisted.
        """

        if not context.messages or context.messages[-1].role != "user":
            raise ValueError("context must end with the current user message")

        if (
            classification.conversation_type is not ConversationType.EVIDENCE_REQUIRED
            and documents
        ):
            raise ValueError(
                "only evidence-required messages may include retrieved documents"
            )

        conversation_type = classification.conversation_type
        retrieval_query = classification.retrieval_query

        # If the message is evidence-required but no documents were retrieved, downgrade
        # the classification to a discuss-in-person response. This avoids generating
        # a response that claims to be evidence-backed when no evidence is available.
        if (
            classification.conversation_type is ConversationType.EVIDENCE_REQUIRED
            and not documents
        ):
            conversation_type = ConversationType.DISCUSS_IN_PERSON
            retrieval_query = None

        stored_user_message = context.messages[-1]
        generation_message = stored_user_message.content

        if conversation_type is ConversationType.EVIDENCE_REQUIRED:
            assert retrieval_query is not None
            generation_message = self._prompts.render(
                "answer-with-retrieved-context",
                {
                    "question": stored_user_message.content,
                    "retrieval_query": retrieval_query,
                    "candidates": _serialize_documents(documents),
                },
            )
        generation_user_message = StoredMessage(
            id=stored_user_message.id,
            role="user",
            content=generation_message,
        )
        generation_messages = (
            (generation_user_message,)
            if conversation_type in _CURRENT_MESSAGE_ONLY_TYPES
            else (*context.messages[:-1], generation_user_message)
        )
        generation_context = ConversationContext(
            messages=generation_messages,
            completed_turns=context.completed_turns,
        )

        generation_system_prompt = self._prompts.render(
            _GENERATION_PROMPTS[conversation_type],
            {
                "display_name": self._display_name,
                "public_profile": self._public_profile or "null",
            },
        )
        with self._tracing.activate():
            async with trace(
                CHAT_RESPONSE_TRACE_NAME,
                inputs={
                    "message": stored_user_message.content,
                    "history": generation_context.messages[:-1],
                    "conversation_type": conversation_type.value,
                    "retrieval_query": retrieval_query,
                    "documents": documents,
                    "system_prompt": generation_system_prompt,
                },
            ) as run:
                yield ChatEvent(
                    type="message_start",
                    conversation_id=conversation_id,
                    message_id=message_id,
                )
                content_parts: list[str] = []
                input_tokens: int | None = None
                output_tokens: int | None = None
                async for (
                    delta,
                    input_tokens,
                    output_tokens,
                ) in self._model.stream_response(
                    generation_context,
                    generation_system_prompt,
                ):
                    if delta is not None:
                        content_parts.append(delta)
                        yield ChatEvent(type="text_delta", delta=delta)
                if input_tokens is None or output_tokens is None:
                    raise RuntimeError(
                        "OpenAI stream ended without completion metadata"
                    )

                content = "".join(content_parts)
                run.end(
                    outputs={
                        "content": content,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    }
                )
                self._usage_by_message[message_id] = (input_tokens, output_tokens)
                await self._memory.append_turn(
                    conversation_id,
                    stored_user_message,
                    StoredMessage(id=message_id, role="assistant", content=content),
                )
                try:
                    yield ChatEvent(type="message_end")
                finally:
                    self._usage_by_message.pop(message_id, None)
