# Phase 4B3 Selection Tools and One-Step Undo Implementation Plan

> **For implementation:** Use `executing-plans`, `test-driven-development`, and
> `verification-before-completion` task by task. Work inline in the current controller task;
> do not create or fork another large task. Checkboxes are the execution ledger.

**Goal:** Add exact-selection rewrite, polish, expand, compress, and one safe append-only undo
while reusing the accepted Phase 4B2 draft-operation chain and keeping the main editor unchanged
until the backend commits a terminal result.

**Architecture:** The existing operation route accepts four additional local operation types and
freezes scalar offsets plus the selected-text digest into its input manifest. Reservation validates
the exact authoritative selection before any provider side effect. Streaming remains replacement
preview only. Successful settlement reconstructs `prefix + replacement + suffix` under the existing
operation/session/draft fence; local cancel/failure never changes WorkingDraft. Undo is a separate
short CAS transaction that restores the original operation's `before` recovery snapshot into a new
revision. No table, column, scheduler, worker lifecycle, or provider endpoint is added.

**Tech stack:** Python 3.13, FastAPI/Pydantic, asyncio, aiomysql/MySQL 8, pytest,
Vue 3/Pinia, native fetch, Node test runner, Vite, Playwright with an injected loopback fake
provider.

---

## Fixed scope and stop rules

- Implement only `rewrite_selection`, `polish_selection`, `expand_selection`,
  `compress_selection`, and undo of the latest untouched successful local replacement.
- Do not add full-draft rewrite, candidate load/compare/fusion, Canon writes, finalization,
  download, backup/import, market scheduler work, new operation infrastructure, or new schema
  objects.
- Do not call a real provider, live website, or product database.
- Keep Phase 4B2 `generate_new` behavior and its 4/4 browser gate unchanged.
- Use focused RED/GREEN commands while editing. Run the slice matrix once after code stops
  changing. Full unit/integration/browser regression waits for Phase 4 close under
  `docs/testing/test-gate-policy.md`.
- If review finds an extreme but non-blocking issue outside this active path, record it for later;
  do not widen Phase 4B3 merely to reach an artificial zero-finding review.
- Logs and artifacts may contain exit/count/first cause/resource ledger only, never prose,
  selection text, replacement text, provider bodies, secrets, or DSNs.

## Public contracts fixed by this plan

Local create command:

```json
{
  "operationType": "rewrite_selection",
  "expectedWorkingDraftRevision": 7,
  "expectedContentHash": "<64 lowercase hex>",
  "startOffset": 12,
  "endOffset": 19,
  "selectedTextHash": "<64 lowercase hex>",
  "idempotencyKey": "<canonical lowercase UUID>",
  "authorInstruction": "optional, at most 1000 Unicode scalars"
}
```

For `generate_new`, the existing exact five-field command remains unchanged. Local terminal
operation projections add nullable `resultSelectionStart` and `resultSelectionEnd`; both are null
for `generate_new` and non-null only for a completed local operation. `resultSelectionEnd` is
derived from the committed replacement scalar length, not stored in a new column.

Undo route and command:

```text
POST /api/projects/{pid}/chapter-sessions/{session_id}/working-draft/undo
```

```json
{
  "expectedWorkingDraftRevision": 8,
  "expectedContentHash": "<64 lowercase hex>",
  "sourceOperationId": "<canonical lowercase UUID>"
}
```

The undo response is the existing closed ChapterSession workspace projection. A stale, duplicate,
manually edited, later-operation, cross-owner, or non-local request fails closed with the existing
fixed conflict/precondition error family.

## Task 1: Lock the schema vocabulary and governing authority

**Files:**

- Modify: `backend/schema/40_drafts.sql`
- Modify: `backend/schema_version.py`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Modify: `backend/tests/unit/test_schema_version.py`
- Modify: `backend/tests/unit/test_initialize_database.py`
- Modify: `backend/tests/integration/test_schema_bootstrap.py`
- Modify: `CURRENT_PROJECT_STATE.md`

- [ ] **Step 1: Write schema RED assertions**

Require schema version `writer-core-v1.10.0`, unchanged table count, and only these vocabulary
extensions:

```sql
CHECK (operation_type IN (
  'generate_new','rewrite_selection','polish_selection',
  'expand_selection','compress_selection'
))
CHECK (replacement_reason IN (
  'generate_new','rewrite_selection','polish_selection',
  'expand_selection','compress_selection','undo_local'
))
```

Also assert that no `selection_*` column, undo table, migration, trigger, or compatibility view was
added.

- [ ] **Step 2: Run schema RED**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q
```

Expected: failures only for the old v1.9.0/version hash and old closed CHECK vocabularies.

- [ ] **Step 3: Make the minimal schema change**

Broaden the two CHECK constraints and bump only the exact bootstrap schema version. Update
`CURRENT_PROJECT_STATE.md` to name Phase 4B3 as active, without claiming product DB readiness.

- [ ] **Step 4: Run focused GREEN**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add backend/schema/40_drafts.sql backend/schema_version.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/integration/test_schema_bootstrap.py CURRENT_PROJECT_STATE.md
git commit -m "schema: admit phase4b3 local draft operations"
```

## Task 2: Validate exact scalar selections before provider work

**Files:**

- Create: `backend/services/draft_selection.py`
- Create: `backend/tests/unit/test_draft_selection.py`
- Modify: `backend/services/draft_operations.py`
- Modify: `backend/prompts/chapter_draft.py`
- Modify: `backend/tests/unit/test_draft_operation_service.py`
- Modify: `backend/tests/unit/test_chapter_draft_prompt.py`

- [ ] **Step 1: Write pure-helper RED tests**

Cover:

- non-empty Unicode-scalar slicing with supplementary characters;
- negative, reversed, empty, and out-of-bounds ranges;
- lowercase SHA-256 of exact UTF-8 selected text;
- no more than 300 scalars of left/right context;
- exact reconstruction and returned inserted range;
- operation intent labels for all four closed local types.

The helper returns values, never logs text, and has no database/provider dependency.

- [ ] **Step 2: Run helper RED**

```powershell
python -m pytest backend/tests/unit/test_draft_selection.py -q
```

Expected: import failure because the helper does not exist.

- [ ] **Step 3: Implement the smallest pure helper**

Expose a closed `LOCAL_DRAFT_OPERATION_TYPES`, `validate_selection(...)`,
`selection_context(...)`, and `replace_selection(...)`. Python string indices are the scalar
authority after strict UTF-8 encoding succeeds.

- [ ] **Step 4: Write service/prompt RED tests**

Extend `StartDraftOperation` with nullable local fields. Test that reservation:

1. locks and validates the authoritative WorkingDraft revision/hash;
2. validates offsets and selected digest before reading provider authority or launching work;
3. freezes only offsets, digest, operation type, bounded context digests/metadata, and existing
   minimum Outline authority in the safe manifest;
4. passes selected text, closed intent, optional instruction, bounded adjacent context, and the
   existing minimum confirmed Outline summary to the prompt builder;
5. does not send the complete WorkingDraft for local operations;
6. trims/counts local author instructions at 1000 scalars while preserving the existing 2000
   scalar `generate_new` limit;
7. gives idempotent replay the same fingerprint and rejects changed range/digest under the same
   key.

- [ ] **Step 5: Run service/prompt RED**

```powershell
python -m pytest backend/tests/unit/test_draft_selection.py backend/tests/unit/test_chapter_draft_prompt.py backend/tests/unit/test_draft_operation_service.py -q
```

Expected: only new local-operation cases fail.

- [ ] **Step 6: Generalize reservation without a second operation path**

Keep one `start -> reserve -> worker` chain. Use `command.operation_type` in the attempt,
fingerprint, recovery reason, prompt, and source payload. Put validated selection authority in the
worker context for later settlement, but never expose prose through public DTOs/errors.

- [ ] **Step 7: Run focused GREEN and compile**

```powershell
python -m pytest backend/tests/unit/test_draft_selection.py backend/tests/unit/test_chapter_draft_prompt.py backend/tests/unit/test_draft_operation_service.py -q
python -m py_compile backend/services/draft_selection.py backend/services/draft_operations.py backend/prompts/chapter_draft.py
```

- [ ] **Step 8: Commit**

```powershell
git add backend/services/draft_selection.py backend/services/draft_operations.py backend/prompts/chapter_draft.py backend/tests/unit/test_draft_selection.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_draft_prompt.py
git commit -m "feat: reserve exact selection draft operations"
```

