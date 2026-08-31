# P0-D Creative Foundation Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing project Seed, Contract, and Bible routes into complete author-facing document workspaces that show the full substance first, preserve each module's current authority and lifecycle, preview every AI result before adoption, and become permanently read-only after first confirmation.

**Architecture:** Add five presentation-only Vue primitives for the shared three-column document shell, while keeping Seed, Contract, and Bible stores, commands, CAS versions, capabilities, and confirmation adapters separate. Seed continues to use the current thirteen-field `SeedPayload` and selected-seed authority. Contract replaces the five-page wizard presentation with one browsable document, but every write still follows the server's `engine -> style -> assets` `draftStage` contract and the existing preview/confirm commands. Bible continues to save one complete strict `BiblePayload`; its only new backend behavior is an audited proposal command that reuses the current Provider, prompt, parser, and generation-attempt table, returns a complete validated proposal, and never writes the active draft. Confirmed baselines expose no author write controls and do not gain clone, re-sign, or next-step shortcuts.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, existing async MySQL repository and generation-attempt storage, Vue 3, Pinia, Vue Router, Naive UI, Node test runner, pytest, Vite, Playwright.

---

## Product and authority boundary

Implement only the approved P0-D flow:

```text
project Seed candidates
-> inspect all 13 fields
-> save candidate revision
-> preview and confirm one project Seed
-> permanent read-only Seed

confirmed Seed
-> browse the whole Contract document
-> save through engine/style/assets stage constraints
-> server preview
-> confirm once
-> permanent read-only Contract

confirmed Contract
-> edit one Bible section in one local complete work copy
-> save complete BiblePayload
-> request whole/section proposal without draft mutation
-> explicitly adopt into the local work copy
-> save complete BiblePayload
-> confirm once
-> permanent read-only Bible
```

The following authority chain must remain unchanged:

```text
Confirmed Seed -> Confirmed Contract -> Confirmed Bible -> Planning -> Canon / Projection
```

The P0-D design is `docs/superpowers/specs/2026-08-31-p0-d-creative-foundation-authoring-design.md`. The approved layout reference is `tmp/p0-d-foundation-layout-options.html`; it is not production code.

### Stable content contracts

Seed renders exactly these current fields and no page-owned additions:

```js
[
  'title', 'genre', 'logline', 'protagonist', 'desire',
  'coreConflict', 'worldPressure', 'openingHook', 'differentiation',
  'targetAudience', 'storyPromise', 'longFormPotential', 'marketBasis',
]
```

Old nine-field Seed revisions display the four absent optional fields as `该历史版本未记录`; they are never rewritten.

Contract preserves the existing server stages:

```text
engine -> style -> assets -> preview/confirm
```

The author document sections are presentation groupings, not a new persistence schema:

```text
故事发动机 / 长篇容量 / 正式资产范围 / 风格方案 / 禁止方向 / 完整预览
```

Bible continues to persist the current strict whole payload. Stable proposal scopes map to those fields:

```python
{
    "whole": None,
    "premise": ("premiseAndPromise",),
    "world_rules": ("worldRules",),
    "progression": ("powerOrProgressionSystem",),
    "core_characters": ("protagonist", "coreCast"),
    "factions": ("factions",),
    "long_term_conflicts": ("longTermConflicts",),
    "relationships": ("relationshipDynamics",),
    "tone_boundaries": ("toneAndNarrativeBoundaries",),
    "continuity_guardrails": ("continuityGuardrails",),
    "open_questions": ("openDesignQuestions",),
}
```

The Provider still returns one complete `BiblePayload`. For a section proposal the frontend adopts only the mapped target field or fields; all other local work-copy fields remain untouched.

### Stable Bible proposal API

Add one command and reuse the existing attempt read:

```http
POST /api/projects/{pid}/bible/proposals
GET  /api/projects/{pid}/bible/generation-attempts/{attemptId}
```

Request:

```json
{
  "scope": "whole",
  "authorInstructions": "突出基层秩序与人物代价",
  "expectedDraftVersion": 0,
  "expectedHeadRevision": 0,
  "idempotencyKey": "bible-proposal-..."
}
```

Successful attempt response adds a complete validated proposal:

```json
{
  "attempt": {
    "id": "...",
    "status": "succeeded",
    "resultHash": "...",
    "proposal": { "premiseAndPromise": "..." }
  }
}
```

`proposal` is `null` for non-succeeded attempts. The idempotency request hash and input manifest must include the operation (`proposal`) and scope so an old direct-generate key cannot replay as a proposal. A section proposal requires an existing saved active draft at the supplied `expectedDraftVersion`. Proposal completion re-locks and revalidates the same project, head, draft, binding, and manifest as the existing generation path, then updates only `bible_generation_attempts.result_json/result_hash/status`; it must not insert, deactivate, or CAS-update `bible_drafts`.

The existing `POST /bible/generate` route may remain for compatibility, but the formal author page must not call or label it as preview.

### Explicit non-goals

- no schema migration, proposal table, partial-Bible table, second Seed/Contract/Bible authority, or duplicated formal正文;
- no generic schema form builder, generic AI rewrite endpoint, shared domain Store, shared confirm command, or shared version state machine;
- no change to Writer Core, Provider binding semantics, Planning, Canon, Projection, chapter finalization, current-state memory, character arc progress, clues, or story progress;
- no confirmed-baseline clone, re-edit, regenerate, re-sign, or automatic next-step navigation;
- no real Provider call, article generation, Stage A/B, production database mutation, or legacy database deletion in implementation verification.

## File map

**Create:**

