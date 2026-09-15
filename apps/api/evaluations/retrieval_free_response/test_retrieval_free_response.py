"""Live response evaluation for routes that do not use retrieval.

Run explicitly with
``pnpm --filter @me-as-a-service/api eval:retrieval-free-response``. This file
is outside the default pytest path because it makes hosted-model requests and is
therefore slower, non-deterministic, and billable.
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from me_as_a_service.chat.model import chat_model_from_environment
from me_as_a_service.chat.prompts import load_prompts
from me_as_a_service.chat.types import (
    ConversationContext,
    ConversationType,
    StoredMessage,
)

DISPLAY_NAME = "Alex Example"
PUBLIC_PROFILE = "https://www.linkedin.com/in/alex-example/"
CASES_PATH = Path(__file__).with_name("cases.json")
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
RETRIEVAL_FREE_PROMPTS = {
    ConversationType.CONVERSATION: "answer-conversation",
    ConversationType.IRRELEVANT: "answer-irrelevant",
    ConversationType.DISCUSS_IN_PERSON: "answer-discuss-in-person",
    ConversationType.INAPPROPRIATE: "answer-inappropriate",
}

# Comment out any conversation types that should be skipped for a manual run.
KEPT_CONVERSATION_TYPES = [
    # ConversationType.CONVERSATION,
    # ConversationType.IRRELEVANT,
    ConversationType.DISCUSS_IN_PERSON,
    # ConversationType.INAPPROPRIATE,
]


class EvaluationMessage(BaseModel):
    """One synthetic historical message supplied to response generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ResponseCase(BaseModel):
    """One frozen response input and its ground-truth conversation type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    conversation_type: ConversationType
    history: tuple[EvaluationMessage, ...] = ()

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        if self.conversation_type not in RETRIEVAL_FREE_PROMPTS:
            raise ValueError("response evaluation supports retrieval-free types only")
        expected_roles = tuple(
            "user" if index % 2 == 0 else "assistant"
            for index in range(len(self.history))
        )
        if tuple(message.role for message in self.history) != expected_roles:
            raise ValueError("history must contain complete alternating turns")
        if self.conversation_type is not ConversationType.CONVERSATION and self.history:
            raise ValueError("only conversation cases may include history")
        return self


@dataclass(frozen=True)
class EvaluationResult:
    """Generated response or provider error for one case."""

    case: ResponseCase
    response: str | None = None
    error: str | None = None


def _load_cases() -> tuple[ResponseCase, ...]:
    cases = tuple(
        TypeAdapter(list[ResponseCase]).validate_json(
            CASES_PATH.read_text(encoding="utf-8")
        )
    )
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise RuntimeError("response case IDs must be unique")

    counts = Counter(case.conversation_type for case in cases)
    expected_counts = Counter(
        {conversation_type: 10 for conversation_type in RETRIEVAL_FREE_PROMPTS}
    )
    if counts != expected_counts:
        raise RuntimeError(
            f"expected 10 cases per retrieval-free type, found {dict(counts)}"
        )
    return cases


CASES = tuple(
    case for case in _load_cases() if case.conversation_type in KEPT_CONVERSATION_TYPES
)
if not CASES:
    raise RuntimeError("KEPT_CONVERSATION_TYPES must include at least one type")


def _context_for(case: ResponseCase) -> ConversationContext:
    historical_messages = tuple(
        StoredMessage(id=uuid4(), role=message.role, content=message.content)
        for message in case.history
    )
    return ConversationContext(
        messages=(
            *historical_messages,
            StoredMessage(id=uuid4(), role="user", content=case.message),
        ),
        completed_turns=len(historical_messages) // 2,
    )


async def _evaluate_cases() -> tuple[EvaluationResult, ...]:
    load_dotenv(REPOSITORY_ROOT / ".env")
    os.environ["LANGSMITH_TRACING"] = "false"
    provider = os.getenv("MAAS_LLM_PROVIDER", "openai")
    model = chat_model_from_environment()
    prompts = load_prompts()
    results: list[EvaluationResult] = []

    print(f"\nProvider: {provider}")
    print(f"Model: {model.model}")
    print(f"Dummy display name: {DISPLAY_NAME}")
    print(f"Cases: {len(CASES)}")

    try:
        for case in CASES:
            system_prompt = prompts.render(
                RETRIEVAL_FREE_PROMPTS[case.conversation_type],
                {
                    "display_name": DISPLAY_NAME,
                    "public_profile": PUBLIC_PROFILE,
                },
            )
            response_parts: list[str] = []
            print(f"\n[{case.id}] {case.conversation_type.value}")
            print(f"Query: {case.message}")
            print("Response: ", end="", flush=True)
            try:
                async for delta, _, _ in model.stream_response(
                    _context_for(case),
                    system_prompt,
                ):
                    if delta is not None:
                        response_parts.append(delta)
                        print(delta, end="", flush=True)
            except Exception as error:
                error_message = f"{type(error).__name__}: {error}"
                print(f"\nError: {error_message}")
                results.append(
                    EvaluationResult(
                        case=case,
                        error=error_message,
                    )
                )
            else:
                print()
                results.append(
                    EvaluationResult(case=case, response="".join(response_parts))
                )
    finally:
        await model.close()
    return tuple(results)


def test_retrieval_free_response_generation() -> None:
    """Print responses for manual review without rating their quality."""

    results = asyncio.run(_evaluate_cases())

    provider_errors: list[str] = []
    for result in results:
        if result.error is not None:
            provider_errors.append(f"{result.case.id}: {result.error}")

    if provider_errors:
        pytest.fail("Provider failures:\n" + "\n".join(provider_errors), pytrace=False)
