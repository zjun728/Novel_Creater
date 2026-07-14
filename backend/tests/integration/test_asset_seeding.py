from __future__ import annotations

from contextlib import asynccontextmanager
from itertools import count
import json
from pathlib import Path

import aiomysql
import pytest

from backend.domain.assets import ASSET_CATEGORIES, AssetProvenance, load_asset_package
from backend.domain.json_contracts import canonical_hash
from backend.repositories.assets import AssetRepository
from backend.services.assets import AssetSeedConflict, AssetSeedService
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]
MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "writer-core-v1.1.0"
    / "manifest.json"
)


def service(disposable_mysql, repository=None, *, start=1):
    ids = count(start)
    return AssetSeedService(
        repository or AssetRepository(),
        transaction_factory=transaction_factory_for(
            disposable_mysql.connection_config
        ),
        connection_factory=readonly_connection(disposable_mysql),
        id_factory=lambda: f"10000000-0000-0000-0000-{next(ids):012d}",
        clock=lambda: 1_720_000_000_000,
    )


def readonly_connection(disposable_mysql):
    @asynccontextmanager
    async def factory():
        yield disposable_mysql.session

    return factory


def replace_style(package, **updates):
    styles = list(package.styles)
    styles[0] = styles[0].model_copy(update=updates)
    return package.model_copy(update={"styles": tuple(styles)})


def next_style_revision(package, revision):
    original = package.styles[0]
    payload = original.payload.model_copy(
        update={"reading_experience": f"integration revision {revision}"}
    )
    return replace_style(
        package,
        revision=revision,
        payload=payload,
        content_hash=canonical_hash(payload),
    )


async def asset_counts(session):
    values = []
    for table in (
        "style_templates",
        "style_template_heads",
        "experience_cards",
        "experience_card_heads",
    ):
        row = await session.fetchone(f"SELECT COUNT(*) AS count FROM {table}")
        values.append(int(row["count"]))
    return tuple(values)


async def insert_style_revision(session, asset, *, row_id, status="active"):
    await session.execute(
        "INSERT INTO style_templates "
        "(id,stable_key,revision,name,payload_json,provenance_json,content_hash,"
        "status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)",
        (
            row_id,
            asset.stable_key,
            asset.revision,
            asset.name,
            json.dumps(asset.payload.model_dump(mode="json"), ensure_ascii=False),
            json.dumps(
                asset.provenance.model_dump(mode="json"), ensure_ascii=False
            ),
            asset.content_hash,
            status,
        ),
    )


async def test_release_package_first_seed_and_exact_replay_are_idempotent(
    disposable_mysql,
):
    package = load_asset_package(MANIFEST, mode="release")
    seeder = service(disposable_mysql)

    first = await seeder.seed(package)
    replay = await seeder.seed(package)

    assert (first.inserted, first.replayed, first.advanced) == (74, 0, 0)
    assert (replay.inserted, replay.replayed, replay.advanced) == (0, 74, 0)
    for table, expected in (
        ("style_templates", 10),
        ("style_template_heads", 10),
        ("experience_cards", 64),
        ("experience_card_heads", 64),
    ):
        row = await disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table}"
        )
        assert int(row["count"]) == expected


async def test_revision_plus_one_keeps_history_and_hash_bound_head(
    disposable_mysql,
):
    package = load_asset_package(MANIFEST, mode="release")
    seeder = service(disposable_mysql)
    await seeder.seed(package)
    original = package.styles[0]
    payload = original.payload.model_copy(
        update={"reading_experience": "integration revision two"}
    )
    styles = list(package.styles)
    styles[0] = original.model_copy(
        update={
            "revision": 2,
            "payload": payload,
            "content_hash": canonical_hash(payload),
        }
    )

    report = await seeder.seed(package.model_copy(update={"styles": tuple(styles)}))

    assert (report.inserted, report.replayed, report.advanced) == (0, 73, 1)
    rows = await disposable_mysql.session.fetchall(
        "SELECT revision,status,content_hash FROM style_templates "
        "WHERE stable_key=%s ORDER BY revision",
        (original.stable_key,),
    )
    assert [(row["revision"], row["status"]) for row in rows] == [
        (1, "archived"),
        (2, "active"),
    ]
    head = await disposable_mysql.session.fetchone(
        "SELECT revision,content_hash FROM style_template_heads WHERE stable_key=%s",
        (original.stable_key,),
    )
    assert (head["revision"], head["content_hash"]) == (
        2,
        canonical_hash(payload),
    )


async def test_contract_asset_hash_foreign_key_shape_is_declared(
    disposable_mysql,
):
    """Schema-level proof; contract fixtures are completed in M2D."""

    constraints = await disposable_mysql.session.fetchall(
        "SELECT TABLE_NAME,COLUMN_NAME,REFERENCED_COLUMN_NAME "
        "FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN "
        "('style_contract_template_refs','creation_contract_experience_refs') "
        "AND REFERENCED_TABLE_NAME IS NOT NULL ORDER BY TABLE_NAME,ORDINAL_POSITION"
    )
    triples = {
        (row["TABLE_NAME"], row["COLUMN_NAME"], row["REFERENCED_COLUMN_NAME"])
        for row in constraints
    }
    assert (
        "style_contract_template_refs",
        "asset_hash",
        "content_hash",
    ) in triples
    assert (
        "creation_contract_experience_refs",
        "asset_hash",
        "content_hash",
    ) in triples


