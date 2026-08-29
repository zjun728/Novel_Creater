# Author-facing Planning and Bible Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for behavior changes, superpowers:requesting-code-review at each review gate, and superpowers:verification-before-completion before any completion claim.

**Goal:** Replace Planning’s raw Canon/Projection diagnostics and Creation Bible’s raw internal status values with bounded, author-facing Chinese presentation while preserving all existing authority, routing, and write behavior.

**Architecture:** Add two pure presentation modules at the application boundary. The Planning adapter validates the existing progress envelope and joins only closed, trusted progress shapes to the current Planning hierarchy before emitting an immutable, identifier-free display model. The Bible adapter owns closed reason/mode/history-status mappings and omission rules. Vue components render only those display values; backend DTOs, store/controller authority, and APIs remain unchanged.

**Tech Stack:** Vue 3 Composition API, JavaScript ES modules, Vite SSR component tests, Node test runner, Playwright/Chromium for read-only product acceptance.

---

## Scope fence

- Implement `docs/superpowers/specs/2026-08-29-author-facing-planning-status-design.md` exactly.
- Keep sidebar navigation and every save, confirm, generation, finalization, Canon, Projection, Planning, Bible, and routing authority unchanged.
- Do not add automatic navigation, stage buttons, backend routes, DTO/schema changes, database writes, migrations, or Provider calls.
- Validate headed Chromium only at 1440×900 and browser zoom 100%; mobile portrait and 200% zoom are outside scope.
- Do not fix the observed `GET /contract-draft` 404 or productize Bible history basis metadata in this slice.
- Keep `D:\Projects\Novel_Creater\.review-worktrees\` unmodified and untracked.
- Commit after each focused green task. Before acceptance, an independent reviewer must report no unresolved Blocking or Major finding.

## Task 0: Freeze the approved specification and reviewed plan

**Files:** `docs/superpowers/specs/2026-08-29-author-facing-planning-status-design.md` and this plan.

- [ ] Confirm the specification status is `Approved`, this plan has no placeholder, and an independent adversarial plan review reports Ready with zero Blocking/Major findings.
- [ ] Run `git diff --check`, `git diff --cached --check`, and `git status --short`. Expect only the approved spec status, this new plan, and untouched untracked `.review-worktrees/`.
- [ ] Commit the frozen documents before product code: `git add docs/superpowers/specs/2026-08-29-author-facing-planning-status-design.md docs/superpowers/plans/2026-08-29-author-facing-planning-status.md`, then `git diff --cached --check`, then `git commit -m "docs: plan author-facing planning status"`.
- [ ] Run `git status --short` and `git show --stat --oneline HEAD`; expect both documents committed and only `.review-worktrees/` untracked. Task 1 is forbidden until this gate is green.

## File map

Create:

- `frontend/src/application/planning/actualProgressPresentation.js`
- `frontend/src/application/bible/bibleStatusPresentation.js`
- `frontend/tests/unit/actualProgressPresentation.test.mjs`
- `frontend/tests/unit/bibleStatusPresentation.test.mjs`
- `docs/superpowers/acceptance/2026-08-29-author-facing-planning-status.md`

Modify:

- `frontend/src/components/planning/ActualProgressPanel.vue`
- `frontend/src/components/planning/PlanningWorkspace.vue`
- `frontend/src/application/bible/bibleWorkspaceController.js`
- `frontend/src/views/ProjectBibleView.vue`
- `frontend/src/components/bible/BibleHistoryDrawer.vue`
- `frontend/tests/unit/planningWorkspaceSfc.test.mjs`
- `frontend/tests/unit/bibleWorkspaceController.test.mjs`
- `frontend/tests/unit/projectBibleView.test.mjs`

## Display-model contracts

Planning exports `presentActualProgress({ items, status, planningContent })`. It applies an internal, non-overridable `MAX_VISIBLE_ROWS = 10` and returns a recursively frozen object containing only:

```js
{
  state: 'invalid' | 'syncing' | 'no-canon' | 'empty' | 'unrecognized' | 'recognized',
  heading: '正文进度',
  message: '固定中文状态文本',
  rows: [{ key: 'progress-row-0', chapterLabel: '第 3 章', kindLabel: '阶段', hierarchyLabel: '雨夜入县衙 / 初查', statusLabel: '已推进' }],
  omittedRecognizedCount: 0,
  unrecognizedCount: 0,
}
```

The display `key` is an ordinal, never a target ID. No raw entry, ID, path, revision, hash, subject, entity, rejected value, or exception is returned.

Bible exports `bibleReasonLabel(reason)`, `presentBibleReasons(reasons)`, `bibleModeLabel(mode)`, and `bibleHistoryStatusLabel(status)`. The controller re-exports `bibleReasonLabel` for compatibility.

## Task 1: Build the fail-closed Planning presentation adapter

**Files:** Create `frontend/src/application/planning/actualProgressPresentation.js` and `frontend/tests/unit/actualProgressPresentation.test.mjs`.

- [ ] Write a failing table test covering `story_block → 故事块`, `stage → 阶段`, `scene_task → 场景任务` and `started → 已开始`, `advanced → 已推进`, `completed → 已完成`. For every pair, provide an exact valid raw entry and matching Planning node. Assert author labels appear and raw field names/target IDs do not.
- [ ] Run `node --test frontend/tests/unit/actualProgressPresentation.test.mjs` and confirm RED with `ERR_MODULE_NOT_FOUND`.
- [ ] Implement status-envelope validation before inspecting entries:

```js
const validRevision = value => Number.isSafeInteger(value) && value >= 0
const validEnvelope = status => (
  status !== null
  && typeof status === 'object'
  && typeof status.synchronized === 'boolean'
  && validRevision(status.canonRevision)
  && validRevision(status.projectionRevision)
  && status.synchronized === (status.canonRevision === status.projectionRevision)
)
```

- [ ] Return only the approved fixed state and empty rows for invalid, syncing, no-Canon, and synchronized-empty cases. Invalid state must not fall through to row recognition.
- [ ] Index `planningContent.storyBlocks`, nested stages, and nested scene tasks. Match only a non-empty server `id`, never `clientNodeKey`. Preserve parents for block, block/stage, or block/stage/task hierarchy. Read only block/stage `title` and task `task`; trim labels and substitute `当前规划项` for blank text.
- [ ] Accept `value` only when its prototype is `Object.prototype` or `null` and its sorted own enumerable keys are exactly `chapterNumber,status,targetId,targetType`. Require supported strings, non-empty `targetId`, positive safe-integer chapter, `entityId === null`, `subjectKey === '__global__'`, exact `fieldPath === plot.progress.${targetType}.${targetId}`, and a same-kind indexed node.
- [ ] Deduplicate with nested maps keyed internally by chapter/kind/target ID/status so delimiters cannot collide. Sort by chapter descending then stable input order. Count distinct chapters before limiting to 10 rows. Return separate omitted-recognized and unrecognized counts; recursively freeze the result.
- [ ] Add adversarial tests for every invalid envelope including throwing status getters/proxies; `items` as null/object/string; null/array/primitive entries; throwing entry getters/proxies; malformed/null/array Planning content, throwing hierarchy getters, and non-array node collections; shape-colliding `plot.*` facts; mismatched path/value; unsupported `volume`/`plot`; wrong subject/entity; missing target; extra enumerable keys, inherited required keys, required keys made non-enumerable, or wrong scalar types; unsafe chapters; hostile UUID/hash/path/nested JSON; duplicate author titles; exact duplicate events; hierarchy disambiguation; 12-to-10 truncation; stable order; mixed/all-unrecognized/empty states; and absence of `已同步 0 章`.
- [ ] Use narrow fail-closed guards around hierarchy traversal and each entry inspection. A malformed container produces an empty index; an entry that throws increments only the unrecognized count. Never return or log an exception. Assert `Object.isFrozen` for the result, rows array, every row, and every nested public collection.
- [ ] Run `node --test frontend/tests/unit/actualProgressPresentation.test.mjs`; expect all tests green with no warnings.
- [ ] Commit only these two files with `git commit -m "feat: present planning progress for authors"`.

## Task 2: Render only the Planning display model

**Files:** Modify `ActualProgressPanel.vue`, `PlanningWorkspace.vue`, and `planningWorkspaceSfc.test.mjs`.

- [ ] Replace the old mounted-panel raw-diagnostic expectations with failing assertions for all approved states and author rows. Pass `planningContent` into the harness. Assert visible text, accessible names, and `id`, `title`, `data-*` attributes omit exact sentinels for revision, UUID, hash, path, subject, entity, target ID, and raw JSON.
- [ ] Add a failing workspace integration assertion that the three Planning tabs pass the current aggregate to the same read-only panel and that the panel has no controls, editable content, event handlers, or emits.
- [ ] Run `node --test frontend/tests/unit/planningWorkspaceSfc.test.mjs`; expect RED because raw Canon/Projection revisions, paths, and JSON still render.
- [ ] Add `planningContent` to the panel props and compute only the pure adapter result:

```js
const presentation = computed(() => presentActualProgress({
  items: props.items,
  status: props.status,
  planningContent: props.planningContent,
}))
```

- [ ] Delete `publicValue`, raw revision computeds, and the raw-derived key function. Render a semantic heading, fixed summary, an ordered list only for recognized rows, and separate omitted/unrecognized summaries. Use display ordinal keys only.
- [ ] Pass `:planning-content="planningContent"` beside the existing items/status props in `PlanningWorkspace.vue`.
- [ ] Keep the panel secondary using existing `--nc-*` tokens. Remove the obsolete mobile media rule; add no narrow-screen or 200%-zoom behavior.
- [ ] Run `node --test frontend/tests/unit/actualProgressPresentation.test.mjs frontend/tests/unit/planningWorkspaceSfc.test.mjs` and `npm --prefix frontend run build`; expect both focused suites and build green.
- [ ] Request independent code review of closed-origin validation, non-disclosure, hierarchy, bounded list, state precedence, read-only semantics, accessibility, and scope. Resolve every Blocking/Major finding and rerun the two commands.
- [ ] Commit Task 2 with `git commit -m "feat: replace planning diagnostics with author summary"`.

## Task 3: Localize Bible reasons, modes, and history status

**Files:** Create `bibleStatusPresentation.js` and its test; modify the Bible controller, view, history drawer, controller test, and view test listed above.

- [ ] Write failing pure tests for all supported reason codes, `bible_confirmed → null`, ordered visible-label deduplication, fixed unknown fallback, all five modes, both history statuses, and fixed unknown mode/status fallbacks that never echo input. Include `__proto__`, `constructor`, `toString`, null, arrays, and symbols as adversarial reason/mode/status values.
- [ ] Add failing controller/component tests proving confirmed plus duplicate contract reasons show one guidance sentence; the page renders `CREATION BIBLE · 已确认`; all other modes render approved labels; history uses `当前修订`/`历史修订`/`状态待核对`; and history detail filters confirmation, deduplicates labels, and never echoes unknown codes.
- [ ] Run `node --test frontend/tests/unit/bibleStatusPresentation.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs frontend/tests/unit/projectBibleView.test.mjs`; expect RED for the missing helper and current raw labels.
- [ ] Move the reason map into the new helper and implement omission and ordered deduplication:

```js
export const bibleReasonLabel = reason => {
  if (reason === 'bible_confirmed') return null
  return Object.hasOwn(REASON_LABELS, reason)
    ? REASON_LABELS[reason]
    : '创作圣经状态需要重新读取。'
}

