import argparse
import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import pytest

import me_as_a_service.evaluation.routing as evaluation_module
from me_as_a_service.chat.model import ModelEvent, WebSearchResult
from me_as_a_service.chat.types import (
    ConversationContext,
    EvidenceAssessment,
    StoredMessage,
    TurnAnalysis,
)
from me_as_a_service.evaluation import EvaluationCase, load_evaluation_cases
from me_as_a_service.evaluation.routing import evaluate_turn_analysis
from me_as_a_service.instance import load_instance
from me_as_a_service.knowledge import ScopedEvidenceRetriever
from me_as_a_service.knowledge.models import Passage

REPOSITORY_ROOT = Path(__file__).parents[3]
INSTANCE = load_instance(REPOSITORY_ROOT / "examples/fictional-profile")
QUESTIONS_PATH = INSTANCE.evaluation_questions
if QUESTIONS_PATH is None:
    raise RuntimeError("fictional instance must include evaluation questions")


class FixtureModel:
    model = "fixture-model"

    async def analyze_turn(
        self,
        message: str,
        history: tuple[StoredMessage, ...],
        policy: str,
    ) -> TurnAnalysis:
        if message == "Hello!":
            return TurnAnalysis("conversational", None)
        if message == "Who currently leads Northstar's research lab?":
            return TurnAnalysis("public_context", message)
        if message.startswith("Build ") or message.startswith("Ignore "):
            return TurnAnalysis("redirected", None)
        query = " ".join((*[item.content for item in history], message))
        return TurnAnalysis("retrieval", query)

    async def assess_evidence(
        self,
        question: str,
        retrieval_query: str,
        evidence: tuple[Passage, ...],
    ) -> EvidenceAssessment:
        sufficient = not (
            "Director of Engineering" in question
            or "currently leads Northstar's research lab" in question
        )
        return EvidenceAssessment(
            supporting_passage_ids=(
                tuple(passage.passage_id for passage in evidence) if sufficient else ()
            ),
            sufficient=sufficient,
        )

    async def stream(self, context: ConversationContext) -> AsyncIterator[ModelEvent]:
        if False:
            yield

    async def search_web(self, question: str, query: str) -> WebSearchResult:
        raise AssertionError("the routing evaluator does not execute web search")

    async def close(self) -> None:
        return None


def test_turn_analysis_evaluation_matches_seed_cases() -> None:
    cases = load_evaluation_cases(cast(Path, QUESTIONS_PATH))

    report = asyncio.run(
        evaluate_turn_analysis(
            FixtureModel(),
            "policy",
            cases,
            ScopedEvidenceRetriever.from_directory(INSTANCE.knowledge_directory),
        )
    )

    assert report.model == "fixture-model"
    assert report.total_cases == 9
    assert report.accuracy == 1.0
    assert report.false_redirects == 0
    assert report.false_grounded == 0


def test_evaluation_command_requires_openai_credentials() -> None:
    args = argparse.Namespace(
        questions=None,
        knowledge=None,
        output=None,
        model="test-model",
        api_key=None,
    )

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        asyncio.run(evaluation_module._run(args))


def test_routing_evaluation_predicts_web_fallback_without_executing_search() -> None:
    case = EvaluationCase(
        id="public-context",
        question="Who currently leads Northstar's research lab?",
        question_type="public_context_current_fact",
        answerability="answerable",
        expected_route="web_grounded",
        must_cite=True,
        prior_user_messages=(),
        expected_sources=(),
        required_facts=(),
        relevant_sections=(),
    )

    report = asyncio.run(
        evaluate_turn_analysis(
            FixtureModel(),
            "policy",
            (case,),
            ScopedEvidenceRetriever.from_directory(INSTANCE.knowledge_directory),
        )
    )

    assert report.accuracy == 1.0
    assert report.cases[0].analysis_route == "public_context"
    assert report.cases[0].final_route == "web_grounded"
