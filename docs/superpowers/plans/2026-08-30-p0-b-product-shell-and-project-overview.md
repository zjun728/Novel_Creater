# P0-B Product Shell and Project Overview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the demo-like project landing page with a production author overview and grouped product navigation backed by one read-only server aggregation, without changing Writer Core lifecycle or write authority.

**Architecture:** Add a separate Q-class `project_overview` domain/service/repository path that reads existing project, Seed, Contract, Bible, Planning, Outline, ChapterSession, final chapter, and Canon/Projection authorities in one read snapshot. The frontend validates and stores that DTO, presents an information-first overview with manual module links, and reshapes the existing shell into grouped navigation without mounting placeholder product pages. Existing mutation services, Provider behavior, databases, and Writer Core semantics remain untouched.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, existing async MySQL adapter, Vue 3, Pinia, Vue Router, Naive UI, Node test runner, pytest, Playwright.

---

## Scope and file map

**Create:**

- `backend/domain/project_overview.py` — strict immutable author-facing overview DTOs and cross-field validation.
- `backend/repositories/project_overview.py` — one snapshot-bound read aggregation; no commands and no state inference outside existing authorities.
- `backend/services/project_overview.py` — maps authoritative rows into the thin DTO and stable author states.
- `backend/domain/routers/project_overview.py` — `GET /api/projects/{project_id}/overview` only.
- `backend/tests/unit/test_project_overview_domain.py` — DTO invariants.
- `backend/tests/unit/test_project_overview_repository.py` — SQL scope and aggregate behavior.
- `backend/tests/unit/test_project_overview_service.py` — authority-to-author-state mapping.
- `frontend/src/application/projects/projectOverview.js` — strict response parser, Chinese status presentation, and manual destination mapping.
- `frontend/src/components/projects/ProjectPageHeader.vue` — reusable page identity layer.
- `frontend/src/views/ProjectExportView.vue` — dedicated home for the existing export/backup controls removed from Overview.
- `frontend/tests/unit/projectOverviewApi.test.mjs` — client response validation.
- `frontend/tests/unit/projectOverviewPresentation.test.mjs` — Chinese copy and state mapping.
- `frontend/tests/unit/projectExportView.test.mjs` — export/backup route ownership.

**Modify:**

- `backend/main.py` — register the read-only overview router.
- `backend/tests/api/test_product_routes.py` — public route shape, URL decoding, missing-project behavior.
- `backend/tests/api/test_route_inventory.py` — freeze the new GET route as read-only.
- `frontend/src/api/db/client.js` — add `api.projects.overview(projectId)` with strict parsing.
- `frontend/src/stores/projectStore.js` — add latest-request-safe overview state separate from preparation.
- `frontend/tests/unit/projectStore.test.mjs` — overview identity, stale response, retry, and clear behavior.
- `frontend/src/components/layout/productShell.js` — grouped project sections and new export route; retain only routes that actually exist.
- `frontend/src/components/layout/Sidebar.vue` — render section labels and keep keyboard/mobile behavior.
- `frontend/tests/unit/productShell.test.mjs` — freeze grouped information architecture.
- `frontend/src/router/projectRoutes.js` — add `/projects/:projectId/settings/export`.
- `frontend/src/views/ProjectOverviewView.vue` — replace next-action/demo content with the production overview.
- `frontend/tests/unit/projectPreparationOverview.test.mjs` — replace preparation/next-action expectations with overview expectations.
- `frontend/src/style.css` — shared page spacing and responsive tokens only when used by two or more Plan B components.
- `frontend/e2e/product-shell.spec.ts` — verify the real overview and grouped navigation.

**Explicitly out of scope:**

- no Topic Center routes or placeholder pages (Plan C owns them);
- no Seed/Contract/Bible editor redesign (Plan D);
- no continuity table, continuity count fabrication, or continuity pages (Plan E); the overview returns `availability="pending_module"` and `pending_count=null` until that authority exists;
- no unified workbench or old writing-route cutover (Plan F);
- no schema migration, Provider call, prompt change, model-binding mutation, project-database write, or Writer Core service edit;
- no automatic “continue next” action on Overview.

