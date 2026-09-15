"""Configure optional LangSmith tracing for the chat model boundary.

This module creates the tracing context, attaches model-call instrumentation,
and flushes exported traces during shutdown. It does not define application
spans, choose trace metadata for individual turns, or affect chat behavior when
telemetry is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import partial
from typing import Any

from langsmith import Client, tracing_context
from langsmith.wrappers import wrap_openai

from .model import OpenAICompatibleChatModel

DEFAULT_LANGSMITH_PROJECT = "me-as-a-service"
OPENAI_CHAT_COMPLETION_TRACE_NAME = "openai_chat_completion"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LangSmithTracing:
    """Hold optional LangSmith configuration and lifecycle operations.

    Disabled instances preserve the same interface while leaving the model
    client unchanged and emitting no traces.
    """

    enabled: bool
    client: Client | None
    project: str
    tags: tuple[str, ...]
    metadata: dict[str, Any]

    def activate(self) -> AbstractContextManager[None]:
        """Return a context that applies the configured project metadata."""

        return tracing_context(
            enabled=self.enabled,
            client=self.client,
            project_name=self.project,
            tags=list(self.tags),
            metadata=self.metadata,
        )

    def wrap_chat_model(
        self, chat_model: OpenAICompatibleChatModel
    ) -> OpenAICompatibleChatModel:
        """Instrument model requests when tracing is enabled.

        Wrapping failures are logged and the original model is returned so
        optional telemetry cannot prevent chat startup.
        """

        if not self.enabled:
            return chat_model

        try:
            return chat_model.wrap_client(
                partial(
                    wrap_openai,
                    tracing_extra={"client": self.client},
                    chat_name=OPENAI_CHAT_COMPLETION_TRACE_NAME,
                )
            )
        except Exception as error:
            logger.warning(
                "LangSmith OpenAI wrapping failed",
                extra={"error_class": type(error).__name__},
            )
            return chat_model

    async def flush(self, timeout_seconds: float = 5) -> None:
        """Flush pending traces within a bounded shutdown interval.

        Export failures are logged and suppressed because telemetry is not part
        of the public response contract.
        """

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
    """Build tracing configuration from environment and deployment metadata.

    Tracing remains disabled unless explicitly requested with a usable API key.
    Initialization failures degrade to a disabled configuration.
    """

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


def _log_tracing_error(error: Exception) -> None:
    """Record asynchronous export failures without exposing trace content."""

    logger.warning(
        "LangSmith trace export failed",
        extra={"error_class": type(error).__name__},
    )
