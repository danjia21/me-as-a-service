import asyncio
from collections.abc import AsyncIterator
from importlib.metadata import version
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from langsmith import Client
from openai import AsyncOpenAI

import me_as_a_service.chat.model as model_module
from me_as_a_service.chat.model import (
    EVIDENCE_JUDGE_MAX_OUTPUT_TOKENS,
    ModelCompleted,
    ModelTextDelta,
    OpenAIChatModel,
    openai_model_from_environment,
    tracing_from_environment,
)
from me_as_a_service.chat.prompts import load_prompts
from me_as_a_service.chat.types import (
    ConversationContext,
    EvidenceAssessment,
    StoredMessage,
    TurnAnalysis,
)
from me_as_a_service.knowledge.models import Passage


def test_langsmith_runtime_version_is_pinned() -> None:
    assert version("langsmith") == "0.10.14"


class FakeStream:
    def __init__(self, *, include_usage: bool = True) -> None:
        self._include_usage = include_usage

    async def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello "))],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="there."))],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[],
            usage=(
                SimpleNamespace(prompt_tokens=42, completion_tokens=7)
                if self._include_usage
                else None
            ),
        )


class FakeCompletions:
    def __init__(
        self,
        *,
        include_usage: bool = True,
        assessment_content: str | None = (
            '{"supporting_passage_ids":["passage-1"],"sufficient":true}'
        ),
        assessment_finish_reason: str = "stop",
    ) -> None:
        self.include_usage = include_usage
        self.assessment_content = assessment_content
        self.assessment_finish_reason = assessment_finish_reason
        self.request: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> object:
        self.request = kwargs
        if kwargs.get("stream"):
            return FakeStream(include_usage=self.include_usage)
        response_format = cast(dict[str, object], kwargs["response_format"])
        schema = cast(dict[str, object], response_format["json_schema"])
        content = (
            '{"route":"retrieval","retrieval_query":"standalone query"}'
            if schema["name"] == "turn_analysis"
            else self.assessment_content
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason=(
                        self.assessment_finish_reason
                        if schema["name"] == "evidence_assessment"
                        else "stop"
                    ),
                )
            ]
        )


class FakeClient:
    def __init__(
        self,
        *,
        include_usage: bool = True,
        assessment_content: str | None = (
            '{"supporting_passage_ids":["passage-1"],"sufficient":true}'
        ),
        assessment_finish_reason: str = "stop",
    ) -> None:
        self.completions = FakeCompletions(
            include_usage=include_usage,
            assessment_content=assessment_content,
            assessment_finish_reason=assessment_finish_reason,
        )
        self.chat = SimpleNamespace(completions=self.completions)
        self.responses = FakeResponses()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeResponses:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> object:
        self.request = kwargs
        citation = SimpleNamespace(
            type="url_citation",
            start_index=14,
            end_index=24,
            title="RPG people",
            url="https://rpg.example/people",
        )
        output_text = SimpleNamespace(
            type="output_text",
            text="RPG is led by Scaramuzza.",
            annotations=[citation],
        )
        return SimpleNamespace(
            output=[SimpleNamespace(type="message", content=[output_text])],
            usage=SimpleNamespace(input_tokens=21, output_tokens=6),
        )


def _context() -> ConversationContext:
    return ConversationContext(
        system_policy="System policy.",
        messages=(
            StoredMessage(
                id=uuid4(),
                role="user",
                content="Question?",
                generation_content=(
                    "Grounded instruction.\n\nPublic evidence:\n"
                    "- Complete evidence.\n\nUser question:\nQuestion?"
                ),
            ),
        ),
        route="grounded",
        evidence=(
            Passage(
                passage_id="passage-1",
                source_id="source-1",
                section_path=("Work",),
                text="Complete evidence.",
                ordinal=0,
            ),
        ),
    )


def test_openai_model_streams_text_and_requires_final_usage() -> None:
    async def exercise() -> None:
        fake = FakeClient()
        model = OpenAIChatModel(
            cast(AsyncOpenAI, fake),
            model="test-model",
            prompts=load_prompts(),
            max_output_tokens=123,
        )
        events = [event async for event in model.stream(_context())]

        assert events == [
            ModelTextDelta(delta="Hello "),
            ModelTextDelta(delta="there."),
            ModelCompleted(input_tokens=42, output_tokens=7),
        ]
        request = fake.completions.request
        assert request is not None
        assert request["model"] == "test-model"
        assert request["stream_options"] == {"include_usage": True}
        assert request["max_completion_tokens"] == 123
        messages = cast(list[dict[str, str]], request["messages"])
        assert messages[0] == {"role": "system", "content": "System policy."}
        assert messages[1]["role"] == "user"
        assert "Complete evidence." in messages[1]["content"]
        assert messages[1]["content"].endswith("User question:\nQuestion?")

    asyncio.run(exercise())