## Stable response contract

The route serializes this author DTO in camelCase:

```json
{
  "project": {
    "id": "project-1",
    "title": "典镇山河",
    "genre": "东方奇幻",
    "logline": "少年以县志镇压黑潮。",
    "targetWords": 2400000,
    "targetChapters": 720,
    "updatedAtMs": 1788067200000,
    "lifecycle": "active"
  },
  "progress": {
    "authoritativeChapterNumber": 4,
    "currentVolume": {"id": "volume-1", "order": 1, "title": "第一卷"},
    "latestFinalChapter": {"number": 3, "title": "夜渡", "finalizedAtMs": 1788067100000},
    "finalizedChapterCount": 3,
    "finalizedScalarCount": 11840
  },
  "modules": {
    "seed": "current",
    "contract": "current",
    "bible": "current",
    "planning": "current",
    "outline": "current",
    "writing": "working_draft"
  },
  "writerCore": {
    "canonRevision": 3,
    "projectionRevision": 3,
    "synchronized": true
  },
  "continuity": {"availability": "pending_module", "pendingCount": null},
  "recentAchievements": [
    {"kind": "final_chapter", "label": "第 3 章《夜渡》已定稿", "occurredAtMs": 1788067100000}
  ]
}
```

`currentVolume` is present only when the confirmed current Outline resolves through its pinned Planning revision to one active Volume. The repository/service must return `null` when that authority is absent or internally inconsistent; it must never match by display title. `continuity.pendingCount` must remain `null` until Plan E supplies the table and owning service.

### Task 1: Establish an isolated clean baseline

**Files:** None

- [ ] **Step 1: Create the isolated worktree**

Use branch `codex/p0-b-product-shell-overview` under the ignored repository-local `.worktrees/` directory, following the `using-git-worktrees` skill. The worktree must start from the current local `main` commit containing P0-A.

- [ ] **Step 2: Preserve unrelated user files**

Run:

```powershell
git status --short --branch
git rev-parse HEAD
git diff --check
```

Expected: the isolated worktree is clean. The untracked `.review-worktrees/` and `tmp/brainstorm-topic-center-*.html` stay only in the main checkout and are never copied, staged, edited, or deleted.

- [ ] **Step 3: Run the deterministic baseline**

Run:

```powershell
npm test
npm run build
```

Expected: both exit `0`; no Provider, external network, product database, Vite server, or backend server is used.

### Task 2: Freeze the strict backend overview DTO with TDD

**Files:**

- Create: `backend/domain/project_overview.py`
- Create: `backend/tests/unit/test_project_overview_domain.py`

- [ ] **Step 1: Write failing DTO tests**

Cover the exact JSON contract above plus these invariants:

```python
def test_overview_rejects_frontend_inferred_or_raw_authority_fields():
    forbidden = {
        "next_action", "target_path", "raw_json", "content_hash",
        "planning_json", "canon_events",
    }
    assert forbidden.isdisjoint(ProjectOverview.model_fields)


def test_sync_flag_must_equal_revision_comparison():
    with pytest.raises(ValidationError, match="synchronized"):
        overview(writer_core={
            "canon_revision": 4,
            "projection_revision": 3,
            "synchronized": True,
        })


def test_pending_continuity_module_cannot_claim_zero_issues():
    with pytest.raises(ValidationError, match="pending_count"):
        OverviewContinuity(availability="pending_module", pending_count=0)


def test_current_volume_requires_stable_identity_not_only_a_title():
    with pytest.raises(ValidationError):
        OverviewVolume(id="", order=1, title="第一卷")
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_project_overview_domain.py
```

Expected: collection fails because `backend.domain.project_overview` does not exist.

- [ ] **Step 3: Implement the strict values**

Implement frozen, strict, `extra="forbid"` Pydantic values with these public types:

