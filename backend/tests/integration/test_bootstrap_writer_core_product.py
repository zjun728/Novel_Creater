import json

import aiomysql
import pytest

from backend.scripts.bootstrap_writer_core_product import (
    LegacyInventory,
    bootstrap_writer_core_product,
)
from backend.scripts.reset_writer_core_data import (
    _LEGACY_PROJECT_COLUMNS,
    _LEGACY_PROVIDER_COLUMNS,
    _LEGACY_SEED_COLUMNS,
)
from backend.tests.support.disposable_mysql import (
    _close_raw_connection,
    _open_admin_session,
    assert_disposable_name,
    new_database_name,
    test_server_config,
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
    config = test_server_config()
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
        )
        database_connection = await aiomysql.connect(**{**config, "db": database_name})
        cursor = await database_connection.cursor(aiomysql.DictCursor)
        try:
            expected = {
                "projects": 1,
                "creative_seeds": 3,
                "provider_profiles": 2,
                "project_selected_seeds": 1,
                "task_model_bindings": 1,
                "task_model_binding_items": 8,
                "canon_revisions": 1,
                "projection_heads": 1,
            }
            for table, count in expected.items():
                await cursor.execute(f"SELECT COUNT(*) AS count FROM `{table}`")
                assert (await cursor.fetchone())["count"] == count
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
        if database_connection is not None:
            await _close_raw_connection(database_connection)
        assert_disposable_name(database_name)
        await admin_session.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
        await admin_session.close()
