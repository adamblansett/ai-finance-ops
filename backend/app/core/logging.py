import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEY_RE = re.compile(
    r"(password|secret|token|authorization|api_key|ssn|tax_id|credit_card)",
    re.IGNORECASE,
)


def _redact_sensitive_fields(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    _ = (logger, method_name)
    for key in list(event_dict.keys()):
        if _SENSITIVE_KEY_RE.search(str(key)):
            event_dict[key] = "[REDACTED]"
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structured JSON logging with contextvars and secret scrubbing."""
    numeric_level = getattr(logging, log_level.strip().upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=numeric_level, force=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_sensitive_fields,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
