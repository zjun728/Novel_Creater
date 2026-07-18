from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.domain.assets import AssetInventory, AssetProvenance, load_asset_package
from backend.domain.json_contracts import canonical_hash
from backend.repositories.assets import AssetRepository
from backend.scripts.seed_writer_assets import AssetSeedCommandError, run_cli
from backend.http_errors import (
    AssetCatalogNotReady,
    AssetNotFound,
    AssetRecommendationConflict,
)
from backend.services.assets import AssetReadService, AssetSeedConflict, AssetSeedService


MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "writer-core-v1.1.0"
    / "manifest.json"
)


@pytest.fixture
def package():
    return load_asset_package(MANIFEST, mode="release")


class MemoryAssetRepository:
    def __init__(self):
        self.revisions = {"style": {}, "card": {}}
        self.heads = {"style": {}, "card": {}}
        self.events: list[str] = []
        self.fail_on: tuple[str, str] | None = None

    async def lock_schema_guard(self, session):
        self.events.append("lock:schema_metadata:1")

    async def list_heads(self, session, asset_type, *, for_update):
        self.events.append(
            f"heads:{asset_type}:{'lock' if for_update else 'read'}"
        )
        return [
            deepcopy(self.heads[asset_type][key])
            for key in sorted(self.heads[asset_type])
        ]

    async def fetch_revision(self, session, asset_type, stable_key, revision):
        self.events.append(f"revision:{asset_type}:{stable_key}:{revision}")
        row = self.revisions[asset_type].get((stable_key, revision))
        return deepcopy(row) if row is not None else None

    async def list_revisions_for_key(
        self, session, asset_type, stable_key, *, for_update
    ):
        self.events.append(
            f"history:{asset_type}:{stable_key}:"
            f"{'lock' if for_update else 'read'}"
        )
        return [
            deepcopy(row)
            for (key, _), row in sorted(
                self.revisions[asset_type].items(), key=lambda item: item[0]
            )
            if key == stable_key
        ]

    async def insert_revision(self, session, asset_type, row):
        self.events.append(f"insert:{asset_type}:{row['stable_key']}")
        if self.fail_on == (asset_type, row["stable_key"]):
            raise RuntimeError("injected asset insert failure")
        self.revisions[asset_type][(row["stable_key"], row["revision"])] = deepcopy(row)

    async def archive_revision(self, session, asset_type, revision_id):
        self.events.append(f"archive:{asset_type}:{revision_id}")
        for row in self.revisions[asset_type].values():
            if row["id"] == revision_id and row["status"] == "active":
                row["status"] = "archived"
                return 1
        return 0

    async def insert_head(self, session, asset_type, row):
        self.events.append(f"head-insert:{asset_type}:{row['stable_key']}")
        self.heads[asset_type][row["stable_key"]] = deepcopy(row)

    async def move_head(self, session, asset_type, row, *, expected):
        self.events.append(f"head-move:{asset_type}:{row['stable_key']}")
        current = self.heads[asset_type].get(row["stable_key"])
        if current != expected:
            return 0
        self.heads[asset_type][row["stable_key"]] = deepcopy(row)
        return 1


class MemoryTransactionFactory:
    def __init__(self, repository):
        self.repository = repository

    @asynccontextmanager
    async def __call__(self):
        before = deepcopy((self.repository.revisions, self.repository.heads))
        try:
            yield self.repository
        except BaseException:
            self.repository.revisions, self.repository.heads = before
            raise


def service_for(repository: MemoryAssetRepository) -> AssetSeedService:
    values = iter(f"00000000-0000-0000-0000-{index:012d}" for index in range(1, 500))
    return AssetSeedService(
        repository,
        transaction_factory=MemoryTransactionFactory(repository),
        connection_factory=readonly_connection(repository),
        id_factory=lambda: next(values),
        clock=lambda: 1_720_000_000_000,
    )


def readonly_connection(repository):
    @asynccontextmanager
    async def factory():
        yield repository

    return factory


def replace_style(package, index=0, **updates):
    styles = list(package.styles)
    styles[index] = styles[index].model_copy(update=updates)
    return package.model_copy(update={"styles": tuple(styles)})


def next_style_revision(package, revision: int):
    original = package.styles[0]
    payload = original.payload.model_copy(
        update={"reading_experience": f"revision-{revision}-reading-experience"}
    )
    return replace_style(
        package,
        revision=revision,
        payload=payload,
        content_hash=canonical_hash(payload),
    )


