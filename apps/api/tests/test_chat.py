import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from langsmith import Client
from prometheus_client import CONTENT_TYPE_LATEST

import me_as_a_service.api as api_module
from me_as_a_service.api import (
    MAX_MESSAGE_LENGTH,
    NDJSON_MEDIA_TYPE,
    app,
    chat_workflow,
    conversation_store,
    ip_rate_limiter,
    session_rate_limiter,
    traffic_monitor,
    usage_ledger,
)
from me_as_a_service.chat.model import (
    LangSmithTracing,
    ModelCompleted,
    ModelEvent,
    ModelTextDelta,
    WebSearchResult,
)
from me_as_a_service.chat.prompts import load_prompts
from me_as_a_service.chat.storage import InMemoryConversationStore
from me_as_a_service.chat.types import (
    MAX_PAST_TURNS,
    AnalysisRoute,
    ChatEvent,
    ConversationContext,
    EvidenceAssessment,
    FurtherReadingEvent,
    StoredMessage,
    TextDeltaEvent,
    TurnAnalysis,
)
from me_as_a_service.chat.usage import InMemoryUsageLedger
from me_as_a_service.chat.workflow import (
    ChatWorkflow,
    ContextAssembler,
    UsageLimitExceeded,
)
from me_as_a_service.instance import load_instance
from me_as_a_service.knowledge import load_markdown_corpus
from me_as_a_service.knowledge.models import FurtherReading, Passage
from me_as_a_service.knowledge.retrieval import ScopedRetrievalResult
from me_as_a_service.traffic import QueueSaturated, SlidingWindowRateLimiter

REPOSITORY_ROOT = Path(__file__).parents[3]
INSTANCE = load_instance(REPOSITORY_ROOT / "examples/fictional-profile")
client = TestClient(app)


class FakeModel:
    model = "fake-model"

    def __init__(
        self,
        *,
        judge_result: bool = True,
        supporting_passage_ids: tuple[str, ...] | None = None,
        analysis: TurnAnalysis | None = None,
        fail_assessment: bool = False,
        fail_stream: bool = False,
        fail_web_search: bool = False,
        web_result: WebSearchResult | None = None,
    ) -> None:
        self.judge_result = judge_result
        self.supporting_passage_ids = supporting_passage_ids
        self.analysis = analysis
        self.fail_assessment = fail_assessment
        self.fail_stream = fail_stream
        self.fail_web_search = fail_web_search
        self.web_result = web_result or WebSearchResult(
            content=(
                "RPG is led by [Prof. Davide Scaramuzza](https://rpg.example/people)."
            ),
            links=(
                FurtherReading(label="RPG people", url="https://rpg.example/people"),
            ),
            input_tokens=20,
            output_tokens=8,
        )
        self.context: ConversationContext | None = None
        self.analysis_history: tuple[StoredMessage, ...] | None = None
        self.analysis_calls = 0
        self.assessment_calls = 0
        self.web_search_calls = 0

    async def analyze_turn(
        self,
        message: str,
        history: tuple[StoredMessage, ...],
        policy: str,
    ) -> TurnAnalysis:
        self.analysis_calls += 1
        self.analysis_history = history
        if self.analysis is not None:
            return self.analysis
        normalized = message.casefold()
        if normalized.strip(" !.") in {"hi", "hello", "hello again"}:
            return TurnAnalysis("conversational", None)
        if "solve the travelling" in normalized:
            return TurnAnalysis("redirected", None)
        query = " ".join(
            (*[item.content for item in history if item.role == "user"], message)
        )
        return TurnAnalysis("retrieval", query)

    async def assess_evidence(
        self,
        question: str,
        retrieval_query: str,
        evidence: tuple[Passage, ...],
    ) -> EvidenceAssessment:
        self.assessment_calls += 1
        if self.fail_assessment:
            raise RuntimeError("assessment failed")
        passage_ids = self.supporting_passage_ids
        if passage_ids is None:
            passage_ids = tuple(passage.passage_id for passage in evidence)
        return EvidenceAssessment(
            supporting_passage_ids=passage_ids,
            sufficient=self.judge_result,
        )

    async def search_web(self, question: str, query: str) -> WebSearchResult:
        self.web_search_calls += 1
        if self.fail_web_search:
            raise RuntimeError("web search failed")
        return self.web_result

    async def stream(self, context: ConversationContext) -> AsyncIterator[ModelEvent]:
        self.context = context
        if context.route == "grounded":
            reply = "Based on my approved sources, " + " ".join(
                passage.text for passage in context.evidence
            )
        elif context.route == "insufficient_evidence":
            reply = "I don't have enough detail to answer that faithfully."
        elif context.route == "privacy_boundary":
            reply = "I keep that part of my life private."
        elif context.route == "redirected":
            reply = (
                "That is better put to the real me or a general-purpose LLM. "
                "I'm here to talk about my experience and work."
            )
        else:
            requests = [
                message.content
                for message in context.messages
                if message.role == "user"
            ]
            reply = "Request history:\n" + "\n".join(requests)
        yield ModelTextDelta(delta=reply)
        if self.fail_stream:
            raise RuntimeError("provider failed")
        yield ModelCompleted(input_tokens=10, output_tokens=5)

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def reset_application_state(monkeypatch: pytest.MonkeyPatch) -> None:
    asyncio.run(conversation_store.clear())
    asyncio.run(usage_ledger.clear())
    ip_rate_limiter.clear()
    session_rate_limiter.clear()
    traffic_monitor.clear()
    monkeypatch.setattr(chat_workflow, "_model", FakeModel())