async def test_experience_category_check_accepts_exact_domain_values_and_rejects_old_aliases(
    disposable_mysql,
):
    for index, category in enumerate(ASSET_CATEGORIES, 1):
        await disposable_mysql.session.execute(
            "INSERT INTO experience_cards "
            "(id,stable_key,revision,title,category,payload_json,provenance_json,"
            "content_hash,status,created_at) VALUES (%s,%s,1,%s,%s,'{}','{}',%s,"
            "'active',1)",
            (
                f"20000000-0000-0000-0000-{index:012d}",
                f"category-{category}",
                category,
                category,
                f"{index:064x}",
            ),
        )

    for index, invalid in enumerate(("plot", "information", "rhythm", "unknown"), 100):
        with pytest.raises((aiomysql.IntegrityError, aiomysql.OperationalError)):
            await disposable_mysql.session.execute(
                "INSERT INTO experience_cards "
                "(id,stable_key,revision,title,category,payload_json,provenance_json,"
                "content_hash,status,created_at) VALUES (%s,%s,1,%s,%s,'{}','{}',%s,"
                "'active',1)",
                (
                    f"20000000-0000-0000-0000-{index:012d}",
                    f"invalid-{invalid}",
                    invalid,
                    invalid,
                    f"{index:064x}",
                ),
            )


async def test_mid_package_sql_failure_rolls_back_all_four_asset_tables(
    disposable_mysql,
):
    class SqlFailureRepository(AssetRepository):
        calls = 0

        async def insert_revision(self, session, asset_type, row):
            self.calls += 1
            if self.calls == 11:
                await session.execute("INSERT INTO task3a_missing_table VALUES (1)")
            await super().insert_revision(session, asset_type, row)

    package = load_asset_package(MANIFEST, mode="release")
    with pytest.raises((aiomysql.ProgrammingError, aiomysql.OperationalError)):
        await service(disposable_mysql, SqlFailureRepository()).seed(package)

    assert await asset_counts(disposable_mysql.session) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "damage",
    ("extra", "missing", "empty_styles", "empty_cards"),
)
async def test_innodb_rejects_extra_missing_or_cross_type_partial_head_sets(
    disposable_mysql, damage
):
    package = load_asset_package(MANIFEST, mode="release")
    seeder = service(disposable_mysql)
    await seeder.seed(package)
    if damage == "extra":
        await disposable_mysql.session.execute(
            "INSERT INTO style_templates "
            "(id,stable_key,revision,name,payload_json,provenance_json,content_hash,"
            "status,created_at) VALUES (%s,'unknown-style',1,'Unknown','{}','{}',%s,"
            "'active',1)",
            ("90000000-0000-0000-0000-000000000001", "f" * 64),
        )
        await disposable_mysql.session.execute(
            "INSERT INTO style_template_heads "
            "(stable_key,style_template_id,revision,content_hash,updated_at) "
            "VALUES ('unknown-style',%s,1,%s,1)",
            ("90000000-0000-0000-0000-000000000001", "f" * 64),
        )
    elif damage == "missing":
        await disposable_mysql.session.execute(
            "DELETE FROM experience_card_heads WHERE stable_key=%s",
            (package.experience_cards[0].stable_key,),
        )
    elif damage == "empty_styles":
        await disposable_mysql.session.execute("DELETE FROM style_template_heads")
    else:
        await disposable_mysql.session.execute("DELETE FROM experience_card_heads")
    before = await asset_counts(disposable_mysql.session)

    with pytest.raises(AssetSeedConflict, match="head set"):
        await seeder.seed(package)

    assert await asset_counts(disposable_mysql.session) == before


async def test_innodb_rejects_revision_jump_and_backward_without_mutation(
    disposable_mysql,
):
    package = load_asset_package(MANIFEST, mode="release")
    seeder = service(disposable_mysql)
    await seeder.seed(package)
    before = await asset_counts(disposable_mysql.session)

    with pytest.raises(AssetSeedConflict, match="next revision"):
        await seeder.seed(next_style_revision(package, 3))
    assert await asset_counts(disposable_mysql.session) == before

    revision_two = next_style_revision(package, 2)
    await seeder.seed(revision_two)
    after_advance = await asset_counts(disposable_mysql.session)
    with pytest.raises(AssetSeedConflict, match="next revision"):
        await seeder.seed(package)
    assert await asset_counts(disposable_mysql.session) == after_advance