def memory_revision_row(asset_type, asset, *, row_id, status="active"):
    return {
        "id": row_id,
        "stable_key": asset.stable_key,
        "revision": asset.revision,
        "label": asset.name if asset_type == "style" else asset.title,
        "category": None if asset_type == "style" else asset.category,
        "payload_json": json.dumps(
            asset.payload.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "provenance_json": json.dumps(
            asset.provenance.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "content_hash": asset.content_hash,
        "status": status,
        "created_at": 1,
    }


@pytest.mark.asyncio
async def test_first_seed_inserts_all_74_assets_and_same_release_replays_zero_inserts(package):
    repository = MemoryAssetRepository()
    service = service_for(repository)

    first = await service.seed(package)
    replay = await service.seed(package)

    assert (first.inserted, first.replayed, first.advanced) == (74, 0, 0)
    assert (replay.inserted, replay.replayed, replay.advanced) == (0, 74, 0)
    assert len(repository.revisions["style"]) == 10
    assert len(repository.revisions["card"]) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    (
        lambda package: replace_style(package, name="同修订改名"),
        lambda package: replace_style(
            package,
            provenance=AssetProvenance(
                reviewer="另一位审核者",
                review_time="2026-07-12T15:00:00+08:00",
                decision="approved",
            ),
        ),
    ),
)
async def test_same_revision_requires_full_immutable_row_not_payload_hash_only(
    package, changed
):
    repository = MemoryAssetRepository()
    service = service_for(repository)
    await service.seed(package)

    with pytest.raises(AssetSeedConflict, match="immutable revision differs"):
        await service.seed(changed(package))


@pytest.mark.asyncio
async def test_revision_plus_one_appends_archives_and_moves_only_one_head(package):
    repository = MemoryAssetRepository()
    service = service_for(repository)
    await service.seed(package)

    report = await service.seed(next_style_revision(package, 2))

    key = package.styles[0].stable_key
    assert (report.inserted, report.replayed, report.advanced) == (0, 73, 1)
    assert repository.revisions["style"][(key, 1)]["status"] == "archived"
    assert repository.revisions["style"][(key, 2)]["status"] == "active"
    assert repository.heads["style"][key]["revision"] == 2


@pytest.mark.asyncio
async def test_revision_jump_and_backward_both_fail_closed(package):
    repository = MemoryAssetRepository()
    service = service_for(repository)
    await service.seed(package)

    with pytest.raises(AssetSeedConflict, match="next revision"):
        await service.seed(next_style_revision(package, 3))

    await service.seed(next_style_revision(package, 2))
    with pytest.raises(AssetSeedConflict, match="next revision"):
        await service.seed(package)


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["extra", "missing"])
async def test_existing_head_set_must_equal_package_keys(package, damage):
    repository = MemoryAssetRepository()
    service = service_for(repository)
    await service.seed(package)
    if damage == "extra":
        repository.heads["style"]["unknown-style"] = {
            "stable_key": "unknown-style",
            "id": "00000000-0000-0000-0000-999999999999",
            "revision": 1,
            "content_hash": "f" * 64,
        }
    else:
        del repository.heads["card"][package.experience_cards[0].stable_key]

    with pytest.raises(AssetSeedConflict, match="head set"):
        await service.seed(package)


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_type", ["style", "card"])
async def test_only_both_empty_head_types_are_a_first_seed(package, empty_type):
    repository = MemoryAssetRepository()
    service = service_for(repository)
    await service.seed(package)
    repository.heads[empty_type].clear()

    with pytest.raises(AssetSeedConflict, match="head set"):
        await service.seed(package)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    ("orphan_revision_one", "orphan_next_revision", "archived_head_revision"),
)
async def test_dry_run_and_execute_reject_orphans_or_non_active_head_without_changes(
    package, corruption
):
    repository = MemoryAssetRepository()
    service = service_for(repository)
    target_package = package
    if corruption == "orphan_revision_one":
        asset = package.styles[0]
        repository.revisions["style"][(asset.stable_key, 1)] = memory_revision_row(
            "style",
            asset,
            row_id="80000000-0000-0000-0000-000000000001",
        )
    else:
        await service.seed(package)
        target_package = next_style_revision(package, 2)
        asset = target_package.styles[0]
        if corruption == "orphan_next_revision":
            repository.revisions["style"][(asset.stable_key, 2)] = memory_revision_row(
                "style",
                asset,
                row_id="80000000-0000-0000-0000-000000000002",
            )
        else:
            repository.revisions["style"][(asset.stable_key, 1)]["status"] = "archived"
    before = deepcopy((repository.revisions, repository.heads))

    with pytest.raises(AssetSeedConflict):
        await service.dry_run(target_package)
    assert (repository.revisions, repository.heads) == before
    with pytest.raises(AssetSeedConflict):
        await service.seed(target_package)
    assert (repository.revisions, repository.heads) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    ("no_head_orphan_two", "future_three", "gap", "old_active"),
)
async def test_dry_run_and_execute_validate_complete_revision_history(
    package, corruption
):
    repository = MemoryAssetRepository()
    service = service_for(repository)
    if corruption == "no_head_orphan_two":
        target_package = package
        orphan_package = next_style_revision(package, 2)
        orphan = orphan_package.styles[0]
        repository.revisions["style"][(orphan.stable_key, 2)] = memory_revision_row(
            "style", orphan, row_id="81000000-0000-0000-0000-000000000002"
        )
    else:
        await service.seed(package)
        key = package.styles[0].stable_key
        if corruption == "future_three":
            target_package = package
            future = next_style_revision(package, 3).styles[0]
            repository.revisions["style"][(key, 3)] = memory_revision_row(
                "style", future, row_id="81000000-0000-0000-0000-000000000003"
            )
        elif corruption == "gap":
            target_package = next_style_revision(package, 3)
            head_asset = target_package.styles[0]
            row = memory_revision_row(
                "style", head_asset, row_id="81000000-0000-0000-0000-000000000013"
            )
            repository.revisions["style"][(key, 1)]["status"] = "archived"
            repository.revisions["style"][(key, 3)] = row
            repository.heads["style"][key] = {
                "stable_key": key,
                "id": row["id"],
                "revision": 3,
                "content_hash": row["content_hash"],
                "updated_at": 2,
            }
        else:
            target_package = next_style_revision(package, 2)
            await service.seed(target_package)
            repository.revisions["style"][(key, 1)]["status"] = "active"
    before = deepcopy((repository.revisions, repository.heads))

    with pytest.raises(AssetSeedConflict):
        await service.dry_run(target_package)
    assert (repository.revisions, repository.heads) == before
    with pytest.raises(AssetSeedConflict):
        await service.seed(target_package)
    assert (repository.revisions, repository.heads) == before


@pytest.mark.asyncio
async def test_any_failure_rolls_back_the_whole_package(package):
    repository = MemoryAssetRepository()
    repository.fail_on = ("card", sorted(c.stable_key for c in package.experience_cards)[0])

    with pytest.raises(RuntimeError, match="injected asset insert failure"):
        await service_for(repository).seed(package)

    assert repository.revisions == {"style": {}, "card": {}}
    assert repository.heads == {"style": {}, "card": {}}


@pytest.mark.asyncio
async def test_execute_locks_global_guard_then_processes_style_and_card_keys_in_fixed_order(package):
    repository = MemoryAssetRepository()
    await service_for(repository).seed(package)

    actions = [event for event in repository.events if event.startswith("insert:")]
    expected = [
        *(f"insert:style:{key}" for key in sorted(s.stable_key for s in package.styles)),
        *(f"insert:card:{key}" for key in sorted(c.stable_key for c in package.experience_cards)),
    ]
    assert repository.events[0] == "lock:schema_metadata:1"
    assert actions == expected


class RecordingSession:
    def __init__(self):
        self.calls = []

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", " ".join(sql.split()), args))
        return {"singleton_id": 1}

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", " ".join(sql.split()), args))
        return []


@pytest.mark.asyncio
async def test_repository_guard_and_head_queries_have_deterministic_lock_order():
    session = RecordingSession()
    repository = AssetRepository()

    await repository.lock_schema_guard(session)
    await repository.list_heads(session, "style", for_update=True)
    await repository.list_heads(session, "card", for_update=False)

    assert session.calls[0][1] == (
        "SELECT singleton_id FROM schema_metadata WHERE singleton_id=1 FOR UPDATE"
    )
    assert "ORDER BY h.stable_key ASC FOR UPDATE" in session.calls[1][1]
    assert "ORDER BY h.stable_key ASC" in session.calls[2][1]
    assert "FOR UPDATE" not in session.calls[2][1]


