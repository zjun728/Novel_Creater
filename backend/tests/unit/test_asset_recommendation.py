from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.domain.asset_eligibility import (
    load_asset_eligibility_package,
)
from backend.domain.assets import AssetProvenance, load_asset_package
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.seeds import build_seed_provenance, seed_revision_document
from backend.repositories.assets import AssetRepository
from backend.scripts.seed_writer_assets import AssetSeedCommandError, run_cli
from backend.http_errors import (
    AssetCatalogNotReady,
    AssetNotFound,
)
from backend.services.assets import AssetReadService, AssetSeedConflict, AssetSeedService
from backend.services.creative_assets import CreativeAssetService


MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "writer-core-v1.1.0"
    / "manifest.json"
)
TAXONOMY_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "recommendation-taxonomy-v1.0.0"
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


# Typed recommendation eligibility contract (Phase 2C Task 2).
from backend.domain.seeds import SeedPayload


def _candidate_inventory(package):
    from backend.domain.asset_recommendations import AssetCandidateSummary

    return tuple(
        AssetCandidateSummary(
            asset_revision_id=f"style-{index}",
            asset_type="style",
            stable_key=asset.stable_key,
            revision=asset.revision,
            content_hash=asset.content_hash,
            status="active",
            label=asset.name,
            category=None,
            facts="free text deliberately says xianxia mystery romance",
        )
        for index, asset in enumerate(package.styles, 1)
    ) + tuple(
        AssetCandidateSummary(
            asset_revision_id=f"card-{index}",
            asset_type="experience_card",
            stable_key=asset.stable_key,
            revision=asset.revision,
            content_hash=asset.content_hash,
            status="active",
            label=asset.title,
            category=asset.category,
            facts="free text deliberately says xianxia mystery romance",
        )
        for index, asset in enumerate(package.experience_cards, 1)
    )


def test_typed_filter_requires_exact_taxonomy_version_and_hash(package):
    from backend.domain.asset_recommendations import (
        AssetRecommendationScope,
        RecommendationInputError,
        filter_eligible_candidates,
    )

    taxonomy = load_asset_eligibility_package(
        TAXONOMY_MANIFEST,
        asset_package=package,
        mode="release",
    )
    scope = AssetRecommendationScope(
        genre="historical",
        creation_stage="drafting",
        status="active",
        prohibited_directions=(),
    )

    for version, content_hash in (
        ("recommendation-taxonomy-v0.0.0", taxonomy.manifest.eligibility_file.sha256),
        (taxonomy.package_version, "f" * 64),
    ):
        with pytest.raises(RecommendationInputError, match="taxonomy"):
            filter_eligible_candidates(
                _candidate_inventory(package),
                taxonomy_entries=taxonomy.entries,
                taxonomy_version=taxonomy.package_version,
                taxonomy_hash=taxonomy.manifest.eligibility_file.sha256,
                expected_taxonomy_version=version,
                expected_taxonomy_hash=content_hash,
                scope=scope,
            )


def test_typed_filter_ignores_candidate_free_text_and_uses_only_four_dimensions(
    package,
):
    from backend.domain.asset_recommendations import (
        AssetRecommendationScope,
        filter_eligible_candidates,
    )

    taxonomy = load_asset_eligibility_package(
        TAXONOMY_MANIFEST,
        asset_package=package,
        mode="release",
    )
    candidates = _candidate_inventory(package)
    scope = AssetRecommendationScope(
        genre="historical",
        creation_stage="drafting",
        status="active",
        prohibited_directions=("comedic",),
    )
    result = filter_eligible_candidates(
        candidates,
        taxonomy_entries=taxonomy.entries,
        taxonomy_version=taxonomy.package_version,
        taxonomy_hash=taxonomy.manifest.eligibility_file.sha256,
        expected_taxonomy_version=taxonomy.package_version,
        expected_taxonomy_hash=taxonomy.manifest.eligibility_file.sha256,
        scope=scope,
    )
    entries = {
        (entry.asset_type, entry.stable_key, entry.asset_content_hash): entry
        for entry in taxonomy.entries
    }

    assert result
    assert {
        (item.asset_type, item.stable_key, item.content_hash) for item in result
    } == {
        (item.asset_type, item.stable_key, item.content_hash)
        for item in candidates
        if (
            (entry := entries[
                (item.asset_type, item.stable_key, item.content_hash)
            ])
            and ("historical" in entry.genres or "general" in entry.genres)
            and "drafting" in entry.creation_stages
            and "comedic" not in entry.prohibited_directions
        )
    }


