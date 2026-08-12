# Phase 6A Finalized Novel Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let an author download only finalized chapters as one deterministic TXT or Markdown file from either an active or archived project.

**Architecture:** Add one closed read model from `final_chapters` through its pinned ChapterSession, ChapterOutline revision, and Planning revision. A pure domain renderer produces exact bytes; a thin FastAPI router exposes options and the attachment. The Vue UI uses one narrow binary client/controller and a shared compact panel. This slice adds no schema, job, temporary file, Provider call, or product-database access.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, aiomysql repository sessions, Vue 3, Pinia, Naive UI, Node test runner, pytest, Playwright, disposable MySQL.

---

## Scope guard

- Implement only Phase 6A sections 2 and 3 of `docs/superpowers/specs/2026-08-09-phase6-download-backup-import-design.md`.
- Read only `final_chapters`; never substitute WorkingDraft, Candidate, partial operation output, current Planning head, or placeholder prose.
- Keep download synchronous and memory-bounded by a fixed 128 MiB output limit. This product currently targets a local single-author novel, so a job system or temporary file would be unjustified.
- Do not add PDF, EPUB, DOCX, multi-file ZIP, chapter ranges, custom templates, cancellation, or download history.
- Run focused tests during tasks. Run the branch-wide Python/Node/MySQL/build/browser gates only after 6C at Phase 6 close.

## Execution status (2026-08-10)

Tasks 1–6 are implemented and committed through `0de6402`. Task 7 focused verification,
specification review, quality review, resource audit, and acceptance record are complete. Phase 6A
is accepted only for finalized TXT/Markdown download with disposable local data; Phase 6B backup,
Phase 6C import, complete Phase 6, real Provider quality, and product-database readiness remain open.

## Task 1: Closed download domain and deterministic renderer

**Files:**

- Create: `backend/domain/novel_downloads.py`
- Create: `backend/tests/unit/test_novel_downloads.py`

- [ ] Write failing tests for strict selector validation:
  - `book` rejects `volumeId` and `chapterNumber`;
  - `volume` requires only `volumeId`;
  - `chapter` requires only a positive `chapterNumber`;
  - only `txt` and `markdown` are accepted.
- [ ] Write failing tests for book, volume, and chapter selection, global chapter ordering, and exact missing-scope outcomes.
- [ ] Write failing byte fixtures proving UTF-8 without BOM, LF normalization, exactly one final newline, and these exact structures:

```python
assert render_txt(snapshot) == (
    "书名\n\n"
    "===== 第 1 卷 · 卷名 =====\n\n"
    "----- 第 1 章 · 章名 -----\n\n"
    "正文\n"
).encode("utf-8")

assert render_markdown(snapshot) == (
    "# 书名\n\n"
    "## 第 1 卷 · 卷名\n\n"
    "### 第 1 章 · 章名\n\n"
    "正文\n"
).encode("utf-8")
```

- [ ] Write failing tests for flattened/escaped headings, unchanged prose apart from CRLF/CR normalization, and the 128 MiB fail-closed output ceiling.
- [ ] Implement immutable values with closed fields:

```python
DownloadScope = Literal["book", "volume", "chapter"]
DownloadFormat = Literal["txt", "markdown"]

class NovelDownloadSelector(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    scope: DownloadScope
    format: DownloadFormat
    volume_id: str | None = None
    chapter_number: int | None = Field(default=None, ge=1)

class FinalizedChapterSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    chapter_number: int = Field(ge=1)
    chapter_title: str
    volume_id: str
    volume_order: int = Field(ge=1)
    volume_title: str
    content: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
```

- [ ] Implement `select_chapters`, `render_novel_download`, `safe_attachment_names`, and domain exceptions. Recompute every final prose SHA-256 before selecting or rendering.
- [ ] Run `python -m pytest backend/tests/unit/test_novel_downloads.py -q` and record only exit/count/first cause.
- [ ] Commit: `feat: render finalized novel downloads`

## Task 2: Pinned historical read repository

**Files:**

- Create: `backend/repositories/novel_downloads.py`
- Create: `backend/tests/unit/test_novel_download_repository.py`
- Create: `backend/tests/integration/test_novel_download_repository_mysql.py`

- [ ] Write failing repository-unit tests that assert explicit parameterized reads and corruption on any missing or mismatched pinned link.
- [ ] Write a focused disposable-MySQL test with two Planning revisions where the current head moves a chapter but the finalized chapter remains in the volume pinned at finalization.
- [ ] Add sentinel WorkingDraft and Candidate bodies and prove neither appears in the returned snapshot.
- [ ] Implement one read-only repository method:

