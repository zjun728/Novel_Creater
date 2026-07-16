from decimal import Decimal
import json

import aiomysql
import pytest

from backend.database import DatabaseSession
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.reset_writer_core_data import (
    M1_MANIFEST_HASH,
    M1_SCHEMA_VERSION,
    M1_TABLE_NAMES,
    ResetPartialStateError,
    ResetRequest,
    reset_writer_core_data,
)
from backend.scripts.verify_milestone2_product import verify_milestone2_product


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


def request():
    return ResetRequest(
        project_title="永乐大典",
        seed_titles=tuple(title for _, title in SEEDS),
        preferred_provider_name="联通云",
        preferred_model="deepseek-v4-flash",
    )


def seed_payload(title):
    return SeedPayload(
        title=title,
        genre="历史穿越",
        logline=f"{title}的合成测试梗概",
        protagonist="测试主角",
        desire="完成可验证目标",
        coreConflict="守住唯一事实源",
        worldPressure="时间窗口持续收紧",
        openingHook="一页异常典籍出现",
        differentiation="仅用于M1到M2重建测试",
    )


async def create_m1_product_state(session):
    ddl = {
        "schema_metadata": """CREATE TABLE schema_metadata (
            singleton_id TINYINT PRIMARY KEY,schema_version VARCHAR(64) NOT NULL,
            manifest_hash CHAR(64) NOT NULL,initialized_at BIGINT NOT NULL)""",
        "projects": """CREATE TABLE projects (
            id CHAR(36) PRIMARY KEY,title VARCHAR(200) NOT NULL,genre VARCHAR(120) NOT NULL,
            description TEXT NOT NULL,target_words INT NOT NULL,target_chapters INT NOT NULL,
            status VARCHAR(24) NOT NULL,current_chapter INT NOT NULL,created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL)""",
        "creative_seeds": """CREATE TABLE creative_seeds (
            id CHAR(36) PRIMARY KEY,project_id CHAR(36) NOT NULL,title VARCHAR(200) NOT NULL,
            premise_json JSON NOT NULL,content_hash CHAR(64) NOT NULL,status VARCHAR(24) NOT NULL,
            created_at BIGINT NOT NULL)""",
        "project_selected_seeds": """CREATE TABLE project_selected_seeds (
            project_id CHAR(36) PRIMARY KEY,seed_id CHAR(36) NOT NULL,selected_at BIGINT NOT NULL)""",
        "provider_profiles": """CREATE TABLE provider_profiles (
            id CHAR(36) PRIMARY KEY,name VARCHAR(120) NOT NULL,provider_type VARCHAR(64) NOT NULL,
            model_name VARCHAR(160) NOT NULL,base_url VARCHAR(2048) NOT NULL,api_key TEXT NOT NULL,
            enabled TINYINT NOT NULL,sort_order INT NOT NULL,stream TINYINT NOT NULL,
            max_context_tokens INT NOT NULL,max_output_tokens INT NOT NULL,
            temperature DECIMAL(5,3) NOT NULL,top_p DECIMAL(5,3) NOT NULL,
            supports_json TINYINT NOT NULL,supports_streaming TINYINT NOT NULL,
            notes TEXT NOT NULL,thinking JSON NULL,created_at BIGINT NOT NULL,updated_at BIGINT NOT NULL)""",
        "task_model_bindings": """CREATE TABLE task_model_bindings (
            id CHAR(36) PRIMARY KEY,project_id CHAR(36) NOT NULL,source_project_id CHAR(36) NULL,
            created_at BIGINT NOT NULL,updated_at BIGINT NOT NULL)""",
        "task_model_binding_items": """CREATE TABLE task_model_binding_items (
            id CHAR(36) PRIMARY KEY,project_id CHAR(36) NOT NULL,binding_id CHAR(36) NOT NULL,
            task_key VARCHAR(100) NOT NULL,provider_id CHAR(36) NOT NULL,
            model_name VARCHAR(160) NOT NULL,created_at BIGINT NOT NULL,updated_at BIGINT NOT NULL)""",
        "canon_revisions": """CREATE TABLE canon_revisions (
            id CHAR(36) PRIMARY KEY,project_id CHAR(36) NOT NULL,revision_number INT NOT NULL,
            content_hash CHAR(64) NOT NULL)""",
        "projection_heads": """CREATE TABLE projection_heads (
            project_id CHAR(36) PRIMARY KEY,canon_revision_number INT NOT NULL,
            projection_revision_number INT NOT NULL,content_hash CHAR(64) NOT NULL)""",
    }
    for table in M1_TABLE_NAMES:
        await session.execute(ddl.get(table, f"CREATE TABLE {table} (id INT PRIMARY KEY)"))
    await session.execute(
        "INSERT INTO schema_metadata VALUES (1,%s,%s,1)",
        (M1_SCHEMA_VERSION, M1_MANIFEST_HASH),
    )
    await session.execute(
        "INSERT INTO projects VALUES (%s,%s,%s,%s,%s,%s,%s,0,1,1)",
        (PROJECT_ID, "永乐大典", "历史穿越", "M1 foundation", 1_000_000, 300, "drafting"),
    )
    for seed_id, title in SEEDS:
        payload = seed_payload(title)
        await session.execute(
            "INSERT INTO creative_seeds VALUES (%s,%s,%s,%s,%s,'candidate',1)",
            (seed_id, PROJECT_ID, title, canonical_json(payload), canonical_hash(payload)),
        )
    await session.execute(
        "INSERT INTO project_selected_seeds VALUES (%s,%s,1)",
        (PROJECT_ID, SEEDS[2][0]),
    )
    for provider_id, name, model, enabled, sort_order in PROVIDERS:
        await session.execute(
            """INSERT INTO provider_profiles VALUES
               (%s,%s,'openai-compatible',%s,%s,%s,%s,%s,1,200000,4096,%s,%s,1,1,%s,%s,1,1)""",
            (
                provider_id, name, model, f"https://{name}.example/v1",
                f"private-{provider_id}", enabled, sort_order,
                Decimal("0.800"), Decimal("0.900"), "private notes", json.dumps({"mode": "private"}),
            ),
        )
    binding_id = "44444444-4444-4444-4444-444444444444"
    await session.execute(
        "INSERT INTO task_model_bindings VALUES (%s,%s,NULL,1,1)",
        (binding_id, PROJECT_ID),
    )
    for index, task_key in enumerate(TASK_KEYS):
        await session.execute(
            "INSERT INTO task_model_binding_items VALUES (%s,%s,%s,%s,%s,%s,1,1)",
            (
                f"55555555-5555-5555-5555-{index:012d}", PROJECT_ID, binding_id,
                task_key, PROVIDERS[0][0], PROVIDERS[0][2],
            ),
        )
    empty_hash = "0" * 64
    await session.execute(
        "INSERT INTO canon_revisions VALUES (%s,%s,0,%s)",
        ("66666666-6666-6666-6666-666666666666", PROJECT_ID, empty_hash),
    )
    await session.execute(
        "INSERT INTO projection_heads VALUES (%s,0,0,%s)",
        (PROJECT_ID, empty_hash),
    )


