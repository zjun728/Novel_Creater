from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from backend.domain.json_contracts import canonical_hash
from backend.repositories.bibles import BibleRepository
from backend.services.bibles import (
    BibleConfirmationFailed,
    BibleConflict,
    BibleService,
    CloneBibleDraft,
    ConfirmBible,
    SaveBibleDraft,
)
from backend.tests.integration.test_contract_confirmation import (
    _confirm as confirm_contract,
    _saved as saved_contract,
    _service as contract_service,
)
from backend.tests.support.disposable_mysql import transaction_factory_for
from backend.tests.unit.test_bible_service import bible_payload


pytestmark = pytest.mark.mysql


def bible_service(
    disposable_mysql,
    contracts,
    *,
    failpoint=lambda _stage: None,
    service_class=BibleService,
):
    tx = transaction_factory_for(disposable_mysql.connection_config)

    @asynccontextmanager
    async def read_connection():
        yield disposable_mysql.session

    ids = iter(
        f"91000000-0000-0000-0000-{number:012d}"
        for number in range(1, 100)
    )
    return service_class(
        BibleRepository(),
        contract_service=contracts,
        transaction_factory=tx,
        connection_factory=read_connection,
        id_factory=lambda: next(ids),
        clock=lambda: 1_900_000_000_700,
        failpoint=failpoint,
    )


async def confirmed_contract_basis(disposable_mysql):
    contracts = contract_service(disposable_mysql)
    _, draft = await saved_contract(disposable_mysql, contracts)
    await disposable_mysql.session.execute(
        """INSERT INTO project_bible_heads
           (project_id,revision,bible_revision_id,content_hash,updated_at)
           VALUES (%s,0,NULL,NULL,%s)""",
        (draft.project_id, 1_900_000_000_650),
    )
    confirmed = await contracts.confirm(confirm_contract(draft))
    assert confirmed.contract_ready is True
    return contracts, confirmed


async def count(session, table):
    row = await session.fetchone(f"SELECT COUNT(*) AS count FROM {table}")
    return int(row["count"])


