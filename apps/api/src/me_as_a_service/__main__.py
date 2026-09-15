"""Configure process logging and launch the API server."""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import uvicorn


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
            "()": JsonFormatter,
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


if __name__ == "__main__":
    run()
