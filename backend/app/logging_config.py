"""
Structured logging configuration (structlog).

Both the FastAPI process (app/main.py) and the ARQ worker process (app/worker.py)
call configure_logging() once at startup, so every logger.info/warning call across
API routes and agent nodes renders through the same processors — giving a consistent
field set (timestamp, level, event) plus whatever structured kwargs the call site
binds (e.g. run_id, node, latency_ms in app/worker.py's per-node execution logs).
"""
import logging

import structlog

from app.config import settings


def configure_logging() -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    # JSON in production (log aggregators expect one JSON object per line);
    # human-readable console output otherwise.
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.env == "production"
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