@pytest.mark.asyncio
async def test_real_bible_confirmation_freezes_revision_advances_head_and_replays(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    service = bible_service(disposable_mysql, contracts)
    saved = await service.save_draft(
        SaveBibleDraft(
            contract.project_id,
            0,
            bible_payload(),
        )
    )
    command = ConfirmBible(
        contract.project_id,
        "real-bible-confirm-1",
        saved.draft_version,
        0,
    )

    first = await service.confirm(command)
    replay = await service.confirm(command)

    assert replay == first
    assert first.revision == 1
    assert first.basis.selection_revision == contract.selection_revision
    assert first.basis.creation_contract_id == contract.creation_contract_id
    assert first.basis.creation_hash == contract.creation_hash
    assert first.basis.style_contract_id == contract.style_contract_id
    assert first.basis.style_hash == contract.style_hash
    assert first.basis.binding_revision_id is None
    assert first.basis.binding_hash is None
    assert await count(disposable_mysql.session, "creation_bible_revisions") == 1
    assert await count(disposable_mysql.session, "bible_confirmation_requests") == 1
    head = await disposable_mysql.session.fetchone(
        "SELECT * FROM project_bible_heads WHERE project_id=%s",
        (contract.project_id,),
    )
    request = await disposable_mysql.session.fetchone(
        """SELECT selection_revision,contract_revision,creation_contract_id,
                  creation_hash,style_contract_id,style_hash,draft_id,
                  draft_version,draft_hash,status,result_revision,result_hash
             FROM bible_confirmation_requests
            WHERE project_id=%s AND idempotency_key=%s""",
        (contract.project_id, command.idempotency_key),
    )
    draft = await disposable_mysql.session.fetchone(
        "SELECT active_slot FROM project_bible_drafts WHERE id=%s",
        (saved.draft_id,),
    )
    assert head["revision"] == 1
    assert head["bible_revision_id"] == first.bible_revision_id
    assert head["content_hash"] == first.content_hash
    assert draft == {"active_slot": None}
    assert request == {
        "selection_revision": saved.basis.selection_revision,
        "contract_revision": saved.basis.contract_revision,
        "creation_contract_id": saved.basis.creation_contract_id,
        "creation_hash": saved.basis.creation_hash,
        "style_contract_id": saved.basis.style_contract_id,
        "style_hash": saved.basis.style_hash,
        "draft_id": saved.draft_id,
        "draft_version": saved.draft_version,
        "draft_hash": saved.content_hash,
        "status": "succeeded",
        "result_revision": first.revision,
        "result_hash": first.content_hash,
    }
    with pytest.raises(BibleConflict):
        await service.confirm(
            ConfirmBible(
                contract.project_id,
                command.idempotency_key,
                saved.draft_version,
                1,
            )
        )


@pytest.mark.asyncio
async def test_real_adjustment_creates_new_draft_and_keeps_both_immutable_revisions(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    service = bible_service(disposable_mysql, contracts)
    first_draft = await service.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    first = await service.confirm(
        ConfirmBible(
            contract.project_id,
            "real-bible-first",
            first_draft.draft_version,
            0,
        )
    )

    cloned = await service.clone_draft(
        CloneBibleDraft(contract.project_id, source_revision=1)
    )
    updated = await service.save_draft(
        SaveBibleDraft(
            contract.project_id,
            cloned.draft_version,
            bible_payload(
                protagonist="后续版本将让主角以更谨慎的方式承担未来代价。"
            ),
        )
    )
    second = await service.confirm(
        ConfirmBible(
            contract.project_id,
            "real-bible-second",
            updated.draft_version,
            1,
        )
    )
    page = await service.history(contract.project_id, limit=1)
    next_page = await service.history(
        contract.project_id,
        limit=1,
        before_revision=page.next_before_revision,
    )
    rows = await disposable_mysql.session.fetchall(
        """SELECT revision,content_hash,content_json
             FROM creation_bible_revisions
            WHERE project_id=%s ORDER BY revision""",
        (contract.project_id,),
    )

    assert first.revision == 1
    assert second.revision == 2
    assert first.content_hash != second.content_hash
    assert tuple(item.revision for item in page.items) == (2,)
    assert page.next_before_revision == 2
    assert tuple(item.revision for item in next_page.items) == (1,)
    assert next_page.next_before_revision is None
    assert [row["content_hash"] for row in rows] == [
        first.content_hash,
        second.content_hash,
    ]


@pytest.mark.asyncio
async def test_real_confirmation_failure_rolls_back_main_writes_and_is_replayable(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    service = bible_service(
        disposable_mysql,
        contracts,
        failpoint=lambda stage: (
            (_ for _ in ()).throw(RuntimeError("real rollback sentinel"))
            if stage == "after_request_reserve"
            else None
        ),
    )
    saved = await service.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )

    command = ConfirmBible(
        contract.project_id,
        "real-bible-rollback",
        saved.draft_version,
        0,
    )
    with pytest.raises(BibleConfirmationFailed):
        await service.confirm(command)

    writes = await count(disposable_mysql.session, "bible_confirmation_requests")
    with pytest.raises(BibleConfirmationFailed):
        await service.confirm(command)
    with pytest.raises(BibleConflict):
        await service.confirm(
            ConfirmBible(
                contract.project_id,
                command.idempotency_key,
                saved.draft_version,
                1,
            )
        )

    head = await disposable_mysql.session.fetchone(
        "SELECT revision FROM project_bible_heads WHERE project_id=%s",
        (contract.project_id,),
    )
    draft = await disposable_mysql.session.fetchone(
        """SELECT active_slot,draft_version,content_hash
             FROM project_bible_drafts WHERE id=%s""",
        (saved.draft_id,),
    )
    visible_draft = await service.get_draft(contract.project_id)
    request = await disposable_mysql.session.fetchone(
        """SELECT draft_id,draft_version,draft_hash,status,
                  public_error_code,result_revision,result_hash
             FROM bible_confirmation_requests
            WHERE project_id=%s AND idempotency_key=%s""",
        (contract.project_id, command.idempotency_key),
    )
    assert head == {"revision": 0}
    assert draft == {
        "active_slot": 1,
        "draft_version": saved.draft_version,
        "content_hash": saved.content_hash,
    }
    assert visible_draft.status == "current"
    assert visible_draft.can_edit is visible_draft.can_confirm is True
    assert visible_draft.can_clone is False
    assert await count(disposable_mysql.session, "creation_bible_revisions") == 0
    assert writes == 1
    assert await count(disposable_mysql.session, "bible_confirmation_requests") == 1
    assert request == {
        "draft_id": saved.draft_id,
        "draft_version": saved.draft_version,
        "draft_hash": saved.content_hash,
        "status": "failed",
        "public_error_code": "BibleConfirmationFailed",
        "result_revision": None,
        "result_hash": None,
    }


@pytest.mark.asyncio
async def test_failure_settlement_never_overwrites_a_concurrent_success(
    disposable_mysql,
):
    settlement_started = asyncio.Event()
    allow_settlement = asyncio.Event()

    class DelayedSettlementBibleService(BibleService):
        async def _settle_confirmation_failure(self, context):
            settlement_started.set()
            await allow_settlement.wait()
            return await super()._settle_confirmation_failure(context)

    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    failing = bible_service(
        disposable_mysql,
        contracts,
        failpoint=lambda stage: (
            (_ for _ in ()).throw(RuntimeError("settlement race sentinel"))
            if stage == "after_request_reserve"
            else None
        ),
        service_class=DelayedSettlementBibleService,
    )
    succeeding = bible_service(disposable_mysql, contracts)
    saved = await failing.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    command = ConfirmBible(
        contract.project_id,
        "real-bible-settlement-race",
        saved.draft_version,
        0,
    )

    failing_task = asyncio.create_task(failing.confirm(command))
    try:
        await asyncio.wait_for(settlement_started.wait(), timeout=1)
    except BaseException:
        failing_task.cancel()
        await asyncio.gather(failing_task, return_exceptions=True)
        raise
    succeeded = await succeeding.confirm(command)
    allow_settlement.set()
    replay = await failing_task

    request = await disposable_mysql.session.fetchone(
        """SELECT status,bible_revision_id,result_revision,result_hash,
                  public_error_code
             FROM bible_confirmation_requests
            WHERE project_id=%s AND idempotency_key=%s""",
        (contract.project_id, command.idempotency_key),
    )
    assert replay == succeeded
    assert request == {
        "status": "succeeded",
        "bible_revision_id": succeeded.bible_revision_id,
        "result_revision": succeeded.revision,
        "result_hash": succeeded.content_hash,
        "public_error_code": None,
    }


@pytest.mark.asyncio
async def test_real_failed_request_replays_without_touching_the_editable_draft(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    service = bible_service(disposable_mysql, contracts)
    saved = await service.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    command = ConfirmBible(
        contract.project_id,
        "real-bible-failed",
        saved.draft_version,
        0,
    )
    request_hash = canonical_hash(
        {
            "projectId": contract.project_id,
            "draftId": saved.draft_id,
            "draftVersion": saved.draft_version,
            "draftHash": saved.content_hash,
            "expectedHeadRevision": 0,
        }
    )
    await disposable_mysql.session.execute(
        """INSERT INTO bible_confirmation_requests
           (id,project_id,selection_revision,contract_revision,
            creation_contract_id,creation_hash,style_contract_id,style_hash,
            draft_id,draft_version,draft_hash,idempotency_key,request_hash,
            status,bible_revision_id,result_revision,result_hash,
            public_error_code,created_at,completed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'failed',
                   NULL,NULL,NULL,'BibleConfirmationFailed',%s,%s)""",
        (
            "92000000-0000-0000-0000-000000000001",
            contract.project_id,
            saved.basis.selection_revision,
            saved.basis.contract_revision,
            saved.basis.creation_contract_id,
            saved.basis.creation_hash,
            saved.basis.style_contract_id,
            saved.basis.style_hash,
            saved.draft_id,
            saved.draft_version,
            saved.content_hash,
            command.idempotency_key,
            request_hash,
            1_900_000_000_700,
            1_900_000_000_701,
        ),
    )

    with pytest.raises(BibleConfirmationFailed):
        await service.confirm(command)
    with pytest.raises(BibleConfirmationFailed):
        await service.confirm(command)

    draft = await disposable_mysql.session.fetchone(
        "SELECT active_slot,draft_version FROM project_bible_drafts WHERE id=%s",
        (saved.draft_id,),
    )
    assert draft == {"active_slot": 1, "draft_version": saved.draft_version}
    assert await count(disposable_mysql.session, "creation_bible_revisions") == 0
