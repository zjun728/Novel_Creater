# Phase 1 Product Shell and Project Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary single-path frontend with the first production product shell and deliver a complete, testable project lifecycle: create by title, open, rename, archive with undo, restore, and permanently delete only from the archived-projects page.

**Architecture:** The route is the source of project context, Pinia owns list/detail cache state, and FastAPI exposes explicit lifecycle commands backed by one transactional service. The project's writing workflow `status` stays independent from `archived_at`; a hidden `lifecycle_revision` gives archive, restore, and permanent delete compare-and-swap semantics. Archived projects remain readable through a dedicated read model but all product writes use the shared active-project lock. Permanent deletion is an explicit ownership operation: project-private rows cascade with the project, cross-project clone provenance is detached with `SET NULL`, and shared provider/asset/corpus rows are never deleted. Unit and API tests run without a provider; MySQL and Playwright tests use a fresh disposable MySQL 8 database and runner-owned services.

**Tech Stack:** Vue 3, Vue Router 4, Pinia 3, Naive UI, Node test runner, Playwright, FastAPI, Pydantic 2, aiomysql, pytest, MySQL 8.

---

## Delivery constraints

- Work only from clean `main@12b2e6a` or a later commit containing this plan.
- Use branch `codex/product-shell-lifecycle` in
  `C:\Users\zhangjun\.codex\worktrees\product-shell-lifecycle\Novel_Creater`.
- Do not copy untracked files from another worktree.
- Do not start or query the product database. Integration and browser tests must
  create a database matching `^novel_creator_test_[a-f0-9]{32}$` and drop it.
- Do not call any provider/model in Phase 1.
- Do not add compatibility redirects for `/project/:id`,
  `/writer/:projectId/:chapterNum?`, or the old `/settings` route. Unknown and
  retired URLs render `NotFoundView`.
- Do not expose provider secrets in responses, logs, errors, screenshots, or
  test artifacts.
- Do not add dead Phase 2–6 navigation entries. Stage 1 only exposes working
  destinations.
- Test behavior through imported functions and rendered/browser behavior. A
  source-regex assertion may supplement but never replace a behavioral test.

## Frozen Phase 1 behavior

- `/` redirects to `/projects`.
- Active project cards are not clickable containers.
- A project with a resumable chapter session shows primary `继续写作` and
  secondary `打开项目`; all other projects show only `打开项目`.
- Create and rename forms contain one field: `项目名称`.
- Archive executes immediately, shows a non-blocking toast, and offers `撤销`.
- Restore executes immediately.
- Permanent delete appears only at `/projects/archived`, requires exactly one
  red danger dialog, and the server rejects deletion of an active project.
- A route for an archived project renders a read-only status page with
  `恢复项目` and `返回项目库`.
- Route parameters restore project context after browser refresh. Leaving a
  project page does not erase a still-valid project cache.
- Success, info, and warning feedback use Toast. Form validation is inline.
  Only destructive or genuine decision points use Dialog.
- All server-side writes reject archived projects even when called without the
  frontend.

### Task 1: Establish the project ownership schema

**Files:**

- Modify: `backend/schema/10_core.sql`
- Modify: `backend/schema/20_contracts.sql`
- Modify: `backend/schema/30_planning.sql`
- Modify: `backend/schema/40_drafts.sql`
- Modify: `backend/schema/50_canon.sql`
- Modify: `backend/schema/60_projections.sql`
- Modify: `backend/schema/70_corpus.sql`
- Modify: `backend/schema_version.py`
- Modify: `backend/repositories/project_lifecycle.py`
- Modify: `backend/repositories/projects.py`
- Modify: `backend/repositories/model_bindings.py`
- Modify: `backend/scripts/reset_writer_core_data.py`
- Modify: `backend/scripts/run_milestone2_product_session.py`
- Modify: `backend/tests/unit/test_schema_version.py`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Rewrite: `backend/tests/unit/test_reset_writer_core_data.py`
- Modify: `backend/tests/unit/test_run_milestone2_product_session.py`
- Modify: `backend/tests/unit/test_project_lifecycle_repository.py`
- Modify: `backend/tests/unit/test_project_creation.py`
- Create: `backend/tests/unit/test_frozen_writer_core_v11.py`
- Create: `backend/tests/support/frozen_writer_core_v11.py`
- Create: `backend/tests/fixtures/writer_core_v11_schema.sql.gz.b64`
- Modify: `backend/tests/integration/test_project_archive.py`
- Rewrite: `backend/tests/integration/test_milestone2_product_rebuild.py`
- Create: `backend/tests/integration/test_project_ownership_delete.py`

- [ ] **Step 1: Write the schema contract tests**

Add unit assertions for:

```python
assert EXPECTED_SCHEMA_VERSION == "writer-core-v1.2.0"
assert "archived_at BIGINT NULL" in project_statement
assert "lifecycle_revision INT NOT NULL DEFAULT 0" in project_statement
assert (
    "FOREIGN KEY (source_project_id) REFERENCES projects(id) "
    "ON DELETE SET NULL"
) in binding_revision_statement
```

Add a MySQL integration test that initializes a fresh schema, creates two
projects, gives the second project a binding revision cloned from the first,
populates every project-private table in the ownership graph, and adds shared
style-template, experience-card, corpus-fragment, and corpus-import descendants.
Before deleting the source project, attempt representative cross-project parent
references from the seed, binding, contract, planning, draft/finalization,
Canon, projection, and reference-use families and assert that every insert is
rejected. Then execute:

```python
await session.execute("DELETE FROM projects WHERE id=%s", (source_project_id,))
remaining = await session.fetchone(
    "SELECT id FROM projects WHERE id=%s", (source_project_id,)
)
clone = await session.fetchone(
    """SELECT source_project_id FROM project_model_binding_revisions
       WHERE project_id=%s ORDER BY revision DESC LIMIT 1""",
    (clone_project_id,),
)
assert remaining is None
assert clone["source_project_id"] is None
```

