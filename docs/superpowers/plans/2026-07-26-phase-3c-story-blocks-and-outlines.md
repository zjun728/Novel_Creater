# Phase 3C Story Blocks and Chapter Outlines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the future-story Planning aggregate, let the author create and confirm one authoritative ChapterOutline, and open exactly one server-authoritative ChapterSession from the real product UI.

**Architecture:** Keep the existing `PlanningRepository`/`PlanningService`/`planningStore` chain and the final writer-core-v1.5 schema. Deliver three sequential vertical slices on one branch: StoryBlock editing, ChapterOutline manual/AI/history, then authoritative chapter/session routing. The backend owns every authority, status, chapter number, and capability; the browser carries only explicit edits and concurrency assertions.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, aiomysql, MySQL 8, Vue 3, Pinia 3, Vue Router 4, Naive UI, Node test runner, Playwright.

---

## Frozen decisions

- Baseline: `main@59d80d739ef39a09bcd54e1888e4e4da90a98fa3`.
- Delivery branch: `codex/phase3c-story-blocks-outlines`.
- Approved design: `docs/superpowers/specs/2026-07-26-phase-3c-story-blocks-outlines-design.md`.
- Delivery order is fixed: Story Blocks, Chapter Outlines, authoritative chapter/session.
- No schema change, migration, compatibility alias, legacy fallback, `PlanningV2`, or new Store.
- `StoryBlock`, `Stage`, and `SceneTask` remain inside the single `planning-v1` aggregate.
- Story Blocks have no target chapter count, completed flag, or manually maintained actual progress.
- Outline state is a child state of `planningStore`; do not create `chapterOutlineStore`.
- Outline appears below Story Blocks at `/projects/:projectId/planning/story-blocks`; do not add a fourth Planning route.
- AI generation uses the existing project `planning` task binding and never confirms an Outline or creates a Session.
- Planning/Outline drift during generation finishes as `superseded`, never as `succeeded, loaded=false`.
- The server calculates the chapter number from an active drafting Session, otherwise `MAX(final_chapters.chapter_num)+1`, otherwise `1`.
- One project can have at most one drafting Session by project-row serialization plus a query across all chapter numbers.
- Automated acceptance uses a fake only at the external Provider boundary, disposable MySQL 8, loopback ports, and no product database or real Provider.
- Public API, logs, errors, screenshots, reports, and artifacts contain no API key, prompt, raw Provider output, manifest, corpus text, Authorization header, password, or DSN.

## File map

### Backend files to create

- `backend/repositories/chapter_outlines.py`: Outline head, Draft, immutable revision, confirmation, attempt, lease, and authority queries.
- `backend/services/chapter_outlines.py`: current state, manual Draft CAS, confirmation, history, and capabilities.
- `backend/prompts/chapter_outline.py`: closed safe manifest and bounded prompt.
- `backend/gateways/chapter_outline_provider.py`: strict production Provider boundary.
- `backend/services/chapter_outline_generation.py`: reserve/call/publish/reconcile.
- `backend/routers/chapter_outlines.py`: canonical Outline API and public DTO projection.
- `backend/tests/unit/test_chapter_outline_repository.py`
- `backend/tests/unit/test_chapter_outline_service.py`
- `backend/tests/unit/test_chapter_outline_prompt.py`
- `backend/tests/unit/test_chapter_outline_gateway.py`
- `backend/tests/unit/test_chapter_outline_generation_service.py`
- `backend/tests/api/test_chapter_outline_routes.py`
- `backend/tests/integration/test_chapter_outline_lifecycle.py`
- `backend/tests/integration/test_chapter_outline_generation.py`
- `backend/tests/integration/test_authoritative_chapter_session.py`

### Backend files to modify

- `backend/domain/chapter_outlines.py`
- `backend/repositories/planning.py`
- `backend/services/planning_generation.py`
- `backend/repositories/chapter_sessions.py`
- `backend/services/chapter_sessions.py`
- `backend/routers/chapter_sessions.py`
- `backend/repositories/project_lifecycle.py`
- `backend/services/project_lifecycle.py`
- `backend/main.py`
- Focused existing Planning, Session, lifecycle, archive, public-error, and secret-boundary tests.

### Frontend files to create

- `frontend/src/components/planning/StoryBlockEditor.vue`
- `frontend/src/components/planning/ChapterOutlineWorkspace.vue`
- `frontend/src/components/planning/ChapterOutlineHistoryDrawer.vue`
- `frontend/src/application/planning/chapterOutlineController.js`
- `frontend/tests/unit/storyBlockEditor.test.mjs`
- `frontend/tests/unit/chapterOutlineController.test.mjs`
- `frontend/tests/unit/chapterOutlineWorkspace.test.mjs`

### Frontend files to modify

- `frontend/src/api/db/client.js`
- `frontend/src/stores/planningStore.js`
- `frontend/src/application/planning/planningWorkspaceController.js`
- `frontend/src/components/planning/PlanningWorkspace.vue`
- `frontend/src/views/ProjectPlanningView.vue`
- `frontend/src/router/projectRoutes.js`
- `frontend/src/components/layout/productShell.js`
- `frontend/src/views/ProjectOverviewView.vue`
- `frontend/src/stores/chapterSessionStore.js`
- `frontend/src/views/ChapterWriterView.vue`
- Focused API, Store, controller, route, shell, overview, and runtime-inventory tests.

### Acceptance files to create or modify

- `frontend/e2e/phase3c-story-blocks-outlines.spec.ts`
- `frontend/e2e/playwright.phase3c.config.ts`
- `frontend/e2e/run-phase3c.mjs`
- `scripts/tests/phase3cSuite.test.mjs`
- `scripts/tests/phase3PlanContract.test.mjs`
- `scripts/run-tests.mjs`
- Root and frontend `package.json`
- `docs/acceptance/2026-07-26-phase-3c-story-blocks-outlines.md`
- `CURRENT_PROJECT_STATE.md`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

## Slice 1 — Story Blocks

### Task 1: Freeze the Phase 3C delivery contract

**Files:**

