"""Prepare one canonical Phase 4B2 browser fixture in a disposable database."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections.abc import Sequence
from types import SimpleNamespace

from backend.database import close_pool, connection
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.services.chapter_sessions import ChapterSessionService
from backend.tests.integration.test_authoritative_chapter_session import (
    PROJECT,
    _confirmed_outline,
    _create_command,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


_DISPOSABLE = re.compile(r"novel_creator_test_[a-f0-9]{32}\Z")
PARTIAL_OUTPUT_SHA256 = "f0a0b60f973a06b3723525ece56b44231bf8b4d1715e7356d2d008063767741f"
COMPLETED_OUTPUT_SHA256 = "c88ade88d9dd15b14d6bd8b9c7662072148fdb8dc4fc714d56a9fb9a31f12fbe"
EMPTY_OUTPUT_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def assert_database_name(database_name: str) -> str:
    if not isinstance(database_name, str) or _DISPOSABLE.fullmatch(database_name) is None:
        raise RuntimeError("Phase4B2 fixture requires a disposable database")
    return database_name


def _configuration(database_name: str) -> dict[str, object]:
    required = ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD")
    if any(not os.environ.get(name) for name in required):
        raise RuntimeError("Phase4B2 fixture requires explicit disposable MySQL authority")
    return {
        "host": os.environ["MYSQL_HOST"],
        "port": int(os.environ["MYSQL_PORT"]),
        "user": os.environ["MYSQL_USER"],
        "password": os.environ["MYSQL_PASSWORD"],
        "db": database_name,
        "charset": "utf8mb4",
        "autocommit": True,
    }


async def prepare(database_name: str) -> None:
    """Create confirmed immutable basis, Planning, StoryBlock, confirmed Outline,
    ChapterSession and WorkingDraft through the canonical product chain."""
    database_name = assert_database_name(database_name)
    if os.environ.get("MYSQL_DB") != database_name:
        raise RuntimeError("Phase4B2 fixture database authority mismatch")
    config = _configuration(database_name)
    async with connection() as session:
        selected = await session.fetchone("SELECT DATABASE() AS database_name")
        if selected != {"database_name": database_name}:
            raise RuntimeError("Phase4B2 fixture selected a non-owned database")
        fixture = SimpleNamespace(
            session=session,
            database_name=database_name,
            connection_config=config,
        )
        # _confirmed_outline creates the confirmed immutable basis, Planning,
        # StoryBlock and confirmed Outline through the real product services.
        _, planning, outline = await _confirmed_outline(fixture)
        transaction_factory = transaction_factory_for(config)
        chapter_service = ChapterSessionService(
            ChapterSessionRepository(), transaction_factory=transaction_factory,
        )
        workspace = await chapter_service.create_session(_create_command(planning, outline))
        if workspace.session.project_id != PROJECT:
            raise RuntimeError("Phase4B2 fixture project authority mismatch")
        await session.execute(
            """UPDATE provider_profiles
                  SET base_url=%s,api_key=%s,enabled=1,stream=1,
                      supports_streaming=1
                WHERE id='81000000-0000-0000-0000-000000000004'""",
            (
                os.environ["BROWSER_PROVIDER_BASE_URL"],
                os.environ["BROWSER_SECRET_SENTINEL"],
            ),
        )


def assert_postcondition_snapshot(
    chapter: dict[str, object] | None,
    candidate: dict[str, object] | None,
    attempt: dict[str, object] | None,
    draft: dict[str, object] | None,
    events: Sequence[dict[str, object]],
    recovery: Sequence[dict[str, object]],
    scenario: str,
) -> None:
    recovery = list(recovery)
    if scenario not in {"complete", "reconnect", "cancel-output", "cancel-empty"}:
        raise RuntimeError("Phase4B2 verifier scenario is invalid")
    if not chapter or candidate != {"total": 0} or not attempt or not draft:
        raise RuntimeError("Phase4B2 verifier canonical state is invalid")
    sequences = [row.get("sequence_num") for row in events]
    event_types = [row.get("event_type") for row in events]
    if sequences != list(range(1, len(events) + 1)):
        raise RuntimeError("Phase4B2 operation event sequence verification failed")
    expected_status = {
        "complete": "completed",
        "reconnect": "running",
        "cancel-output": "cancelled",
        "cancel-empty": "cancelled",
    }[scenario]
    expected_scalars = 0 if scenario == "cancel-empty" else (257 if scenario == "complete" else 256)
    if (
        attempt.get("status") != expected_status
        or attempt.get("partial_output_scalars") != expected_scalars
        or attempt.get("last_event_sequence") != len(events)
        or not event_types
        or event_types[0] != "started"
    ):
        raise RuntimeError("Phase4B2 terminal operation/event verification failed")
    if scenario == "complete":
        valid_events = event_types == ["started", "delta", "delta", "completed"]
    elif scenario == "reconnect":
        valid_events = event_types[:2] == ["started", "delta"] and all(
            event == "heartbeat" for event in event_types[2:]
        )
    elif scenario == "cancel-output":
        valid_events = (
            event_types[:2] == ["started", "delta"]
            and event_types[-1:] == ["cancelled"]
            and all(event == "heartbeat" for event in event_types[2:-1])
        )
    else:
        valid_events = (
            event_types[:1] == ["started"]
            and event_types[-1:] == ["cancelled"]
            and all(event == "heartbeat" for event in event_types[1:-1])
        )
    if not valid_events:
        raise RuntimeError("Phase4B2 terminal operation/event verification failed")
    terminal = scenario != "reconnect"
    if terminal:
        if chapter.get("active_draft_operation_id") is not None:
            raise RuntimeError("Phase4B2 terminal operation remained active")
    elif chapter.get("active_draft_operation_id") is None:
        raise RuntimeError("Phase4B2 reconnect operation was not active")
    base = attempt.get("base_working_draft_revision")
    base_hash = attempt.get("base_working_draft_hash")
    operation_id = attempt.get("id")
    if base != 1 or base_hash != EMPTY_OUTPUT_SHA256:
        raise RuntimeError("Phase4B2 canonical WorkingDraft base verification failed")
    has_result = scenario in {"complete", "cancel-output"}
    if has_result:
        expected_hash = COMPLETED_OUTPUT_SHA256 if scenario == "complete" else PARTIAL_OUTPUT_SHA256
        expected_recovery = [
            {
                "working_draft_revision": base,
                "content_hash": base_hash,
                "snapshot_role": "before",
                "source_operation_id": operation_id,
            },
            {
                "working_draft_revision": base + 1,
                "content_hash": expected_hash,
                "snapshot_role": "after",
                "source_operation_id": operation_id,
            },
        ]
        if (
            attempt.get("result_working_draft_revision") != base + 1
            or attempt.get("partial_output_hash") != expected_hash
            or attempt.get("result_content_hash") != expected_hash
            or draft.get("revision") != base + 1
            or draft.get("content_hash") != expected_hash
            or recovery != expected_recovery
        ):
            raise RuntimeError("Phase4B2 WorkingDraft recovery verification failed")
        return
    if (
        attempt.get("result_working_draft_revision") is not None
        or attempt.get("result_content_hash") is not None
        or draft.get("revision") != base
        or draft.get("content_hash") != base_hash
        or recovery != []
    ):
        raise RuntimeError("Phase4B2 unchanged WorkingDraft verification failed")
    if scenario == "reconnect" and attempt.get("partial_output_hash") != PARTIAL_OUTPUT_SHA256:
        raise RuntimeError("Phase4B2 reconnect partial digest verification failed")
    if scenario == "cancel-empty" and attempt.get("partial_output_hash") != EMPTY_OUTPUT_SHA256:
        raise RuntimeError("Phase4B2 cancel-empty WorkingDraft base verification failed")


def assert_exactly_one_attempt(attempts: list[dict[str, object]]) -> dict[str, object]:
    if len(attempts) != 1:
        raise RuntimeError("Phase4B2 verifier requires exactly one draft operation")
    return attempts[0]


async def verify_postconditions(database_name: str, scenario: str) -> None:
    """Read only the current disposable database: Candidate count remains zero,
    then verify WorkingDraft recovery plus the terminal operation/event facts."""
    database_name = assert_database_name(database_name)
    if scenario not in {"complete", "reconnect", "cancel-output", "cancel-empty"}:
        raise RuntimeError("Phase4B2 verifier scenario is invalid")
    if os.environ.get("MYSQL_DB") != database_name:
        raise RuntimeError("Phase4B2 verifier database authority mismatch")
    async with connection() as session:
        await session.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await session.execute("START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT")
        try:
            selected = await session.fetchone("SELECT DATABASE() AS database_name")
            if selected != {"database_name": database_name}:
                raise RuntimeError("Phase4B2 verifier selected a non-owned database")
            chapter = await session.fetchone(
                """SELECT id,active_draft_operation_id
                     FROM chapter_sessions
                    WHERE project_id=%s AND chapter_num=1""",
                (PROJECT,),
            )
            candidate = await session.fetchone(
                "SELECT COUNT(*) AS total FROM draft_candidates WHERE project_id=%s",
                (PROJECT,),
            )
            attempts = await session.fetchall(
                """SELECT id,status,base_working_draft_revision,base_working_draft_hash,
                          partial_output_hash,partial_output_scalars,
                          result_working_draft_revision,result_content_hash,last_event_sequence
                     FROM draft_operation_attempts
                    WHERE project_id=%s AND chapter_session_id=%s""",
                (PROJECT, chapter["id"] if chapter else None),
            )
            attempt = assert_exactly_one_attempt(attempts)
            draft = await session.fetchone(
                """SELECT revision,content_hash FROM working_drafts
                     WHERE project_id=%s AND chapter_session_id=%s""",
                (PROJECT, chapter["id"] if chapter else None),
            )
            events = await session.fetchall(
                """SELECT sequence_num,event_type FROM draft_operation_events
                     WHERE project_id=%s AND draft_operation_id=%s
                     ORDER BY sequence_num""",
                (PROJECT, attempt["id"] if attempt else None),
            )
            recovery = await session.fetchall(
                """SELECT working_draft_revision,content_hash,snapshot_role,source_operation_id
                     FROM working_draft_revisions
                     WHERE project_id=%s AND chapter_session_id=%s
                     ORDER BY working_draft_revision,snapshot_role""",
                (PROJECT, chapter["id"] if chapter else None),
            )
        finally:
            await session.raw.rollback()
    assert_postcondition_snapshot(chapter, candidate, attempt, draft, events, recovery, scenario)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--verify-postconditions", choices=(
        "complete", "reconnect", "cancel-output", "cancel-empty",
    ))
    args = parser.parse_args()
    try:
        if args.verify_postconditions:
            await verify_postconditions(args.database, args.verify_postconditions)
        else:
            await prepare(args.database)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