## Task 3: Settle local replacements atomically and preserve originals on every non-success

**Files:**

- Modify: `backend/services/draft_operations.py`
- Modify: `backend/repositories/chapter_sessions.py`
- Modify: `backend/tests/unit/test_draft_operation_service.py`
- Modify: `backend/tests/unit/test_chapter_session_repository.py`
- Modify: `backend/tests/integration/test_draft_operation_integrity.py`
- Modify: `backend/tests/integration/test_draft_operation_streaming_integrity.py`

- [ ] **Step 1: Write local-settlement RED tests**

Require:

- completion re-locks session/draft/operation and revalidates base authority, exact range, and
  selected digest;
- only the selected range changes and WorkingDraft advances exactly one revision;
- before/after recovery rows store full snapshots with the local replacement reason and original
  operation ID;
- source payload records local operation ID/type and base revision;
- terminal result exposes derived inserted scalar range;
- local cancellation with empty or non-empty partial, provider failure, invalid/empty replacement,
  expiry, fence loss, and draft drift leave WorkingDraft and recovery history unchanged;
- the accepted `generate_new` completion and partial-cancel behavior remains unchanged.

- [ ] **Step 2: Run settlement RED**

```powershell
python -m pytest backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_session_repository.py -q
```

Expected: only new local completion/cancel assertions fail.

- [ ] **Step 3: Implement a small operation-type branch inside existing settlement**

For local success, validate replacement text without stripping meaningful leading/trailing prose,
reject empty output after validation, call `replace_selection`, hash the reconstructed full draft,
and persist through the same snapshots/CAS/event/attempt transaction. Keep `generate_new` on its
accepted path. In cancellation settlement, explicitly skip all WorkingDraft/recovery writes for
local types even when a durable partial exists.

Do not change the registry, event cadence, lease, heartbeat, pool, gateway, or task ownership.

- [ ] **Step 4: Run unit GREEN**

```powershell
python -m pytest backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_session_repository.py -q
python -m py_compile backend/services/draft_operations.py backend/repositories/chapter_sessions.py
```

- [ ] **Step 5: Add and run the narrow disposable-MySQL evidence**

Add one success transaction, one cancel-with-partial preservation case, and one stale-settlement
case to the existing operation integrity files.

```powershell
python -m pytest backend/tests/integration/test_draft_operation_integrity.py backend/tests/integration/test_draft_operation_streaming_integrity.py -q
```

Expected: PASS against runner-owned `novel_creator_test_*` databases only.

- [ ] **Step 6: Commit**

```powershell
git add backend/services/draft_operations.py backend/repositories/chapter_sessions.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_session_repository.py backend/tests/integration/test_draft_operation_integrity.py backend/tests/integration/test_draft_operation_streaming_integrity.py
git commit -m "feat: apply fenced local draft replacements"
```

## Task 4: Expose strict local-operation and undo HTTP contracts

**Files:**

- Modify: `backend/routers/chapter_sessions.py`
- Modify: `backend/services/draft_operations.py`
- Modify: `backend/repositories/chapter_sessions.py`
- Modify: `backend/tests/api/test_draft_operation_routes.py`
- Modify: `backend/tests/api/test_chapter_session_routes.py`
- Modify: `backend/tests/unit/test_draft_operation_service.py`
- Modify: `backend/tests/unit/test_chapter_session_repository.py`
- Modify: `backend/tests/integration/test_draft_operation_integrity.py`

- [ ] **Step 1: Write route and undo RED tests**

Test strict per-operation request fields, scalar bounds, selected digest, 1000-scalar local
instruction limit, duplicate JSON member/body/content-type handling, cross-owner hiding, fixed
errors, and nullable terminal selection fields.

For undo, require the exact three-field body and verify:

- current source payload names the same completed local operation;
- current revision/hash equals the operation result;
- the matching `before` recovery snapshot is owner-scoped and exact;
- one new `undo_local` revision is appended and WorkingDraft advances exactly once;
- duplicate/stale/manual/later/generate-new/cross-owner requests do not mutate rows;
- no provider, registry, event, or synthetic operation is created.

- [ ] **Step 2: Run HTTP/undo RED**

