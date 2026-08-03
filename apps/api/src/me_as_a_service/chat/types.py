from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from me_as_a_service.knowledge.models import FurtherReading, Passage

MAX_MESSAGE_LENGTH = 2_000
MAX_PAST_TURNS = 6

TurnRoute = Literal[
    "conversational",
    "privacy_boundary",
    "grounded",
    "web_grounded",
    "insufficient_evidence",
    "redirected",
]
AnalysisRoute = Literal[
    "conversational",
    "privacy_boundary",
    "redirected",
    "retrieval",
    "public_context",
]
Role = Literal["user", "assistant"]

# -- For complete responses --


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
    model_config = ConfigDict(frozen=True)

    conversation_id: UUID
    message_id: UUID
    content: str


# -- For streaming responses --


class MessageStartEvent(BaseModel):
    type: Literal["message_start"] = "message_start"
    conversation_id: UUID
    message_id: UUID


class TextDeltaEvent(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    delta: str


class FurtherReadingEvent(BaseModel):
    """Curated links the grounded answer's sources point readers to."""

    type: Literal["further_reading"] = "further_reading"
    links: tuple[FurtherReading, ...] = Field(min_length=1)


class MessageEndEvent(BaseModel):
    type: Literal["message_end"] = "message_end"


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    detail: str


ChatEvent = (
    MessageStartEvent
    | TextDeltaEvent
    | FurtherReadingEvent
    | MessageEndEvent
    | ErrorEvent
)

# -- For internal use --


@dataclass(frozen=True)
class StoredMessage:
    id: UUID
    role: Role
    content: str
    generation_content: str | None = None


@dataclass(frozen=True)
class TurnAnalysis:
    route: AnalysisRoute
    retrieval_query: str | None


class EvidenceAssessment(BaseModel):
    """Supporting candidates selected by the semantic evidence assessment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    supporting_passage_ids: tuple[str, ...]
    sufficient: bool


@dataclass(frozen=True)
class ConversationContext:
    system_policy: str
    messages: tuple[StoredMessage, ...]
    route: TurnRoute = "conversational"
    evidence: tuple[Passage, ...] = ()
