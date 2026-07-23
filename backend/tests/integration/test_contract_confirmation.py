from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest
from pymysql.err import IntegrityError

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS, BindingItem, BindingRevision
from backend.domain.seeds import SeedPayload
from backend.http_errors import ProjectArchived
from backend.repositories.bibles import BibleRepository
from backend.repositories.contracts import ContractRepository
from backend.repositories.seeds import SeedRepository
from backend.services.bibles import BibleService, SaveBibleDraft
from backend.services.contracts import (
    AssetRevisionRef,
    ConfirmContracts,
    ContractConflict,
    ContractDraftInput,
    ContractHistoryPage,
    ContractNotFound,
    ContractPreconditionFailed,
    ContractService,
    CorpusSourceRef,
    SaveContractDraft,
)
from backend.services.seeds import CreateSeed, SeedService, SelectSeed
from backend.tests.support.contract_fakes import SEED_PAYLOAD, style_asset
from backend.tests.integration.test_contract_drafts import (
    BINDING,
    CARD,
    CHAPTER,
    ENGINE,
    FRAGMENT,
    PROJECT,
    PROVIDER,
    SEED,
    SOURCE,
    SOURCE_REV,
    STYLE,
    _bootstrap,
    _draft,
)
from backend.tests.support.disposable_mysql import transaction_factory_for
from backend.tests.unit.test_bible_service import bible_payload


pytestmark = pytest.mark.mysql

FORMAL_TABLES = (
    "creation_contracts",
    "style_contracts",
    "creation_contract_engine_refs",
    "style_contract_template_refs",
    "creation_contract_experience_refs",
    "creation_contract_corpus_refs",
    "creation_contract_corpus_fragment_refs",
    "contract_confirmation_requests",
)


def _service(disposable_mysql, *, failpoint=lambda _stage: None):
    tx = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    ids = iter(
        f"83000000-0000-0000-0000-{number:012d}" for number in range(1, 500)
    )
    return ContractService(
        ContractRepository(), transaction_factory=tx,
        connection_factory=read_connection,
        id_factory=lambda: next(ids), clock=lambda: 1_900_000_000_300,
        failpoint=failpoint,
    )


def _seed_service(disposable_mysql):
    tx = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    return SeedService(
        SeedRepository(),
        transaction_factory=tx,
        connection_factory=read_connection,
        clock=lambda: 1_900_000_000_400,
    )


async def _saved(disposable_mysql, service):
    facts = await _bootstrap(disposable_mysql.session)
    saved = await service.save_draft(
        SaveContractDraft(PROJECT, 0, _draft(facts))
    )
    return facts, saved


def _confirm(saved, key="confirm-real", content_hash=None):
    return ConfirmContracts(
        PROJECT, key, saved.draft_version,
        content_hash or saved.content_hash,
    )


async def _count(session, table):
    row = await session.fetchone(f"SELECT COUNT(*) AS count FROM {table}")
    return int(row["count"])


