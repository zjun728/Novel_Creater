# M5 AI WorkingDraft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend-owned AI generation that writes prose into the current `WorkingDraft` without creating candidates, finalizing chapters, or exposing provider secrets to the browser.

**Architecture:** The frontend sends a small generation command to a new chapter-session endpoint. Backend service locks the session/draft, resolves the formal `writing` binding, builds a chapter prompt from planning/session state, calls an injectable OpenAI-compatible gateway, and saves the returned prose as the next `WorkingDraft` revision.

**Tech Stack:** FastAPI, Pydantic, aiomysql transactions, httpx gateway, Pinia, Vue 3, Node test runner, pytest.

---

## File map

- Create `backend/prompts/chapter_draft.py`: deterministic prompt builder for M5.
- Create `backend/gateways/chapter_draft_provider.py`: injectable OpenAI-compatible chapter draft provider boundary.
- Create `backend/services/chapter_draft_generation.py`: command, service, errors, CAS write.
- Modify `backend/repositories/chapter_sessions.py`: add repository helpers to resolve `writing` binding provider inside a transaction.
- Modify `backend/routers/chapter_sessions.py`: add `generate-working-draft` route and safe error mapping.
- Modify `backend/tests/unit/test_chapter_draft_generation_service.py`: service TDD.
- Modify `backend/tests/api/test_chapter_session_routes.py`: route TDD.
- Modify `frontend/src/api/db/client.js`: generation endpoint allowlist.
- Modify `frontend/src/stores/chapterSessionStore.js`: generation action and loading state.
- Modify `frontend/src/views/ChapterWriterView.vue`: instruction input and generation button.
- Modify `frontend/tests/unit/writerCoreApi.test.mjs`, `frontend/tests/unit/chapterSessionStore.test.mjs`, `frontend/tests/unit/m1Navigation.test.mjs`: frontend boundary tests.

## Task 1: Backend generation domain and service

**Files:**
- Create: `backend/tests/unit/test_chapter_draft_generation_service.py`
- Create: `backend/prompts/chapter_draft.py`
- Create: `backend/gateways/chapter_draft_provider.py`
- Create: `backend/services/chapter_draft_generation.py`
- Modify: `backend/repositories/chapter_sessions.py`

- [ ] **Step 1: Write failing service tests**

Add tests for:

```python
async def test_generation_writes_provider_output_to_working_draft_without_candidate()
async def test_generation_conflict_does_not_call_provider()
async def test_generation_provider_failure_does_not_mutate_draft()
```

Expected command:

```powershell
python -m pytest backend/tests/unit/test_chapter_draft_generation_service.py -q
```

Expected result: FAIL because `backend.services.chapter_draft_generation` does not exist.

- [ ] **Step 2: Implement minimal prompt/gateway/service**

Create service command:

```python
@dataclass(frozen=True)
class GenerateWorkingDraft:
    project_id: str
    chapter_session_id: str
    expected_working_draft_revision: int
    author_instruction: str = ""
```

Service behavior:

- open transaction;
- read session by id;
- reject non-drafting session;
- read current working draft;
- compare revision before provider call;
- resolve `writing` provider;
- build messages;
- call provider gateway;
- reject empty output;
- upsert working draft with revision `+1`;
- return workspace.

- [ ] **Step 3: Run service tests**

Run:

```powershell
python -m pytest backend/tests/unit/test_chapter_draft_generation_service.py -q
```

Expected: PASS.

## Task 2: Backend route

**Files:**
- Modify: `backend/routers/chapter_sessions.py`
- Modify: `backend/tests/api/test_chapter_session_routes.py`
- Modify: `backend/tests/api/test_route_inventory.py`

- [ ] **Step 1: Write failing route tests**

Add API tests proving:

- `POST /api/projects/p1/chapter-sessions/session-1/generate-working-draft` returns updated working draft;
- response candidates stay empty;
- unknown request field such as `apiKey` returns `ChapterSessionRequestInvalid`.

Run:

```powershell
python -m pytest backend/tests/api/test_chapter_session_routes.py backend/tests/api/test_route_inventory.py -q
```