def test_openai_model_fails_closed_when_stream_usage_is_missing() -> None:
    async def exercise() -> None:
        model = OpenAIChatModel(
            cast(AsyncOpenAI, FakeClient(include_usage=False)),
            model="test-model",
            prompts=load_prompts(),
        )
        with pytest.raises(RuntimeError, match="without final token usage"):
            _ = [event async for event in model.stream(_context())]

    asyncio.run(exercise())


def test_generation_adapter_uses_lean_history_and_current_full_prompt() -> None:
    history = tuple(
        StoredMessage(
            id=uuid4(),
            role="user" if index % 2 == 0 else "assistant",
            content=f"message {index}",
            generation_content=(f"combined {index}" if index % 2 == 0 else None),
        )
        for index in range(7)
    )

    messages = model_module._history_messages(
        "System policy.", history, for_generation=True
    )

    assert len(messages) == 8
    assert messages[1] == {"role": "user", "content": "message 0"}
    assert messages[3] == {"role": "user", "content": "message 2"}
    assert messages[5] == {"role": "user", "content": "message 4"}
    assert messages[-1] == {"role": "user", "content": "combined 6"}


def test_openai_structured_calls_share_the_same_client() -> None:
    async def exercise() -> None:
        fake = FakeClient()
        model = OpenAIChatModel(
            cast(AsyncOpenAI, fake), model="test-model", prompts=load_prompts()
        )
        history = (
            StoredMessage(
                id=uuid4(),
                role="user",
                content="Earlier",
                generation_content="Internal evidence.\n\nUser question:\nEarlier",
            ),
        )

        assert await model.analyze_turn(
            "What happened next?", history, "Analyze."
        ) == TurnAnalysis(route="retrieval", retrieval_query="standalone query")
        analysis_request = fake.completions.request
        assert analysis_request is not None
        analysis_messages = cast(list[dict[str, str]], analysis_request["messages"])
        assert analysis_messages[1] == {"role": "user", "content": "Earlier"}
        assert await model.assess_evidence(
            "What happened next?", "standalone query", _context().evidence
        ) == EvidenceAssessment(supporting_passage_ids=("passage-1",), sufficient=True)
        request = fake.completions.request
        assert request is not None
        assert request["max_completion_tokens"] == EVIDENCE_JUDGE_MAX_OUTPUT_TOKENS
        messages = cast(list[dict[str, str]], request["messages"])
        assert "Passage ID: passage-1" in messages[1]["content"]
        assert "Source: source-1 [source-1]" in messages[1]["content"]

    asyncio.run(exercise())


def test_openai_web_search_returns_clickable_citations_and_links() -> None:
    async def exercise() -> None:
        fake = FakeClient()
        model = OpenAIChatModel(
            cast(AsyncOpenAI, fake), model="test-model", prompts=load_prompts()
        )

        result = await model.search_web(
            "Who is the head of RPG?", "Who currently leads RPG?"
        )

        assert result.content == (
            "RPG is led by [Scaramuzza](https://rpg.example/people)."
        )
        assert [(link.label, link.url) for link in result.links] == [
            ("RPG people", "https://rpg.example/people")
        ]
        assert (result.input_tokens, result.output_tokens) == (21, 6)
        request = fake.responses.request
        assert request is not None
        assert request["model"] == "test-model"
        assert request["tool_choice"] == "required"
        assert request["max_tool_calls"] == 1
        assert request["parallel_tool_calls"] is False
        assert request["tools"] == [
            {"type": "web_search", "search_context_size": "low"}
        ]
        assert "Who currently leads RPG?" in cast(str, request["input"])

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("section_path", "expected_section"),
    (
        ((), None),
        (("Approved account",), None),
        (("Experience", "Researcher"), "Section: Experience > Researcher"),
    ),
)
def test_assessment_candidate_only_renders_informative_sections(
    section_path: tuple[str, ...], expected_section: str | None
) -> None:
    passage = Passage(
        passage_id="passage",
        source_id="source",
        section_path=section_path,
        text="Evidence text.",
        ordinal=0,
    )

    rendered = model_module._render_assessment_candidate(passage)

    if expected_section is None:
        assert "Section:" not in rendered
    else:
        assert expected_section in rendered


