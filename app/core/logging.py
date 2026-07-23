import logging

import structlog


def configure_logging(log_level: str) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(log_level.upper())
            if isinstance(logging.getLevelName(log_level.upper()), int)
            else logging.INFO
        ),
        cache_logger_on_first_use=True,
    )
