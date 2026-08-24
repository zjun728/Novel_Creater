# Novel Creator Manuscript Productization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved “作品稿件” vertical slice so authors can discover, read, review the pinned outline for, download, and navigate away from finalized chapters without reopening historical chapters in the writer.

**Architecture:** Add a lightweight manuscript directory read model and a target-chapter verified read model beside the existing download boundary. Share pinned-authority validation with downloads, keep project preparation as an independent existing request mapped by one frontend action helper, and keep final prose in a route-scoped controller rather than a persistent store. Build the product flow in four independently reviewed phases: read-only domain/API, desktop manuscript flow, responsive/accessibility shell, and full browser/product acceptance.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, aiomysql/MySQL, Vue 3, Vue Router, Pinia, Naive UI, Node test runner, Playwright, Vite.

---

## Approved source and scope fence

- Implement `docs/superpowers/specs/2026-08-24-manuscript-productization-design.md`; do not expand into the later seed → contract → bible → planning transition slice.
- Preserve `/projects/:projectId/write/chapters/:chapterNumber` as the current-authority writing route. Historical finalized chapters are read only through the new manuscript routes.
- Do not parse attachment text into browser prose, infer chapter titles from prose, regenerate finalized data, edit/reopen a final chapter, add a migration, or call a real Provider.
- Keep preparation separate from manuscript responses. The browser may load manuscript content successfully while the creative next action is temporarily unavailable.
- Keep `D:\Projects\Novel_Creater\.review-worktrees\` unmodified and untracked.
- Commit after each task only when its focused red/green tests pass. Stop at every phase review gate until independent code review has no unresolved Blocking/Major finding and a visible-browser check covers the phase’s real paths.

## File map

### Backend domain, persistence, service, and HTTP boundary

- Create `backend/domain/manuscripts.py`: strict immutable manuscript values, author outline projection, canonical ordering, scalar counts, and narrow domain errors.
- Create `backend/repositories/manuscripts.py`: metadata-only directory query, target-only chapter query, pinned Planning/Outline reconstruction, and public-safe corruption boundary.
- Create `backend/services/manuscripts.py`: read-only transaction orchestration, UTC timestamp projection, response DTO construction, and public error mapping.
- Create `backend/domain/routers/manuscripts.py`: the two strict GET routes and no-store headers.
- Modify `backend/repositories/novel_downloads.py`: reuse shared pinned-authority helpers and query only the chosen download scope before prose verification.
- Modify `backend/domain/novel_downloads.py`: verify final prose only after exact scope selection.
- Modify `backend/services/novel_downloads.py`: validate the selector before repository access and pass the selector into the scoped repository read.
- Modify `backend/domain/routers/__init__.py` and `backend/main.py`: register the manuscript router.

### Backend tests

- Create `backend/tests/unit/test_manuscript_domain.py`.
- Create `backend/tests/unit/test_manuscript_repository.py`.
- Create `backend/tests/unit/test_manuscript_service.py`.
- Create `backend/tests/api/test_manuscript_routes.py`.
- Create `backend/tests/integration/test_manuscript_repository_mysql.py`.
- Modify `backend/tests/unit/test_novel_downloads.py`, `backend/tests/unit/test_novel_download_repository.py`, `backend/tests/unit/test_novel_download_service.py`, and `backend/tests/integration/test_novel_download_repository_mysql.py`.
- Modify `backend/tests/api/test_route_inventory.py` and `backend/tests/unit/test_router_domain_boundary.py`.

### Frontend application and views

- Create `frontend/src/application/projects/projectNextAction.js`: the only preparation-to-author-action mapper.
- Create `frontend/src/application/manuscript/manuscriptController.js`: strict response validation, page/request generations, safe error states, and retry ownership.
- Create `frontend/src/application/manuscript/manuscriptHistory.js`: history-entry scroll/focus persistence without storing prose.
- Create `frontend/src/views/ManuscriptIndexView.vue` and `frontend/src/views/FinalChapterReaderView.vue`.
- Create `frontend/src/components/manuscript/ManuscriptChapterList.vue`, `FinalChapterArticle.vue`, and `FinalOutlinePanel.vue`.
- Create `frontend/src/components/layout/MobileNavigationDrawer.vue`.
- Modify `frontend/src/api/db/client.js`, `frontend/src/router/projectRoutes.js`, `frontend/src/components/layout/productShell.js`, `frontend/src/components/layout/Sidebar.vue`, `frontend/src/App.vue`, and `frontend/src/style.css`.
- Modify `frontend/src/views/ProjectOverviewView.vue`, `frontend/src/views/ChapterWriterView.vue`, `frontend/src/components/writer/FinalizationPanel.vue`, and `frontend/src/application/writer/finalizationController.js`.

### Frontend tests and browser acceptance

- Create `frontend/tests/unit/manuscriptApi.test.mjs`, `manuscriptController.test.mjs`, `manuscriptHistory.test.mjs`, `projectNextAction.test.mjs`, `manuscriptIndexView.test.mjs`, `finalChapterReaderView.test.mjs`, `manuscriptComponents.test.mjs`, and `mobileNavigationDrawer.test.mjs`.
- Modify `frontend/tests/unit/projectRoutes.test.mjs`, `productShell.test.mjs`, `projectRouteSfcIntegration.test.mjs`, `projectPreparationOverview.test.mjs`, `finalizationController.test.mjs`, `finalizationPanel.test.mjs`, and `chapterWriterView.test.mjs`.
- Create `frontend/e2e/phase8a/manuscript-productization.spec.mjs`, `frontend/e2e/playwright.phase8a.config.mjs`, and `frontend/e2e/run-phase8a.mjs`.
- Create `backend/scripts/prepare_phase8a_browser_db.py` and `backend/tests/unit/test_prepare_phase8a_browser_db.py`.
- Create `backend/scripts/verify_manuscript_product_smoke.py` and `backend/tests/unit/test_verify_manuscript_product_smoke.py`.
- Modify `scripts/run-tests.mjs`, `scripts/tests/testEntrypoint.test.mjs`, root `package.json`, and `frontend/package.json`.
- Create `docs/superpowers/acceptance/2026-08-24-phase8a-manuscript-productization.md`.

## Task 1: Select download scope before final-prose verification

**Files:**

- Modify: `backend/domain/novel_downloads.py`
- Modify: `backend/repositories/novel_downloads.py`
- Modify: `backend/services/novel_downloads.py`
- Modify: `backend/tests/unit/test_novel_downloads.py`
- Modify: `backend/tests/unit/test_novel_download_repository.py`
- Modify: `backend/tests/unit/test_novel_download_service.py`
- Modify: `backend/tests/integration/test_novel_download_repository_mysql.py`

- [ ] Add a failing domain test with chapters 1 and 3 where chapter 3 has a bad SHA-256. Assert chapter 1 selection and rendering succeeds, chapter 3 selection fails with `NovelDownloadIntegrityError`, and book selection fails.
- [ ] Change `select_chapters` to match and sort first, reject an empty selection, and verify only the selected tuple:

```python
matching = tuple(
    chapter for chapter in snapshot.chapters
    if _matches_selector(chapter, selector)
)
if not matching:
    raise NovelDownloadScopeNotFoundError(
        "requested download scope has no finalized chapters"
    )