```python
class NovelDownloadRepository:
    async def load_finalized_snapshot(
        self, session, project_id: str
    ) -> NovelDownloadSnapshot | None:
        ...
```

- [ ] Query explicit columns from `projects`, `final_chapters`, `chapter_sessions`, `chapter_outline_revisions`, and `planning_revisions`; do not use `SELECT *`, heads, Provider tables, or project-global mutable Planning.
- [ ] Decode `planning_json` with `backend/domain/planning.py` and `outline_json` with `backend/domain/chapter_outlines.py`. Verify persisted revision ids, revision numbers, hashes, chapter number, story-block/volume reference, and volume membership before returning domain values.
- [ ] Allow project lifecycle `active` or `archived`; treat missing project separately from a project with zero finalized chapters.
- [ ] Run:

```powershell
python -m pytest backend/tests/unit/test_novel_download_repository.py -q
python -m pytest backend/tests/integration/test_novel_download_repository_mysql.py -q
```

- [ ] Verify disposable database ledger shows created = cleaned and remaining = 0.
- [ ] Commit: `feat: read pinned finalized novel snapshots`

## Task 3: Service and closed HTTP boundary

**Files:**

- Create: `backend/services/novel_downloads.py`
- Create: `backend/routers/novel_downloads.py`
- Create: `backend/tests/unit/test_novel_download_service.py`
- Create: `backend/tests/api/test_novel_download_routes.py`
- Modify: `backend/main.py`
- Modify: the existing route-inventory test located by repository search

- [ ] Write failing service tests for option projection, scope selection, absent project, zero finalized chapters, missing requested scope, and integrity failure.
- [ ] Implement a read-only transaction boundary and return either options DTOs or exact rendered bytes plus names/media type. Keep response bytes capped at 128 MiB.
- [ ] Write failing API tests for the two exact routes:

```text
GET /api/projects/{project_id}/novel-download/options
GET /api/projects/{project_id}/novel-download
```

- [ ] Test strict query combinations and closed public outcomes: 404 missing project/scope, 409 no finalized chapter, 422 invalid query, fixed 500 integrity error.
- [ ] Test exact success headers:

```python
assert response.headers["cache-control"] == "private, no-store"
assert response.headers["x-content-type-options"] == "nosniff"
assert response.headers["content-disposition"].startswith("attachment;")
assert "filename=" in response.headers["content-disposition"]
assert "filename*=UTF-8''" in response.headers["content-disposition"]
```

- [ ] Use `text/plain; charset=utf-8` for TXT and `text/markdown; charset=utf-8` for Markdown. Do not log or embed prose in public errors.
- [ ] Register only the new router in `backend/main.py` and add both GET routes to the closed route inventory.
- [ ] Run:

```powershell
python -m pytest backend/tests/unit/test_novel_download_service.py backend/tests/api/test_novel_download_routes.py -q
python -m py_compile backend/domain/novel_downloads.py backend/repositories/novel_downloads.py backend/services/novel_downloads.py backend/routers/novel_downloads.py
```

- [ ] Commit: `feat: expose finalized novel downloads`

## Task 4: Binary frontend client and single-owner controller

**Files:**

- Modify: `frontend/src/api/db/client.js`
- Create: `frontend/src/application/downloads/novelDownloadController.js`
- Create: `frontend/tests/unit/novelDownloadApi.test.mjs`
- Create: `frontend/tests/unit/novelDownloadController.test.mjs`

- [ ] Write failing client tests proving the existing JSON request path remains unchanged and a new narrow binary request returns `{ blob, contentDisposition }`.
- [ ] Verify abort/network/non-2xx responses still become fixed safe API errors and response bodies are never rendered as filenames.
- [ ] Implement `getNovelDownloadOptions(projectId)` and `downloadFinalizedNovel(projectId, selector, { signal })` with `URLSearchParams` from the closed selector only.
- [ ] Write failing controller tests for exactly one in-flight request, operation-store start/finish in `finally`, no duplicate click, object URL creation, hidden anchor click, and unconditional `URL.revokeObjectURL`.
- [ ] Implement the controller with injected browser primitives so unit tests need no DOM patching:

```javascript
export function createNovelDownloadController({
  api,
  operationStore,
  createObjectURL,
  revokeObjectURL,
  saveBlob,
}) {
  let inFlight = false
  return { loadOptions, download, get inFlight() { return inFlight } }
}
```

