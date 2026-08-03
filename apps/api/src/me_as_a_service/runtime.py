import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import uvicorn

from me_as_a_service.chat.model import (
    DEFAULT_OPENAI_MODEL,
    openai_model_from_environment,
    tracing_from_environment,
)
from me_as_a_service.chat.prompts import load_prompts
from me_as_a_service.chat.storage import conversation_store_from_environment
from me_as_a_service.chat.usage import usage_ledger_from_environment
from me_as_a_service.chat.workflow import (
    DEFAULT_DAILY_TOKEN_BUDGET,
    DEFAULT_MAX_TURNS_PER_CONVERSATION,
    ChatWorkflow,
)
from me_as_a_service.instance import Instance
from me_as_a_service.knowledge.retrieval import EvidenceRetriever


class JsonFormatter(logging.Formatter):
    """Emit bounded operational fields without request or response content."""

    _EXTRA_FIELDS = (
        "duration_ms",
        "error_class",
        "method",
        "outcome",
        "path",
        "status",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.casefold(),
            "service": "api",
            "environment": os.getenv("MAAS_ENVIRONMENT", "production"),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info and "error_class" not in payload:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["error_class"] = exception_type.__name__
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "me_as_a_service.runtime.JsonFormatter",
        }
    },
    "handlers": {
        "stderr": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stderr",
        },
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "me_as_a_service": {
            "handlers": ["stdout"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn": {
            "handlers": ["stderr"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["stderr"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["stdout"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}


def build_chat_workflow(
    *, instance: Instance, retriever: EvidenceRetriever
) -> ChatWorkflow:
    prompts = load_prompts()
    model_name = os.getenv("MAAS_LLM_MODEL", DEFAULT_OPENAI_MODEL)
    tracing = tracing_from_environment(
        instance_id=instance.config.id,
        model=model_name,
        prompt_revision=prompts.revision,
    )
    return ChatWorkflow(
        store=conversation_store_from_environment(),
        usage_ledger=usage_ledger_from_environment(),
        model=openai_model_from_environment(tracing, prompts),
        retriever=retriever,
        prompts=prompts,
        tracing=tracing,
        instance_id=instance.config.id,
        display_name=instance.config.display_name,
        personal_terms=instance.config.routing.personal_terms,
        max_turns_per_conversation=int(
            os.getenv(
                "MAAS_MAX_TURNS_PER_CONVERSATION",
                str(DEFAULT_MAX_TURNS_PER_CONVERSATION),
            )
        ),
        daily_token_budget=int(
            os.getenv("MAAS_DAILY_TOKEN_BUDGET", str(DEFAULT_DAILY_TOKEN_BUDGET))
        ),
    )


def run() -> None:
    uvicorn.run(
        "me_as_a_service.api:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        workers=1,
        access_log=False,
        proxy_headers=False,
        timeout_graceful_shutdown=int(
            os.getenv("MAAS_GRACEFUL_SHUTDOWN_SECONDS", "30")
        ),
        log_config=LOGGING_CONFIG,
    )