@pytest.mark.asyncio
async def test_repository_lists_one_key_history_in_revision_order_with_optional_lock():
    session = RecordingSession()
    repository = AssetRepository()

    await repository.list_revisions_for_key(
        session, "style", "stable-key", for_update=True
    )
    await repository.list_revisions_for_key(
        session, "card", "stable-key", for_update=False
    )

    assert session.calls[0][1] == (
        "SELECT id,stable_key,revision,content_hash,status FROM style_templates "
        "WHERE stable_key=%s ORDER BY revision ASC FOR UPDATE"
    )
    assert session.calls[0][2] == ("stable-key",)
    assert session.calls[1][1] == (
        "SELECT id,stable_key,revision,content_hash,status FROM experience_cards "
        "WHERE stable_key=%s ORDER BY revision ASC"
    )
    assert session.calls[1][2] == ("stable-key",)


@pytest.mark.asyncio
async def test_cli_validate_only_uses_fixed_release_manifest_without_database_import_or_connection(
    monkeypatch,
):
    class ForbiddenDatabaseModule:
        def __getattr__(self, name):
            raise AssertionError(f"validate-only imported database member {name}")

    monkeypatch.setitem(__import__("sys").modules, "backend.database", ForbiddenDatabaseModule())
    output = []

    code = await run_cli(["--validate-only"], output=output.append)

    assert code == 0
    rendered = "\n".join(output)
    assert "package_version=writer-core-v1.1.0" in rendered
    assert "style_count=10" in rendered
    assert "card_count=64" in rendered
    assert "payload" not in rendered
    assert "provenance" not in rendered


@pytest.mark.asyncio
async def test_cli_dry_run_closes_default_database_pool(monkeypatch, package):
    repository = MemoryAssetRepository()
    events = []

    async def close_pool():
        events.append("close")

    database_runtime = type("DatabaseRuntime", (), {})()
    database_runtime.connection = readonly_connection(repository)
    database_runtime.close_pool = close_pool
    monkeypatch.setitem(
        __import__("sys").modules, "backend.database", database_runtime
    )

    code = await run_cli(
        ["--dry-run", "--database", "writer_core_test"],
        repository=repository,
        connection_config={"db": "writer_core_test"},
        output=lambda value: None,
    )

    assert code == 0
    assert events == ["close"]


@pytest.mark.asyncio
async def test_cli_dry_run_closes_default_database_pool_after_service_error(
    monkeypatch, package
):
    repository = MemoryAssetRepository()
    service_error = RuntimeError("injected dry-run failure")
    events = []

    async def fail_list_heads(session, asset_type, *, for_update):
        raise service_error

    async def close_pool():
        events.append("close")

    monkeypatch.setattr(repository, "list_heads", fail_list_heads)
    database_runtime = type("DatabaseRuntime", (), {})()
    database_runtime.connection = readonly_connection(repository)
    database_runtime.close_pool = close_pool
    monkeypatch.setitem(
        __import__("sys").modules, "backend.database", database_runtime
    )

    with pytest.raises(RuntimeError) as raised:
        await run_cli(
            ["--dry-run", "--database", "writer_core_test"],
            repository=repository,
            connection_config={"db": "writer_core_test"},
        )

    assert raised.value is service_error
    assert events == ["close"]


@pytest.mark.asyncio
async def test_cli_preserves_service_and_default_pool_close_failures(monkeypatch):
    repository = MemoryAssetRepository()
    service_error = RuntimeError("service failure")
    close_error = OSError("close failure")

    async def fail_list_heads(session, asset_type, *, for_update):
        raise service_error

    async def close_pool():
        raise close_error

    monkeypatch.setattr(repository, "list_heads", fail_list_heads)
    database_runtime = type("DatabaseRuntime", (), {})()
    database_runtime.connection = readonly_connection(repository)
    database_runtime.close_pool = close_pool
    monkeypatch.setitem(
        __import__("sys").modules, "backend.database", database_runtime
    )

    with pytest.raises(BaseExceptionGroup) as raised:
        await run_cli(
            ["--dry-run", "--database", "writer_core_test"],
            repository=repository,
            connection_config={"db": "writer_core_test"},
        )

    assert raised.value.exceptions == (service_error, close_error)


@pytest.mark.asyncio
async def test_cli_preserves_default_pool_close_failure(monkeypatch):
    repository = MemoryAssetRepository()
    close_error = OSError("close failure")

    async def close_pool():
        raise close_error

    database_runtime = type("DatabaseRuntime", (), {})()
    database_runtime.connection = readonly_connection(repository)
    database_runtime.close_pool = close_pool
    monkeypatch.setitem(
        __import__("sys").modules, "backend.database", database_runtime
    )

    with pytest.raises(OSError) as raised:
        await run_cli(
            ["--dry-run", "--database", "writer_core_test"],
            repository=repository,
            connection_config={"db": "writer_core_test"},
            output=lambda value: None,
        )

    assert raised.value is close_error


@pytest.mark.asyncio
async def test_cli_execute_closes_default_database_pool(monkeypatch, package):
    repository = MemoryAssetRepository()
    events = []

    async def close_pool():
        events.append("close")

    database_runtime = type("DatabaseRuntime", (), {})()
    database_runtime.transaction = MemoryTransactionFactory(repository)
    database_runtime.close_pool = close_pool
    monkeypatch.setitem(
        __import__("sys").modules, "backend.database", database_runtime
    )

    code = await run_cli(
        [
            "--execute",
            "--database",
            "writer_core_test",
            "--confirm-seed",
            "writer_core_test",
        ],
        repository=repository,
        connection_config={"db": "writer_core_test"},
        output=lambda value: None,
    )

    assert code == 0
    assert events == ["close"]


@pytest.mark.asyncio
async def test_cli_execute_closes_default_database_pool_after_service_error(
    monkeypatch, package
):
    repository = MemoryAssetRepository()
    repository.fail_on = ("style", package.styles[0].stable_key)
    events = []

    async def close_pool():
        events.append("close")

    database_runtime = type("DatabaseRuntime", (), {})()
    database_runtime.transaction = MemoryTransactionFactory(repository)
    database_runtime.close_pool = close_pool
    monkeypatch.setitem(
        __import__("sys").modules, "backend.database", database_runtime
    )

    with pytest.raises(RuntimeError, match="injected asset insert failure"):
        await run_cli(
            [
                "--execute",
                "--database",
                "writer_core_test",
                "--confirm-seed",
                "writer_core_test",
            ],
            repository=repository,
            connection_config={"db": "writer_core_test"},
        )

    assert events == ["close"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ("dry-run", "execute"))
