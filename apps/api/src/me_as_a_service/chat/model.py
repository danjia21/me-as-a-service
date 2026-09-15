"""Run hosted-LLM operations for a prepared conversation context.

This module translates ``ConversationContext`` values into OpenAI-compatible
requests for structured message classification, query rewriting, and streamed
response generation.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable

from openai import AsyncOpenAI

from .types import ConversationContext, MessageClassification

DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-flash"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MAX_OUTPUT_TOKENS = 300


class OpenAICompatibleChatModel:
    """Implement chat operations with an OpenAI-compatible hosted model.

    Each operation accepts conversation context and its system prompt separately,
    then returns only the classification, optional query, response deltas, and
    usage needed by the application layer.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        *,
        model: str,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        """Configure the provider client, model name, and output-token cap."""

        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self.model = model
        self._client = client
        self._max_output_tokens = max_output_tokens

    async def classify_and_rewrite_message(
        self, context: ConversationContext, system_prompt: str
    ) -> MessageClassification:
        """Classify a message and optionally produce a retrieval query.

        Only evidence-required questions include a query. Invalid structured output
        fails the operation instead of guessing a route or fallback query.

        Raises:
            RuntimeError: If the model returns no structured content or invalid
                structured content.
        """
        completion = await self._client.chat.completions.create(
            model=self.model,
            messages=context.to_openai_messages(system_prompt),
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "message_classification",
                    "strict": True,
                    "schema": MessageClassification.model_json_schema(),
                },
            },
        )
        content = completion.choices[0].message.content

        if content is None:
            raise RuntimeError("message classification returned no structured content")

        return MessageClassification.model_validate_json(content)

    async def stream_response(
        self, context: ConversationContext, system_prompt: str
    ) -> AsyncIterator[tuple[str | None, int | None, int | None]]:
        """Stream a response for a fully prepared generation context.

        Text items carry a non-null delta. The final item uses
        ``(None, input_tokens, output_tokens)``. Missing final usage is an error
        because downstream accounting requires it.
        """
        messages = context.to_openai_messages(system_prompt)
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
                yield delta, input_tokens, output_tokens

        if input_tokens is None or output_tokens is None:
            raise RuntimeError("OpenAI stream ended without final token usage")

        yield None, input_tokens, output_tokens

    async def close(self) -> None:
        """Close the underlying provider client."""

        await self._client.close()

    def wrap_client(
        self, wrapper: Callable[[AsyncOpenAI], AsyncOpenAI]
    ) -> OpenAICompatibleChatModel:
        """Return a copy with an instrumented client and unchanged settings."""

        return OpenAICompatibleChatModel(
            wrapper(self._client),
            model=self.model,
            max_output_tokens=self._max_output_tokens,
        )


def chat_model_from_environment() -> OpenAICompatibleChatModel:
    """Build the production hosted-model boundary from the environment.

    Reads ``MAAS_LLM_PROVIDER``, ``MAAS_LLM_MODEL``, and
    ``MAAS_MAX_OUTPUT_TOKENS``. The required API key depends on the provider.
    Prompt selection and tracing remain the caller's responsibility.

    Raises:
        RuntimeError: If the provider is unsupported or its API key is missing.
        ValueError: If ``MAAS_MAX_OUTPUT_TOKENS`` is not an integer.
    """
    provider = os.getenv("MAAS_LLM_PROVIDER", "openai").casefold()
    if provider == "openai":
        api_key_name = "OPENAI_API_KEY"
        default_model = DEFAULT_OPENAI_MODEL
        base_url = None
    elif provider == "openrouter":
        api_key_name = "OPENROUTER_API_KEY"
        default_model = DEFAULT_OPENROUTER_MODEL
        base_url = OPENROUTER_BASE_URL
    else:
        raise RuntimeError("MAAS_LLM_PROVIDER must be either 'openai' or 'openrouter'")

    api_key = os.getenv(api_key_name)
    if not api_key:
        raise RuntimeError(f"{api_key_name} is required for hosted generation")

    model = os.getenv("MAAS_LLM_MODEL", default_model)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    return OpenAICompatibleChatModel(
        client,
        model=model,
        max_output_tokens=int(
            os.getenv("MAAS_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS))
        ),
    )
