from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from backend.domain.json_contracts import canonical_hash
from backend.http_errors import PublicDomainError
from backend.repositories.bibles import BibleRepository
from backend.services.bibles import (
    BibleConfirmationFailed,
    BibleConflict,
    BiblePreconditionFailed,
    BibleService,
    CloneBibleDraft,
    ConfirmBible,
    SaveBibleDraft,
)
from backend.services.bible_generation import (
    BibleGenerationRetryable,
    BibleGenerationService,
    GenerateBibleDraft,
)
from backend.tests.integration.test_contract_confirmation import (
    _confirm as confirm_contract,
    _saved as saved_contract,
    _service as contract_service,
)
from backend.tests.integration.test_contract_drafts import SOURCE
from backend.tests.support.disposable_mysql import transaction_factory_for
from backend.tests.unit.test_bible_service import bible_payload


pytestmark = pytest.mark.mysql


def bible_service(
    disposable_mysql,
    contracts,
    *,
    failpoint=lambda _stage: None,
    service_class=BibleService,
    repository=None,
):
    tx = transaction_factory_for(disposable_mysql.connection_config)

    ids = iter(
        f"91000000-0000-0000-0000-{number:012d}"
        for number in range(1, 100)
    )
    return service_class(
        repository or BibleRepository(),
        contract_service=contracts,
        transaction_factory=tx,
        id_factory=lambda: next(ids),
        clock=lambda: 1_900_000_000_700,
        failpoint=failpoint,
    )


class PausingReadBibleRepository(BibleRepository):
    def __init__(self):
        self.pause_method = None
        self.observed = asyncio.Event()
        self.release = asyncio.Event()

    def arm(self, method):
        self.pause_method = method

    async def _pause(self, method):
        if self.pause_method != method:
            return
        self.pause_method = None
        self.observed.set()
        await self.release.wait()

    async def read_bible_head(self, session, project_id):
        row = await super().read_bible_head(session, project_id)
        await self._pause("head")
        return row

    async def read_active_draft(self, session, project_id):
        row = await super().read_active_draft(session, project_id)
        await self._pause("active-draft")
        return row


class FailingSettlementBibleRepository(BibleRepository):
    def __init__(self):
        self.fail_failed_request_insert = True

    async def insert_failed_confirmation_request(self, session, row):
        if self.fail_failed_request_insert:
            raise RuntimeError("private real settlement insert failure")
        return await super().insert_failed_confirmation_request(session, row)


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


class FakeBibleGateway:
    def __init__(self, payload=None):
        self.payload = payload or bible_payload(
            premiseAndPromise="Provider 生成的未来设计只在原子发布后成为草稿。"
        )
        self.calls = 0
        self.started = None
        self.release = None

    async def generate(self, **_values):
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        return self.payload


def bible_generation_service(
    disposable_mysql,
    contracts,
    gateway,
    *,
    failpoint=lambda _stage: None,
):
    tx = transaction_factory_for(disposable_mysql.connection_config)
    ids = iter(
        f"93000000-0000-0000-0000-{number:012d}"
        for number in range(1, 100)
    )
    return BibleGenerationService(
        BibleRepository(),
        contract_service=contracts,
        transaction_factory=tx,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: 1_900_000_001_000,
        failpoint=failpoint,
    )


