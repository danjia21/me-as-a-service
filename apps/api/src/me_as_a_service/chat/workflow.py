import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from me_as_a_service.chat.model import (
    ChatModel,
    LangSmithTracing,
    ModelCompleted,
    ModelTextDelta,
    WebSearchResult,
)
from me_as_a_service.chat.prompts import PromptSet
from me_as_a_service.chat.storage import ConversationStore
from me_as_a_service.chat.types import (
    MAX_PAST_TURNS,
    ChatEvent,
    ChatResponse,
    ConversationContext,
    EvidenceAssessment,
    FurtherReadingEvent,
    MessageEndEvent,
    MessageStartEvent,
    StoredMessage,
    TextDeltaEvent,
    TurnAnalysis,
    TurnRoute,
)
from me_as_a_service.chat.usage import UsageLedger
from me_as_a_service.knowledge.models import FurtherReading, Passage
from me_as_a_service.knowledge.retrieval import (
    EvidenceRetriever,
    ScopedRetrievalResult,
)

DEFAULT_CONTEXT_CHARACTER_LIMIT = 12_000
DEFAULT_MAX_TURNS_PER_CONVERSATION = 20
DEFAULT_DAILY_TOKEN_BUDGET = 100_000

logger = logging.getLogger(__name__)


class UsageLimitExceeded(RuntimeError):
    pass


class ContextAssembler:
    """Keep the newest complete messages within fixed count and character bounds."""

    def __init__(
        self,
        *,
        past_turn_limit: int = MAX_PAST_TURNS,
        character_limit: int = DEFAULT_CONTEXT_CHARACTER_LIMIT,
    ) -> None:
        if past_turn_limit < 0 or character_limit < 1:
            raise ValueError("context limits must be positive")
        self._past_turn_limit = past_turn_limit
        self._character_limit = character_limit

    def assemble(
        self, history: tuple[StoredMessage, ...], system_policy: str
    ) -> ConversationContext:
        if not history:
            return ConversationContext(system_policy=system_policy, messages=())

        current_message = history[-1]
        prior_messages = history[:-1]
        prior_turns = tuple(
            prior_messages[index : index + 2]
            for index in range(0, len(prior_messages), 2)
        )
        selected_turns: list[tuple[StoredMessage, ...]] = []
        character_count = len(_current_model_content(current_message))
        candidate_turns = (
            prior_turns[-self._past_turn_limit :] if self._past_turn_limit else ()
        )
        for turn in reversed(candidate_turns):
            turn_length = sum(len(message.content) for message in turn)
            if character_count + turn_length > self._character_limit:
                break
            selected_turns.append(turn)
            character_count += turn_length

        selected = tuple(
            message for turn in reversed(selected_turns) for message in turn
        )

        return ConversationContext(
            system_policy=system_policy,
            messages=(*selected, current_message),
        )


def _current_model_content(message: StoredMessage) -> str:
    return message.generation_content or message.content


@dataclass(frozen=True)
class WorkflowCompleted:
    content: str
    route: TurnRoute
    input_tokens: int
    output_tokens: int


WorkflowEvent = ChatEvent | WorkflowCompleted


def _root_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return {"message": inputs["message"]}


def _root_outputs(events: Sequence[Any]) -> dict[str, Any]:
    completed = next(
        (event for event in reversed(events) if isinstance(event, WorkflowCompleted)),
        None,
    )
    if completed is None:
        return {"outcome": "cancelled"}
    return {
        "assistant_content": completed.content,
        "route": completed.route,
        "input_tokens": completed.input_tokens,
        "output_tokens": completed.output_tokens,
        "outcome": "completed",
    }


def _step_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in inputs.items()
        if key not in {"classifier", "model", "retriever", "fallback"}
    }


@traceable(name="analyze_turn", process_inputs=_step_inputs)
async def _analyze_turn(
    model: ChatModel,
    message: str,
    history: tuple[StoredMessage, ...],
    policy: str,
) -> TurnAnalysis:
    return await model.analyze_turn(message, history, policy)


def _retrieval_outputs(
    results: tuple[ScopedRetrievalResult, ...],
) -> dict[str, Any]:
    return {
        "results": [
            {
                "source_id": result.passage.source_id,
                "passage_id": result.passage.passage_id,
                "scope": result.scope,
                "rank_within_scope": result.rank_within_scope,
                "score": result.score,
                "section_path": result.passage.section_path,
                "text": result.passage.text,
            }
            for result in results
        ]
    }


@traceable(
    name="retrieve_evidence",
    run_type="retriever",
    process_inputs=_step_inputs,
    process_outputs=_retrieval_outputs,
)
def _retrieve_evidence(
    retriever: EvidenceRetriever, query: str
) -> tuple[ScopedRetrievalResult, ...]:
    return retriever.search(query)