```python
OverviewArtifactStatus = Literal[
    "missing", "working_draft", "pending_confirmation", "current",
    "needs_review",
]

class OverviewWriterCore(_StrictValue):
    canon_revision: int = Field(ge=0)
    projection_revision: int = Field(ge=0)
    synchronized: bool

    @model_validator(mode="after")
    def validate_sync(self):
        if self.synchronized != (self.canon_revision == self.projection_revision):
            raise ValueError("synchronized differs from authoritative revisions")
        return self

class OverviewContinuity(_StrictValue):
    availability: Literal["pending_module", "available"]
    pending_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_availability(self):
        if (self.availability == "available") != (self.pending_count is not None):
            raise ValueError("pending_count differs from continuity availability")
        return self
```

Also implement `OverviewProject`, `OverviewVolume`, `OverviewFinalChapter`, `OverviewProgress`, `OverviewModuleStates`, `OverviewAchievement`, and `ProjectOverview`. Reject blank/control-character identity text and contradictory final chapter/count combinations.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_project_overview_domain.py
git add -- backend/domain/project_overview.py backend/tests/unit/test_project_overview_domain.py
git diff --cached --check
git commit -m "test: freeze project overview read contract"
```

Expected: tests pass and the commit contains exactly the new DTO and tests.

### Task 3: Add the snapshot-bound read repository

**Files:**

- Create: `backend/repositories/project_overview.py`
- Create: `backend/tests/unit/test_project_overview_repository.py`

- [ ] **Step 1: Write failing repository tests**

Use the repository test session fake to assert:

```python
snapshot = await repository.read_snapshot(session, "project / 一")
assert snapshot["project"]["id"] == "project / 一"
assert snapshot["final_aggregate"] == {
    "chapter_count": 3,
    "scalar_count": 11840,
    "latest_number": 3,
    "latest_title": "夜渡",
    "latest_finalized_at": 1788067100000,
}
assert all("content" not in sql.lower() for sql, _ in session.calls
           if "final_chapters" in sql.lower())
```

The fake must also prove every query uses the exact `project_id`, the selected Seed joins its selected immutable revision, the current Outline is read only at the repository-provided authoritative chapter, and no SQL contains `INSERT`, `UPDATE`, `DELETE`, `FOR UPDATE`, or a continuity table name.

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_project_overview_repository.py
```

Expected: import failure for the new repository.

- [ ] **Step 3: Implement bounded authority reads**

Implement:

```python
class ProjectOverviewRepository:
    async def read_snapshot(self, session, project_id: str):
        project = await session.fetchone(
            "SELECT * FROM projects WHERE id=%s", (project_id,),
        )
        if project is None:
            return None
        selected_seed = await session.fetchone(
            """SELECT selected.selection_revision,selected.selected_at,
                      revision.payload_json
                 FROM project_selected_seeds selected
                 JOIN creative_seed_revisions revision
                   ON revision.project_id=selected.project_id
                  AND revision.seed_id=selected.seed_id
                  AND revision.id=selected.seed_revision_id
                  AND revision.content_hash=selected.seed_hash
                WHERE selected.project_id=%s""",
            (project_id,),
        )
        contract = await session.fetchone(
            """SELECT head.revision,head.updated_at,
                      EXISTS(SELECT 1 FROM project_contract_drafts draft
                              WHERE draft.project_id=head.project_id) AS has_draft
                 FROM project_contract_heads head WHERE head.project_id=%s""",
            (project_id,),
        )
        bible = await session.fetchone(
            """SELECT head.revision,head.updated_at,
                      EXISTS(SELECT 1 FROM project_bible_drafts draft
                              WHERE draft.project_id=head.project_id
                                AND draft.active_slot=1) AS has_draft
                 FROM project_bible_heads head WHERE head.project_id=%s""",
            (project_id,),
        )
        planning = await session.fetchone(
            """SELECT head.revision,head.updated_at,revision.content_json,
                      EXISTS(SELECT 1 FROM planning_drafts draft
                              WHERE draft.project_id=head.project_id
                                AND draft.active_slot=1) AS has_draft
                 FROM project_planning_heads head
                 LEFT JOIN planning_revisions revision
                   ON revision.project_id=head.project_id
                  AND revision.id=head.planning_revision_id
                  AND revision.revision=head.revision
                  AND revision.content_hash=head.content_hash
                WHERE head.project_id=%s""",
            (project_id,),
        )
        session_row = await session.fetchone(
            """SELECT id,chapter_num,status,created_at,finalized_at
                 FROM chapter_sessions WHERE project_id=%s AND status='drafting'""",
            (project_id,),
        )
        final_aggregate = await session.fetchone(
            """SELECT COUNT(*) AS chapter_count,
                      COALESCE(SUM(CHAR_LENGTH(content)),0) AS scalar_count,
                      MAX(chapter_num) AS latest_number
                 FROM final_chapters WHERE project_id=%s""",
            (project_id,),
        )
        max_final = final_aggregate["latest_number"]
        latest_final = None if max_final is None else await session.fetchone(
            """SELECT chapter_num AS latest_number,title AS latest_title,
                      finalized_at AS latest_finalized_at
                 FROM final_chapters
                WHERE project_id=%s AND chapter_num=%s""",
            (project_id, max_final),
        )
        final_aggregate = {**final_aggregate, **(latest_final or {})}
        authoritative_chapter = int(max_final or 0) + 1
        outline = await session.fetchone(
            """SELECT head.revision,head.updated_at,revision.content_json
                 FROM project_chapter_outline_heads head
                 LEFT JOIN chapter_outline_revisions revision
                   ON revision.project_id=head.project_id
                  AND revision.chapter_num=head.chapter_num
                  AND revision.id=head.outline_revision_id
                  AND revision.revision=head.revision
                  AND revision.content_hash=head.content_hash
                WHERE head.project_id=%s AND head.chapter_num=%s""",
            (project_id, authoritative_chapter),
        )
        writer_core = await session.fetchone(
            """SELECT canon_revision_number,projection_revision_number
                 FROM projection_heads WHERE project_id=%s""",
            (project_id,),
        )
        return {
            "project": project, "selected_seed": selected_seed,
            "contract": contract, "bible": bible, "planning": planning,
            "outline": outline, "session": session_row,
            "writer_core": writer_core, "final_aggregate": final_aggregate,
            "authoritative_chapter_number": authoritative_chapter,
        }
```

Required result keys are `project`, `selected_seed`, `contract`, `bible`, `planning`, `outline`, `session`, `writer_core`, and `final_aggregate`. It may read `payload_json`, `planning_revisions.content_json`, and `chapter_outline_revisions.content_json` inside the backend solely to resolve the displayed logline/genre and the current volume by stable IDs; none of those raw JSON blobs leave the service.

The final aggregate query must use `COUNT(*)`, `COALESCE(SUM(CHAR_LENGTH(content)), 0)`, and latest metadata selected by maximum `chapter_num`; it must not transfer prose rows.

- [ ] **Step 4: Verify and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_project_overview_repository.py
git add -- backend/repositories/project_overview.py backend/tests/unit/test_project_overview_repository.py
git diff --cached --check
git commit -m "feat: read authoritative project overview snapshot"
```

### Task 4: Map and expose the Q-class overview route

**Files:**

- Create: `backend/services/project_overview.py`
- Create: `backend/domain/routers/project_overview.py`
- Create: `backend/tests/unit/test_project_overview_service.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/api/test_product_routes.py`
- Modify: `backend/tests/api/test_route_inventory.py`

- [ ] **Step 1: Write failing service and route tests**

Freeze these mappings:

```python
@pytest.mark.parametrize(("head", "draft", "expected"), [
    (None, None, "missing"),
    ({"revision": 0}, {"id": "draft-1"}, "working_draft"),
    ({"revision": 1}, None, "current"),
])
def test_lifecycle_mapping(head, draft, expected):
    assert map_artifact_status(head=head, draft=draft) == expected


