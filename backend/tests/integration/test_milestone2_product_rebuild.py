from __future__ import annotations

from decimal import Decimal
import json

import aiomysql
import pytest

from backend.database import DatabaseSession
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import SeedPayload
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.initialize_database import initialize_database
from backend.scripts.reset_writer_core_data import (
    V11_MANIFEST_HASH,
    V11_SCHEMA_VERSION,
    V11_TABLE_NAMES,
    ResetPartialStateError,
    ResetRequest,
    ResetValidationError,
    _PreservedState,
    _insert_preserved_state,
    _map_project,
    _map_provider,
    _map_v11_seed,
    reset_writer_core_data,
)
from backend.scripts.verify_milestone2_product import verify_milestone2_product


pytestmark = pytest.mark.mysql

PROJECT_ID = "11111111-1111-1111-1111-111111111111"
SEEDS = (
    ("22222222-2222-2222-2222-222222222221", "永乐长明"),
    ("22222222-2222-2222-2222-222222222222", "文渊山海"),
    ("22222222-2222-2222-2222-222222222223", "典镇山河"),
)
PROVIDERS = (
    ("33333333-3333-3333-3333-333333333331", "联通云", "deepseek-v4-flash", 1, 0),
    ("33333333-3333-3333-3333-333333333332", "备用模型", "fallback-model", 0, 10),
)


def request() -> ResetRequest:
    return ResetRequest(
        project_title="永乐大典",
        seed_titles=tuple(title for _, title in SEEDS),
        preferred_provider_name="联通云",
        preferred_model="deepseek-v4-flash",
    )


def seed_payload(title: str) -> SeedPayload:
    return SeedPayload(
        title=title,
        genre="历史穿越",
        logline=f"{title}的合成测试梗概",
        protagonist="测试主角",
        desire="完成可验证目标",
        coreConflict="守住唯一事实源",
        worldPressure="时间窗口持续收紧",
        openingHook="一页异常典籍出现",
        differentiation="仅用于v1.1到v1.2重建测试",
    )


def provider_row(
    provider_id: str,
    name: str,
    model: str,
    enabled: int,
    sort_order: int,
) -> dict[str, object]:
    return _map_provider(
        {
            "id": provider_id,
            "name": name,
            "provider_type": "openai-compatible",
            "model_name": model,
            "base_url": f"https://{name}.example/v1",
            "api_key": f"private-{provider_id}",
            "enabled": enabled,
            "sort_order": sort_order,
            "stream": 1,
            "max_context_tokens": 200_000,
            "max_output_tokens": 4_096,
            "temperature": Decimal("0.800"),
            "top_p": Decimal("0.900"),
            "supports_json": 1,
            "supports_streaming": 1,
            "notes": "private notes",
            "thinking": {"mode": "private"},
            "lifecycle_status": "active",
            "deleted_at": None,
            "created_at": 1,
            "updated_at": 1,
        }
    )


async def create_frozen_v11_product_state(disposable) -> None:
    """Build a test-only v1.1 source inventory without product DB access."""
    await initialize_database(
        disposable.admin_session,
        disposable.database_name,
        disposable.database_name,
        1,
    )
    project = _map_project(
        {
            "id": PROJECT_ID,
            "title": "永乐大典",
            "genre": "历史穿越",
            "description": "v1.1 foundation",
            "target_words": 1_000_000,
            "target_chapters": 300,
            "status": "drafting",
            "current_chapter": 0,
            "created_at": 1,
            "updated_at": 1,
        }
    )
    seeds = []
    for seed_id, title in SEEDS:
        payload = seed_payload(title)
        seeds.append(
            _map_v11_seed(
                {
                    "id": seed_id,
                    "project_id": PROJECT_ID,
                    "title": title,
                    "premise_json": canonical_json(payload),
                    "content_hash": canonical_hash(payload),
                    "status": "candidate",
                    "created_at": 1,
                },
                PROJECT_ID,
            )
        )
    providers = tuple(provider_row(*row) for row in PROVIDERS)
    ids = (
        f"44444444-4444-4444-4444-{index:012d}" for index in range(100)
    )
    await _insert_preserved_state(
        disposable.session,
        _PreservedState(project, tuple(seeds), providers, providers[0]),
        now_ms=1,
        id_factory=ids.__next__,
    )
    await disposable.session.execute(
        """UPDATE schema_metadata
           SET schema_version=%s,manifest_hash=%s WHERE singleton_id=1""",
        (V11_SCHEMA_VERSION, V11_MANIFEST_HASH),
    )