export function presentBibleReasons(reasons) {
  const visible = []
  const seen = new Set()
  for (const reason of Array.isArray(reasons) ? reasons : []) {
    const label = bibleReasonLabel(reason)
    if (label && !seen.has(label)) { seen.add(label); visible.push(label) }
  }
  return Object.freeze(visible)
}
```

- [ ] Implement exact mode labels `first/draft/head/superseded/archived` and history labels `current/superseded` with own-property checks; unknown values including `__proto__` map to fixed `状态待核对`.
- [ ] Import/re-export `bibleReasonLabel` from the controller and compute `reasonLabels` with `presentBibleReasons`. Retain `activeStatus` in the controller contract if existing non-presentation tests need it, but remove it from view rendering.
- [ ] Compute the page eyebrow from `bibleModeLabel(mode.value)`. Remove `labelReason` prop plumbing. In the drawer, render mapped row statuses and a computed filtered detail-reason list; delete the raw-interpolating default.
- [ ] Run the three focused tests and `npm --prefix frontend run build`; expect green.
- [ ] Request independent review for omission in both contexts, deduplication, controller compatibility, closed mappings, fixed fallbacks, preserved permissions/history authority, accessibility, and scope. Resolve Blocking/Major findings and rerun verification.
- [ ] Commit Task 3 with `git commit -m "feat: translate bible status for authors"`.

## Task 4: Full regression and read-only product acceptance

**Files:** Create `docs/superpowers/acceptance/2026-08-29-author-facing-planning-status.md`.

- [ ] Run fresh gates:

```powershell
node --test frontend/tests/unit/actualProgressPresentation.test.mjs frontend/tests/unit/planningWorkspaceSfc.test.mjs frontend/tests/unit/bibleStatusPresentation.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs frontend/tests/unit/projectBibleView.test.mjs
npm --prefix frontend run test:unit
npm --prefix frontend run build
```

Record exact counts/timestamps; do not reuse earlier evidence.

- [ ] Run `git diff --check`, `git diff --cached --check`, `git diff --check origin/main...HEAD`, `git status --short`, and `git diff --name-only origin/main...HEAD`. Expect only approved docs/frontend files and untouched untracked `.review-worktrees/`.
- [ ] Preflight ports with `Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue`; abort if either has a listener. Start `D:\Projects\Novel_Creater\.venv-m2\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` and `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173` in two exact tool-owned terminal sessions, retaining both session IDs. Confirm each session remains alive after health/root succeeds; never accept health from a process outside those sessions.
- [ ] Treat lifecycle as `try/finally`: on success, assertion failure, timeout, or interruption, send Ctrl+C only to the two retained sessions, wait for both to exit, and repeat the port preflight until both ports are free. If a port remains, resolve its PID read-only and terminate it only after proving it is a descendant of the retained session; otherwise stop and report the unknown listener. Cleanup completes before any acceptance verdict.
- [ ] With the Playwright skill and headed Chromium, inspect project `474d110f-977c-4c82-bec4-464f30ec5a16` at 1440×900. Assert `visualViewport.scale === 1`; visit all three Planning tabs and Creation Bible through visible navigation.
- [ ] Install separate in-memory ledgers before navigation for console errors, page errors, failed responses, request failures, Provider routes, external origins, and methods. Assert all business requests are GET, with zero Provider and external-origin requests. Record only classifications/counts, never full content.
- [ ] From the loaded Planning response, keep only exact sentinels needed for non-disclosure (revision, one target ID/path, subject, hash, raw JSON token). Assert none appears in visible text, accessible names, or `id`, `title`, `data-*` attributes. Assert the author summary is present, at most 10 rows, and read-only.
- [ ] On Bible, assert the eyebrow uses mode label and confirmed-baseline message remains. Click `修订历史`, wait for its GET, inspect all visible history rows, open one `查看详情`, and assert current/history/detail reason and status presentation omit `bible_confirmed`, raw `current`/`superseded`, and any observed unknown code. Close with the existing control and verify focus restoration. Do not require basis hashes/IDs to disappear; that surface is outside scope.
- [ ] Capture headed screenshots after the Planning summary and opened Bible history detail reach their asserted states. Save them only under one explicitly created runner-owned acceptance directory. Record each as a temporary path plus `已审核后删除`, then remove the directory during lifecycle cleanup; screenshots are not committed in this slice.
- [ ] Do not visit Contract during acceptance and do not suppress any Planning/Bible error. The known Contract 404 remains an explicit non-claim.
- [ ] Write the acceptance record with viewport/zoom, exact routes, GET-only and error ledgers, Provider/external counts, sentinel categories (not values), temporary screenshot paths marked `已审核后删除`, unit/build results, reviewer verdicts, commit hashes, and non-claims.
- [ ] Stop owned services, verify ports are free, and delete only runner-owned artifacts; never delete `.playwright-cli/` wholesale.
- [ ] Request final independent review of full diff and evidence. Resolve Blocking/Major findings and repeat affected gates.
- [ ] Commit evidence with `git commit -m "docs: accept author-facing planning status"`.
- [ ] On the exact committed tree, run `git status --short`, `git log --oneline origin/main..HEAD`, `npm --prefix frontend run test:unit`, and `npm --prefix frontend run build`. Expect only `.review-worktrees/` untracked, visible slice commits, and green gates.
- [ ] Fetch and push only if safe: run `git fetch origin main`, `git merge-base --is-ancestor origin/main HEAD`, then `git push origin main`. If origin is not an ancestor, stop and reconcile; never force-push.

## Completion boundary

Claim only that Planning finalized-progress presentation and current/history Bible status labels are author-facing at the approved wide-screen target. Do not claim automatic transitions, fully productized Bible history, complete frontend overhaul, mobile/200%-zoom support, Contract 404 resolution, real Provider creation, or finished novel-content quality.