- `frontend/src/components/foundation/FoundationWorkspace.vue`
- `frontend/src/components/foundation/FoundationSectionIndex.vue`
- `frontend/src/components/foundation/FoundationStatusRail.vue`
- `frontend/src/components/foundation/FoundationDocumentSection.vue`
- `frontend/src/components/foundation/FoundationConfirmationDialog.vue`
- `frontend/src/components/seeds/SeedDocument.vue`
- `frontend/src/components/seeds/SeedOtherCandidatesDrawer.vue`
- `frontend/src/application/contracts/contractDocumentSections.js`
- `frontend/src/components/bible/BibleProposalReview.vue`
- `frontend/src/application/bible/bibleProposalScopes.js`
- `frontend/tests/unit/foundationWorkspace.test.mjs`
- `frontend/tests/unit/seedDocument.test.mjs`
- `frontend/tests/unit/contractDocumentSections.test.mjs`
- `frontend/tests/unit/bibleProposalScopes.test.mjs`
- `frontend/tests/unit/bibleProposalReview.test.mjs`
- `frontend/e2e/p0-d-creative-foundation.spec.ts`
- `frontend/e2e/run-p0-d.mjs`

**Modify:**

- `backend/prompts/bible.py`
- `backend/services/bible_generation.py`
- `backend/domain/routers/bibles.py`
- `backend/tests/unit/test_bible_prompt.py`
- `backend/tests/unit/test_bible_generation_service.py`
- `backend/tests/api/test_bible_routes.py`
- `backend/tests/api/test_route_inventory.py`
- `frontend/src/api/db/client.js`
- `frontend/src/views/ProjectSeedsView.vue`
- `frontend/src/components/seeds/SeedCard.vue`
- `frontend/src/components/seeds/SeedEditor.vue`
- `frontend/src/stores/seedStore.js`
- `frontend/src/views/ProjectContractView.vue`
- `frontend/src/components/project/CreationContractWizard.vue`
- `frontend/src/components/project/contract/StoryEngineStep.vue`
- `frontend/src/components/project/contract/StyleSelectionStep.vue`
- `frontend/src/components/project/contract/StyleTrialPanel.vue`
- `frontend/src/components/project/contract/AssetScopeStep.vue`
- `frontend/src/components/project/contract/CapacityStep.vue`
- `frontend/src/components/project/contract/ContractPreviewStep.vue`
- `frontend/src/components/project/contract/ContractDecisionSummary.vue`
- `frontend/src/domain/creation-contract/wizard-state.js`
- `frontend/src/stores/creationContractStore.js`
- `frontend/src/views/ProjectBibleView.vue`
- `frontend/src/components/bible/BibleEditor.vue`
- `frontend/src/components/bible/BibleHistoryDrawer.vue`
- `frontend/src/application/bible/bibleWorkspaceController.js`
- `frontend/src/application/bible/bibleStatusPresentation.js`
- `frontend/src/stores/bibleStore.js`
- `frontend/tests/unit/projectSeedsView.test.mjs`
- `frontend/tests/unit/seedStore.test.mjs`
- `frontend/tests/unit/projectContractView.test.mjs`
- `frontend/tests/unit/projectBibleView.test.mjs`
- `frontend/tests/unit/bibleWorkspaceController.test.mjs`
- `frontend/tests/unit/bibleStore.test.mjs`
- `frontend/tests/unit/bibleStatusPresentation.test.mjs`
- `frontend/tests/unit/bibleModalFocus.test.mjs`
- `frontend/package.json`
- `package.json`
- `scripts/run-tests.mjs`

Do not modify schema files, Canon/Projection/Planning services, writer-core inputs, or confirmed-baseline persistence rules.

---

### Task 1: Establish the protected baseline and characterization tests

**Files:**
- Test: `frontend/tests/unit/projectSeedsView.test.mjs`
- Test: `frontend/tests/unit/projectContractView.test.mjs`
- Test: `frontend/tests/unit/projectBibleView.test.mjs`
- Test: `backend/tests/unit/test_bible_generation_service.py`
- Test: `backend/tests/api/test_bible_routes.py`

- [ ] **Step 1: Create an isolated implementation branch/worktree**

Use `superpowers:using-git-worktrees`. Start from the commit containing this plan and the approved P0-D design. Preserve the existing untracked `.review-worktrees/` and `tmp/brainstorm-*` files; do not copy them into the worktree or delete them.

Expected branch name:

```text
codex/p0-d-creative-foundation
```

- [ ] **Step 2: Run the narrow existing baseline**

Run:

```powershell
node --test frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/seedStore.test.mjs
node --test frontend/tests/unit/projectContractView.test.mjs
node --test frontend/tests/unit/projectBibleView.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/bibleStatusPresentation.test.mjs frontend/tests/unit/bibleModalFocus.test.mjs
python -m pytest backend/tests/unit/test_bible_prompt.py backend/tests/unit/test_bible_generation_service.py backend/tests/api/test_bible_routes.py -q
```

Expected: all current tests pass before behavior changes. Record exact counts in the task notes.

- [ ] **Step 3: Add authority characterization assertions**

Add tests that pin these boundaries before refactoring:

```text
Seed confirmed payload is read-only and has no select-again/update/delete controls.
Contract confirmed head is read-only and cannot expose a new-draft/clone route.
Bible confirmed head is read-only and cannot expose generate/proposal/save/clone controls.
Existing direct Bible generate still writes a draft for compatibility.
```

These assertions characterize behavior that already exists and must pass. Add the new proposal red test only in Task 6, immediately before its implementation.

- [ ] **Step 4: Commit the characterization boundary**

```powershell
git add frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/projectBibleView.test.mjs backend/tests/unit/test_bible_generation_service.py backend/tests/api/test_bible_routes.py
git commit -m "test: protect P0-D foundation authority boundaries"
```