def generate_command(project_id, key):
    return GenerateBibleDraft(
        project_id=project_id,
        author_instructions="强调群像分工与长期关系代价。",
        expected_draft_version=0,
        expected_head_revision=0,
        idempotency_key=key,
    )


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
async def test_get_draft_uses_one_snapshot_across_active_draft_and_head(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    writer = bible_service(disposable_mysql, contracts)
    saved = await writer.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    repository = PausingReadBibleRepository()
    reader = bible_service(
        disposable_mysql,
        contracts,
        repository=repository,
    )
    repository.arm("active-draft")

    read_task = asyncio.create_task(reader.get_draft(contract.project_id))
    await asyncio.wait_for(repository.observed.wait(), timeout=1)
    try:
        await writer.confirm(
            ConfirmBible(
                contract.project_id,
                "snapshot-draft-confirm",
                saved.draft_version,
                0,
            )
        )
    finally:
        repository.release.set()
    result = await read_task

    assert result.status == "current"
    assert result.can_edit is result.can_confirm is True
    assert result.base_head_revision == 0


@pytest.mark.asyncio
async def test_get_head_uses_one_snapshot_when_a_new_active_draft_is_inserted(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    writer = bible_service(disposable_mysql, contracts)
    saved = await writer.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    confirmed = await writer.confirm(
        ConfirmBible(
            contract.project_id,
            "snapshot-head-confirm",
            saved.draft_version,
            0,
        )
    )
    repository = PausingReadBibleRepository()
    reader = bible_service(
        disposable_mysql,
        contracts,
        repository=repository,
    )
    repository.arm("head")

    read_task = asyncio.create_task(reader.get_head(contract.project_id))
    await asyncio.wait_for(repository.observed.wait(), timeout=1)
    try:
        await writer.clone_draft(
            CloneBibleDraft(
                contract.project_id,
                source_revision=confirmed.revision,
            )
        )
    finally:
        repository.release.set()
    result = await read_task

    assert result.revision == 1
    assert result.can_clone is True


@pytest.mark.asyncio
async def test_history_uses_one_snapshot_for_head_and_revision_page(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    writer = bible_service(disposable_mysql, contracts)
    saved = await writer.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    first = await writer.confirm(
        ConfirmBible(
            contract.project_id,
            "snapshot-history-first",
            saved.draft_version,
            0,
        )
    )
    repository = PausingReadBibleRepository()
    reader = bible_service(
        disposable_mysql,
        contracts,
        repository=repository,
    )
    repository.arm("head")

    read_task = asyncio.create_task(reader.history(contract.project_id))
    await asyncio.wait_for(repository.observed.wait(), timeout=1)
    try:
        cloned = await writer.clone_draft(
            CloneBibleDraft(
                contract.project_id,
                source_revision=first.revision,
            )
        )
        await writer.confirm(
            ConfirmBible(
                contract.project_id,
                "snapshot-history-second",
                cloned.draft_version,
                first.revision,
            )
        )
    finally:
        repository.release.set()
    result = await read_task

    assert tuple(item.revision for item in result.items) == (1,)
    assert result.items[0].status == "current"


@pytest.mark.asyncio
async def test_history_detail_uses_one_snapshot_when_clone_occupies_draft_slot(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    writer = bible_service(disposable_mysql, contracts)
    saved = await writer.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    confirmed = await writer.confirm(
        ConfirmBible(
            contract.project_id,
            "snapshot-detail-confirm",
            saved.draft_version,
            0,
        )
    )
    repository = PausingReadBibleRepository()
    reader = bible_service(
        disposable_mysql,
        contracts,
        repository=repository,
    )
    repository.arm("head")

    read_task = asyncio.create_task(
        reader.get_history_revision(contract.project_id, confirmed.revision)
    )
    await asyncio.wait_for(repository.observed.wait(), timeout=1)
    try:
        await writer.clone_draft(
            CloneBibleDraft(
                contract.project_id,
                source_revision=confirmed.revision,
            )
        )
    finally:
        repository.release.set()
    result = await read_task

    assert result.revision == confirmed.revision
    assert result.can_clone is True


@pytest.mark.asyncio
async def test_bible_write_holds_canonical_corpus_readiness_lock_until_commit(
    disposable_mysql,
):
    checked = asyncio.Event()
    release = asyncio.Event()

    class PausingContractService:
        def __init__(self, delegate):
            self.delegate = delegate

        async def get_head(
            self,
            project_id,
            *,
            session=None,
            for_update=False,
        ):
            result = (
                await self.delegate.get_head(project_id)
                if session is None and not for_update
                else await self.delegate.get_head(
                    project_id,
                    session=session,
                    for_update=for_update,
                )
            )
            checked.set()
            await release.wait()
            return result

    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    writer = bible_service(disposable_mysql, contracts)
    saved = await writer.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    service = bible_service(
        disposable_mysql,
        PausingContractService(contracts),
    )
    command = ConfirmBible(
        contract.project_id,
        "canonical-readiness-lock",
        saved.draft_version,
        0,
    )
    tx = transaction_factory_for(disposable_mysql.connection_config)

    async def archive_corpus():
        async with tx() as session:
            changed = await session.execute(
                """UPDATE corpus_sources
                      SET archived_at=%s,updated_at=%s
                    WHERE id=%s AND archived_at IS NULL""",
                (1_900_000_000_900, 1_900_000_000_900, SOURCE),
            )
            assert changed == 1

    confirm_task = asyncio.create_task(service.confirm(command))
    await asyncio.wait_for(checked.wait(), timeout=1)
    drift_task = asyncio.create_task(archive_corpus())
    completed, _ = await asyncio.wait({drift_task}, timeout=0.25)
    drift_was_blocked = not completed
    release.set()
    confirmed = await confirm_task
    await drift_task

    assert drift_was_blocked is True
    assert confirmed.revision == 1
    with pytest.raises(BiblePreconditionFailed):
        await writer.clone_draft(
            CloneBibleDraft(
                contract.project_id,
                source_revision=confirmed.revision,
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


@pytest.mark.parametrize(
    "stage",
    (
        "after_request_reserve",
        "after_revision_insert",
        "after_head_advance",
        "after_draft_clear",
        "before_request_success",
    ),
)
@pytest.mark.asyncio
async def test_real_confirmation_failure_rolls_back_main_writes_and_is_replayable(
    disposable_mysql,
    stage,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    service = bible_service(
        disposable_mysql,
        contracts,
        failpoint=lambda current_stage: (
            (_ for _ in ()).throw(RuntimeError("real rollback sentinel"))
            if current_stage == stage
            else None
        ),
    )
    saved = await service.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )

    command = ConfirmBible(
        contract.project_id,
        f"real-bible-rollback-{stage}",
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
async def test_real_unrecorded_settlement_failure_is_retryable_then_succeeds(
    disposable_mysql,
):
    state = {"fail_main": True}

    def fail_once(stage):
        if state["fail_main"] and stage == "after_request_reserve":
            state["fail_main"] = False
            raise RuntimeError("private real main failure")

    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    repository = FailingSettlementBibleRepository()
    service = bible_service(
        disposable_mysql,
        contracts,
        failpoint=fail_once,
        repository=repository,
    )
    saved = await service.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    command = ConfirmBible(
        contract.project_id,
        "real-bible-retryable-settlement",
        saved.draft_version,
        0,
    )

    with pytest.raises(PublicDomainError) as captured:
        await service.confirm(command)

    head = await disposable_mysql.session.fetchone(
        "SELECT revision FROM project_bible_heads WHERE project_id=%s",
        (contract.project_id,),
    )
    draft = await disposable_mysql.session.fetchone(
        """SELECT active_slot,draft_version
             FROM project_bible_drafts WHERE id=%s""",
        (saved.draft_id,),
    )
    assert captured.value.code == "BibleConfirmationRetryable"
    assert captured.value.status_code == 503
    assert captured.value.retryable is True
    assert "private" not in str(captured.value).lower()
    assert head == {"revision": 0}
    assert draft == {
        "active_slot": 1,
        "draft_version": saved.draft_version,
    }
    assert await count(disposable_mysql.session, "creation_bible_revisions") == 0
    assert await count(disposable_mysql.session, "bible_confirmation_requests") == 0

    repository.fail_failed_request_insert = False
    succeeded = await service.confirm(command)
    assert succeeded.revision == 1
    assert await count(disposable_mysql.session, "creation_bible_revisions") == 1
    assert await count(disposable_mysql.session, "bible_confirmation_requests") == 1


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
async def test_settlement_drift_without_receipt_is_retryable_and_key_can_confirm_latest_draft(
    disposable_mysql,
):
    settlement_started = asyncio.Event()
    allow_settlement = asyncio.Event()
    fail_main = True

    class DelayedSettlementBibleService(BibleService):
        async def _settle_confirmation_failure(self, context):
            settlement_started.set()
            await allow_settlement.wait()
            return await super()._settle_confirmation_failure(context)

    def fail_once(stage):
        nonlocal fail_main
        if fail_main and stage == "after_request_reserve":
            fail_main = False
            raise RuntimeError("private settlement drift sentinel")

    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    failing = bible_service(
        disposable_mysql,
        contracts,
        failpoint=fail_once,
        service_class=DelayedSettlementBibleService,
    )
    writer = bible_service(disposable_mysql, contracts)
    saved = await failing.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    old_command = ConfirmBible(
        contract.project_id,
        "real-bible-settlement-drift",
        saved.draft_version,
        0,
    )

    failing_task = asyncio.create_task(failing.confirm(old_command))
    try:
        await asyncio.wait_for(settlement_started.wait(), timeout=1)
        updated = await writer.save_draft(
            SaveBibleDraft(
                contract.project_id,
                saved.draft_version,
                bible_payload(
                    premiseAndPromise="并发保存后的新创作圣经前提必须成为唯一可确认版本。"
                ),
            )
        )
    finally:
        allow_settlement.set()

    with pytest.raises(PublicDomainError) as captured:
        await asyncio.wait_for(failing_task, timeout=2)

    receipt_count = await disposable_mysql.session.fetchone(
        """SELECT COUNT(*) AS count
             FROM bible_confirmation_requests
            WHERE project_id=%s AND idempotency_key=%s""",
        (contract.project_id, old_command.idempotency_key),
    )
    assert captured.value.code == "BibleConfirmationRetryable"
    assert captured.value.status_code == 503
    assert captured.value.retryable is True
    assert receipt_count == {"count": 0}

    with pytest.raises(BibleConflict):
        await writer.confirm(old_command)
    succeeded = await writer.confirm(
        ConfirmBible(
            contract.project_id,
            old_command.idempotency_key,
            updated.draft_version,
            0,
        )
    )
    assert succeeded.revision == 1


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


@pytest.mark.asyncio
async def test_real_generation_lease_allows_one_gateway_call_and_atomic_draft(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    gateway = FakeBibleGateway()
    gateway.started = asyncio.Event()
    gateway.release = asyncio.Event()
    service = bible_generation_service(
        disposable_mysql,
        contracts,
        gateway,
    )
    command = generate_command(
        contract.project_id,
        "real-bible-generation-one-call",
    )

    owner = asyncio.create_task(service.generate(command))
    await asyncio.wait_for(gateway.started.wait(), timeout=2)
    inflight = await service.generate(command)
    gateway.release.set()
    succeeded = await asyncio.wait_for(owner, timeout=2)
    replay = await service.generate(command)

    assert inflight.status == "running"
    assert succeeded.status == replay.status == "succeeded"
    assert succeeded == replay
    assert gateway.calls == 1
    attempt = await disposable_mysql.session.fetchone(
        """SELECT status,owner_token,lease_expires_at,attempt_version,
                  result_json,result_hash,public_error_code
             FROM bible_generation_attempts WHERE id=%s""",
        (succeeded.attempt_id,),
    )
    draft = await disposable_mysql.session.fetchone(
        """SELECT active_slot,draft_version,base_head_revision,
                  binding_revision_id,binding_hash,draft_json,content_hash
             FROM project_bible_drafts
            WHERE project_id=%s AND active_slot=1""",
        (contract.project_id,),
    )
    assert attempt["status"] == "succeeded"
    assert attempt["owner_token"] is None
    assert attempt["lease_expires_at"] is None
    assert attempt["attempt_version"] == 2
    assert attempt["result_json"] is not None
    assert attempt["result_hash"] == succeeded.result_hash
    assert attempt["public_error_code"] is None
    assert draft["active_slot"] == 1
    assert draft["draft_version"] == 1
    assert draft["base_head_revision"] == 0
    assert draft["binding_revision_id"] is not None
    assert draft["binding_hash"] is not None
    assert draft["content_hash"] == succeeded.result_hash


@pytest.mark.asyncio
async def test_real_generation_overwrites_manual_draft_with_atomic_provenance(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    manual = bible_service(disposable_mysql, contracts)
    saved = await manual.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    before = await disposable_mysql.session.fetchone(
        """SELECT binding_revision_id,binding_hash
             FROM project_bible_drafts WHERE id=%s""",
        (saved.draft_id,),
    )
    assert before == {"binding_revision_id": None, "binding_hash": None}

    gateway = FakeBibleGateway()
    generated = await bible_generation_service(
        disposable_mysql,
        contracts,
        gateway,
    ).generate(
        GenerateBibleDraft(
            project_id=contract.project_id,
            author_instructions="保留手工基础，强化长期关系代价。",
            expected_draft_version=saved.draft_version,
            expected_head_revision=0,
            idempotency_key="real-bible-generation-provenance",
        )
    )

    assert generated.status == "succeeded"
    assert contract.binding_ref is not None
    draft = await disposable_mysql.session.fetchone(
        """SELECT id,draft_version,content_hash,binding_revision_id,
                  binding_hash
             FROM project_bible_drafts
            WHERE project_id=%s AND active_slot=1""",
        (contract.project_id,),
    )
    assert draft == {
        "id": saved.draft_id,
        "draft_version": saved.draft_version + 1,
        "content_hash": generated.result_hash,
        "binding_revision_id": contract.binding_ref.id,
        "binding_hash": contract.binding_ref.content_hash,
    }

    confirmed = await manual.confirm(
        ConfirmBible(
            contract.project_id,
            "real-bible-confirm-generated-provenance",
            draft["draft_version"],
            0,
        )
    )
    revision = await disposable_mysql.session.fetchone(
        """SELECT binding_revision_id,binding_hash
             FROM creation_bible_revisions WHERE id=%s""",
        (confirmed.bible_revision_id,),
    )
    assert revision == {
        "binding_revision_id": contract.binding_ref.id,
        "binding_hash": contract.binding_ref.content_hash,
    }


@pytest.mark.asyncio
async def test_real_publish_commit_ack_error_reads_back_succeeded_attempt(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    gateway = FakeBibleGateway()
    base_transaction = transaction_factory_for(
        disposable_mysql.connection_config
    )
    transaction_count = 0

    @asynccontextmanager
    async def commit_ack_fails_after_publish():
        nonlocal transaction_count
        transaction_count += 1
        current = transaction_count
        async with base_transaction() as session:
            yield session
        if current == 2:
            raise RuntimeError("PRIVATE_PUBLISH_ACK_DETAIL")

    ids = iter(
        f"93000000-0000-0000-0000-{number:012d}"
        for number in range(1, 100)
    )
    service = BibleGenerationService(
        BibleRepository(),
        contract_service=contracts,
        transaction_factory=commit_ack_fails_after_publish,
        provider_gateway=gateway,
        id_factory=lambda: next(ids),
        clock=lambda: 1_900_000_001_000,
    )
    command = generate_command(
        contract.project_id,
        "real-bible-generation-publish-ack",
    )

    succeeded = await service.generate(command)
    replay = await service.generate(command)

    assert succeeded == replay
    assert succeeded.status == "succeeded"
    assert gateway.calls == 1
    attempt = await disposable_mysql.session.fetchone(
        """SELECT status,owner_token,lease_expires_at,result_hash,
                  public_error_code
             FROM bible_generation_attempts WHERE id=%s""",
        (succeeded.attempt_id,),
    )
    draft = await disposable_mysql.session.fetchone(
        """SELECT content_hash,binding_revision_id,binding_hash
             FROM project_bible_drafts
            WHERE project_id=%s AND active_slot=1""",
        (contract.project_id,),
    )
    assert attempt == {
        "status": "succeeded",
        "owner_token": None,
        "lease_expires_at": None,
        "result_hash": succeeded.result_hash,
        "public_error_code": None,
    }
    assert draft["content_hash"] == succeeded.result_hash
    assert draft["binding_revision_id"] == contract.binding_ref.id
    assert draft["binding_hash"] == contract.binding_ref.content_hash


@pytest.mark.asyncio
async def test_real_expired_generation_lease_cas_terminalizes_without_call(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    gateway = FakeBibleGateway()
    service = bible_generation_service(
        disposable_mysql,
        contracts,
        gateway,
    )
    command = generate_command(
        contract.project_id,
        "real-bible-generation-expired",
    )
    identity = {}
    replay, context = await service._reserve(command, identity)
    assert replay is None
    assert context is not None
    await disposable_mysql.session.execute(
        """UPDATE bible_generation_attempts SET lease_expires_at=%s
            WHERE id=%s AND owner_token=%s AND attempt_version=1""",
        (
            1_900_000_001_000,
            context["attempt"]["id"],
            identity["owner_token"],
        ),
    )

    expired = await service.generate(command)
    second = await service.generate(command)

    assert expired == second
    assert expired.status == "outcome_unknown"
    assert expired.public_error_code == BibleGenerationRetryable.code
    assert expired.attempt_version == 2
    assert gateway.calls == 0
    row = await disposable_mysql.session.fetchone(
        """SELECT status,owner_token,lease_expires_at,attempt_version,
                  result_json,result_hash,public_error_code
             FROM bible_generation_attempts WHERE id=%s""",
        (expired.attempt_id,),
    )
    assert row == {
        "status": "outcome_unknown",
        "owner_token": None,
        "lease_expires_at": None,
        "attempt_version": 2,
        "result_json": None,
        "result_hash": None,
        "public_error_code": "BibleGenerationRetryable",
    }
    assert await count(disposable_mysql.session, "project_bible_drafts") == 0


@pytest.mark.asyncio
async def test_real_generation_publication_failure_rolls_back_draft_and_result(
    disposable_mysql,
):
    contracts, contract = await confirmed_contract_basis(disposable_mysql)
    manual = bible_service(disposable_mysql, contracts)
    saved = await manual.save_draft(
        SaveBibleDraft(contract.project_id, 0, bible_payload())
    )
    before = await disposable_mysql.session.fetchone(
        """SELECT draft_json,content_hash,draft_version,updated_at,
                  binding_revision_id,binding_hash
             FROM project_bible_drafts WHERE id=%s""",
        (saved.draft_id,),
    )
    gateway = FakeBibleGateway()

    def fail_after_draft(stage):
        if stage == "after_draft_write":
            raise RuntimeError("PRIVATE_ATOMIC_FAILURE_DETAIL")

    service = bible_generation_service(
        disposable_mysql,
        contracts,
        gateway,
        failpoint=fail_after_draft,
    )
    result = await service.generate(
        GenerateBibleDraft(
            project_id=contract.project_id,
            author_instructions="这次发布必须回滚。",
            expected_draft_version=saved.draft_version,
            expected_head_revision=0,
            idempotency_key="real-bible-generation-atomic-failure",
        )
    )

    assert result.status == "outcome_unknown"
    assert result.public_error_code == BibleGenerationRetryable.code
    assert gateway.calls == 1
    row = await disposable_mysql.session.fetchone(
        """SELECT status,result_json,result_hash,public_error_code
             FROM bible_generation_attempts WHERE id=%s""",
        (result.attempt_id,),
    )
    assert row == {
        "status": "outcome_unknown",
        "result_json": None,
        "result_hash": None,
        "public_error_code": "BibleGenerationRetryable",
    }
    after = await disposable_mysql.session.fetchone(
        """SELECT draft_json,content_hash,draft_version,updated_at,
                  binding_revision_id,binding_hash
             FROM project_bible_drafts WHERE id=%s""",
        (saved.draft_id,),
    )
    assert after == before
