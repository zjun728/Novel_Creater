import asyncio
import re

import pytest

import backend.scripts.prepare_phase8a_browser_db as fixture


DATABASE = "novel_creator_test_0123456789abcdef0123456789abcdef"


def test_phase8a_fixture_declares_three_deterministic_projects_and_exact_authority():
    assert fixture.PROJECTS == {
        "complete": "8a000000-0000-4000-8000-000000000001",
        "awaiting-author": "8a000000-0000-4000-8000-000000000002",
        "corrupt": "8a000000-0000-4000-8000-000000000003",
    }
    assert fixture.CHAPTER_TITLES == (
        "泔水醒来，三日织机赌局",
        "废料改机",
        "复验定局",
    )
    assert len(fixture.PINNED_OUTLINES) == 4
    assert all(outline.chapter_goal for outline in fixture.PINNED_OUTLINES)
    assert fixture.WORKING_SENTINEL not in "".join(fixture.FINAL_PROSE)
    assert fixture.CANDIDATE_SENTINEL not in "".join(fixture.FINAL_PROSE)
    assert fixture.fixture_signature()["finalCounts"] == [3, 3, 3]
    assert fixture.postcondition_signature()["finalCounts"] == [3, 4, 3]
    assert fixture.postcondition_signature()["lifecycles"] == ["archived", "active", "active"]


@pytest.mark.parametrize("name", ["novel_creator", "novel_creater", "../" + DATABASE])
def test_fixture_rejects_every_non_disposable_schema(name):
    with pytest.raises(RuntimeError, match="disposable"):
        fixture.assert_database_name(name)


def test_fixture_source_is_provider_free_and_has_no_schema_ddl():
    source = open(fixture.__file__, encoding="utf-8").read()
    assert "ProviderMustNotRun" in source
    assert "prepare_product_shell_browser_db" not in source
    assert not re.search(r"\b(?:CREATE|DROP)\s+(?:DATABASE|SCHEMA)\b", source, re.I)
    assert not re.search(r"ProviderProfileService|httpx|requests|aiohttp", source)


def test_fixture_cli_owns_runtime_configuration_lifecycle():
    source = open(fixture.__file__, encoding="utf-8").read()
    assert "load_runtime_configuration" in source
    assert "install_runtime_configuration" in source
    assert "clear_runtime_configuration" in source
    assert source.index("install_runtime_configuration") < source.index("await (verify_postconditions")
    assert source.index("await close_pool()") < source.index("clear_runtime_configuration(snapshot)")


@pytest.mark.asyncio
async def test_prepare_is_idempotent_only_for_the_same_complete_fixture(monkeypatch):
    calls = []

    async def authority(database_name):
        calls.append(("authority", database_name))

    snapshots = iter([None, fixture.fixture_signature(), fixture.fixture_signature()])

    async def snapshot():
        value = next(snapshots)
        calls.append(("snapshot", value))
        return value

    async def seed():
        calls.append(("seed", None))

    monkeypatch.setattr(fixture, "assert_owned_database", authority)
    monkeypatch.setattr(fixture, "read_fixture_signature", snapshot)
    monkeypatch.setattr(fixture, "seed_fixture", seed)

    await fixture.prepare(DATABASE)
    await fixture.prepare(DATABASE)

    assert [name for name, _ in calls].count("seed") == 1


@pytest.mark.asyncio
async def test_prepare_refuses_partially_populated_schema(monkeypatch):
    async def authority(_database_name):
        return None

    async def snapshot():
        return {"projectCount": 1}

    monkeypatch.setattr(fixture, "assert_owned_database", authority)
    monkeypatch.setattr(fixture, "read_fixture_signature", snapshot)

    with pytest.raises(RuntimeError, match="empty or exact"):
        await fixture.prepare(DATABASE)
