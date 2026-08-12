# Finalization Review Empty-State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return a closed HTTP 200 empty projection for an existing chapter session with no finalization attempt, while preserving 404 for missing session authority and eliminating the expected browser 4xx/network error.

**Architecture:** `FinalizationService.get_review` distinguishes session absence from attempt absence inside its existing transaction. The route returns `{ "state": "empty" }` for the latter; the frontend serializer maps only that exact closed projection to `null`, which already produces the controller's `prepare` state. Existing populated review and error paths remain unchanged.

**Tech Stack:** Python 3, FastAPI, pytest, JavaScript ES modules, Vue reactivity, Node test runner, Playwright Phase 6A harness.

---

### Task 1: Backend empty-review contract

**Files:**
- Modify: `backend/services/finalization.py:521-533`
- Test: `backend/tests/unit/test_finalization_service.py:613-620`
- Test: `backend/tests/api/test_finalization_routes.py`

- [ ] **Step 1: Write failing service tests**

Add a fake-repository session authority seam and two tests:

```python
@pytest.mark.asyncio
async def test_get_review_returns_closed_empty_state_for_existing_session_without_attempt():
    repository = FakeRepository()
    repository.view = None
    repository.session = {"id": "session-1"}
    service, *_ = _review_service(repository)

    assert await service.get_review("project-1", "session-1") == {"state": "empty"}


@pytest.mark.asyncio
async def test_get_review_keeps_missing_session_not_found():
    repository = FakeRepository()
    repository.view = None
    repository.session = None
    service, *_ = _review_service(repository)

    with pytest.raises(FinalizationConflict, match="FINALIZATION_NOT_FOUND"):
        await service.get_review("project-1", "session-1")
```

- [ ] **Step 2: Run service tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_finalization_service.py -q --basetemp=.pytest-phase7a-finalization-service-red
```

Expected: the empty-state test fails because `get_review` still raises `FINALIZATION_NOT_FOUND` for every `None` view.

- [ ] **Step 3: Implement the minimal service distinction**

Inside the existing transaction, retain `read_current_view`; only when it returns `None`, resolve the session with the existing repository authority method:

```python
async with self.transaction_factory() as session:
    value = await self.repository.read_current_view(
        session, project_id, chapter_session_id,
    )
    if value is None:
        chapter_session = await self.repository.lock_session(
            session, project_id, chapter_session_id,
        )
        if chapter_session is None:
            raise FinalizationConflict("FINALIZATION_NOT_FOUND")
        return {"state": "empty"}
return value
```

Do not catch or normalize persistence failures, and do not change populated review values.

- [ ] **Step 4: Add route RED/GREEN coverage**

Extend the route fake to return a configurable review and assert both public cases:

```python
def test_get_finalization_returns_200_empty_projection_for_existing_session(client, service):
    service.review = {"state": "empty"}
    response = client.get("/api/projects/project-1/chapter-sessions/session-1/finalization")
    assert response.status_code == 200
    assert response.json() == {"state": "empty"}


def test_get_finalization_keeps_true_not_found_fixed(client, service):
    service.error = FinalizationConflict("FINALIZATION_NOT_FOUND")
    response = client.get("/api/projects/project-1/chapter-sessions/missing/finalization")
    assert response.status_code == 404
    assert response.json() == {
        "code": "FinalizationNotFound",
        "message": "Finalization or chapter session was not found",
    }