async def test_cli_injected_database_factory_does_not_touch_default_pool(
    monkeypatch, mode
):
    class ForbiddenDatabaseModule:
        def __getattr__(self, name):
            raise AssertionError(f"injected {mode} imported database member {name}")

    repository = MemoryAssetRepository()
    monkeypatch.setitem(
        __import__("sys").modules, "backend.database", ForbiddenDatabaseModule()
    )
    if mode == "dry-run":
        argv = ["--dry-run", "--database", "writer_core_test"]
        factories = {"connection_factory": readonly_connection(repository)}
    else:
        argv = [
            "--execute",
            "--database",
            "writer_core_test",
            "--confirm-seed",
            "writer_core_test",
        ]
        factories = {
            "transaction_factory": MemoryTransactionFactory(repository)
        }

    code = await run_cli(
        argv,
        repository=repository,
        connection_config={"db": "writer_core_test"},
        output=lambda value: None,
        **factories,
    )

    assert code == 0


@pytest.mark.asyncio
async def test_cli_dry_run_reads_heads_but_performs_zero_dml(package):
    repository = MemoryAssetRepository()
    await service_for(repository).seed(package)
    repository.events.clear()
    output = []

    code = await run_cli(
        ["--dry-run", "--database", "writer_core_test"],
        repository=repository,
        connection_factory=readonly_connection(repository),
        connection_config={"db": "writer_core_test", "password": "SECRET"},
        output=output.append,
    )

    assert code == 0
    expected = ["heads:style:read", "heads:card:read"]
    for asset_type, keys in (
        ("style", sorted(s.stable_key for s in package.styles)),
        ("card", sorted(c.stable_key for c in package.experience_cards)),
    ):
        for key in keys:
            expected.extend(
                (
                    f"history:{asset_type}:{key}:read",
                    f"revision:{asset_type}:{key}:1",
                )
            )
    assert repository.events == expected
    rendered = "\n".join(output)
    assert "report.inserted=0" in rendered
    assert "report.replayed=74" in rendered
    assert "SECRET" not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "argv",
    (
        ["--execute", "--database", "product", "--confirm-seed", "different"],
        ["--execute", "--database", "other", "--confirm-seed", "other"],
    ),
)
async def test_cli_execute_requires_database_confirmation_and_config_match_before_connection(argv):
    connected = False

    @asynccontextmanager
    async def forbidden_transaction():
        nonlocal connected
        connected = True
        raise AssertionError("must reject before connection")
        yield

    with pytest.raises(AssetSeedCommandError):
        await run_cli(
            argv,
            transaction_factory=forbidden_transaction,
            connection_config={"db": "product", "password": "SECRET"},
        )
    assert connected is False


@pytest.mark.parametrize(
    "argv",
    (
        [],
        ["--validate-only", "--dry-run"],
        ["--password", "SUPER_SECRET_SENTINEL"],
    ),
)
def test_cli_rejects_missing_multiple_or_unknown_modes_without_echoing_input(
    argv, capfd
):
    import asyncio

    with pytest.raises(SystemExit) as raised:
        asyncio.run(run_cli(argv))
    stdout, stderr = capfd.readouterr()
    assert raised.value.code == 2
    assert stdout == ""
    assert stderr == "Writer asset seed arguments are invalid.\n"
    assert "SUPER_SECRET_SENTINEL" not in stderr


# Pure deterministic recommendation contract (M2C Task 3B).
from inspect import signature
import unicodedata

from pydantic import ValidationError

from backend.domain.asset_recommendations import (
    RECOMMENDATION_VERSION,
    AssetRecommendationRef,
    AssetRecommendationResult,
    RecommendationInputError,
    recommend_assets,
    validate_recommendation_inventory,
)
from backend.domain.seeds import SeedPayload


def _seed(**updates):
    values = {
        "title": "典镇山河",
        "genre": "穿越 架空历史 文明建设 群像",
        "logline": "现代典籍修复师穿越乱世，以知识、制度和协作重建一座边城。",
        "protagonist": "谨慎但愿意承担责任的典籍修复师",
        "desire": "让百姓活下来，并把一次胜利变成可持续的秩序与成长",
        "coreConflict": "旧权力阻挠改革，每个建设成果都会带来新的利益冲突与后果",
        "worldPressure": "资源短缺、朝廷猜忌与敌军轮番施压",
        "openingHook": "主角用残卷知识解决水患，却因此被多方盯上",
        "differentiation": "跨章推进文明建设，群像角色各有目标，能力成长来自实践反馈",
    }
    values.update(updates)
    return SeedPayload(**values)


def _engine(**updates):
    values = {
        "name": "残卷筑城",
        "storyPromise": "用知识建设制度，让小人物协作改变乱世",
        "protagonistDesire": "保护边城并建立可持续秩序",
        "sustainedPressure": "资源、权力和战争压力交替升级",
        "growthDirection": "从个人解题成长为能组织群像协作的建设者",
        "conflictLoop": "发现建设问题，组织伙伴试行，承担后果，再跨章修正制度",
        "ensembleRoles": (
            {"role": "工匠", "purpose": "把知识转成可用技术"},
            {"role": "商人", "purpose": "连接资源并提出利益条件"},
        ),
        "advantageAndCost": "现代知识提供突破方向，但验证和推广都消耗资源与信任",
        "satisfactionSources": ("建设成果", "伙伴成长", "群像协作"),
        "longFormVariation": ("水利", "商路", "军备", "制度反噬"),
        "endingAnchor": "众人共同守住自己建立的新秩序",
        "risks": ("建设过程写成说明书", "配角只服务主角"),
        "differentiation": "穿越知识必须经过试错，长期因果和人物选择跨章保留",
    }
    values.update(updates)
    return values


def _recommend(package, seed=None, engine=None, *, seed_hash=None, engine_hash=None):
    seed = seed or _seed()
    engine = engine or _engine()
    return recommend_assets(
        seed,
        engine,
        package,
        seed_hash=seed_hash or canonical_hash(seed),
        engine_hash=engine_hash or canonical_hash(engine),
    )