After deletion, assert every project-private table has no source-project rows,
the clone revision remains with a null source, and every shared row and shared
descendant remains.

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
python -m pytest backend/tests/unit/test_schema_version.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_run_milestone2_product_session.py backend/tests/integration/test_project_ownership_delete.py -q
```

Expected: unit assertions fail because the version is `writer-core-v1.1.0`
and archive metadata is absent; the integration deletion is blocked by current
`RESTRICT` ownership edges.

- [ ] **Step 3: Encode ownership instead of a manual delete list**

Keep writing workflow status independent from archival state. In `projects`,
change the status constraint and add:

```sql
archived_at BIGINT NULL,
lifecycle_revision INT NOT NULL DEFAULT 0,
CHECK (status IN ('drafting','active','completed')),
CHECK (lifecycle_revision >= 0)
```

Set direct project ownership edges to `ON DELETE CASCADE`. Set
`project_model_binding_revisions.source_project_id` to `ON DELETE SET NULL`.
Set project-private parent/child edges to `ON DELETE CASCADE` so deleting a
project cannot be blocked by its own contract, draft, Canon, projection, or
citation history. Keep references to shared rows—provider profiles, style
templates, experience cards, corpus sources, and corpus chapters—non-cascading;
project deletion must not delete shared assets.

For every project-private child that also stores `project_id`, scope its parent
foreign key as `(project_id, parent_id)` and add the matching parent
`UNIQUE (project_id, id)` key. A globally valid parent ID from another project
must never satisfy a private child edge.

Set:

```python
EXPECTED_SCHEMA_VERSION = "writer-core-v1.2.0"
```

Replace active-project predicates with `archived_at IS NULL`; archived reads
use `archived_at IS NOT NULL`. Do not add an `ALTER TABLE` migration. This
product has no runtime compatibility requirement; only a newly initialized
database is valid for v1.2.0.

Keep the writer asset package version at `writer-core-v1.1.0`; schema and asset
package versions are separate contracts. Replace the M2 session script's
hard-coded schema comparison with `EXPECTED_SCHEMA_VERSION`.

Rewrite the explicit development reset command so it recognizes exactly the
frozen current product source (`writer-core-v1.1.0` plus its frozen manifest)
and the new v1.2 target. Remove the older M1 v1.0 branch and its mapping code.
Build reset integration sources from a repository-contained snapshot of the
actual v1.1 DDL, protected by its raw SQL, compressed payload, manifest, and
49-table inventory hashes. The test fixture initializer must reject every
non-disposable database name before issuing `USE` or any DDL.
This one-time, explicitly confirmed rebuild path is not imported by runtime.
It preserves only the approved project identity, three seeds, and provider
configuration; it must never run as part of this phase's tests against the
product database.

- [ ] **Step 4: Run the focused schema tests**

Run:

```powershell
python -m pytest backend/tests/unit/test_schema_version.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_run_milestone2_product_session.py backend/tests/integration/test_project_ownership_delete.py -q
python -m pytest backend/tests/unit/test_frozen_writer_core_v11.py -q
python -m pytest backend/tests/unit/test_project_lifecycle_repository.py backend/tests/unit/test_project_creation.py -q
python -m pytest backend/tests/integration/test_project_archive.py -q
python -m pytest backend/tests/integration/test_milestone2_product_rebuild.py -q
```

Expected: PASS. Archive writes preserve workflow status and use
`archived_at`; the frozen v1.1 reset fixture rebuilds to v1.2; all test
databases are removed by their fixtures.

- [ ] **Step 5: Commit**

```powershell
git add backend/schema backend/schema_version.py backend/repositories/project_lifecycle.py backend/repositories/projects.py backend/repositories/model_bindings.py backend/scripts/reset_writer_core_data.py backend/scripts/run_milestone2_product_session.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_run_milestone2_product_session.py backend/tests/unit/test_project_lifecycle_repository.py backend/tests/unit/test_project_creation.py backend/tests/unit/test_frozen_writer_core_v11.py backend/tests/support/frozen_writer_core_v11.py backend/tests/fixtures/writer_core_v11_schema.sql.gz.b64 backend/tests/integration/test_project_archive.py backend/tests/integration/test_milestone2_product_rebuild.py backend/tests/integration/test_project_ownership_delete.py
git commit -m "feat: define project lifecycle ownership"
```

### Tasks 2–3: Replace the backend project lifecycle atomically

The old `backend/services/projects.py` module is imported by the current HTTP
layer, scripts, and lifecycle integration tests. Service replacement and the
explicit HTTP API therefore form one implementation, verification, review, and
commit gate. No intermediate commit may delete the old service while leaving a
direct consumer broken, and no compatibility shim is permitted.

**Files:**

- Modify: `backend/http_errors.py`
- Modify: `backend/repositories/project_lifecycle.py`
- Modify: `backend/repositories/projects.py`
- Create: `backend/services/project_lifecycle.py`
- Delete: `backend/services/projects.py`
- Modify: `backend/tests/unit/test_project_lifecycle_repository.py`
- Modify: `backend/tests/unit/test_project_creation.py`
- Create: `backend/tests/unit/test_project_lifecycle_service.py`
- Modify: `backend/routers/projects.py`
- Modify: `backend/tests/api/test_product_routes.py`
- Modify: `backend/tests/api/test_route_inventory.py`
- Modify: `backend/tests/api/test_public_domain_errors.py`
- Modify: `backend/scripts/prepare_milestone1_browser_db.py`
- Modify: `backend/scripts/prepare_milestone2_browser_db.py`
- Modify: `backend/scripts/reset_writer_core_data.py`
- Modify: `backend/scripts/verify_milestone2_product.py`
- Modify: `backend/tests/integration/test_model_binding_revisions.py`
- Modify: `backend/tests/integration/test_milestone2_product_rebuild.py`
- Modify: `backend/tests/integration/test_project_archive.py`
- Modify: `backend/tests/unit/test_verify_milestone2_product.py`

The additional script and test files above are direct import consumers of the
deleted service. They move to `ProjectLifecycleService` in the same atomic gate;
they do not restore old CRUD behavior.

- [ ] **Step 1: Write domain, repository, HTTP, and real race tests**

Cover:

- title-only creation uses internal defaults `genre=""`,
  `description=""`, `target_words=100000`, `target_chapters=100`;
- active and archived lists are disjoint;
- any-status read distinguishes missing from archived;
- archive preserves workflow status, stores the archive timestamp, and
  increments lifecycle revision;
- archive rejects a project with `story_engine_batches.status` in
  `reserved`, `running`, or `outcome_unknown`;
- restore clears only the archive timestamp and increments lifecycle revision;
- rename changes only `title`;
- permanent delete locks an archived project and deletes it;
- permanent delete of active, missing, or busy projects returns a stable domain
  error.
- same-title rename succeeds without relying on MySQL affected-row count;
- lifecycle command JSON accepts only an exact integer, rejecting booleans,
  floats, strings, missing fields, and extra fields;
- two independent MySQL transactions cover both rename/archive lock orders,
  same-revision double archive/restore/delete, and both archive/reservation lock
  orders without sleeps or mocked connections.

Use explicit error types:

```python
class ProjectArchived(PublicDomainError):
    status_code = 409
    code = "ProjectArchived"
    message = "Project is archived"