```powershell
python -m pytest backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_chapter_session_routes.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_session_repository.py -q
```

- [ ] **Step 3: Implement the closed DTOs and short undo transaction**

Add nullable local fields to `CreateDraftOperationBody` with validation based on operation type.
Add `UndoLocalDraftBody` and `DraftOperationService.undo_local(...)`. Add one repository query for
the owner-scoped completed source attempt plus its exact `before` recovery snapshot; reuse existing
session/draft locks, revision insert, and WorkingDraft CAS.

Return the normal authoritative workspace via the existing ChapterSession service/projection after
the undo transaction. Do not return recovery prose or operation manifest data.

- [ ] **Step 4: Run focused GREEN and integration proof**

```powershell
python -m pytest backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_chapter_session_routes.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_session_repository.py -q
python -m pytest backend/tests/integration/test_draft_operation_integrity.py -q
python -m py_compile backend/routers/chapter_sessions.py backend/services/draft_operations.py backend/repositories/chapter_sessions.py
```

- [ ] **Step 5: Commit**

```powershell
git add backend/routers/chapter_sessions.py backend/services/draft_operations.py backend/repositories/chapter_sessions.py backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_chapter_session_routes.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_session_repository.py backend/tests/integration/test_draft_operation_integrity.py
git commit -m "feat: add append-only local draft undo"
```

## Task 5: Extend the frontend transport boundary without leaking prose authority

**Files:**

- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/chapterSessionStore.js`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Modify: `frontend/tests/unit/chapterSessionStore.test.mjs`

- [ ] **Step 1: Write transport/store RED tests**

Require exact generate-vs-local request shapes, four closed local types, scalar integer/range checks,
selected digest, 1000-scalar instruction limit, strict nullable terminal range correlations, and the
exact undo path/body. Reject sensitive/extra/deep/cyclic keys before fetch. Verify undo accepts only
the normal closed workspace response and updates the store only in its current route generation.

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs
```

- [ ] **Step 3: Implement the narrow client/store methods**

Generalize the current draft command validator by operation type; do not add another HTTP client or
state store. Add `chapterSessions.undoLocalDraft(...)` and the corresponding guarded store method.

- [ ] **Step 4: Run GREEN**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs
```

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/api/db/client.js frontend/src/stores/chapterSessionStore.js frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs
git commit -m "feat: expose local draft operation transport"
```

## Task 6: Reuse the coordinator and controller for local preview, terminal adoption, and undo

**Files:**

- Modify: `frontend/src/application/writer/draftOperationTimeline.js`
- Modify: `frontend/src/application/writer/draftOperationCoordinator.js`
- Modify: `frontend/src/application/writer/chapterWriterController.js`
- Modify: `frontend/tests/unit/draftOperationTimeline.test.mjs`
- Modify: `frontend/tests/unit/draftOperationCoordinator.test.mjs`
- Modify: `frontend/tests/unit/chapterWriterController.test.mjs`

- [ ] **Step 1: Write coordinator/controller RED tests**

Cover:

- one frozen local command per click with exact scalar range/digest;
- selection must still match flushed visible text before start;
- local deltas populate a separate replacement preview and never `editorText`/autosave;
- cancellation/failure preserves editor text even with a non-empty partial;
- completion reloads one authoritative workspace and accepts only matching operation/revision/hash;
- controller restores the inserted range using terminal derived offsets;
- same-key reconnect never triggers a second provider POST;
- undo is visible only for the latest current local result and calls the exact source operation;
- manual edit, later local/generate/candidate action, reset, dispose, or stale workspace removes undo;
- unknown undo result reloads once to reconcile authority, without inventing an idempotency retry.

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/draftOperationTimeline.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs frontend/tests/unit/chapterWriterController.test.mjs
```

- [ ] **Step 3: Generalize existing state instead of adding a coordinator**

Let the coordinator freeze either the existing generate command or a local command. Preserve its
cursor/seal/reconnect/cancel fences. Expose preview kind/type and terminal selection range. In the
controller, use the existing captured selection, compute its digest with the existing SHA-256 text
utility, flush first, validate the selection against the still-current text, then dispatch. Keep the
main editor bound to autosave text for local operations; only full generation retains its accepted
editor-wide streaming preview.

Represent undo eligibility as ephemeral controller state derived from the accepted terminal result
and current persisted authority. Do not persist a frontend undo stack.

- [ ] **Step 4: Run GREEN**

```powershell
node --test frontend/tests/unit/draftOperationTimeline.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs frontend/tests/unit/chapterWriterController.test.mjs
```

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/application/writer/draftOperationTimeline.js frontend/src/application/writer/draftOperationCoordinator.js frontend/src/application/writer/chapterWriterController.js frontend/tests/unit/draftOperationTimeline.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs frontend/tests/unit/chapterWriterController.test.mjs
git commit -m "feat: coordinate local selection replacements"
```