def test_recommender_returns_fixed_three_styles_and_two_to_four_unique_cards(package):
    result = _recommend(package)

    assert result.recommendation_version == RECOMMENDATION_VERSION
    assert len(result.styles) == len({item.stable_key for item in result.styles}) == 3
    assert 2 <= len(result.experience_cards) <= 4
    assert len(result.experience_cards) == len(
        {item.stable_key for item in result.experience_cards}
    )
    assert tuple(item.stable_key for item in result.styles) == (
        "epic-civilization-building",
        "immersive-ensemble",
        "high-energy-growth",
    )
    assert tuple(item.stable_key for item in result.experience_cards) == (
        "ensemble-help-has-condition",
        "arc-aftermath-new-normal",
        "plot-small-answer-new-pressure",
        "progression-new-tier-new-problem",
    )
    assert tuple(item.reason_codes for item in result.styles) == (
        ("semantic-profile", "seed-context", "engine-context"),
        ("semantic-profile", "seed-context", "engine-context"),
        ("semantic-profile", "seed-context", "engine-context"),
    )
    assert tuple(item.reason_codes for item in result.experience_cards) == (
        ("category-profile", "asset-text-overlap"),
        ("category-profile", "asset-text-overlap"),
        ("category-profile", "asset-text-overlap"),
        ("category-profile", "asset-text-overlap"),
    )
    categories = {
        next(card.category for card in package.experience_cards if card.stable_key == item.stable_key)
        for item in result.experience_cards
    }
    assert {"ensemble", "progression_economy"} <= categories


def _xianxia_seed():
    return SeedPayload(
        title="青冥问道",
        genre="玄幻 仙侠 穿越 求生",
        logline="药童坠入修仙界，靠辨识灵草、谨慎试探和资源积累寻找生路。",
        protagonist="出身卑微、惜命而有耐心的药童",
        desire="活下去并稳健积累修炼资源，最终突破境界",
        coreConflict="宗门争夺灵脉，弱者必须在斗法与交易之间保存自己",
        worldPressure="妖兽、强修和资源枯竭不断压缩安全空间",
        openingHook="他从毒草旁的虫尸判断出唯一安全路线",
        differentiation="每次修炼突破都有准备、验证、消耗和后续风险",
    )


def _xianxia_engine():
    return {
        "name": "草木求生",
        "storyPromise": "凡人以谨慎判断和资源积累踏上修仙路",
        "protagonistDesire": "保存性命并取得可持续的修炼资源",
        "sustainedPressure": "强敌、妖兽与资源消耗轮番逼近",
        "growthDirection": "从辨药自保走向组合旧能力完成境界突破",
        "conflictLoop": "侦察风险，采集灵草，交换丹药，斗法脱身，再修炼突破",
        "ensembleRoles": (
            {"role": "同门药童", "purpose": "交换情报但保留自己的生路"},
        ),
        "advantageAndCost": "识药经验能降低风险，但每次验证都消耗时间与药材",
        "satisfactionSources": (
            "安全取得稀缺灵草",
            "准备充分后越阶脱身",
            "境界突破打开新选择",
        ),
        "longFormVariation": ("宗门药园求生", "坊市资源交换", "秘境侦察与斗法"),
        "endingAnchor": "主角建立不受强宗支配的修行生路",
        "risks": ("谨慎写成拖延", "突破缺少积累证据"),
        "differentiation": "求生判断、资源闭环和修炼反馈彼此咬合",
    }


def _mystery_seed():
    return SeedPayload(
        title="夜巡司",
        genre="高武 悬疑 诡异",
        logline="巡夜武者追查连环命案，拳脚交锋不断改写证据含义。",
        protagonist="相信证据但容易先入为主的年轻巡官",
        desire="查清命案并阻止下一次献祭",
        coreConflict="嫌疑人各有秘密，幕后者借武道禁术制造错误判断",
        worldPressure="宵禁、追杀与下一名受害者的期限同时逼近",
        openingHook="密室尸体旁留下不属于死者的旧拳印",
        differentiation="公平线索藏在正常动作中，高武交锋会改变位置、战术和证据",
    )


def _mystery_engine():
    return {
        "name": "拳印疑案",
        "storyPromise": "用公平线索与高武行动共同推进诡异命案",
        "protagonistDesire": "识破凶手并阻止献祭",
        "sustainedPressure": "嫌疑人沉默、诡异追杀和期限共同收紧",
        "growthDirection": "巡官学会用新证据修正旧判断并调整战术",
        "conflictLoop": "勘察线索，盘问嫌疑人，遭遇交锋，保护证据，再重建推断",
        "ensembleRoles": (
            {"role": "仵作", "purpose": "检验拳伤并坚持不同判断"},
        ),
        "advantageAndCost": "武者能追击凶手，但伤势会持续限制后续战术",
        "satisfactionSources": ("旧证据被公平改写", "交锋同时争夺证物", "真相揭开后迫使选择"),
        "longFormVariation": ("密室拳印", "夜市追凶", "武馆旧案"),
        "endingAnchor": "巡官在公开证据后阻止献祭",
        "risks": ("故意隐藏关键线索", "战斗与查案彼此脱节"),
        "differentiation": "每次动作冲突都改变证据、位置或战术",
    }


def test_xianxia_survival_and_high_martial_mystery_use_only_their_own_semantics(package):
    xianxia = _recommend(
        package,
        _xianxia_seed(),
        _xianxia_engine(),
    )
    mystery = _recommend(
        package,
        _mystery_seed(),
        _mystery_engine(),
    )

    assert tuple(item.stable_key for item in xianxia.styles) == (
        "cautious-survival-accumulation",
        "high-energy-growth",
        "direct-propulsive",
    )
    assert {"epic-civilization-building", "immersive-ensemble"}.isdisjoint(
        item.stable_key for item in xianxia.styles
    )
    assert tuple(item.stable_key for item in mystery.styles) == (
        "restrained-suspense",
        "high-energy-growth",
        "direct-propulsive",
    )
    assert {"epic-civilization-building", "immersive-ensemble"}.isdisjoint(
        item.stable_key for item in mystery.styles
    )
    categories_by_key = {
        card.stable_key: card.category for card in package.experience_cards
    }
    assert {categories_by_key[item.stable_key] for item in xianxia.experience_cards} == {
        "progression_economy",
        "action_conflict",
    }
    assert {categories_by_key[item.stable_key] for item in mystery.experience_cards} == {
        "suspense",
        "action_conflict",
        "information_release",
    }