class ProjectLifecycleConflict(PublicDomainError):
    status_code = 409
    code = "ProjectLifecycleConflict"
    message = "Project lifecycle changed; refresh and retry"

class ProjectBusy(PublicDomainError):
    status_code = 409
    code = "ProjectBusy"
    message = "Project has an unfinished operation"
```

- [ ] **Step 2: Run both focused groups and race tests, then verify failure**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_lifecycle_repository.py backend/tests/unit/test_project_creation.py backend/tests/unit/test_project_lifecycle_service.py -q
python -m pytest backend/tests/api/test_product_routes.py backend/tests/api/test_route_inventory.py backend/tests/api/test_public_domain_errors.py -q
python -m pytest backend/tests/integration/test_project_archive.py -q
```

Expected: FAIL because restore, archived reads, busy guards, and permanent
delete do not exist, `CreateProject` still requires old public fields, the old
router still maps `DELETE` to archive, lifecycle JSON is coercive, and the real
race invariants are not yet protected.

- [ ] **Step 3: Add shared lifecycle reads and locks**

In `project_lifecycle.py`, add:

```python
async def read_project(session, project_id: str):
    return await session.fetchone(
        "SELECT * FROM projects WHERE id=%s",
        (project_id,),
    )

async def lock_project(session, project_id: str):
    return await session.fetchone(
        "SELECT * FROM projects WHERE id=%s FOR UPDATE",
        (project_id,),
    )
```

Keep `read_active_project` and `lock_active_project` as the only helpers used by
ordinary product mutations. When an any-status row exists but is archived,
services raise `ProjectArchived`; missing IDs raise `ProjectNotFound`.

- [ ] **Step 4: Implement explicit lifecycle repository methods**

Implement the exact repository surface `list_active(session)`,
`list_archived(session)`, `get_any(session, project_id)`,
`lock_any(session, project_id)`,
`has_unfinished_operation(session, project_id)`,
`archive(session, project_id, expected_revision)`,
`restore(session, project_id, expected_revision)`, and
`permanently_delete(session, project_id, expected_revision)`.

Archive must be one conditional update:

```sql
UPDATE projects
SET archived_at=%s,
    lifecycle_revision=lifecycle_revision+1,
    updated_at=%s
WHERE id=%s AND archived_at IS NULL AND lifecycle_revision=%s
```

Restore clears `archived_at`, increments `lifecycle_revision`, and uses the
same compare-and-swap rule. Permanent delete is exactly:

```sql
DELETE FROM projects
WHERE id=%s AND archived_at IS NOT NULL AND lifecycle_revision=%s
```

The schema, not a Python table list, owns private-row cleanup.

- [ ] **Step 5: Implement the service and replace every direct consumer**

Make the create command title-focused:

```python
class CreateProject(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    genre: str = ""
    description: str = ""
    target_words: int = 100_000
    target_chapters: int = 100
```

Expose service methods:

```python
list_active()
list_archived()
get(project_id, include_archived=False)
rename(project_id, title)
archive(project_id, expected_lifecycle_revision)
restore(project_id, expected_lifecycle_revision)
permanently_delete(project_id, expected_lifecycle_revision)
```

`ProjectResult` includes `archived_at` and `lifecycle_revision` so the frontend
can perform the next CAS operation without a refetch. Put these operations in
`ProjectLifecycleService`; update imports, then delete the old
`backend/services/projects.py` rather than retaining two project services.
All commands use one transaction and a row lock. Do not retain
`ProjectService.delete()` or general-purpose `UpdateProject`.

Replace the project router in the same working tree state with exactly:

```text
GET    /api/projects
GET    /api/projects/archived
POST   /api/projects
GET    /api/projects/{project_id}
PUT    /api/projects/{project_id}
POST   /api/projects/{project_id}/archive
POST   /api/projects/{project_id}/restore
DELETE /api/projects/{project_id}
```

`ProjectCreate` and `ProjectRename` forbid extra fields.
`ProjectLifecycleCommand` uses strict validation and requires the exact
non-negative JSON integer `expectedLifecycleRevision`. Declare
`/projects/archived` before the dynamic project route. Permanent delete returns
`204`. Migrate all four scripts and every listed integration/unit consumer to
`ProjectLifecycleService`, then delete `backend/services/projects.py`.

