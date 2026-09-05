# Project Metadata Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authors provide complete project metadata during blank creation and maintain it later from a real project settings page.

**Architecture:** Reuse the existing `projects` columns and `ProjectResult`. Broaden only the strict create request, add one CAS-protected metadata update command, and expose the same five-field form through a dedicated create dialog and settings view. Writer Core artifacts and candidate-to-Seed handoff remain unchanged.

**Tech Stack:** Python 3, FastAPI, Pydantic, MySQL repository boundary, Vue 3, Pinia, Vue Router, Node test runner, pytest.

---

### Task 1: Add strict backend create and metadata-update contracts

**Files:**
- Modify: `backend/services/project_lifecycle.py`
- Modify: `backend/repositories/projects.py`
- Modify: `backend/domain/routers/projects.py`
- Modify: `backend/tests/unit/test_project_creation.py`
- Modify: `backend/tests/api/test_product_routes.py`

- [ ] **Step 1: Write failing tests for full create input and CAS update**

Add API assertions that a full request reaches `CreateProject` unchanged:

```python
assert command.model_dump() == {
    "id": command.id,
    "title": "新项目",
    "genre": "东方奇幻",
    "description": "一部长期成长小说",
    "target_words": 3_000_000,
    "target_chapters": 900,
}
```

Add service tests for `UpdateProjectMetadata` proving: matching revision updates all fields and increments lifecycle revision; identical content is a no-op; stale revision conflicts; archived projects reject the write.