- Modify: `scripts/tests/phase3PlanContract.test.mjs`
- Test: `scripts/tests/phase3PlanContract.test.mjs`

- [ ] **Step 1: Write the failing detailed-plan contract**

Add a test body that uses a not-yet-defined `phase3cPlan` value and requires:

```javascript
const required = [
  'codex/phase3c-story-blocks-outlines',
  'no schema change',
  'StoryBlock',
  'chapterOutlineController',
  'authoritative chapter',
  'npm run test:browser:phase3c',
]
for (const phrase of required) {
  assert.ok(phase3cPlan.toLowerCase().includes(phrase.toLowerCase()))
}
```

Scan the tracked production runtime, not this explanatory plan, for duplicate or
obsolete architecture names:

```javascript
const runtime = (
  await Promise.all([
    readProjectFile('frontend/src/stores/planningStore.js'),
    readProjectFile('frontend/src/application/planning/planningWorkspaceController.js'),
    readProjectFile('frontend/src/components/planning/PlanningWorkspace.vue'),
    readProjectFile('frontend/src/views/ProjectPlanningView.vue'),
    readProjectFile('frontend/src/router/projectRoutes.js'),
  ])
).join('\n')
for (const forbidden of [
  'planningV2Store',
  'chapterOutlineStore',
  'storyBlockStore',
  'PlanningWorkspaceV2',
  '/planning/initial',
]) {
  assert.equal(runtime.includes(forbidden), false)
}
```

- [ ] **Step 2: Run RED**

```powershell
node --test scripts/tests/phase3PlanContract.test.mjs
```

Expected: FAIL because the current contract does not read the Phase 3C plan.

- [ ] **Step 3: Point the contract at the exact plan and run GREEN**

Add:

```javascript
const phase3cPlanPath =
  'docs/superpowers/plans/2026-07-26-phase-3c-story-blocks-and-outlines.md'
const phase3cPlan = await readProjectFile(phase3cPlanPath)
```

Run the same command. Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add -- scripts/tests/phase3PlanContract.test.mjs
git commit -m "test: freeze phase three c delivery contract"
```

### Task 2: Extend the Planning controller for nested Story Blocks

**Files:**

- Modify: `frontend/src/application/planning/planningWorkspaceController.js`
- Modify: `frontend/tests/unit/planningWorkspaceController.test.mjs`
- Create: `frontend/tests/unit/storyBlockEditor.test.mjs`

- [ ] **Step 1: Write nested-edit RED tests**

Use one editable Planning Draft and assert:

```javascript
assert.equal(controller.addStoryBlock(), true)
assert.equal(store.localContent.storyBlocks.length, 1)
assert.equal(controller.addStage(blockKey), true)
assert.equal(controller.addSceneTask(blockKey, stageKey), true)
assert.equal(controller.selectActiveStoryBlock(blockKey), true)
assert.equal(controller.complete, true)
```

Cover stable `clientNodeKey`, add/update/reorder, new-node removal, historical-node retirement, no reactivation, one-step local undo, active StoryBlock selection, Volume/Plot references, and nested order normalization. Assert the submitted objects never contain `targetChapterCount`, `completed`, or actual-progress fields.

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/planningWorkspaceController.test.mjs frontend/tests/unit/storyBlockEditor.test.mjs
```

Expected: FAIL on missing nested controller methods.

- [ ] **Step 3: Implement immutable nested helpers**

Add these exact controller methods while preserving `store.editLocal()` as the only mutation boundary:

```javascript
addStoryBlock()
updateStoryBlock(blockKey, patch)
removeStoryBlock(blockKey)
moveStoryBlock(blockKey, direction)
selectActiveStoryBlock(blockKey)
addStage(blockKey)
updateStage(blockKey, stageKey, patch)
removeStage(blockKey, stageKey)
moveStage(blockKey, stageKey, direction)
addSceneTask(blockKey, stageKey)
updateSceneTask(blockKey, stageKey, taskKey, patch)
removeSceneTask(blockKey, stageKey, taskKey)
moveSceneTask(blockKey, stageKey, taskKey, direction)
undoStoryBlockEdit()
```

The editable fields are closed:

```javascript
const STORY_BLOCK_FIELDS = [
  'title', 'volumeRef', 'plotRefs', 'entrySituation', 'blockGoal',
  'mainPressure', 'expectedChange', 'openQuestions', 'involvedCharacters',
]
const STAGE_FIELDS = ['title', 'purpose', 'dramaticQuestion']
const SCENE_TASK_FIELDS = ['task', 'completionEvidence']
```

- [ ] **Step 4: Run GREEN and commit**

```powershell
node --test frontend/tests/unit/planningWorkspaceController.test.mjs frontend/tests/unit/storyBlockEditor.test.mjs
git add -- frontend/src/application/planning/planningWorkspaceController.js frontend/tests/unit/planningWorkspaceController.test.mjs frontend/tests/unit/storyBlockEditor.test.mjs
git commit -m "feat: edit nested story planning"
```

### Task 3: Add the canonical Story Blocks workspace

**Files:**