## Task 7: Add the compact selection toolbar and replacement preview

**Files:**

- Modify: `frontend/src/components/writer/PlainTextDraftEditor.vue`
- Modify: `frontend/src/views/ChapterWriterView.vue`
- Modify: `frontend/tests/unit/plainTextDraftEditor.test.mjs`
- Modify: `frontend/tests/unit/chapterWriterView.test.mjs`
- Modify: `frontend/tests/unit/plainTextRange.test.mjs`

- [ ] **Step 1: Write UI RED tests**

Require four buttons only for a non-empty valid selection, disabled/busy/cancel behavior, a
separate labelled replacement preview, terminal inserted-range restoration through the native
textarea, and one `撤销本次 AI 修改` action only while eligible. Verify no modal, history drawer,
candidate controls, direct fetch, `page.evaluate`, or alternative editor path is added.

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/plainTextRange.test.mjs frontend/tests/unit/plainTextDraftEditor.test.mjs frontend/tests/unit/chapterWriterView.test.mjs
```

- [ ] **Step 3: Implement the compact UI**

Keep `PlainTextDraftEditor` as the only textarea. Add a narrowly scoped selection-restore prop or
method based on its existing UTF-16/scalar mapping, without mutating text. In the view, render the
four-action toolbar, the replacement preview block, existing stop action, and ephemeral undo button.
Use the existing instruction input; show its applicable 1000 limit while a local action is selected.

- [ ] **Step 4: Run GREEN and build**

```powershell
node --test frontend/tests/unit/plainTextRange.test.mjs frontend/tests/unit/plainTextDraftEditor.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/chapterWriterController.test.mjs
npm run build
```

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/writer/PlainTextDraftEditor.vue frontend/src/views/ChapterWriterView.vue frontend/tests/unit/plainTextRange.test.mjs frontend/tests/unit/plainTextDraftEditor.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/chapterWriterController.test.mjs
git commit -m "feat: add compact selection writing tools"
```

## Task 8: Add one narrow fake-provider browser scenario

**Files:**

- Create: `frontend/e2e/phase4b3-selection-tools.spec.ts`
- Create: `frontend/e2e/playwright.phase4b3.config.ts`
- Create: `frontend/e2e/run-phase4b3.mjs`
- Create: `backend/scripts/prepare_phase4b3_browser_db.py`
- Create: `scripts/tests/phase4B3BrowserContract.test.mjs`
- Modify: `scripts/run-tests.mjs`
- Modify: `package.json`
- Modify: `frontend/package.json`

- [ ] **Step 1: Write runner-contract RED**

Require one formal spec with one serial browser test. Reuse the existing `product-runner.mjs`
primitives and Phase4B2 safety invariants: runner-owned disposable DB/temp/artifact roots, loopback
fake provider only, no proxy, UI-only interaction, no direct API/fetch/axios/route interception,
sanitized diagnostics, and residue cleanup. Do not copy the Phase4B2 four-scenario matrix.

```powershell
node --test scripts/tests/phase4B3BrowserContract.test.mjs
```

Expected: FAIL because the Phase4B3 formal inventory is absent.

- [ ] **Step 2: Implement the thin runner and one scenario**

The scenario uses the visible UI to exercise 改写, 润色, 扩写, 压缩 sequentially against small
selections, verifies local preview never changes the editor before completion, cancels one streamed
action and verifies unchanged prose, completes the final action, then clicks undo and verifies the
prior authoritative prose. The fake provider returns markers/digests in its private ledger; neither
test output nor artifacts print prose bodies.

- [ ] **Step 3: Run runner-contract GREEN**

