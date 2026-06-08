"""Structured JSON logging for AnsiQ SaaS — production-ready logging."""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC
from typing import Any


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    service: str = "ansiq",
    environment: str = "production",
) -> None:
    """Configure production logging with structured JSON output."""
    level = os.getenv("ANSIQ_LOG_LEVEL", level).upper()
    environment = os.getenv("ANSIQ_ENV", environment)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level, logging.INFO))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    if json_format:
        handler = StructuredJsonHandler(
            service=service,
            environment=environment,
        )
    else:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)

    handler.setLevel(getattr(logging, level, logging.INFO))
    root_logger.addHandler(handler)

    # Set third-party log levels
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.captureWarnings(True)
    logger = logging.getLogger("ansiq.init")
    logger.info("Logging initialized (level=%s, json=%s, env=%s)", level, json_format, environment)


class StructuredJsonHandler(logging.Handler):
    """JSON-formatted logging handler for production log aggregation."""

    def __init__(
        self,
        service: str = "ansiq",
        environment: str = "production",
    ):
        super().__init__()
        self.service = service
        self.environment = environment

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_entry = self._format_record(record)
            msg = self._serialize(log_entry)
            stream = sys.stderr if record.levelno >= logging.WARNING else sys.stdout
            stream.write(msg + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)

    def _format_record(self, record: logging.LogRecord) -> dict[str, Any]:
        return {
            "timestamp": self._format_time(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
            "environment": self.environment,
            "module": record.module,
            "line": record.lineno,
            "function": record.funcName,
        }

    def _format_time(self, timestamp: float) -> str:
        from datetime import datetime

        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()

    def _serialize(self, data: dict[str, Any]) -> str:
        import json

        return json.dumps(data, default=str, ensure_ascii=False)