def post_message(message: str, conversation_id: str | None = None) -> Response:
    body: dict[str, str] = {"message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return client.post("/api/v1/chat", json=body)


def test_json_chat_preserves_the_minimal_public_contract() -> None:
    response = post_message("What did Rowan build at Northstar Mobility?")

    assert response.status_code == 200
    body = response.json()
    assert UUID(body["conversation_id"])
    assert UUID(body["message_id"])
    assert "Lantern" in body["content"]
    assert set(body) == {"conversation_id", "message_id", "content"}
    assert "X-Trace-ID" not in response.headers


def test_chat_uses_context_to_ground_a_follow_up() -> None:
    first = post_message("What did Rowan build at Northstar Mobility?").json()
    second = post_message("What happened next?", first["conversation_id"]).json()

    assert second["conversation_id"] == first["conversation_id"]
    assert "Lantern" in second["content"]
    history = asyncio.run(conversation_store.history(UUID(first["conversation_id"])))
    assert [message.role for message in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert history[0].content == "What did Rowan build at Northstar Mobility?"
    assert history[0].generation_content is not None
    assert "Lantern" in history[0].generation_content
    assert history[0].generation_content.endswith(
        "User question:\nWhat did Rowan build at Northstar Mobility?"
    )


def test_chat_redirects_an_unrelated_request_without_retrieval_metadata() -> None:
    body = post_message("Solve the travelling salesperson problem.").json()

    assert "general-purpose LLM" in body["content"]
    assert "route" not in body
    assert "trace_id" not in body
    assert "citations" not in body


def test_ndjson_events_remain_ordered_and_private() -> None:
    response = client.post(
        "/api/v1/chat",
        headers={"Accept": NDJSON_MEDIA_TYPE},
        json={"message": "Explain Rowan's Harbor work"},
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith(NDJSON_MEDIA_TYPE)
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["type"] == "message_start"
    assert events[-1] == {"type": "message_end"}
    assert [event["type"] for event in events].count("text_delta") >= 1
    assert all("trace_id" not in event for event in events)
    assert all("route" not in event for event in events)


def test_failed_stream_and_budget_rejection_update_prometheus_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_workflow, "_model", FakeModel(fail_stream=True))
    failed = client.post(
        "/api/v1/chat",
        headers={"Accept": NDJSON_MEDIA_TYPE},
        json={"message": "Hello"},
    )
    assert json.loads(failed.text.splitlines()[-1])["type"] == "error"
    assert (
        'maas_chat_outcomes_total{outcome="failed"} 1.0' in client.get("/metrics").text
    )

    monkeypatch.setattr(chat_workflow, "_daily_token_budget", 1)
    asyncio.run(usage_ledger.record(datetime.now(UTC), 1, 0))
    rejected = post_message("Hello")
    assert rejected.status_code == 429
    assert (
        'maas_chat_outcomes_total{outcome="usage_limited"} 1.0'
        in client.get("/metrics").text
    )


@pytest.mark.parametrize(
    ("payload", "status_code"),
    [
        ({"message": "   "}, 422),
        ({"message": "x" * (MAX_MESSAGE_LENGTH + 1)}, 422),
        ({"message": "Hello", "role": "system"}, 422),
    ],
)
def test_chat_validates_client_input(payload: dict[str, str], status_code: int) -> None:
    assert client.post("/api/v1/chat", json=payload).status_code == status_code


def test_chat_rejects_an_unknown_conversation() -> None:
    response = post_message("Hello", str(uuid4()))
    assert response.status_code == 404


def test_rate_and_queue_limits_remain_operational(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_module,
        "ip_rate_limiter",
        SlidingWindowRateLimiter(limit=1, window_seconds=60),
    )
    assert post_message("Hello").status_code == 200
    assert post_message("Hello again").status_code == 429

    class SaturatedGate:
        async def acquire(self) -> None:
            raise QueueSaturated("The service is busy.")

    monkeypatch.setattr(api_module, "inference_gate", SaturatedGate())
    api_module.ip_rate_limiter.clear()
    assert post_message("Hello").status_code == 503


def test_readiness_and_metrics_depend_on_storage_and_usage_not_langsmith() -> None:
    with TestClient(app) as lifespan_client:
        assert lifespan_client.get("/health/ready").status_code == 200
        assert (
            lifespan_client.post("/api/v1/chat", json={"message": "Hello!"}).status_code
            == 200
        )
        response = lifespan_client.get("/metrics")

    assert response.headers["Content-Type"] == CONTENT_TYPE_LATEST
    assert "maas_persistence_ready 1" in response.text
    assert "maas_model_tokens_today 15.0" in response.text


class CountingRetriever:
    def __init__(self, results: tuple[ScopedRetrievalResult, ...]) -> None:
        self.results = results
        self.calls = 0

    def search(self, query: str) -> tuple[ScopedRetrievalResult, ...]:
        self.calls += 1
        return self.results


def _workflow(
    *,
    model: FakeModel,
    retriever: CountingRetriever,
    store: InMemoryConversationStore | None = None,
    ledger: InMemoryUsageLedger | None = None,
    max_turns: int = 20,
    daily_budget: int = 100_000,
    tracing: LangSmithTracing | None = None,
) -> ChatWorkflow:
    return ChatWorkflow(
        store=store or InMemoryConversationStore(),
        usage_ledger=ledger or InMemoryUsageLedger(),
        model=model,
        retriever=retriever,
        prompts=load_prompts(),
        tracing=tracing or LangSmithTracing(False, None, "test", (), {}),
        instance_id=INSTANCE.config.id,
        display_name=INSTANCE.config.display_name,
        personal_terms=INSTANCE.config.routing.personal_terms,
        max_turns_per_conversation=max_turns,
        daily_token_budget=daily_budget,
    )


def _evidence_result() -> ScopedRetrievalResult:
    sources = load_markdown_corpus(INSTANCE.knowledge_directory)
    passage = next(
        passage
        for source in sources
        for passage in source.passages
        if "Lantern" in passage.text
    )
    return ScopedRetrievalResult(
        passage=passage,
        score=1.0,
        scope="resume",
        rank_within_scope=1,
    )


def _further_reading_results() -> tuple[ScopedRetrievalResult, ...]:
    paper = FurtherReading(label="Paper", url="https://example.org/paper")
    code = FurtherReading(label="Code", url="https://example.org/code")
    passages = (
        Passage(
            passage_id="lantern:one",
            source_id="lantern",
            section_path=("Approved account",),
            text="Lantern routed incidents to the on-call engineer.",
            ordinal=0,
            further_reading=(paper,),
        ),
        Passage(
            passage_id="lantern:two",
            source_id="lantern",
            section_path=("Approved account",),
            text="Lantern cut triage time for the operations team.",
            ordinal=1,
            further_reading=(code,),
        ),
    )
    return tuple(
        ScopedRetrievalResult(
            passage=passage,
            score=1.0,
            scope="personal",
            rank_within_scope=rank,
        )
        for rank, passage in enumerate(passages, start=1)
    )


def test_grounded_turn_streams_each_source_link_once_before_the_answer_ends() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        workflow = _workflow(
            model=FakeModel(analysis=TurnAnalysis("retrieval", "What was Lantern?")),
            retriever=CountingRetriever(_further_reading_results()),
            store=store,
        )
        events = [
            event
            async for event in workflow.stream_turn(
                conversation_id=conversation_id,
                message="What was Lantern?",
                message_id=uuid4(),
            )
        ]

        assert [event.type for event in events][-2:] == [
            "further_reading",
            "message_end",
        ]
        links = next(
            event.links for event in events if isinstance(event, FurtherReadingEvent)
        )
        assert [(link.label, link.url) for link in links] == [
            ("Paper", "https://example.org/paper"),
            ("Code", "https://example.org/code"),
        ]

    asyncio.run(exercise())


def test_insufficient_evidence_turn_withholds_further_reading() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        workflow = _workflow(
            model=FakeModel(
                judge_result=False,
                analysis=TurnAnalysis("retrieval", "What was Lantern?"),
            ),
            retriever=CountingRetriever(_further_reading_results()),
            store=store,
        )
        events = [
            event
            async for event in workflow.stream_turn(
                conversation_id=conversation_id,
                message="What was Lantern?",
                message_id=uuid4(),
            )
        ]

        assert not any(isinstance(event, FurtherReadingEvent) for event in events)

    asyncio.run(exercise())


def test_public_context_falls_back_to_web_search_and_exposes_citations() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        ledger = InMemoryUsageLedger()
        conversation_id = await store.create()
        model = FakeModel(
            judge_result=False,
            analysis=TurnAnalysis("public_context", "Who currently leads RPG?"),
        )
        workflow = _workflow(
            model=model,
            retriever=CountingRetriever(()),
            store=store,
            ledger=ledger,
        )

        events = [
            event
            async for event in workflow.stream_turn(
                conversation_id=conversation_id,
                message="Who is the head of RPG?",
                message_id=uuid4(),
            )
        ]

        assert model.web_search_calls == 1
        assert model.context is None
        assert any(
            isinstance(event, TextDeltaEvent)
            and "Prof. Davide Scaramuzza" in event.delta
            for event in events
        )
        links = next(
            event.links for event in events if isinstance(event, FurtherReadingEvent)
        )
        assert links == (
            FurtherReading(label="RPG people", url="https://rpg.example/people"),
        )
        boundary = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        assert await ledger.tokens_since(boundary) == 28

    asyncio.run(exercise())


def test_public_context_prefers_sufficient_curated_evidence() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        model = FakeModel(
            analysis=TurnAnalysis("public_context", "Who currently leads RPG?"),
        )
        workflow = _workflow(
            model=model,
            retriever=CountingRetriever((_evidence_result(),)),
            store=store,
        )

        await workflow.complete_turn(
            conversation_id=conversation_id,
            message="Who is the head of RPG?",
            message_id=uuid4(),
        )

        assert model.web_search_calls == 0
        assert model.context is not None
        assert model.context.route == "grounded"

    asyncio.run(exercise())


def test_public_context_web_search_failure_fails_closed() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        model = FakeModel(
            analysis=TurnAnalysis("public_context", "Who currently leads RPG?"),
            fail_web_search=True,
        )
        workflow = _workflow(
            model=model,
            retriever=CountingRetriever(()),
            store=store,
        )

        response = await workflow.complete_turn(
            conversation_id=conversation_id,
            message="Who is the head of RPG?",
            message_id=uuid4(),
        )

        assert "enough detail" in response.content
        assert model.web_search_calls == 1
        assert model.context is not None
        assert model.context.route == "insufficient_evidence"

    asyncio.run(exercise())


def test_only_selected_evidence_reaches_generation_and_further_reading() -> None:
    async def exercise() -> None:
        results = _further_reading_results()
        selected_id = results[1].passage.passage_id
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        model = FakeModel(
            analysis=TurnAnalysis("retrieval", "What was Lantern?"),
            supporting_passage_ids=(selected_id,),
        )
        workflow = _workflow(
            model=model,
            retriever=CountingRetriever(results),
            store=store,
        )

        events = [
            event
            async for event in workflow.stream_turn(
                conversation_id=conversation_id,
                message="What was Lantern?",
                message_id=uuid4(),
            )
        ]

        assert model.context is not None
        assert [passage.passage_id for passage in model.context.evidence] == [
            selected_id
        ]
        links = next(
            event.links for event in events if isinstance(event, FurtherReadingEvent)
        )
        assert [(link.label, link.url) for link in links] == [
            ("Code", "https://example.org/code")
        ]

    asyncio.run(exercise())


def test_assessment_selection_is_restored_to_candidate_order() -> None:
    async def exercise() -> None:
        results = _further_reading_results()
        reversed_ids = tuple(result.passage.passage_id for result in reversed(results))
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        model = FakeModel(
            analysis=TurnAnalysis("retrieval", "What was Lantern?"),
            supporting_passage_ids=reversed_ids,
        )
        workflow = _workflow(
            model=model,
            retriever=CountingRetriever(results),
            store=store,
        )

        await workflow.complete_turn(
            conversation_id=conversation_id,
            message="What was Lantern?",
            message_id=uuid4(),
        )

        assert model.context is not None
        assert [passage.passage_id for passage in model.context.evidence] == [
            result.passage.passage_id for result in results
        ]

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "selected_ids",
    (
        ("lantern:one", "lantern:one"),
        ("unknown",),
        (),
    ),
)
def test_invalid_evidence_assessment_fails_closed(
    selected_ids: tuple[str, ...],
) -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        model = FakeModel(
            analysis=TurnAnalysis("retrieval", "What was Lantern?"),
            supporting_passage_ids=selected_ids,
        )
        workflow = _workflow(
            model=model,
            retriever=CountingRetriever(_further_reading_results()),
            store=store,
        )

        response = await workflow.complete_turn(
            conversation_id=conversation_id,
            message="What was Lantern?",
            message_id=uuid4(),
        )

        assert "enough detail" in response.content
        assert model.context is not None
        assert model.context.route == "insufficient_evidence"
        assert model.context.evidence == ()

    asyncio.run(exercise())


def test_empty_retrieval_skips_evidence_assessment() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        model = FakeModel(analysis=TurnAnalysis("retrieval", "Missing evidence"))
        workflow = _workflow(
            model=model,
            retriever=CountingRetriever(()),
            store=store,
        )

        await workflow.complete_turn(
            conversation_id=conversation_id,
            message="Missing evidence",
            message_id=uuid4(),
        )

        assert model.assessment_calls == 0
        assert model.context is not None
        assert model.context.route == "insufficient_evidence"

    asyncio.run(exercise())


def test_evidence_assessment_failure_fails_closed() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        model = FakeModel(
            analysis=TurnAnalysis("retrieval", "What was Lantern?"),
            fail_assessment=True,
        )
        workflow = _workflow(
            model=model,
            retriever=CountingRetriever(_further_reading_results()),
            store=store,
        )

        await workflow.complete_turn(
            conversation_id=conversation_id,
            message="What was Lantern?",
            message_id=uuid4(),
        )

        assert model.assessment_calls == 1
        assert model.context is not None
        assert model.context.route == "insufficient_evidence"
        assert model.context.evidence == ()

    asyncio.run(exercise())


def test_ndjson_stream_publishes_further_reading_as_labeled_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat_workflow, "_retriever", CountingRetriever(_further_reading_results())
    )
    response = client.post(
        "/api/v1/chat",
        headers={"Accept": NDJSON_MEDIA_TYPE},
        json={"message": "What was Lantern at Northstar?"},
    )

    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-2] == {
        "type": "further_reading",
        "links": [
            {"label": "Paper", "url": "https://example.org/paper"},
            {"label": "Code", "url": "https://example.org/code"},
        ],
    }
    assert all("passage_id" not in json.dumps(event) for event in events)


