from decimal import Decimal
import json

import aiomysql
import pytest

from backend.schema_manifest import created_table_names, manifest_hash
from backend.schema_version import EXPECTED_SCHEMA_VERSION
from backend.scripts.reset_writer_core_data import (
    RESET_LOCK_NAME,
    ResetPartialStateError,
    ResetRequest,
    ResetValidationError,
    reset_writer_core_data,
)
from backend.domain.json_contracts import canonical_hash
from backend.domain.model_bindings import BindingItem, BindingRevision, TASK_KEYS
from backend.domain.seeds import SeedPayload
from backend.services.projections import build_projection_bundle
from backend.tests.support.legacy_writer_core import (
    LEGACY_DERIVED_TABLES,
    OTHER_PROJECT_ID,
    PROJECT_ID,
    PROVIDER_ID,
    SEEDS,
    SENTINELS,
    create_legacy_writer_core,
)
from backend.tests.support.disposable_mysql import _open_admin_session


pytestmark = pytest.mark.filterwarnings(
    "ignore:Integer display width is deprecated and will be removed in a future release"
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


class CommitFailingAdminProxy(RecordingAdminProxy):
    def __init__(self, delegate):
        super().__init__(delegate)
        self.closed = False

    async def execute(self, sql, args=None):
        normalized = " ".join(sql.split())
        self.calls.append(("execute", normalized, args))
        if normalized == "COMMIT":
            raise RuntimeError("injected COMMIT failure")
        return await self.delegate.execute(sql, args)

    async def close(self):
        self.calls.append(("close", "CLOSE", None))
        self.closed = True
        await self.delegate.close()


def request():
    return ResetRequest(
        project_title="永乐大典",
        seed_titles=("永乐长明", "文渊山海", "典镇山河"),
        preferred_provider_name="联通云",
        preferred_model="deepseek-v4-flash",
    )


async def legacy_snapshot(session):
    return {
        "projects": await session.fetchall("SELECT * FROM projects ORDER BY id"),
        "creative_seeds": await session.fetchall("SELECT * FROM creative_seeds ORDER BY id"),
        "provider_profiles": await session.fetchall("SELECT * FROM provider_profiles ORDER BY id"),
        "derived": {
            table: await session.fetchall(f"SELECT * FROM `{table}` ORDER BY id")
            for table in LEGACY_DERIVED_TABLES
        },
    }


@pytest.mark.mysql
async def test_dry_run_is_read_only_and_redacts_preserved_secrets(empty_disposable_mysql, capsys, caplog):
    await create_legacy_writer_core(empty_disposable_mysql.session)

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
    await create_legacy_writer_core(empty_disposable_mysql.session)
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
        await cursor.execute("SELECT * FROM project_selected_seeds WHERE project_id=%s", (PROJECT_ID,))
        selected = await cursor.fetchone()
        await cursor.execute("SELECT * FROM creative_seed_revisions ORDER BY seed_id")
        seed_revisions = await cursor.fetchall()
        await cursor.execute("SELECT * FROM creative_seed_heads ORDER BY seed_id")
        seed_heads = await cursor.fetchall()
        await cursor.execute("SELECT * FROM project_model_binding_revisions")
        binding_revision = await cursor.fetchone()
        await cursor.execute("SELECT * FROM project_model_binding_items ORDER BY task_key")
        bindings = await cursor.fetchall()
        await cursor.execute("SELECT * FROM project_model_binding_heads")
        binding_head = await cursor.fetchone()
        await cursor.execute("SELECT * FROM project_contract_heads")
        contract_head = await cursor.fetchone()
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
    assert projects == [{
        "id": old_project["id"],
        "title": old_project["title"],
        "genre": old_project["genre"],
        "description": old_project["description"],
        "target_words": old_project["target_words"],
        "target_chapters": old_project["target_chapters"],
        "status": "drafting",
        "current_chapter": 0,
        "created_at": old_project["created_at"],
        "updated_at": old_project["updated_at"],
    }]
    assert len(seeds) == len(old_seeds) == 3
    for mapped, legacy in zip(seeds, old_seeds, strict=True):
        payload = SeedPayload(**{
            "title": legacy["title"],
            "genre": legacy["genre"],
            "logline": legacy["logline"],
            "protagonist": legacy["protagonist"],
            "desire": legacy["desire"],
            "coreConflict": legacy["core_conflict"],
            "worldPressure": legacy["world_pressure"],
            "openingHook": legacy["opening_hook"],
            "differentiation": legacy["differentiation"],
        })
        assert mapped == {
            "id": legacy["id"],
            "project_id": legacy["project_id"],
            "status": "candidate",
            "created_at": legacy["created_at"],
            "updated_at": legacy["created_at"],
        }
        revision_row = next(row for row in seed_revisions if row["seed_id"] == legacy["id"])
        assert json.loads(revision_row["payload_json"]) == payload.model_dump(mode="json")
        assert revision_row["revision"] == 1
        assert revision_row["content_hash"] == canonical_hash(payload)
        head_row = next(row for row in seed_heads if row["seed_id"] == legacy["id"])
        assert head_row["revision_id"] == revision_row["id"]
        assert head_row["revision"] == 1
        assert head_row["content_hash"] == revision_row["content_hash"]
    assert len(providers) == len(old_providers) == 2
    legacy_by_id = {row["id"]: row for row in old_providers}
    for mapped in providers:
        legacy = legacy_by_id[mapped["id"]]
        assert mapped == {
            "id": legacy["id"],
            "name": legacy["name"],
            "provider_type": legacy["provider_type"],
            "model_name": legacy["model"],
            "base_url": legacy["base_url"],
            "api_key": legacy["api_key"],
            "enabled": 1,
            "sort_order": 0 if legacy["id"] == PROVIDER_ID else 10,
            "stream": legacy["stream"],
            "max_context_tokens": legacy["max_context_tokens"],
            "max_output_tokens": legacy["max_output_tokens"],
            "temperature": Decimal(str(legacy["temperature"])).quantize(Decimal("0.001")),
            "top_p": Decimal(str(legacy["top_p"])).quantize(Decimal("0.001")),
            "supports_json": legacy["supports_json"],
            "supports_streaming": legacy["supports_streaming"],
            "notes": legacy["notes"] or "",
            "thinking": legacy["thinking"],
            "lifecycle_status": "active",
            "deleted_at": None,
            "created_at": legacy["created_at"],
            "updated_at": legacy["updated_at"],
        }
    selected_revision = next(row for row in seed_revisions if row["seed_id"] == SEEDS[2][0])
    assert selected["seed_id"] == SEEDS[2][0]
    assert selected["seed_revision_id"] == selected_revision["id"]
    assert selected["seed_hash"] == selected_revision["content_hash"]
    assert selected["selection_revision"] == 1
    assert {row["task_key"] for row in bindings} == set(TASK_KEYS)
    assert {row["provider_id"] for row in bindings} == {PROVIDER_ID}
    assert {row["provider_name_snapshot"] for row in bindings} == {"联通云"}
    assert {row["model_name_snapshot"] for row in bindings} == {"deepseek-v4-flash"}
    domain_binding = BindingRevision(
        project_id=PROJECT_ID,
        revision=1,
        items=tuple(BindingItem(
            task_key=task_key,
            resolution_status="bound",
            provider_id=PROVIDER_ID,
            provider_name_snapshot="联通云",
            model_name_snapshot="deepseek-v4-flash",
        ) for task_key in TASK_KEYS),
    )
    assert binding_revision["content_hash"] == canonical_hash(domain_binding)
    assert binding_revision["source_project_id"] is None
    assert all(row["binding_revision_id"] == binding_revision["id"] for row in bindings)
    for row in bindings:
        item = next(item for item in domain_binding.items if item.task_key == row["task_key"])
        assert row["item_hash"] == canonical_hash(item)
    assert binding_head["binding_revision_id"] == binding_revision["id"]
    assert binding_head["revision"] == 1
    assert binding_head["content_hash"] == binding_revision["content_hash"]
    assert contract_head["revision"] == 0
    assert contract_head["project_id"] == PROJECT_ID
    assert all(contract_head[key] is None for key in (
        "creation_contract_id", "style_contract_id", "creation_hash", "style_hash"
    ))
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
                "project_model_binding_revisions", "project_model_binding_heads",
                "canon_revisions", "projection_heads", "project_contract_heads",
            }
            else 3 if table in {"creative_seeds", "creative_seed_revisions", "creative_seed_heads"}
            else 2 if table == "provider_profiles"
            else len(TASK_KEYS) if table == "project_model_binding_items"
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
    capability_sql = " ".join(sql for _, sql, _ in calls[lock_index + 1:drop_index])
    for required in ("VERSION()", "information_schema.COLLATIONS", "JSON_VALID", "information_schema.CHECK_CONSTRAINTS"):
        assert required in capability_sql


