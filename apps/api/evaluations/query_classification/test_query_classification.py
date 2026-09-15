"""Live-model evaluation for the instance-agnostic message classifier.

Run explicitly with ``pnpm --filter @me-as-a-service/api eval:classification``.
This file is outside the default pytest test path because it makes hosted-model
requests and is therefore slower, non-deterministic, and billable.
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
    MessageClassification,
    StoredMessage,
)

DISPLAY_NAME = "Alex Example"
MAX_CONCURRENCY = 5
CASES_PATH = Path(__file__).with_name("cases.json")
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class EvaluationMessage(BaseModel):
    """One synthetic historical message supplied to the classifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ClassificationCase(BaseModel):
    """One frozen classifier input and its expected route."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    expected_type: ConversationType
    history: tuple[EvaluationMessage, ...] = ()

    @model_validator(mode="after")
    def validate_history(self) -> Self:
        expected_roles = tuple(
            "user" if index % 2 == 0 else "assistant"
            for index in range(len(self.history))
        )
        if tuple(message.role for message in self.history) != expected_roles:
            raise ValueError("history must contain complete alternating turns")
        return self


@dataclass(frozen=True)
class EvaluationResult:
    """Actual classifier output or provider error for one case."""

    case: ClassificationCase
    classification: MessageClassification | None = None
    error: str | None = None


def _load_cases() -> tuple[ClassificationCase, ...]:
    cases = tuple(
        TypeAdapter(list[ClassificationCase]).validate_json(
            CASES_PATH.read_text(encoding="utf-8")
        )
    )
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise RuntimeError("classification case IDs must be unique")

    counts = Counter(case.expected_type for case in cases)
    expected_counts = Counter(
        {conversation_type: 10 for conversation_type in ConversationType}
    )
    if counts != expected_counts:
        raise RuntimeError(
            f"expected 10 cases per conversation type, found {dict(counts)}"
        )
    return cases


CASES = _load_cases()


def _context_for(case: ClassificationCase) -> ConversationContext:
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


async def _evaluate_cases() -> tuple[str, str, tuple[EvaluationResult, ...]]:
    load_dotenv(REPOSITORY_ROOT / ".env")
    os.environ["LANGSMITH_TRACING"] = "false"
    provider = os.getenv("MAAS_LLM_PROVIDER", "openai")
    model = chat_model_from_environment()
    classifier_prompt = load_prompts().render(
        "classify-and-rewrite-message",
        {"display_name": DISPLAY_NAME},
    )
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def evaluate(case: ClassificationCase) -> EvaluationResult:
        async with semaphore:
            try:
                classification = await model.classify_and_rewrite_message(
                    _context_for(case),
                    classifier_prompt,
                )
            except Exception as error:
                return EvaluationResult(
                    case=case,
                    error=f"{type(error).__name__}: {error}",
                )
            return EvaluationResult(case=case, classification=classification)

    try:
        results = tuple(await asyncio.gather(*(evaluate(case) for case in CASES)))
    finally:
        await model.close()
    return provider, model.model, results


def test_query_classification() -> None:
    """Require every frozen case to receive its expected conversation type."""

    provider, model_name, results = asyncio.run(_evaluate_cases())

    print(f"\nProvider: {provider}")
    print(f"Model: {model_name}")
    print(f"Cases: {len(results)}")
    print("\nCase results:")

    for result in results:
        classification = result.classification
        prediction = (
            classification.conversation_type.value
            if classification is not None
            else "error"
        )
        retrieval_query = (
            classification.retrieval_query if classification is not None else None
        )
        print(
            f"{result.case.id} | message={result.case.message!r} | "
            f"target={result.case.expected_type.value} | prediction={prediction} | "
            f"retrieval_query={retrieval_query!r}"
        )
        if result.error is not None:
            print(f"  error={result.error}")

    failures: list[str] = []
    print("\nSummary:")
    for conversation_type in ConversationType:
        type_results = tuple(
            result
            for result in results
            if result.case.expected_type is conversation_type
        )
        correct = sum(
            result.classification is not None
            and result.classification.conversation_type is conversation_type
            for result in type_results
        )
        print(f"{conversation_type.value}: {correct}/{len(type_results)}")

    for result in results:
        if result.error is not None:
            failures.append(f"{result.case.id}: {result.error}")
            continue
        assert result.classification is not None
        actual_type = result.classification.conversation_type
        if actual_type is not result.case.expected_type:
            failures.append(
                f"{result.case.id}: expected {result.case.expected_type.value}, "
                f"got {actual_type.value}; message={result.case.message!r}"
            )

    correct_total = len(results) - len(failures)
    print(f"Overall: {correct_total}/{len(results)}")
    if failures:
        pytest.fail("Classification failures:\n" + "\n".join(failures), pytrace=False)