@pytest.mark.parametrize(
    ("route", "expected_calls"),
    [
        ("conversational", 0),
        ("privacy_boundary", 0),
        ("redirected", 0),
        ("retrieval", 1),
        ("public_context", 1),
    ],
)
def test_workflow_performs_zero_or_one_retrieval(
    route: str, expected_calls: int
) -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        retriever = CountingRetriever((_evidence_result(),))
        workflow = _workflow(
            model=FakeModel(
                analysis=TurnAnalysis(
                    cast(AnalysisRoute, route),
                    (
                        "What did Rowan build?"
                        if route in {"retrieval", "public_context"}
                        else None
                    ),
                )
            ),
            retriever=retriever,
            store=store,
        )
        await workflow.complete_turn(
            conversation_id=conversation_id,
            message="What did Rowan build?",
            message_id=uuid4(),
        )
        assert retriever.calls == expected_calls

    asyncio.run(exercise())


def test_privacy_boundary_skips_retrieval_and_uses_its_own_response_path() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        retriever = CountingRetriever((_evidence_result(),))
        model = FakeModel(analysis=TurnAnalysis("privacy_boundary", None))
        workflow = _workflow(model=model, retriever=retriever, store=store)

        response = await workflow.complete_turn(
            conversation_id=conversation_id,
            message="Are you married?",
            message_id=uuid4(),
        )

        assert response.content == "I keep that part of my life private."
        assert retriever.calls == 0
        assert model.context is not None
        assert model.context.route == "privacy_boundary"

    asyncio.run(exercise())


