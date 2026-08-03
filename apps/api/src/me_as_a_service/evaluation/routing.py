import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

from openai import AsyncOpenAI

from me_as_a_service.chat.model import DEFAULT_OPENAI_MODEL, ChatModel, OpenAIChatModel
from me_as_a_service.chat.prompts import load_prompts
from me_as_a_service.chat.types import AnalysisRoute, StoredMessage, TurnRoute
from me_as_a_service.chat.workflow import select_supporting_evidence
from me_as_a_service.evaluation.cases import EvaluationCase, load_evaluation_cases
from me_as_a_service.instance import load_selected_instance
from me_as_a_service.knowledge import EvidenceRetriever, ScopedEvidenceRetriever

ROUTES: tuple[TurnRoute, ...] = (
    "conversational",
    "privacy_boundary",
    "grounded",
    "web_grounded",
    "insufficient_evidence",
    "redirected",
)


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    expected_route: TurnRoute
    analysis_route: AnalysisRoute
    retrieval_query: str | None
    final_route: TurnRoute
    correct: bool


@dataclass(frozen=True)
class RoutingReport:
    model: str
    total_cases: int
    correct_cases: int
    accuracy: float
    false_redirects: int
    false_grounded: int
    per_route_accuracy: dict[TurnRoute, float]
    confusion_matrix: dict[TurnRoute, dict[TurnRoute, int]]
    cases: tuple[CaseResult, ...]


async def evaluate_turn_analysis(
    model: ChatModel,
    policy: str,
    cases: Sequence[EvaluationCase],
    retriever: EvidenceRetriever,
) -> RoutingReport:
    results: list[CaseResult] = []
    for case in cases:
        history = tuple(
            StoredMessage(id=uuid4(), role="user", content=message)
            for message in case.prior_user_messages
        )
        analysis = await model.analyze_turn(case.question, history, policy)
        if analysis.route in {"retrieval", "public_context"}:
            if analysis.retrieval_query is None:
                raise RuntimeError("retrieval analysis returned no query")
            retrieval_query = analysis.retrieval_query
            candidates = tuple(
                result.passage for result in retriever.search(retrieval_query)
            )
            if candidates:
                try:
                    assessment = await model.assess_evidence(
                        case.question, retrieval_query, candidates
                    )
                    _ = select_supporting_evidence(candidates, assessment)
                except Exception:
                    sufficient = False
                else:
                    sufficient = assessment.sufficient
            else:
                sufficient = False
            final_route: TurnRoute
            if sufficient:
                final_route = "grounded"
            elif analysis.route == "public_context":
                final_route = "web_grounded"
            else:
                final_route = "insufficient_evidence"
        else:
            retrieval_query = None
            final_route = cast(TurnRoute, analysis.route)
        results.append(
            CaseResult(
                case_id=case.id,
                expected_route=case.expected_route,
                analysis_route=analysis.route,
                retrieval_query=retrieval_query,
                final_route=final_route,
                correct=final_route == case.expected_route,
            )
        )
    return _build_report(model.model, tuple(results))


def _build_report(model: str, results: tuple[CaseResult, ...]) -> RoutingReport:
    total_cases = len(results)
    correct_cases = sum(result.correct for result in results)
    confusion_matrix: dict[TurnRoute, dict[TurnRoute, int]] = {
        expected: {predicted: 0 for predicted in ROUTES} for expected in ROUTES
    }
    for result in results:
        confusion_matrix[result.expected_route][result.final_route] += 1

    per_route_accuracy: dict[TurnRoute, float] = {}
    for route in ROUTES:
        route_results = [result for result in results if result.expected_route == route]
        per_route_accuracy[route] = (
            sum(result.correct for result in route_results) / len(route_results)
            if route_results
            else 0.0
        )

    return RoutingReport(
        model=model,
        total_cases=total_cases,
        correct_cases=correct_cases,
        accuracy=correct_cases / total_cases if total_cases else 0.0,
        false_redirects=sum(
            result.final_route == "redirected" and result.expected_route != "redirected"
            for result in results
        ),
        false_grounded=sum(
            result.final_route in {"grounded", "web_grounded"}
            and result.expected_route not in {"grounded", "web_grounded"}
            for result in results
        ),
        per_route_accuracy=per_route_accuracy,
        confusion_matrix=confusion_matrix,
        cases=results,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate structured turn analysis.")
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--knowledge", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default=DEFAULT_OPENAI_MODEL)
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY"))
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> RoutingReport:
    if not args.api_key:
        raise RuntimeError("OPENAI_API_KEY is required for turn-analysis evaluation")
    instance = load_selected_instance()
    questions_path = args.questions or instance.evaluation_questions
    if questions_path is None:
        raise RuntimeError("the selected instance has no evaluation fixture")
    knowledge_directory = args.knowledge or instance.knowledge_directory
    cases = load_evaluation_cases(questions_path)
    retriever = ScopedEvidenceRetriever.from_directory(knowledge_directory)
    prompts = load_prompts()
    model = OpenAIChatModel(
        AsyncOpenAI(api_key=args.api_key), model=args.model, prompts=prompts
    )
    try:
        return await evaluate_turn_analysis(
            model,
            prompts.turn_analysis_policy(
                instance.config.display_name,
                instance.config.routing.personal_terms,
            ),
            cases,
            retriever,
        )
    finally:
        await model.close()


def main() -> None:
    args = _parse_args()
    report = asyncio.run(_run(args))
    serialized = json.dumps(asdict(report), indent=2)
    if args.output is None:
        print(serialized)
    else:
        args.output.write_text(f"{serialized}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
