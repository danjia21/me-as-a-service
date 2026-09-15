"""Coordinate chat, knowledge retrieval, and operational usage policy."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

from .chat import (
    Chat,
    ChatEvent,
    ChatResponse,
)
from .instance import Instance
from .knowledge import Knowledge
from .operations.token_usage import UsageLedger, usage_ledger_from_environment
from .operations.usage_limits import (
    DEFAULT_DAILY_TOKEN_BUDGET,
    DEFAULT_MAX_TURNS_PER_CONVERSATION,
    UsageLimits,
)


def build_chat_workflow(instance: Instance) -> "ChatWorkflow":
    return ChatWorkflow(
        chat=Chat.from_environment(instance=instance),
        knowledge=Knowledge(instance),
        usage_ledger=usage_ledger_from_environment(),
        max_turns_per_conversation=int(
            os.getenv(
                "MAAS_MAX_TURNS_PER_CONVERSATION",
                str(DEFAULT_MAX_TURNS_PER_CONVERSATION),
            )
        ),
        daily_token_budget=int(
            os.getenv("MAAS_DAILY_TOKEN_BUDGET", str(DEFAULT_DAILY_TOKEN_BUDGET))
        ),
    )


class ChatWorkflow:
    """Apply retrieval and operational policy around a conversational model."""

    def __init__(
        self,
        *,
        chat: Chat,
        knowledge: Knowledge,
        usage_ledger: UsageLedger,
        max_turns_per_conversation: int = DEFAULT_MAX_TURNS_PER_CONVERSATION,
        daily_token_budget: int = DEFAULT_DAILY_TOKEN_BUDGET,
    ) -> None:
        self._chat = chat
        self._knowledge = knowledge
        self._usage_ledger = usage_ledger
        self._usage_limits = UsageLimits(
            usage_ledger,
            max_turns_per_conversation=max_turns_per_conversation,
            daily_token_budget=daily_token_budget,
        )

    @property
    def daily_token_budget(self) -> int:
        return self._usage_limits.daily_token_budget

    async def initialize(self) -> None:
        await self._chat.initialize()
        await self._usage_ledger.initialize()

    async def healthcheck(self) -> None:
        await self._chat.healthcheck()
        await self._usage_ledger.healthcheck()

    async def shutdown(self) -> None:
        await self._chat.shutdown()

    async def create_conversation(self) -> UUID:
        return await self._chat.create_conversation()

    async def conversation_exists(self, conversation_id: UUID) -> bool:
        return await self._chat.conversation_exists(conversation_id)

    async def tokens_since(self, boundary: datetime) -> int:
        return await self._usage_ledger.tokens_since(boundary)

    async def clear(self) -> None:
        await self._chat.clear()
        await self._usage_ledger.clear()

    async def stream_turn(
        self,
        *,
        conversation_id: UUID,
        message: str,
        message_id: UUID,
    ) -> AsyncIterator[ChatEvent]:
        context = await self._chat.assemble_context(conversation_id, message)
        await self._usage_limits.check(context.completed_turns)

        classification = await self._chat.classify_and_rewrite_message(context)
        retrieval_query = classification.retrieval_query
        documents = (
            self._knowledge.retrieve(retrieval_query)
            if retrieval_query is not None
            else ()
        )

        usage_recorded = False
        try:
            async for event in self._chat.stream_response(
                conversation_id=conversation_id,
                message_id=message_id,
                context=context,
                classification=classification,
                documents=documents,
            ):
                if event.type == "message_end":
                    if not await self._record_usage(message_id):
                        raise RuntimeError(
                            "chat stream ended without completion metadata"
                        )
                    usage_recorded = True
                yield event
        finally:
            if not usage_recorded:
                await self._record_usage(message_id)

    async def _record_usage(self, message_id: UUID) -> bool:
        usage = self._chat.pop_usage(message_id)
        if usage is None:
            return False
        input_tokens, output_tokens = usage
        await self._usage_ledger.record(
            datetime.now(UTC),
            input_tokens,
            output_tokens,
        )
        return True

    async def complete_turn(
        self,
        *,
        conversation_id: UUID,
        message: str,
        message_id: UUID,
    ) -> ChatResponse:
        content_parts: list[str] = []
        completed = False
        async for event in self.stream_turn(
            conversation_id=conversation_id,
            message=message,
            message_id=message_id,
        ):
            if event.type == "text_delta" and event.delta is not None:
                content_parts.append(event.delta)
            elif event.type == "message_end":
                completed = True
        if not completed:
            raise RuntimeError("chat turn ended without a completion event")
        return ChatResponse(
            conversation_id=conversation_id,
            message_id=message_id,
            content="".join(content_parts),
        )