- Create: `frontend/src/components/planning/StoryBlockEditor.vue`
- Modify: `frontend/src/components/planning/PlanningWorkspace.vue`
- Modify: `frontend/src/views/ProjectPlanningView.vue`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/tests/unit/planningWorkspaceSfc.test.mjs`
- Modify: `frontend/tests/unit/projectPlanningView.test.mjs`
- Modify: `frontend/tests/unit/projectRoutes.test.mjs`
- Modify: `frontend/tests/unit/productShell.test.mjs`
- Modify: `frontend/tests/unit/phase2RuntimeInventory.test.mjs`

- [ ] **Step 1: Write route and component RED tests**

Require one route:

```text
/projects/:projectId/planning/story-blocks
```

It must mount `ProjectPlanningView`, set `activeTab === "story-blocks"`, preserve the same project’s dirty Planning Draft when switching among all three tabs, and select the existing Planning shell item. Assert no `/outlines` route and no new Store import.

- [ ] **Step 2: Write interaction RED tests**

Require labeled controls for every frozen field, explicit add/retire/reorder actions, local undo for a newly removed node, active-block selection, and a complete aggregate summary before confirmation. Archived and superseded states render the same component read-only.

- [ ] **Step 3: Run RED**

```powershell
node --test frontend/tests/unit/planningWorkspaceSfc.test.mjs frontend/tests/unit/projectPlanningView.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs frontend/tests/unit/phase2RuntimeInventory.test.mjs
```

- [ ] **Step 4: Implement the third shared tab**

Add:

```javascript
export function planningStoryBlocksPath(projectId) {
  return `/projects/${segment(projectId)}/planning/story-blocks`
}
```

Extend the same-project route allowlist to all three route names. Mount `StoryBlockEditor` only when `activeTab === 'story-blocks'`; keep one save, one Planning confirmation, one history drawer, and one Planning generation operation.

- [ ] **Step 5: Run GREEN and commit**

```powershell
npm --prefix frontend run test:unit
git add -- frontend/src/components/planning/StoryBlockEditor.vue frontend/src/components/planning/PlanningWorkspace.vue frontend/src/views/ProjectPlanningView.vue frontend/src/router/projectRoutes.js frontend/src/components/layout/productShell.js frontend/tests/unit/planningWorkspaceSfc.test.mjs frontend/tests/unit/projectPlanningView.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs frontend/tests/unit/phase2RuntimeInventory.test.mjs
git commit -m "feat: add story block planning workspace"
```

## Slice 2 — Chapter Outlines

### Task 4: Implement Outline persistence and authority reads

**Files:**

- Create: `backend/repositories/chapter_outlines.py`
- Modify: `backend/repositories/chapter_sessions.py`
- Create: `backend/tests/unit/test_chapter_outline_repository.py`
- Modify: `backend/tests/unit/test_chapter_session_repository.py`
- Create: `backend/tests/integration/test_chapter_outline_lifecycle.py`

- [ ] **Step 1: Write repository RED tests**

Require these exact operations:

```python
lock_project(session, project_id)
read_project_any(session, project_id)
read_current_authorities(session, project_id)
lock_outline_head(session, project_id, chapter_number)
read_outline_head(session, project_id, chapter_number)
read_active_draft(session, project_id, chapter_number)
read_draft(session, project_id, chapter_number, draft_id)
insert_draft(session, row)
update_draft_cas(session, row, expected_revision, expected_hash)
supersede_draft(session, project_id, chapter_number, draft_id)
insert_revision(session, row)
advance_head_cas(session, row, expected_revision)
find_confirmation(session, project_id, chapter_number, idempotency_key)
insert_confirmation_pending(session, row)
finish_confirmation(session, row)
list_revisions(session, project_id, chapter_number)
```

Also require attempt methods matching the existing columns:

```python
lock_attempt_by_key(session, project_id, idempotency_key)
read_attempt_by_key(session, project_id, idempotency_key)
lock_attempt(session, project_id, operation_id)
read_attempt(session, project_id, operation_id)
lock_active_attempt(session, draft_id)
next_fencing_token(session, draft_id)
insert_attempt(session, row)
supersede_attempt(session, operation_id, fencing_token)
fail_attempt(session, operation_id, fencing_token, failure_code)
load_result_into_draft(
    session, draft_id, expected_revision, expected_hash,
    operation_id, fencing_token, content, content_hash, loaded_at
)
```

Extend the existing `ChapterSessionRepository` as the single chapter-authority
query owner:

```python
read_active_session(session, project_id)
read_max_final_chapter_number(session, project_id)
```

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_repository.py backend/tests/unit/test_chapter_session_repository.py backend/tests/integration/test_chapter_outline_lifecycle.py -q
```

Expected: FAIL because the repository does not exist.

- [ ] **Step 3: Implement against the existing v1.5 tables**

Use only:

```text
chapter_outline_drafts
chapter_outline_generation_attempts
chapter_outline_revisions
project_chapter_outline_heads
chapter_outline_confirmation_requests
```

Every JSON write uses canonical JSON. Every terminal attempt update includes `status='pending'`, `active_slot=1`, operation ID, and fencing token in its CAS predicate. Static authority reads return normalized dictionaries and never expose raw database JSON.

`load_result_into_draft` is one joined CAS that updates the exact Draft and the
pending attempt together: Draft revision/content/source attempt plus attempt
`status='succeeded'`, result JSON/hash, loaded Draft revision, and loaded time.
There is no standalone “mark succeeded” method.

`ChapterOutlineService` receives both repositories and calculates the chapter
from the project-locked `read_active_session` and
`read_max_final_chapter_number` facts. No Outline-specific chapter calculator is
allowed.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_repository.py backend/tests/unit/test_chapter_session_repository.py backend/tests/integration/test_chapter_outline_lifecycle.py -q
git add -- backend/repositories/chapter_outlines.py backend/repositories/chapter_sessions.py backend/tests/unit/test_chapter_outline_repository.py backend/tests/unit/test_chapter_session_repository.py backend/tests/integration/test_chapter_outline_lifecycle.py
git commit -m "feat: persist chapter outline revisions"
```

### Task 5: Add manual Outline state, Draft CAS, confirmation, and history

**Files:**

- Modify: `backend/domain/chapter_outlines.py`
- Create: `backend/services/chapter_outlines.py`
- Create: `backend/routers/chapter_outlines.py`
- Modify: `backend/main.py`
- Create: `backend/tests/unit/test_chapter_outline_service.py`
- Create: `backend/tests/api/test_chapter_outline_routes.py`
- Modify: `backend/tests/integration/test_chapter_outline_lifecycle.py`
- Modify: `backend/tests/api/test_public_domain_errors.py`
- Modify: `backend/tests/unit/test_archived_write_inventory.py`

- [ ] **Step 1: Write closed service DTO RED tests**

Add a closed, saveable work-in-progress value beside the existing strict
confirmable `DraftChapterOutline`:

```python
class EditableChapterOutlineContent(_StrictOutlineValue):
    schema_version: Literal["chapter-outline-draft-v1"] = Field(
        default="chapter-outline-draft-v1",
        alias="schemaVersion",
    )
    volume_ref: PlanningNodeRef | None = Field(default=None, alias="volumeRef")
    story_block_ref: PlanningNodeRef | None = Field(
        default=None,
        alias="storyBlockRef",
    )
    stage_refs: tuple[PlanningNodeRef, ...] = Field(
        default=(),
        alias="stageRefs",
    )
    scene_task_refs: tuple[PlanningNodeRef, ...] = Field(
        default=(),
        alias="sceneTaskRefs",
    )
    chapter_goal: str = Field(default="", alias="chapterGoal", max_length=4000)
    expected_characters: tuple[str, ...] = Field(
        default=(),
        alias="expectedCharacters",
    )
    continuation: tuple[str, ...] = ()
    planned_tasks: tuple[str, ...] = Field(default=(), alias="plannedTasks")
    scenes: tuple[str, ...] = ()
    forbidden_early_events: tuple[str, ...] = Field(
        default=(),
        alias="forbiddenEarlyEvents",
    )