selected = tuple(sorted(matching, key=lambda chapter: chapter.chapter_number))
_verify_final_prose(selected)
return selected
```

- [ ] Add failing repository and service tests proving the validated `NovelDownloadSelector` reaches the repository before any final prose is read. Reject an invalid selector without opening a transaction.
- [ ] Change `NovelDownloadRepository.load_finalized_snapshot` to require a `selector` argument and add parameterized SQL predicates for chapter or volume scope. Book scope remains project-wide. Preserve explicit columns and deterministic `chapter_num, id` ordering.
- [ ] Keep structural validation fail-closed: duplicate chapters, inconsistent volume identity/order/title, and an unsafe selector still fail before rendering. Only out-of-scope prose and prose hash are excluded from the selected query.
- [ ] Add a disposable-MySQL regression with three final chapters and a corrupted third body/hash pair. Assert chapter 1 download succeeds, chapter 3/volume/book downloads fail, and no project row is changed.
- [ ] Run:

```powershell
python -m pytest backend/tests/unit/test_novel_downloads.py backend/tests/unit/test_novel_download_repository.py backend/tests/unit/test_novel_download_service.py -q
python -m pytest backend/tests/integration/test_novel_download_repository_mysql.py -m mysql -q
```

  Expected: both commands exit 0; the integration ledger reports no disposable database residue.
- [ ] Commit: `fix: isolate finalized download integrity scope`

## Task 2: Define closed manuscript domain values

**Files:**

- Create: `backend/domain/manuscripts.py`
- Create: `backend/tests/unit/test_manuscript_domain.py`

- [ ] Write failing tests for strict/frozen/extra-forbid models covering active and archived lifecycles, positive chapter and volume numbers, non-negative scalar counts, safe non-empty titles, and non-negative persisted finalized milliseconds.
- [ ] Define the core values with Python field names and camel-case aliases at the router DTO boundary:

```python
class ManuscriptChapterMeta(_FrozenManuscriptValue):
    number: int = Field(ge=1)
    title: str = Field(min_length=1)
    scalar_count: int = Field(ge=0)
    finalized_at_ms: int = Field(ge=0)

class ManuscriptVolume(_FrozenManuscriptValue):
    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    chapters: tuple[ManuscriptChapterMeta, ...]

class FinalOutlineProjection(_FrozenManuscriptValue):
    chapter_goal: str
    expected_characters: tuple[str, ...]
    continuation: tuple[str, ...]
    planned_tasks: tuple[str, ...]
    scenes: tuple[str, ...]
    forbidden_early_events: tuple[str, ...]
