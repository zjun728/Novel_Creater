import pytest

from backend.scripts.reset_writer_core_data import (
    RESET_LOCK_NAME,
    ResetPartialStateError,
    ResetRequest,
    ResetSafetyError,
    reset_writer_core_data,
    run_cli,
)


DISPOSABLE = "novel_creator_test_0123456789abcdef0123456789abcdef"


class RecordingAdminSession:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", " ".join(sql.split()), args))
        if ".`projects`" in sql:
            return [{
                "id": "project", "title": "永乐大典", "genre": "历史",
                "description": "DESCRIPTION_SENTINEL", "target_words": 1,
                "target_chapters": 1, "status": "active", "current_chapter": 0,
                "created_at": 1, "updated_at": 1,
            }]
        if ".`creative_seeds`" in sql:
            return [
                {"id": str(index), "project_id": "project", "title": title,
                 "premise_json": "{}", "content_hash": "1" * 64,
                 "status": "candidate", "created_at": 1}
                for index, title in enumerate(("永乐长明", "文渊山海", "典镇山河"), 1)
            ]
        if ".`provider_profiles`" in sql:
            return [{
                "id": "provider", "name": "联通云", "provider_type": "test",
                "model_name": "deepseek-v4-flash", "base_url": "BASE_URL_SENTINEL",
                "api_key": "API_KEY_SENTINEL", "enabled": 1, "sort_order": 0,
                "stream": 1, "max_context_tokens": 1, "max_output_tokens": 1,
                "temperature": 0.7, "top_p": 0.9, "supports_json": 1,
                "supports_streaming": 1, "notes": "NOTES_SENTINEL",
                "thinking": None, "created_at": 1, "updated_at": 1,
            }]
        raise AssertionError(f"unexpected SELECT: {sql}")

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        raise AssertionError(f"unexpected SELECT: {sql}")

    async def execute(self, sql, args=None):
        self.calls.append(("execute", " ".join(sql.split()), args))
        raise AssertionError(f"dry-run executed SQL: {sql}")

    async def close(self):
        self.closed = True


def request(**changes):
    values = {
        "project_title": "永乐大典",
        "seed_titles": ("永乐长明", "文渊山海", "典镇山河"),
        "preferred_provider_name": "联通云",
        "preferred_model": "deepseek-v4-flash",
    }
    values.update(changes)
    return ResetRequest(**values)


@pytest.mark.parametrize("seed_titles", [(), ("a", "b"), ("a", "a", "c"), ("a", "b", "c", "d")])
def test_reset_request_requires_exactly_three_unique_seed_titles(seed_titles):
    with pytest.raises(ValueError, match="three unique"):
        request(seed_titles=seed_titles)


@pytest.mark.asyncio
async def test_dry_run_reads_only_three_preserve_tables_and_redacts_secrets():
    session = RecordingAdminSession()
    output = []

    report = await reset_writer_core_data(
        session,
        database_name=DISPOSABLE,
        confirm_reset=DISPOSABLE,
        request=request(),
        execute=False,
        allow_product_database=False,
        output=output.append,
    )

    assert report.executed is False
    selected_sql = " ".join(sql for kind, sql, _ in session.calls if kind.startswith("fetch"))
    assert "`projects`" in selected_sql
    assert "`creative_seeds`" in selected_sql
    assert "`provider_profiles`" in selected_sql
    for forbidden in (
        "chapters", "versions", "canon_events", "settings", "memory_views",
        "arc_projections", "volume_plans", "story_blocks", "audits", "qa",
    ):
        assert f".`{forbidden}`" not in selected_sql.lower()
    rendered = "\n".join(output)
    for secret in ("DESCRIPTION_SENTINEL", "BASE_URL_SENTINEL", "API_KEY_SENTINEL", "NOTES_SENTINEL"):
        assert secret not in rendered


@pytest.mark.asyncio
async def test_execute_confirmation_mismatch_rejects_before_connection():
    called = False

    async def connection_factory(config):
        nonlocal called
        called = True
        return RecordingAdminSession()

    with pytest.raises(ResetSafetyError, match="confirmation"):
        await run_cli(
            [
                "--database", DISPOSABLE,
                "--confirm-reset", "novel_creator_test_ffffffffffffffffffffffffffffffff",
                "--project-title", "永乐大典",
                "--seed-title", "永乐长明",
                "--seed-title", "文渊山海",
                "--seed-title", "典镇山河",
                "--preferred-provider-name", "联通云",
                "--preferred-model", "deepseek-v4-flash",
                "--execute",
            ],
            connection_factory=connection_factory,
            connection_config={"password": "PASSWORD_SENTINEL"},
        )

    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("execute", (False, True))