def test_workflow_records_usage_after_completion() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        ledger = InMemoryUsageLedger()
        conversation_id = await store.create()
        workflow = _workflow(
            model=FakeModel(),
            retriever=CountingRetriever(()),
            store=store,
            ledger=ledger,
        )
        await workflow.complete_turn(
            conversation_id=conversation_id,
            message="Hello",
            message_id=uuid4(),
        )
        boundary = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        assert await ledger.tokens_since(boundary) == 15

    asyncio.run(exercise())


def test_failed_stream_does_not_persist_a_partial_turn_or_usage() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        ledger = InMemoryUsageLedger()
        conversation_id = await store.create()
        workflow = _workflow(
            model=FakeModel(fail_stream=True),
            retriever=CountingRetriever(()),
            store=store,
            ledger=ledger,
        )
        with pytest.raises(RuntimeError, match="provider failed"):
            await workflow.complete_turn(
                conversation_id=conversation_id,
                message="Hello",
                message_id=uuid4(),
            )
        assert await store.history(conversation_id) == ()

    asyncio.run(exercise())


def test_cancelled_stream_does_not_persist_a_partial_turn() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        workflow = _workflow(
            model=FakeModel(),
            retriever=CountingRetriever(()),
            store=store,
        )
        events = workflow.stream_turn(
            conversation_id=conversation_id,
            message="Hello",
            message_id=uuid4(),
        )
        first = await anext(events)
        assert first.type == "message_start"
        await cast(AsyncGenerator[ChatEvent, None], events).aclose()
        assert await store.history(conversation_id) == ()

    asyncio.run(exercise())


