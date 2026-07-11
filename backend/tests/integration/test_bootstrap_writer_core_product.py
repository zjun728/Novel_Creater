import json

import aiomysql
import pytest

from backend.domain.json_contracts import canonical_hash
from backend.domain.model_bindings import BindingItem, BindingRevision, TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.schema_manifest import created_table_names
from backend.scripts.bootstrap_writer_core_product import (
    LegacyInventory,
    _CLI_PRODUCT_EXECUTE_AUTHORITY,
    bootstrap_writer_core_product,
)
from backend.scripts.reset_writer_core_data import (
    VERIFIED_EMPTY_TABLES,
    _LEGACY_PROJECT_COLUMNS,
    _LEGACY_PROVIDER_COLUMNS,
    _LEGACY_SEED_COLUMNS,
)
from backend.tests.support.disposable_mysql import (
    _close_raw_connection,
    _open_admin_session,
    assert_disposable_name,
    new_database_name,
    test_server_config as _mysql_server_config,
)


def _source_inventory():
    project_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    project = dict(zip(_LEGACY_PROJECT_COLUMNS, (
        project_id, "永乐大典", "历史", "DESCRIPTION_SECRET", 1_000_000,
        500, 17, "active", 100, 200,
    )))
    seeds = []
    for index, title in enumerate(("永乐长明", "文渊山海", "典镇山河"), 1):
        seeds.append(dict(zip(_LEGACY_SEED_COLUMNS, (
            f"00000000-0000-0000-0000-{index:012d}", project_id, title,
            "历史", f"{title}故事", "主人公", "守护典籍", "朝局冲突",
            "天下大势", "开篇危机", "守护文明", "独特史观", "克制厚重",
            "user", None, None, "candidate", 100,
        ))))
    providers = (
        dict(zip(_LEGACY_PROVIDER_COLUMNS, (
            "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "联通云-DeepSeek-V4-Flash", "openai-compatible",
            "https://BASE_URL_SECRET.invalid", "API_KEY_SECRET",
            "DeepSeek-V4-Flash", 1, 128_000, 8_192, 0.7, 0.95, 1, 1,
            "NOTES_SECRET", None, 100, 200,
        ))),
        dict(zip(_LEGACY_PROVIDER_COLUMNS, (
            "ffffffff-ffff-ffff-ffff-ffffffffffff", "备用云",
            "openai-compatible", "https://BACKUP_SECRET.invalid", "BACKUP_KEY",
            "backup-model", 0, 64_000, 4_096, 0.5, 0.9, 0, 0,
            "BACKUP_NOTES", json.dumps({"budget": 3}), 90, 190,
        ))),
    )
    return LegacyInventory("5.7.44", (project,), tuple(seeds), providers)