```

- [ ] Add pure `canonicalize_manuscript_volumes` validation. Flatten actual finalized chapters by global `number`, allow gaps, reject duplicates, require volume order to be monotone non-decreasing, require each volume to occupy one contiguous run, and require identical `(id, order, title)` wherever a volume appears.
- [ ] Add pure `unicode_scalar_count(value: str) -> int` using Python code-point semantics, and reject any repository-provided count that is boolean, negative, or non-integer.
- [ ] Add narrow internal errors `ManuscriptProjectMissing`, `FinalChapterMissing`, `ManuscriptCorrupt`, and `ManuscriptUnavailable`. Their fixed messages must contain no stored identifier, hash, JSON, SQL, prose, or exception text.
- [ ] Test author outline projection against a valid `ChapterOutline`; assert the result includes only the six approved author fields and excludes IDs, revisions, hashes, basis, Canon/Projection, and raw status.
- [ ] Run `python -m pytest backend/tests/unit/test_manuscript_domain.py -q`.

  Expected: exit 0 with every manuscript-domain case passing.
- [ ] Commit: `feat: define manuscript read domain`

## Task 3: Read lightweight directory metadata and one verified chapter

**Files:**

- Create: `backend/repositories/manuscripts.py`
- Create: `backend/tests/unit/test_manuscript_repository.py`
- Create: `backend/tests/integration/test_manuscript_repository_mysql.py`
- Modify: `backend/repositories/novel_downloads.py`

- [ ] Move the reusable private authority checks from `backend/repositories/novel_downloads.py` into public-safe helpers in `backend/repositories/manuscripts.py`: JSON-object decoding, equal-pin validation, Planning/Outline canonical hash validation, planning-node closure, ChapterSession/final/outline/planning pin agreement, and volume/story-block membership.
- [ ] Keep the shared corruption constructor fixed:

```python
def manuscript_corruption() -> ManuscriptCorrupt:
    return ManuscriptCorrupt("finalized manuscript authority is corrupt")