- [ ] **Step 6: Run the single atomic verification gate**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_lifecycle_repository.py backend/tests/unit/test_project_creation.py backend/tests/unit/test_project_lifecycle_service.py -q
python -m pytest backend/tests/api/test_product_routes.py backend/tests/api/test_route_inventory.py backend/tests/api/test_public_domain_errors.py -q
python -m pytest backend/tests/integration/test_project_archive.py backend/tests/integration/test_model_binding_revisions.py -q
python -m pytest backend/tests/integration/test_project_archive.py -q
python -m pytest backend/tests/unit/test_prepare_milestone1_browser_db.py backend/tests/unit/test_prepare_milestone2_browser_db.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_verify_milestone2_product.py -q
rg "backend\.services\.projects|services\.projects|\bProjectService\b|\bUpdateProject\b" backend
```

Expected: both focused groups and all affected tests PASS, race tests PASS in at
least two consecutive runs with disposable-database residual zero, and `rg`
finds no forbidden import or retired class.

- [ ] **Step 7: Make one atomic commit only after the whole gate is green**

```powershell
git add backend/http_errors.py backend/repositories/project_lifecycle.py backend/repositories/projects.py backend/services/project_lifecycle.py backend/services/projects.py backend/routers/projects.py backend/tests/unit/test_project_lifecycle_repository.py backend/tests/unit/test_project_creation.py backend/tests/unit/test_project_lifecycle_service.py backend/tests/api/test_product_routes.py backend/tests/api/test_route_inventory.py backend/tests/api/test_public_domain_errors.py backend/scripts/prepare_milestone1_browser_db.py backend/scripts/prepare_milestone2_browser_db.py backend/scripts/reset_writer_core_data.py backend/scripts/verify_milestone2_product.py backend/tests/integration/test_model_binding_revisions.py backend/tests/integration/test_milestone2_product_rebuild.py backend/tests/integration/test_project_archive.py backend/tests/unit/test_verify_milestone2_product.py docs/superpowers/plans/2026-07-18-phase-1-product-shell-lifecycle.md
git commit -m "feat: add transactional project lifecycle api"
```

### Task 4: Close archived-project write gaps

**Files:**

- Modify: `backend/repositories/project_lifecycle.py`
- Modify: `backend/repositories/canon.py`
- Modify: `backend/services/canon.py`
- Modify: `backend/services/chapter_sessions.py`
- Modify: `backend/services/chapter_draft_generation.py`
- Modify: `backend/services/story_engines.py`
- Modify: `backend/tests/unit/test_canon_revision.py`
- Modify: `backend/tests/unit/test_canon_idempotency.py`
- Modify: `backend/tests/unit/test_chapter_session_service.py`
- Modify: `backend/tests/unit/test_chapter_draft_generation_service.py`
- Modify: `backend/tests/unit/test_story_engine_service.py`
- Modify: `backend/tests/unit/test_project_lifecycle_repository.py`
- Modify: `backend/tests/integration/test_project_archive.py`
- Modify: `backend/tests/support/canon_fakes.py`
- Modify: `backend/tests/support/story_engine_fakes.py`
- Create: `backend/tests/unit/test_archived_write_inventory.py`

- [ ] **Step 1: Add a behavioral write-fence matrix**

Extend MySQL integration coverage:

1. create and populate a project;
2. archive it;
3. attempt seed, binding, contract, planning, story-engine, chapter-session,
   working-draft save, candidate save, generated-draft result, story-engine
   outcome-unknown writeback, and Canon writes;
4. assert every call returns `ProjectArchived`;
5. restore it;
6. prove a normal write succeeds;
7. reserve a story-engine operation and assert archive returns `ProjectBusy`.

Add an explicit active-project write-entrypoint inventory. Invoke every entry
with a guard-probe repository, assert the guard is the first repository action,
and prove an archived error stops all downstream repository and Provider calls.
Do not inspect source text.

Add real disposable-MySQL generation/archive races using two independent
connections and an event-gated fake Provider:

- a successful generation holds the project row lock until its draft update
  commits, then archive completes;
- a failed generation rolls back, releases the lock, and archive completes
  without changing the original draft.

- [ ] **Step 2: Run focused tests and verify the known gaps**

Run:

```powershell
python -m pytest backend/tests/integration/test_project_archive.py backend/tests/unit/test_archived_write_inventory.py -q
```

Expected: FAIL for Canon commit, working-draft save, candidate save,
generated-working-draft, and story-engine outcome-unknown paths because they
do not all lock the active project before mutation or result writeback.

- [ ] **Step 3: Make the shared lock distinguish archived from missing**

Change `lock_active_project()` to lock the project row by ID first, then raise
`ProjectArchived` when `archived_at IS NOT NULL`. Return `None` only when the
project does not exist. Existing seed, binding, contract, planning,
story-engine, and chapter-session callers therefore retain their domain-specific
missing errors but receive the one uniform archive error.

```python
async def lock_active_project(session, project_id: str):
    row = await session.fetchone(
        "SELECT * FROM projects WHERE id=%s FOR UPDATE",
        (project_id,),
    )
    if row is not None and row["archived_at"] is not None:
        raise ProjectArchived()
    return row
```

- [ ] **Step 4: Fence every known unguarded write**

In `CanonRepository`:

```python
async def lock_project(self, session, project_id: str):
    return await lock_active_project(session, project_id)
```

At the start of `CanonService.commit()`, `save_working_draft()`,
`save_candidate()`, and `mark_outcome_unknown()`, inside their transaction and
before reading aggregate state:

```python
if await self.repository.lock_project(session, request.project_id) is None:
    raise ProjectNotFound()