def test_typed_filter_can_return_zero_without_default_or_forced_count(package):
    from backend.domain.asset_recommendations import (
        AssetRecommendationScope,
        filter_eligible_candidates,
    )

    taxonomy = load_asset_eligibility_package(
        TAXONOMY_MANIFEST,
        asset_package=package,
        mode="release",
    )
    archived = tuple(
        item.model_copy(update={"status": "archived"})
        for item in _candidate_inventory(package)
    )
    result = filter_eligible_candidates(
        archived,
        taxonomy_entries=taxonomy.entries,
        taxonomy_version=taxonomy.package_version,
        taxonomy_hash=taxonomy.manifest.eligibility_file.sha256,
        expected_taxonomy_version=taxonomy.package_version,
        expected_taxonomy_hash=taxonomy.manifest.eligibility_file.sha256,
        scope=AssetRecommendationScope(
            genre="historical",
            creation_stage="drafting",
            status="active",
            prohibited_directions=(),
        ),
    )

    assert result == ()


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


def test_asset_recommendation_decodes_seed_payload_with_reserved_provenance():
    seed = _seed()
    provenance = build_seed_provenance(
        kind="manual",
        snapshots=(),
        analysis=None,
        inspiration_attempt=None,
        public_notes=("作者显式保存。",),
    )
    selected = {
        "selection_revision": 7,
        "seed_id": "seed-1",
        "seed_revision_id": "revision-1",
        "seed_hash": canonical_hash(seed),
        "revision_hash": canonical_hash(seed),
        "payload_json": seed_revision_document(seed, provenance),
    }
    option = _engine()
    engine = {
        "batch_status": "succeeded",
        "selection_revision": 7,
        "seed_id": "seed-1",
        "seed_revision_id": "revision-1",
        "seed_hash": canonical_hash(seed),
        "payload_json": option,
        "content_hash": canonical_hash(option),
    }

    decoded, decoded_option = AssetReadService._recommendation_inputs(
        selected,
        engine,
    )

    assert decoded == seed
    assert decoded_option == option


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
        draft = {
            "schemaVersion": "contract-draft-v2",
            "draftStage": "engine",
            "engineOptionId": self.engine["id"],
            "engineHash": self.engine["content_hash"],
            "channelProfileKey": "qidian-qq",
            "genreProfileKey": "historical",
            "qualityCharterVersion": "quality-v1",
            "targetTotalWords": 1_000_000,
            "expectedVolumeCount": 10,
            "expectedChapterCount": 400,
            "chapterWordRangePreference": (2_000, 3_000),
            "prohibitedDirections": ("不要机械推进",),
            "authorNotes": "long-form",
            "primaryStyleRef": None,
            "secondaryStyleRef": None,
            "experienceCardRefs": None,
            "corpusSourceRefs": None,
            "likes": None,
            "dislikes": None,
            "seedRevisionId": self.selected["seed_revision_id"],
            "seedHash": self.selected["seed_hash"],
            "modelBindingRef": {
                "id": "binding-1",
                "revision": 1,
                "contentHash": "a" * 64,
            },
        }
        self.contract_draft = {
            "engine_option_id": self.engine["id"],
            "selection_revision": self.selected["selection_revision"],
            "seed_hash": self.selected["seed_hash"],
            "draft_json": canonical_json(draft),
            "content_hash": canonical_hash(draft),
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

    async def read_contract_draft(self, session, project_id, option_id):
        self.calls.append(("contract-draft", project_id, option_id))
        if (
            self.contract_draft is None
            or self.contract_draft["engine_option_id"] != option_id
        ):
            return None
        return deepcopy(self.contract_draft)

    async def list_active_revisions(self, session, asset_type):
        self.calls.append(("catalog", asset_type))
        rows = self.styles if asset_type == "style" else self.cards
        return deepcopy(rows)

    async def list_current_revisions(self, session, asset_type):
        self.calls.append(("current-catalog", asset_type))
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
async def test_read_service_current_head_catalog_includes_active_and_archived(
    package,
):
    repository = ReadAssetRepository(package)
    repository.styles[0]["status"] = "archived"
    service = read_service(repository)

    styles, cards = await service.current_head_catalog()

    assert len(styles) == 10
    assert len(cards) == 64
    assert {record.status for record in styles} == {"active", "archived"}
    assert repository.calls == [
        ("current-catalog", "style"),
        ("current-catalog", "card"),
    ]


class SplitCurrentHeadReadService:
    def __init__(self, package, *, unmatched_archived=False):
        styles = [
            AssetReadService._record(
                "style",
                _read_row(
                    asset,
                    f"style-{index}",
                    status="archived" if index == 1 else "active",
                ),
            )
            for index, asset in enumerate(package.styles, 1)
        ]
        if unmatched_archived:
            original = styles[0]
            changed_asset = original.asset.model_copy(
                update={"stable_key": "archived-unmatched-style"}
            )
            styles[0] = type(original)(
                id=original.id,
                status=original.status,
                asset=changed_asset,
            )
        self.all_styles = tuple(styles)
        self.active_styles = tuple(
            record for record in styles if record.status == "active"
        )
        self.cards = tuple(
            AssetReadService._record(
                "card",
                _read_row(asset, f"card-{index}"),
            )
            for index, asset in enumerate(package.experience_cards, 1)
        )

    async def catalog(self):
        return self.active_styles, self.cards

    async def current_head_catalog(self):
        return self.all_styles, self.cards


@pytest.mark.asyncio
async def test_creative_inventory_and_status_filter_use_all_current_heads(
    package,
):
    taxonomy = load_asset_eligibility_package(
        TAXONOMY_MANIFEST,
        asset_package=package,
        mode="release",
    )
    service = CreativeAssetService(
        SplitCurrentHeadReadService(package),
        taxonomy=taxonomy,
    )

    inventory = await service.inventory()
    active = await service.list_styles(status="active")
    archived = await service.list_styles(status="archived")

    assert inventory.style_count == 10
    assert inventory.statuses == ("active", "archived")
    assert len(active) == 9
    assert len(archived) == 1
    assert archived[0].record.status == "archived"


@pytest.mark.asyncio
async def test_unmatched_archived_current_head_is_basic_listable_not_eligible(
    package,
):
    taxonomy = load_asset_eligibility_package(
        TAXONOMY_MANIFEST,
        asset_package=package,
        mode="release",
    )
    service = CreativeAssetService(
        SplitCurrentHeadReadService(package, unmatched_archived=True),
        taxonomy=taxonomy,
    )

    archived = await service.list_styles(status="archived")
    typed = await service.list_styles(
        status="archived",
        genre="general",
    )

    assert len(archived) == 1
    assert archived[0].record.asset.stable_key == "archived-unmatched-style"
    assert archived[0].eligibility is None
    assert typed == ()


@pytest.mark.asyncio
async def test_unmatched_active_current_head_fails_catalog_closed(package):
    taxonomy = load_asset_eligibility_package(
        TAXONOMY_MANIFEST,
        asset_package=package,
        mode="release",
    )
    reader = SplitCurrentHeadReadService(package)
    original = reader.all_styles[1]
    changed = type(original)(
        id=original.id,
        status="active",
        asset=original.asset.model_copy(
            update={"stable_key": "active-unmatched-style"}
        ),
    )
    reader.all_styles = (
        reader.all_styles[0],
        changed,
        *reader.all_styles[2:],
    )
    service = CreativeAssetService(reader, taxonomy=taxonomy)

    with pytest.raises(AssetCatalogNotReady):
        await service.inventory()


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
    await repository.read_contract_draft(session, "project-1", "engine-1")
    await repository.list_active_revisions(session, "style")
    await repository.list_active_revisions(session, "card")
    await repository.fetch_revision_by_id(session, "style", "style-id")
    await repository.fetch_revision_by_id(session, "card", "card-id")

    assert len(session.events) == 8
    rendered_sql = " ".join(sql.casefold() for _, sql, _ in session.events)
    assert not any(word in rendered_sql for word in (" insert ", " update ", " delete ", " for update"))
    assert session.events[1][2] == ("project-1",)
    assert session.events[2][2] == ("project-1", "engine-1")
    assert session.events[3][2] == ("project-1", "engine-1")
    assert session.events[-1][2] == ("card-id",)


@pytest.mark.asyncio
async def test_read_repository_lists_only_current_heads_with_both_statuses():
    session = RecordingReadSession()
    repository = AssetRepository()

    await repository.list_current_revisions(session, "style")
    await repository.list_current_revisions(session, "card")

    assert len(session.events) == 2
    for _, sql, params in session.events:
        normalized = " ".join(sql.casefold().split())
        assert " join " in normalized
        assert "_heads h" in normalized
        assert "r.status in ('active','archived')" in normalized
        assert "order by r.stable_key asc" in normalized
        assert params is None
        assert not any(
            token in f" {normalized} "
            for token in (" insert ", " update ", " delete ", " for update ")
        )


@pytest.mark.asyncio
async def test_read_repository_details_cannot_read_arbitrary_historical_revisions():
    session = RecordingReadSession()
    repository = AssetRepository()

    await repository.fetch_revision_by_id(session, "style", "style-id")
    await repository.fetch_revision_by_id(session, "card", "card-id")

    assert len(session.events) == 2
    for _, sql, params in session.events:
        normalized = " ".join(sql.casefold().split())
        assert " join " in normalized
        assert "_heads h" in normalized
        assert "r.id=%s" in normalized
        assert "r.status in ('active','archived')" in normalized
        assert params is not None