```

- [ ] Add failing query-shape tests for `ManuscriptRepository.load_directory(session, project_id)`. Require explicit columns from projects/final/session/outline/planning, `CHAR_LENGTH(final.content) AS final_scalar_count`, and no `final.content` projection. Assert one project parameter and deterministic ordering.
- [ ] Add failing tests for `ManuscriptRepository.load_chapter(session, project_id, chapter_number)`. Require `WHERE project.id=%s AND final.chapter_num=%s`, target prose/hash, exact pinned Outline/Planning rows, and a separate metadata-only neighbor query that never selects neighbor prose.
- [ ] Implement `ManuscriptRepository.load_directory(self, session, project_id: str) -> ManuscriptDirectoryRecord | None` and `ManuscriptRepository.load_chapter(self, session, project_id: str, chapter_number: int) -> FinalChapterRecord | None` as the only public repository entry points. Both methods must return fully validated records in this step; no stub body is permitted.
- [ ] Distinguish: missing project returns `None`; existing project with no final chapters returns an empty directory; missing target final chapter returns a target-missing record; database exceptions become `ManuscriptUnavailable` without chained sensitive causes.
- [ ] For directory rows, validate project/session/final/outline/planning pins and volume structure without loading or checking final prose SHA-256. Sum database scalar counts deterministically in Python.
- [ ] For a target chapter, validate the same authority chain, decode the exact pinned Outline/Planning, recompute target final prose SHA-256, compute scalar count from the verified string, and project only approved outline fields. Never query Outline history or use `session_pinned` status selection.
- [ ] Reuse the new shared helpers from `NovelDownloadRepository`; delete the duplicate implementations there.
- [ ] Add disposable-MySQL cases for: active/archived equivalence; chapter gaps; the three real-shaped Chinese titles; moved Planning head with pinned historical authority; missing pinned rows; bad Outline/Planning hashes; target prose corruption; and a corrupt chapter 3 that does not block directory or chapter 1.
- [ ] Run:

```powershell
python -m pytest backend/tests/unit/test_manuscript_repository.py backend/tests/unit/test_novel_download_repository.py -q
python -m pytest backend/tests/integration/test_manuscript_repository_mysql.py backend/tests/integration/test_novel_download_repository_mysql.py -m mysql -q
```

  Expected: exit 0; captured SQL proves the directory transfers no prose and neighbor lookup transfers no neighbor prose.
- [ ] Commit: `feat: read pinned manuscript records`

## Task 4: Expose strict read-only manuscript APIs

**Files:**

- Create: `backend/services/manuscripts.py`
- Create: `backend/domain/routers/manuscripts.py`
- Create: `backend/tests/unit/test_manuscript_service.py`
- Create: `backend/tests/api/test_manuscript_routes.py`
- Modify: `backend/domain/routers/__init__.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/api/test_route_inventory.py`
- Modify: `backend/tests/unit/test_router_domain_boundary.py`

- [ ] Write failing service tests for exact directory and chapter response shapes, canonical ordering, chapter gaps, total scalar sum, previous/next based on actual final rows, active/archived lifecycle, and persisted-millisecond-to-UTC RFC 3339 conversion.
- [ ] Define strict response DTOs in `backend/services/manuscripts.py`; serialize camel-case aliases and fixed `Z` timestamps. Keep `content` only in the target chapter DTO and omit every internal identifier except the approved volume `id`.
- [ ] Open one read-only transaction per service call. Map repository outcomes to the narrow internal domain errors without logging response bodies or stored payloads.
- [ ] Write failing API tests for these exact routes:

```text
GET /api/projects/{project_id}/manuscript
GET /api/projects/{project_id}/manuscript/chapters/{chapter_number}
```

- [ ] Cover the complete public matrix and fixed safe messages:

```python
EXPECTED = {
    (404, "ManuscriptProjectNotFound"),
    (404, "FinalChapterNotFound"),
    (422, "ManuscriptRequestInvalid"),
    (500, "ManuscriptIntegrityFailure"),
    (503, "ManuscriptTemporarilyUnavailable"),
}
```

- [ ] Reject non-positive/malformed chapter numbers and every unknown query parameter with `ManuscriptRequestInvalid`. Do not let FastAPI’s default validation body become the public contract; install a route-local closed query/path validator.
- [ ] Add success headers `Cache-Control: private, no-store` and `X-Content-Type-Options: nosniff`. Assert errors never contain stored IDs, hashes, field paths, SQL, prose, raw JSON, or exception text.
- [ ] Register the router and add both GET routes to the closed inventory. Keep all request parsing and HTTP mapping in `backend/domain/routers/manuscripts.py`; repository imports remain forbidden at the router boundary.
- [ ] Run:

```powershell
python -m pytest backend/tests/unit/test_manuscript_service.py backend/tests/api/test_manuscript_routes.py backend/tests/api/test_route_inventory.py backend/tests/unit/test_router_domain_boundary.py -q
python -m py_compile backend/domain/manuscripts.py backend/repositories/manuscripts.py backend/services/manuscripts.py backend/domain/routers/manuscripts.py
```

  Expected: exit 0 and the route inventory contains exactly the two new manuscript GET entries.
- [ ] Request independent Phase 1 code review against spec sections 6.2, 6.3, 8, 10, and 12.1. Resolve every Blocking/Major finding.
- [ ] Run a visible API/browser probe against a disposable database: directory → chapter 1 → outline payload → chapter 2 navigation, plus the corrupt chapter-3 isolation case. Record that no Provider endpoint or product database was touched.
- [ ] Commit: `feat: expose finalized manuscript reading`

## Task 5: Add strict frontend API parsing and one preparation-action mapper

**Files:**

- Create: `frontend/src/application/projects/projectNextAction.js`
- Create: `frontend/src/application/manuscript/manuscriptController.js`
- Create: `frontend/tests/unit/projectNextAction.test.mjs`
- Create: `frontend/tests/unit/manuscriptApi.test.mjs`
- Create: `frontend/tests/unit/manuscriptController.test.mjs`
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: `frontend/tests/unit/projectPreparationOverview.test.mjs`

- [ ] Extract the overview’s current preparation copy into `mapProjectNextAction(preparation)`. Write table-driven failing tests for every existing `nextAction`, including `prepare_chapter_outline`, active session/draft continuation, a provided safe `targetPath`, archived lifecycle, missing fields, and unknown actions.
- [ ] Return one closed UI value rather than localized fields from the backend:

```javascript
{
  state: 'available',
  label: '继续创作第 4 章',
  description: '回到当前权威章节，继续已有写作。',
  targetPath: '/projects/p1/write/chapters/4',
  chapterNumber: 4,
}
```

  The only other states are `{ state: 'archived' }` and `{ state: 'unavailable', label: '重新读取创作状态' }`. Never calculate `chapterNumber + 1` in this mapper.
- [ ] Update `ProjectOverviewView.vue` to consume the mapper with no local duplicate `actionCopy` table. Preserve all existing preparation status and retry behavior.
- [ ] Add `api.manuscripts.index(projectId, options)` and `api.manuscripts.chapter(projectId, chapterNumber, options)` to `frontend/src/api/db/client.js`; both use the existing JSON request path and pass an `AbortSignal`.
- [ ] Write strict client tests for URL encoding, exact paths, GET semantics, abort forwarding, no query fields, safe `ApiError` outcomes, and closed response parsing.
- [ ] Add exact manuscript response parsers in `frontend/src/api/db/client.js`. Before returning data, reject unknown fields, wrong primitive types, duplicate chapter numbers, unsorted/crossed volumes, bad navigation neighbors, internal keys (`hash`, `revision`, `basis`, `contentHash`), and a scalar count that does not match target prose according to the existing `unicodeScalarLength` helper.
- [ ] Keep `manuscriptController.js` responsible for request ownership and page state, not a second response parser. It must verify that the parsed response still matches the requested project/chapter before publishing it and discard any stale generation.
- [ ] Build separate `content` and `preparation` state machines. Content states are `idle | loading | ready | empty | missing-project | missing-chapter | invalid-address | integrity-failure | unavailable`; preparation states are `idle | loading | ready | unavailable | archived`.
- [ ] Use one generation keyed only by normalized `(projectId, chapterNumber)` and an `AbortController`. A `view` query change must not increment generation, issue a request, clear content, move focus, or reset scroll.
- [ ] Map public error codes to fixed Chinese author copy. Do not render `error.message`; unknown failures become `unavailable`. Preserve only the safe `correlationId` for a default-collapsed “关联编号” detail on integrity/temporary failures. A 503 retry keeps the last already-validated content visible.
- [ ] Run:

```powershell
node --test frontend/tests/unit/projectNextAction.test.mjs frontend/tests/unit/manuscriptApi.test.mjs frontend/tests/unit/manuscriptController.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs
```

  Expected: exit 0; tests prove content and preparation can succeed/fail independently.
- [ ] Commit: `feat: coordinate manuscript frontend state`

## Task 6: Add manuscript routes, navigation, directory, and overview entry

**Files:**

- Create: `frontend/src/views/ManuscriptIndexView.vue`
- Create: `frontend/src/components/manuscript/ManuscriptChapterList.vue`
- Create: `frontend/tests/unit/manuscriptIndexView.test.mjs`
- Create: `frontend/tests/unit/manuscriptComponents.test.mjs`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: `frontend/tests/unit/projectRoutes.test.mjs`
- Modify: `frontend/tests/unit/productShell.test.mjs`
- Modify: `frontend/tests/unit/projectRouteSfcIntegration.test.mjs`
- Modify: `frontend/tests/unit/projectPreparationOverview.test.mjs`

- [ ] Add failing path-helper and route-inventory tests for:

```javascript
manuscriptPath('project 1')
// /projects/project%201/manuscript
finalChapterPath('project 1', 3)
// /projects/project%201/manuscript/chapters/3
```

  `finalChapterPath` must reuse the positive-integer guard used by `chapterWriterPath`.
- [ ] Register lazy route names `ProjectManuscript` and `FinalChapterReader`. Reader props must contain only route params; the `view` query remains router state.
- [ ] Add “作品稿件” after “故事规划” and before “模型绑定” for both active and archived projects. Select it for both manuscript route names and use `aria-current="page"` through the existing Sidebar link behavior.
- [ ] Extend shell titles: directory is “作品稿件”; reader is the route-stable “第 N 章定稿”. Do not load or publish the asynchronous chapter title into the global shell.
- [ ] Write component tests for a continuous semantic directory grouped by volume. Each chapter grid row must contain sibling elements: one reader link as the primary hit area and one secondary download control. Assert no interactive element is nested in another.
- [ ] Implement the directory page with one `h1`, work title, final chapter count, total “字数”, active preparation action or archived read-only label, secondary download menu, and chapter rows with title/count/time/status.
- [ ] Use `api.novelDownloads.options` only to declare available download scope/format entries, and the existing `novelDownloadController` to deliver files. A failure to load options hides the affected download menu and provides a local retry; it must not hide the manuscript directory.
- [ ] Implement the empty state “还没有已定稿章节”. For an active project it uses the same `mapProjectNextAction`; for archived it exposes no creative CTA and no disabled download controls.
- [ ] Replace the overview’s `NovelDownloadPanel` with one manuscript summary link “作品稿件 · 已定稿 N 章”. Keep `ProjectBackupPanel` in place and do not add a second directory/download panel.
- [ ] Cover missing project, integrity failure, temporary failure with retained content, preparation failure with readable directory, archived state, and retry ownership. Author-visible markup must not contain `Canon`, `Projection`, UUID-shaped text, hashes, revisions, field paths, or raw JSON.
- [ ] Run:

```powershell
node --test frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs frontend/tests/unit/projectRouteSfcIntegration.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs frontend/tests/unit/manuscriptComponents.test.mjs frontend/tests/unit/manuscriptIndexView.test.mjs
npm --prefix frontend run build
```

  Expected: tests and production build exit 0; the overview owns one manuscript entry and no full download panel.
- [ ] Commit: `feat: add manuscript directory product flow`

## Task 7: Build finalized chapter reader and pinned-outline view

**Files:**

- Create: `frontend/src/views/FinalChapterReaderView.vue`
- Create: `frontend/src/components/manuscript/FinalChapterArticle.vue`
- Create: `frontend/src/components/manuscript/FinalOutlinePanel.vue`
- Create: `frontend/tests/unit/finalChapterReaderView.test.mjs`
- Modify: `frontend/tests/unit/manuscriptComponents.test.mjs`

- [ ] Write failing reader tests for absent/invalid `view` normalizing to `text`, `?view=text` and `?view=outline` deep links, query-only browser navigation without a second chapter request, and project/chapter changes creating a new request generation.
- [ ] Implement the page order exactly: directory backlink; volume/number/title/count/finalized time; “正文 / 本章小纲” controls; selected content; previous/directory/next navigation; active-project current creation action.
- [ ] Use real buttons or links with `aria-pressed`/current semantics for view switching. Update only `route.query.view` with Vue Router and preserve unrelated safe query absence; normalize invalid values with `replace`, not an extra history entry.
- [ ] Render prose in `FinalChapterArticle.vue` as plain text paragraphs split only on normalized blank lines. Never use `v-html`, Markdown execution, JSON serialization, or download-text parsing. Set a reading measure near 42 Chinese characters and line-height at least 1.75 with relative units.
- [ ] Render only the six author outline fields in `FinalOutlinePanel.vue`. Empty arrays use a plain “无” value; do not show a diagnostics section unless a later separately approved scope adds it.
- [ ] Use only response navigation values for previous/next links. Omit a missing edge; allow cross-volume and chapter-number gaps. The directory link is always available.
- [ ] Keep article and outline hidden together on integrity failure. A missing final chapter states that it “不属于作品稿件” and offers directory plus the independently loaded safe current action.
- [ ] Add chapter download as a secondary reader action through the existing download controller. A chapter download error stays local and cannot replace verified on-screen prose.
- [ ] Assert the final article is read-only: no textbox, contenteditable, “编辑本章”, “重新打开会话”, commit, generation, or mutation button exists.
- [ ] Run:

```powershell
node --test frontend/tests/unit/manuscriptController.test.mjs frontend/tests/unit/manuscriptComponents.test.mjs frontend/tests/unit/finalChapterReaderView.test.mjs
npm --prefix frontend run build
```

  Expected: exit 0; query-only changes reuse the same loaded chapter and navigation uses actual final rows.
- [ ] Commit: `feat: read finalized chapters in product`

## Task 8: Close the post-finalization transition

**Files:**

- Modify: `frontend/src/application/writer/finalizationController.js`
- Modify: `frontend/src/components/writer/FinalizationPanel.vue`
- Modify: `frontend/src/views/ChapterWriterView.vue`
- Modify: `frontend/tests/unit/finalizationController.test.mjs`
- Modify: `frontend/tests/unit/finalizationPanel.test.mjs`
- Modify: `frontend/tests/unit/chapterWriterView.test.mjs`

- [ ] Add failing controller tests that preserve the committed result’s chapter number, call `onCommitted` once, then independently reload preparation and verify the just-finalized chapter through `api.manuscripts.chapter`.
- [ ] Add a route-safe post-finalization value:

```javascript
{
  currentAction: mapProjectNextAction(reloadedPreparation),
  finalizedChapterPath: '/projects/p1/manuscript/chapters/4',
  finalizedChapterReadable: true,
}
```

  When preparation fails, `currentAction` is unavailable. When the reader verification fails, omit only the finalized-chapter action. Never infer chapter 5 or assume the committed chapter is readable.
- [ ] Keep commit idempotency/recovery behavior unchanged. A post-commit read failure must not change the server-authoritative “已定稿” result into a failed commit.
- [ ] Replace the success alert copy that says future changes are unimplemented. Show the mapped next creative action as primary and “查看本章定稿” as secondary only after reader verification.
- [ ] Wire `ChapterWriterView.vue` to the same preparation mapper used by overview/directory/reader. Do not pass the just-finalized old chapter number to the writer CTA.
- [ ] Assert finalization success stays on the page, exposes both verified paths, and neither action triggers automatically.
- [ ] Run:

```powershell
node --test frontend/tests/unit/finalizationController.test.mjs frontend/tests/unit/finalizationPanel.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/projectNextAction.test.mjs
npm --prefix frontend run build
```

  Expected: exit 0; committed authority survives either follow-up read failure.
- [ ] Request independent Phase 2 code review against the complete desktop loop: overview → directory → reader/outline/download → current writing and writer finalization → reader → next current action. Resolve every Blocking/Major finding.
- [ ] Run the desktop loop in a visible 1440×900 browser on a disposable three-final-chapter fixture. Use links and buttons only; verify browser back/forward and refreshed outline deep link. Do not use browser `fetch`, `page.request`, database writes during the scenario, or a Provider.
- [ ] Commit: `feat: close finalized manuscript author loop`

## Task 9: Make shell, focus, history, and narrow-screen navigation accessible

**Files:**

- Create: `frontend/src/components/layout/MobileNavigationDrawer.vue`
- Create: `frontend/src/application/manuscript/manuscriptHistory.js`
- Create: `frontend/tests/unit/mobileNavigationDrawer.test.mjs`
- Create: `frontend/tests/unit/manuscriptHistory.test.mjs`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/layout/Sidebar.vue`
- Modify: `frontend/src/style.css`
- Modify: `frontend/src/views/ManuscriptIndexView.vue`
- Modify: `frontend/src/views/FinalChapterReaderView.vue`
- Modify: `frontend/tests/unit/productShell.test.mjs`
- Modify: `frontend/tests/unit/manuscriptIndexView.test.mjs`
- Modify: `frontend/tests/unit/finalChapterReaderView.test.mjs`

