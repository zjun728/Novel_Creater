import copy
import hashlib

import pytest

from backend.domain.json_contracts import canonical_hash
from backend.services.draft_operations import DraftOperationPreconditionFailed, DraftOperationRequestInvalid
from backend.tests.unit.test_draft_operation_service import (
    FakeRepository, FakeGateway, PROJECT_ID, SESSION_ID, command, make_service, start_and_finish,
)


class ReviewRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.outline["current_planning_hash"] = self.session["planning_hash"]
        text = "原稿全文：人物留在门外。" * 250
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.draft.update(content=text, content_hash=digest)
        report = {"status": "completed", "deterministicBlocks": [], "findings": [
            {"id": str(i), "dimension": "pacing", "reason": "重复解释" * 200,
             "suggestedAction": f"保留动作，删去第{i}段重复解释。", "evidence": None}
            for i in range(8)
        ]}
        report["contentHash"] = canonical_hash(report)
        self.reference = {
            "attemptId": "40000000-0000-4000-8000-000000000001",
            "candidateId": "50000000-0000-4000-8000-000000000001",
            "candidateHash": digest, "changeSetRevision": 2,
            "changeSetHash": "e" * 64, "qualityReportHash": report["contentHash"],
        }
        self.review = {
            "attempt": {"id": self.reference["attemptId"], "status": "awaiting_author", "active_slot": 1,
                        "expected_canon_revision": 5, "expected_planning_hash": "a" * 64,
                        "expected_outline_hash": "c" * 64},
            "view": {**{k: self.reference[k] for k in ("attemptId", "candidateId", "candidateHash")},
                     "status": "awaiting_author", "qualityReport": report,
                     "changeSet": {"revision": 2, "contentHash": "e" * 64}},
            "candidate": {"id": self.reference["candidateId"], "project_id": PROJECT_ID,
                          "chapter_session_id": SESSION_ID, "content": text, "content_hash": digest},
        }

    async def read_review_for_draft_operation(self, *args):
        return copy.deepcopy(self.review)

    async def invalidate_adjusted_review(self, *args):
        self.review["attempt"].update(status="invalidated", active_slot=None)
        self.review["view"]["status"] = "invalidated"
        return True

    def request(self, **overrides):
        return command(expected_content_hash=self.draft["content_hash"],
                       review_reference={**self.reference, **overrides})


@pytest.mark.asyncio
async def test_review_uses_complete_original_and_all_opinions_and_replays_once():
    repo = ReviewRepository()
    old = copy.deepcopy(repo.review["candidate"])
    service, _, gateway, *_ = make_service(repo)
    request = repo.request()
    result = await start_and_finish(service, request)
    assert result.status == "completed"
    prompt = gateway.calls[0]["messages"][1]["content"]
    assert old["content"] in prompt
    for finding in repo.review["view"]["qualityReport"]["findings"]:
        assert finding["reason"] in prompt and finding["suggestedAction"] in prompt
    assert "本稿完整审稿意见" in prompt
    assert repo.review["candidate"] == old
    assert repo.review["view"]["status"] == "invalidated"
    assert (await service.start(request)).operation_id == result.operation_id
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("changeSetRevision", 1), ("candidateHash", "f" * 64),
    ("qualityReportHash", "f" * 64), ("attemptId", "60000000-0000-4000-8000-000000000001")])
async def test_stale_reference_never_starts_provider(field, value):
    repo = ReviewRepository()
    service, _, gateway, *_ = make_service(repo)
    with pytest.raises(DraftOperationPreconditionFailed):
        await service.start(repo.request(**{field: value}))
    assert not gateway.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", [
    lambda repo: repo.review["view"]["changeSet"].update(revision=3),
    lambda repo: repo.review["attempt"].update(status="cancelled", active_slot=None),
    lambda repo: repo.outline.update(current_planning_hash="f" * 64),
])
async def test_review_or_authority_drift_during_generation_never_overwrites(mutate):
    repo = ReviewRepository()
    original = repo.draft["content"]
    service, *_ = make_service(repo, FakeGateway(on_generate=lambda: mutate(repo)))
    result = await start_and_finish(service, repo.request())
    assert result.status == "expired"
    assert repo.draft["content"] == original


@pytest.mark.asyncio
async def test_review_failure_preserves_old_draft():
    from backend.gateways.chapter_draft_provider import ChapterDraftProviderError
    repo = ReviewRepository()
    original = repo.draft["content"]
    service, *_ = make_service(repo, FakeGateway(ChapterDraftProviderError("failed")))
    result = await start_and_finish(service, repo.request())
    assert result.status == "failed"
    assert repo.draft["content"] == original
    assert repo.review["view"]["status"] == "awaiting_author"


@pytest.mark.asyncio
async def test_even_identical_generated_text_requires_a_new_review():
    repo = ReviewRepository()
    service, *_ = make_service(repo, FakeGateway(repo.draft["content"]))
    result = await start_and_finish(service, repo.request())
    assert result.status == "completed"
    assert repo.review["view"]["status"] == "invalidated"


@pytest.mark.parametrize("reference", [{}, {"instructions": "frontend injected opinions"}, None])
def test_review_reference_shape_is_closed(reference):
    from backend.services.draft_review import review_reference
    with pytest.raises(ValueError):
        review_reference(reference)


def test_api_preserves_review_reference_and_rejects_local_use():
    from backend.domain.routers.chapter_sessions import CreateDraftOperationBody
    repo = ReviewRepository()
    body = {"operationType": "generate_new", "expectedWorkingDraftRevision": 1,
            "expectedContentHash": repo.draft["content_hash"],
            "idempotencyKey": "60000000-0000-4000-8000-000000000001", "reviewReference": repo.reference}
    assert CreateDraftOperationBody.model_validate(body).reviewReference == repo.reference
    with pytest.raises(ValueError):
        CreateDraftOperationBody.model_validate({**body, "operationType": "polish_selection",
            "startOffset": 0, "endOffset": 1, "selectedTextHash": "a" * 64})


def test_http_route_passes_review_reference_to_service():
    from backend.tests.api.test_draft_operation_routes import make_client, create_body, PROJECT_ID as PID, SESSION_ID as SID
    client, service, _ = make_client()
    reference = ReviewRepository().reference
    response = client.post(f"/api/projects/{PID}/chapter-sessions/{SID}/draft-operations",
                           json=create_body(reviewReference=reference))
    assert response.status_code == 200, response.text
    assert service.commands[0].review_reference == reference


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", [False, True])
async def test_cancel_review_partial_rechecks_authority_before_adoption(drift):
    repo = ReviewRepository()
    original = repo.draft["content"]
    service, *_ = make_service(repo)
    started = await service.start(repo.request())
    partial = "调整中的部分正文"
    repo.operations[started.operation_id].update(partial_output_text=partial,
        partial_output_hash=hashlib.sha256(partial.encode()).hexdigest(),
        partial_output_scalars=len(partial), last_event_sequence=2)
    if drift:
        repo.review["view"]["changeSet"]["revision"] = 3
    result = await service.cancel(PROJECT_ID, SESSION_ID, started.operation_id)
    assert result.status == ("expired" if drift else "cancelled")
    assert repo.draft["content"] == (original if drift else partial)
    assert repo.review["view"]["status"] == ("awaiting_author" if drift else "invalidated")