```

For `ChapterDraftGenerationService.generate_working_draft()`, hold the
active-project row lock from preparation through the final draft update in the
current non-streaming service. This prevents archive from committing during a
provider operation. Phase 4 replaces this long transaction with the persistent
operation-lease and streaming protocol; Phase 1 must not invent a second
temporary provider path.

- [ ] **Step 5: Run the write-fence tests**

Run:

```powershell
python -m pytest backend/tests/unit/test_canon_revision.py backend/tests/unit/test_chapter_session_service.py backend/tests/unit/test_chapter_draft_generation_service.py backend/tests/unit/test_story_engine_service.py backend/tests/integration/test_project_archive.py backend/tests/unit/test_archived_write_inventory.py -q
```

Expected: PASS without provider calls.

- [ ] **Step 6: Commit**

```powershell
git add backend/repositories/project_lifecycle.py backend/repositories/canon.py backend/services/canon.py backend/services/chapter_sessions.py backend/services/chapter_draft_generation.py backend/services/story_engines.py backend/tests/unit/test_canon_revision.py backend/tests/unit/test_canon_idempotency.py backend/tests/unit/test_chapter_session_service.py backend/tests/unit/test_chapter_draft_generation_service.py backend/tests/unit/test_story_engine_service.py backend/tests/unit/test_project_lifecycle_repository.py backend/tests/integration/test_project_archive.py backend/tests/support/canon_fakes.py backend/tests/support/story_engine_fakes.py backend/tests/unit/test_archived_write_inventory.py docs/superpowers/plans/2026-07-18-phase-1-product-shell-lifecycle.md
git commit -m "fix: fence writes for archived projects"
```

### Tasks 5-6: Build lifecycle state and canonical route context atomically

**Files:**

- Modify: `frontend/src/api/db/client.js`
- Rewrite: `frontend/src/stores/projectStore.js`
- Create: `frontend/src/router/projectRoutes.js`
- Rewrite: `frontend/src/router/index.js`
- Create: `frontend/src/views/NotFoundView.vue`
- Create: `frontend/src/views/ProjectOverviewView.vue`
- Create: `frontend/src/views/ArchivedProjectStatusView.vue`
- Create: `frontend/src/views/ProviderSettingsView.vue`
- Create: `frontend/src/views/ProjectLibraryView.vue`
- Create: `frontend/src/views/ArchivedProjectsView.vue`
- Create: `frontend/src/composables/useRouteProject.js`
- Modify: `frontend/src/views/ChapterWriterView.vue`
- Modify: `frontend/src/components/settings/TaskModelBinding.vue`
- Create: `frontend/src/components/settings/projectBindingSelection.js`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Create: `frontend/tests/unit/projectLifecycleStore.test.mjs`
- Create: `frontend/tests/unit/projectRoutes.test.mjs`
- Create: `frontend/tests/unit/projectRouteSfcIntegration.test.mjs`
- Rewrite: `frontend/tests/unit/m1Navigation.test.mjs`
- Modify: `frontend/tests/unit/modelBindingStore.test.mjs`

The state rewrite and route replacement are one atomic implementation and
review gate. The old active router calls the retired store surface, so there
must not be a commit or handoff between the two halves.

- [ ] **Step 1: Write API and store tests, then verify RED**

Test these client calls:

```javascript
api.projects.listActive()
api.projects.listArchived()
api.projects.create({ title })
api.projects.get(projectId)
api.projects.rename(projectId, { title })
api.projects.archive(projectId, expectedLifecycleRevision)
api.projects.restore(projectId, expectedLifecycleRevision)
api.projects.permanentlyDelete(projectId, expectedLifecycleRevision)
```

Test the store with injected API fakes:

- separate `activeProjects` and `archivedProjects`;
- create/rename insert or replace only after a successful response;
- archive moves the project only after success;
- undo calls restore and returns the same project to the active list;
- failed lifecycle writes leave both lists and current project unchanged;
- an older `loadProject` response cannot overwrite a newer route context;
- late list or project reads cannot overwrite a newer lifecycle write;
- permanent delete removes only an archived project after server success and a
  late read cannot resurrect it;
- rename, archive, restore, and permanent delete for one project are sent and
  applied in invocation order, while different projects remain independent;
- a failed mutation does not poison the next queued mutation, and a later
  failure cannot erase an earlier successful mutation.

Run:

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/projectLifecycleStore.test.mjs
```

Expected: FAIL because the client has ambiguous `delete` semantics and the
store has a single list plus `invalidateOpenProject()`.

- [ ] **Step 2: Implement narrow API payloads and route-safe state**

Replace the project client block with:

```javascript
projects: {
  listActive: () => get('/projects'),
  listArchived: () => get('/projects/archived'),
  create: ({ title }) => post('/projects', { title }),
  get: projectId => get(`/projects/${segment(projectId)}`),
  rename: (projectId, { title }) => put(
    `/projects/${segment(projectId)}`,
    { title },
  ),
  archive: (projectId, expectedLifecycleRevision) => post(
    `/projects/${segment(projectId)}/archive`,
    { expectedLifecycleRevision },
  ),
  restore: (projectId, expectedLifecycleRevision) => post(
    `/projects/${segment(projectId)}/restore`,
    { expectedLifecycleRevision },
  ),
  permanentlyDelete: (projectId, expectedLifecycleRevision) => del(
    `/projects/${segment(projectId)}`,
    { expectedLifecycleRevision },
  ),
}
```

Remove `PROJECT_FIELDS` and `projects.delete`.

Expose:

```javascript
activeProjects
archivedProjects
currentProject
loadActiveProjects()
loadArchivedProjects()
loadProject(projectId)
createProject(title)
renameProject(projectId, title)
archiveProject(projectId, expectedLifecycleRevision)
restoreProject(projectId, expectedLifecycleRevision)
permanentlyDeleteProject(projectId, expectedLifecycleRevision)
```

Retain `createLatestRequestGuard`, but do not clear `currentProject` on route
component unmount. Replace it only from the latest route load or a successful
lifecycle mutation for that same project, and clear it only when that route
project is permanently deleted. Guard list loads and route loads so a response
started before a successful create, rename, archive, restore, or delete cannot
overwrite the committed lifecycle result.

When the route project ID changes, clear the prior `currentProject` before the
new read starts. A failed read for the new route remains empty; lifecycle
results for another project cannot repopulate or clear that route-owned slot.

Serialize the four project-ID lifecycle mutations through one per-project tail
queue. Store a rejection-swallowing continuation as the tail but return each
operation's original promise to its caller. Remove a settled tail only when it
is still the map entry for that project, so an older completion cannot delete a
newer chain. Project creation remains outside this queue because no project ID
exists before its response.

- [ ] **Step 3: Run the API and store tests**

