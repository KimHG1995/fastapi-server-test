import io
import logging
from typing import cast

from structlog.typing import WrappedLogger

from app.core.logging import RedactingFormatter, configure_logging, redact_sensitive_data


def _redact_message(message: str) -> str:
    redacted = redact_sensitive_data(
        cast(WrappedLogger, object()),
        "error",
        {"event": message},
    )
    return cast(str, redacted["event"])


def test_authorization_credential_is_fully_redacted_with_case_and_spacing() -> None:
    message = "request failed Authorization :   bEaReR exposed-access-token"

    redacted = _redact_message(message)

    assert redacted == "request failed Authorization :   [REDACTED]"
    assert "bEaReR" not in redacted
    assert "exposed-access-token" not in redacted


def test_database_url_and_password_are_redacted_without_changing_safe_text() -> None:
    message = (
        "password=db-password "
        "postgresql+asyncpg://db-user:url-password@db.example/app; "
        "passwordless authorization strategy"
    )

    redacted = _redact_message(message)

    assert "db-password" not in redacted
    assert "db-user" not in redacted
    assert "url-password" not in redacted
    assert redacted.endswith("passwordless authorization strategy")


def test_reconfigure_logging_wraps_a_replaced_uvicorn_handler_once() -> None:
    configure_logging("INFO")

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    uvicorn_logger = logging.getLogger("uvicorn.error")
    original_handlers = uvicorn_logger.handlers
    original_propagate = uvicorn_logger.propagate
    original_disabled = uvicorn_logger.disabled
    uvicorn_logger.handlers = [handler]
    uvicorn_logger.propagate = False
    uvicorn_logger.disabled = True
    try:
        configure_logging("INFO")
        wrapped_formatter = handler.formatter
        assert isinstance(wrapped_formatter, RedactingFormatter)

        configure_logging("INFO")
        assert handler.formatter is wrapped_formatter

        try:
            raise RuntimeError("Authorization: Bearer uvicorn-exposed-token")
        except RuntimeError:
            uvicorn_logger.exception("request failed")
    finally:
        uvicorn_logger.handlers = original_handlers
        uvicorn_logger.propagate = original_propagate
        uvicorn_logger.disabled = original_disabled

    formatted = output.getvalue()
    assert "RuntimeError" in formatted
    assert "uvicorn-exposed-token" not in formatted
    assert "Bearer" not in formatted