```powershell
node --test scripts/tests/phase4B3BrowserContract.test.mjs scripts/tests/browser-runner.test.mjs scripts/tests/phase3BrowserSupport.test.mjs
```

- [ ] **Step 4: Run the single browser slice gate**

```powershell
npm run test:browser:phase4b3
```

Expected: `1 passed`, fake provider only, owned residue zero.

- [ ] **Step 5: Commit**

```powershell
git add frontend/e2e/phase4b3-selection-tools.spec.ts frontend/e2e/playwright.phase4b3.config.ts frontend/e2e/run-phase4b3.mjs backend/scripts/prepare_phase4b3_browser_db.py scripts/tests/phase4B3BrowserContract.test.mjs scripts/run-tests.mjs package.json frontend/package.json
git commit -m "test: add phase4b3 selection browser gate"
```

## Task 9: Fresh slice verification, review, and acceptance record

**Files:**

- Create: `docs/acceptance/2026-08-09-phase-4b3-selection-tools-undo.md`
- Modify: `CURRENT_PROJECT_STATE.md`
- Modify: `PRODUCT_DEVELOPMENT_PLAN.md`
- Modify: `DEVELOPMENT_LOG.md`

- [ ] **Step 1: Inspect scope before running gates**

```powershell
git status --short --branch
git diff --stat HEAD~8..HEAD
git diff --check
```

Confirm no new table/column, provider call, product DB access, scheduler behavior, or out-of-scope
feature. Audit owned Python/Node/pytest/process/port/temp/Vite cache resources and clean only exact
runner-owned residue.

- [ ] **Step 2: Run one fresh focused Python/API set**

```powershell
python -m pytest backend/tests/unit/test_draft_selection.py backend/tests/unit/test_chapter_draft_prompt.py backend/tests/unit/test_draft_operation_service.py backend/tests/unit/test_chapter_session_repository.py backend/tests/api/test_draft_operation_routes.py backend/tests/api/test_chapter_session_routes.py -q
python -m py_compile backend/services/draft_selection.py backend/services/draft_operations.py backend/prompts/chapter_draft.py backend/repositories/chapter_sessions.py backend/routers/chapter_sessions.py
```

- [ ] **Step 3: Run one fresh frontend/root Node set and build**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/draftOperationTimeline.test.mjs frontend/tests/unit/draftOperationCoordinator.test.mjs frontend/tests/unit/chapterWriterController.test.mjs frontend/tests/unit/plainTextRange.test.mjs frontend/tests/unit/plainTextDraftEditor.test.mjs frontend/tests/unit/chapterWriterView.test.mjs scripts/tests/phase4B3BrowserContract.test.mjs
npm run build
```

- [ ] **Step 4: Run one fresh narrow MySQL and browser set serially**

```powershell
python -m pytest backend/tests/integration/test_schema_bootstrap.py backend/tests/integration/test_draft_operation_integrity.py backend/tests/integration/test_draft_operation_streaming_integrity.py -q
npm run test:browser:phase4b3
```

Record only exit, pass count, first cause if any, and exact owned-resource ledger.

- [ ] **Step 5: Perform one serial specification review, then one quality review**

Review against
`docs/superpowers/specs/2026-08-09-lean-product-scope-and-phase4b3-selection-tools-design.md`.
Fix only Critical or active-path data-loss/security/deterministic failures. If code changes, rerun only
the affected focused/slice evidence. Do not start a second discovery expansion.

- [ ] **Step 6: Write the acceptance record**

State exactly what is accepted with the injected fake provider and keep these unaccepted:

```text
Full-draft rewrite, candidate load/compare/fusion, finalization, Canon projection,
download/export, real-provider quality, and product-database readiness remain unaccepted.
```

Also state that full Phase/release regression has not run at this slice boundary and is intentionally
deferred to Phase 4 close under the current lean gate policy.

- [ ] **Step 7: Final consistency checks and commit**

```powershell
git diff --check
git status --short --branch
git add docs/acceptance/2026-08-09-phase-4b3-selection-tools-undo.md CURRENT_PROJECT_STATE.md PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md
git commit -m "docs: accept phase4b3 selection tools and undo"
git status --short --branch
```

Do not push. Do not claim full Phase 4 completion. The next product slice after this acceptance is
Phase 4C candidate load and two-candidate read-only comparison; fusion remains deferred.
