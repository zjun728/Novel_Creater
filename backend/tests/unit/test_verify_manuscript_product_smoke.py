from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest


PROJECT_ID = "474d110f-977c-4c82-bec4-464f30ec5a16"
TITLES = ("泔水醒来，三日织机赌局", "废料改机", "复验定局")
SECRET = "SENSITIVE_EXCEPTION_MUST_NOT_LEAK"


def _outline():
    return SimpleNamespace(
        chapter_goal="goal",
        expected_characters=("character",),
        continuation=("continuation",),
        planned_tasks=("task",),
        scenes=("scene",),
        forbidden_early_events=("later",),
    )


def _directory(*, titles=TITLES, count=3):
    chapters = tuple(
        SimpleNamespace(number=number, title=title)
        for number, title in enumerate(titles, 1)
    )
    return SimpleNamespace(
        project_id=PROJECT_ID,
        summary=SimpleNamespace(final_chapter_count=count),
        volumes=(SimpleNamespace(chapters=chapters),),
    )


def _chapter(number, *, title=None, outline=None, project_id=PROJECT_ID):
    return SimpleNamespace(
        project_id=project_id,
        chapter=SimpleNamespace(number=number, title=title or TITLES[number - 1]),
        outline=_outline() if outline is None else outline,
    )


class ManuscriptService:
    def __init__(self, *, directory=None, chapters=None, error=None):
        self.directory_result = directory or _directory()
        self.chapters = chapters or {number: _chapter(number) for number in range(1, 4)}
        self.error = error
        self.calls = []

    async def directory(self, project_id):
        self.calls.append(("directory", project_id))
        if self.error:
            raise self.error
        return self.directory_result

    async def chapter(self, project_id, chapter_number):
        self.calls.append(("chapter", project_id, chapter_number))
        if self.error:
            raise self.error
        return self.chapters[chapter_number]


class PreparationService:
    def __init__(self, *, authority=4, outline="current", error=None):
        self.result = SimpleNamespace(
            authoritative_chapter_number=authority,
            outline=outline,
        )
        self.error = error
        self.calls = []

    async def preparation(self, project_id):
        self.calls.append(project_id)
        if self.error:
            raise self.error
        return self.result


def _dependencies(*, manuscript=None, preparation=None):
    from backend.scripts.verify_manuscript_product_smoke import SmokeDependencies

    return SmokeDependencies(
        manuscript=manuscript or ManuscriptService(),
        preparation=preparation or PreparationService(),
    )


@pytest.mark.asyncio
async def test_smoke_calls_production_service_contracts_once_and_returns_safe_counts():
    from backend.scripts.verify_manuscript_product_smoke import verify_product_smoke

    manuscript = ManuscriptService()
    preparation = PreparationService()

    result = await verify_product_smoke(
        PROJECT_ID,
        dependencies=_dependencies(manuscript=manuscript, preparation=preparation),
    )

    assert manuscript.calls == [
        ("directory", PROJECT_ID),
        ("chapter", PROJECT_ID, 1),
        ("chapter", PROJECT_ID, 2),
        ("chapter", PROJECT_ID, 3),
    ]
    assert preparation.calls == [PROJECT_ID]
    assert result == {
        "projectId": PROJECT_ID,
        "status": "passed",
        "finalChapterCount": 3,
        "chapterChecks": 3,
        "outlineChecks": 3,
        "authorityChapter": 4,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("manuscript", "preparation"),
    (
        (ManuscriptService(directory=_directory(titles=("wrong", *TITLES[1:]))), PreparationService()),
        (ManuscriptService(chapters={1: _chapter(1, title="wrong"), 2: _chapter(2), 3: _chapter(3)}), PreparationService()),
        (ManuscriptService(chapters={1: _chapter(1, outline=False), 2: _chapter(2), 3: _chapter(3)}), PreparationService()),
        (ManuscriptService(directory=_directory(count=4)), PreparationService()),
        (ManuscriptService(), PreparationService(authority=5)),
        (ManuscriptService(), PreparationService(outline="missing")),
    ),
    ids=("directory-title", "chapter-title", "pinned-outline", "count", "authority", "current-outline"),
)
async def test_smoke_fails_closed_on_wrong_authority_title_outline_or_integrity(
    manuscript, preparation,
):
    from backend.scripts.verify_manuscript_product_smoke import (
        SmokeIntegrityError,
        verify_product_smoke,
    )

    with pytest.raises(SmokeIntegrityError):
        await verify_product_smoke(
            PROJECT_ID,
            dependencies=_dependencies(manuscript=manuscript, preparation=preparation),
        )


class Session:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", sql, args))
        return {"ok": 1}

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", sql, args))
        return ({"ok": 1},)


