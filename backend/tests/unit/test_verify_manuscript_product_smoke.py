from __future__ import annotations

import asyncio
import builtins
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
        "chapterCheckCount": 3,
        "pinnedCheckCount": 3,
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
    ),
    ids=("directory-title", "chapter-title", "pinned-outline", "count", "authority"),
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


@pytest.mark.asyncio
async def test_smoke_accepts_authority_four_when_next_outline_is_missing():
    from backend.scripts.verify_manuscript_product_smoke import verify_product_smoke

    result = await verify_product_smoke(
        PROJECT_ID,
        dependencies=_dependencies(
            preparation=PreparationService(authority=4, outline="missing"),
        ),
    )

    assert result["status"] == "passed"


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
        "SELECT value INTO @captured FROM safe_table",
        "SELECT value INTO OUTFILE '/tmp/export' FROM safe_table",
        "SELECT value INTO DUMPFILE '/tmp/export' FROM safe_table",
        "SELECT value FROM safe_table FOR UPDATE",
        "SELECT value FROM safe_table LOCK IN SHARE MODE",
        "SELECT GET_LOCK('smoke', 1) FROM safe_table",
        "SELECT RELEASE_LOCK('smoke') FROM safe_table",
        "SELECT IS_FREE_LOCK('smoke') FROM safe_table",
        "SELECT IS_USED_LOCK('smoke') FROM safe_table",
        "SELECT LOAD_FILE('/tmp/private') FROM safe_table",
        "SELECT SLEEP(1) FROM safe_table",
        "SELECT BENCHMARK(1, SHA2('x', 256)) FROM safe_table",
        "SELECT product_udf(value) FROM safe_table",
        "SELECT `product_udf`(value) FROM safe_table",
        "SELECT `product`.`product_udf`(value) FROM safe_table",
        'SELECT "product_udf"(value) FROM safe_table',
        "SELECT @captured := value FROM safe_table",
        "SELECT 危险函数(value) FROM safe_table",
        "SELECT 危险udf(value) FROM safe_table",
        "SELECT café(value) FROM safe_table",
        "SELECT 1",
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


@pytest.mark.asyncio
async def test_sql_guard_allows_unicode_only_inside_single_quoted_literal():
    from backend.scripts.verify_manuscript_product_smoke import ReadOnlySqlSession

    underlying = Session()
    sql = "SELECT value FROM safe_table WHERE status='中文值'"

    assert await ReadOnlySqlSession(underlying).fetchone(sql) == {"ok": 1}
    assert underlying.calls == [("fetchone", sql, None)]


@pytest.mark.asyncio
async def test_default_dependencies_share_guarded_production_read_only_factory(monkeypatch):
    from backend import database
    from backend.scripts.verify_manuscript_product_smoke import (
        ReadOnlySqlSession,
        _default_dependencies,
    )
    from backend.services.manuscripts import ManuscriptReadingService
    from backend.services.project_lifecycle import ProjectLifecycleService

    entered = exited = 0
    underlying = Session()

    @asynccontextmanager
    async def fake_read_only_transaction():
        nonlocal entered, exited
        entered += 1
        try:
            yield underlying
        finally:
            exited += 1

    monkeypatch.setattr(database, "read_only_transaction", fake_read_only_transaction)

    dependencies = _default_dependencies()

    assert isinstance(dependencies.manuscript, ManuscriptReadingService)
    assert isinstance(dependencies.preparation, ProjectLifecycleService)
    assert (
        dependencies.manuscript._transaction_factory
        is dependencies.preparation.transaction_factory
        is dependencies.preparation.connection_factory
    )
    async with dependencies.manuscript._transaction_factory() as session:
        assert isinstance(session, ReadOnlySqlSession)
        assert await session.fetchone("SELECT value FROM safe_table") == {"ok": 1}
    assert entered == exited == 1
    assert underlying.calls == [("fetchone", "SELECT value FROM safe_table", None)]


class ProductQueryCorpusSession(Session):
    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", sql, args))
        normalized = " ".join(sql.split()).lower()
        if "from projects where id=%s" in normalized:
            return {"id": PROJECT_ID, "archived_at": None}
        if "from project_contract_heads" in normalized:
            return {"revision": 0}
        return None

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", sql, args))
        return []