Expected: the branch remains green after the characterization commit.

---

### Task 2: Build the shared presentation-only document shell

**Files:**
- Create: `frontend/src/components/foundation/FoundationWorkspace.vue`
- Create: `frontend/src/components/foundation/FoundationSectionIndex.vue`
- Create: `frontend/src/components/foundation/FoundationStatusRail.vue`
- Create: `frontend/src/components/foundation/FoundationDocumentSection.vue`
- Create: `frontend/src/components/foundation/FoundationConfirmationDialog.vue`
- Create: `frontend/tests/unit/foundationWorkspace.test.mjs`

- [ ] **Step 1: Write the failing shell contract test**

Test compiled/SSR output and keyboard behavior for:

```text
one Chinese page title and purpose
left section navigation with current / 已填写 / 建议补充 / 阻塞 labels
middle document slot as the dominant region
right status/actions slot
directory click emits a stable section key and focuses the target heading
confirmation dialog traps focus and restores it to its trigger
confirmed/read-only mode omits the write-actions slot instead of disabling it
```

Also inspect the component CSS text for:

```css
grid-template-columns
min-width: 0
overflow-wrap: anywhere
@media (max-width: 760px)
@media (prefers-reduced-motion: reduce)
```

Run:

```powershell
node --test frontend/tests/unit/foundationWorkspace.test.mjs
```

Expected: FAIL because the components do not exist.

- [ ] **Step 2: Implement five small slot-based components**

`FoundationWorkspace.vue` owns layout only. It accepts display props such as `title`, `purpose`, `statusLabel`, and `readOnly`; all module data and commands enter through named slots.

`FoundationSectionIndex.vue` accepts already-derived items:

```js
{
  key: 'world_rules',
  label: '世界规则',
  status: 'filled',       // filled | suggested | blocked
  statusLabel: '已填写',
  targetId: 'bible-world-rules',
}
```

It must not infer service capability from payload content.

`FoundationStatusRail.vue` renders summary/status/source/action slots. `FoundationDocumentSection.vue` provides a heading anchor and read/edit slots. `FoundationConfirmationDialog.vue` provides only modal visuals/focus mechanics and snapshot/source/action slots; it never imports a Store or calls a confirm API.

- [ ] **Step 3: Make the shell responsive without a second mobile component**

Desktop uses three columns. Medium widths narrow the side rails. At `760px` or below use one natural vertical flow: section index, document, status/actions. Ensure page scrolling remains on the document and no component applies a permanent body lock.

- [ ] **Step 4: Run and commit**

```powershell
node --test frontend/tests/unit/foundationWorkspace.test.mjs
git add frontend/src/components/foundation frontend/tests/unit/foundationWorkspace.test.mjs
git commit -m "feat: add creative foundation document shell"
```

Expected: PASS.

---

### Task 3: Convert project Seed into a complete candidate document workspace

**Files:**
- Create: `frontend/src/components/seeds/SeedDocument.vue`
- Create: `frontend/src/components/seeds/SeedOtherCandidatesDrawer.vue`
- Create: `frontend/tests/unit/seedDocument.test.mjs`
- Modify: `frontend/src/views/ProjectSeedsView.vue`
- Modify: `frontend/src/components/seeds/SeedCard.vue`
- Modify: `frontend/src/components/seeds/SeedEditor.vue`
- Modify: `frontend/src/stores/seedStore.js`
- Modify: `frontend/tests/unit/projectSeedsView.test.mjs`
- Modify: `frontend/tests/unit/seedStore.test.mjs`

- [ ] **Step 1: Write failing Seed author-experience tests**

Cover:

```text
candidate list first when no Seed is selected
candidate detail shows all 13 fields in the approved order
one section at a time enters inline edit
save produces an existing Seed revision, not a new authority
server selection capability/reasons decide whether confirmation is enabled
confirmation CTA text is exactly 确认项目种子
confirmation succeeds and stays on /projects/:id/seeds
confirmed Seed is the only main document and exposes no write control
unselected candidates move to 其他候选（只读）
old 9-field revisions show 该历史版本未记录 for the four absent fields
provenance stays in 来源与诊断, never in SeedPayload
```

Run:

```powershell
node --test frontend/tests/unit/seedDocument.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/seedStore.test.mjs
```

Expected: FAIL on the missing document/drawer behavior.

- [ ] **Step 2: Implement the Seed document and section index**

Group the thirteen fields for navigation without changing the payload:

```js
[
  { key: 'positioning', label: '作品定位', fields: ['title', 'genre', 'targetAudience'] },
  { key: 'core', label: '故事核心', fields: ['logline', 'protagonist', 'desire', 'coreConflict'] },
  { key: 'pressure', label: '开篇与压力', fields: ['worldPressure', 'openingHook'] },
  { key: 'promise', label: '差异与承诺', fields: ['differentiation', 'storyPromise', 'longFormPotential', 'marketBasis'] },
]
```

`SeedDocument.vue` renders existing values as readable text and delegates edits to `SeedEditor.vue`. “完成本区编辑” updates a candidate work copy; “保存种子” continues to call the current candidate create/update revision command.

- [ ] **Step 3: Implement the confirmed/other-candidates split**

When the Store reports a selected Seed:

- render that selected revision in the main read-only document;
- hide create/edit/archive/restore/delete/select controls;
- render every non-selected candidate in `SeedOtherCandidatesDrawer.vue` as read-only trace material;
- use “版本历史” only for revisions of the same candidate;
- keep selection success on the same route.

- [ ] **Step 4: Verify conflict and archived behavior**

