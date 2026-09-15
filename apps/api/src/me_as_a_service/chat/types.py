from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, Self, cast
from uuid import UUID

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_MESSAGE_LENGTH = 2_000
MAX_PAST_TURNS = 6


class ConversationType(StrEnum):
    """Classify how one incoming message should be answered."""

    # A professional question that requires conversation history and retrieved evidence.
    EVIDENCE_REQUIRED = "evidence_required"
    # A greeting or other non-substantive message that requires only conversation
    # history.
    CONVERSATION = "conversation"
    # A substantive request outside the professional discussion's scope.
    IRRELEVANT = "irrelevant"
    # A subjective or personal question best answered directly by the person.
    DISCUSS_IN_PERSON = "discuss_in_person"
    # A request for private, sensitive, secret, or identifying information.
    INAPPROPRIATE = "inappropriate"


class MessageClassification(BaseModel):
    """Validated routing decision and optional standalone retrieval query."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_type: ConversationType
    # For EVIDENCE_REQUIRED messages, a rewritten query for retrieval; otherwise null.
    retrieval_query: str | None

    @field_validator("retrieval_query")
    @classmethod
    def normalize_retrieval_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        query = value.strip()
        if not query:
            raise ValueError("retrieval query must be non-blank or null")
        return query

    @model_validator(mode="after")
    def validate_route(self) -> Self:
        if self.conversation_type is ConversationType.EVIDENCE_REQUIRED:
            if self.retrieval_query is None:
                raise ValueError("evidence-required messages require a retrieval query")
        elif self.retrieval_query is not None:
            raise ValueError(
                "only evidence-required messages may have a retrieval query"
            )
        return self


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID | None = None
    message: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)]

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("message must not be blank")
        return message


class ChatResponse(BaseModel):
    """For complete responses."""

    model_config = ConfigDict(frozen=True)

    conversation_id: UUID
    message_id: UUID
    content: str


class ChatEvent(BaseModel):
    """For streaming responses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["message_start", "text_delta", "message_end", "error"]
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    delta: str | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        expected_fields = {
            "message_start": frozenset(("conversation_id", "message_id")),
            "text_delta": frozenset(("delta",)),
            "message_end": frozenset(),
            "error": frozenset(("detail",)),
        }
        payload_fields = ("conversation_id", "message_id", "delta", "detail")
        provided_fields = frozenset(
            field for field in payload_fields if getattr(self, field) is not None
        )
        expected = expected_fields[self.type]
        if provided_fields != expected:
            raise ValueError(
                f"{self.type} requires exactly these payload fields: {sorted(expected)}"
            )
        return self


@dataclass(frozen=True)
class StoredMessage:
    """A user or assistant message stored in conversation history."""

    id: UUID
    role: Literal["user", "assistant"]
    content: str

    def to_openai_message(self) -> ChatCompletionMessageParam:
        """Return the message in OpenAI Chat Completions format."""

        return cast(
            ChatCompletionMessageParam,
            {"role": self.role, "content": self.content},
        )


@dataclass(frozen=True)
class ConversationContext:
    """Bounded conversation messages prepared for one hosted-model request."""

    messages: tuple[StoredMessage, ...]
    # Number of turns completed before this request, used for usage accounting.
    completed_turns: int

    def to_openai_messages(
        self, system_prompt: str
    ) -> list[ChatCompletionMessageParam]:
        """Return the context in OpenAI Chat Completions format."""

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system_prompt}
        ]
        messages.extend(message.to_openai_message() for message in self.messages)
        return messages
