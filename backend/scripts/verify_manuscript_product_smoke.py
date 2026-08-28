"""Verify one product manuscript through read-only production services."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import re
import sys
from typing import Callable, Sequence


APPROVED_CHAPTER_TITLES = (
    "泔水醒来，三日织机赌局",
    "废料改机",
    "复验定局",
)
_EXPECTED_AUTHORITY_CHAPTER = 4
_WRITE_KEYWORDS = re.compile(
    r"\b(?:insert|update|delete|replace|alter|drop|create|truncate)\b",
    re.IGNORECASE,
)
_SIDE_EFFECT_SELECT = re.compile(
    r"\b(?:into|for\s+update|lock\s+in\s+share\s+mode)\b",
    re.IGNORECASE,
)
_COMMENT_MARKERS = ("--", "#", "/*", "*/")
_UNSAFE_LEXEMES = ("`", '"', "@", ":=")
_FUNCTION_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_SAFE_READ_FUNCTIONS = frozenset(
    {"char_length", "field", "lower", "max", "trim"}
)
_GROUPING_TOKENS = frozenset(
    {"and", "exists", "from", "in", "or", "where"}
)


class SmokeArgumentError(ValueError):
    """The public command contract was not followed."""


class SmokeIntegrityError(RuntimeError):
    """The read authority did not match the approved product state."""


class ReadOnlySqlError(RuntimeError):
    """A query fell outside the verifier's conservative SELECT allowlist."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise SmokeArgumentError() from None


class ReadOnlySqlSession:
    """Fail closed around the small SQL surface used by read repositories.

    This is deliberately a conservative lexical guard, not a SQL parser. It
    accepts only one comment-free, semicolon-free SELECT with a FROM clause.
    Function calls are limited to the pure-read functions used by the smoke's
    production repositories; unknown functions fail closed.
    """

    def __init__(self, session) -> None:
        self._session = session

    @staticmethod
    def _mask_literals(sql: str) -> str:
        masked = list(sql)
        quote = None
        index = 0
        while index < len(sql):
            character = sql[index]
            if quote is None:
                if character in ("'", '"', "`"):
                    quote = character
                    masked[index] = " "
            else:
                masked[index] = " "
                if character == "\\" and index + 1 < len(sql):
                    index += 1
                    masked[index] = " "
                elif character == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        index += 1
                        masked[index] = " "
                    else:
                        quote = None
            index += 1
        if quote is not None:
            raise ReadOnlySqlError() from None
        return "".join(masked)

    @staticmethod
    def _require_select(sql: object) -> str:
        if type(sql) is not str:
            raise ReadOnlySqlError() from None
        masked = ReadOnlySqlSession._mask_literals(sql)
        stripped = masked.lstrip()
        functions = {
            match.group(1).lower()
            for match in _FUNCTION_CALL.finditer(masked)
        } - _GROUPING_TOKENS
        if (
            not re.match(r"(?i)^select\b", stripped)
            or re.search(r"(?i)\bfrom\b", stripped) is None
            or ";" in sql
            or any(marker in sql for marker in _COMMENT_MARKERS)
            or any(marker in sql for marker in _UNSAFE_LEXEMES)
            or _WRITE_KEYWORDS.search(masked)
            or _SIDE_EFFECT_SELECT.search(masked)
            or not functions.issubset(_SAFE_READ_FUNCTIONS)
        ):
            raise ReadOnlySqlError() from None
        return sql

    async def execute(self, sql, args=None):
        del sql, args
        raise ReadOnlySqlError() from None

    async def fetchone(self, sql, args=None):
        return await self._session.fetchone(self._require_select(sql), args)

    async def fetchall(self, sql, args=None):
        return await self._session.fetchall(self._require_select(sql), args)


def guarded_read_only_transaction(transaction_factory):
    """Layer the SQL allowlist over an enforced read-only transaction."""

    @asynccontextmanager
    async def guarded():
        async with transaction_factory() as session:
            yield ReadOnlySqlSession(session)

    return guarded


@dataclass(frozen=True)
class SmokeDependencies:
    manuscript: object
    preparation: object


def _default_dependencies() -> SmokeDependencies:
    from backend.database import read_only_transaction
    from backend.domain.routers.contracts import get_contract_service
    from backend.repositories.chapter_outlines import ChapterOutlineRepository
    from backend.repositories.chapter_sessions import ChapterSessionRepository
    from backend.repositories.projects import ProjectRepository
    from backend.services.manuscripts import ManuscriptReadingService
    from backend.services.project_lifecycle import ProjectLifecycleService

    transaction_factory = guarded_read_only_transaction(read_only_transaction)
    project_repository = ProjectRepository(
        chapter_session_repository=ChapterSessionRepository(),
        chapter_outline_repository=ChapterOutlineRepository(),
    )
    return SmokeDependencies(
        manuscript=ManuscriptReadingService(transaction_factory),
        preparation=ProjectLifecycleService(
            project_repository,
            transaction_factory,
            transaction_factory,
            contract_service=get_contract_service(),
        ),
    )


