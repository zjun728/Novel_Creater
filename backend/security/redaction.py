"""Recursive secret redaction and safe FastAPI error boundaries."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from uuid import uuid4

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


REDACTED = "[REDACTED]"
_SECRET_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "authorization",
        "baseurl",
        "base_url",
        "password",
        "token",
    }
)


def redact_secrets(value):
    if isinstance(value, BaseException):
        return type(value).__name__
    if isinstance(value, Mapping):
        return {
            key: (
                REDACTED
                if str(key).casefold() in _SECRET_KEYS
                else redact_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, set):
        return {redact_secrets(item) for item in value}
    return value


def _redact_validation_errors(errors):
    sanitized = redact_secrets(errors)
    for error in sanitized:
        location = error.get("loc", ())
        if any(str(part).casefold() in _SECRET_KEYS for part in location):
            error["input"] = REDACTED
    return sanitized


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.msg)
        record.args = redact_secrets(record.args)
        record.exc_info = None
        record.exc_text = None
        return True


def _install_redaction_filter(target) -> None:
    if not any(
        isinstance(item, SecretRedactionFilter)
        for item in target.filters
    ):
        target.addFilter(SecretRedactionFilter())


def install_error_handlers(app, *, logger=None) -> None:
    application_logger = logger or logging.getLogger("backend")
    _install_redaction_filter(application_logger)
    _install_redaction_filter(logging.getLogger("uvicorn.error"))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ):
        correlation_id = str(uuid4())
        application_logger.warning(
            "request_validation_error type=%s correlation_id=%s",
            type(exc).__name__,
            correlation_id,
        )
        return JSONResponse(
            status_code=422,
            content={
                "detail": jsonable_encoder(
                    _redact_validation_errors(exc.errors())
                ),
                "correlationId": correlation_id,
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        correlation_id = str(uuid4())
        application_logger.error(
            "unexpected_error type=%s correlation_id=%s",
            type(exc).__name__,
            correlation_id,
        )
        return JSONResponse(
            status_code=500,
            content={
                "message": "Internal server error",
                "correlationId": correlation_id,
            },
        )
