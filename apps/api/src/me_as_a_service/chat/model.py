from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol, cast

from langsmith import Client, tracing_context
from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ConfigDict, model_validator

from me_as_a_service.chat.prompts import PromptSet
from me_as_a_service.chat.types import (
    AnalysisRoute,
    ConversationContext,
    EvidenceAssessment,
    StoredMessage,
    TurnAnalysis,
)
from me_as_a_service.knowledge.models import FurtherReading, Passage

DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MAX_OUTPUT_TOKENS = 300
EVIDENCE_JUDGE_MAX_OUTPUT_TOKENS = 1024
DEFAULT_LANGSMITH_PROJECT = "me-as-a-service"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelTextDelta:
    delta: str


@dataclass(frozen=True)
class ModelCompleted:
    input_tokens: int
    output_tokens: int


ModelEvent = ModelTextDelta | ModelCompleted


@dataclass(frozen=True)
class WebSearchResult:
    content: str
    links: tuple[FurtherReading, ...]
    input_tokens: int
    output_tokens: int


class ChatModel(Protocol):
    model: str

    async def analyze_turn(
        self,
        message: str,
        history: tuple[StoredMessage, ...],
        policy: str,
    ) -> TurnAnalysis: ...

    async def assess_evidence(
        self,
        question: str,
        retrieval_query: str,
        evidence: tuple[Passage, ...],
    ) -> EvidenceAssessment: ...

    async def search_web(self, question: str, query: str) -> WebSearchResult: ...

    def stream(self, context: ConversationContext) -> AsyncIterator[ModelEvent]: ...

    async def close(self) -> None: ...


class _StructuredTurnAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route: AnalysisRoute
    retrieval_query: str | None

    @model_validator(mode="after")
    def validate_retrieval_query(self) -> _StructuredTurnAnalysis:
        if self.route in {"retrieval", "public_context"}:
            if self.retrieval_query is None or not self.retrieval_query.strip():
                raise ValueError("retrieval route requires a non-blank query")
        elif self.retrieval_query is not None:
            raise ValueError("non-retrieval routes require a null query")
        return self