class RecordingProxy:
    def __init__(self, session, fail_on=None):
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

    async def close(self):
        return await self.session.close()


async def open_database(config):
    connection = await aiomysql.connect(**config)
    return connection, DatabaseSession(connection)


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_exact_m1_rebuilds_to_fresh_m2_then_execute_is_idempotent_noop(
    empty_disposable_mysql,
):
    await create_m1_product_state(empty_disposable_mysql.session)
    dry_proxy = RecordingProxy(empty_disposable_mysql.admin_session)
    dry = await reset_writer_core_data(
        dry_proxy,
        database_name=empty_disposable_mysql.database_name,
        confirm_reset=empty_disposable_mysql.database_name,
        request=request(),
        execute=False,
        allow_product_database=False,
        output=lambda _value: None,
    )
    assert not dry.executed
    assert not any(kind == "execute" for kind, _, _ in dry_proxy.calls)

    report = await reset_writer_core_data(
        empty_disposable_mysql.admin_session,
        database_name=empty_disposable_mysql.database_name,
        confirm_reset=empty_disposable_mysql.database_name,
        request=request(),
        execute=True,
        allow_product_database=False,
        output=lambda _value: None,
    )
    assert report.executed

    connection, session = await open_database(empty_disposable_mysql.connection_config)
    try:
        receipt = await verify_milestone2_product(session)
        assert receipt["schemaVersion"] == EXPECTED_SCHEMA_VERSION
        assert receipt["manifestHash"] == manifest_hash()
        assert receipt["project"]["selectedSeedTitle"] == "典镇山河"
        assert receipt["project"]["providerCount"] == len(PROVIDERS)
    finally:
        connection.close()

    noop_proxy = RecordingProxy(empty_disposable_mysql.admin_session)
    noop = await reset_writer_core_data(
        noop_proxy,
        database_name=empty_disposable_mysql.database_name,
        confirm_reset=empty_disposable_mysql.database_name,
        request=request(),
        execute=True,
        allow_product_database=False,
        output=lambda _value: None,
    )
    assert not noop.executed
    forbidden = ("DROP DATABASE", "CREATE DATABASE", "CREATE TABLE", "INSERT ", "UPDATE ", "DELETE ")
    assert not any(
        kind == "execute" and sql.lstrip().upper().startswith(forbidden)
        for kind, sql, _ in noop_proxy.calls
    )


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_failed_m1_rebuild_drops_incomplete_database_and_releases_lock(
    empty_disposable_mysql,
):
    await create_m1_product_state(empty_disposable_mysql.session)
    proxy = RecordingProxy(empty_disposable_mysql.admin_session, fail_on="INSERT INTO projects")

    with pytest.raises(ResetPartialStateError):
        await reset_writer_core_data(
            proxy,
            database_name=empty_disposable_mysql.database_name,
            confirm_reset=empty_disposable_mysql.database_name,
            request=request(),
            execute=True,
            allow_product_database=False,
            output=lambda _value: None,
        )

    remaining = await empty_disposable_mysql.admin_session.fetchone(
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
        (empty_disposable_mysql.database_name,),
    )
    assert remaining is None
    assert any("RELEASE_LOCK" in sql for kind, sql, _ in proxy.calls if kind == "fetchone")
    # Restore an empty disposable shell so the shared fixture can account for
    # its own created/cleaned lifecycle in the terminal summary.
    await empty_disposable_mysql.admin_session.execute(
        f"CREATE DATABASE `{empty_disposable_mysql.database_name}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
    )