class ReadOnlyTransactionProbe:
    def __init__(self):
        self.session = Session()
        self.entered = self.exited = 0

    @asynccontextmanager
    async def __call__(self):
        self.entered += 1
        try:
            yield self.session
        finally:
            self.exited += 1


@pytest.mark.asyncio
async def test_guarded_transaction_preserves_read_only_boundary_and_select_reads():
    from backend.scripts.verify_manuscript_product_smoke import guarded_read_only_transaction

    transaction = ReadOnlyTransactionProbe()
    factory = guarded_read_only_transaction(transaction)

    async with factory() as session:
        assert await session.fetchone("SELECT value FROM safe_table WHERE id=%s", (PROJECT_ID,)) == {"ok": 1}
        assert await session.fetchall("\n SELECT value FROM safe_table") == ({"ok": 1},)

    assert transaction.entered == transaction.exited == 1
    assert transaction.session.calls == [
        ("fetchone", "SELECT value FROM safe_table WHERE id=%s", (PROJECT_ID,)),
        ("fetchall", "\n SELECT value FROM safe_table", None),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    (
        "INSERT INTO x VALUES (1)", "UPDATE x SET y=1", "DELETE FROM x",
        "REPLACE INTO x VALUES (1)", "ALTER TABLE x ADD y INT", "DROP TABLE x",
        "CREATE TABLE x (id INT)", "TRUNCATE TABLE x", "SELECT 1; SELECT 2",
        "SELECT 1 -- hidden write", "SELECT 1 # hidden write", "SELECT /* hidden */ 1",
        "WITH disguised AS (SELECT 1) SELECT * FROM disguised",
        "(SELECT 1)", "SELECT 'safe';", "SELECT 1 UNION UPDATE x SET y=1",
    ),
)
async def test_sql_guard_rejects_writes_multiple_statements_comments_and_ctes(sql):
    from backend.scripts.verify_manuscript_product_smoke import ReadOnlySqlError, ReadOnlySqlSession

    underlying = Session()
    guarded = ReadOnlySqlSession(underlying)

    with pytest.raises(ReadOnlySqlError):
        await guarded.fetchone(sql)
    assert underlying.calls == []


@pytest.mark.asyncio
async def test_sql_guard_rejects_execute_even_for_select():
    from backend.scripts.verify_manuscript_product_smoke import ReadOnlySqlError, ReadOnlySqlSession

    underlying = Session()
    with pytest.raises(ReadOnlySqlError):
        await ReadOnlySqlSession(underlying).execute("SELECT 1")
    assert underlying.calls == []


@pytest.mark.parametrize(
    "argv",
    ((), (PROJECT_ID,), ("--project-id",), ("--project-id", PROJECT_ID, "extra"),
     ("--project-id", PROJECT_ID, "--project-id", "second")),
)
def test_cli_requires_exactly_one_explicit_project_id(argv):
    from backend.scripts.verify_manuscript_product_smoke import SmokeArgumentError, parse_project_id

    with pytest.raises(SmokeArgumentError):
        parse_project_id(argv)


def test_cli_accepts_one_explicit_project_id():
    from backend.scripts.verify_manuscript_product_smoke import parse_project_id

    assert parse_project_id(("--project-id", PROJECT_ID)) == PROJECT_ID


@pytest.mark.asyncio
async def test_run_cli_prints_only_fixed_safe_summary():
    import json
    from backend.scripts.verify_manuscript_product_smoke import run_cli

    output = []
    assert await run_cli(
        ("--project-id", PROJECT_ID),
        dependencies=_dependencies(),
        output=output.append,
    ) == 0

    assert json.loads(output[0]) == {
        "authorityChapter": 4,
        "chapterChecks": 3,
        "finalChapterCount": 3,
        "outlineChecks": 3,
        "projectId": PROJECT_ID,
        "status": "passed",
    }
    assert not any(title in output[0] for title in TITLES)
    assert "content" not in output[0].lower()
    assert "hash" not in output[0].lower()


def test_main_redacts_sensitive_exceptions_and_returns_fixed_failure_category(capsys):
    from backend.scripts.verify_manuscript_product_smoke import main

    code = main(
        ("--project-id", PROJECT_ID),
        dependencies=_dependencies(manuscript=ManuscriptService(error=RuntimeError(SECRET))),
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.strip() == (
        '{"category":"unexpected","projectId":"' + PROJECT_ID + '","status":"failed"}'
    )
    assert SECRET not in captured.err


def test_main_redacts_invalid_extra_argument(capsys):
    from backend.scripts.verify_manuscript_product_smoke import main

    code = main(("--project-id", PROJECT_ID, SECRET), dependencies=_dependencies())

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert captured.err.strip() == '{"category":"arguments","status":"failed"}'
    assert SECRET not in captured.err
