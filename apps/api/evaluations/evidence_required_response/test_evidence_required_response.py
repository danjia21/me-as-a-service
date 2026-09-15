"""Live response evaluation for instance-specific evidence-required questions.

Run explicitly with
``pnpm --filter @me-as-a-service/api eval:evidence-required-response``. This file
is outside the default pytest path because it makes hosted-model requests and is
therefore slower, non-deterministic, and billable.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import load_dotenv

from me_as_a_service.chat_workflow import build_chat_workflow
from me_as_a_service.instance import load_instance_from_environment

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class EvaluationResult:
    """Generated response or provider error for one question."""

    question_id: str
    response: str | None = None
    error: str | None = None


async def _evaluate_cases() -> tuple[EvaluationResult, ...]:
    load_dotenv(REPOSITORY_ROOT / ".env")
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["MAAS_CONVERSATION_STORE"] = "memory"

    instance = load_instance_from_environment()
    cases = instance.evaluation_questions()
    workflow = build_chat_workflow(instance)
    results: list[EvaluationResult] = []

    print(f"\nInstance: {instance.directory}")
    print(f"Display name: {instance.display_name}")
    print(f"Cases: {len(cases)}")

    await workflow.initialize()
    try:
        for question_id, question in cases.items():
            conversation_id = await workflow.create_conversation()
            print(f"\n[{question_id}]")
            print(f"Question: {question}")
            try:
                response = await workflow.complete_turn(
                    conversation_id=conversation_id,
                    message=question,
                    message_id=uuid4(),
                )
            except Exception as error:
                error_message = f"{type(error).__name__}: {error}"
                print(f"Error: {error_message}")
                results.append(
                    EvaluationResult(question_id=question_id, error=error_message)
                )
            else:
                print(f"Response: {response.content}")
                results.append(
                    EvaluationResult(
                        question_id=question_id,
                        response=response.content,
                    )
                )
    finally:
        await workflow.shutdown()

    return tuple(results)


def test_evidence_required_response_generation() -> None:
    """Print every final response and fail on provider errors."""

    results = asyncio.run(_evaluate_cases())
    failures: list[str] = []

    for result in results:
        if result.error is not None:
            failures.append(f"{result.question_id}: {result.error}")

    if failures:
        pytest.fail("Evaluation failures:\n" + "\n".join(failures), pytrace=False)