@pytest.mark.asyncio
async def test_real_read_only_contract_assets_use_four_bulk_queries_for_many_refs(
    disposable_mysql,
):
    facts = await _bootstrap(disposable_mysql.session)
    now = 1_900_000_000_600
    secondary_style_id = "86000000-0000-0000-0000-000000000001"
    secondary_payload = style_asset(flavor="章回悬念")
    secondary_hash = canonical_hash(secondary_payload)
    await disposable_mysql.session.execute(
        """INSERT INTO style_templates
           (id,stable_key,revision,name,payload_json,provenance_json,content_hash,
            status,created_at)
           VALUES (%s,'bulk-secondary',1,'批量副风格',%s,'{}',%s,'active',%s)""",
        (
            secondary_style_id,
            canonical_json(secondary_payload),
            secondary_hash,
            now,
        ),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO style_template_heads
           (stable_key,style_template_id,revision,content_hash,updated_at)
           VALUES ('bulk-secondary',%s,1,%s,%s)""",
        (secondary_style_id, secondary_hash, now),
    )

    experience_ids = [CARD]
    corpus_refs = [(SOURCE, SOURCE_REV)]
    fragment_refs = [(SOURCE, SOURCE_REV, FRAGMENT)]
    for index in range(1, 6):
        suffix = f"{index:012d}"
        card_id = f"86000000-0000-0000-0001-{suffix}"
        card_key = f"bulk-card-{index}"
        card_payload = {
            "schemaVersion": "experience-card-v1",
            "rule": f"bulk-choice-{index}",
        }
        card_hash = canonical_hash(card_payload)
        await disposable_mysql.session.execute(
            """INSERT INTO experience_cards
               (id,stable_key,revision,title,category,payload_json,
                provenance_json,content_hash,status,created_at)
               VALUES (%s,%s,1,%s,'plot_organization',%s,'{}',%s,'active',%s)""",
            (
                card_id,
                card_key,
                f"批量经验 {index}",
                canonical_json(card_payload),
                card_hash,
                now + index,
            ),
        )
        await disposable_mysql.session.execute(
            """INSERT INTO experience_card_heads
               (stable_key,experience_card_id,revision,content_hash,updated_at)
               VALUES (%s,%s,1,%s,%s)""",
            (card_key, card_id, card_hash, now + index),
        )
        experience_ids.append(card_id)

        source_id = f"86000000-0000-0000-0002-{suffix}"
        revision_id = f"86000000-0000-0000-0003-{suffix}"
        chapter_id = f"86000000-0000-0000-0004-{suffix}"
        fragment_id = f"86000000-0000-0000-0005-{suffix}"
        source_hash = f"{index + 100:064x}"
        fragment_hash = f"{index + 200:064x}"
        await disposable_mysql.session.execute(
            """INSERT INTO corpus_blobs
               (content_hash,byte_length,storage_key,created_at)
               VALUES (%s,300,%s,%s)""",
            (source_hash, f"corpus/bulk-{index}", now + index),
        )
        await disposable_mysql.session.execute(
            """INSERT INTO corpus_sources
               (id,source_key,archived_at,created_at,updated_at)
               VALUES (%s,%s,NULL,%s,%s)""",
            (source_id, f"bulk-source-{index}", now + index, now + index),
        )
        await disposable_mysql.session.execute(
            """INSERT INTO corpus_source_revisions
               (id,source_id,revision,content_hash,relative_path,display_name,
                author,reference_tags_json,notes,provenance_json,byte_length,
                encoding,parser_version,normalizer_version,fragmenter_version,
                index_version,status,public_error_code,imported_at,analyzed_at,
                created_at)
               VALUES (%s,%s,1,%s,%s,%s,'作者','[]','','{}',300,'utf-8',
                       'p1','n1','f1','i1','analyzed',NULL,%s,%s,%s)""",
            (
                revision_id,
                source_id,
                source_hash,
                f"bulk-{index}.txt",
                f"批量语料 {index}",
                now + index,
                now + index,
                now + index,
            ),
        )
        await disposable_mysql.session.execute(
            """INSERT INTO corpus_source_heads
               (source_id,revision_id,revision,content_hash,updated_at)
               VALUES (%s,%s,1,%s,%s)""",
            (source_id, revision_id, source_hash, now + index),
        )
        await disposable_mysql.session.execute(
            """INSERT INTO corpus_chapters
               (id,corpus_source_id,source_revision_id,source_revision,
                source_hash,chapter_order,title,raw_byte_start,raw_byte_end,
                normalized_char_start,normalized_char_end,normalized_text,
                content_hash,created_at)
               VALUES (%s,%s,%s,1,%s,1,'第一章',0,300,0,300,%s,%s,%s)""",
            (
                chapter_id,
                source_id,
                revision_id,
                source_hash,
                "A" * 300,
                f"{index + 300:064x}",
                now + index,
            ),
        )
        await disposable_mysql.session.execute(
            """INSERT INTO corpus_fragments
               (id,corpus_source_id,corpus_chapter_id,fragment_order,
                chapter_char_start,chapter_char_end,normalized_text,
                content_hash,index_payload,analysis_version,created_at)
               VALUES (%s,%s,%s,1,0,300,%s,%s,'{}','analysis-v1',%s)""",
            (
                fragment_id,
                source_id,
                chapter_id,
                "A" * 300,
                fragment_hash,
                now + index,
            ),
        )
        corpus_refs.append((source_id, revision_id))
        fragment_refs.append((source_id, revision_id, fragment_id))

    class CountingSession:
        def __init__(self, delegate):
            self.delegate = delegate
            self.fetchall_count = 0

        async def fetchall(self, sql, args=None):
            self.fetchall_count += 1
            return await self.delegate.fetchall(sql, args)

    counting = CountingSession(disposable_mysql.session)
    repository = ContractRepository()
    result = await repository.read_contract_asset_references(
        counting,
        style_ids=(STYLE, secondary_style_id),
        experience_ids=tuple(experience_ids),
        corpus_revision_refs=tuple(corpus_refs),
        fragment_refs=tuple(fragment_refs),
    )

    assert counting.fetchall_count == 4
    assert {row["id"] for row in result["styles"]} == {
        STYLE,
        secondary_style_id,
    }
    assert {row["id"] for row in result["experiences"]} == set(experience_ids)
    assert {
        (row["id"], row["revision_id"])
        for row in result["corpora"]
    } == set(corpus_refs)
    assert {
        (
            row["source_id"],
            row["source_revision_id"],
            row["fragment_id"],
        )
        for row in result["fragments"]
    } == set(fragment_refs)
    assert all(
        row["source_hash"] in {
            facts["source_hash"],
            *(f"{index + 100:064x}" for index in range(1, 6)),
        }
        for row in result["corpora"]
    )

    empty = await repository.read_contract_asset_references(
        counting,
        style_ids=(),
        experience_ids=(),
        corpus_revision_refs=(),
        fragment_refs=(),
    )
    assert empty == {
        "styles": (),
        "experiences": (),
        "corpora": (),
        "fragments": (),
    }
    assert counting.fetchall_count == 4


@pytest.mark.asyncio
async def test_real_confirmation_freezes_exact_relations_and_replays(disposable_mysql):
    service = _service(disposable_mysql)
    facts, saved = await _saved(disposable_mysql, service)

    first = await service.confirm(_confirm(saved))
    replay = await service.confirm(_confirm(saved))

    assert replay == first
    assert first.revision == 1
    assert first.binding_ref.id == BINDING
    assert len(first.binding_ref.items) == 8
    assert first.engine_ref.id == ENGINE
    assert first.style_refs[0].id == STYLE
    assert first.experience_card_refs[0].id == CARD
    assert first.corpus_source_refs[0].id == SOURCE
    assert first.creation_hash == facts.get("creation_hash", first.creation_hash)
    head = await disposable_mysql.session.fetchone(
        "SELECT * FROM project_contract_heads WHERE project_id=%s", (PROJECT,)
    )
    assert head["revision"] == 1
    assert head["creation_contract_id"] == first.creation_contract_id
    assert head["style_contract_id"] == first.style_contract_id
    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM project_contract_drafts WHERE project_id=%s", (PROJECT,)
    ) is None
    assert await _count(disposable_mysql.session, "creation_contracts") == 1
    assert await _count(disposable_mysql.session, "style_contracts") == 1
    assert await _count(disposable_mysql.session, "creation_contract_engine_refs") == 1
    assert await _count(disposable_mysql.session, "style_contract_template_refs") == 1
    assert await _count(disposable_mysql.session, "creation_contract_experience_refs") == 1
    assert await _count(disposable_mysql.session, "creation_contract_corpus_refs") == 1
    assert await _count(
        disposable_mysql.session, "creation_contract_corpus_fragment_refs"
    ) == 1
    request = await disposable_mysql.session.fetchone(
        "SELECT * FROM contract_confirmation_requests WHERE project_id=%s",
        (PROJECT,),
    )
    assert request["status"] == "succeeded"
    assert request["result_revision"] == 1
    creation_row = await disposable_mysql.session.fetchone(
        """SELECT quality_charter_version,chapter_capacity_policy
             FROM creation_contracts WHERE project_id=%s""",
        (PROJECT,),
    )
    assert creation_row == {
        "quality_charter_version": saved.draft.qualityCharterVersion,
        "chapter_capacity_policy": canonical_json({
            "expectedVolumeCount": saved.draft.expectedVolumeCount,
            "expectedChapterCount": saved.draft.expectedChapterCount,
            "chapterWordRangePreference": list(
                saved.draft.chapterWordRangePreference
            ),
        }),
    }
    assert (await service.get_head(PROJECT)).revision == 1
    history_page = await service.history(PROJECT)
    assert tuple(item.revision for item in history_page.items) == (1,)
    assert history_page.next_before_revision is None

    with pytest.raises(ContractConflict):
        await service.confirm(_confirm(saved, content_hash="f" * 64))
    with pytest.raises(ContractConflict):
        await service.confirm(_confirm(saved, key="different-key"))

    cloned = await service.clone_revision(PROJECT, 1)
    revised = await service.save_draft(SaveContractDraft(
        PROJECT, cloned.draft_version, _draft(facts, likes=("第二版偏好",))
    ))
    second = await service.confirm(_confirm(revised, key="confirm-second"))
    history = (await service.history(PROJECT)).items
    old_replay = await service.confirm(_confirm(saved))
    assert second.revision == 2
    assert tuple(item.revision for item in history) == (2, 1)
    assert history[0].contract_ready is True
    assert history[0].superseded_reasons == ()
    assert history[1].contract_ready is False
    assert history[1].reasons == ("superseded",)
    assert history[1].superseded_reasons == ("contract_revision_replaced",)
    assert old_replay.creation_contract_id == first.creation_contract_id
    assert old_replay.creation_hash == first.creation_hash
    assert old_replay.contract_ready is False
    assert old_replay.reasons == ("superseded",)
    assert old_replay.superseded_reasons == ("contract_revision_replaced",)
    assert history[1].creation_contract == first.creation_contract
    assert history[1].style_contract == first.style_contract

    historical_clone = await service.clone_revision(PROJECT, 1)
    assert historical_clone.base_head_revision == 2
    assert historical_clone.draft_version == 1
    assert historical_clone.draft.likes == saved.draft.likes
    assert historical_clone.draft.likes != revised.draft.likes
    assert (await service.get_head(PROJECT)).revision == 2
    assert await _count(disposable_mysql.session, "creation_contracts") == 2


@pytest.mark.asyncio
async def test_real_history_pages_by_exclusive_revision_without_duplicates_or_gaps(
    disposable_mysql,
):
    service = _service(disposable_mysql)
    _, draft = await _saved(disposable_mysql, service)
    for revision in (1, 2, 3):
        await service.confirm(_confirm(draft, key=f"history-page-{revision}"))
        if revision < 3:
            draft = await service.clone_revision(PROJECT, revision)

    first = await service.history(PROJECT, limit=2)
    second = await service.history(
        PROJECT, limit=2, before_revision=first.next_before_revision
    )
    empty = await service.history(PROJECT, limit=2, before_revision=1)

    assert tuple(item.revision for item in first.items) == (3, 2)
    assert first.next_before_revision == 2
    assert tuple(item.revision for item in second.items) == (1,)
    assert second.next_before_revision is None
    assert empty == ContractHistoryPage(items=(), next_before_revision=None)


@pytest.mark.asyncio
async def test_real_archived_project_reads_confirmed_head_and_history_but_rejects_operations(
    disposable_mysql,
):
    service = _service(disposable_mysql)
    _, saved = await _saved(disposable_mysql, service)
    confirmed = await service.confirm(_confirm(saved, key="confirmed-before-archive"))
    await disposable_mysql.session.execute(
        "UPDATE projects SET archived_at=%s,lifecycle_revision=1 WHERE id=%s",
        (1_900_000_000_500, PROJECT),
    )
    counts = {
        table: await _count(disposable_mysql.session, table)
        for table in FORMAL_TABLES
    }

    assert await service.get_head(PROJECT) == confirmed
    assert await service.history(PROJECT) == ContractHistoryPage(
        items=(confirmed,), next_before_revision=None,
    )
    with pytest.raises(ContractNotFound):
        await service.preview(PROJECT)
    with pytest.raises(ProjectArchived):
        await service.confirm(_confirm(saved, key="confirmed-before-archive"))
    with pytest.raises(ProjectArchived):
        await service.clone_revision(PROJECT, confirmed.revision)

    assert {
        table: await _count(disposable_mysql.session, table)
        for table in FORMAL_TABLES
    } == counts
    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM project_contract_drafts WHERE project_id=%s", (PROJECT,)
    ) is None


@pytest.mark.parametrize(
    ("case", "field", "tampered", "relation_updates", "capacity_updates"),
    (
        ("selection", "selectionRevision", 2, {}, {}),
        ("channel", "channelProfileKey", "tampered-channel", {}, {}),
        ("genre", "genreProfileKey", "tampered-genre", {}, {}),
        ("charter", "qualityCharterVersion", "tampered-charter-v2", {}, {}),
        ("word-min", "targetTotalWords", 150_001,
         {"total_word_max": 150_001}, {}),
        ("word-max", "targetTotalWords", 149_999,
         {"total_word_min": 149_999}, {}),
        ("volumes", "expectedVolumeCount", 9, {}, {}),
        ("chapters", "expectedChapterCount", 401, {}, {}),
        ("chapter-range", "chapterWordRangePreference", [2_600, 3_600], {}, {}),
        ("capacity-extra", None, None, {}, {"unexpected": 1}),
    ),
)
@pytest.mark.asyncio
async def test_real_non_head_clone_rejects_creation_payload_relational_drift(
    disposable_mysql, case, field, tampered, relation_updates, capacity_updates,
):
    service = _service(disposable_mysql)
    _, first_draft = await _saved(disposable_mysql, service)
    await service.confirm(_confirm(first_draft, key=f"first-{case}"))
    second_draft = await service.clone_revision(PROJECT, 1)
    await service.confirm(_confirm(second_draft, key=f"second-{case}"))
    historical = await disposable_mysql.session.fetchone(
        """SELECT id,content_json,chapter_capacity_policy
             FROM creation_contracts WHERE project_id=%s AND revision=1""",
        (PROJECT,),
    )
    creation = json.loads(historical["content_json"])
    if field is not None:
        creation[field] = tampered
    await disposable_mysql.session.execute(
        "UPDATE creation_contracts SET content_json=%s,content_hash=%s WHERE id=%s",
        (canonical_json(creation), canonical_hash(creation), historical["id"]),
    )
    for column, value in relation_updates.items():
        await disposable_mysql.session.execute(
            f"UPDATE creation_contracts SET {column}=%s WHERE id=%s",
            (value, historical["id"]),
        )
    if capacity_updates:
        capacity = json.loads(historical["chapter_capacity_policy"])
        capacity.update(capacity_updates)
        await disposable_mysql.session.execute(
            "UPDATE creation_contracts SET chapter_capacity_policy=%s WHERE id=%s",
            (canonical_json(capacity), historical["id"]),
        )

    with pytest.raises(ContractPreconditionFailed):
        await service.clone_revision(PROJECT, 1)

    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM project_contract_drafts WHERE project_id=%s", (PROJECT,)
    ) is None


@pytest.mark.asyncio
async def test_real_non_head_clone_rejects_capacity_number_type_drift(
    disposable_mysql,
):
    service = _service(disposable_mysql)
    facts = await _bootstrap(disposable_mysql.session)
    values = _draft(facts).model_dump(mode="python")
    values["expectedVolumeCount"] = 8
    first_draft = await service.save_draft(SaveContractDraft(
        PROJECT, 0, ContractDraftInput(**values)
    ))
    await service.confirm(_confirm(first_draft, key="strict-number-first"))
    second_draft = await service.clone_revision(PROJECT, 1)
    await service.confirm(_confirm(second_draft, key="strict-number-second"))
    historical = await disposable_mysql.session.fetchone(
        """SELECT id,chapter_capacity_policy
             FROM creation_contracts WHERE project_id=%s AND revision=1""",
        (PROJECT,),
    )
    capacity = json.loads(historical["chapter_capacity_policy"])
    capacity["expectedVolumeCount"] = 8.0
    await disposable_mysql.session.execute(
        "UPDATE creation_contracts SET chapter_capacity_policy=%s WHERE id=%s",
        (canonical_json(capacity), historical["id"]),
    )

    with pytest.raises(ContractPreconditionFailed):
        await service.clone_revision(PROJECT, 1)

    assert await disposable_mysql.session.fetchone(
        "SELECT * FROM project_contract_drafts WHERE project_id=%s", (PROJECT,)
    ) is None


@pytest.mark.asyncio
async def test_real_confirmation_accepts_maximum_legal_capacity_values(
    disposable_mysql,
):
    service = _service(disposable_mysql)
    facts = await _bootstrap(disposable_mysql.session)
    values = _draft(facts).model_dump(mode="python")
    values.update({
        "targetTotalWords": 100_000_000,
        "expectedVolumeCount": 1_000,
        "expectedChapterCount": 100_000,
        "chapterWordRangePreference": (100_000, 100_000),
    })

    saved = await service.save_draft(SaveContractDraft(
        PROJECT, 0, ContractDraftInput(**values)
    ))
    preview = await service.preview(PROJECT)
    confirmed = await service.confirm(_confirm(saved, key="confirm-max-capacity"))
    creation_row = await disposable_mysql.session.fetchone(
        """SELECT total_word_min,total_word_max,chapter_capacity_policy
             FROM creation_contracts WHERE id=%s""",
        (confirmed.creation_contract_id,),
    )

    assert preview.contract_ready is True
    assert confirmed.contract_ready is True
    assert creation_row == {
        "total_word_min": 100_000_000,
        "total_word_max": 100_000_000,
        "chapter_capacity_policy": canonical_json({
            "expectedVolumeCount": 1_000,
            "expectedChapterCount": 100_000,
            "chapterWordRangePreference": [100_000, 100_000],
        }),
    }


@pytest.mark.asyncio
async def test_real_manual_confirmation_without_binding_is_nullable_and_replayable(
    disposable_mysql,
):
    service = _service(disposable_mysql)
    facts = await _bootstrap(disposable_mysql.session)
    await disposable_mysql.session.execute(
        "DELETE FROM project_model_binding_heads WHERE project_id=%s", (PROJECT,)
    )
    saved = await service.save_draft(SaveContractDraft(PROJECT, 0, _draft(facts)))

    first = await service.confirm(_confirm(saved, key="confirm-without-binding"))
    replay = await service.confirm(_confirm(saved, key="confirm-without-binding"))
    creation = await disposable_mysql.session.fetchone(
        """SELECT binding_revision_id,binding_hash FROM creation_contracts
           WHERE id=%s""",
        (first.creation_contract_id,),
    )

    assert saved.draft.modelBindingRef is None
    assert first == replay
    assert first.binding_ref is None
    assert first.creation_contract.modelBindingRef is None
    assert first.contract_ready is True
    assert creation == {"binding_revision_id": None, "binding_hash": None}
    assert await _count(
        disposable_mysql.session, "creation_contract_corpus_fragment_refs"
    ) == 1
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM project_contract_drafts WHERE project_id=%s", (PROJECT,)
    ) is None
    assert (await service.get_head(PROJECT)).contract_ready is True


@pytest.mark.parametrize(
    ("drift", "expected_reason"),
    (
        ("unknown", "corpus_fragment_missing"),
        ("hash", "corpus_fragment_invalid"),
        ("range", "corpus_fragment_invalid"),
    ),
)
@pytest.mark.asyncio
async def test_real_fragment_reference_rejects_unknown_hash_and_out_of_bounds(
    disposable_mysql, drift, expected_reason,
):
    service = _service(disposable_mysql)
    facts = await _bootstrap(disposable_mysql.session)
    fragment_id = FRAGMENT
    fragment_hash = facts["fragment_hash"]
    char_start, char_end = 10, 110
    if drift == "unknown":
        fragment_id = "82000000-0000-0000-0000-000000000099"
    elif drift == "hash":
        fragment_hash = "e" * 64
    else:
        char_start, char_end = 250, 350
    source_ref = CorpusSourceRef(
        id=SOURCE,
        revisionId=SOURCE_REV,
        revision=1,
        contentHash=facts["source_hash"],
        selectionMode="author",
        fragments=({
            "chapterId": CHAPTER,
            "fragmentId": fragment_id,
            "fragmentHash": fragment_hash,
            "chapterCharStart": char_start,
            "chapterCharEnd": char_end,
            "referenceUse": "style",
        },),
        pinnedHistoricalRevision=False,
    )
    saved = await service.save_draft(SaveContractDraft(
        PROJECT, 0, _draft(facts, corpus_source_refs=(source_ref,))
    ))

    preview = await service.preview(PROJECT)

    assert preview.contract_ready is False
    assert any(reason.startswith(expected_reason) for reason in preview.reasons)
    with pytest.raises(ContractConflict):
        await service.confirm(_confirm(saved, key=f"invalid-fragment-{drift}"))
    assert await _count(disposable_mysql.session, "creation_contracts") == 0
    assert await _count(
        disposable_mysql.session, "creation_contract_corpus_fragment_refs"
    ) == 0


@pytest.mark.asyncio
async def test_real_same_seed_reselection_supersedes_readiness_and_clone_generation(
    disposable_mysql,
):
    contract_service = _service(disposable_mysql)
    seed_service = _seed_service(disposable_mysql)
    _, saved = await _saved(disposable_mysql, contract_service)
    confirmed = await contract_service.confirm(_confirm(saved))
    assert confirmed.selection_revision == 1
    assert (await seed_service.get_selected(PROJECT)).seed_ready is True

    selection_two = await seed_service.select(
        SelectSeed(
            project_id=PROJECT,
            seed_id=SEED,
            expected_seed_revision=1,
            expected_selection_revision=1,
        )
    )
    readiness = await seed_service.get_selected(PROJECT)

    assert selection_two.selection_revision == 2
    assert readiness.seed_ready is False
    assert readiness.reasons == ("selected_seed_drift",)
    with pytest.raises(ContractConflict):
        await contract_service.clone_revision(PROJECT, 1)
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM project_contract_drafts WHERE project_id=%s",
        (PROJECT,),
    ) is None
    generations = await disposable_mysql.session.fetchall(
        """SELECT selection_revision,COUNT(*) AS contract_count
             FROM creation_contracts
            WHERE project_id=%s
            GROUP BY selection_revision
            ORDER BY selection_revision""",
        (PROJECT,),
    )
    assert generations == [{"selection_revision": 1, "contract_count": 1}]


@pytest.mark.asyncio
async def test_real_a_b_a_marks_old_contract_history_and_replay_superseded(
    disposable_mysql,
):
    contract_service = _service(disposable_mysql)
    seed_service = _seed_service(disposable_mysql)
    _, saved = await _saved(disposable_mysql, contract_service)
    first = await contract_service.confirm(_confirm(saved))
    seed_b = await seed_service.create(
        CreateSeed(
            project_id=PROJECT,
            payload=SeedPayload.model_validate({
                **SEED_PAYLOAD,
                "title": "B generation",
            }),
        )
    )
    selected_b = await seed_service.select(
        SelectSeed(
            project_id=PROJECT,
            seed_id=seed_b.id,
            expected_seed_revision=1,
            expected_selection_revision=1,
        )
    )
    selected_a = await seed_service.select(
        SelectSeed(
            project_id=PROJECT,
            seed_id=SEED,
            expected_seed_revision=1,
            expected_selection_revision=selected_b.selection_revision,
        )
    )

    historical = (await contract_service.history(PROJECT)).items
    replay = await contract_service.confirm(_confirm(saved))

    assert first.contract_ready is True
    assert selected_a.selection_revision == 3
    assert historical[0].contract_ready is False
    assert historical[0].reasons == ("superseded",)
    assert historical[0].superseded_reasons == ("selection_revision_changed",)
    assert replay.contract_ready is False
    assert replay.reasons == ("superseded",)
    assert replay.superseded_reasons == ("selection_revision_changed",)
    assert await disposable_mysql.session.fetchone(
        """SELECT revision,creation_contract_id
             FROM project_contract_heads WHERE project_id=%s""",
        (PROJECT,),
    ) == {
        "revision": 1,
        "creation_contract_id": first.creation_contract_id,
    }
    assert await _count(disposable_mysql.session, "creation_contracts") == 1


@pytest.mark.asyncio
async def test_real_same_seed_reselection_keeps_old_engine_draft_fail_closed(
    disposable_mysql,
):
    contract_service = _service(disposable_mysql)
    seed_service = _seed_service(disposable_mysql)
    _, initial = await _saved(disposable_mysql, contract_service)
    selection_two = await seed_service.select(
        SelectSeed(
            project_id=PROJECT,
            seed_id=SEED,
            expected_seed_revision=1,
            expected_selection_revision=1,
        )
    )

    preview = await contract_service.preview(PROJECT)

    assert selection_two.selection_revision == 2
    assert preview.contract_ready is False
    assert preview.reasons == ("selection_drift",)
    with pytest.raises(ContractConflict):
        await contract_service.confirm(
            _confirm(initial, key="old-engine-selection")
        )
    assert await disposable_mysql.session.fetchone(
        "SELECT revision FROM project_contract_heads WHERE project_id=%s",
        (PROJECT,),
    ) == {"revision": 0}
    assert await _count(disposable_mysql.session, "creation_contracts") == 0
    assert await _count(disposable_mysql.session, "contract_confirmation_requests") == 0


@pytest.mark.parametrize("drift", ("item_content", "item_hash", "aggregate_hash"))
@pytest.mark.asyncio
async def test_real_confirmation_rejects_any_binding_snapshot_drift(
    disposable_mysql, drift
):
    service = _service(disposable_mysql)
    _, saved = await _saved(disposable_mysql, service)

    if drift == "item_content":
        await disposable_mysql.session.execute(
            """UPDATE project_model_binding_items
               SET model_name_snapshot='tampered-model'
               WHERE binding_revision_id=%s AND task_key='writing'""",
            (BINDING,),
        )
    elif drift == "item_hash":
        await disposable_mysql.session.execute(
            """UPDATE project_model_binding_items SET item_hash=%s
               WHERE binding_revision_id=%s AND task_key='writing'""",
            ("f" * 64, BINDING),
        )
    else:
        with pytest.raises(IntegrityError):
            await disposable_mysql.session.execute(
                """UPDATE project_model_binding_revisions SET content_hash=%s
                   WHERE id=%s""",
                ("f" * 64, BINDING),
            )
        return

    with pytest.raises(ContractConflict):
        await service.confirm(_confirm(saved, key=f"binding-{drift}"))


@pytest.mark.parametrize(("table", "owner_column", "owner_id", "extra"), (
    ("style_contract_template_refs", "style_contract_id", "style_contract_id", " AND role='primary'"),
    ("creation_contract_experience_refs", "creation_contract_id", "creation_contract_id", ""),
    ("creation_contract_corpus_refs", "creation_contract_id", "creation_contract_id", ""),
))
@pytest.mark.asyncio
async def test_real_reads_fail_closed_when_a_confirmed_ref_projection_is_deleted(
    disposable_mysql, table, owner_column, owner_id, extra
):
    service = _service(disposable_mysql)
    _, saved = await _saved(disposable_mysql, service)
    confirmed = await service.confirm(_confirm(saved))
    owner = getattr(confirmed, owner_id)
    await disposable_mysql.session.execute(
        f"DELETE FROM {table} WHERE {owner_column}=%s{extra}",
        (owner,),
    )

    with pytest.raises(ContractPreconditionFailed):
        await service.get_head(PROJECT)
    with pytest.raises(ContractPreconditionFailed):
        await service.history(PROJECT)
    with pytest.raises(ContractPreconditionFailed):
        await service.clone_revision(PROJECT, 1)
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM project_contract_drafts WHERE project_id=%s", (PROJECT,)
    ) is None


@pytest.mark.asyncio
async def test_real_clone_rejects_tampered_reference_manifest_without_draft(
    disposable_mysql,
):
    service = _service(disposable_mysql)
    _, saved = await _saved(disposable_mysql, service)
    await service.confirm(_confirm(saved))
    await disposable_mysql.session.execute(
        """UPDATE creation_contracts SET reference_manifest_hash=%s
           WHERE project_id=%s""",
        ("f" * 64, PROJECT),
    )

    with pytest.raises(ContractPreconditionFailed):
        await service.clone_revision(PROJECT, 1)
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM project_contract_drafts WHERE project_id=%s", (PROJECT,)
    ) is None


@pytest.mark.asyncio
async def test_real_two_first_confirmations_have_exactly_one_winner(disposable_mysql):
    service = _service(disposable_mysql)
    _, saved = await _saved(disposable_mysql, service)

    outcomes = await asyncio.gather(
        service.confirm(_confirm(saved, key="first-a")),
        service.confirm(_confirm(saved, key="first-b")),
        return_exceptions=True,
    )

    assert sum(getattr(item, "revision", None) == 1 for item in outcomes) == 1
    assert sum(isinstance(item, ContractConflict) for item in outcomes) == 1
    assert await _count(disposable_mysql.session, "creation_contracts") == 1
    assert await _count(disposable_mysql.session, "contract_confirmation_requests") == 1


@pytest.mark.asyncio
async def test_real_reverse_cross_project_provider_and_asset_locks_finish_without_deadlock(
    disposable_mysql,
):
    await _bootstrap(disposable_mysql.session)
    project2 = "84000000-0000-0000-0000-000000000001"
    binding2 = "84000000-0000-0000-0000-000000000002"
    provider2 = "84000000-0000-0000-0000-000000000003"
    style2 = "84000000-0000-0000-0000-000000000004"
    now = 1_900_000_000_500
    await disposable_mysql.session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES (%s,'reverse locks','fantasy','test',100000,100,'drafting',0,%s,%s)""",
        (project2, now, now),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO provider_profiles
           (id,name,provider_type,model_name,base_url,api_key,enabled,sort_order,
            stream,max_context_tokens,max_output_tokens,temperature,top_p,
            supports_json,supports_streaming,notes,thinking,lifecycle_status,
            deleted_at,created_at,updated_at)
           VALUES (%s,'Provider Two','openai-compatible','model-two',
                   'https://test.invalid',
                   'test-only-key',1,2,1,100000,4096,0.7,0.9,1,1,'',NULL,
                   'active',NULL,%s,%s)""",
        (provider2, now, now),
    )

    async def install_binding(project_id, binding_id, reverse):
        items = tuple(BindingItem(
            task_key=task, resolution_status="bound",
            provider_id=(provider2 if (index % 2 == 0) ^ reverse else PROVIDER),
            provider_name_snapshot=(
                "Provider Two" if (index % 2 == 0) ^ reverse else "Contract Provider"
            ),
            model_name_snapshot=(
                "model-two" if (index % 2 == 0) ^ reverse else "test-model"
            ),
        ) for index, task in enumerate(TASK_KEYS))
        revision_hash = canonical_hash(BindingRevision(
            project_id=project_id, revision=1, items=items,
        ))
        if binding_id == BINDING:
            await disposable_mysql.session.execute(
                "DELETE FROM project_model_binding_heads WHERE project_id=%s",
                (project_id,),
            )
            await disposable_mysql.session.execute(
                "DELETE FROM project_model_binding_items WHERE binding_revision_id=%s",
                (binding_id,),
            )
            await disposable_mysql.session.execute(
                "UPDATE project_model_binding_revisions SET content_hash=%s WHERE id=%s",
                (revision_hash, binding_id),
            )
        else:
            await disposable_mysql.session.execute(
                """INSERT INTO project_model_binding_revisions
                   (id,project_id,revision,content_hash,source_project_id,created_at)
                   VALUES (%s,%s,1,%s,NULL,%s)""",
                (binding_id, project_id, revision_hash, now),
            )
        for item in items:
            await disposable_mysql.session.execute(
                """INSERT INTO project_model_binding_items
                   (binding_revision_id,task_key,resolution_status,provider_id,
                    provider_name_snapshot,model_name_snapshot,item_hash)
                   VALUES (%s,%s,'bound',%s,%s,%s,%s)""",
                (binding_id, item.task_key, item.provider_id,
                 item.provider_name_snapshot, item.model_name_snapshot,
                 canonical_hash(item)),
            )
        await disposable_mysql.session.execute(
            "INSERT INTO project_model_binding_heads VALUES (%s,1,%s,%s,%s)",
            (project_id, binding_id, revision_hash, now),
        )

    await install_binding(PROJECT, BINDING, False)
    await install_binding(project2, binding2, True)
    style_payload = style_asset(flavor="反向锁测试")
    style_hash = canonical_hash(style_payload)
    await disposable_mysql.session.execute(
        """INSERT INTO style_templates
           (id,stable_key,revision,name,payload_json,provenance_json,content_hash,
            status,created_at) VALUES (%s,'reverse-style',1,'Reverse Style',%s,
            '{}',%s,'active',%s)""",
        (style2, canonical_json(style_payload), style_hash, now),
    )
    await disposable_mysql.session.execute(
        "INSERT INTO style_template_heads VALUES ('reverse-style',%s,1,%s,%s)",
        (style2, style_hash, now),
    )

    tx = transaction_factory_for(disposable_mysql.connection_config)
    repository = ContractRepository()
    service = _service(disposable_mysql)

    async def lock_binding(project_id):
        async with tx() as session:
            await session.execute("SET SESSION innodb_lock_wait_timeout=2")
            return await repository.lock_binding_snapshot(session, project_id)

    binding_results = await asyncio.wait_for(asyncio.gather(
        lock_binding(PROJECT), lock_binding(project2),
    ), timeout=5)
    assert all(len(result["items"]) == 8 for result in binding_results)

    primary = AssetRevisionRef(id=STYLE, revision=1, contentHash=(
        await disposable_mysql.session.fetchone(
            "SELECT content_hash FROM style_templates WHERE id=%s", (STYLE,)
        )
    )["content_hash"])
    secondary = AssetRevisionRef(id=style2, revision=1, contentHash=style_hash)

    async def lock_assets(reverse):
        async with tx() as session:
            await session.execute("SET SESSION innodb_lock_wait_timeout=2")
            draft = SimpleNamespace(
                primaryStyleRef=secondary if reverse else primary,
                secondaryStyleRef=primary if reverse else secondary,
                experienceCardRefs=(), corpusSourceRefs=(),
            )
            return await service._lock_contract_assets(session, draft)

    asset_results = await asyncio.wait_for(asyncio.gather(
        lock_assets(False), lock_assets(True),
    ), timeout=5)
    assert tuple(result[0]["id"] for result in asset_results) == (STYLE, style2)


@pytest.mark.asyncio
async def test_real_bible_readiness_and_reverse_contract_confirmation_share_asset_lock_order(
    disposable_mysql,
):
    readiness_first_locked = asyncio.Event()
    release_readiness = asyncio.Event()
    confirmation_first_locked = asyncio.Event()

    class PausingReadinessRepository(ContractRepository):
        def __init__(self):
            self.paused = False

        async def _pause_after_first_asset_lock(self):
            if self.paused:
                return
            self.paused = True
            readiness_first_locked.set()
            await release_readiness.wait()

        async def read_style_revision(
            self,
            session,
            asset_id,
            *,
            lock=False,
        ):
            row = await super().read_style_revision(
                session,
                asset_id,
                lock=lock,
            )
            if lock:
                await self._pause_after_first_asset_lock()
            return row

        async def read_corpus_revision(
            self,
            session,
            source_id,
            revision_id,
            *,
            lock=False,
        ):
            row = await super().read_corpus_revision(
                session,
                source_id,
                revision_id,
                lock=lock,
            )
            if lock:
                await self._pause_after_first_asset_lock()
            return row

    class ObservingConfirmationRepository(ContractRepository):
        def __init__(self):
            self.observed = False

        def _observe_first_asset_lock(self):
            if self.observed:
                return
            self.observed = True
            confirmation_first_locked.set()

        async def read_style_revision(
            self,
            session,
            asset_id,
            *,
            lock=False,
        ):
            row = await super().read_style_revision(
                session,
                asset_id,
                lock=lock,
            )
            if lock:
                self._observe_first_asset_lock()
            return row

        async def read_corpus_revision(
            self,
            session,
            source_id,
            revision_id,
            *,
            lock=False,
        ):
            row = await super().read_corpus_revision(
                session,
                source_id,
                revision_id,
                lock=lock,
            )
            if lock:
                self._observe_first_asset_lock()
            return row

    setup_service = _service(disposable_mysql)
    facts, saved = await _saved(disposable_mysql, setup_service)
    await setup_service.confirm(_confirm(saved, key="readiness-lock-basis"))

    project2 = "85000000-0000-0000-0000-000000000001"
    seed2 = "85000000-0000-0000-0000-000000000002"
    seed_revision2 = "85000000-0000-0000-0000-000000000003"
    batch2 = "85000000-0000-0000-0000-000000000004"
    engine2 = "85000000-0000-0000-0000-000000000005"
    now = 1_900_000_000_600
    await disposable_mysql.session.execute(
        """INSERT INTO projects
           (id,title,genre,description,target_words,target_chapters,status,
            current_chapter,created_at,updated_at)
           VALUES (%s,'reverse Bible readiness','fantasy','test',100000,100,
                   'drafting',0,%s,%s)""",
        (project2, now, now),
    )
    await disposable_mysql.session.execute(
        "INSERT INTO creative_seeds VALUES (%s,%s,'candidate',%s,%s)",
        (seed2, project2, now, now),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO creative_seed_revisions
           (id,project_id,seed_id,revision,payload_json,content_hash,created_at)
           VALUES (%s,%s,%s,1,%s,%s,%s)""",
        (
            seed_revision2,
            project2,
            seed2,
            canonical_json(SEED_PAYLOAD),
            facts["seed_hash"],
            now,
        ),
    )
    await disposable_mysql.session.execute(
        "INSERT INTO creative_seed_heads VALUES (%s,%s,1,%s,%s)",
        (seed2, seed_revision2, facts["seed_hash"], now),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO project_seed_selection_revisions
           (project_id,selection_revision,seed_id,seed_revision_id,seed_hash,selected_at)
           VALUES (%s,1,%s,%s,%s,%s)""",
        (project2, seed2, seed_revision2, facts["seed_hash"], now),
    )
    await disposable_mysql.session.execute(
        "INSERT INTO project_selected_seeds VALUES (%s,%s,%s,%s,1,%s,%s)",
        (project2, seed2, seed_revision2, facts["seed_hash"], now, now),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO story_engine_batches
           (id,project_id,selection_revision,source_type,seed_id,seed_revision_id,seed_hash,
            binding_revision_id,binding_hash,provider_id,model_name_snapshot,
            idempotency_key,request_json,request_hash,status,attempt_id,
            attempt_started_at,lease_expires_at,raw_response_text,
            raw_response_hash,public_error_code,created_at,finished_at)
           VALUES (%s,%s,1,'manual',%s,%s,%s,NULL,NULL,NULL,NULL,
                   'reverse-lock-manual','{}',%s,'succeeded',NULL,NULL,NULL,
                   NULL,NULL,NULL,%s,%s)""",
        (
            batch2,
            project2,
            seed2,
            seed_revision2,
            facts["seed_hash"],
            "b" * 64,
            now,
            now,
        ),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO story_engine_options
           (id,project_id,selection_revision,batch_id,option_order,payload_json,
            content_hash,created_at)
           SELECT %s,%s,1,%s,1,payload_json,content_hash,%s
             FROM story_engine_options WHERE id=%s""",
        (engine2, project2, batch2, now, ENGINE),
    )
    await disposable_mysql.session.execute(
        "INSERT INTO project_contract_heads VALUES (%s,0,NULL,NULL,NULL,NULL,%s)",
        (project2, now),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO project_bible_heads
           (project_id,revision,bible_revision_id,content_hash,updated_at)
           VALUES (%s,0,NULL,NULL,%s)""",
        (PROJECT, now),
    )
    reverse_draft = _draft(
        facts,
        experience_card_refs=(),
    ).model_copy(update={"engineOptionId": engine2})
    saved2 = await setup_service.save_draft(
        SaveContractDraft(project2, 0, reverse_draft)
    )

    tx = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    def contract_with_repository(repository, prefix):
        ids = iter(
            f"{prefix}-0000-0000-0000-{number:012d}"
            for number in range(1, 100)
        )
        return ContractService(
            repository,
            transaction_factory=tx,
            connection_factory=read_connection,
            id_factory=lambda: next(ids),
            clock=lambda: now,
        )

    readiness_contracts = contract_with_repository(
        PausingReadinessRepository(),
        "86000000",
    )
    confirming_contracts = contract_with_repository(
        ObservingConfirmationRepository(),
        "87000000",
    )
    bible_ids = iter(
        f"88000000-0000-0000-0000-{number:012d}"
        for number in range(1, 100)
    )
    bible = BibleService(
        BibleRepository(),
        contract_service=readiness_contracts,
        transaction_factory=tx,
        id_factory=lambda: next(bible_ids),
        clock=lambda: now,
    )

    bible_task = asyncio.create_task(
        bible.save_draft(SaveBibleDraft(PROJECT, 0, bible_payload()))
    )
    try:
        await asyncio.wait_for(readiness_first_locked.wait(), timeout=1)
    except BaseException:
        release_readiness.set()
        bible_task.cancel()
        await asyncio.gather(bible_task, return_exceptions=True)
        raise

    confirmation_task = asyncio.create_task(
        confirming_contracts.confirm(
            ConfirmContracts(
                project2,
                "reverse-bible-contract-locks",
                saved2.draft_version,
                saved2.content_hash,
            )
        )
    )
    try:
        try:
            await asyncio.wait_for(
                confirmation_first_locked.wait(),
                timeout=0.25,
            )
            confirmation_reached_first_asset = True
        except TimeoutError:
            confirmation_reached_first_asset = False
    finally:
        release_readiness.set()

    outcomes = await asyncio.wait_for(
        asyncio.gather(
            bible_task,
            confirmation_task,
            return_exceptions=True,
        ),
        timeout=5,
    )
    errors = [result for result in outcomes if isinstance(result, BaseException)]
    assert errors == []
    assert confirmation_reached_first_asset is False
    assert outcomes[0].draft_version == 1
    assert outcomes[1].revision == 1