class OpenAIChatModel:
    """Production model calls through one OpenAI-compatible SDK client."""

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        prompts: PromptSet,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        web_search_tool_type: str = "web_search",
    ) -> None:
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self.model = model
        self._client = client
        self._prompts = prompts
        self._max_output_tokens = max_output_tokens
        self._web_search_tool_type = web_search_tool_type

    async def analyze_turn(
        self,
        message: str,
        history: tuple[StoredMessage, ...],
        policy: str,
    ) -> TurnAnalysis:
        messages = _history_messages(policy, history)
        messages.append({"role": "user", "content": message})
        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "turn_analysis",
                    "strict": True,
                    "schema": _StructuredTurnAnalysis.model_json_schema(),
                },
            },
        )
        content = completion.choices[0].message.content
        if content is None:
            raise RuntimeError("turn analysis returned no structured content")
        analysis = _StructuredTurnAnalysis.model_validate_json(content)
        query = (
            analysis.retrieval_query.strip()
            if analysis.retrieval_query is not None
            else None
        )
        return TurnAnalysis(route=analysis.route, retrieval_query=query)

    async def assess_evidence(
        self,
        question: str,
        retrieval_query: str,
        evidence: tuple[Passage, ...],
    ) -> EvidenceAssessment:
        rendered_evidence = "\n\n".join(
            _render_assessment_candidate(passage) for passage in evidence
        )
        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._prompts.evidence_sufficiency},
                {
                    "role": "user",
                    "content": (
                        f"Original question:\n{question}\n\n"
                        f"Retrieval query:\n{retrieval_query}\n\n"
                        f"Evidence:\n{rendered_evidence}"
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "evidence_assessment",
                    "strict": True,
                    "schema": EvidenceAssessment.model_json_schema(),
                },
            },
            # Reasoning tokens count toward this limit. A very small allowance can
            # therefore produce finish_reason="length" before any JSON is emitted.
            max_completion_tokens=EVIDENCE_JUDGE_MAX_OUTPUT_TOKENS,
        )
        content = completion.choices[0].message.content
        if content is None:
            finish_reason = completion.choices[0].finish_reason
            raise RuntimeError(
                "evidence assessment returned no decision "
                f"(finish_reason={finish_reason!r})"
            )
        return EvidenceAssessment.model_validate_json(content)

    async def search_web(self, question: str, query: str) -> WebSearchResult:
        web_search_tool: dict[str, Any] = {"type": self._web_search_tool_type}
        if self._web_search_tool_type == "web_search":
            web_search_tool["search_context_size"] = "low"
        responses = cast(Any, self._client.responses)
        response = await responses.create(
            model=self.model,
            instructions=self._prompts.web_grounded,
            input=(f"Standalone search query:\n{query}\n\nUser question:\n{question}"),
            tools=[web_search_tool],
            tool_choice="required",
            max_tool_calls=1,
            parallel_tool_calls=False,
            max_output_tokens=self._max_output_tokens,
        )
        if response.usage is None:
            raise RuntimeError("OpenAI web search returned no usage metadata")

        text: str | None = None
        annotations: list[Any] = []
        for item in response.output:
            if item.type != "message":
                continue
            for content in item.content:
                if content.type == "output_text":
                    text = content.text
                    annotations.extend(content.annotations)
        if not text:
            raise RuntimeError("OpenAI web search returned no answer text")

        citations = tuple(
            annotation
            for annotation in annotations
            if annotation.type == "url_citation"
            and annotation.url.startswith(("https://", "http://"))
        )
        links = _web_citation_links(citations)
        if not links:
            raise RuntimeError("OpenAI web search returned no URL citations")
        return WebSearchResult(
            content=_render_clickable_citations(text, citations),
            links=links,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    async def stream(self, context: ConversationContext) -> AsyncIterator[ModelEvent]:
        messages = _history_messages(
            context.system_policy, context.messages, for_generation=True
        )
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            max_completion_tokens=self._max_output_tokens,
        )

        input_tokens: int | None = None
        output_tokens: int | None = None
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                input_tokens = usage.prompt_tokens
                output_tokens = usage.completion_tokens
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield ModelTextDelta(delta=delta)

        if input_tokens is None or output_tokens is None:
            raise RuntimeError("OpenAI stream ended without final token usage")
        yield ModelCompleted(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def close(self) -> None:
        await self._client.close()


def _web_citation_links(citations: tuple[Any, ...]) -> tuple[FurtherReading, ...]:
    links: list[FurtherReading] = []
    seen: set[str] = set()
    for citation in citations:
        if citation.url in seen:
            continue
        seen.add(citation.url)
        links.append(
            FurtherReading(
                label=getattr(citation, "title", citation.url), url=citation.url
            )
        )
    return tuple(links)


def _render_clickable_citations(text: str, citations: tuple[Any, ...]) -> str:
    rendered = text
    end_boundary = len(text)
    for citation in sorted(citations, key=lambda item: item.start_index, reverse=True):
        if not (0 <= citation.start_index < citation.end_index <= end_boundary):
            continue
        label = text[citation.start_index : citation.end_index]
        rendered = (
            rendered[: citation.start_index]
            + f"[{label}]({citation.url})"
            + rendered[citation.end_index :]
        )
        end_boundary = citation.start_index
    return rendered


def _render_assessment_candidate(passage: Passage) -> str:
    source = passage.source_title or passage.source_id
    lines = [
        f"Passage ID: {passage.passage_id}",
        f"Source: {source} [{passage.source_id}]",
    ]
    if passage.section_path and passage.section_path != ("Approved account",):
        lines.append(f"Section: {' > '.join(passage.section_path)}")
    lines.append(f"Evidence:\n{passage.text}")
    return "\n".join(lines)


def _history_messages(
    system_policy: str,
    history: tuple[StoredMessage, ...],
    *,
    for_generation: bool = False,
) -> list[ChatCompletionMessageParam]:
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_policy}
    ]
    current_message_index = len(history) - 1
    for index, message in enumerate(history):
        if message.role == "user":
            content = (
                message.generation_content
                if (
                    for_generation
                    and index == current_message_index
                    and message.generation_content is not None
                )
                else message.content
            )
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "assistant", "content": message.content})
    return messages