@pytest.mark.asyncio
async def test_default_production_service_query_corpus_passes_guard(monkeypatch):
    from backend import database
    from backend.repositories.contracts import ContractRepository
    from backend.scripts.verify_manuscript_product_smoke import _default_dependencies
    from backend.services.manuscripts import ManuscriptProjectNotFound

    underlying = ProductQueryCorpusSession()

    @asynccontextmanager
    async def fake_read_only_transaction():
        yield underlying

    monkeypatch.setattr(database, "read_only_transaction", fake_read_only_transaction)
    dependencies = _default_dependencies()

    with pytest.raises(ManuscriptProjectNotFound):
        await dependencies.manuscript.directory(PROJECT_ID)
    for number in range(1, 4):
        with pytest.raises(ManuscriptProjectNotFound):
            await dependencies.manuscript.chapter(PROJECT_ID, number)
    preparation = await dependencies.preparation.preparation(PROJECT_ID)
    async with dependencies.manuscript._transaction_factory() as session:
        binding = await ContractRepository().read_binding_snapshot(
            session,
            PROJECT_ID,
        )

    assert preparation.authoritative_chapter_number == 1
    assert binding is None
    assert len(underlying.calls) >= 20
    assert all(call[1].lstrip().lower().startswith("select") for call in underlying.calls)


@pytest.mark.asyncio
async def test_real_read_only_transaction_starts_read_only_commits_and_releases(monkeypatch):
    from backend import database
    from backend.tests.support.fakes import FakePool

    pool = FakePool()

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(database, "get_pool", fake_get_pool)

    async with database.read_only_transaction() as session:
        assert await session.fetchone("SELECT one") == {"value": "one"}

    assert pool.raw.executions[0] == ("START TRANSACTION READ ONLY", None)
    assert pool.raw.commit_count == 1
    assert pool.raw.rollback_count == 0
    assert pool.acquire_count == pool.release_count == 1


@pytest.mark.asyncio
async def test_real_read_only_transaction_rolls_back_error_and_releases(monkeypatch):
    from backend import database
    from backend.tests.support.fakes import FakePool

    pool = FakePool()

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(database, "get_pool", fake_get_pool)

    with pytest.raises(RuntimeError, match="body failed"):
        async with database.read_only_transaction():
            raise RuntimeError("body failed")

    assert pool.raw.executions[0] == ("START TRANSACTION READ ONLY", None)
    assert pool.raw.commit_count == 0
    assert pool.raw.rollback_count == 1
    assert pool.acquire_count == pool.release_count == 1


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


@pytest.mark.parametrize(
    "argv",
    (
        ("--project-id", "not-a-uuid"),
        ("--project-id", "x" * 100_000),
        ("--project-id", PROJECT_ID + "\x7f"),
        ("--project-id", PROJECT_ID + "\u202e"),
        ("--project-id", PROJECT_ID.upper()),
        ("--project-id", "{" + PROJECT_ID + "}"),
        ("--project-id", PROJECT_ID.replace("-", "")),
        ("--pro", PROJECT_ID),
        ("--project", PROJECT_ID),
    ),
    ids=(
        "not-uuid", "oversized", "del", "bidi", "uppercase", "braced",
        "unhyphenated", "short-abbreviation", "long-abbreviation",
    ),
)
def test_cli_rejects_noncanonical_or_abbreviated_project_id(argv):
    from backend.scripts.verify_manuscript_product_smoke import (
        SmokeArgumentError,
        parse_project_id,
    )

    with pytest.raises(SmokeArgumentError):
        parse_project_id(argv)


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
        "chapterCheckCount": 3,
        "finalChapterCount": 3,
        "pinnedCheckCount": 3,
        "projectId": PROJECT_ID,
        "status": "passed",
    }
    assert set(json.loads(output[0])) == {
        "chapterCheckCount",
        "finalChapterCount",
        "pinnedCheckCount",
        "projectId",
        "status",
    }
    assert not any(title in output[0] for title in TITLES)
    assert "authority" not in output[0].lower()
    assert "outline" not in output[0].lower()
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