Run:

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/projectLifecycleStore.test.mjs
```

Expected: PASS.

- [ ] **Step 4: Write pure route and context tests, then verify RED**

Assert builders:

```javascript
projectOverviewPath('a/b') === '/projects/a%2Fb/overview'
chapterWriterPath('p 1', 3) === '/projects/p%201/write/chapters/3'
```

Assert route matching:

- `/` resolves as redirect to `/projects`;
- `/projects`, `/projects/archived`, `/settings/providers`, and
  `/projects/:projectId/overview` are named routes;
- `/projects/:projectId/write/chapters/:chapterNumber` requires a chapter;
- `/project/old-id`, `/writer/old-id/1`, `/settings`, and arbitrary paths
  resolve to `NotFound`;
- a project-route refresh calls `loadProject(route.params.projectId)`;
- an archived response selects `ArchivedProjectStatusView`;
- a missing project selects `NotFoundView`;
- a real memory router lazy-loads and server-renders at least one route SFC
  through Vite's Vue transform.

The repository has no DOM mount harness (`@vue/test-utils`, `jsdom`, or
`happy-dom`), so this atomic gate uses Vue's server renderer and stubs only
Naive UI's visual components. DOM event behavior remains the browser gate's
responsibility; do not add a new test dependency for this task.

Run:

```powershell
node --test frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/m1Navigation.test.mjs
```

Expected: FAIL because old routes and wildcard-home redirect remain.

- [ ] **Step 5: Add the registry, route context, and minimal route shells**

Export frozen named path builders from `projectRoutes.js`. Define these Phase 1
routes:

```text
/projects
/projects/archived
/projects/:projectId/overview
/projects/:projectId/write/chapters/:chapterNumber
/settings/providers
/not-found
/:pathMatch(.*)*
```

The writer route may still render the existing `ChapterWriterView.vue` in this
phase, but it must use the canonical URL and a required positive chapter
number. Do not expose a navigation link until Phase 4 unless the project has a
real resumable session.

`useRouteProject()` observes `route.params.projectId`, calls
`store.loadProject()`, and returns explicit `loading`, `active`, `archived`,
`missing`, and `error` states. `ProjectOverviewView` renders only the active
overview shell. `ArchivedProjectStatusView` is read-only and exposes restore
and return actions.

Create minimal accessible `ProjectLibraryView` and `ArchivedProjectsView`
route shells that only load and summarize their corresponding lists. Task 7
adds cards, dialogs, and lifecycle interactions. Wrap only the existing
Provider/model component in `ProviderSettingsView`; migrate its active
`TaskModelBinding` child to `activeProjects` and `loadActiveProjects` without a
compatibility alias. Its initial selection may reuse `currentProject` only when
that ID is present in `activeProjects`; an archived current project falls back
to the first active project or an empty selection. Change the existing writer's
return action to `projectOverviewPath()`.

- [ ] **Step 6: Run the atomic frontend gate**

Run:

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/projectLifecycleStore.test.mjs
node --test frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/projectRouteSfcIntegration.test.mjs frontend/tests/unit/m1Navigation.test.mjs
npm --prefix frontend run test:unit
npm --prefix frontend run build
rg "PROJECT_FIELDS|api\.projects\.delete|invalidateOpenProject" frontend/src/api/db/client.js frontend/src/stores/projectStore.js
rg "path:\s*['\"]/project/|path:\s*['\"]/writer/|views/(HomeView|ProjectView|SettingsView)\.vue" frontend/src/router
```

Expected: all tests and the build pass. The final `rg` returns no active client,
store, or route match.

- [ ] **Step 7: Commit the atomic gate**

```powershell
git add docs/superpowers/plans/2026-07-18-phase-1-product-shell-lifecycle.md frontend/src/api/db/client.js frontend/src/stores/projectStore.js frontend/src/router frontend/src/views/NotFoundView.vue frontend/src/views/ProjectOverviewView.vue frontend/src/views/ArchivedProjectStatusView.vue frontend/src/views/ProviderSettingsView.vue frontend/src/views/ProjectLibraryView.vue frontend/src/views/ArchivedProjectsView.vue frontend/src/composables/useRouteProject.js frontend/src/views/ChapterWriterView.vue frontend/src/components/settings/TaskModelBinding.vue frontend/src/components/settings/projectBindingSelection.js frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/projectLifecycleStore.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/projectRouteSfcIntegration.test.mjs frontend/tests/unit/m1Navigation.test.mjs frontend/tests/unit/modelBindingStore.test.mjs
git commit -m "feat: add project lifecycle routes and state"
```

### Task 7: Build project library and archived-project interactions

**Files:**

- Modify: `frontend/src/views/ProjectLibraryView.vue`
- Modify: `frontend/src/views/ArchivedProjectsView.vue`
- Create: `frontend/src/components/projects/ProjectCard.vue`
- Create: `frontend/src/components/projects/ProjectNameDialog.vue`
- Create: `frontend/src/components/projects/ProjectEmptyState.vue`
- Create: `frontend/tests/unit/projectCard.test.mjs`
- Create: `frontend/tests/unit/projectNameDialog.test.mjs`

- [ ] **Step 1: Write component behavior tests**

Mount with deterministic props and test:

- clicking card whitespace emits nothing;
- `打开项目` emits `open`;
- resumable project renders primary `继续写作` plus secondary `打开项目`;
- ordinary project renders only `打开项目`;
- More contains only `重命名` and `归档`;
- archived card renders `恢复` and `永久删除`;
- the name dialog has one input, trims surrounding whitespace, validates empty
  input inline, submits on Enter, and disables repeated submit while pending.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
