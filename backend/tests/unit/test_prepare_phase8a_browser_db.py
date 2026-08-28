import asyncio
from copy import deepcopy
from hashlib import sha256
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
    expected = fixture.fixture_signature()
    assert [item["title"] for item in expected["projects"]] == list(fixture.PROJECT_TITLES.values())
    assert expected["finalCounts"] == [3, 3, 3]
    assert expected["authoritativeChapters"] == [4, 4, 4]
    assert expected["outlineGoals"] == [[item.chapter_goal for item in fixture.PINNED_OUTLINES]] * 3
    for project_outlines in expected["outlines"]:
        for outline in project_outlines:
            assert outline["schemaVersion"] == "chapter-outline-v1"
            assert outline["hashMatches"] is True
            for field in ("volumeRef", "storyBlockRef"):
                assert set(outline["content"][field]) == {"id", "revision", "contentHash"}
            for field in ("stageRefs", "sceneTaskRefs"):
                assert len(outline["content"][field]) == 1
                assert set(outline["content"][field][0]) == {"id", "revision", "contentHash"}
    assert expected["sentinelCounts"] == {"working": 3, "candidate": 3}
    assert expected["corruptHashMismatch"] is True
    assert expected["finalChapters"][2][2]["storedHash"] == sha256(fixture.FINAL_PROSE[2].encode("utf-8")).hexdigest()
    assert expected["awaitingAuthorReviews"] == [{
        "projectId": fixture.PROJECTS["awaiting-author"],
        "chapter": 4,
        "status": "awaiting_author",
    }]
    postcondition = fixture.postcondition_signature()
    assert postcondition["finalCounts"] == [3, 4, 3]
    assert postcondition["lifecycles"] == ["archived", "active", "active"]
    assert postcondition["awaitingAuthorReviews"] == []


@pytest.mark.parametrize("name", ["novel_creator", "novel_creater", "../" + DATABASE])
def test_fixture_rejects_every_non_disposable_schema(name):
    with pytest.raises(RuntimeError, match="disposable"):
        fixture.assert_database_name(name)


def test_fixture_uses_local_deterministic_finalization_and_has_no_schema_ddl():
    source = open(fixture.__file__, encoding="utf-8").read()
    assert "ProviderMustNotRun" not in source
    assert "quality_provider=_Quality()" in source
    assert "extraction_provider=_Extraction(title)" in source
    assert "prepare_product_shell_browser_db" not in source
    assert not re.search(r"\b(?:CREATE|DROP)\s+(?:DATABASE|SCHEMA)\b", source, re.I)
    assert not re.search(r"ProviderProfileService|httpx|requests|aiohttp", source)


def test_outline_hash_verifier_rejects_changed_content_with_the_stored_hash_unchanged():
    payload = deepcopy(fixture.fixture_signature()["outlines"][0][0]["content"])
    payload.update({"chapterNumber": 1, "canonRevision": 0, "projectionRevision": 0})
    stored_hash = fixture.canonical_hash(payload)
    persisted = {**payload, "contentHash": stored_hash}
    assert fixture.outline_hash_matches(persisted, stored_hash) is True
    persisted["volumeRef"]["id"] = "tampered-pin"
    assert fixture.outline_hash_matches(persisted, stored_hash) is False


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


@pytest.mark.asyncio
@pytest.mark.parametrize("field", [
    "title", "outline", "sentinel", "hash", "pin-id", "pin-revision", "pin-hash",
    "outline-content-with-stale-hash",
])
async def test_prepare_refuses_a_fixture_with_corrupted_authority(monkeypatch, field):
    observed = deepcopy(fixture.fixture_signature())
    if field == "title":
        observed["projects"][0]["title"] = "错误标题"
    elif field == "outline":
        observed["outlineGoals"][0][0] = "错误小纲"
    elif field == "sentinel":
        observed["sentinelCounts"]["working"] = 0
    elif field == "hash":
        observed["corruptHashMismatch"] = False
    elif field == "pin-id":
        observed["outlines"][0][0]["content"]["volumeRef"]["id"] = "wrong-pin"
    elif field == "pin-revision":
        observed["outlines"][1][1]["content"]["storyBlockRef"]["revision"] += 1
    elif field == "pin-hash":
        observed["outlines"][2][2]["content"]["stageRefs"][0]["contentHash"] = "0" * 64
    else:
        observed["outlines"][0][0]["content"]["chapterGoal"] = "被篡改的小纲"
        observed["outlines"][0][0]["hashMatches"] = False

    monkeypatch.setattr(fixture, "assert_owned_database", lambda _database: asyncio.sleep(0))
    monkeypatch.setattr(fixture, "read_fixture_signature", lambda: asyncio.sleep(0, result=observed))

    with pytest.raises(RuntimeError, match="empty or exact"):
        await fixture.prepare(DATABASE)