def test_shuffle_and_nfkc_casefold_punctuation_are_invariant(package):
    baseline = _recommend(
        package,
        _seed(genre="XIANXIA survival cultivation"),
        _engine(name="MYSTERY ENGINE"),
        seed_hash="1" * 64,
        engine_hash="2" * 64,
    )
    shuffled = package.model_copy(
        update={
            "styles": tuple(reversed(package.styles)),
            "experience_cards": tuple(reversed(package.experience_cards)),
        }
    )
    equivalent = _recommend(
        shuffled,
        _seed(genre=unicodedata.normalize("NFKD", "ＸＩＡＮＸＩＡ　ＳＵＲＶＩＶＡＬ，ＣＵＬＴＩＶＡＴＩＯＮ")),
        _engine(name="ｍｙｓｔｅｒｙ---ｅｎｇｉｎｅ"),
        seed_hash="1" * 64,
        engine_hash="2" * 64,
    )
    assert equivalent == baseline


def test_unmatched_context_uses_explicit_defaults_and_stable_key_ties(package):
    engine = {
        field: "quartz zephyr"
        for field in (
            "name",
            "storyPromise",
            "protagonistDesire",
            "sustainedPressure",
            "growthDirection",
            "conflictLoop",
            "advantageAndCost",
            "endingAnchor",
            "differentiation",
        )
    }
    engine.update(
        {
            "ensembleRoles": ({"role": "quartz", "purpose": "zephyr"},),
            "satisfactionSources": ("quartz",),
            "longFormVariation": ("zephyr",),
            "risks": ("quartz",),
        }
    )
    result = _recommend(
        package,
        _seed(**{field: "quartz zephyr" for field in SeedPayload.model_fields}),
        engine,
    )
    assert tuple(item.stable_key for item in result.styles) == (
        "direct-propulsive",
        "immersive-ensemble",
        "high-energy-growth",
    )
    assert tuple(item.stable_key for item in result.experience_cards) == (
        "plot-cause-effect-relay",
        "character-antagonist-adapts-clock",
    )


@pytest.mark.parametrize(
    "text",
    ("人物", "survivalist mysterybox cultivationist relationship"),
)
def test_short_or_embedded_signals_do_not_trigger_profiles_or_card_overlap(package, text):
    seed = SeedPayload(**{field: text for field in SeedPayload.model_fields})
    engine = {
        field: text
        for field in (
            "name",
            "storyPromise",
            "protagonistDesire",
            "sustainedPressure",
            "growthDirection",
            "conflictLoop",
            "advantageAndCost",
            "endingAnchor",
            "differentiation",
        )
    }
    engine.update(
        {
            "ensembleRoles": ({"role": text, "purpose": text},),
            "satisfactionSources": (text,),
            "longFormVariation": (text,),
            "risks": (text,),
        }
    )

    result = _recommend(package, seed, engine)

    assert tuple(item.stable_key for item in result.styles) == (
        "direct-propulsive",
        "immersive-ensemble",
        "high-energy-growth",
    )
    assert tuple(item.stable_key for item in result.experience_cards) == (
        "plot-cause-effect-relay",
        "character-antagonist-adapts-clock",
    )
    assert all(item.reason_codes == ("default-rank",) for item in result.styles)
    assert all(
        item.reason_codes == ("default-rank",)
        for item in result.experience_cards
    )


def test_recommendation_hash_is_stable_and_external_hashes_only_change_it(package):
    baseline = _recommend(package, seed_hash="a" * 64, engine_hash="b" * 64)
    replay = _recommend(package, seed_hash="a" * 64, engine_hash="b" * 64)
    changed = _recommend(package, seed_hash="c" * 64, engine_hash="b" * 64)

    assert replay == baseline
    assert changed.styles == baseline.styles
    assert changed.experience_cards == baseline.experience_cards
    assert changed.recommendation_hash != baseline.recommendation_hash
    assert baseline.recommendation_hash == canonical_hash(
        {
            "version": RECOMMENDATION_VERSION,
            "seedHash": "a" * 64,
            "engineHash": "b" * 64,
            "styles": [item.model_dump(mode="json") for item in baseline.styles],
            "experienceCards": [
                item.model_dump(mode="json") for item in baseline.experience_cards
            ],
        }
    )


def test_recommender_rejects_invalid_hash_engine_shape_bounds_and_non_release_package(package):
    with pytest.raises(RecommendationInputError, match="hash"):
        _recommend(package, seed_hash="A" * 64)
    with pytest.raises(RecommendationInputError, match="engine payload"):
        _recommend(package, engine={**_engine(), "unknown": "raw"})
    with pytest.raises(RecommendationInputError, match="engine payload"):
        _recommend(package, engine=_engine(name="x" * 2001))
    with pytest.raises(RecommendationInputError, match="engine payload"):
        _recommend(package, engine=_engine(risks=tuple("x" for _ in range(21))))
    too_many_items = _engine(
        satisfactionSources=tuple("x" for _ in range(20)),
        longFormVariation=tuple("x" for _ in range(20)),
        risks=tuple("x" for _ in range(20)),
        ensembleRoles=tuple(
            {"role": "x", "purpose": "x"} for _ in range(20)
        ),
    )
    with pytest.raises(RecommendationInputError, match="engine payload"):
        _recommend(package, engine=too_many_items)
    long_text = "x" * 2_000
    too_many_characters = {
        field: long_text
        for field in (
            "name",
            "storyPromise",
            "protagonistDesire",
            "sustainedPressure",
            "growthDirection",
            "conflictLoop",
            "advantageAndCost",
            "endingAnchor",
            "differentiation",
        )
    }
    too_many_characters.update(
        {
            "ensembleRoles": ({"role": long_text, "purpose": long_text},),
            "satisfactionSources": tuple(long_text for _ in range(15)),
            "longFormVariation": tuple(long_text for _ in range(15)),
            "risks": tuple(long_text for _ in range(15)),
        }
    )
    with pytest.raises(RecommendationInputError, match="engine payload"):
        _recommend(package, engine=too_many_characters)
    candidate = package.model_copy(
        update={
            "styles": (
                package.styles[0].model_copy(
                    update={"provenance": AssetProvenance(decision="candidate")}
                ),
                *package.styles[1:],
            )
        }
    )
    with pytest.raises(Exception, match="ASSET_RELEASE_REVIEW_INCOMPLETE"):
        _recommend(candidate)


