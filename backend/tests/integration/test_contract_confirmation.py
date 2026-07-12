from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from backend.repositories.contracts import ContractRepository
from backend.services.contracts import (
    ConfirmContracts,
    ContractConflict,
    ContractService,
    SaveContractDraft,
)
from backend.tests.integration.test_contract_drafts import (
    BINDING,
    CARD,
    ENGINE,
    PROJECT,
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