def test_main_default_path_owns_runtime_lifecycle_in_order(monkeypatch, capsys):
    from backend import config, database
    from backend.scripts import verify_manuscript_product_smoke as verifier

    events = []
    snapshot = object()
    dependencies = _dependencies()

    def load():
        events.append("load")
        return snapshot

    def install(value):
        assert value is snapshot
        events.append("install")

    def resolve_dependencies():
        events.append("dependencies")
        return dependencies

    async def close():
        events.append("close")

    def clear(value):
        assert value is snapshot
        events.append("clear")

    monkeypatch.setattr(config, "load_runtime_configuration", load)
    monkeypatch.setattr(config, "install_runtime_configuration", install)
    monkeypatch.setattr(config, "clear_runtime_configuration", clear)
    monkeypatch.setattr(database, "close_pool", close)
    monkeypatch.setattr(verifier, "_default_dependencies", resolve_dependencies)

    assert verifier.main(("--project-id", PROJECT_ID)) == 0
    assert events == ["load", "install", "dependencies", "close", "clear"]
    assert capsys.readouterr().err == ""


def test_main_injected_dependencies_do_not_touch_runtime_lifecycle(monkeypatch):
    from backend import config, database
    from backend.scripts import verify_manuscript_product_smoke as verifier

    def forbidden(*_args, **_kwargs):
        pytest.fail("injected dependencies must not touch runtime lifecycle")

    async def forbidden_async(*_args, **_kwargs):
        pytest.fail("injected dependencies must not touch runtime lifecycle")

    monkeypatch.setattr(config, "load_runtime_configuration", forbidden)
    monkeypatch.setattr(config, "install_runtime_configuration", forbidden)
    monkeypatch.setattr(config, "clear_runtime_configuration", forbidden)
    monkeypatch.setattr(database, "close_pool", forbidden_async)

    assert verifier.main(
        ("--project-id", PROJECT_ID),
        dependencies=_dependencies(),
    ) == 0


@pytest.mark.parametrize("failed_cleanup", ("close", "clear"))
def test_main_runtime_cleanup_failure_is_fixed_and_both_cleanup_steps_are_attempted(
    monkeypatch,
    capsys,
    failed_cleanup,
):
    from backend import config, database
    from backend.scripts import verify_manuscript_product_smoke as verifier

    events = []
    snapshot = object()

    monkeypatch.setattr(config, "load_runtime_configuration", lambda: snapshot)
    monkeypatch.setattr(config, "install_runtime_configuration", lambda _value: None)
    monkeypatch.setattr(verifier, "_default_dependencies", _dependencies)

    async def close():
        events.append("close")
        if failed_cleanup == "close":
            raise RuntimeError(SECRET)

    def clear(_value):
        events.append("clear")
        if failed_cleanup == "clear":
            raise RuntimeError(SECRET)

    monkeypatch.setattr(database, "close_pool", close)
    monkeypatch.setattr(config, "clear_runtime_configuration", clear)

    assert verifier.main(("--project-id", PROJECT_ID)) == 1
    captured = capsys.readouterr()
    assert events == ["close", "clear"]
    assert captured.out == ""
    assert captured.err.strip() == (
        '{"category":"unexpected","projectId":"'
        + PROJECT_ID
        + '","status":"failed"}'
    )
    assert SECRET not in captured.err


def _runtime_snapshot():
    from backend.config import RuntimeConfiguration

    return RuntimeConfiguration(
        mysql_items=(
            ("host", "127.0.0.1"),
            ("port", 3307),
            ("user", "owner"),
            ("password", "private"),
            ("db", "owner_database"),
            ("charset", "utf8mb4"),
            ("autocommit", True),
            ("minsize", 1),
            ("maxsize", 10),
        ),
        corpus_root=None,
        managed_corpus_root=None,
        market_scheduler_enabled=False,
    )