async def test_route_is_read_only_and_decodes_project_id(client, service):
    response = await client.get("/api/projects/project%20%2F%20%E4%B8%80/overview")
    assert response.status_code == 200
    assert service.calls == ["project / 一"]
    assert "nextAction" not in response.json()
```

Also test missing project returns the existing public 404 classification, archived projects remain readable with `lifecycle="archived"`, unsynchronized heads are represented rather than rejected, and a malformed pinned volume relation yields `currentVolume=null` rather than a guessed relation.

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_project_overview_service.py backend/tests/api/test_product_routes.py backend/tests/api/test_route_inventory.py
```

Expected: new imports/route assertions fail.

- [ ] **Step 3: Implement service mapping**

Implement:

```python
class ProjectOverviewService:
    def __init__(self, repository, connection_factory):
        self.repository = repository
        self.connection_factory = connection_factory

    async def get(self, project_id: str) -> ProjectOverview:
        async with self.connection_factory() as session:
            snapshot = await self.repository.read_snapshot(session, project_id)
        if snapshot is None:
            raise ProjectNotFound()
        return build_project_overview(snapshot)
```

`build_project_overview` derives statuses only from server rows. `writing` is `working_draft` only for a drafting ChapterSession, `current` only when the latest authoritative chapter is already finalized and no drafting session exists, and otherwise `missing` or `pending_confirmation` according to the current Outline authority. Recent achievements are a maximum of five server-sorted labels from confirmed Seed/Contract/Bible/Planning and latest final chapter timestamps.

- [ ] **Step 4: Add and register the route**

The router contains only:

```python
@router.get("/projects/{project_id}/overview")
async def get_project_overview(project_id: str):
    return (await _service.get(project_id)).model_dump(
        mode="json", by_alias=True,
    )
```

Register it in `backend/main.py` under `/api`. Do not modify an existing Writer Core router or service.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_project_overview_domain.py backend/tests/unit/test_project_overview_repository.py backend/tests/unit/test_project_overview_service.py backend/tests/api/test_product_routes.py backend/tests/api/test_route_inventory.py backend/tests/unit/test_router_domain_boundary.py
git add -- backend/services/project_overview.py backend/domain/routers/project_overview.py backend/main.py backend/tests/unit/test_project_overview_service.py backend/tests/api/test_product_routes.py backend/tests/api/test_route_inventory.py
git diff --cached --check
git commit -m "feat: expose read-only project overview"
```

### Task 5: Add a strict frontend overview boundary

**Files:**

- Create: `frontend/src/application/projects/projectOverview.js`
- Create: `frontend/tests/unit/projectOverviewApi.test.mjs`
- Create: `frontend/tests/unit/projectOverviewPresentation.test.mjs`
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/projectStore.js`
- Modify: `frontend/tests/unit/projectStore.test.mjs`

- [ ] **Step 1: Write failing client and presentation tests**

Required expectations:

```javascript
assert.equal(result.project.title, '典镇山河')
assert.equal(result.writerCore.synchronized, true)
assert.throws(() => parseProjectOverview({ ...payload, nextAction: 'continue_writing' }))
assert.throws(() => parseProjectOverview({ ...payload, progress: {
  ...payload.progress, finalizedChapterCount: 3, latestFinalChapter: null,
} }))
assert.equal(artifactStatusLabel('working_draft'), '工作草稿')
assert.equal(artifactStatusLabel('current'), '当前正式版')
assert.equal(continuitySummary({ availability: 'pending_module', pendingCount: null }),
  '连续性问题将在连续性模块启用后显示')
```

The store tests must prove responses for project A cannot overwrite project B, retry retains the active project identity, and lifecycle mutations clear the overview state.

- [ ] **Step 2: Run RED**

Run:

```powershell
node --test frontend/tests/unit/projectOverviewApi.test.mjs frontend/tests/unit/projectOverviewPresentation.test.mjs frontend/tests/unit/projectStore.test.mjs
```