@dataclass(frozen=True)
class LangSmithTracing:
    enabled: bool
    client: Client | None
    project: str
    tags: tuple[str, ...]
    metadata: dict[str, Any]

    @contextmanager
    def activate(self) -> Iterator[None]:
        with tracing_context(
            enabled=self.enabled,
            client=self.client,
            project_name=self.project,
            tags=list(self.tags),
            metadata=self.metadata,
        ):
            yield

    async def flush(self, timeout_seconds: float = 5) -> None:
        if self.client is None:
            return
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self.client.flush, timeout_seconds),
                timeout=timeout_seconds + 0.5,
            )
        except Exception as error:
            logger.warning(
                "LangSmith trace flush failed",
                extra={"error_class": type(error).__name__},
            )


def tracing_from_environment(
    *, instance_id: str, model: str, prompt_revision: str
) -> LangSmithTracing:
    requested = os.getenv("LANGSMITH_TRACING", "false").casefold() == "true"
    project = os.getenv("LANGSMITH_PROJECT", DEFAULT_LANGSMITH_PROJECT)
    metadata: dict[str, Any] = {
        "environment": os.getenv("MAAS_ENVIRONMENT", "development"),
        "application_revision": os.getenv("MAAS_APPLICATION_REVISION", "unknown"),
        "instance": instance_id,
        "model": model,
        "prompt_revision": prompt_revision,
    }
    tags = ("me-as-a-service", metadata["environment"], instance_id)
    if not requested:
        return LangSmithTracing(False, None, project, tags, metadata)

    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        logger.warning("LangSmith tracing requested without LANGSMITH_API_KEY")
        return LangSmithTracing(False, None, project, tags, metadata)

    try:
        client = Client(
            api_url=os.getenv("LANGSMITH_ENDPOINT") or None,
            api_key=api_key,
            workspace_id=os.getenv("LANGSMITH_WORKSPACE_ID") or None,
            tracing_error_callback=_log_tracing_error,
        )
    except Exception as error:
        logger.warning(
            "LangSmith initialization failed",
            extra={"error_class": type(error).__name__},
        )
        return LangSmithTracing(False, None, project, tags, metadata)
    return LangSmithTracing(True, client, project, tags, metadata)


def openai_model_from_environment(
    tracing: LangSmithTracing,
    prompts: PromptSet,
) -> OpenAIChatModel:
    provider = os.getenv("MAAS_LLM_PROVIDER", "openai").casefold()
    if provider == "openai":
        api_key_name = "OPENAI_API_KEY"
        default_model = DEFAULT_OPENAI_MODEL
        base_url = None
        web_search_tool_type = "web_search"
    elif provider == "openrouter":
        api_key_name = "OPENROUTER_API_KEY"
        default_model = DEFAULT_OPENROUTER_MODEL
        base_url = OPENROUTER_BASE_URL
        web_search_tool_type = "openrouter:web_search"
    else:
        raise RuntimeError("MAAS_LLM_PROVIDER must be either 'openai' or 'openrouter'")

    api_key = os.getenv(api_key_name)
    if not api_key:
        raise RuntimeError(f"{api_key_name} is required for hosted generation")
    model = os.getenv("MAAS_LLM_MODEL", default_model)
    native_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    client = native_client
    if tracing.enabled:
        try:
            client = wrap_openai(
                native_client,
                tracing_extra={"client": tracing.client},
                chat_name="openai_generation",
            )
        except Exception as error:
            logger.warning(
                "LangSmith OpenAI wrapping failed",
                extra={"error_class": type(error).__name__},
            )
    return OpenAIChatModel(
        client,
        model=model,
        prompts=prompts,
        web_search_tool_type=web_search_tool_type,
        max_output_tokens=int(
            os.getenv("MAAS_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS))
        ),
    )


def _log_tracing_error(error: Exception) -> None:
    logger.warning(
        "LangSmith trace export failed",
        extra={"error_class": type(error).__name__},
    )