@pytest.mark.parametrize("difference", ("title", "provenance"))
async def test_innodb_same_revision_requires_title_and_provenance_identity(
    disposable_mysql, difference
):
    package = load_asset_package(MANIFEST, mode="release")
    seeder = service(disposable_mysql)
    await seeder.seed(package)
    if difference == "title":
        changed = replace_style(package, name="Same revision renamed")
    else:
        changed = replace_style(
            package,
            provenance=AssetProvenance(
                reviewer="Different reviewer",
                review_time="2026-07-12T16:00:00+08:00",
                decision="approved",
            ),
        )
    before = await asset_counts(disposable_mysql.session)

    with pytest.raises(AssetSeedConflict, match="immutable revision differs"):
        await seeder.seed(changed)

    assert await asset_counts(disposable_mysql.session) == before


@pytest.mark.parametrize("failure", ("archive", "head"))
async def test_archive_or_head_cas_failure_rolls_back_insert_and_old_status(
    disposable_mysql, failure
):
    class ArchiveFailureRepository(AssetRepository):
        async def archive_revision(self, session, asset_type, revision_id):
            return 0

    class HeadFailureRepository(AssetRepository):
        async def move_head(self, session, asset_type, row, *, expected):
            return 0

    package = load_asset_package(MANIFEST, mode="release")
    await service(disposable_mysql).seed(package)
    repository = (
        ArchiveFailureRepository() if failure == "archive" else HeadFailureRepository()
    )

    with pytest.raises(AssetSeedConflict):
        await service(disposable_mysql, repository, start=200).seed(
            next_style_revision(package, 2)
        )

    assert await asset_counts(disposable_mysql.session) == (10, 10, 64, 64)
    original = package.styles[0]
    rows = await disposable_mysql.session.fetchall(
        "SELECT revision,status FROM style_templates WHERE stable_key=%s "
        "ORDER BY revision",
        (original.stable_key,),
    )
    assert list(rows) == [{"revision": 1, "status": "active"}]
    head = await disposable_mysql.session.fetchone(
        "SELECT revision,content_hash FROM style_template_heads WHERE stable_key=%s",
        (original.stable_key,),
    )
    assert head == {"revision": 1, "content_hash": original.content_hash}


@pytest.mark.parametrize(
    "corruption",
    ("orphan_revision_one", "orphan_next_revision", "archived_head_revision"),
)
async def test_dry_run_and_execute_reject_innodb_orphans_and_archived_head_without_changes(
    disposable_mysql, corruption
):
    package = load_asset_package(MANIFEST, mode="release")
    seeder = service(disposable_mysql)
    target_package = package
    if corruption == "orphan_revision_one":
        await insert_style_revision(
            disposable_mysql.session,
            package.styles[0],
            row_id="70000000-0000-0000-0000-000000000001",
        )
    else:
        await seeder.seed(package)
        target_package = next_style_revision(package, 2)
        if corruption == "orphan_next_revision":
            await insert_style_revision(
                disposable_mysql.session,
                target_package.styles[0],
                row_id="70000000-0000-0000-0000-000000000002",
            )
        else:
            await disposable_mysql.session.execute(
                "UPDATE style_templates SET status='archived' "
                "WHERE stable_key=%s AND revision=1",
                (target_package.styles[0].stable_key,),
            )
    before = await asset_counts(disposable_mysql.session)

    with pytest.raises(AssetSeedConflict):
        await seeder.dry_run(target_package)
    assert await asset_counts(disposable_mysql.session) == before
    with pytest.raises(AssetSeedConflict):
        await seeder.seed(target_package)
    assert await asset_counts(disposable_mysql.session) == before


@pytest.mark.parametrize(
    "corruption",
    ("no_head_orphan_two", "future_three", "old_active"),
)
async def test_complete_innodb_revision_history_is_required_by_dry_run_and_execute(
    disposable_mysql, corruption
):
    package = load_asset_package(MANIFEST, mode="release")
    seeder = service(disposable_mysql)
    if corruption == "no_head_orphan_two":
        target_package = package
        orphan = next_style_revision(package, 2).styles[0]
        await insert_style_revision(
            disposable_mysql.session,
            orphan,
            row_id="71000000-0000-0000-0000-000000000002",
        )
    else:
        await seeder.seed(package)
        if corruption == "future_three":
            target_package = package
            future = next_style_revision(package, 3).styles[0]
            await insert_style_revision(
                disposable_mysql.session,
                future,
                row_id="71000000-0000-0000-0000-000000000003",
            )
        else:
            target_package = next_style_revision(package, 2)
            await seeder.seed(target_package)
            await disposable_mysql.session.execute(
                "UPDATE style_templates SET status='active' "
                "WHERE stable_key=%s AND revision=1",
                (target_package.styles[0].stable_key,),
            )
    before = await asset_counts(disposable_mysql.session)

    with pytest.raises(AssetSeedConflict):
        await seeder.dry_run(target_package)
    assert await asset_counts(disposable_mysql.session) == before
    with pytest.raises(AssetSeedConflict):
        await seeder.seed(target_package)
    assert await asset_counts(disposable_mysql.session) == before
