import logging
import re
from collections.abc import Mapping
from typing import cast

import structlog
from structlog.typing import EventDict, WrappedLogger

REDACTED = "[REDACTED]"
SENSITIVE_KEY_PATTERN = re.compile(
    r"password|passwd|token|secret|authorization|api[_-]?key", re.IGNORECASE
)
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?P<key>password|passwd|token|secret|authorization|api[_-]?key)"
    r"(?P<separator>\s*[=:]\s*)(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)
DATABASE_URL_PATTERN = re.compile(
    r"\b(?:postgres|postgresql)(?:\+[a-z0-9_-]+)?://[^\s,;]+", re.IGNORECASE
)
AUTHORIZATION_VALUE_PATTERN = re.compile(
    r"(?P<key>authorization)(?P<separator>\s*[=:]\s*)"
    r"(?:(?:bearer|basic)\s+)?[^\s,;]+",
    re.IGNORECASE,
)


class RedactingFormatter(logging.Formatter):
    def __init__(self, formatter: logging.Formatter | None = None) -> None:
        super().__init__()
        self.formatter = formatter or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        return cast(str, _redact_value(self.formatter.format(record)))


def redact_sensitive_data(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    del logger, method_name
    return cast(EventDict, _redact_value(event_dict))


def _redact_value(value: object, key: str | None = None) -> object:
    if key is not None and SENSITIVE_KEY_PATTERN.search(key):
        return REDACTED
    if isinstance(value, str):
        redacted = AUTHORIZATION_VALUE_PATTERN.sub(
            r"\g<key>\g<separator>[REDACTED]",
            value,
        )
        redacted = DATABASE_URL_PATTERN.sub(REDACTED, redacted)
        return SENSITIVE_VALUE_PATTERN.sub(r"\g<key>\g<separator>[REDACTED]", redacted)
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact_value(item, str(item_key)) for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def _configure_uvicorn_redaction() -> None:
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.disabled = False
        for handler in logger.handlers:
            if not isinstance(handler.formatter, RedactingFormatter):
                handler.setFormatter(RedactingFormatter(handler.formatter))


def configure_logging(log_level: str) -> None:
    _configure_uvicorn_redaction()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            redact_sensitive_data,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(log_level.upper())
            if isinstance(logging.getLevelName(log_level.upper()), int)
            else logging.INFO
        ),
        cache_logger_on_first_use=True,
    )