class RecordingProxy:
    def __init__(self, session, fail_on: str | None = None):
        self.session = session
        self.fail_on = fail_on
        self.calls = []

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", sql, args))
        return await self.session.fetchone(sql, args)

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", sql, args))
        return await self.session.fetchall(sql, args)

    async def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("injected rebuild failure")
        return await self.session.execute(sql, args)


async def open_database(config):
    connection = await aiomysql.connect(**config)
    return connection, DatabaseSession(connection)


def assert_no_mutating_ddl(proxy: RecordingProxy) -> None:
    forbidden = ("DROP DATABASE", "CREATE DATABASE", "CREATE TABLE")
    assert not any(
        kind == "execute" and sql.lstrip().upper().startswith(forbidden)
        for kind, sql, _ in proxy.calls
    )


@pytest.mark.asyncio
async def test_frozen_v11_rebuilds_to_v12_then_v12_execute_is_noop(
    empty_disposable_mysql,
):
    await create_frozen_v11_product_state(empty_disposable_mysql)

    dry_proxy = RecordingProxy(empty_disposable_mysql.admin_session)
    dry_output = []
    dry = await reset_writer_core_data(
        dry_proxy,
        database_name=empty_disposable_mysql.database_name,
        confirm_reset=empty_disposable_mysql.database_name,
        request=request(),
        execute=False,
        output=dry_output.append,
    )
    assert dry.executed is False
    assert_no_mutating_ddl(dry_proxy)
    dry_receipt = json.loads(dry_output[0])
    assert dry_receipt["source"] == {
        **dry_receipt["source"],
        "kind": "v1.1-source",
        "schemaVersion": V11_SCHEMA_VERSION,
        "manifestHash": V11_MANIFEST_HASH,
        "tables": list(V11_TABLE_NAMES),
    }
    assert dry_receipt["target"]["kind"] == "v1.2-target"
    assert dry_receipt["target"]["schemaVersion"] == EXPECTED_SCHEMA_VERSION
    assert dry_receipt["target"]["tables"] == list(created_table_names())
    assert dry_receipt["target"]["verified"] is False
    assert "private-" not in dry_output[0]
    assert "api_key" not in dry_output[0].lower()

    report = await reset_writer_core_data(
        empty_disposable_mysql.admin_session,
        database_name=empty_disposable_mysql.database_name,
        confirm_reset=empty_disposable_mysql.database_name,
        request=request(),
        execute=True,
        output=lambda _value: None,
    )
    assert report.executed is True

    connection, session = await open_database(
        empty_disposable_mysql.connection_config
    )
    try:
        receipt = await verify_milestone2_product(
            session,
            expected_database=empty_disposable_mysql.database_name,
        )
        assert receipt["schemaVersion"] == EXPECTED_SCHEMA_VERSION
        assert receipt["manifestHash"] == manifest_hash()
        assert receipt["project"]["selectedSeedTitle"] == "典镇山河"
        assert receipt["project"]["providerCount"] == len(PROVIDERS)
        project = await session.fetchone(
            """SELECT id,status,archived_at,lifecycle_revision
                 FROM projects WHERE id=%s""",
            (PROJECT_ID,),
        )
        assert project == {
            "id": PROJECT_ID,
            "status": "drafting",
            "archived_at": None,
            "lifecycle_revision": 0,
        }
    finally:
        connection.close()

    noop_proxy = RecordingProxy(empty_disposable_mysql.admin_session)
    noop_output = []
    noop = await reset_writer_core_data(
        noop_proxy,
        database_name=empty_disposable_mysql.database_name,
        confirm_reset=empty_disposable_mysql.database_name,
        request=request(),
        execute=True,
        output=noop_output.append,
    )
    assert noop.executed is False
    assert noop.mode == "no-op"
    noop_receipt = json.loads(noop_output[0])
    assert noop_receipt["source"]["kind"] == "v1.2-target"
    assert noop_receipt["target"]["verified"] is True
    assert_no_mutating_ddl(noop_proxy)