```

This value contains only author-editable fields. Chapter number, Planning,
Canon/Projection, capacity policy, and content hash stay in server authority
columns/read models and cannot be submitted as edits.

Define commands:

```python
@dataclass(frozen=True)
class CreateChapterOutlineDraft:
    project_id: str
    chapter_number: int

@dataclass(frozen=True)
class SaveChapterOutlineDraft:
    project_id: str
    chapter_number: int
    draft_id: str
    expected_draft_revision: int
    expected_draft_hash: str
    content: EditableChapterOutlineContent

@dataclass(frozen=True)
class ConfirmChapterOutlineDraft:
    project_id: str
    chapter_number: int
    draft_id: str
    expected_draft_revision: int
    expected_draft_hash: str
    expected_head_revision: int
    idempotency_key: str
```

Test manual singleton create/replay, save, CAS conflict, archived denial, basis
drift to `superseded`, strict active-node references, Canon/Projection mismatch,
confirmation same-key replay, confirmation different-fingerprint conflict,
atomic head advance, rollback, and history statuses `current`, `superseded`,
`session_pinned`, `archived`. With an active Session, the `current` read model
returns the exact Session-pinned Outline/Planning revisions and disables every
Outline mutation even if newer Planning exists.

- [ ] **Step 2: Write API RED tests**

Register static routes before `/{chapter_number}`:

```text
GET  /api/projects/{pid}/chapter-outlines/current
GET  /api/projects/{pid}/chapter-outlines/operations/by-key/{idempotency_key}
GET  /api/projects/{pid}/chapter-outlines/operations/{operation_id}
GET  /api/projects/{pid}/chapter-outlines/{chapter_number}
GET  /api/projects/{pid}/chapter-outlines/{chapter_number}/history
POST /api/projects/{pid}/chapter-outlines/{chapter_number}/drafts
PUT  /api/projects/{pid}/chapter-outlines/{chapter_number}/drafts/{draft_id}
POST /api/projects/{pid}/chapter-outlines/{chapter_number}/drafts/{draft_id}/confirm
```

Bodies are strict Pydantic models with `extra="forbid"`. Public responses contain camelCase UI fields, fixed reason codes, and no DB JSON, prompt, manifest, attempt internals, or secret.

The `current` response is closed to:

```text
projectId
lifecycle
authoritativeChapterNumber
targetPath
planningAuthority
canonProjectionAuthority
confirmedOutline
draft
activeSession
capabilities { view, createDraft, editDraft, generate, confirm, startSession }
reasons[]
```

`confirmedOutline` and `draft` each contain their public identity, basis summary,
editable content, and derived status only. The response never returns a
database row or internal generation attempt.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_domain.py backend/tests/unit/test_chapter_outline_service.py backend/tests/api/test_chapter_outline_routes.py backend/tests/api/test_public_domain_errors.py backend/tests/integration/test_chapter_outline_lifecycle.py -q
```

- [ ] **Step 4: Implement short-transaction confirmation**

Use this fixed lock order:

```text
project
-> active Session/final chapter authority
-> Planning Head
-> Canon/Projection Head
-> Outline Head
-> Outline Draft
-> confirmation request
```

Create Drafts with the server-authoritative chapter, frozen current authority,
and an empty `EditableChapterOutlineContent`. Save it with
`draftRevision + contentHash` CAS. On confirmation, combine the stored editable
content with the server-owned chapter/Planning/capacity basis to construct the
strict `DraftChapterOutline`, normalize through
`normalize_chapter_outline()`, insert one immutable revision, advance the head
with CAS, mark the Draft confirmed, and complete the idempotency row in the same
transaction.