Expected: FAIL because route is missing.

- [ ] **Step 2: Implement route and inventory entry**

Route body:

```python
class GenerateWorkingDraftBody(_StrictBody):
    expectedWorkingDraftRevision: int = Field(ge=1)
    authorInstruction: str = Field(default="", max_length=2000)
```

Route calls `ChapterDraftGenerationService.generate_working_draft`.

- [ ] **Step 3: Run route tests**

Run:

```powershell
python -m pytest backend/tests/api/test_chapter_session_routes.py backend/tests/api/test_route_inventory.py -q
```

Expected: PASS.

## Task 3: Frontend API and store

**Files:**
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Modify: `frontend/tests/unit/chapterSessionStore.test.mjs`
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/chapterSessionStore.js`

- [ ] **Step 1: Write failing frontend API/store tests**

Extend tests so generation sends only:

```js
{
  expectedWorkingDraftRevision: 1,
  authorInstruction: '对话多一点'
}
```

and strips:

```js
{ apiKey: 'must-not-send', baseURL: 'must-not-send', debug: true }
```

Store test must assert `saveCandidate` is not called and candidate count remains unchanged after generation.

Run:

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs
```

Expected: FAIL because client/store method is missing.

- [ ] **Step 2: Implement client and store action**

Add `api.chapterSessions.generateWorkingDraft(projectId, sessionId, data)`.

Add store state:

```js
const generatingDraft = ref(false)
const generationInstruction = ref('')
```

Add action:

```js
async function generateWorkingDraft(nextProjectId, authorInstruction = '') {
  const current = requireWorkspace(workspace.value)
  return api.chapterSessions.generateWorkingDraft(nextProjectId, current.session.id, {
    expectedWorkingDraftRevision: current.workingDraft.revision,
    authorInstruction,
  })
}
```

Install returned workspace, do not call `saveCandidate`.

- [ ] **Step 3: Run frontend API/store tests**

Run:

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs
```

Expected: PASS.

## Task 4: Frontend UI

**Files:**
- Modify: `frontend/src/views/ChapterWriterView.vue`
- Modify: `frontend/tests/unit/m1Navigation.test.mjs`

- [ ] **Step 1: Write failing UI boundary test**

Assert `ChapterWriterView.vue` contains `AI 生成工作稿`, uses `generateWorkingDraft`, and does not contain `chatCompletion`, `createAdapter`, `providerAdapter`, `applyAdapter`, `finalize`, `定稿`, or `生成候选`.

Run:

```powershell
node --test frontend/tests/unit/m1Navigation.test.mjs
```

Expected: FAIL until UI is wired.

- [ ] **Step 2: Implement UI**

Add an instruction textarea/input and an `AI 生成工作稿` button. Button is disabled without session or while generating. On success, the existing watcher syncs the returned draft into the editor.

- [ ] **Step 3: Run UI test**

Run:

```powershell
node --test frontend/tests/unit/m1Navigation.test.mjs
```

Expected: PASS.

## Task 5: Verification and handoff

**Files:**
- No source edits expected.

- [ ] **Step 1: Run targeted tests**

```powershell
python -m pytest backend/tests/unit/test_chapter_draft_generation_service.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py backend/tests/api/test_route_inventory.py -q
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/m1Navigation.test.mjs
```

Expected: all pass.

- [ ] **Step 2: Run full verification**

```powershell
npm test
npm run build --prefix frontend
```

Expected: all pass.

- [ ] **Step 3: Commit**

```powershell
git add backend frontend docs/superpowers/specs/2026-07-17-m5-ai-working-draft-design.md docs/superpowers/plans/2026-07-17-m5-ai-working-draft.md
git commit -m "feat: generate chapter working drafts through backend"
```

Expected: commit succeeds with only M5 files.

- [ ] **Step 4: Manual live acceptance**

Start services from merged code, open `http://127.0.0.1:5173/`, enter 《永乐大典》 writing workspace, click `AI 生成工作稿`, confirm generated prose appears in WorkingDraft, candidate count remains unchanged, then optionally click `保存为候选`.