@traceable(name="assess_evidence", process_inputs=_step_inputs)
async def _assess_evidence(
    model: ChatModel,
    question: str,
    retrieval_query: str,
    evidence: tuple[Passage, ...],
) -> dict[str, Any]:
    if not evidence:
        return {
            "supporting_passage_ids": (),
            "sufficient": False,
            "method": "empty_retrieval",
        }
    try:
        assessment = await model.assess_evidence(question, retrieval_query, evidence)
    except Exception as error:
        logger.warning(
            "OpenAI evidence assessment failed closed: %s",
            error,
            extra={
                "error_class": type(error).__name__,
            },
        )
        return {
            "supporting_passage_ids": (),
            "sufficient": False,
            "method": "model_failure",
        }

    try:
        selected_evidence = select_supporting_evidence(evidence, assessment)
    except ValueError:
        logger.warning("OpenAI evidence assessment was invalid and failed closed")
        return {
            "supporting_passage_ids": (),
            "sufficient": False,
            "method": "invalid_assessment",
        }

    return {
        "supporting_passage_ids": tuple(
            passage.passage_id for passage in selected_evidence
        ),
        "sufficient": assessment.sufficient,
        "method": "openai",
    }


@traceable(name="web_search", process_inputs=_step_inputs)
async def _search_web(model: ChatModel, question: str, query: str) -> WebSearchResult:
    return await model.search_web(question, query)