Draft creation has no invented idempotency ledger. After locking the project and
reading chapter authority, return the existing current active Draft or
supersede a stale one and create exactly one new active Draft under
`uq_outline_draft_active_slot`.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_domain.py backend/tests/unit/test_chapter_outline_service.py backend/tests/api/test_chapter_outline_routes.py backend/tests/api/test_public_domain_errors.py backend/tests/integration/test_chapter_outline_lifecycle.py -q
git add -- backend/domain/chapter_outlines.py backend/services/chapter_outlines.py backend/routers/chapter_outlines.py backend/main.py backend/tests/unit/test_chapter_outline_service.py backend/tests/api/test_chapter_outline_routes.py backend/tests/integration/test_chapter_outline_lifecycle.py backend/tests/api/test_public_domain_errors.py backend/tests/unit/test_archived_write_inventory.py
git commit -m "feat: add manual chapter outline workflow"
```

### Task 6: Define the safe Outline Provider boundary

**Files:**

- Create: `backend/prompts/chapter_outline.py`
- Create: `backend/gateways/chapter_outline_provider.py`
- Create: `backend/tests/unit/test_chapter_outline_prompt.py`
- Create: `backend/tests/unit/test_chapter_outline_gateway.py`
- Modify: `backend/tests/unit/test_provider_response_secret_scanning.py`

- [ ] **Step 1: Write prompt and gateway RED tests**

Define the closed manifest:

```python
class PlanningAuthority(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    revision_id: str
    revision: int
    content_hash: str

class ProjectionAuthority(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    revision: int
    content_hash: str

class PublicBindingAuthority(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    revision_id: str
    revision: int
    content_hash: str
    provider_id: str
    model_name: str

class ChapterOutlineGenerationManifest(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    schema_version: Literal["chapter-outline-generation-v1"] = "chapter-outline-generation-v1"
    chapter_number: int
    planning: PlanningAuthority
    canon_revision: int
    projection: ProjectionAuthority
    story_block: StoryBlock
    allowed_stages: tuple[Stage, ...]
    allowed_scene_tasks: tuple[SceneTask, ...]
    volume: Volume
    plots: tuple[Plot, ...]
    capacity_policy: OutlineCapacityPolicy
    draft_revision: int
    draft_hash: str
    author_instructions: str
    binding: PublicBindingAuthority
```

Require the gateway:

```python
class ChapterOutlineProvider(Protocol):
    async def generate(
        self,
        *,
        provider: PublicProviderRuntime,
        model_name: str,
        manifest: ChapterOutlineGenerationManifest,
    ) -> EditableChapterOutlineContent: ...
```

Test deterministic byte budget, secret scan before hashing/call, one strict structured parse, no raw response persistence/logging, and fixed safe failure categories.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_prompt.py backend/tests/unit/test_chapter_outline_gateway.py backend/tests/unit/test_provider_response_secret_scanning.py -q
```

- [ ] **Step 3: Implement the production gateway**

Reuse the backend AI client and `planning` task binding. The prompt asks for one
complete `EditableChapterOutlineContent`, preserves the exact allowed node refs,
and explicitly forbids inventing IDs. Publish attaches the server-owned chapter,
Planning, Canon/Projection, and capacity basis and validates it through the
strict `DraftChapterOutline`. The prompt never embeds API keys, raw corpus
passages, or internal database fields.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_prompt.py backend/tests/unit/test_chapter_outline_gateway.py backend/tests/unit/test_provider_response_secret_scanning.py -q
git add -- backend/prompts/chapter_outline.py backend/gateways/chapter_outline_provider.py backend/tests/unit/test_chapter_outline_prompt.py backend/tests/unit/test_chapter_outline_gateway.py backend/tests/unit/test_provider_response_secret_scanning.py
git commit -m "feat: add chapter outline provider boundary"
```

### Task 7: Implement Outline generation and unify supersession semantics

**Files:**

- Create: `backend/services/chapter_outline_generation.py`
- Modify: `backend/repositories/planning.py`
- Modify: `backend/services/planning_generation.py`
- Modify: `backend/routers/chapter_outlines.py`
- Modify: `backend/main.py`
- Create: `backend/tests/unit/test_chapter_outline_generation_service.py`
- Create: `backend/tests/integration/test_chapter_outline_generation.py`
- Modify: `backend/tests/unit/test_planning_repository.py`
- Modify: `backend/tests/unit/test_planning_generation_service.py`
- Modify: `backend/tests/integration/test_planning_generation.py`
- Modify: `backend/tests/api/test_chapter_outline_routes.py`
- Modify: `backend/tests/api/test_route_inventory.py`
- Modify: `backend/tests/integration/test_project_archive.py`
- Modify: `backend/tests/unit/test_main_lifespan.py`

- [ ] **Step 1: Write generation RED tests**

Define:

```python
@dataclass(frozen=True)
class GenerateChapterOutline:
    project_id: str
    chapter_number: int
    draft_id: str
    draft_revision: int
    draft_hash: str
    idempotency_key: str
    author_instructions: str

@dataclass(frozen=True)
class ChapterOutlineOperationResult:
    operation_id: str
    status: Literal["pending", "succeeded", "failed", "superseded"]
    failure_code: str | None
    model: PublicModelSummary
    loaded: bool
    loaded_draft_revision: int | None
```

Expose generation only through:

```text
POST /api/projects/{pid}/chapter-outlines/{chapter_number}/drafts/{draft_id}/generate
GET  /api/projects/{pid}/chapter-outlines/operations/by-key/{idempotency_key}
GET  /api/projects/{pid}/chapter-outlines/operations/{operation_id}
```

Cover same-key replay, different-fingerprint conflict, one pending attempt, expired lease, cancellation, Provider/parse failure, Draft save during generation, chapter/Planning/Canon/Projection/binding/lifecycle drift, stale fence, exact successful load, and read-only operation lookup with no hidden retry.

Because Task 6 made Provider gateways explicit lifecycle resources, registering
the Outline generation service also registers one exact production Outline
gateway handle. The FastAPI lifespan starts it after the Planning gateway and
closes it before the Planning gateway. Cover partial startup rollback, repeated
lifespans, active-call drain, cleanup failure, and repeated shutdown
cancellation. Do not create a second Outline gateway in `main.py`.

- [ ] **Step 2: Add Planning drift regression RED tests**

Change the existing Planning expectation:

```python
assert result.status == "superseded"
assert result.loaded is False
assert result.loaded_draft_revision is None
```

The repository must terminally supersede before returning; `succeeded, loaded=false` is no longer legal for authority drift.

Delete the now-dead standalone
`PlanningRepository.succeed_generation_attempt()` method and its old
repository contract. Planning success continues to occur only inside
`load_generation_result_into_draft()`; the drift branch calls
`supersede_generation_attempt()` with the same operation/fence CAS.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_generation_service.py backend/tests/integration/test_chapter_outline_generation.py backend/tests/unit/test_planning_repository.py backend/tests/unit/test_planning_generation_service.py backend/tests/integration/test_planning_generation.py backend/tests/api/test_chapter_outline_routes.py -q
```

- [ ] **Step 4: Implement reserve, call, publish**

Reserve transaction:

```text
project -> chapter authority -> Planning -> Canon/Projection
-> Outline Head/Draft -> planning binding/provider
-> idempotency -> live lease -> fencing token -> commit
```

Call `ChapterOutlineProvider.generate()` after the transaction closes.

Publish transaction:

```text
project -> chapter authority -> Planning -> Canon/Projection
-> Outline Head/Draft -> binding -> attempt -> validate output
-> joined CAS loads exact Draft and marks attempt succeeded -> commit
```

This follows the approved global lock order. A non-locking lookup may recover
the project identity for an operation, but every `FOR UPDATE` attempt lock and
every terminal attempt update occurs only after the project and upstream
authority locks. Reserve, publish, failure settlement, confirmation, Session
creation, and archive paths must never acquire project and attempt locks in the
opposite order.

Any authority drift calls `supersede_attempt`; Provider/parse failures call
`fail_attempt`; only the joined Draft/attempt CAS can produce
`succeeded, loaded=true`.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_generation_service.py backend/tests/integration/test_chapter_outline_generation.py backend/tests/unit/test_planning_repository.py backend/tests/unit/test_planning_generation_service.py backend/tests/integration/test_planning_generation.py backend/tests/api/test_chapter_outline_routes.py backend/tests/api/test_route_inventory.py backend/tests/integration/test_project_archive.py backend/tests/unit/test_main_lifespan.py -q
git add -- backend/services/chapter_outline_generation.py backend/repositories/planning.py backend/services/planning_generation.py backend/routers/chapter_outlines.py backend/main.py backend/tests/unit/test_chapter_outline_generation_service.py backend/tests/integration/test_chapter_outline_generation.py backend/tests/unit/test_planning_repository.py backend/tests/unit/test_planning_generation_service.py backend/tests/integration/test_planning_generation.py backend/tests/api/test_chapter_outline_routes.py backend/tests/api/test_route_inventory.py backend/tests/integration/test_project_archive.py backend/tests/unit/test_main_lifespan.py
git commit -m "feat: generate chapter outlines safely"
```

### Task 8: Add Outline API state to the single Planning Store and page

**Files:**

- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/planningStore.js`
- Create: `frontend/src/application/planning/chapterOutlineController.js`
- Create: `frontend/src/components/planning/ChapterOutlineWorkspace.vue`
- Create: `frontend/src/components/planning/ChapterOutlineHistoryDrawer.vue`
- Modify: `frontend/src/components/planning/PlanningWorkspace.vue`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Modify: `frontend/tests/unit/planningStore.test.mjs`
- Create: `frontend/tests/unit/chapterOutlineController.test.mjs`
- Create: `frontend/tests/unit/chapterOutlineWorkspace.test.mjs`
- Modify: `frontend/tests/unit/planningWorkspaceSfc.test.mjs`

- [ ] **Step 1: Write API RED tests**

Require:

```javascript
api.chapterOutlines.current(projectId)
api.chapterOutlines.get(projectId, chapterNumber)
api.chapterOutlines.history(projectId, chapterNumber)
api.chapterOutlines.createDraft(projectId, chapterNumber)
api.chapterOutlines.saveDraft(projectId, chapterNumber, draftId, command)
api.chapterOutlines.confirmDraft(projectId, chapterNumber, draftId, command)
api.chapterOutlines.generateDraft(projectId, chapterNumber, draftId, command)
api.chapterOutlines.getOperation(projectId, operationId)
api.chapterOutlines.getOperationByKey(projectId, idempotencyKey)
```

Validate positive chapter numbers, opaque IDs/keys, strict public operation projection, timeout only on generation, and no hidden Provider fields.

- [ ] **Step 2: Write Store and controller RED tests**

Add Outline child refs to `planningStore`:

```javascript
outlineState
outlineHistory
outlineLocalContent
outlineDirty
outlineLoading
outlineSaving
outlineConfirming
outlineGenerating
outlineReconciling
outlineOperation
outlineRecoveryKey
outlineOutcomeUnknown
outlineAwaitingAuthority
```

Test context fencing, manual create/edit/save, no auto-version on typing, confirm, immutable history, unknown-result GET reconciliation, exact authoritative load, superseded non-overwrite, preserved local edits, model-unready manual work, and combined leave protection.

- [ ] **Step 3: Run RED**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/planningStore.test.mjs frontend/tests/unit/chapterOutlineController.test.mjs frontend/tests/unit/chapterOutlineWorkspace.test.mjs frontend/tests/unit/planningWorkspaceSfc.test.mjs
```

- [ ] **Step 4: Implement one Store with separate local locks**

Planning AI locks only the Planning editor. Outline AI locks only the Outline editor. Planning confirmation, Outline confirmation, and Session creation use the global operation overlay. Same-project tab changes preserve both dirty states and author instructions.

The Outline controller exposes:

```javascript
createManualDraft()
editLocal(content)
save()
generate()
reconcile()
confirm()
openHistory()
closeHistory()
```

- [ ] **Step 5: Implement the embedded Outline workspace**

Render it below Story Blocks. The chapter number and authority identities are read-only. Node selectors use only server-returned active nodes and submit their exact IDs/revisions/hashes. Show fixed recovery links for missing Bible/Planning, drift, archived state, and Canon/Projection mismatch.

The editable form is closed to:

```text
volumeRef
storyBlockRef
stageRefs
sceneTaskRefs
chapterGoal
expectedCharacters
continuation
plannedTasks
scenes
forbiddenEarlyEvents
```

The combined leave guard checks Planning dirty state, Outline dirty state, both
author-instruction fields, both generation operations, unknown outcomes, and
pending authoritative reloads. It prompts once only when leaving Planning,
switching project, or unloading; all three Planning tabs remain prompt-free.

- [ ] **Step 6: Run GREEN and commit**

```powershell
npm --prefix frontend run test:unit
npm --prefix frontend run build
git add -- frontend/src/api/db/client.js frontend/src/stores/planningStore.js frontend/src/application/planning/chapterOutlineController.js frontend/src/components/planning/ChapterOutlineWorkspace.vue frontend/src/components/planning/ChapterOutlineHistoryDrawer.vue frontend/src/components/planning/PlanningWorkspace.vue frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/planningStore.test.mjs frontend/tests/unit/chapterOutlineController.test.mjs frontend/tests/unit/chapterOutlineWorkspace.test.mjs frontend/tests/unit/planningWorkspaceSfc.test.mjs
git commit -m "feat: add chapter outline workspace"
```

## Slice 3 — Authoritative chapter and Session

### Task 9: Make chapter number and active Session server-authoritative

**Files:**

- Modify: `backend/repositories/chapter_sessions.py`
- Modify: `backend/services/chapter_sessions.py`
- Modify: `backend/routers/chapter_sessions.py`
- Create: `backend/tests/integration/test_authoritative_chapter_session.py`
- Modify: `backend/tests/unit/test_chapter_session_repository.py`
- Modify: `backend/tests/unit/test_chapter_session_service.py`
- Modify: `backend/tests/api/test_chapter_session_routes.py`

- [ ] **Step 1: Write authority RED tests**

Reuse the two repository authority queries added in Task 4 and test the service
rule:

```python
def authoritative_chapter(active_session, max_final_chapter):
    if active_session is not None:
        return int(active_session["chapter_num"])
    if max_final_chapter is not None:
        return int(max_final_chapter) + 1
    return 1
```

Cover no history → 1, final chapter 7 → 8, active drafting chapter 4 → 4, same-authority replay, wrong URL conflict, two concurrent creates for different chapters, missing/current-drift Outline, and archived project denial.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_repository.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py backend/tests/integration/test_authoritative_chapter_session.py -q
```

- [ ] **Step 3: Serialize create-or-replay**

Inside `create_session()`:

```text
lock project
-> query active drafting Session across the project
-> calculate authoritative chapter from active Session/final chapters
-> reject requested chapter mismatch
-> read and validate current confirmed Outline
-> replay the matching Session or create Session + empty WorkingDraft
```

The browser’s `chapterNumber`, Planning, Outline, and Canon values remain
concurrency assertions, not authority sources. The Session router keeps the
fixed safe `ChapterSessionConflict`; the `chapter-outlines/current` read model
supplies the authoritative number and explicit target link used by the page.
Nothing silently redirects.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_repository.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py backend/tests/integration/test_authoritative_chapter_session.py -q
git add -- backend/repositories/chapter_sessions.py backend/services/chapter_sessions.py backend/routers/chapter_sessions.py backend/tests/unit/test_chapter_session_repository.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py backend/tests/integration/test_authoritative_chapter_session.py
git commit -m "feat: enforce authoritative chapter sessions"
```

### Task 10: Route project next action and Writer entry through Outline authority

**Files:**

- Modify: `backend/repositories/project_lifecycle.py`
- Modify: `backend/services/project_lifecycle.py`
- Modify: `backend/tests/unit/test_project_lifecycle_repository.py`
- Modify: `backend/tests/unit/test_project_lifecycle_service.py`
- Modify: `backend/tests/api/test_product_routes.py`
- Modify: `backend/tests/integration/test_project_archive.py`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: `frontend/src/stores/chapterSessionStore.js`
- Modify: `frontend/src/views/ChapterWriterView.vue`
- Modify: `frontend/tests/unit/projectPreparationOverview.test.mjs`
- Modify: `frontend/tests/unit/chapterSessionStore.test.mjs`
- Modify: `frontend/tests/unit/projectRouteSfcIntegration.test.mjs`

- [ ] **Step 1: Write backend next-action RED tests**

Extend the single preparation snapshot with active Session, maximum final chapter, authoritative chapter, current Outline Draft/Head, and pending Outline operation. Assert priority:

```text
active Session -> continue_writing
pending Planning/Outline operation -> recovery route
upstream Seed/Contract/Bible actions
Planning Draft -> continue_planning
missing/current-invalid Planning -> establish_planning
missing confirmed Outline -> prepare_chapter_outline
active Outline Draft -> continue_chapter_outline
confirmed current Outline -> start_chapter_session
```

Every actionable result includes a canonical backend target path.

- [ ] **Step 2: Write frontend entry RED tests**

The overview uses only `preparation.targetPath`. The Writer loads `/chapter-outlines/current` first, shows a read-only Outline summary, and:

```javascript
if (current.authoritativeChapterNumber !== routeChapterNumber) {
  showConflictWithExplicitLink(current.targetPath)
}
```

It creates a Session only from `current.confirmedOutline` pins. It never calculates `chapter + 1` or falls back to `projects.current_chapter`.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest backend/tests/unit/test_project_lifecycle_repository.py backend/tests/unit/test_project_lifecycle_service.py backend/tests/api/test_product_routes.py backend/tests/integration/test_project_archive.py -q
node --test frontend/tests/unit/projectPreparationOverview.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/projectRouteSfcIntegration.test.mjs
```

- [ ] **Step 4: Implement one authoritative entry**

Return fixed `nextAction`, `targetPath`, `authoritativeChapterNumber`, and reason codes from the backend. The Writer does not add formal Phase 4 three-column editing, streaming, revision comparison, or finalization.

- [ ] **Step 5: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_project_lifecycle_repository.py backend/tests/unit/test_project_lifecycle_service.py backend/tests/api/test_product_routes.py backend/tests/integration/test_project_archive.py -q
npm --prefix frontend run test:unit
git add -- backend/repositories/project_lifecycle.py backend/services/project_lifecycle.py backend/tests/unit/test_project_lifecycle_repository.py backend/tests/unit/test_project_lifecycle_service.py backend/tests/api/test_product_routes.py backend/tests/integration/test_project_archive.py frontend/src/views/ProjectOverviewView.vue frontend/src/stores/chapterSessionStore.js frontend/src/views/ChapterWriterView.vue frontend/tests/unit/projectPreparationOverview.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/projectRouteSfcIntegration.test.mjs
git commit -m "feat: open writing from confirmed outline"
```

### Task 11: Add the formal Phase 3C browser gate

**Files:**

- Create: `frontend/e2e/phase3c-story-blocks-outlines.spec.ts`
- Create: `frontend/e2e/playwright.phase3c.config.ts`
- Create: `frontend/e2e/run-phase3c.mjs`
- Create: `scripts/tests/phase3cSuite.test.mjs`
- Modify: `scripts/run-tests.mjs`
- Modify: `package.json`
- Modify: `frontend/package.json`

- [ ] **Step 1: Write the runner-contract RED test**

Require one Phase 3C runner/config/spec, random loopback ports, scheduler off, strict external-network fail-closed, fake Planning/Outline Provider gateways only, random disposable MySQL 8, `SELECT DATABASE()` ownership proof, runtime observer settlement, reverse cleanup, and secret scan.

Reject:

```javascript
const forbidden = [
  'page.request', 'page.route', 'page.evaluate',
  'fetch(', 'axios', 'usePlanningStore(', 'api.',
]
```

- [ ] **Step 2: Run RED**

```powershell
node --test scripts/tests/phase3cSuite.test.mjs
```

- [ ] **Step 3: Implement the UI-only workflow**

Cover:

1. model-unready manual StoryBlock/Stage/SceneTask creation and Planning confirmation;
2. manual Outline Draft/save/confirm and Session creation;
3. fake Outline AI exact-Draft load and unknown-result GET reconciliation;
4. Planning R2 supersedes an unpinned old Outline;
5. an existing Session keeps exact old Planning/Outline pins readable;
6. project overview, direct URL, Outline, Session, and Writer share one authoritative chapter;
7. archived, missing upstream, Canon/Projection mismatch, and wrong chapter URL fail closed;
8. refresh/back/forward across all three Planning routes;
9. API/log/artifact secret scan;
10. real Provider calls, product DB reads/writes, and live website access all remain zero.

- [ ] **Step 4: Run GREEN**

```powershell
node --test scripts/tests/phase3cSuite.test.mjs
npm run test:browser:phase3c
```

Expected cleanup evidence:

```text
database created = cleaned
database remaining = 0
owned process/port/temp root/Vite cache residue = 0
real provider calls = 0
product DB reads/writes = 0/0
```

- [ ] **Step 5: Commit**

```powershell
git add -- frontend/e2e/phase3c-story-blocks-outlines.spec.ts frontend/e2e/playwright.phase3c.config.ts frontend/e2e/run-phase3c.mjs scripts/tests/phase3cSuite.test.mjs scripts/run-tests.mjs package.json frontend/package.json
git commit -m "test: add phase three c browser gate"
```

### Task 12: Review, verify, and package Phase 3C acceptance

**Files:**

- Create: `docs/acceptance/2026-07-26-phase-3c-story-blocks-outlines.md`
- Modify: `CURRENT_PROJECT_STATE.md`
- Modify: `PRODUCT_DEVELOPMENT_PLAN.md`
- Modify: `DEVELOPMENT_LOG.md`
- Modify: `scripts/tests/phase3PlanContract.test.mjs`

- [ ] **Step 1: Run focused gates**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_domain.py backend/tests/unit/test_chapter_outline_repository.py backend/tests/unit/test_chapter_outline_service.py backend/tests/unit/test_chapter_outline_prompt.py backend/tests/unit/test_chapter_outline_gateway.py backend/tests/unit/test_chapter_outline_generation_service.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_outline_routes.py backend/tests/api/test_chapter_session_routes.py backend/tests/integration/test_chapter_outline_lifecycle.py backend/tests/integration/test_chapter_outline_generation.py backend/tests/integration/test_authoritative_chapter_session.py -q
node --test frontend/tests/unit/planningStore.test.mjs frontend/tests/unit/planningWorkspaceController.test.mjs frontend/tests/unit/storyBlockEditor.test.mjs frontend/tests/unit/chapterOutlineController.test.mjs frontend/tests/unit/chapterOutlineWorkspace.test.mjs frontend/tests/unit/projectPlanningView.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs scripts/tests/phase3cSuite.test.mjs
```

- [ ] **Step 2: Obtain sequential independent reviews**

First request a specification review and fix findings until Critical/Important/Minor = `0/0/0`. Only then request a quality review and fix findings until `0/0/0`. Return every finding to the same slice implementer, rerun focused tests, and repeat the corresponding review.

- [ ] **Step 3: Run the final package gates strictly serially**

```powershell
npm run test:browser:phase3c
npm test
npm run test:integration
npm run build
git diff --check
```

Stop at the first failure. Use systematic debugging and RED→GREEN before restarting all five gates from the beginning. Do not run MySQL or build gates in parallel.

- [ ] **Step 4: Verify owned-resource cleanup**

After browser and integration, check only owned Phase 3C process IDs, ports, temp roots, Vite cache directories, and databases named exactly `novel_creator_test_<32 lowercase hex>`. Never stop the normal local MySQL service and never inspect or clean the product database.

- [ ] **Step 5: Write only fresh evidence**

Record exact fresh exit codes, pass/skip/fail counts, browser scenario count, created/cleaned/remaining database counts, build module count, external call counts, and secret-scan findings. Update product state documents so Phase 3C is completed and Phase 3D is the next phase. Do not reuse Phase 3B numbers.

- [ ] **Step 6: Commit acceptance**

```powershell
git add -- docs/acceptance/2026-07-26-phase-3c-story-blocks-outlines.md CURRENT_PROJECT_STATE.md PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md scripts/tests/phase3PlanContract.test.mjs
git commit -m "test: accept story blocks and chapter outlines"
git show --check --stat --oneline HEAD
git status --short --branch
```

- [ ] **Step 7: Finish the development branch**

Use `finishing-a-development-branch`. Fetch and compare `origin/main`; do not force-push. If the normal main worktree is dirty, preserve it and use a separate clean integration worktree for a fast-forward or merge. Push only after fresh verification and report network failure honestly.

## Completion boundary

Phase 3C is complete only when the author can build a complete Planning aggregate, manually or explicitly with AI prepare and confirm the authoritative next-chapter Outline, and enter exactly one correctly pinned ChapterSession through the real UI.

Phase 3C does not claim Future Plan/Actual Progress projection, formal three-column writing UX, streamed chapter generation, candidate comparison/fusion, AI-taste review, conflict review, Canon extraction, finalization, real Provider readiness, product database readiness, or novel-content quality acceptance.