Keep the current selection revision and Seed revision CAS checks. A conflict preserves the local candidate form and offers an explicit authoritative reload. An archived project renders the selected/candidate documents as read-only.

- [ ] **Step 5: Run and commit**

```powershell
node --test frontend/tests/unit/seedDocument.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/seedStore.test.mjs
git add frontend/src/views/ProjectSeedsView.vue frontend/src/components/seeds frontend/src/stores/seedStore.js frontend/tests/unit/seedDocument.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/seedStore.test.mjs
git commit -m "feat: make project Seed a complete author document"
```

Expected: PASS.

---

### Task 4: Derive Contract document access without weakening `draftStage`

**Files:**
- Create: `frontend/src/application/contracts/contractDocumentSections.js`
- Create: `frontend/tests/unit/contractDocumentSections.test.mjs`
- Modify: `frontend/src/domain/creation-contract/wizard-state.js`
- Modify: `frontend/src/stores/creationContractStore.js`

- [ ] **Step 1: Write the failing deterministic section-state test**

Given `draftStage`, server readiness/capability, current payload, and selection drift, assert:

```text
all six sections are always visible
engine-stage writes only engine-owned fields
style-stage opens style and capacity fields allowed by the existing contract
assets-stage opens asset fields and final preview
blocked comes only from server capability/reasons or server validation
filled/suggested are display-only and never grant confirm capability
draftVersion is labelled 并发版本, not 历史版本
```

Run:

```powershell
node --test frontend/tests/unit/contractDocumentSections.test.mjs
```

Expected: FAIL because the mapper does not exist.

- [ ] **Step 2: Implement a pure presentation mapper**

Export one `contractDocumentSections(state)` function. It may call the existing `contractStepAccess()` to preserve the tested `engine/style/assets` rules, but must return author sections rather than step numbers. Do not add a client-side permission source.

- [ ] **Step 3: Keep Store semantics unchanged**

Add only selectors needed by the document UI, such as active CAS version, saved stage, server confirm capability, and server reasons. Existing save, engine generation, style trial, preview, confirm, history, idempotency, conflict, and authoritative reload commands remain the only writes.

- [ ] **Step 4: Run and commit**

```powershell
node --test frontend/tests/unit/contractDocumentSections.test.mjs frontend/tests/unit/projectContractView.test.mjs
git add frontend/src/application/contracts frontend/src/domain/creation-contract/wizard-state.js frontend/src/stores/creationContractStore.js frontend/tests/unit/contractDocumentSections.test.mjs
git commit -m "refactor: map Contract stages into document sections"
```

Expected: PASS.

---

### Task 5: Replace the Contract wizard presentation with one browsable document

**Files:**
- Modify: `frontend/src/views/ProjectContractView.vue`
- Modify: `frontend/src/components/project/CreationContractWizard.vue`
- Modify: `frontend/src/components/project/contract/StoryEngineStep.vue`
- Modify: `frontend/src/components/project/contract/StyleSelectionStep.vue`
- Modify: `frontend/src/components/project/contract/StyleTrialPanel.vue`
- Modify: `frontend/src/components/project/contract/AssetScopeStep.vue`
- Modify: `frontend/src/components/project/contract/CapacityStep.vue`
- Modify: `frontend/src/components/project/contract/ContractPreviewStep.vue`
- Modify: `frontend/src/components/project/contract/ContractDecisionSummary.vue`
- Modify: `frontend/tests/unit/projectContractView.test.mjs`

- [ ] **Step 1: Replace wizard-oriented test expectations with document expectations**

Assert:

```text
the confirmed Seed summary is visible above the document
all six Contract section headings exist in one render
clicking a directory item targets a section instead of changing page step
locked downstream sections explain their responsibility and server blocker
engine multi-proposal and style trial remain preview-before-adopt
capacity, assets, styles, and prohibited directions keep existing saves
final confirmation uses the server preview snapshot/hash/capability
confirmed Contract removes every write/AI/preview control
there is no 下一步 / 上一步 / step progress bar / automatic route push
```

Run:

```powershell
node --test frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/contractDocumentSections.test.mjs
```

Expected: FAIL against the current five-step template.

- [ ] **Step 2: Refactor `CreationContractWizard.vue` in place**

Keep the component filename to avoid route churn, but replace `step` navigation with `activeSectionKey` and the shared Foundation shell. Render every section in document order. A locked section remains readable and states which prerequisite is missing; its submit controls are absent.

- [ ] **Step 3: Adapt existing section components, do not duplicate them**

Remove their page-level “next/previous” footer assumptions. Retain their current form data, validation, Store calls, AI preview/adopt behavior, idempotency, and busy handling. Each component emits `editing`, `dirty`, and `saved` to the document owner; only one section can edit at a time.

- [ ] **Step 4: Use the shared visual confirmation shell with Contract-specific data**

Pass the existing server preview, draft version/hash, confirmed Seed reference, frozen asset/style references, readiness reasons, and Contract confirm callback through slots. Do not create a common confirm adapter or infer readiness from local completeness.

- [ ] **Step 5: Verify no writer-core regression and commit**

```powershell
node --test frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/contractDocumentSections.test.mjs
npm --prefix frontend run build
git add frontend/src/views/ProjectContractView.vue frontend/src/components/project frontend/tests/unit/projectContractView.test.mjs
git commit -m "feat: present Contract as one author document"
```

Expected: tests and build PASS.

---

### Task 6: Define whole/section Bible proposal prompts and result contracts

**Files:**
- Modify: `backend/prompts/bible.py`
- Modify: `backend/services/bible_generation.py`
- Modify: `backend/tests/unit/test_bible_prompt.py`
- Modify: `backend/tests/unit/test_bible_generation_service.py`

