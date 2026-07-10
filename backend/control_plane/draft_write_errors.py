"""Safe public errors for the dormant draft-write control plane."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DraftWriteError(Exception):
    code: str
    http_status: int
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


class CommitOutcomeUnknown(DraftWriteError):
    def __init__(self) -> None:
        super().__init__(
            code="commit_outcome_unknown",
            http_status=503,
            message="The commit outcome could not be confirmed.",
            retryable=True,
        )


class TransactionOutcomeUnknown(DraftWriteError):
    def __init__(self) -> None:
        super().__init__(
            code="transaction_outcome_unknown",
            http_status=503,
            message="The transaction outcome could not be confirmed.",
            retryable=True,
        )


class UnsafeDisposableDatabase(DraftWriteError):
    def __init__(self) -> None:
        super().__init__(
            code="feature_disabled",
            http_status=404,
            message="Draft write control plane is disabled.",
        )


def mysql_error_number(error: BaseException) -> int | None:
    """Extract a MySQL numeric error without formatting unsafe exception text."""

    args = getattr(error, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


def map_mysql_error(error: BaseException) -> DraftWriteError | None:
    """Map only explicitly supported retryable MySQL conflicts."""

    number = mysql_error_number(error)
    if number == 1205:
        return DraftWriteError(
            code="idempotency_in_progress",
            http_status=409,
            message="An idempotent write is still in progress.",
            retryable=True,
        )
    if number == 1213:
        return DraftWriteError(
            code="transaction_retryable_conflict",
            http_status=409,
            message="The transaction conflicted with another write.",
            retryable=True,
        )
    return None