def test_public_models_are_strict_frozen_and_api_has_no_limit_or_full_inventory_path(package):
    result = _recommend(package)
    with pytest.raises(ValidationError):
        AssetRecommendationRef(
            stable_key=result.styles[0].stable_key,
            revision="1",
            content_hash=result.styles[0].content_hash,
            reason_codes=result.styles[0].reason_codes,
        )
    with pytest.raises(ValidationError):
        AssetRecommendationResult(**{
            **result.model_dump(mode="python"),
            "styles": list(result.styles),
        })
    with pytest.raises(ValidationError):
        result.styles[0].stable_key = "changed"

    parameters = signature(recommend_assets).parameters
    assert "limit" not in parameters
    assert "card_count" not in parameters
    assert len(result.experience_cards) < len(package.experience_cards)


# Read-only database/API application boundary (M2C Task 3C).
def _read_row(asset, revision_id, *, status="active"):
    return {
        "id": revision_id,
        "stable_key": asset.stable_key,
        "revision": asset.revision,
        "label": asset.name if hasattr(asset, "name") else asset.title,
        "category": getattr(asset, "category", None),
        "payload_json": asset.payload.model_dump(mode="json"),
        "provenance_json": asset.provenance.model_dump(mode="json"),
        "content_hash": asset.content_hash,
        "status": status,
    }


class ReadAssetRepository:
    def __init__(self, package):
        self.project = {"id": "project-1"}
        seed = _seed()
        self.selected = {
            "seed_id": "seed-1",
            "selection_revision": 7,
            "seed_revision_id": "seed-revision-1",
            "seed_revision": 1,
            "seed_hash": canonical_hash(seed),
            "revision_hash": canonical_hash(seed),
            "payload_json": seed.model_dump(mode="json"),
        }
        engine = _engine()
        self.engine = {
            "id": "engine-1",
            "project_id": "project-1",
            "batch_status": "succeeded",
            "selection_revision": self.selected["selection_revision"],
            "seed_id": self.selected["seed_id"],
            "seed_revision_id": self.selected["seed_revision_id"],
            "seed_hash": self.selected["seed_hash"],
            "payload_json": engine,
            "content_hash": canonical_hash(engine),
        }
        self.styles = [
            _read_row(asset, f"style-{index}")
            for index, asset in enumerate(package.styles, 1)
        ]
        self.cards = [
            _read_row(asset, f"card-{index}")
            for index, asset in enumerate(package.experience_cards, 1)
        ]
        self.calls = []

    async def read_project(self, session, project_id):
        self.calls.append(("project", project_id))
        return deepcopy(self.project)

    async def read_selected_seed(self, session, project_id):
        self.calls.append(("selected", project_id))
        return deepcopy(self.selected)

    async def read_engine_option(self, session, project_id, option_id):
        self.calls.append(("engine", project_id, option_id))
        if (
            self.engine is None
            or self.engine["project_id"] != project_id
            or self.engine["id"] != option_id
        ):
            return None
        return deepcopy(self.engine)

    async def list_active_revisions(self, session, asset_type):
        self.calls.append(("catalog", asset_type))
        rows = self.styles if asset_type == "style" else self.cards
        return deepcopy(rows)

    async def fetch_revision_by_id(self, session, asset_type, revision_id):
        self.calls.append(("detail", asset_type, revision_id))
        rows = self.styles if asset_type == "style" else self.cards
        return deepcopy(next((row for row in rows if row["id"] == revision_id), None))


def read_service(repository):
    @asynccontextmanager
    async def connection():
        yield object()

    return AssetReadService(repository, transaction_factory=connection)


@pytest.mark.asyncio
async def test_read_service_requires_exact_approved_catalog_and_filters_category(package):
    repository = ReadAssetRepository(package)
    service = read_service(repository)

    styles = await service.list_styles()
    cards = await service.list_cards(category="dialogue")

    assert len(styles) == 10
    assert len(cards) == 6
    assert {record.asset.category for record in cards} == {"dialogue"}

    repository.styles.pop()
    with pytest.raises(AssetCatalogNotReady):
        await service.list_styles()

    repository = ReadAssetRepository(package)
    repository.cards[0]["provenance_json"] = {
        "reviewer": None, "review_time": None, "decision": "candidate"
    }
    with pytest.raises(AssetCatalogNotReady):
        await read_service(repository).list_cards()


@pytest.mark.asyncio
async def test_detail_accepts_active_or_archived_approved_revision_and_hides_others(package):
    repository = ReadAssetRepository(package)
    service = read_service(repository)
    repository.styles[0]["status"] = "archived"

    archived = await service.get_style("style-1")
    assert archived.status == "archived"

    repository.styles[0]["provenance_json"]["decision"] = "candidate"
    with pytest.raises(AssetNotFound):
        await service.get_style("style-1")
    with pytest.raises(AssetNotFound):
        await service.get_card("cross-project-or-missing")


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ("invalid-json", "content-hash"))
async def test_existing_detail_with_damaged_immutable_row_is_catalog_not_ready(package, damage):
    repository = ReadAssetRepository(package)
    if damage == "invalid-json":
        repository.styles[0]["payload_json"] = b"{invalid"
    else:
        repository.styles[0]["content_hash"] = "f" * 64

    with pytest.raises(AssetCatalogNotReady):
        await read_service(repository).get_style("style-1")


@pytest.mark.asyncio
async def test_recommendation_reads_only_current_db_facts_and_is_order_invariant(package):
    repository = ReadAssetRepository(package)
    baseline = await read_service(repository).recommend("project-1", "engine-1")
    repository.styles.reverse()
    repository.cards.reverse()
    shuffled = await read_service(repository).recommend("project-1", "engine-1")

    assert baseline.recommendation_hash == shuffled.recommendation_hash
    assert baseline.seed_revision_id == "seed-revision-1"
    assert baseline.engine_option_id == "engine-1"
    assert len(baseline.styles) == 3
    assert 2 <= len(baseline.experience_cards) <= 4
    assert all(item.record.id for item in baseline.styles)


@pytest.mark.asyncio
async def test_recommendation_rejects_selected_payload_hash_mismatch(package):
    repository = ReadAssetRepository(package)
    repository.selected["payload_json"] = _seed(title="changed").model_dump(mode="json")

    with pytest.raises(AssetRecommendationConflict):
        await read_service(repository).recommend("project-1", "engine-1")


@pytest.mark.asyncio
async def test_recommendation_rejects_revision_hash_selection_hash_mismatch(package):
    repository = ReadAssetRepository(package)
    repository.selected["revision_hash"] = "f" * 64

    with pytest.raises(AssetRecommendationConflict):
        await read_service(repository).recommend("project-1", "engine-1")