def _directory_chapters(directory) -> tuple[object, ...]:
    try:
        return tuple(
            chapter
            for volume in directory.volumes
            for chapter in volume.chapters
        )
    except (AttributeError, TypeError):
        raise SmokeIntegrityError() from None


def _outline_is_valid(outline: object) -> bool:
    if not outline:
        return False
    fields = (
        "chapter_goal",
        "expected_characters",
        "continuation",
        "planned_tasks",
        "scenes",
        "forbidden_early_events",
    )
    try:
        values = tuple(getattr(outline, field) for field in fields)
    except AttributeError:
        return False
    return (
        isinstance(values[0], str)
        and bool(values[0].strip())
        and all(isinstance(value, tuple) and bool(value) for value in values[1:])
    )


async def verify_product_smoke(
    project_id: str,
    *,
    dependencies: SmokeDependencies,
) -> dict[str, object]:
    """Read and validate one approved manuscript without exposing payloads."""

    directory = await dependencies.manuscript.directory(project_id)
    chapter_results = []
    for number in range(1, 4):
        chapter_results.append(
            await dependencies.manuscript.chapter(project_id, number)
        )
    chapters = tuple(chapter_results)
    preparation = await dependencies.preparation.preparation(project_id)
    directory_chapters = _directory_chapters(directory)

    try:
        directory_identity = directory.project_id
        final_count = directory.summary.final_chapter_count
        directory_pairs = tuple(
            (chapter.number, chapter.title) for chapter in directory_chapters
        )
        detail_pairs = tuple(
            (chapter.chapter.number, chapter.chapter.title) for chapter in chapters
        )
        detail_identities = tuple(chapter.project_id for chapter in chapters)
        authority = preparation.authoritative_chapter_number
        outline_status = preparation.outline
    except (AttributeError, TypeError):
        raise SmokeIntegrityError() from None

    expected_pairs = tuple(enumerate(APPROVED_CHAPTER_TITLES, 1))
    if (
        directory_identity != project_id
        or detail_identities != (project_id,) * 3
        or final_count != 3
        or directory_pairs != expected_pairs
        or detail_pairs != expected_pairs
        or not all(_outline_is_valid(chapter.outline) for chapter in chapters)
        or authority != _EXPECTED_AUTHORITY_CHAPTER
        or outline_status != "current"
    ):
        raise SmokeIntegrityError() from None

    return {
        "projectId": project_id,
        "status": "passed",
        "finalChapterCount": final_count,
        "chapterCheckCount": len(chapters),
        "pinnedCheckCount": len(chapters),
    }


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(add_help=False)
    parser.add_argument("--project-id", action="append", required=True)
    return parser


def parse_project_id(argv: Sequence[str] | None) -> str:
    arguments = _parser().parse_args(argv)
    values = arguments.project_id
    if (
        type(values) is not list
        or len(values) != 1
        or type(values[0]) is not str
        or not values[0].strip()
        or values[0] != values[0].strip()
        or any(ord(character) < 32 for character in values[0])
    ):
        raise SmokeArgumentError() from None
    return values[0]


async def run_cli(
    argv: Sequence[str] | None = None,
    *,
    dependencies: SmokeDependencies | None = None,
    output: Callable[[str], None] = print,
) -> int:
    project_id = parse_project_id(argv)
    summary = await verify_product_smoke(
        project_id,
        dependencies=dependencies or _default_dependencies(),
    )
    output(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


def _failure(category: str, project_id: str | None = None) -> str:
    receipt: dict[str, object] = {"category": category}
    if project_id is not None:
        receipt["projectId"] = project_id
    receipt["status"] = "failed"
    return json.dumps(receipt, sort_keys=True, separators=(",", ":"))


def _failure_category(error: BaseException) -> str:
    from backend.services.manuscripts import (
        FinalChapterNotFound,
        ManuscriptIntegrityFailure,
        ManuscriptProjectNotFound,
        ManuscriptTemporarilyUnavailable,
    )

    if isinstance(error, (SmokeIntegrityError, ManuscriptIntegrityFailure)):
        return "integrity"
    if isinstance(error, (ManuscriptProjectNotFound, FinalChapterNotFound)):
        return "not_found"
    if isinstance(error, ManuscriptTemporarilyUnavailable):
        return "unavailable"
    if isinstance(error, ReadOnlySqlError):
        return "read_only"
    return "unexpected"


def main(
    argv: Sequence[str] | None = None,
    *,
    dependencies: SmokeDependencies | None = None,
) -> int:
    try:
        project_id = parse_project_id(argv)
    except SmokeArgumentError:
        print(_failure("arguments"), file=sys.stderr)
        return 2
    try:
        summary = asyncio.run(
            verify_product_smoke(
                project_id,
                dependencies=dependencies or _default_dependencies(),
            )
        )
    except BaseException as error:
        print(_failure(_failure_category(error), project_id), file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
