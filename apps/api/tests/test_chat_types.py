from uuid import uuid4

import pytest
from pydantic import ValidationError

from me_as_a_service.chat.types import (
    ChatEvent,
    ConversationType,
    MessageClassification,
)


def test_message_classification_normalizes_an_evidence_query() -> None:
    classification = MessageClassification(
        conversation_type=ConversationType.EVIDENCE_REQUIRED,
        retrieval_query="  standalone query  ",
    )

    assert classification.retrieval_query == "standalone query"


@pytest.mark.parametrize(
    ("conversation_type", "retrieval_query"),
    [
        (ConversationType.EVIDENCE_REQUIRED, None),
        (ConversationType.CONVERSATION, "unexpected query"),
        (ConversationType.IRRELEVANT, "unexpected query"),
        (ConversationType.DISCUSS_IN_PERSON, "unexpected query"),
        (ConversationType.INAPPROPRIATE, "unexpected query"),
    ],
)
def test_message_classification_rejects_invalid_query_pairings(
    conversation_type: ConversationType,
    retrieval_query: str | None,
) -> None:
    with pytest.raises(ValidationError):
        MessageClassification(
            conversation_type=conversation_type,
            retrieval_query=retrieval_query,
        )


@pytest.mark.parametrize(
    ("event", "expected_json"),
    [
        (
            ChatEvent(
                type="message_start",
                conversation_id=(conversation_id := uuid4()),
                message_id=(message_id := uuid4()),
            ),
            (
                '{"type":"message_start","conversation_id":'
                f'"{conversation_id}","message_id":"{message_id}"}}'
            ),
        ),
        (
            ChatEvent(type="text_delta", delta="Hello"),
            '{"type":"text_delta","delta":"Hello"}',
        ),
        (ChatEvent(type="message_end"), '{"type":"message_end"}'),
        (
            ChatEvent(type="error", detail="Unavailable"),
            '{"type":"error","detail":"Unavailable"}',
        ),
    ],
)
def test_chat_event_preserves_the_streaming_wire_format(
    event: ChatEvent, expected_json: str
) -> None:
    assert event.model_dump_json(exclude_none=True) == expected_json


@pytest.mark.parametrize(
    "event",
    [
        {"type": "message_start", "conversation_id": uuid4()},
        {"type": "text_delta"},
        {"type": "message_end", "detail": "unexpected"},
        {"type": "error", "delta": "unexpected"},
    ],
)
def test_chat_event_rejects_invalid_payload_shapes(event: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="requires exactly"):
        ChatEvent.model_validate(event)