- [ ] **Step 1: Write failing prompt and command tests**

Test these cases:

```python
whole proposal accepts no saved draft and asks for one complete BiblePayload
section proposal requires a saved draft and includes that complete draft as currentBible
scope is one of the stable keys listed above
request hash and manifest differ by operation and scope
prompt states that non-target fields must be retained
prompt remains bounded and never includes Provider secrets
```

Run:

```powershell
python -m pytest backend/tests/unit/test_bible_prompt.py backend/tests/unit/test_bible_generation_service.py -q
```

Expected: FAIL on the new proposal command/prompt arguments.

- [ ] **Step 2: Add the proposal command without changing `GenerateBibleDraft` compatibility**

In `backend/services/bible_generation.py`, add a frozen `GenerateBibleProposal` dataclass with `scope`, author instructions, expected versions, and idempotency key. Keep `GenerateBibleDraft` and its direct-write behavior for compatibility.

Factor validation/request document/manifest building so both operations share the existing safeguards but include:

```python
"operation": "proposal"  # or "draft_generation"
"scope": command.scope   # proposal only
```

- [ ] **Step 3: Extend the prompt builder minimally**

Add `proposal_scope` and `current_bible` arguments. Whole mode asks for a complete first proposal. Section mode supplies the saved complete Bible and asks the Provider to improve only the target semantic section while still returning all strict fields. Keep the same JSON-only output schema and token/context budgets.

- [ ] **Step 4: Add validated proposal content to the public result object**

Extend `BibleGenerationAttemptResult` with `proposal: BiblePayload | None`. `_attempt_result()` decodes `result_json` only for `succeeded`, validates it strictly as `BiblePayload`, and fails closed on corrupt stored content.

- [ ] **Step 5: Run and commit**

```powershell
python -m pytest backend/tests/unit/test_bible_prompt.py backend/tests/unit/test_bible_generation_service.py -q
git add backend/prompts/bible.py backend/services/bible_generation.py backend/tests/unit/test_bible_prompt.py backend/tests/unit/test_bible_generation_service.py
git commit -m "feat: define audited Bible proposal contracts"
```

Expected: prompt/domain tests PASS. Route-level proposal tests are added and completed together in Task 7.

---

### Task 7: Implement the non-mutating Bible proposal service and route

**Files:**
- Modify: `backend/services/bible_generation.py`
- Modify: `backend/domain/routers/bibles.py`
- Modify: `backend/tests/unit/test_bible_generation_service.py`
- Modify: `backend/tests/api/test_bible_routes.py`
- Modify: `backend/tests/api/test_route_inventory.py`

- [ ] **Step 1: Write failing service transaction tests**

Add tests for:

```text
successful whole proposal stores only terminal attempt result_json/result_hash
successful section proposal stores only terminal attempt result_json/result_hash
insert_draft, cas_update_draft, and deactivate_active_draft are never called
active draft ID/version/hash and head revision are identical before and after
replay returns the same validated proposal without a second Provider call
version/binding/manifest drift fails without publishing a proposal
confirmed Bible, archived project, missing Contract, unbound Provider, and unsaved section proposal are rejected
failed/unknown outcomes return no proposal and preserve the draft
```

- [ ] **Step 2: Implement a proposal-only terminal transaction**

Add `BibleGenerationService.propose(command)`. Reuse `_reserve`, `_load_inputs`, gateway invocation, strict `BiblePayload` parsing, cancellation handling, lease/idempotency, and attempt status handling. Add a `_complete_proposal()` transaction that:

1. re-locks project and attempt;
2. re-runs `_load_inputs(..., build_prompt=False)`;
3. compares manifest and basis;
4. calls only `succeed_generation_attempt(...)`;
5. returns the validated result.

Do not route proposal success through the existing `_publish()` draft-writing function.

- [ ] **Step 3: Add strict HTTP validation and public serialization**

Add `GenerateBibleProposalBody` in `backend/domain/routers/bibles.py` with a `Literal` scope and the same bounded author instructions, expected versions, and idempotency pattern. Add `POST /projects/{pid}/bible/proposals`. `_public_generation_attempt()` serializes `proposal` with `model_dump(mode="json")` when present.

- [ ] **Step 4: Pin the route inventory**

Add the proposal route to `backend/tests/api/test_route_inventory.py`; do not remove or rename existing Bible routes in this batch.

- [ ] **Step 5: Run and commit**

```powershell
python -m pytest backend/tests/unit/test_bible_generation_service.py backend/tests/api/test_bible_routes.py backend/tests/api/test_route_inventory.py -q
git add backend/services/bible_generation.py backend/domain/routers/bibles.py backend/tests/unit/test_bible_generation_service.py backend/tests/api/test_bible_routes.py backend/tests/api/test_route_inventory.py
git commit -m "feat: add non-mutating Bible proposal API"
```

Expected: PASS, including explicit repository-call assertions proving no draft mutation.

---

### Task 8: Add Bible proposal client, Store, scope adapter, and controller behavior