```

- [ ] **Step 5: Run backend focused tests and commit**

Run:

```powershell
python -m pytest backend/tests/unit/test_finalization_service.py backend/tests/api/test_finalization_routes.py -q --basetemp=.pytest-phase7a-finalization-backend
python -m py_compile backend/services/finalization.py backend/routers/finalization.py
```

Expected: all pass, no warnings or residue.

Commit:

```powershell
git add backend/services/finalization.py backend/tests/unit/test_finalization_service.py backend/tests/api/test_finalization_routes.py
git commit -m "fix: represent empty finalization review explicitly"
```

### Task 2: Frontend closed empty projection

**Files:**
- Modify: `frontend/src/api/db/client.js:1971-2026`
- Test: `frontend/tests/unit/finalizationApi.test.mjs`
- Test: `frontend/tests/unit/finalizationController.test.mjs:161-173`

- [ ] **Step 1: Write API and controller RED tests**

Add an API test proving the exact empty projection becomes the normal `null` review without swallowing unrelated values:

```javascript
test('getFinalization maps only the closed empty projection to null', async () => {
  const api = createApi({ get: async () => ({ state: 'empty' }) })
  assert.equal(await api.chapterSessions.getFinalization('project-1', 'session-1'), null)
})
```

Replace the controller's old 404-normal test with a 200-empty test:

```javascript
test('load treats the explicit empty review as prepare state', async () => {
  const controller = createFinalizationController({
    getReview: async () => null,
  })
  assert.equal(await controller.load(), null)
  assert.equal(controller.review.value, null)
  assert.equal(controller.error.value, '')
  assert.equal(controller.primaryAction.value, 'prepare')
})
```

Keep a separate test showing an actual API 404 is not reclassified as normal empty state.

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```powershell
node --test frontend/tests/unit/finalizationApi.test.mjs frontend/tests/unit/finalizationController.test.mjs
```

Expected: API serialization rejects `{ state: 'empty' }`, and the old controller 404 behavior conflicts with the new contract.

- [ ] **Step 3: Implement the minimal serializer**

At the start of `finalizationReview`, accept only the exact closed empty object:

```javascript
function finalizationReview(value) {
  const source = finalizationObject(value, 'review')
  if (source.state === 'empty' && Object.keys(source).length === 1) return null
  // existing populated-review validation remains unchanged
}
```

Do not add a generic catch in the controller. Remove only the legacy branch that treats a 404 from `getReview` as the normal empty state.

- [ ] **Step 4: Run frontend focused tests and commit**

Run:

```powershell
node --test frontend/tests/unit/finalizationApi.test.mjs frontend/tests/unit/finalizationController.test.mjs
```

Expected: all pass.

Commit:

```powershell
git add frontend/src/api/db/client.js frontend/tests/unit/finalizationApi.test.mjs frontend/tests/unit/finalizationController.test.mjs
git commit -m "fix: consume empty finalization review state"
```

### Task 3: Focused regression and Phase 6A closure

**Files:**
- Verify only: backend/frontend files from Tasks 1-2
- Existing dirty Task 5 harness files remain a separate commit boundary

- [ ] **Step 1: Run focused backend and frontend regression**

Run:

```powershell
python -m pytest backend/tests/unit/test_finalization_service.py backend/tests/api/test_finalization_routes.py -q --basetemp=.pytest-phase7a-finalization-focused
node --test frontend/tests/unit/finalizationApi.test.mjs frontend/tests/unit/finalizationController.test.mjs
git diff --check
```

Expected: all pass; the only expected Git notice is the existing LF-to-CRLF warning.

- [ ] **Step 2: Re-run Phase 6A contracts**

Run:

```powershell
node --test scripts/tests/phase6aBrowserContract.test.mjs frontend/e2e/phase6a/runtime-observer.test.mjs
```

Expected: all pass, with no observer tolerance added.

- [ ] **Step 3: Run one replacement Phase 6A formal gate**

Run once:

```powershell
npm run test:browser:phase6a
```

Expected: exit 0; scenario 1/1; every runtime counter, cleanup category, owned root, DB, process, port, download, artifact, Provider, and outbound ledger is zero. If it fails, stop at the first fixed stage/cause and do not automatically rerun.

- [ ] **Step 4: Commit the Task 5 harness separately after review**

After spec and quality review confirm C/I are zero:

```powershell
git add backend/scripts/prepare_phase6a_browser_db.py frontend/e2e/run-phase6a.mjs frontend/e2e/playwright.phase6a.config.mjs frontend/e2e/phase6a/finalized-novel-download.spec.mjs frontend/e2e/phase6a/runtime-observer.mjs frontend/e2e/phase6a/runtime-observer.test.mjs scripts/tests/phase6aBrowserContract.test.mjs
git commit -m "test: harden phase6a browser boundary"
```

Do not include product files from Tasks 1-2 in this harness commit.