- [ ] **Step 2: Run focused backend tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_creation.py backend/tests/api/test_product_routes.py -q --basetemp .pytest-tmp/project-metadata-red
```

Expected: failures show the missing update command/route and the create route rejecting new fields.

- [ ] **Step 3: Implement the minimal backend command**

Add a strict frozen command:

```python
class UpdateProjectMetadata(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    project_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    genre: str = Field(max_length=120)
    description: str = Field(max_length=5_000)
    target_words: int = Field(gt=0)
    target_chapters: int = Field(gt=0)
    expected_lifecycle_revision: int = Field(ge=0)
```

Implement `ProjectLifecycleService.update_metadata()` using the existing active-project row lock and `_require_revision`. Add repository SQL that updates the five fields, increments `lifecycle_revision`, and guards on the expected revision.

- [ ] **Step 4: Expose strict request DTOs**

Broaden `ProjectCreate` with `genre`, `description`, `targetWords`, and `targetChapters` defaults. Add `ProjectMetadataUpdate` and:

```python
@router.put("/projects/{project_id}/settings")
async def update_project_settings(project_id: str, data: ProjectMetadataUpdate):
    return _convert_result(
        await _service.update_metadata(
            UpdateProjectMetadata(
                project_id=project_id,
                title=data.title,
                genre=data.genre,
                description=data.description,
                target_words=data.target_words,
                target_chapters=data.target_chapters,
                expected_lifecycle_revision=data.expected_lifecycle_revision,
            )
        )
    )
```

Keep the original title-only rename route available.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/services/project_lifecycle.py backend/repositories/projects.py backend/domain/routers/projects.py backend/tests/unit/test_project_creation.py backend/tests/api/test_product_routes.py
git commit -m "feat: add project metadata commands"
```

### Task 2: Close the frontend metadata transport and store boundary

**Files:**
- Create: `frontend/src/application/projects/projectMetadata.js`
- Create: `frontend/tests/unit/projectMetadata.test.mjs`
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/projectStore.js`
- Modify: `frontend/tests/unit/projectOverviewApi.test.mjs`
- Modify: `frontend/tests/unit/projectStore.test.mjs`

- [ ] **Step 1: Write failing boundary and store tests**

Lock a five-field public payload with defaults and local Chinese validation. Assert that create sends only:

```javascript
{
  title: '新项目',
  genre: '东方奇幻',
  description: '一部长期成长小说',
  targetWords: 3000000,
  targetChapters: 900,
}
```

Assert settings update additionally sends `expectedLifecycleRevision`, replaces only the server-returned project, and clears the matching overview cache.

- [ ] **Step 2: Run focused frontend tests and verify RED**

```powershell
node --test frontend/tests/unit/projectMetadata.test.mjs frontend/tests/unit/projectOverviewApi.test.mjs frontend/tests/unit/projectStore.test.mjs
```

- [ ] **Step 3: Implement the transport and store methods**

Export `normalizeProjectMetadata()` and `validateProjectMetadata()` from the new application module. Change the client to strict picked fields:

```javascript
create: data => post('/projects', projectMetadataPayload(data)),
updateSettings: (projectId, data) => put(
  `/projects/${segment(projectId)}/settings`,
  projectMetadataUpdatePayload(data),
),
```

Change `createProject` to accept the metadata object and add serialized `updateProjectSettings` using the existing per-project mutation queue.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/application/projects/projectMetadata.js frontend/tests/unit/projectMetadata.test.mjs frontend/src/api/db/client.js frontend/src/stores/projectStore.js frontend/tests/unit/projectOverviewApi.test.mjs frontend/tests/unit/projectStore.test.mjs
git commit -m "feat: add project metadata frontend boundary"
```

### Task 3: Build complete blank creation and project settings UI

**Files:**
- Create: `frontend/src/components/projects/ProjectCreateDialog.vue`
- Create: `frontend/src/views/ProjectSettingsView.vue`
- Create: `frontend/tests/unit/projectCreateDialog.test.mjs`
- Create: `frontend/tests/unit/projectSettingsView.test.mjs`
- Modify: `frontend/src/views/ProjectLibraryView.vue`
- Modify: `frontend/src/composables/projectLibraryControllers.js`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/tests/unit/projectLibraryViews.test.mjs`
- Modify: `frontend/tests/unit/projectRoutes.test.mjs`
- Modify: `frontend/tests/unit/projectRouteSfcIntegration.test.mjs`
- Modify: `frontend/tests/unit/productShell.test.mjs`

- [ ] **Step 1: Write failing component and route tests**

Assert the create dialog displays all five fields, defaults to 2,400,000/720, keeps input after failure, and emits one normalized payload. Assert the settings route and sidebar item exist for active and archived projects, with archived inputs disabled.

- [ ] **Step 2: Run focused UI tests and verify RED**

```powershell
node --test frontend/tests/unit/projectCreateDialog.test.mjs frontend/tests/unit/projectSettingsView.test.mjs frontend/tests/unit/projectLibraryViews.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
```

- [ ] **Step 3: Implement the creation dialog**

Use ordinary labeled HTML controls and one submit action. Keep `ProjectNameDialog` for rename. Wire library creation as:

```javascript
async function create(metadata) {
  const created = await store.createProject(metadata)
  await router.push(projectOverviewPath(created.id))
}
```

- [ ] **Step 4: Implement project settings**

Use `useRouteProject()` and the Project Store. Hydrate local fields from the authoritative project, detect dirty state, save with its exact `lifecycleRevision`, retain values on failure, and replace them only with the successful response. Render archived projects read-only.

- [ ] **Step 5: Register the page in routing and shell navigation**

Add `projectSettingsPath(projectId)`, route name `ProjectSettings`, route title, and one “项目设置” item under “项目配置”.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Step 2 command plus `frontend/tests/unit/projectRouteSfcIntegration.test.mjs`. Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/components/projects/ProjectCreateDialog.vue frontend/src/views/ProjectSettingsView.vue frontend/tests/unit/projectCreateDialog.test.mjs frontend/tests/unit/projectSettingsView.test.mjs frontend/src/views/ProjectLibraryView.vue frontend/src/composables/projectLibraryControllers.js frontend/src/router/projectRoutes.js frontend/src/components/layout/productShell.js frontend/tests/unit/projectLibraryViews.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/projectRouteSfcIntegration.test.mjs frontend/tests/unit/productShell.test.mjs
git commit -m "feat: complete project metadata experience"
```

### Task 4: Regression, build, review, and delivery

**Files:**
- Verify every file changed in Tasks 1–3.

- [ ] **Step 1: Run impacted regression tests**

Run all project lifecycle, project store, route, shell, topic handoff, and overview test files. Expected: zero failures.

- [ ] **Step 2: Run full repository verification**

```powershell
npm test
npm run build
git diff --check
```

Expected: backend, script, and frontend suites pass; Vite build succeeds; no whitespace errors.

- [ ] **Step 3: Review scope**

Confirm no schema files, Writer Core state, seed selection, contract, Bible, Planning, Canon, Projection, Provider, or database data were changed.

- [ ] **Step 4: Merge and push**

After review is Ready, fast-forward `codex/project-metadata-settings` into `main`, rerun the affected tests on `main`, push `origin/main`, and remove only this worktree and feature branch.