def test_install_rejection_does_not_close_or_clear_existing_runtime_owner(
    monkeypatch,
    capsys,
):
    from backend import config, database
    from backend.scripts import verify_manuscript_product_smoke as verifier
    from backend.tests.support.fakes import FakePool

    existing_owner = _runtime_snapshot()
    rejected_snapshot = _runtime_snapshot()
    existing_pool = FakePool()
    monkeypatch.setattr(config, "_active_runtime_configuration", existing_owner)
    monkeypatch.setattr(database, "_pool", existing_pool)
    monkeypatch.setattr(
        config,
        "load_runtime_configuration",
        lambda: rejected_snapshot,
    )

    assert verifier.main(("--project-id", PROJECT_ID)) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unexpected" in captured.err
    assert config.current_runtime_configuration() is existing_owner
    assert database._pool is existing_pool
    assert existing_pool.close_count == 0
    assert existing_pool.wait_closed_count == 0


@pytest.mark.parametrize(
    "cleanup_control_flow",
    (KeyboardInterrupt(), SystemExit(7), asyncio.CancelledError()),
    ids=("keyboard-interrupt", "system-exit", "async-cancellation"),
)
def test_cleanup_control_flow_outranks_primary_exception_and_still_clears(
    monkeypatch,
    cleanup_control_flow,
):
    from backend import config, database
    from backend.scripts import verify_manuscript_product_smoke as verifier

    snapshot = object()
    events = []
    monkeypatch.setattr(config, "load_runtime_configuration", lambda: snapshot)
    monkeypatch.setattr(config, "install_runtime_configuration", lambda _value: None)
    monkeypatch.setattr(
        verifier,
        "_default_dependencies",
        lambda: _dependencies(
            manuscript=ManuscriptService(error=RuntimeError(SECRET)),
        ),
    )

    async def close():
        events.append("close")
        raise cleanup_control_flow

    def clear(value):
        assert value is snapshot
        events.append("clear")

    monkeypatch.setattr(database, "close_pool", close)
    monkeypatch.setattr(config, "clear_runtime_configuration", clear)

    with pytest.raises(type(cleanup_control_flow)) as raised:
        verifier.main(("--project-id", PROJECT_ID))

    assert raised.value is cleanup_control_flow
    assert events == ["close", "clear"]


@pytest.mark.parametrize(
    "control_flow_error",
    (KeyboardInterrupt(), SystemExit(9), asyncio.CancelledError()),
    ids=("keyboard-interrupt", "system-exit", "async-cancellation"),
)
def test_main_preserves_control_flow_base_exceptions(control_flow_error):
    from backend.scripts.verify_manuscript_product_smoke import main

    with pytest.raises(type(control_flow_error)) as raised:
        main(
            ("--project-id", PROJECT_ID),
            dependencies=_dependencies(
                manuscript=ManuscriptService(error=control_flow_error),
            ),
        )

    assert raised.value is control_flow_error


def test_main_cold_import_failure_uses_fixed_unexpected_receipt(
    monkeypatch,
    capsys,
):
    from backend.scripts.verify_manuscript_product_smoke import main

    sentinel = "RAW_IMPORT_MUST_NOT_LEAK C:\\private\\machine\\module.py"
    real_import = builtins.__import__

    def failing_backend_import(name, *args, **kwargs):
        if name.startswith("backend."):
            raise ImportError(sentinel)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_backend_import)

    assert main(("--project-id", PROJECT_ID)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == (
        '{"category":"unexpected","projectId":"'
        + PROJECT_ID
        + '","status":"failed"}'
    )
    assert sentinel not in captured.err


def test_failure_category_preserves_known_safe_classifications():
    from backend.scripts.verify_manuscript_product_smoke import (
        ReadOnlySqlError,
        SmokeIntegrityError,
        _failure_category,
    )
    from backend.services.manuscripts import (
        ManuscriptProjectNotFound,
        ManuscriptTemporarilyUnavailable,
    )

    assert _failure_category(SmokeIntegrityError()) == "integrity"
    assert _failure_category(ManuscriptProjectNotFound()) == "not_found"
    assert _failure_category(ManuscriptTemporarilyUnavailable()) == "unavailable"
    assert _failure_category(ReadOnlySqlError()) == "read_only"