- [ ] **Step 3: Implement parser, client, and store**

`parseProjectOverview` must whitelist every field in the stable response, clone/freeze nested values, reject unknown status values, invalid integer ranges, contradictory synchronized heads, and fabricated continuity counts. Add:

```javascript
overview: (projectId, options = {}) => request(
  'GET', `/projects/${segment(projectId)}/overview`, undefined,
  DEFAULT_TIMEOUT, options.signal,
),
```

The project store adds `currentOverview`, `overviewProjectId`, `overviewStatus`, `overviewError`, `loadOverview`, and `clearOverview`, using its own `createLatestRequestGuard()` rather than sharing the preparation guard.

- [ ] **Step 4: Verify and commit**

Run:

```powershell
node --test frontend/tests/unit/projectOverviewApi.test.mjs frontend/tests/unit/projectOverviewPresentation.test.mjs frontend/tests/unit/projectStore.test.mjs
git add -- frontend/src/application/projects/projectOverview.js frontend/src/api/db/client.js frontend/src/stores/projectStore.js frontend/tests/unit/projectOverviewApi.test.mjs frontend/tests/unit/projectOverviewPresentation.test.mjs frontend/tests/unit/projectStore.test.mjs
git diff --cached --check
git commit -m "feat: add project overview frontend boundary"
```

### Task 6: Build grouped navigation and the production overview

**Files:**