async def test_direct_core_call_cannot_authorize_product_database(execute):
    session = RecordingAdminSession()

    with pytest.raises(ResetSafetyError, match="novel_creator"):
        await reset_writer_core_data(
            session,
            database_name="novel_creator",
            confirm_reset="novel_creator",
            request=request(),
            execute=execute,
            allow_product_database=True,
        )

    assert session.calls == []


@pytest.mark.asyncio
async def test_cli_product_dry_run_is_rejected_before_connection():
    called = False

    async def connection_factory(config):
        nonlocal called
        called = True
        return RecordingAdminSession()

    with pytest.raises(ResetSafetyError, match="novel_creator"):
        await run_cli(
            [
                "--database", "novel_creator",
                "--confirm-reset", "novel_creator",
                "--project-title", "永乐大典",
                "--seed-title", "永乐长明",
                "--seed-title", "文渊山海",
                "--seed-title", "典镇山河",
                "--preferred-provider-name", "联通云",
                "--preferred-model", "deepseek-v4-flash",
            ],
            connection_factory=connection_factory,
            connection_config={},
        )

    assert called is False


@pytest.mark.asyncio
async def test_only_matching_cli_execute_authorizes_product_core_flag():
    session = RecordingAdminSession()
    captured = []

    async def connection_factory(config):
        return session

    async def reset_function(admin_session, **kwargs):
        captured.append((admin_session, kwargs))

    result = await run_cli(
        [
            "--database", "novel_creator",
            "--confirm-reset", "novel_creator",
            "--project-title", "永乐大典",
            "--seed-title", "永乐长明",
            "--seed-title", "文渊山海",
            "--seed-title", "典镇山河",
            "--preferred-provider-name", "联通云",
            "--preferred-model", "deepseek-v4-flash",
            "--execute",
        ],
        connection_factory=connection_factory,
        connection_config={},
        reset_function=reset_function,
    )

    assert result == 0
    assert session.closed
    assert len(captured) == 1
    assert captured[0][0] is session
    assert captured[0][1]["allow_product_database"] is True


@pytest.mark.asyncio
async def test_cli_dry_run_uses_injected_server_session_and_closes_it():
    session = RecordingAdminSession()
    output = []

    async def connection_factory(config):
        assert config == {"password": "PASSWORD_SENTINEL"}
        return session

    result = await run_cli(
        [
            "--database", DISPOSABLE,
            "--confirm-reset", DISPOSABLE,
            "--project-title", "永乐大典",
            "--seed-title", "永乐长明",
            "--seed-title", "文渊山海",
            "--seed-title", "典镇山河",
            "--preferred-provider-name", "联通云",
            "--preferred-model", "deepseek-v4-flash",
        ],
        connection_factory=connection_factory,
        connection_config={"password": "PASSWORD_SENTINEL"},
        output=output.append,
    )

    assert result == 0
    assert session.closed
    assert "PASSWORD_SENTINEL" not in "\n".join(output)


@pytest.mark.asyncio
async def test_ddl_failure_reports_partial_state_and_releases_advisory_lock():
    class FailingCreateSession(RecordingAdminSession):
        async def fetchone(self, sql, args=None):
            normalized = " ".join(sql.split())
            self.calls.append(("fetchone", normalized, args))
            if "GET_LOCK" in sql:
                return {"acquired": 1}
            if "RELEASE_LOCK" in sql:
                return {"released": 1}
            raise AssertionError(f"unexpected SELECT: {sql}")

        async def execute(self, sql, args=None):
            normalized = " ".join(sql.split())
            self.calls.append(("execute", normalized, args))
            if sql.startswith("DROP DATABASE"):
                return 1
            if sql.startswith("CREATE DATABASE"):
                raise RuntimeError("injected CREATE failure")
            raise AssertionError(f"unexpected execute: {sql}")

    session = FailingCreateSession()

    with pytest.raises(ResetPartialStateError, match="partially reset") as raised:
        await reset_writer_core_data(
            session,
            database_name=DISPOSABLE,
            confirm_reset=DISPOSABLE,
            request=request(),
            execute=True,
            allow_product_database=False,
            output=lambda value: None,
        )

    assert "injected CREATE failure" in str(raised.value.__cause__)
    assert any(
        kind == "fetchone" and "RELEASE_LOCK" in sql and args == (RESET_LOCK_NAME,)
        for kind, sql, args in session.calls
    )
    drop_index = next(
        index for index, (_, sql, _) in enumerate(session.calls)
        if sql.startswith("DROP DATABASE")
    )
    before_drop = session.calls[:drop_index]
    assert before_drop[0][0] == "fetchone" and "GET_LOCK" in before_drop[0][1]
    preserved_selects = [
        sql for kind, sql, _ in before_drop
        if kind == "fetchall"
    ]
    assert len(preserved_selects) == 3
    assert all(
        any(f".`{table}`" in sql for table in ("projects", "creative_seeds", "provider_profiles"))
        for sql in preserved_selects
    )