class ChatWorkflow:
    def __init__(
        self,
        *,
        store: ConversationStore,
        usage_ledger: UsageLedger,
        model: ChatModel,
        retriever: EvidenceRetriever,
        prompts: PromptSet,
        tracing: LangSmithTracing,
        instance_id: str,
        display_name: str,
        personal_terms: tuple[str, ...],
        context_assembler: ContextAssembler | None = None,
        max_turns_per_conversation: int = DEFAULT_MAX_TURNS_PER_CONVERSATION,
        daily_token_budget: int = DEFAULT_DAILY_TOKEN_BUDGET,
    ) -> None:
        if max_turns_per_conversation < 1:
            raise ValueError("max_turns_per_conversation must be positive")
        if daily_token_budget < 1:
            raise ValueError("daily_token_budget must be positive")
        self._store = store
        self._usage_ledger = usage_ledger
        self._model = model
        self._retriever = retriever
        self._prompts = prompts
        self._tracing = tracing
        self._instance_id = instance_id
        self._system_policy = prompts.system_policy(display_name)
        self._turn_analysis_policy = prompts.turn_analysis_policy(
            display_name, personal_terms
        )
        self._context_assembler = context_assembler or ContextAssembler()
        self._max_turns_per_conversation = max_turns_per_conversation
        self._daily_token_budget = daily_token_budget

    @property
    def store(self) -> ConversationStore:
        return self._store

    @property
    def usage_ledger(self) -> UsageLedger:
        return self._usage_ledger

    @property
    def daily_token_budget(self) -> int:
        return self._daily_token_budget

    async def initialize(self) -> None:
        await self._store.initialize()
        await self._usage_ledger.initialize()

    async def healthcheck(self) -> None:
        await self._store.healthcheck()
        await self._usage_ledger.healthcheck()

    async def shutdown(self) -> None:
        await self._model.close()
        await self._tracing.flush()

    async def stream_turn(
        self,
        *,
        conversation_id: UUID,
        message: str,
        message_id: UUID,
    ) -> AsyncIterator[ChatEvent]:
        trace_id = uuid4()
        with self._tracing.activate():
            async for event in self._stream_turn_traced(
                conversation_id=conversation_id,
                message=message,
                message_id=message_id,
                langsmith_extra={"name": str(trace_id), "run_id": trace_id},
            ):
                if not isinstance(event, WorkflowCompleted):
                    yield event

    @traceable(
        name="chat_turn",
        process_inputs=_root_inputs,
        reduce_fn=_root_outputs,
    )
    async def _stream_turn_traced(
        self,
        *,
        conversation_id: UUID,
        message: str,
        message_id: UUID,
    ) -> AsyncIterator[WorkflowEvent]:
        run = get_current_run_tree()
        try:
            stored_history = await self._store.history(conversation_id)
            await self._enforce_usage_limits(stored_history)
            history = stored_history[-(MAX_PAST_TURNS * 2) :]
            if run is not None:
                run.add_metadata(
                    {
                        "bounded_conversation_history": history,
                        "conversation_id": str(conversation_id),
                        "instance": self._instance_id,
                        "message_id": str(message_id),
                        "session_id": str(conversation_id),
                    }
                )

            analysis = await _analyze_turn(
                self._model, message, history, self._turn_analysis_policy
            )
            route = cast(TurnRoute, analysis.route)
            evidence: tuple[Passage, ...] = ()
            web_result: WebSearchResult | None = None
            if analysis.route in {"retrieval", "public_context"}:
                if analysis.retrieval_query is None:
                    raise RuntimeError("retrieval analysis returned no query")
                evidence_query = analysis.retrieval_query
                retrieval_results = _retrieve_evidence(self._retriever, evidence_query)
                candidates = tuple(result.passage for result in retrieval_results)
                assessment = await _assess_evidence(
                    self._model,
                    message,
                    evidence_query,
                    candidates,
                )
                selected_ids = set(assessment["supporting_passage_ids"])
                evidence = tuple(
                    passage
                    for passage in candidates
                    if passage.passage_id in selected_ids
                )
                if assessment["sufficient"]:
                    route = "grounded"
                elif analysis.route == "public_context":
                    evidence = ()
                    try:
                        web_result = await _search_web(
                            self._model, message, evidence_query
                        )
                    except Exception as error:
                        logger.warning(
                            "OpenAI web search failed closed: %s",
                            error,
                            extra={"error_class": type(error).__name__},
                        )
                        route = "insufficient_evidence"
                    else:
                        route = "web_grounded"
                else:
                    route = "insufficient_evidence"

            user_message = StoredMessage(
                id=uuid4(),
                role="user",
                content=message,
                generation_content=self._prompts.generation_turn_message(
                    route, evidence, message
                ),
            )
            context = self._context_assembler.assemble(
                (*history, user_message), self._system_policy
            )
            context = ConversationContext(
                system_policy=context.system_policy,
                messages=context.messages,
                route=route,
                evidence=evidence,
            )
            if run is not None:
                run.add_metadata({"route": route, "outcome": "running"})

            yield MessageStartEvent(
                conversation_id=conversation_id,
                message_id=message_id,
            )
            content_parts: list[str] = []
            completion: ModelCompleted | None = None
            if web_result is not None:
                content_parts.append(web_result.content)
                yield TextDeltaEvent(delta=web_result.content)
                completion = ModelCompleted(
                    input_tokens=web_result.input_tokens,
                    output_tokens=web_result.output_tokens,
                )
            else:
                async for event in self._model.stream(context):
                    if isinstance(event, ModelTextDelta):
                        content_parts.append(event.delta)
                        yield TextDeltaEvent(delta=event.delta)
                    else:
                        completion = event
            if completion is None:
                raise RuntimeError("OpenAI stream ended without completion metadata")

            content = "".join(content_parts)
            completed_at = datetime.now(UTC)
            await self._usage_ledger.record(
                completed_at,
                completion.input_tokens,
                completion.output_tokens,
            )
            await self._store.append_turn(
                conversation_id,
                user_message,
                StoredMessage(id=message_id, role="assistant", content=content),
            )
            if run is not None:
                run.add_metadata(
                    {
                        "route": route,
                        "model": self._model.model,
                        "prompt_revision": self._prompts.revision,
                        "input_tokens": completion.input_tokens,
                        "output_tokens": completion.output_tokens,
                        "outcome": "completed",
                    }
                )
            if web_result is not None:
                further_reading = web_result.links
            elif route == "grounded":
                further_reading = further_reading_links(evidence)
            else:
                further_reading = ()
            if further_reading:
                yield FurtherReadingEvent(links=further_reading)
            yield WorkflowCompleted(
                content=content,
                route=route,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
            )
            yield MessageEndEvent()
        except BaseException as error:
            if run is not None:
                if isinstance(error, UsageLimitExceeded):
                    outcome = "rejected"
                elif isinstance(error, (asyncio.CancelledError, GeneratorExit)):
                    outcome = "cancelled"
                else:
                    outcome = "failed"
                run.add_metadata(
                    {
                        "outcome": outcome,
                        "error_type": type(error).__name__,
                        "error_message": str(error),
                    }
                )
            raise

    async def _enforce_usage_limits(
        self, stored_history: tuple[StoredMessage, ...]
    ) -> None:
        if len(stored_history) // 2 >= self._max_turns_per_conversation:
            raise UsageLimitExceeded(
                "This conversation reached its turn limit. Start a new conversation."
            )
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        if await self._usage_ledger.tokens_since(today) >= self._daily_token_budget:
            raise UsageLimitExceeded(
                "The daily model budget is exhausted. Please try again tomorrow."
            )

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
            if isinstance(event, TextDeltaEvent):
                content_parts.append(event.delta)
            elif isinstance(event, MessageEndEvent):
                completed = True
        if not completed:
            raise RuntimeError("chat turn ended without a completion event")
        return ChatResponse(
            conversation_id=conversation_id,
            message_id=message_id,
            content="".join(content_parts),
        )


def further_reading_links(
    evidence: tuple[Passage, ...],
) -> tuple[FurtherReading, ...]:
    """Collect each source's curated links once, in retrieval order."""
    links: list[FurtherReading] = []
    seen: set[str] = set()
    for passage in evidence:
        for link in passage.further_reading:
            if link.url in seen:
                continue
            seen.add(link.url)
            links.append(link)
    return tuple(links)


def select_supporting_evidence(
    candidates: tuple[Passage, ...], assessment: EvidenceAssessment
) -> tuple[Passage, ...]:
    """Validate selected IDs and restore the candidate ordering."""
    selected_ids = assessment.supporting_passage_ids
    candidate_ids = {passage.passage_id for passage in candidates}
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("supporting passage IDs must be unique")
    if not set(selected_ids) <= candidate_ids:
        raise ValueError("supporting passage IDs must belong to the candidates")
    if assessment.sufficient and not selected_ids:
        raise ValueError("sufficient evidence requires a supporting passage")

    selected_id_set = set(selected_ids)
    return tuple(
        passage for passage in candidates if passage.passage_id in selected_id_set
    )