node --test frontend/tests/unit/projectCard.test.mjs frontend/tests/unit/projectNameDialog.test.mjs
```

Expected: FAIL because the route shells do not yet have cards, dialogs, or
lifecycle interactions and the components do not exist.

- [ ] **Step 3: Implement the components**

Use semantic buttons, visible focus rings, and one menu trigger per active
card. Do not put a click handler, link role, or keyboard handler on the card
container. The dialog emits only:

```javascript
emit('submit', { title: normalizedTitle })
```

- [ ] **Step 4: Implement the two pages**

`ProjectLibraryView` loads active projects, owns create/rename dialogs, and
routes only from explicit action buttons. `ArchivedProjectsView` loads archived
projects and exposes restore/permanent-delete actions. Both pages show
skeleton/loading, empty, success, and recoverable-error states without a full
page modal.

- [ ] **Step 5: Run component tests**

Run:

```powershell
node --test frontend/tests/unit/projectCard.test.mjs frontend/tests/unit/projectNameDialog.test.mjs
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/views/ProjectLibraryView.vue frontend/src/views/ArchivedProjectsView.vue frontend/src/components/projects frontend/tests/unit/projectCard.test.mjs frontend/tests/unit/projectNameDialog.test.mjs
git commit -m "feat: build project library interactions"
```

### Task 8: Unify toast, danger confirmation, and long-operation feedback

**Files:**

- Rewrite: `frontend/src/composables/useAppMessage.js`
- Create: `frontend/src/composables/useDangerousConfirmation.js`
- Create: `frontend/src/stores/operationStore.js`
- Create: `frontend/src/components/common/AppOperationOverlay.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`
- Create: `frontend/tests/unit/appFeedback.test.mjs`

- [ ] **Step 1: Write feedback tests**

Test:

- success/info/warning/error use `useMessage`, never `useDialog`;
- archive success creates a toast with action `撤销`;
- clicking Undo calls restore exactly once;
- dangerous confirmation defaults to red `永久删除` and neutral `取消`;
- cancel/escape does not run the destructive callback;
- repeated positive clicks run it once;
- operation overlay blocks app-level navigation only when
  `operationStore.blocking` is true.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
node --test frontend/tests/unit/appFeedback.test.mjs
```

Expected: FAIL because ordinary messages currently create non-closable dialogs.

- [ ] **Step 3: Implement toast and confirmation composables**

`useAppMessage` keeps the current `success/error/warning/info` call surface but
delegates to `useMessage`. Support:

```javascript
message.success('项目已归档', {
  actionLabel: '撤销',
  onAction: restore,
  duration: 6000,
})
```

`useDangerousConfirmation().confirm(options)` returns a Promise and calls the
provided action only after one positive confirmation. It is used for permanent
project deletion. Do not migrate unrelated Phase 2 settings screens into the
active route tree.

- [ ] **Step 4: Add the operation overlay host**

Mount `AppOperationOverlay` once inside Naive UI providers. Phase 1 lifecycle
requests stay page-local and do not activate it; the component establishes the
single global host needed by later import/export/finalization operations.

- [ ] **Step 5: Run feedback tests**

Run:

```powershell
node --test frontend/tests/unit/appFeedback.test.mjs
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/composables/useAppMessage.js frontend/src/composables/useDangerousConfirmation.js frontend/src/stores/operationStore.js frontend/src/components/common/AppOperationOverlay.vue frontend/src/App.vue frontend/src/style.css frontend/tests/unit/appFeedback.test.mjs
git commit -m "feat: unify application feedback"
```

### Task 9: Complete the product shell layout

**Files:**

- Rewrite: `frontend/src/components/layout/Sidebar.vue`
- Rewrite: `frontend/src/components/layout/TopBar.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`
- Delete: `frontend/src/views/HomeView.vue`
- Delete: `frontend/src/views/ProjectView.vue`
- Create: `frontend/tests/unit/productShell.test.mjs`

- [ ] **Step 1: Write shell behavior tests**

Assert:

- global navigation contains working `项目库` and `设置` destinations only;
- when `projectId` is in the route, the sidebar displays the project title and
  one `项目概览` module entry;
- there is no bottom `返回项目库` or `切换项目`;
- project title survives refresh by route hydration;
- breadcrumb links to `/projects` and then the active project overview;
- archived context visibly says `已归档` and offers no module mutation links;
- viewport width below the desktop breakpoint collapses the sidebar without
  hiding the current route title.

Use the frozen settings destination `/settings/providers`; the new
`ProviderSettingsView` wraps only the existing Provider/model component.
Do not expose the old Settings tabs, Creative Assets, or corpus navigation
until Phase 2 moves them into their approved product modules.

- [ ] **Step 2: Run the shell test and verify failure**

Run:

```powershell
node --test frontend/tests/unit/productShell.test.mjs
```

Expected: FAIL because the old sidebar has `/`, duplicate back navigation, and
depends on transient store state.

- [ ] **Step 3: Implement route-driven shell**

The top-level shell reads route metadata and `currentProject`. Sidebar menu
keys use canonical path builders. Remove the obsolete `v0.1 本地地基版` label.
Provide clear selected, hover, disabled, and keyboard focus states. Keep visual
density appropriate for a long-session desktop writing product.

- [ ] **Step 4: Remove obsolete active views**

Delete `HomeView.vue` and `ProjectView.vue` after proving no import references
remain:

```powershell
rg "HomeView|ProjectView|/project/|router.push\\('/'\\)" frontend/src frontend/tests
```

Expected: no product references to old routes or old views.

- [ ] **Step 5: Run frontend unit and build checks**

Run:

```powershell
npm --prefix frontend run test:unit
npm --prefix frontend run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src frontend/tests/unit
git commit -m "feat: complete phase one product shell"
```

### Task 10: Add a disposable-MySQL browser acceptance lane

**Files:**

- Create: `backend/scripts/prepare_product_shell_browser_db.py`
- Create: `backend/tests/unit/test_prepare_product_shell_browser_db.py`
- Create: `frontend/e2e/product-shell-lifecycle.spec.ts`
- Create: `frontend/e2e/run-product-shell.mjs`
- Create: `frontend/playwright.product-shell.config.ts`
- Modify: `frontend/package.json`
- Modify: `package.json`
- Modify: `scripts/run-tests.mjs`
- Create: `scripts/tests/productShellSuite.test.mjs`

- [ ] **Step 1: Test the runner contract**

The runner test must prove:

- missing `TEST_MYSQL_*` variables fail before spawning;
- database names match `novel_creator_test_<32 lowercase hex>`;
- every browser spec receives a fresh database;
- backend and Vite ports are runner-reserved and distinct;
- the runner starts only its owned services and verifies a nonce;
- cleanup drops only the database created by this run;
- product database names and arbitrary paths are rejected;
- logs are scanned against runtime sensitive values.

- [ ] **Step 2: Run runner tests and verify failure**

Run:

```powershell
node --test scripts/tests/productShellSuite.test.mjs
python -m pytest backend/tests/unit/test_prepare_product_shell_browser_db.py -q
```

Expected: FAIL because the Phase 1 runner and fixture do not exist.

- [ ] **Step 3: Implement a narrow owned runner**

Extract or reuse the ownership primitives from `run-milestone2.mjs`; do not
copy the closed M2 scenario registry. Register exactly:

```javascript
export const FORMAL_SPECS = Object.freeze([
  'e2e/product-shell-lifecycle.spec.ts',
])
```

Add root suite `browser-product-shell` and scripts:

```json
"test:browser:product-shell": "node scripts/run-tests.mjs browser-product-shell"
```

The fixture initializes the current schema only. It does not seed a provider or
call a model.

- [ ] **Step 4: Write the full browser scenario**

Using real UI actions and API observation:

1. open `/projects`;
2. confirm the create form has only `项目名称`;
3. create `典镇山河`;
4. click card whitespace and prove the route does not change;
5. click `打开项目` and verify canonical overview URL;
6. refresh and verify project context and breadcrumb restore;
7. rename it;
8. archive it and prove no dialog appeared;
9. click toast `撤销` and verify it returns;
10. archive again, open the archived page, and restore directly;
11. archive a third time;
12. start permanent delete, cancel, and prove no DELETE request occurred;
13. confirm permanent delete once and prove the project disappears;
14. visit old and unknown URLs and verify the not-found page;
15. inspect all captured responses and page text for the secret sentinel.

- [ ] **Step 5: Run the browser lane**

Run:

```powershell
npm run test:browser:product-shell
```

Expected: PASS against a runner-owned disposable MySQL 8 database, followed by
database and process cleanup.

- [ ] **Step 6: Commit**

```powershell
git add backend/scripts/prepare_product_shell_browser_db.py backend/tests/unit/test_prepare_product_shell_browser_db.py frontend/e2e/product-shell-lifecycle.spec.ts frontend/e2e/run-product-shell.mjs frontend/playwright.product-shell.config.ts frontend/package.json package.json scripts/run-tests.mjs scripts/tests/productShellSuite.test.mjs
git commit -m "test: add product shell browser acceptance"
```

### Task 11: Run the Phase 1 release gate and reconcile documentation

**Files:**

- Modify: `docs/CURRENT_PROJECT_STATE.md`
- Modify: `docs/PRODUCT_DEVELOPMENT_PLAN.md`
- Modify: `docs/DEVELOPMENT_LOG.md`
- Create: `docs/acceptance/2026-07-18-phase-1-product-shell.md`

- [ ] **Step 1: Run all non-provider verification**

First confirm test variables are present without printing values:

```powershell
$required = 'TEST_MYSQL_HOST','TEST_MYSQL_PORT','TEST_MYSQL_USER','TEST_MYSQL_PASSWORD'
$required | ForEach-Object { "$_=" + [bool](Test-Path "Env:$_") }
```

Then run:

```powershell
npm test
npm run test:integration
npm run test:browser:product-shell
npm --prefix frontend run build
git diff --check
git status --short
```

Expected: all test/build commands PASS, diff check is empty, and status contains
only the intended documentation updates before the final commit.

- [ ] **Step 2: Perform a route and legacy inventory**

Run:

```powershell
rg "/project/|/writer/|redirect: '/'|deleteProject|projects\\.delete|ProjectService\\.delete" frontend/src backend
rg "apiKey|api_key" backend/routers backend/services frontend/src/api
```

Expected:

- first command has no retired lifecycle/route implementation references;
- second command may find secret input/write handling, but no project response
  or export path returns plaintext secret material.

- [ ] **Step 3: Record evidence**

The acceptance report must include:

- commit SHA;
- schema version and manifest hash;
- exact commands and exit codes;
- disposable database name pattern, never credentials;
- browser actions completed;
- confirmation that no provider/model was called;
- confirmation that the product database was not read or written;
- known deferred scope: Creative Assets, contract/bible, planning, writer loop,
  finalization, and export remain later phases.

Update current-state, development-plan, and log documents to mark only Phase 1
as complete. Do not claim the full product rebuild or writing loop is complete.

- [ ] **Step 4: Commit the evidence**

```powershell
git add docs/CURRENT_PROJECT_STATE.md docs/PRODUCT_DEVELOPMENT_PLAN.md docs/DEVELOPMENT_LOG.md docs/acceptance/2026-07-18-phase-1-product-shell.md
git commit -m "docs: record phase one product shell acceptance"
```

- [ ] **Step 5: Final branch audit**

Run:

```powershell
git status --short --branch
git log --oneline --decorate main..HEAD
git diff --stat main...HEAD
```

Expected: clean `codex/product-shell-lifecycle`, with only Phase 1 commits and
no files copied from other worktrees.

## Phase 1 acceptance boundary

Phase 1 is complete only when all of the following are true:

- project lifecycle works through real browser UI and FastAPI against disposable
  MySQL 8;
- refresh and deep-link project context work;
- archived projects are server-side write-protected;
- archive/restore/permanent-delete semantics are distinct and concurrency-safe;
- ordinary feedback is non-blocking and irreversible deletion has one clear
  confirmation;
- old routes and duplicate project navigation are absent;
- product DB and providers were untouched;
- unit, integration, browser, build, diff, and secret-scan gates pass.

Content-quality acceptance—情节丰满、人物饱满、人物化对话、低机械味/低 AI
味、读者愿意继续读—belongs to Phase 7 and cannot be inferred from this shell
delivery.