- [ ] Add a first-focusable skip link “跳到主内容” before the shell. Give the shell’s one semantic `<main>` `id="main-content"` and `tabindex="-1"`; make new route views use `<section>` roots so they do not nest `<main>` landmarks.
- [ ] Add failing shell tests at widths 390, 760, 761, 1119, 1120, and 1440. Widths at or below 760 use the mobile top-bar menu/drawer and no fixed sidebar rail; 761–1119 use the existing compact labeled-by-accessible-name rail; 1120 and above use the complete desktop sidebar.
- [ ] Implement `MobileNavigationDrawer.vue` from the existing shell navigation model. It must expose `role="dialog"`, `aria-modal="true"`, a visible title, a visible close button, current-page state, and links for the same active/archived project modules as desktop.
- [ ] On open: save the menu-button element, lock background scrolling, set the non-drawer application region `inert`, move focus to the first actionable drawer item, and trap Tab/Shift+Tab. On Escape, close button, or navigation: close, remove `inert`, restore scrolling, and return focus to the menu button when it still exists.
- [ ] Add unit tests for opening, focus entry, forward/backward focus wrap, Escape, visible close, backdrop/background inertness, selected link, navigation close, teardown while open, and focus return. Keep touch targets at least 44×44 CSS px.
- [ ] Implement `manuscriptHistory.js` with a namespaced `history.state.manuscriptView` value containing only `{ routeKey, scrollTop, focusId }`. Save before leaving a manuscript history entry; restore after the destination view has rendered and only when the recorded target still exists.
- [ ] On a new project ID or chapter number: reset the custom main scroll container to 0 and focus the page `h1` using `preventScroll`. On `view` query changes: do neither. On browser back/forward: restore that entry’s recorded scroll and focus. Never store content, outline values, title, project ID outside the route key, or preparation data.
- [ ] Add unit tests that distinguish `push`, `replace`, and `popstate` entry behavior; prove two chapter entries retain different scroll positions and an outline/text query toggle does not overwrite or reset the current position.
- [ ] Add responsive CSS proving no horizontal overflow for the whole shell, directory, reader, drawer, menus, and controls. At 200% zoom, allow normal wrapping and vertical growth; never shrink body text or controls below accessible sizes to make them fit.
- [ ] Respect `prefers-reduced-motion` in drawer, shell, view switch, and reading transitions. Remove nonessential transition/animation under the media query.
- [ ] Run:

```powershell
node --test frontend/tests/unit/mobileNavigationDrawer.test.mjs frontend/tests/unit/manuscriptHistory.test.mjs frontend/tests/unit/productShell.test.mjs frontend/tests/unit/manuscriptIndexView.test.mjs frontend/tests/unit/finalChapterReaderView.test.mjs
npm --prefix frontend run build
```

  Expected: exit 0; the breakpoint boundary is explicitly covered on both 760 and 761 CSS px.
- [ ] Request independent Phase 3 accessibility/responsive code review. Require evidence for landmark validity, accessible names, keyboard order, trap escape, focus return, history restoration, reduced motion, and non-nested controls. Resolve every Blocking/Major finding.
- [ ] Run visible-browser checks at 390×844, 760×900, and 761×900. At each size assert `document.documentElement.scrollWidth <= document.documentElement.clientWidth`, complete the drawer keyboard path, and read/open chapter 1 without pointer-only operations.
- [ ] Commit: `feat: make manuscript reading accessible`

## Task 10: Build deterministic Phase 8A browser fixtures and runner

**Files:**

- Create: `backend/scripts/prepare_phase8a_browser_db.py`
- Create: `backend/tests/unit/test_prepare_phase8a_browser_db.py`
- Create: `frontend/e2e/phase8a/manuscript-productization.spec.mjs`
- Create: `frontend/e2e/playwright.phase8a.config.mjs`
- Create: `frontend/e2e/run-phase8a.mjs`
- Modify: `scripts/run-tests.mjs`
- Modify: `scripts/tests/testEntrypoint.test.mjs`
- Modify: root `package.json`
- Modify: `frontend/package.json`