@pytest.mark.parametrize(
    ("content", "expected"),
    (
        (
            '{"supporting_passage_ids":[],"sufficient":false}',
            EvidenceAssessment(supporting_passage_ids=(), sufficient=False),
        ),
        (
            '{"supporting_passage_ids":["passage-1"],"sufficient":false}',
            EvidenceAssessment(supporting_passage_ids=("passage-1",), sufficient=False),
        ),
        (
            '{"supporting_passage_ids":["passage-2","passage-1"],"sufficient":true}',
            EvidenceAssessment(
                supporting_passage_ids=("passage-2", "passage-1"), sufficient=True
            ),
        ),
    ),
)
def test_openai_model_parses_evidence_selections(
    content: str, expected: EvidenceAssessment
) -> None:
    async def exercise() -> None:
        fake = FakeClient(assessment_content=content)
        model = OpenAIChatModel(
            cast(AsyncOpenAI, fake), model="test-model", prompts=load_prompts()
        )
        evidence = (
            *_context().evidence,
            Passage(
                passage_id="passage-2",
                source_id="source-2",
                source_title="Second source",
                section_path=(),
                text="Additional evidence.",
                ordinal=0,
            ),
        )

        assert (
            await model.assess_evidence("Question?", "retrieval query", evidence)
            == expected
        )

    asyncio.run(exercise())


def test_openai_model_reports_length_when_assessment_emits_no_json() -> None:
    async def exercise() -> None:
        model = OpenAIChatModel(
            cast(
                AsyncOpenAI,
                FakeClient(
                    assessment_content=None,
                    assessment_finish_reason="length",
                ),
            ),
            model="test-model",
            prompts=load_prompts(),
        )

        with pytest.raises(RuntimeError, match="finish_reason='length'"):
            await model.assess_evidence(
                "What was your PhD research about?",
                "What was Avery Chen's PhD research about?",
                _context().evidence,
            )

    asyncio.run(exercise())


def test_langsmith_is_disabled_by_default_and_does_not_wrap_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("MAAS_LLM_MODEL", raising=False)
    wrapped = False

    class ConstructorFake(FakeClient):
        def __init__(self, *, api_key: str) -> None:
            super().__init__()
            self.api_key = api_key

    def fail_if_wrapped(client: object, **_: object) -> object:
        nonlocal wrapped
        wrapped = True
        return client

    monkeypatch.setattr(model_module, "AsyncOpenAI", ConstructorFake)
    monkeypatch.setattr(model_module, "wrap_openai", fail_if_wrapped)
    tracing = tracing_from_environment(
        instance_id="test", model="test-model", prompt_revision="revision"
    )

    model = openai_model_from_environment(tracing, load_prompts())

    assert not tracing.enabled
    assert model.model == "gpt-5.4-mini-2026-03-17"
    assert not wrapped


def test_openai_key_is_required_for_runtime_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tracing = model_module.LangSmithTracing(False, None, "test", (), {})

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is required"):
        openai_model_from_environment(tracing, load_prompts())


def test_enabled_langsmith_wraps_the_single_openai_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MAAS_LLM_MODEL", "test-model")
    wrapped: dict[str, object] = {}

    class ConstructorFake(FakeClient):
        def __init__(self, *, api_key: str) -> None:
            super().__init__()
            self.api_key = api_key

    def capture_wrap(client: object, **kwargs: object) -> object:
        wrapped["client"] = client
        wrapped.update(kwargs)
        return client

    monkeypatch.setattr(model_module, "AsyncOpenAI", ConstructorFake)
    monkeypatch.setattr(model_module, "wrap_openai", capture_wrap)
    fake_langsmith = cast(Client, SimpleNamespace())
    tracing = model_module.LangSmithTracing(True, fake_langsmith, "test", (), {})

    model = openai_model_from_environment(tracing, load_prompts())

    assert model.model == "test-model"
    assert isinstance(wrapped["client"], ConstructorFake)
    assert wrapped["chat_name"] == "openai_generation"
    assert wrapped["tracing_extra"] == {"client": fake_langsmith}


def test_langsmith_configuration_selects_project_endpoint_and_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}

    class FakeLangSmithClient:
        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "trace-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "custom-project")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://trace.test")
    monkeypatch.setenv("LANGSMITH_WORKSPACE_ID", "workspace-id")
    monkeypatch.setattr(model_module, "Client", FakeLangSmithClient)

    tracing = tracing_from_environment(
        instance_id="instance", model="model", prompt_revision="revision"
    )

    assert tracing.enabled
    assert tracing.project == "custom-project"
    assert created["api_url"] == "https://trace.test"
    assert created["api_key"] == "trace-key"
    assert created["workspace_id"] == "workspace-id"
