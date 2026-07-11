import json

import aiomysql
import pytest

from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.reset_writer_core_data import (
    RESET_LOCK_NAME,
    ResetRequest,
    ResetValidationError,
    reset_writer_core_data,
)
from backend.services.projects import TASK_KEYS
from backend.services.projections import build_projection_bundle


PROJECT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_PROJECT_ID = "99999999-9999-9999-9999-999999999999"
SEEDS = (
    ("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "永乐长明", "candidate"),
    ("cccccccc-cccc-cccc-cccc-cccccccccccc", "文渊山海", "candidate"),
    ("dddddddd-dddd-dddd-dddd-dddddddddddd", "典镇山河", "selected"),
)
PROVIDER_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
OTHER_PROVIDER_ID = "88888888-8888-8888-8888-888888888888"
SENTINELS = (
    "API_KEY_SENTINEL",
    "BASE_URL_SENTINEL",
    "DESCRIPTION_CHAPTER_SENTINEL",
    "PROVIDER_NOTES_SENTINEL",
    "PASSWORD_SENTINEL",
    "DSN_SENTINEL",
)
LEGACY_DERIVED_TABLES = (
    "task_model_bindings",
    "chapters",
    "chapter_versions",
    "possibility_cards",
    "creative_bible",
    "sample_source",
    "sample_chunk",
    "experience_card",
    "writing_standard_candidate",
    "writing_standard",
    "characters",
    "plot_threads",
    "rolling_outlines",
    "project_volumes",
    "project_audit_reports",
    "correction_tasks",
    "canon_facts",
    "temp_drafts",
    "chapter_beat_plans",
    "story_blocks",
    "story_block_reviews",
    "market_items",
    "market_chat_messages",
    "market_direction_reports",
    "setting_entities",
    "setting_relations",
    "setting_change_events",
    "finalization_markers",
    "project_health_checks",
)


class RecordingAdminProxy:
    def __init__(self, delegate):
        self.delegate = delegate
        self.calls = []

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        return await self.delegate.fetchone(sql, args)

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", " ".join(sql.split()), args))
        return await self.delegate.fetchall(sql, args)

    async def execute(self, sql, args=None):
        self.calls.append(("execute", " ".join(sql.split()), args))
        return await self.delegate.execute(sql, args)


async def create_legacy_tables(session):
    await session.execute(
        """CREATE TABLE projects (
             id CHAR(36), title VARCHAR(200), genre VARCHAR(120), description TEXT,
             target_words INT, target_chapters INT, status VARCHAR(24),
             current_chapter INT, created_at BIGINT, updated_at BIGINT
           ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    await session.execute(
        """CREATE TABLE creative_seeds (
             id CHAR(36), project_id CHAR(36), title VARCHAR(200), premise_json JSON,
             content_hash CHAR(64), status VARCHAR(24), created_at BIGINT
           ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    await session.execute(
        """CREATE TABLE provider_profiles (
             id CHAR(36), name VARCHAR(120), provider_type VARCHAR(64),
             model_name VARCHAR(160), base_url VARCHAR(2048), api_key TEXT,
             enabled TINYINT, sort_order INT, stream TINYINT,
             max_context_tokens INT, max_output_tokens INT,
             temperature DECIMAL(5,3), top_p DECIMAL(5,3),
             supports_json TINYINT, supports_streaming TINYINT, notes TEXT,
             thinking JSON, created_at BIGINT, updated_at BIGINT
           ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
    )
    for table in LEGACY_DERIVED_TABLES:
        await session.execute(
            f"CREATE TABLE `{table}` (id INT PRIMARY KEY, payload LONGTEXT) ENGINE=InnoDB"
        )
        await session.execute(
            f"INSERT INTO `{table}` (id, payload) VALUES (1, %s)",
            (f"{table}-{SENTINELS[2]}-{SENTINELS[4]}-{SENTINELS[5]}",),
        )

    await session.execute(
        """INSERT INTO projects VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            PROJECT_ID, "永乐大典", "历史", SENTINELS[2], 1_000_000, 500,
            "active", 17, 100, 200,
        ),
    )
    await session.execute(
        """INSERT INTO projects VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            OTHER_PROJECT_ID, "无关项目", "其他", "must be removed", 10_000, 10,
            "drafting", 0, 50, 60,
        ),
    )
    for seed_id, title, status in SEEDS:
        await session.execute(
            "INSERT INTO creative_seeds VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (seed_id, PROJECT_ID, title, json.dumps({"title": title}), "1" * 64, status, 100),
        )
    await session.execute(
        "INSERT INTO creative_seeds VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            "77777777-7777-7777-7777-777777777777", OTHER_PROJECT_ID,
            "无关种子", "{}", "2" * 64, "candidate", 50,
        ),
    )
    await session.execute(
        """INSERT INTO provider_profiles VALUES
           (%s,%s,%s,%s,%s,%s,1,0,1,128000,8192,0.700,0.950,1,1,%s,NULL,100,200)""",
        (
            PROVIDER_ID, "联通云", "openai-compatible", "deepseek-v4-flash",
            SENTINELS[1], SENTINELS[0], SENTINELS[3],
        ),
    )
    await session.execute(
        """INSERT INTO provider_profiles VALUES
           (%s,%s,%s,%s,%s,%s,1,5,0,64000,4096,0.500,0.900,0,0,%s,%s,90,190)""",
        (
            OTHER_PROVIDER_ID, "备用云", "openai-compatible", "backup-model",
            "https://DSN_SENTINEL.invalid", "PASSWORD_SENTINEL",
            "PROVIDER_NOTES_SENTINEL-2", json.dumps({"budget": 3}),
        ),
    )


def request():
    return ResetRequest(
        project_title="永乐大典",
        seed_titles=("永乐长明", "文渊山海", "典镇山河"),
        preferred_provider_name="联通云",
        preferred_model="deepseek-v4-flash",
    )


@pytest.mark.mysql
async def test_dry_run_is_read_only_and_redacts_preserved_secrets(empty_disposable_mysql, capsys, caplog):
    await create_legacy_tables(empty_disposable_mysql.session)

    report = await reset_writer_core_data(
        empty_disposable_mysql.admin_session,
        database_name=empty_disposable_mysql.database_name,
        confirm_reset=empty_disposable_mysql.database_name,
        request=request(),
        execute=False,
        allow_product_database=False,
        output=print,
    )

    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert report.executed is False
    assert report.project_id == PROJECT_ID
    assert report.seed_count == 3
    assert report.provider_count == 2
    assert set(report.table_names) == set(created_table_names())
    assert "永乐大典" in rendered
    assert "典镇山河" in rendered
    assert "联通云" in rendered
    assert "deepseek-v4-flash" in rendered
    assert all(value not in rendered for value in SENTINELS)
    assert all(value not in caplog.text for value in SENTINELS)
    for table in LEGACY_DERIVED_TABLES:
        count = await empty_disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM `{table}`"
        )
        assert count == {"count": 1}


@pytest.mark.mysql
async def test_execute_preserves_only_foundation_and_rebuilds_empty_writer_core(empty_disposable_mysql, capsys, caplog):
    await create_legacy_tables(empty_disposable_mysql.session)
    old_project = await empty_disposable_mysql.session.fetchone(
        "SELECT * FROM projects WHERE id=%s", (PROJECT_ID,)
    )
    old_seeds = await empty_disposable_mysql.session.fetchall(
        "SELECT * FROM creative_seeds WHERE project_id=%s ORDER BY id", (PROJECT_ID,)
    )
    old_providers = await empty_disposable_mysql.session.fetchall(
        "SELECT * FROM provider_profiles ORDER BY id"
    )
    recording_admin = RecordingAdminProxy(empty_disposable_mysql.admin_session)

    report = await reset_writer_core_data(
        recording_admin,
        database_name=empty_disposable_mysql.database_name,
        confirm_reset=empty_disposable_mysql.database_name,
        request=request(),
        execute=True,
        allow_product_database=False,
        output=print,
        now_ms=lambda: 1_720_000_000_000,
    )

    captured = capsys.readouterr()
    assert all(value not in captured.out + captured.err for value in SENTINELS)
    assert all(value not in caplog.text for value in SENTINELS)
    connection = await aiomysql.connect(**empty_disposable_mysql.connection_config)
    cursor = await connection.cursor(aiomysql.DictCursor)
    try:
        await cursor.execute("SELECT * FROM projects ORDER BY id")
        projects = await cursor.fetchall()
        await cursor.execute("SELECT * FROM creative_seeds ORDER BY id")
        seeds = await cursor.fetchall()
        await cursor.execute("SELECT * FROM provider_profiles ORDER BY id")
        providers = await cursor.fetchall()
        await cursor.execute("SELECT seed_id FROM project_selected_seeds WHERE project_id=%s", (PROJECT_ID,))
        selected = await cursor.fetchone()
        await cursor.execute("SELECT task_key, provider_id, model_name FROM task_model_binding_items ORDER BY task_key")
        bindings = await cursor.fetchall()
        await cursor.execute("SELECT revision_number, content_hash FROM canon_revisions")
        revision = await cursor.fetchone()
        await cursor.execute("SELECT canon_revision_number, projection_revision_number, content_hash FROM projection_heads")
        head = await cursor.fetchone()
        await cursor.execute("SELECT schema_version, manifest_hash FROM schema_metadata")
        metadata = await cursor.fetchone()
        await cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (empty_disposable_mysql.database_name,))
        tables = {row["TABLE_NAME"] for row in await cursor.fetchall()}
        await cursor.execute(
            """SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME
               FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s""",
            (empty_disposable_mysql.database_name,),
        )
        database_charset = await cursor.fetchone()
        await cursor.execute(
            """SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES
               WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME""",
            (empty_disposable_mysql.database_name,),
        )
        table_storage = await cursor.fetchall()
        table_counts = {}
        for table in created_table_names():
            await cursor.execute(f"SELECT COUNT(*) AS count FROM {table}")
            table_counts[table] = (await cursor.fetchone())["count"]
    finally:
        await cursor.close()
        connection.close()

    empty_hash = build_projection_bundle(0, ()).content_hash
    assert report.executed is True
    assert projects == [old_project]
    assert seeds == old_seeds
    assert providers == old_providers
    assert selected == {"seed_id": SEEDS[2][0]}
    assert {row["task_key"] for row in bindings} == set(TASK_KEYS)
    assert {row["provider_id"] for row in bindings} == {PROVIDER_ID}
    assert {row["model_name"] for row in bindings} == {"deepseek-v4-flash"}
    assert revision == {"revision_number": 0, "content_hash": empty_hash}
    assert head == {
        "canon_revision_number": 0,
        "projection_revision_number": 0,
        "content_hash": empty_hash,
    }
    assert metadata == {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "manifest_hash": manifest_hash(),
    }
    assert tables == set(created_table_names())
    assert database_charset == {
        "DEFAULT_CHARACTER_SET_NAME": "utf8mb4",
        "DEFAULT_COLLATION_NAME": "utf8mb4_0900_ai_ci",
    }
    assert {row["ENGINE"] for row in table_storage} == {"InnoDB"}
    assert all(row["TABLE_COLLATION"].startswith("utf8mb4_") for row in table_storage)
    assert set(table_counts) == set(created_table_names())
    assert table_counts == {
        table: (
            1 if table in {
                "schema_metadata", "projects", "project_selected_seeds",
                "task_model_bindings", "canon_revisions", "projection_heads",
            }
            else 3 if table == "creative_seeds"
            else 2 if table == "provider_profiles"
            else len(TASK_KEYS) if table == "task_model_binding_items"
            else 0
        )
        for table in created_table_names()
    }
    assert set(report.verified_empty_tables) == {
        table for table, count in table_counts.items() if count == 0
    }
    assert not (set(LEGACY_DERIVED_TABLES) - set(created_table_names())) & tables

    calls = recording_admin.calls
    lock_index = next(i for i, (_, sql, _) in enumerate(calls) if "GET_LOCK" in sql)
    drop_index = next(i for i, (_, sql, _) in enumerate(calls) if sql.startswith("DROP DATABASE"))
    create_database_index = next(i for i, (_, sql, _) in enumerate(calls) if sql.startswith("CREATE DATABASE"))
    use_index = next(i for i, (_, sql, _) in enumerate(calls) if sql.startswith("USE "))
    first_table_index = next(i for i, (_, sql, _) in enumerate(calls) if sql.startswith("CREATE TABLE"))
    transaction_index = next(i for i, (_, sql, _) in enumerate(calls) if sql == "START TRANSACTION")
    commit_index = next(i for i, (_, sql, _) in enumerate(calls) if sql == "COMMIT")
    release_index = next(i for i, (_, sql, _) in enumerate(calls) if "RELEASE_LOCK" in sql)
    assert lock_index < drop_index < create_database_index < use_index < first_table_index < transaction_index < commit_index < release_index
    before_drop_reads = [sql for kind, sql, _ in calls[lock_index + 1:drop_index] if kind == "fetchall"]
    assert len(before_drop_reads) == 3
    assert {
        next(table for table in ("projects", "creative_seeds", "provider_profiles") if f".`{table}`" in sql)
        for sql in before_drop_reads
    } == {"projects", "creative_seeds", "provider_profiles"}


@pytest.mark.mysql
@pytest.mark.parametrize("shape", ("missing", "duplicate"))
async def test_execute_rejects_missing_or_duplicate_requested_seed_before_drop(empty_disposable_mysql, shape):
    await create_legacy_tables(empty_disposable_mysql.session)
    if shape == "missing":
        await empty_disposable_mysql.session.execute(
            "DELETE FROM creative_seeds WHERE title=%s", ("永乐长明",)
        )
    else:
        await empty_disposable_mysql.session.execute(
            """INSERT INTO creative_seeds
               SELECT %s, project_id, title, premise_json, content_hash, status, created_at
               FROM creative_seeds WHERE title=%s""",
            ("ffffffff-ffff-ffff-ffff-ffffffffffff", "永乐长明"),
        )

    with pytest.raises(ResetValidationError, match="seed title"):
        await reset_writer_core_data(
            empty_disposable_mysql.admin_session,
            database_name=empty_disposable_mysql.database_name,
            confirm_reset=empty_disposable_mysql.database_name,
            request=request(),
            execute=True,
            allow_product_database=False,
        )

    for table in LEGACY_DERIVED_TABLES:
        count = await empty_disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM `{table}`"
        )
        assert count == {"count": 1}
    lock = await empty_disposable_mysql.session.fetchone(
        "SELECT IS_FREE_LOCK(%s) AS is_free", (RESET_LOCK_NAME,)
    )
    assert lock == {"is_free": 1}


@pytest.mark.mysql
async def test_execute_rejects_duplicate_requested_project_title_before_drop(empty_disposable_mysql):
    await create_legacy_tables(empty_disposable_mysql.session)
    await empty_disposable_mysql.session.execute(
        "UPDATE projects SET title=%s WHERE id=%s", ("永乐大典", OTHER_PROJECT_ID)
    )

    with pytest.raises(ResetValidationError, match="exactly one project"):
        await reset_writer_core_data(
            empty_disposable_mysql.admin_session,
            database_name=empty_disposable_mysql.database_name,
            confirm_reset=empty_disposable_mysql.database_name,
            request=request(),
            execute=True,
            allow_product_database=False,
        )

    for table in LEGACY_DERIVED_TABLES:
        count = await empty_disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM `{table}`"
        )
        assert count == {"count": 1}
    lock = await empty_disposable_mysql.session.fetchone(
        "SELECT IS_FREE_LOCK(%s) AS is_free", (RESET_LOCK_NAME,)
    )
    assert lock == {"is_free": 1}


@pytest.mark.mysql
@pytest.mark.parametrize("shape", ("absent", "disabled", "duplicate"))
async def test_execute_requires_exactly_one_enabled_preferred_provider(empty_disposable_mysql, shape):
    await create_legacy_tables(empty_disposable_mysql.session)
    if shape == "absent":
        await empty_disposable_mysql.session.execute(
            "DELETE FROM provider_profiles WHERE id=%s", (PROVIDER_ID,)
        )
    elif shape == "disabled":
        await empty_disposable_mysql.session.execute(
            "UPDATE provider_profiles SET enabled=0 WHERE id=%s", (PROVIDER_ID,)
        )
    else:
        await empty_disposable_mysql.session.execute(
            """INSERT INTO provider_profiles
               SELECT %s, name, provider_type, model_name, base_url, api_key,
                      enabled, sort_order, stream, max_context_tokens,
                      max_output_tokens, temperature, top_p, supports_json,
                      supports_streaming, notes, thinking, created_at, updated_at
               FROM provider_profiles WHERE id=%s""",
            ("ffffffff-ffff-ffff-ffff-ffffffffffff", PROVIDER_ID),
        )

    with pytest.raises(ResetValidationError, match="exactly one enabled"):
        await reset_writer_core_data(
            empty_disposable_mysql.admin_session,
            database_name=empty_disposable_mysql.database_name,
            confirm_reset=empty_disposable_mysql.database_name,
            request=request(),
            execute=True,
            allow_product_database=False,
        )

    for table in LEGACY_DERIVED_TABLES:
        count = await empty_disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM `{table}`"
        )
        assert count == {"count": 1}
    lock = await empty_disposable_mysql.session.fetchone(
        "SELECT IS_FREE_LOCK(%s) AS is_free", (RESET_LOCK_NAME,)
    )
    assert lock == {"is_free": 1}
