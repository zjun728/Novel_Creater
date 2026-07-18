from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from pymysql.err import IntegrityError

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS, BindingItem, BindingRevision
from backend.repositories.contracts import ContractRepository
from backend.repositories.seeds import SeedRepository
from backend.services.contracts import (
    AssetRevisionRef,
    ConfirmContracts,
    ContractConflict,
    ContractPreconditionFailed,
    ContractService,
    SaveContractDraft,
)
from backend.services.seeds import SeedService, SelectSeed
from backend.tests.support.contract_fakes import style_asset
from backend.tests.integration.test_contract_drafts import (
    BINDING,
    CARD,
    ENGINE,
    PROJECT,
    PROVIDER,
    SEED,
    SOURCE,
    STYLE,
    _bootstrap,
    _draft,
)
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = pytest.mark.mysql

FORMAL_TABLES = (
    "creation_contracts",
    "style_contracts",
    "creation_contract_engine_refs",
    "style_contract_template_refs",
    "creation_contract_experience_refs",
    "creation_contract_corpus_refs",
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
        "chapter_capacity_policy": saved.draft.chapterCapacityPolicy,
    }
    assert (await service.get_head(PROJECT)).revision == 1
    assert tuple(item.revision for item in await service.history(PROJECT)) == (1,)

    with pytest.raises(ContractConflict):
        await service.confirm(_confirm(saved, content_hash="f" * 64))
    with pytest.raises(ContractConflict):
        await service.confirm(_confirm(saved, key="different-key"))

    cloned = await service.clone_current(PROJECT)
    second = await service.confirm(_confirm(cloned, key="confirm-second"))
    history = await service.history(PROJECT)
    old_replay = await service.confirm(_confirm(saved))
    assert second.revision == 2
    assert tuple(item.revision for item in history) == (2, 1)
    assert old_replay == first
    assert history[1].creation_contract == first.creation_contract
    assert history[1].style_contract == first.style_contract


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
        await contract_service.clone_current(PROJECT)
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
    assert preview.reasons == ("seed_drift",)
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
        await service.clone_current(PROJECT)
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
        await service.clone_current(PROJECT)
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


@pytest.mark.parametrize("stage", (
    "after_confirmation_reserve", "after_creation_insert", "after_style_insert",
    "after_engine_refs", "after_style_refs", "after_card_refs",
    "after_corpus_refs", "after_head_cas", "after_draft_delete",
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