- [ ] Write the runner-contract tests first. Reserve unique API/Vite/MySQL ports; own one temporary directory, browser download directory, and disposable `novel_creator_test_%` schema; enforce cleanup on success, assertion failure, signal, and child-process startup failure.
- [ ] Make `prepare_phase8a_browser_db.py` create three independent projects before services start:

  1. `complete`: active project, one volume, finalized chapters 1–3 with titles “泔水醒来，三日织机赌局”, “废料改机”, and “复验定局”, exact pinned Outlines, and current authority chapter 4.
  2. `awaiting-author`: active project with finalized chapters 1–3 and a Provider-free chapter 4 finalization review already at `awaiting_author`, so visible UI confirmation/commit can finalize it without generation.
  3. `corrupt`: active project with finalized chapters 1–3 where chapter 3 content does not match its stored hash; all other pins remain valid.

- [ ] Make fixture creation idempotent only within the disposable schema setup step. The browser scenario must never call the fixture script, write SQL, or mutate database state except through visible product UI and formal APIs.
- [ ] Add `browser-phase8a` to `scripts/run-tests.mjs`, `test:browser:phase8a` to both package files, and formal-test inventory coverage for the one Phase 8A Playwright spec.
- [ ] In the complete fixture, use visible UI to run: overview manuscript summary → sidebar manuscript directory → verify the three exact titles and volume grouping → chapter 1 prose → pinned outline → next chapter → browser back → refresh `?view=outline` → current chapter-4 action. Assert historical reading never shows the authoritative writer-conflict message.
- [ ] Download chapter 1, the volume, and the whole book using Playwright download events. Assert finalized headings/bodies are in deterministic order and no working/candidate sentinel text appears.
- [ ] Archive the complete fixture through visible product UI, return to manuscript, read prose/outline, download again, and assert all creative CTAs disappear while read-only access remains.
- [ ] In the awaiting-author fixture, commit chapter 4 through visible UI, wait for preparation reload and reader verification, follow “查看本章定稿”, follow the mapped chapter-5 action, then return through manuscript to chapter 4. Assert no Provider request is made.
- [ ] In the corrupt fixture, assert the directory lists chapters 1–3; chapter 1 read/download succeeds; chapter 3 read/download fails safely; volume/book download fails; and visible text contains no prose body from the failure, hash, UUID, SQL, field path, or raw exception.
- [ ] Run the fixed viewport matrix:

  - 1440×900 at browser zoom 100%: full desktop rail and complete desktop flow.
  - 1280×800 changed from browser zoom 100% to 200% by repeatedly using Chromium’s real browser zoom-in accelerator in headed Windows Chromium until the measured zoom ratio reaches 2.0: shell, directory, reader, and drawer.
  - 390×844 at 100%: mobile directory, reader, and drawer.
  - 760×900 and 761×900 at 100%: both sides of the shell breakpoint.

- [ ] For the 200% run, record pre/post `window.innerWidth` and `window.devicePixelRatio` and assert both change consistently with browser zoom. Do not use Playwright `deviceScaleFactor`, a smaller viewport substitute, CSS transform/zoom, or page-scale injection.
- [ ] At every matrix point assert no horizontal overflow, all visible controls are keyboard focusable in DOM order, drawer background is inert, Escape and visible close both work, focus returns to menu, touch targets meet 44×44 CSS px, and reduced-motion emulation removes nonessential motion.
- [ ] Keep business assertions on visible UI. Forbid `page.request`, browser `fetch`, `page.evaluate` mutation, route interception, DOM state injection, and scenario-time direct SQL. Permit `page.evaluate` only for read-only geometry/overflow/zoom assertions.
- [ ] Run:

```powershell
python -m pytest backend/tests/unit/test_prepare_phase8a_browser_db.py -q
node --test scripts/tests/testEntrypoint.test.mjs
npm run test:browser:phase8a
```

  Expected: exit 0; the runner reports zero owned child processes, ports, temporary paths, downloads, and disposable schemas after completion.
- [ ] Commit: `test: accept manuscript browser workflow`

## Task 11: Run full gates, independent acceptance, and product read-only smoke

**Files:**

- Create: `backend/scripts/verify_manuscript_product_smoke.py`
- Create: `backend/tests/unit/test_verify_manuscript_product_smoke.py`
- Create: `docs/superpowers/acceptance/2026-08-24-phase8a-manuscript-productization.md`

- [ ] Write unit tests for the product smoke verifier before the verifier. Require one explicit project ID, read-only transaction setup, only `SELECT` statements/repository reads, fixed safe summaries, and rejection of any SQL command containing insert/update/delete/replace/alter/drop/create/truncate or multiple statements.
- [ ] Implement `python -m backend.scripts.verify_manuscript_product_smoke --project-id 474d110f-977c-4c82-bec4-464f30ec5a16`. It must call the production manuscript read service for directory and chapters 1–3 plus the existing preparation service, assert the three approved titles and current authority chapter 4, and print only counts/status—not content, DSN, IDs other than the supplied project ID, hashes, Outline payloads, or exceptions.
- [ ] Run fresh focused gates once after all implementation changes:

```powershell
python -m pytest backend/tests/unit/test_manuscript_domain.py backend/tests/unit/test_manuscript_repository.py backend/tests/unit/test_manuscript_service.py backend/tests/unit/test_novel_downloads.py backend/tests/unit/test_novel_download_repository.py backend/tests/unit/test_novel_download_service.py backend/tests/api/test_manuscript_routes.py backend/tests/api/test_novel_download_routes.py backend/tests/api/test_route_inventory.py backend/tests/unit/test_router_domain_boundary.py backend/tests/unit/test_prepare_phase8a_browser_db.py backend/tests/unit/test_verify_manuscript_product_smoke.py -q
python -m pytest backend/tests/integration/test_manuscript_repository_mysql.py backend/tests/integration/test_novel_download_repository_mysql.py -m mysql -q
node --test frontend/tests/unit/projectNextAction.test.mjs frontend/tests/unit/manuscriptApi.test.mjs frontend/tests/unit/manuscriptController.test.mjs frontend/tests/unit/manuscriptHistory.test.mjs frontend/tests/unit/manuscriptComponents.test.mjs frontend/tests/unit/manuscriptIndexView.test.mjs frontend/tests/unit/finalChapterReaderView.test.mjs frontend/tests/unit/mobileNavigationDrawer.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs frontend/tests/unit/projectRouteSfcIntegration.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs frontend/tests/unit/finalizationController.test.mjs frontend/tests/unit/finalizationPanel.test.mjs frontend/tests/unit/chapterWriterView.test.mjs
npm --prefix frontend run build
npm run test:browser:phase8a
```

  Expected: every command exits 0; disposable MySQL and browser resource ledgers are clean.
- [ ] Run risk-related full regression gates, one at a time, diagnosing the first failure before any rerun:

```powershell
npm test
npm run test:integration
npm --prefix frontend run test:unit
npm run build
```

  Expected: every command exits 0. Record fresh counts because this slice adds tests; do not reuse the pre-slice 5156/432/793 baseline as completion evidence.
- [ ] Request an independent final code review and an independent visible-browser product-flow review. Give reviewers the approved spec, this plan, commits, focused/full command evidence, and Phase 8A resource ledger. Resolve every Blocking/Major and rerun only the gates affected by each fix, followed by one final complete focused gate set.
- [ ] After automated gates and independent reviews pass, run the product smoke verifier against “典镇山河”. Then open the product UI in a visible browser and read only: manuscript directory, chapters 1–3 prose, all three pinned outlines, chapter-1 deep link, and the current chapter-4 action.
- [ ] During product smoke, do not invoke write/generate/finalize/archive/restore/download mutation endpoints, direct SQL writes, test fixture code, Provider endpoints, or external websites. Capture only UI screenshots and safe status/count evidence; never capture or log full prose.
- [ ] Verify `git status --short` shows only intended tracked changes plus the pre-existing `?? .review-worktrees/`; verify `git diff --check`; verify no secrets, product prose, database dump, browser download, screenshot, or temp artifact is staged.
- [ ] Write the acceptance record with exact commit hashes, commands, fresh pass/skip counts, browser matrix, first-cause/fix history, independent review dispositions, zero-Provider statement, product read-only statement, and cleanup ledger.
- [ ] Commit: `docs: accept manuscript productization slice`
- [ ] Push the reviewed commits to `origin/main` only after confirming local `main` is a fast-forward of the expected remote and the worktree contains no unintended staged path.

## Completion boundary

State completion only when all four phase gates, focused/full regressions, visible Phase 8A browser matrix, independent final reviews, and strict product read-only smoke pass. The completion statement may claim the “作品稿件” slice only. It must not claim that the later full project-stage transition productization, real Provider quality, editing/version history, search, annotation, or the complete long-form creation product is finished.