def test_workflow_enforces_turn_and_daily_token_limits() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        ledger = InMemoryUsageLedger()
        conversation_id = await store.create()
        await store.append_turn(
            conversation_id,
            StoredMessage(id=uuid4(), role="user", content="question"),
            StoredMessage(id=uuid4(), role="assistant", content="answer"),
        )
        workflow = _workflow(
            model=FakeModel(),
            retriever=CountingRetriever(()),
            store=store,
            ledger=ledger,
            max_turns=1,
        )
        with pytest.raises(UsageLimitExceeded, match="turn limit"):
            await workflow.complete_turn(
                conversation_id=conversation_id,
                message="again",
                message_id=uuid4(),
            )

        empty_store = InMemoryConversationStore()
        empty_id = await empty_store.create()
        await ledger.record(datetime.now(UTC), 90, 10)
        budget_workflow = _workflow(
            model=FakeModel(),
            retriever=CountingRetriever(()),
            store=empty_store,
            ledger=ledger,
            daily_budget=100,
        )
        with pytest.raises(UsageLimitExceeded, match="daily model budget"):
            await budget_workflow.complete_turn(
                conversation_id=empty_id,
                message="Hello",
                message_id=uuid4(),
            )

    asyncio.run(exercise())


def test_context_assembler_keeps_complete_past_turns_and_current_prompt() -> None:
    history = (
        StoredMessage(id=uuid4(), role="user", content="question 1"),
        StoredMessage(id=uuid4(), role="assistant", content="answer 1"),
        StoredMessage(id=uuid4(), role="user", content="question 2"),
        StoredMessage(id=uuid4(), role="assistant", content="answer 2"),
        StoredMessage(id=uuid4(), role="user", content="current"),
    )
    context = ContextAssembler(past_turn_limit=1, character_limit=100).assemble(
        history, "system"
    )
    assert [message.content for message in context.messages] == [
        "question 2",
        "answer 2",
        "current",
    ]
    assert context.system_policy == "system"