@pytest.mark.mysql
@pytest.mark.asyncio
async def test_cross_server_bootstrap_builds_verified_disposable_target():
    config = _mysql_server_config()
    database_name = new_database_name()
    assert_disposable_name(database_name)
    admin_session = await _open_admin_session(config)
    database_connection = None
    ids = iter(
        f"10000000-0000-0000-0000-{index:012d}" for index in range(20)
    )
    output = []
    try:
        report = await bootstrap_writer_core_product(
            admin_session,
            database_name=database_name,
            source_loader=_source_inventory,
            execute=True,
            confirm_bootstrap=database_name,
            output=output.append,
            now_ms=lambda: 1_720_000_000_000,
            id_factory=lambda: next(ids),
            _product_authority=_CLI_PRODUCT_EXECUTE_AUTHORITY,
        )
        database_connection = await aiomysql.connect(**{**config, "db": database_name})
        cursor = await database_connection.cursor(aiomysql.DictCursor)
        try:
            expected = {
                "projects": 1,
                "creative_seeds": 3,
                "creative_seed_revisions": 3,
                "creative_seed_heads": 3,
                "provider_profiles": 2,
                "project_selected_seeds": 1,
                "project_model_binding_revisions": 1,
                "project_model_binding_items": len(TASK_KEYS),
                "project_model_binding_heads": 1,
                "canon_revisions": 1,
                "projection_heads": 1,
                "project_contract_heads": 1,
            }
            for table, count in expected.items():
                await cursor.execute(f"SELECT COUNT(*) AS count FROM `{table}`")
                assert (await cursor.fetchone())["count"] == count
            for table in VERIFIED_EMPTY_TABLES:
                await cursor.execute(f"SELECT COUNT(*) AS count FROM `{table}`")
                assert (await cursor.fetchone())["count"] == 0
            await cursor.execute("SELECT * FROM creative_seed_revisions ORDER BY seed_id")
            seed_revisions = await cursor.fetchall()
            for row in seed_revisions:
                payload = SeedPayload.model_validate(json.loads(row["payload_json"]), strict=True)
                assert row["revision"] == 1
                assert row["content_hash"] == canonical_hash(payload)
            await cursor.execute("SELECT * FROM project_selected_seeds")
            selected = await cursor.fetchone()
            selected_revision = next(
                row for row in seed_revisions if row["id"] == selected["seed_revision_id"]
            )
            assert json.loads(selected_revision["payload_json"])["title"] == "典镇山河"
            assert selected["seed_hash"] == selected_revision["content_hash"]
            assert selected["selection_revision"] == 1
            await cursor.execute("SELECT * FROM project_model_binding_revisions")
            binding_revision = await cursor.fetchone()
            await cursor.execute("SELECT * FROM project_model_binding_items")
            item_rows = await cursor.fetchall()
            items_by_key = {row["task_key"]: row for row in item_rows}
            domain_items = tuple(BindingItem(
                task_key=task_key,
                resolution_status="bound",
                provider_id=items_by_key[task_key]["provider_id"],
                provider_name_snapshot=items_by_key[task_key]["provider_name_snapshot"],
                model_name_snapshot=items_by_key[task_key]["model_name_snapshot"],
            ) for task_key in TASK_KEYS)
            domain_binding = BindingRevision(
                project_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                revision=1,
                items=domain_items,
            )
            assert binding_revision["content_hash"] == canonical_hash(domain_binding)
            assert all(
                items_by_key[item.task_key]["item_hash"] == canonical_hash(item)
                for item in domain_items
            )
            await cursor.execute("SELECT lifecycle_status, deleted_at FROM provider_profiles")
            assert await cursor.fetchall() == [
                {"lifecycle_status": "active", "deleted_at": None},
                {"lifecycle_status": "active", "deleted_at": None},
            ]
            await cursor.execute("SELECT * FROM project_contract_heads")
            contract_head = await cursor.fetchone()
            assert contract_head["revision"] == 0
            assert all(contract_head[key] is None for key in (
                "creation_contract_id", "style_contract_id", "creation_hash", "style_hash"
            ))
            assert set(expected) | set(VERIFIED_EMPTY_TABLES) | {"schema_metadata"} == set(
                created_table_names()
            )
        finally:
            await cursor.close()
        assert report.binding_item_count == 8
        rendered = "\n".join(output)
        for secret in (
            "DESCRIPTION_SECRET", "BASE_URL_SECRET", "API_KEY_SECRET",
            "NOTES_SECRET", "BACKUP_SECRET", "BACKUP_KEY", "BACKUP_NOTES",
        ):
            assert secret not in rendered
    finally:
        try:
            if database_connection is not None:
                await _close_raw_connection(database_connection)
        finally:
            try:
                assert_disposable_name(database_name)
                await admin_session.execute(
                    f"DROP DATABASE IF EXISTS `{database_name}`"
                )
            finally:
                await admin_session.close()


@pytest.mark.asyncio
async def test_cross_server_cleanup_closes_admin_when_drop_fails(monkeypatch):
    database_name = "novel_creator_test_0123456789abcdef0123456789abcdef"
    drop_error = RuntimeError("drop failed")

    class AdminSession:
        def __init__(self):
            self.calls = []
            self.closed = False

        async def execute(self, sql):
            self.calls.append(sql)
            raise drop_error

        async def close(self):
            self.closed = True

    admin_session = AdminSession()

    async def open_admin_session(config):
        return admin_session

    async def fail_bootstrap(*args, **kwargs):
        raise RuntimeError("bootstrap failed")

    module = "backend.tests.integration.test_bootstrap_writer_core_product"
    monkeypatch.setattr(f"{module}._mysql_server_config", lambda: {})
    monkeypatch.setattr(f"{module}.new_database_name", lambda: database_name)
    monkeypatch.setattr(f"{module}._open_admin_session", open_admin_session)
    monkeypatch.setattr(f"{module}.bootstrap_writer_core_product", fail_bootstrap)

    with pytest.raises(RuntimeError) as raised:
        await test_cross_server_bootstrap_builds_verified_disposable_target()

    assert raised.value is drop_error
    assert admin_session.calls == [f"DROP DATABASE IF EXISTS `{database_name}`"]
    assert admin_session.closed is True