@pytest.mark.asyncio
async def test_reset_classification_fails_closed_before_ddl(
    empty_disposable_mysql,
):
    await create_frozen_v11_product_state(empty_disposable_mysql)
    await empty_disposable_mysql.session.execute(
        """UPDATE schema_metadata SET manifest_hash=%s WHERE singleton_id=1""",
        ("0" * 64,),
    )
    proxy = RecordingProxy(empty_disposable_mysql.admin_session)

    with pytest.raises(ResetValidationError, match="v1.1 source or v1.2 target"):
        await reset_writer_core_data(
            proxy,
            database_name=empty_disposable_mysql.database_name,
            confirm_reset=empty_disposable_mysql.database_name,
            request=request(),
            execute=True,
            output=lambda _value: None,
        )

    assert_no_mutating_ddl(proxy)


@pytest.mark.asyncio
async def test_v12_noop_rejects_archived_foundation_before_ddl(
    empty_disposable_mysql,
):
    await create_frozen_v11_product_state(empty_disposable_mysql)
    await reset_writer_core_data(
        empty_disposable_mysql.admin_session,
        database_name=empty_disposable_mysql.database_name,
        confirm_reset=empty_disposable_mysql.database_name,
        request=request(),
        execute=True,
        output=lambda _value: None,
    )
    await empty_disposable_mysql.admin_session.execute(
        f"""UPDATE `{empty_disposable_mysql.database_name}`.projects
            SET archived_at=123,lifecycle_revision=1"""
    )
    proxy = RecordingProxy(empty_disposable_mysql.admin_session)

    with pytest.raises(ResetValidationError, match="unarchived"):
        await reset_writer_core_data(
            proxy,
            database_name=empty_disposable_mysql.database_name,
            confirm_reset=empty_disposable_mysql.database_name,
            request=request(),
            execute=True,
            output=lambda _value: None,
        )

    assert_no_mutating_ddl(proxy)


@pytest.mark.asyncio
async def test_failed_v11_rebuild_removes_incomplete_database_and_releases_lock(
    empty_disposable_mysql,
):
    await create_frozen_v11_product_state(empty_disposable_mysql)
    proxy = RecordingProxy(
        empty_disposable_mysql.admin_session,
        fail_on="INSERT INTO projects",
    )

    with pytest.raises(ResetPartialStateError):
        await reset_writer_core_data(
            proxy,
            database_name=empty_disposable_mysql.database_name,
            confirm_reset=empty_disposable_mysql.database_name,
            request=request(),
            execute=True,
            output=lambda _value: None,
        )

    remaining = await empty_disposable_mysql.admin_session.fetchone(
        """SELECT SCHEMA_NAME FROM information_schema.SCHEMATA
           WHERE SCHEMA_NAME=%s""",
        (empty_disposable_mysql.database_name,),
    )
    assert remaining is None
    assert any(
        "RELEASE_LOCK" in sql
        for kind, sql, _ in proxy.calls
        if kind == "fetchone"
    )
    await empty_disposable_mysql.admin_session.execute(
        f"CREATE DATABASE `{empty_disposable_mysql.database_name}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
    )