def test_context_assembler_drops_a_whole_turn_at_the_character_limit() -> None:
    history = (
        StoredMessage(id=uuid4(), role="user", content="long question"),
        StoredMessage(id=uuid4(), role="assistant", content="answer"),
        StoredMessage(id=uuid4(), role="user", content="current"),
    )

    context = ContextAssembler(character_limit=10).assemble(history, "system")

    assert [message.content for message in context.messages] == ["current"]


def test_context_assembler_counts_lean_prompts_for_past_turns() -> None:
    history = (
        StoredMessage(
            id=uuid4(),
            role="user",
            content="question",
            generation_content="past evidence that is not replayed",
        ),
        StoredMessage(id=uuid4(), role="assistant", content="answer"),
        StoredMessage(
            id=uuid4(),
            role="user",
            content="current",
            generation_content="full current prompt",
        ),
    )

    context = ContextAssembler(character_limit=34).assemble(history, "system")

    assert [message.content for message in context.messages] == [
        "question",
        "answer",
        "current",
    ]


def test_workflow_bounds_history_for_routing_and_generation() -> None:
    async def exercise() -> None:
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        for index in range(8):
            await store.append_turn(
                conversation_id,
                StoredMessage(id=uuid4(), role="user", content=f"question {index}"),
                StoredMessage(id=uuid4(), role="assistant", content=f"answer {index}"),
            )
        model = FakeModel()
        workflow = _workflow(
            model=model,
            retriever=CountingRetriever(()),
            store=store,
        )
        await workflow.complete_turn(
            conversation_id=conversation_id,
            message="latest",
            message_id=uuid4(),
        )
        assert model.analysis_history is not None
        assert len(model.analysis_history) == MAX_PAST_TURNS * 2
        assert model.context is not None
        assert len(model.context.messages) == MAX_PAST_TURNS * 2 + 1
        assert [message.content for message in model.context.messages] == [
            "question 2",
            "answer 2",
            "question 3",
            "answer 3",
            "question 4",
            "answer 4",
            "question 5",
            "answer 5",
            "question 6",
            "answer 6",
            "question 7",
            "answer 7",
            "latest",
        ]

    asyncio.run(exercise())