- [ ] Parse only the server's safe `Content-Disposition`; use a fixed `novel.txt` or `novel.md` fallback.
- [ ] Run `node --test frontend/tests/unit/novelDownloadApi.test.mjs frontend/tests/unit/novelDownloadController.test.mjs`.
- [ ] Commit: `feat: download finalized novel in frontend`

## Task 5: Shared compact download panel and navigation fence

**Files:**

- Create: `frontend/src/components/projects/NovelDownloadPanel.vue`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: `frontend/src/views/ArchivedProjectStatusView.vue`
- Modify: `frontend/src/stores/operationStore.js`
- Modify: `frontend/src/components/common/AppOperationOverlay.vue`
- Modify: the existing application/root file that owns global `beforeunload`
- Create: `frontend/tests/unit/novelDownloadPanel.test.mjs`
- Modify/Create: focused operation-store, overlay, overview, archived-view, and navigation-fence tests matching repository conventions

- [ ] Write failing component tests for default whole-book TXT, closed scope/format controls, volume/chapter selector visibility, fixed no-finalized-content reason, and disabled duplicate submission.
- [ ] Implement the same compact panel in active Project Overview and archived read-only status. It is secondary to the one creative next action and never displays prose.
- [ ] Add only `operationStore.update(operationId, { label, detail })`; reject unknown ids and preserve ownership/blocking flags.
- [ ] Show current safe phase/detail in the existing overlay. Do not add persistence, history, progress percentages, or Cancel.
- [ ] Install one global `beforeunload` listener while `operationStore.blocking` is true and remove it on teardown. Keep the existing Vue Router navigation guard as the in-app fence.
- [ ] Run the exact focused frontend files, then `npm --prefix frontend run build` once for this slice.
- [ ] Commit: `feat: add finalized novel download panel`

## Task 6: One visible-browser acceptance path

**Files:**

- Create: `frontend/e2e/phase6a/` fixture/spec files following the Phase 5 runner pattern
- Create: `frontend/e2e/run-phase6a.mjs`
- Create: `playwright.phase6a.config.mjs`
- Modify: `scripts/run-tests.mjs`
- Modify: root `package.json`
- Modify: `frontend/package.json`
- Create/Modify: focused runner-contract tests following the Phase 5 conventions

- [ ] First add a failing runner-contract test proving Phase 6A owns unique API/Vite ports, an owned temp/download directory, one disposable `novel_creator_test_%` database, and no real Provider configuration.
- [ ] Add one browser case using only visible UI actions and Playwright's download event. Do not use `page.request`, `page.route`, `fetch`, `axios`, or `page.evaluate` to bypass the product chain.
- [ ] Seed two finalized chapters plus sentinel unsaved/working/candidate text. From Project Overview download whole-book TXT and assert the saved bytes include finalized text in order and exclude every sentinel.
- [ ] Archive the project through the product UI or fixture authority, open the archived read-only screen, and prove Markdown download remains available.
- [ ] Assert operation overlay/navigation fence behavior during an intentionally held local response without calling any Provider.
- [ ] On success and failure, verify browser, API, Vite, ports, owned temp/download files, and disposable database residue are all zero.
- [ ] Run only `npm run test:browser:phase6a`; diagnose any first failure before rerun.
- [ ] Commit: `test: accept phase6a finalized novel download`

## Task 7: Slice review and handoff into 6B

**Files:**

- Create: `docs/acceptance/2026-08-09-phase-6a-finalized-novel-download.md`
- Modify: the current Phase 6 status/plan document if one exists

- [ ] Run `git diff --check` and the combined focused Python/Node tests from Tasks 1–5 once fresh.
- [ ] Run a specification review against the Phase 6 design and this plan. Only Critical or Important defects on the active 6A path may re-enter implementation; record extreme non-blockers for later.
- [ ] After spec findings are 0/0/0, run one serial quality review with the same stop rule.
- [ ] Confirm no Provider call, no product database, no schema migration, no temp residue, and no owned process/port residue.
- [ ] Write a concise acceptance record with exact commands, exit/counts, first-cause history, and resource ledger; do not include prose bodies, DSNs, Provider text, or secrets.
- [ ] Commit: `docs: accept phase6a finalized novel download`
- [ ] Immediately create the separate Phase 6B execution plan and continue without asking the user to review or confirm the specification.

## Completion statement boundary

At 6A completion, state only that finalized TXT/Markdown download is accepted with disposable local data. Do not state that project backup/import, complete Phase 6, product-database readiness, or real-provider quality is accepted.
