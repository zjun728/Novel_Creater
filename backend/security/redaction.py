"""Recursive secret redaction and safe FastAPI error boundaries."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from uuid import uuid4

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.http_errors import PublicDomainError
from backend.security.provider_secrets import (
    is_provider_secret_key,
    sanitize_provider_secret_text,
)


REDACTED = "[REDACTED]"


def redact_secrets(value):
    if isinstance(value, BaseException):
        return type(value).__name__
    if isinstance(value, Mapping):
        return {
            key: (
                REDACTED
                if is_provider_secret_key(key)
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


def _validation_secret_values(body) -> tuple[str, ...]:
    values = []

    def collect(value, *, inside_secret: bool = False):
        if isinstance(value, Mapping):
            if inside_secret:
                values.extend(
                    key
                    for key in value
                    if isinstance(key, str) and key
                )
            for key, item in value.items():
                collect(
                    item,
                    inside_secret=(
                        inside_secret
                        or is_provider_secret_key(key)
                    ),
                )
            return
        if isinstance(value, (tuple, list, set)):
            for item in value:
                collect(item, inside_secret=inside_secret)
            return
        if inside_secret and isinstance(value, str) and value:
            values.append(value)

    collect(body)
    return tuple(
        sorted(dict.fromkeys(values), key=len, reverse=True)
    )


def _redact_validation_errors(errors, body=None):
    def drop_secret_keys(value):
        if isinstance(value, Mapping):
            return {
                key: drop_secret_keys(item)
                for key, item in value.items()
                if not is_provider_secret_key(key)
            }
        if isinstance(value, tuple):
            return tuple(drop_secret_keys(item) for item in value)
        if isinstance(value, list):
            return [drop_secret_keys(item) for item in value]
        if (
            isinstance(value, str)
            and is_provider_secret_key(value)
        ):
            return REDACTED
        return value

    secrets = _validation_secret_values(body)

    def replace_secret_values(value, *, preserve_mapping_keys=False):
        if isinstance(value, Mapping):
            return {
                (
                    key
                    if preserve_mapping_keys or not isinstance(key, str)
                    else replace_secret_values(key)
                ): replace_secret_values(item)
                for key, item in value.items()
            }
        if isinstance(value, tuple):
            return tuple(replace_secret_values(item) for item in value)
        if isinstance(value, list):
            return [replace_secret_values(item) for item in value]
        if isinstance(value, str):
            return sanitize_provider_secret_text(value, secrets)
        return value

    dropped = drop_secret_keys(redact_secrets(errors))
    sanitized = [
        replace_secret_values(error, preserve_mapping_keys=True)
        for error in dropped
    ]
    for error in sanitized:
        error.pop("input", None)
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

    @app.exception_handler(PublicDomainError)
    async def public_domain_error_handler(
        request: Request, exc: PublicDomainError
    ):
        correlation_id = str(uuid4())
        application_logger.warning(
            "public_domain_error type=%s correlation_id=%s",
            type(exc).__name__,
            correlation_id,
        )
        content = {
            "code": exc.code,
            "message": exc.message,
            "correlationId": correlation_id,
        }
        if getattr(exc, "retryable", False) is True:
            content["retryable"] = True
        return JSONResponse(status_code=exc.status_code, content=content)

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
                    _redact_validation_errors(exc.errors(), exc.body)
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