class CapturingLangSmithClient:
    otel_exporter = None

    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.updated: list[dict[str, object]] = []

    def create_run(self, **kwargs: object) -> None:
        self.created.append(kwargs)

    def update_run(self, **kwargs: object) -> None:
        self.updated.append(kwargs)

    def flush(self, timeout: float | None = None) -> None:
        return None


def test_langsmith_trace_tree_mirrors_meaningful_workflow_steps() -> None:
    async def exercise() -> None:
        captured = CapturingLangSmithClient()
        tracing = LangSmithTracing(
            True,
            cast(Client, captured),
            "test-project",
            ("test",),
            {"environment": "test", "prompt_revision": "revision"},
        )
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        workflow = _workflow(
            model=FakeModel(
                analysis=TurnAnalysis("retrieval", "What was Lantern at Northstar?")
            ),
            retriever=CountingRetriever((_evidence_result(),)),
            store=store,
            tracing=tracing,
        )
        await workflow.complete_turn(
            conversation_id=conversation_id,
            message="What was Lantern at Northstar?",
            message_id=uuid4(),
        )

        names = {cast(str, run["name"]) for run in captured.created}
        root = next(run for run in captured.created if run.get("parent_run_id") is None)
        trace_id = cast(UUID, root["id"])
        assert root["name"] == str(trace_id)
        assert names == {
            str(trace_id),
            "analyze_turn",
            "retrieve_evidence",
            "assess_evidence",
        }
        children = [run for run in captured.created if run is not root]
        assert all(run["parent_run_id"] == root["id"] for run in children)
        retrieval_update = next(
            run for run in captured.updated if run["name"] == "retrieve_evidence"
        )
        retrieval_outputs = cast(dict[str, object], retrieval_update["outputs"])
        retrieval_results = cast(list[dict[str, object]], retrieval_outputs["results"])
        assert retrieval_results[0]["scope"] == "resume"
        assert retrieval_results[0]["rank_within_scope"] == 1
        assert "rank" not in retrieval_results[0]
        root_update = next(
            run for run in captured.updated if run["name"] == str(trace_id)
        )
        outputs = cast(dict[str, object], root_update["outputs"])
        assert outputs["outcome"] == "completed"
        assert outputs["route"] == "grounded"
        inputs = cast(dict[str, object], root_update["inputs"])
        assert inputs["message"] == "What was Lantern at Northstar?"
        assert "conversation_id" not in inputs
        assert "message_id" not in inputs
        assert "instance" not in inputs
        assert "bounded_conversation_history" not in inputs
        extra = cast(dict[str, object], root_update["extra"])
        metadata = cast(dict[str, object], extra["metadata"])
        assert metadata["bounded_conversation_history"] == ()
        assert metadata["conversation_id"] == str(conversation_id)
        assert metadata["session_id"] == str(conversation_id)
        assert metadata["instance"] == INSTANCE.config.id
        assert UUID(cast(str, metadata["message_id"]))
        assert metadata["model"] == "fake-model"
        assert metadata["prompt_revision"] == load_prompts().revision

    asyncio.run(exercise())


class FailingLangSmithClient(CapturingLangSmithClient):
    def create_run(self, **kwargs: object) -> None:
        raise RuntimeError("telemetry unavailable")

    def update_run(self, **kwargs: object) -> None:
        raise RuntimeError("telemetry unavailable")


def test_langsmith_transport_failure_is_fail_open() -> None:
    async def exercise() -> None:
        tracing = LangSmithTracing(
            True,
            cast(Client, FailingLangSmithClient()),
            "test-project",
            (),
            {},
        )
        store = InMemoryConversationStore()
        conversation_id = await store.create()
        workflow = _workflow(
            model=FakeModel(),
            retriever=CountingRetriever(()),
            store=store,
            tracing=tracing,
        )

        response = await workflow.complete_turn(
            conversation_id=conversation_id,
            message="Hello",
            message_id=uuid4(),
        )

        assert "Request history" in response.content
        assert len(await store.history(conversation_id)) == 2

    asyncio.run(exercise())