@pytest.mark.mysql
@pytest.mark.parametrize("shape", ("missing", "duplicate"))
async def test_execute_rejects_missing_or_duplicate_requested_seed_before_drop(empty_disposable_mysql, shape):
    await create_legacy_writer_core(empty_disposable_mysql.session)
    if shape == "missing":
        await empty_disposable_mysql.session.execute(
            "DELETE FROM creative_seeds WHERE title=%s", ("永乐长明",)
        )
    else:
        await empty_disposable_mysql.session.execute(
            """INSERT INTO creative_seeds
               SELECT %s, project_id, title, genre, logline, protagonist, desire,
                      core_conflict, world_pressure, opening_hook, emotional_promise,
                      differentiation, style_target, source, risk_notes, ending_anchor,
                      status, created_at
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
    await create_legacy_writer_core(empty_disposable_mysql.session)
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
@pytest.mark.parametrize("shape", ("absent", "duplicate"))
async def test_execute_requires_exactly_one_preferred_legacy_provider(empty_disposable_mysql, shape):
    await create_legacy_writer_core(empty_disposable_mysql.session)
    if shape == "absent":
        await empty_disposable_mysql.session.execute(
            "DELETE FROM provider_profiles WHERE id=%s", (PROVIDER_ID,)
        )
    else:
        await empty_disposable_mysql.session.execute(
            """INSERT INTO provider_profiles
               SELECT %s, name, provider_type, base_url, api_key, model, stream,
                      max_context_tokens, max_output_tokens, temperature, top_p,
                      supports_json, supports_streaming, notes, thinking,
                      created_at, updated_at
               FROM provider_profiles WHERE id=%s""",
            ("ffffffff-ffff-ffff-ffff-ffffffffffff", PROVIDER_ID),
        )

    with pytest.raises(ResetValidationError, match="exactly one preferred legacy"):
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
@pytest.mark.parametrize(
    ("mutation_sql", "args", "message"),
    (
        ("UPDATE projects SET target_words=0 WHERE id=%s", (PROJECT_ID,), "minimum"),
        ("UPDATE provider_profiles SET name=%s WHERE id=%s", ("x" * 121, "88888888-8888-8888-8888-888888888888"), "length"),
        ("UPDATE provider_profiles SET model=%s WHERE id=%s", ("x" * 161, "88888888-8888-8888-8888-888888888888"), "length"),
        (
            """INSERT INTO provider_profiles
               SELECT %s, %s, provider_type, base_url, api_key, model, stream,
                      max_context_tokens, max_output_tokens, temperature, top_p,
                      supports_json, supports_streaming, notes, thinking,
                      created_at, updated_at
               FROM provider_profiles WHERE id=%s""",
            (
                "55555555-5555-5555-5555-555555555555", "联通云",
                "88888888-8888-8888-8888-888888888888",
            ),
            "target collation",
        ),
        ("UPDATE provider_profiles SET max_context_tokens=0 WHERE id=%s", ("88888888-8888-8888-8888-888888888888",), "minimum"),
        ("UPDATE provider_profiles SET stream=2 WHERE id=%s", ("88888888-8888-8888-8888-888888888888",), "0 or 1"),
        ("UPDATE provider_profiles SET temperature=100 WHERE id=%s", ("88888888-8888-8888-8888-888888888888",), "DECIMAL"),
    ),
)
async def test_incompatible_legacy_mapping_is_rejected_before_any_ddl(
    empty_disposable_mysql, mutation_sql, args, message,
):
    await create_legacy_writer_core(empty_disposable_mysql.session)
    await empty_disposable_mysql.session.execute(mutation_sql, args)
    before = await legacy_snapshot(empty_disposable_mysql.session)
    recording_admin = RecordingAdminProxy(empty_disposable_mysql.admin_session)

    with pytest.raises(ResetValidationError, match=message):
        await reset_writer_core_data(
            recording_admin,
            database_name=empty_disposable_mysql.database_name,
            confirm_reset=empty_disposable_mysql.database_name,
            request=request(),
            execute=True,
            allow_product_database=False,
        )

    assert not any(sql.startswith(("DROP DATABASE", "CREATE DATABASE")) for _, sql, _ in recording_admin.calls)
    if message == "target collation":
        assert any("collation_conflict" in sql for _, sql, _ in recording_admin.calls)
    assert await legacy_snapshot(empty_disposable_mysql.session) == before
    lock = await empty_disposable_mysql.session.fetchone(
        "SELECT IS_FREE_LOCK(%s) AS is_free", (RESET_LOCK_NAME,)
    )
    assert lock == {"is_free": 1}


@pytest.mark.mysql
async def test_active_provider_rejects_missing_sensitive_connection_fields_before_ddl(
    empty_disposable_mysql,
):
    await create_legacy_writer_core(empty_disposable_mysql.session)
    await empty_disposable_mysql.session.execute(
        """UPDATE provider_profiles
           SET base_url=NULL, api_key=NULL, stream=NULL,
               max_context_tokens=NULL, max_output_tokens=NULL,
               temperature=NULL, top_p=NULL, supports_json=NULL,
               supports_streaming=NULL, notes=NULL, thinking=NULL
           WHERE id=%s""",
        ("88888888-8888-8888-8888-888888888888",),
    )
    recording_admin = RecordingAdminProxy(empty_disposable_mysql.admin_session)

    with pytest.raises(ResetValidationError, match="active Provider"):
        await reset_writer_core_data(
            recording_admin,
            database_name=empty_disposable_mysql.database_name,
            confirm_reset=empty_disposable_mysql.database_name,
            request=request(), execute=True, allow_product_database=False,
            output=lambda value: None,
        )

    assert not any(
        sql.startswith(("DROP DATABASE", "CREATE DATABASE"))
        for _, sql, _ in recording_admin.calls
    )


@pytest.mark.mysql
@pytest.mark.parametrize("legacy_status", ("candidate", "selected"))
async def test_legacy_seed_status_is_ignored_and_exactly_named_seed_is_selected(
    empty_disposable_mysql, legacy_status,
):
    await create_legacy_writer_core(empty_disposable_mysql.session)
    await empty_disposable_mysql.session.execute(
        "UPDATE creative_seeds SET status=%s WHERE project_id=%s",
        (legacy_status, PROJECT_ID),
    )

    await reset_writer_core_data(
        empty_disposable_mysql.admin_session,
        database_name=empty_disposable_mysql.database_name,
        confirm_reset=empty_disposable_mysql.database_name,
        request=request(), execute=True, allow_product_database=False,
        output=lambda value: None,
    )
    connection = await aiomysql.connect(**empty_disposable_mysql.connection_config)
    cursor = await connection.cursor(aiomysql.DictCursor)
    try:
        await cursor.execute("SELECT id, status FROM creative_seeds ORDER BY id")
        identities = await cursor.fetchall()
        await cursor.execute(
            "SELECT seed_id, seed_revision_id, seed_hash, selection_revision "
            "FROM project_selected_seeds WHERE project_id=%s",
            (PROJECT_ID,),
        )
        selected = await cursor.fetchone()
        await cursor.execute(
            "SELECT id, content_hash FROM creative_seed_revisions WHERE seed_id=%s",
            (SEEDS[2][0],),
        )
        selected_revision = await cursor.fetchone()
    finally:
        await cursor.close()
        connection.close()
    assert {row["status"] for row in identities} == {"candidate"}
    assert selected == {
        "seed_id": SEEDS[2][0],
        "seed_revision_id": selected_revision["id"],
        "seed_hash": selected_revision["content_hash"],
        "selection_revision": 1,
    }


@pytest.mark.mysql
async def test_commit_failure_rolls_back_closes_session_and_releases_lock_by_disconnect(
    empty_disposable_mysql,
):
    await create_legacy_writer_core(empty_disposable_mysql.session)
    admin_config = {
        key: value for key, value in empty_disposable_mysql.connection_config.items()
        if key != "db"
    }
    reset_admin = await _open_admin_session(admin_config)
    failing_admin = CommitFailingAdminProxy(reset_admin)

    with pytest.raises(ResetPartialStateError, match="partially reset") as raised:
        await reset_writer_core_data(
            failing_admin,
            database_name=empty_disposable_mysql.database_name,
            confirm_reset=empty_disposable_mysql.database_name,
            request=request(), execute=True, allow_product_database=False,
            output=lambda value: None,
        )

    assert "injected COMMIT failure" in str(raised.value.__cause__)
    assert failing_admin.closed
    sql_calls = [sql for _, sql, _ in failing_admin.calls]
    assert "COMMIT" in sql_calls
    assert "ROLLBACK" in sql_calls
    assert any("RELEASE_LOCK" in sql for sql in sql_calls)
    assert sql_calls.index("ROLLBACK") < next(
        index for index, sql in enumerate(sql_calls) if "RELEASE_LOCK" in sql
    ) < sql_calls.index("CLOSE")
    lock = await empty_disposable_mysql.admin_session.fetchone(
        "SELECT IS_FREE_LOCK(%s) AS is_free", (RESET_LOCK_NAME,)
    )
    assert lock == {"is_free": 1}

    connection = await aiomysql.connect(**empty_disposable_mysql.connection_config)
    cursor = await connection.cursor(aiomysql.DictCursor)
    try:
        await cursor.execute("SELECT COUNT(*) AS count FROM projects")
        assert await cursor.fetchone() == {"count": 0}
        await cursor.execute("SELECT COUNT(*) AS count FROM schema_metadata")
        assert await cursor.fetchone() == {"count": 1}
    finally:
        await cursor.close()
        connection.close()