**Files:**
- Create: `frontend/src/application/bible/bibleProposalScopes.js`
- Create: `frontend/tests/unit/bibleProposalScopes.test.mjs`
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/bibleStore.js`
- Modify: `frontend/src/application/bible/bibleWorkspaceController.js`
- Modify: `frontend/tests/unit/bibleStore.test.mjs`
- Modify: `frontend/tests/unit/bibleWorkspaceController.test.mjs`

- [ ] **Step 1: Write failing client/Store/controller tests**

Cover:

```text
api.bible.propose POSTs the exact stable body
Store keeps proposal separate from draft/head/dirty state
proposal success does not reload draft as direct generate currently does
whole adoption replaces the local complete work copy only
section adoption copies only its mapped field(s)
section proposal is denied while local work is dirty or no saved draft exists
whole proposal can create an initial local work copy without saving it
project switch invalidates proposal requests and clears proposal state
conflict preserves the local work copy
confirmed/archived modes cannot propose or adopt
```

Run:

```powershell
node --test frontend/tests/unit/bibleProposalScopes.test.mjs frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs
```

Expected: FAIL.

- [ ] **Step 2: Implement a frozen scope map and copy helpers**

`bibleProposalScopes.js` owns stable keys, Chinese labels, and exact field mapping. Export pure `adoptBibleProposal(current, proposal, scope)` that deep-copies and never mutates either argument.

- [ ] **Step 3: Add `api.bible.propose` and Store proposal state**

Sanitize the returned attempt with the existing Bible public-data rules and strict expected fields. Add `proposalAttempt`, `proposing`, `propose()`, and `clearProposal()` without changing direct `generate()` compatibility. A successful proposal must not call `head()` or `draft.get()`.

- [ ] **Step 4: Add controller preview/adoption behavior**

The controller owns `proposalOpen`, requested scope, comparison snapshot, and explicit adopt/cancel. Adopting changes only `working`; it sets unsaved state and never calls Store save automatically. Saving still sends one complete current payload through existing `PUT /bible/draft` CAS.

- [ ] **Step 5: Run and commit**

```powershell
node --test frontend/tests/unit/bibleProposalScopes.test.mjs frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs
git add frontend/src/api/db/client.js frontend/src/application/bible frontend/src/stores/bibleStore.js frontend/tests/unit/bibleProposalScopes.test.mjs frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs
git commit -m "feat: add explicit Bible proposal adoption flow"
```

Expected: PASS.

---

### Task 9: Convert Bible into a sectioned author document with proposal review

**Files:**
- Create: `frontend/src/components/bible/BibleProposalReview.vue`
- Create: `frontend/tests/unit/bibleProposalReview.test.mjs`
- Modify: `frontend/src/views/ProjectBibleView.vue`
- Modify: `frontend/src/components/bible/BibleEditor.vue`
- Modify: `frontend/src/components/bible/BibleHistoryDrawer.vue`
- Modify: `frontend/src/application/bible/bibleStatusPresentation.js`
- Modify: `frontend/tests/unit/projectBibleView.test.mjs`
- Modify: `frontend/tests/unit/bibleStatusPresentation.test.mjs`
- Modify: `frontend/tests/unit/bibleModalFocus.test.mjs`

- [ ] **Step 1: Write failing document/proposal/read-only tests**

Assert:

```text
all ten approved Bible sections are visible in one document
summary shows Contract basis, draft CAS version, world/core-cast/faction counts, and open-question count
only one section is editable at a time
完成本区编辑 changes only the local complete work copy
手动保存 sends the full 11-field BiblePayload
whole and section proposal have a before/after preview
采纳建议 changes only the local work copy and remains visibly unsaved
取消 closes preview without changing the work copy
formal page no longer calls /bible/generate
confirmed Bible removes edit/save/proposal/confirm controls
history remains read-only and does not imply recoverable draft history
```

Run:

```powershell
node --test frontend/tests/unit/bibleProposalReview.test.mjs frontend/tests/unit/projectBibleView.test.mjs frontend/tests/unit/bibleStatusPresentation.test.mjs frontend/tests/unit/bibleModalFocus.test.mjs
```

Expected: FAIL.

- [ ] **Step 2: Refactor `BibleEditor.vue` into readable sections**

Keep one complete `modelValue`. Add `activeSection`, `editingSection`, `readOnly`, and section-level events. Scalar/list controls remain the existing implementation; do not create partial payload DTOs. Empty sections explain their required content.

- [ ] **Step 3: Build `BibleProposalReview.vue` for one consumer**

Show scope, author request, current text/items, proposed text/items, and explicit “采纳建议” / “取消”. For whole proposals, show a compact section-by-section comparison rather than raw JSON. For a section proposal, show only mapped fields. Keep the proposal dialog independently scrollable and restore focus/scroll on close.

- [ ] **Step 4: Recompose `ProjectBibleView.vue` with the shared shell**

Use the section directory, full document, and right rail. Replace the author-page “生成创作圣经” action with “AI 生成初稿” (whole, when no saved draft) and “AI 补充/重写本区” (saved, clean draft). Leave the old direct-generate Store method unreferenced by the formal view.

- [ ] **Step 5: Correct author-facing status language**

Replace “请完成或重新签署创作契约” with:

```text
当前项目契约状态异常，请查看来源与诊断。
```

Keep stable reason/error codes only inside the diagnosis detail. Do not translate unknown server codes into invented recovery actions.

- [ ] **Step 6: Use the shared confirmation visuals with the Bible-specific adapter**

Pass the current saved complete draft, `draftVersion`, Contract basis, service capability/reasons, and existing Bible confirm callback. Confirmation success stays on the Bible route and switches to permanent read-only.

- [ ] **Step 7: Run and commit**

```powershell
node --test frontend/tests/unit/bibleProposalReview.test.mjs frontend/tests/unit/projectBibleView.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/bibleStatusPresentation.test.mjs frontend/tests/unit/bibleModalFocus.test.mjs
npm --prefix frontend run build
git add frontend/src/views/ProjectBibleView.vue frontend/src/components/bible frontend/src/application/bible frontend/tests/unit/bibleProposalReview.test.mjs frontend/tests/unit/projectBibleView.test.mjs frontend/tests/unit/bibleStatusPresentation.test.mjs frontend/tests/unit/bibleModalFocus.test.mjs
git commit -m "feat: make Bible a proposal-aware author document"
```

Expected: tests and build PASS.

---

### Task 10: Unify author wording, status derivation, and confirmation behavior across all three pages

**Files:**
- Modify: `frontend/src/views/ProjectSeedsView.vue`
- Modify: `frontend/src/components/project/CreationContractWizard.vue`
- Modify: `frontend/src/views/ProjectBibleView.vue`
- Modify: `frontend/tests/unit/projectSeedsView.test.mjs`
- Modify: `frontend/tests/unit/projectContractView.test.mjs`
- Modify: `frontend/tests/unit/projectBibleView.test.mjs`
- Modify: `frontend/tests/unit/foundationWorkspace.test.mjs`

- [ ] **Step 1: Add cross-page static and render assertions**

Test that each page shows a Chinese title, purpose, lifecycle, upstream summary, editability, complete content, and source/diagnosis details. Assert the main author surface does not expose:

```text
raw JSON
stable keys as labels
unexplained English enum values
hashes or internal IDs as primary headings
重新签署
确认并进入
下一步
```

- [ ] **Step 2: Implement the three separate confirmation adapters through slots**

Seed supplies candidate revision/payload/provenance/selection capability. Contract supplies server preview/draft version/hash/confirm capability. Bible supplies saved full draft/draft version/Contract basis/confirm capability. The shared dialog remains unaware of all three command shapes.

- [ ] **Step 3: Verify confirmed mode removes writes**

For each page test the DOM after successful confirmation, after reload, and in an archived project. Buttons and inputs for edit, save, AI, clone, delete, restore, select, preview, and confirm must be absent rather than merely disabled.

- [ ] **Step 4: Run and commit**

```powershell
node --test frontend/tests/unit/foundationWorkspace.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/projectBibleView.test.mjs
git add frontend/src/views/ProjectSeedsView.vue frontend/src/components/project/CreationContractWizard.vue frontend/src/views/ProjectBibleView.vue frontend/tests/unit/foundationWorkspace.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/projectBibleView.test.mjs
git commit -m "fix: align creative foundation author states"
```

Expected: PASS.

---

### Task 11: Verify responsive scrolling, keyboard access, focus, and reduced motion

**Files:**
- Modify: `frontend/src/components/foundation/FoundationWorkspace.vue`
- Modify: `frontend/src/components/foundation/FoundationSectionIndex.vue`
- Modify: `frontend/src/components/foundation/FoundationConfirmationDialog.vue`
- Modify: `frontend/src/components/seeds/SeedOtherCandidatesDrawer.vue`
- Modify: `frontend/src/components/project/contract/ContractHistoryDrawer.vue`
- Modify: `frontend/src/components/bible/BibleHistoryDrawer.vue`
- Modify: `frontend/tests/unit/foundationWorkspace.test.mjs`
- Modify: `frontend/tests/unit/bibleModalFocus.test.mjs`

- [ ] **Step 1: Add failing interaction checks**

Cover:

```text
directory navigation is keyboard operable
target heading receives focus without losing the page scroll container
Esc closes dialog/drawer when safe
Tab remains inside the open modal
closing restores trigger focus and previous scroll position
side rail wheel/touch scrolling does not block main page scrolling
360px viewport has no horizontal overflow
prefers-reduced-motion disables decorative transitions
live regions announce one state change, not duplicated labels
```

- [ ] **Step 2: Apply only local CSS/interaction fixes**

Use `min-width: 0`, bounded modal/drawer `max-height`, `overflow: auto` only on the bounded overlay body, natural page scrolling elsewhere, and explicit focus restoration. Do not introduce a global scroll manager.

- [ ] **Step 3: Run and commit**

```powershell
node --test frontend/tests/unit/foundationWorkspace.test.mjs frontend/tests/unit/bibleModalFocus.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/projectBibleView.test.mjs
git add frontend/src/components/foundation frontend/src/components/seeds/SeedOtherCandidatesDrawer.vue frontend/src/components/project/contract/ContractHistoryDrawer.vue frontend/src/components/bible/BibleHistoryDrawer.vue frontend/tests/unit/foundationWorkspace.test.mjs frontend/tests/unit/bibleModalFocus.test.mjs
git commit -m "fix: harden foundation workspace interaction quality"
```

Expected: PASS.

---

### Task 12: Add one deterministic P0-D browser acceptance path

**Files:**
- Create: `frontend/e2e/p0-d-creative-foundation.spec.ts`
- Create: `frontend/e2e/run-p0-d.mjs`
- Modify: `scripts/run-tests.mjs`
- Modify: `frontend/package.json`
- Modify: `package.json`

- [ ] **Step 1: Register the failing formal browser suite**

Add `browser-p0-d` to `scripts/run-tests.mjs`, plus:

```json
"test:browser:p0-d": "node scripts/run-tests.mjs browser-p0-d"
```

at the root and the equivalent `../scripts/run-tests.mjs` command in `frontend/package.json`.

Run:

```powershell
npm run test:browser:p0-d
```

Expected: FAIL because the runner/spec is absent.

- [ ] **Step 2: Build a bounded disposable runner by reusing product-runner helpers**

Follow `frontend/e2e/run-p0-c.mjs` ownership patterns:

- create one exact disposable MySQL database matching `^novel_creator_test_[0-9a-f]{32}$`;
- start loopback-only fake Provider, backend, Vite, and Playwright processes;
- expose no runtime secrets in logs/artifacts;
- use deterministic Seed/Contract/Bible fixtures and Provider JSON;
- count expected Provider calls;
- verify the active Bible draft row is unchanged by proposal and changes only after explicit save;
- terminate owned processes and delete only the owned database/temp root in `finally`;
- do not access `novel_creator` or `novel_creator_v113`.

- [ ] **Step 3: Implement the single complete author flow**

The spec performs:

1. open project Seed and inspect the thirteen-field candidate;
2. edit/save one candidate revision;
3. preview and confirm Seed, remain on page, verify permanent read-only and other-candidates drawer;
4. open Contract manually from project navigation;
5. generate/preview/adopt story-engine options, fill the remaining sections through real stage saves, preview and confirm;
6. open Bible manually from project navigation;
7. request a whole proposal and verify the UI/dataset still reports no active draft mutation;
8. adopt, save the whole payload, request and adopt one section proposal, save again;
9. preview and confirm Bible;
10. reload all three pages and verify full content plus absent write controls;
11. exercise desktop scrolling and a 360px viewport without horizontal overflow;
12. assert exact writes and zero browser console/page errors.

Do not test real prose generation or downstream chapter writing here.

- [ ] **Step 4: Run and commit**

With the repository's standard in-memory test environment bridge supplying only `TEST_MYSQL_HOST`, `TEST_MYSQL_PORT`, `TEST_MYSQL_USER`, and `TEST_MYSQL_PASSWORD`, run once:

```powershell
npm run test:browser:p0-d
```

Expected terminal markers:

```text
p0d_browser_database=verified
p0d_browser_cleanup=verified
```

Then:

```powershell
git add frontend/e2e/p0-d-creative-foundation.spec.ts frontend/e2e/run-p0-d.mjs scripts/run-tests.mjs frontend/package.json package.json
git commit -m "test: accept the P0-D creative foundation flow"
```

---

### Task 13: Run the complete verification gate and close the implementation branch

**Files:** No production edits expected; fix only evidence-backed failures within P0-D scope.

- [ ] **Step 1: Run the full relevant frontend unit set**

```powershell
node --test frontend/tests/unit/foundationWorkspace.test.mjs frontend/tests/unit/seedDocument.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/seedStore.test.mjs frontend/tests/unit/contractDocumentSections.test.mjs frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/bibleProposalScopes.test.mjs frontend/tests/unit/bibleProposalReview.test.mjs frontend/tests/unit/projectBibleView.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/bibleStatusPresentation.test.mjs frontend/tests/unit/bibleModalFocus.test.mjs
```

Expected: PASS.

- [ ] **Step 2: Run the full relevant backend set**

```powershell
python -m pytest backend/tests/unit/test_bible_prompt.py backend/tests/unit/test_bible_generation_service.py backend/tests/unit/test_bible_service.py backend/tests/api/test_bible_routes.py backend/tests/api/test_route_inventory.py -q
```

Expected: PASS.

- [ ] **Step 3: Run surrounding Seed/Contract/Bible regression tests**

```powershell
python -m pytest backend/tests/unit/test_seed_domain.py backend/tests/unit/test_seed_service.py backend/tests/api/test_seed_routes.py backend/tests/unit/test_contract_service.py backend/tests/api/test_contract_routes.py -q
npm run test:browser:phase2
```

Use only the existing deterministic/disposable test bridge for suites that require MySQL. Expected: PASS, no product database access.

- [ ] **Step 4: Run production build and P0-D browser acceptance**

```powershell
npm --prefix frontend run build
npm run test:browser:p0-d
```

Expected: PASS and cleanup markers present.

- [ ] **Step 5: Review the diff against the non-goals**

Run:

```powershell
git diff --check
git status --short
git diff --stat main...HEAD
git diff --name-only main...HEAD
rg -n "partial.?bible|proposal.*table|重新签署|确认并进入|自动.*下一步" backend frontend/src
```

Verify:

- no schema/Canon/Projection/Planning/writer-core files changed;
- no new authority or generic form/rewrite/confirm layer exists;
- no confirmed page exposes writes;
- proposal completion does not call draft repository writes;
- all business labels are Chinese or have adjacent Chinese explanation;
- only owned implementation artifacts are staged.

- [ ] **Step 6: Request final code review**

Use `superpowers:requesting-code-review`. Review specifically for authority regression, direct-draft mutation from proposal, client-inferred permission, confirmed-baseline write leaks, scroll/focus regression, and test-only overengineering. Fix only verified P0-D defects and rerun the affected gates.

- [ ] **Step 7: Create the final verification commit only if fixes were needed**

```powershell
git add -p
git commit -m "fix: close P0-D verification findings"
```

Do not create an empty commit.

- [ ] **Step 8: Finish the branch safely**

Use `superpowers:verification-before-completion`, then `superpowers:finishing-a-development-branch`. Report exact test counts, build result, browser cleanup evidence, commits, changed-file boundary, and any retained compatibility route. Do not merge or push until the user selects the integration option.

---

## Plan self-check

- Every approved Seed/Contract/Bible section, state, AI rule, confirmation rule, and read-only rule maps to an implementation task and test.
- Seed stays on the thirteen-field authority and retains old nine-field revision display compatibility.
- Contract becomes a document without weakening `draftStage` or replacing server preview/capability.
- Bible section editing remains one local complete work copy and one whole-payload save.
- Bible proposal uses the existing Provider/gateway/prompt/parser/attempt storage and cannot mutate the active draft.
- The five shared components are presentation-only; there is no shared Store, command, version model, or domain state machine.
- Confirmed baselines remain permanent and have no clone/re-sign/next-step UI.
- Current state, memory, arcs, clues, Planning, Canon, Projection, and Writer Core are untouched.
- Browser verification is one complete deterministic author flow, not a new test platform or real article-generation exercise.
- The plan contains no unresolved marker, pseudo-file, or unspecified implementation handoff.