- Create: `frontend/src/components/projects/ProjectPageHeader.vue`
- Create: `frontend/src/views/ProjectExportView.vue`
- Create: `frontend/tests/unit/projectExportView.test.mjs`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/src/components/layout/Sidebar.vue`
- Modify: `frontend/tests/unit/productShell.test.mjs`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: `frontend/tests/unit/projectPreparationOverview.test.mjs`
- Modify: `frontend/src/style.css`

- [ ] **Step 1: Write failing shell and page tests**

Freeze the currently real, grouped project navigation:

```javascript
assert.deepEqual(shell.projectContext.sections.map(section => [
  section.label,
  section.items.map(item => item.label),
]), [
  ['', ['项目概览']],
  ['创作基础', ['创作种子', '创作契约', '创作圣经']],
  ['故事规划', ['分卷规划', '情节线', '故事块']],
  ['写作与稿件', ['作品稿件']],
  ['项目配置', ['模型绑定', '导出与备份']],
])
```

Do not add Topic Center or continuity links before their product routes exist. The Overview render test must assert:

- title, genre, logline, target words, finalized scalar count, current volume, authoritative chapter, and latest final chapter are visible without opening an accordion;
- Seed, Contract, Bible, Planning, Outline, and Writing use Chinese status labels;
- Canon/Projection synchronization and continuity availability are visible in author language;
- recent achievements render at most five entries;
- module cards are manual links, with no “下一步”, `nextAction`, raw JSON, UUID, hash, backup panel, or download panel;
- loading, missing, archived, retryable overview error, and route-switch stale response states are explicit.

- [ ] **Step 2: Run RED**

Run:

```powershell
node --test frontend/tests/unit/productShell.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs frontend/tests/unit/projectExportView.test.mjs
```

- [ ] **Step 3: Implement the grouped shell**

Change the shell model from a flat `modules` array to `sections`, but retain a derived flat `modules` array for one release only if existing non-UI tests require it. `Sidebar.vue` renders section headings and items with the same 44px minimum target, focus ring, collapsed behavior, and mobile drawer semantics. Empty section labels are visually hidden.

The target `/projects/:projectId/settings/export` mounts `frontend/src/views/ProjectExportView.vue`, which composes the existing `NovelDownloadPanel` and `ProjectBackupPanel`; it adds no API and no duplicate business logic. Removing these panels from Overview must not make export/backup unreachable.

- [ ] **Step 4: Implement the information-first Overview**

`ProjectOverviewView.vue` loads only `projectStore.loadOverview(projectId)`. Use `ProjectPageHeader.vue` for the page identity layer, then render:

1. project identity and logline;
2. progress strip for target/finalized words, current volume/current authority, latest final chapter;
3. six lifecycle module summaries with manual links;
4. Writer Core synchronization and continuity availability;
5. recent achievements.

The page must use semantic headings, `dl` for metrics, `aria-live` only for asynchronous status, and a single retry button for overview failure. It must not load the old preparation endpoint or call `mapProjectNextAction`.

- [ ] **Step 5: Verify responsive behavior and commit**

Run:

```powershell
node --test frontend/tests/unit/productShell.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs frontend/tests/unit/projectExportView.test.mjs frontend/tests/unit/mobileNavigationDrawer.test.mjs frontend/tests/unit/m1Navigation.test.mjs
npm run build
git add -- frontend/src/components/projects/ProjectPageHeader.vue frontend/src/views/ProjectExportView.vue frontend/src/components/layout/productShell.js frontend/src/components/layout/Sidebar.vue frontend/src/router/projectRoutes.js frontend/src/views/ProjectOverviewView.vue frontend/src/style.css frontend/tests/unit/productShell.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs frontend/tests/unit/projectExportView.test.mjs
git diff --cached --check
git commit -m "feat: productize project overview and navigation"
```

### Task 7: Run browser acceptance and the P0-B gate

**Files:**

- Modify: `frontend/e2e/product-shell.spec.ts`

- [ ] **Step 1: Extend the real browser acceptance**

Add one deterministic seeded-browser case that opens the Overview and proves:

```text
project title + logline visible
2,400,000 target words visible
actual finalized scalar count visible
current volume/chapter visible
manual module link changes route
export/backup page is reachable
Overview has no next-step CTA
main content scrolls while pointer is over the overview
desktop and 760px mobile navigation remain usable
```

The browser fixture may use existing deterministic local setup only; no Provider or external network call.

- [ ] **Step 2: Run the focused browser suite once**

Run:

```powershell
npm run test:browser:product-shell
```

Expected: exit `0`; if infrastructure fails, diagnose before any retry.

- [ ] **Step 3: Run all deterministic tests and build**

Run:

```powershell
npm test
npm run build
```

Expected: exit `0` for both.

- [ ] **Step 4: Run the disposable MySQL integration suite once**

Use the existing `.env.local.json` in-memory mapping to `TEST_MYSQL_HOST`, `TEST_MYSQL_PORT`, `TEST_MYSQL_USER`, and `TEST_MYSQL_PASSWORD`, preserving and restoring any prior process values in `finally`. Run exactly:

```powershell
npm run test:integration
```

Expected: exit `0`; only random `novel_creator_test_<32 lowercase hex>` databases are created and all are cleaned. Do not map `MYSQL_DB`, open `novel_creator`/`novel_creator_v113`, call a Provider, or retry automatically.

- [ ] **Step 5: Commit acceptance and verify scope**

Run:

```powershell
git add -- frontend/e2e/product-shell.spec.ts
git diff --cached --check
git commit -m "test: accept p0-b project overview"
git status --short --branch
git log --oneline main..HEAD
```

Expected: a clean feature worktree with only Plan B commits ahead of local `main`.

## Exit criteria

P0-B is complete only when:

- `/api/projects/{project_id}/overview` is a read-only Q aggregation and returns no raw JSON, prose, hashes, or next-action authority;
- Overview presents identity, long-form target/actual progress, current position, real lifecycle states, Writer Core synchronization, continuity availability, and recent achievements in Chinese;
- Overview contains manual module links but no automatic “continue next” CTA;
- export/backup remains reachable from its dedicated project configuration page;
- grouped navigation exposes only real mounted pages and is usable with keyboard, desktop, collapsed sidebar, and mobile drawer;
- no Writer Core service, mutation route, schema, Provider, prompt, model binding, or product database changed;
- deterministic tests, the focused browser suite, disposable integration suite, and production build pass;
- the branch stops at a safe commit for review before Plan C.