@pytest.mark.parametrize("stage", (
    "after_confirmation_reserve", "after_creation_insert", "after_style_insert",
        "after_engine_refs", "after_style_refs", "after_card_refs",
        "after_corpus_refs", "after_corpus_fragment_refs", "after_head_cas",
        "after_draft_delete",
    "before_request_success",
))
@pytest.mark.asyncio
async def test_real_every_failpoint_rolls_back_request_contract_refs_head_and_delete(
    disposable_mysql, stage
):
    def failpoint(current):
        if current == stage:
            raise RuntimeError(stage)

    service = _service(disposable_mysql, failpoint=failpoint)
    _, saved = await _saved(disposable_mysql, service)

    with pytest.raises(RuntimeError, match=stage):
        await service.confirm(_confirm(saved))

    for table in FORMAL_TABLES:
        assert await _count(disposable_mysql.session, table) == 0
    head = await disposable_mysql.session.fetchone(
        "SELECT revision FROM project_contract_heads WHERE project_id=%s",
        (PROJECT,),
    )
    assert head["revision"] == 0
    draft = await disposable_mysql.session.fetchone(
        "SELECT draft_version,content_hash FROM project_contract_drafts WHERE project_id=%s",
        (PROJECT,),
    )
    assert draft == {
        "draft_version": saved.draft_version,
        "content_hash": saved.content_hash,
    }