@pytest.mark.asyncio
async def test_recommendation_rejects_engine_payload_hash_mismatch(package):
    repository = ReadAssetRepository(package)
    repository.engine["payload_json"] = _engine(name="changed")

    with pytest.raises(AssetRecommendationConflict):
        await read_service(repository).recommend("project-1", "engine-1")


class SnapshotTransaction:
    def __init__(self, repository):
        self.repository = repository
        self.entered = 0
        self.exited = 0
        self.session_ids = []

    @asynccontextmanager
    async def __call__(self):
        self.entered += 1
        snapshot = {
            "project": deepcopy(self.repository.project),
            "selected": deepcopy(self.repository.selected),
            "engine": deepcopy(self.repository.engine),
            "styles": deepcopy(self.repository.styles),
            "cards": deepcopy(self.repository.cards),
        }
        session = type("SnapshotSession", (), {})()
        session.active = True
        session.snapshot = snapshot
        self.session_ids.append(id(session))
        try:
            yield session
        finally:
            session.active = False
            self.exited += 1


class MutatingSnapshotRepository(ReadAssetRepository):
    def _snapshot(self, session, key):
        assert session.active is True
        return deepcopy(session.snapshot[key])

    async def read_project(self, session, project_id):
        result = self._snapshot(session, "project")
        self.selected["seed_hash"] = "f" * 64
        return result

    async def read_selected_seed(self, session, project_id):
        return self._snapshot(session, "selected")

    async def read_engine_option(self, session, project_id, option_id):
        row = self._snapshot(session, "engine")
        return row if row["project_id"] == project_id and row["id"] == option_id else None

    async def list_active_revisions(self, session, asset_type):
        return self._snapshot(session, "styles" if asset_type == "style" else "cards")


@pytest.mark.asyncio
async def test_recommendation_uses_one_active_transaction_snapshot_despite_live_mutation(package):
    repository = MutatingSnapshotRepository(package)
    transaction_factory = SnapshotTransaction(repository)
    service = AssetReadService(
        repository,
        transaction_factory=transaction_factory,
    )

    result = await service.recommend("project-1", "engine-1")

    assert result.seed_hash != repository.selected["seed_hash"]
    assert transaction_factory.entered == transaction_factory.exited == 1
    assert len(transaction_factory.session_ids) == 1


def test_recommender_accepts_release_asset_inventory_without_manifest(package):
    inventory = AssetInventory(
        styles=package.styles,
        experience_cards=package.experience_cards,
    )

    from_inventory = recommend_assets(
        _seed(),
        _engine(),
        inventory,
        seed_hash=canonical_hash(_seed()),
        engine_hash=canonical_hash(_engine()),
    )
    from_package = _recommend(package)

    assert from_inventory == from_package


def test_recommendation_inventory_rejects_polluted_fixed_style_key(package):
    polluted_style = package.styles[0].model_copy(
        update={"stable_key": "polluted-style-key"}
    )
    inventory = AssetInventory(
        styles=(polluted_style, *package.styles[1:]),
        experience_cards=package.experience_cards,
    )

    with pytest.raises(RecommendationInputError, match="profile"):
        validate_recommendation_inventory(inventory)


@pytest.mark.asyncio
async def test_polluted_fixed_style_key_makes_all_catalog_reads_503(package):
    repository = ReadAssetRepository(package)
    repository.styles[0]["stable_key"] = "polluted-style-key"
    service = read_service(repository)

    with pytest.raises(AssetCatalogNotReady):
        await service.list_styles()
    with pytest.raises(AssetCatalogNotReady):
        await service.list_cards()
    with pytest.raises(AssetCatalogNotReady):
        await service.recommend("project-1", "engine-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ("project", "engine"))
async def test_recommendation_hides_project_and_cross_project_engine_existence(package, missing):
    repository = ReadAssetRepository(package)
    if missing == "project":
        repository.project = None
    else:
        repository.engine["project_id"] = "another-project"

    with pytest.raises(AssetNotFound):
        await read_service(repository).recommend("project-1", "engine-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damage",
    (
        "seed-absent", "batch-running", "seed-id-drift",
        "seed-revision-drift", "seed-hash-drift", "seed-json", "engine-json",
    ),
)
async def test_recommendation_conflicts_on_unready_or_drifted_db_facts(package, damage):
    repository = ReadAssetRepository(package)
    if damage == "seed-absent":
        repository.selected = None
    elif damage == "batch-running":
        repository.engine["batch_status"] = "running"
    elif damage == "seed-id-drift":
        repository.engine["seed_id"] = "old-seed"
    elif damage == "seed-revision-drift":
        repository.engine["seed_revision_id"] = "old-revision"
    elif damage == "seed-hash-drift":
        repository.engine["seed_hash"] = "f" * 64
    elif damage == "seed-json":
        repository.selected["payload_json"] = b"{invalid"
    else:
        repository.engine["payload_json"] = "{invalid"

    with pytest.raises(AssetRecommendationConflict):
        await read_service(repository).recommend("project-1", "engine-1")


class RecordingReadSession:
    def __init__(self):
        self.events = []

    async def fetchone(self, sql, params=None):
        self.events.append(("fetchone", sql, params))
        return None

    async def fetchall(self, sql, params=None):
        self.events.append(("fetchall", sql, params))
        return []

    async def execute(self, *args, **kwargs):
        raise AssertionError("read repository must not execute DML")


@pytest.mark.asyncio
async def test_read_repository_uses_fixed_bound_selects_and_zero_write_sql():
    session = RecordingReadSession()
    repository = AssetRepository()

    await repository.read_project(session, "project-1")
    await repository.read_selected_seed(session, "project-1")
    await repository.read_engine_option(session, "project-1", "engine-1")
    await repository.list_active_revisions(session, "style")
    await repository.list_active_revisions(session, "card")
    await repository.fetch_revision_by_id(session, "style", "style-id")
    await repository.fetch_revision_by_id(session, "card", "card-id")

    assert len(session.events) == 7
    rendered_sql = " ".join(sql.casefold() for _, sql, _ in session.events)
    assert not any(word in rendered_sql for word in (" insert ", " update ", " delete ", " for update"))
    assert session.events[1][2] == ("project-1",)
    assert session.events[2][2] == ("project-1", "engine-1")
    assert session.events[-1][2] == ("card-id",)
