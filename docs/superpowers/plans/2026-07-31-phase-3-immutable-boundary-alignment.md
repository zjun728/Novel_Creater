# Phase 3 Immutable Boundary Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the delivered Seed, Contract, Bible, Chapter Outline, and
ChapterSession flow with the approved immutable-boundary model: confirmed
project baselines never change, while an outline may change until its chapter
prose is finalized and every candidate records the exact outline it used.

**Architecture:** Keep the existing services, routes, stores, and schema. Seed
selection and Bible confirmation become terminal server-side transitions.
ChapterSession remains immutable entry provenance, but the current Outline Head
may advance while the session is drafting; each newly saved Candidate records
the current Outline and Planning authority in its existing `provenance_json`,
and the read model derives `current` or `stale`. Finalization and Canon
realization remain a separate Phase 5 transaction.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, aiomysql, MySQL 8, pytest,
Vue 3, Pinia 3, Vue Router 4, Naive UI, Node test runner, Playwright.

---

## Authority, worktree, and scope

- Product correction:
  `docs/superpowers/specs/2026-07-31-immutable-boundaries-revision-design.md`.
- Existing Phase 3 authority:
  `docs/superpowers/specs/2026-07-24-phase-3-story-planning-design.md`.
- Existing Phase 3D delivery plan:
  `docs/superpowers/plans/2026-07-30-phase-3d-boundary-and-acceptance.md`.
- Branch: `codex/phase3d-boundary-acceptance`.
- Starting HEAD: `a81ae8f5a1b370a65bdddedfff1854f13f139ca1`.
- Worktree:
  `D:\CodexData\.codex\worktrees\phase3d-boundary-acceptance\Novel_Creater`.

The working tree already contains the uncommitted Phase 3 formal browser
runner. Preserve these files and build the corrected scenarios into the same
runner:

```text
frontend/e2e/runtime-observer.mjs
frontend/package.json
package.json
scripts/run-tests.mjs
scripts/tests/run-tests.test.mjs
scripts/tests/runtime-observer.test.mjs
frontend/e2e/phase3-story-planning.spec.ts
frontend/e2e/playwright.phase3.config.ts
frontend/e2e/run-phase3.mjs
scripts/tests/phase3Suite.test.mjs
```

Do not reset, checkout, clean, or replace those paths. Before every commit,
stage only the files named by that task and inspect `git diff --cached`.

## Fixed product decisions

- The flow is Seed -> Contract -> Bible -> Planning -> Outline -> Writing.
- The first confirmed Seed, Contract, and Bible are permanent project
  baselines. There is no later selection, clone, revision, reactivation,
  project branch, or history rewrite.
- Planning contains Volume, Plot, StoryBlock, Stage, and SceneTask. Future,
  unrealized content may change; realized historical identity may not.
- A ChapterSession records the authority used to enter writing and is not
  silently rebound when the Outline Head advances.
- Until prose finalization exists and succeeds, the current chapter outline can
  be adjusted, regenerated, and adopted even when a drafting Session exists.
- Existing WorkingDraft and Candidate rows are preserved after an outline
  change.
- A Candidate records the current Outline Head and its Planning authority when
  saved. A Candidate based on a previous Outline Head is `stale`; it is not
  deleted.
- Phase 5 finalization will require a `current` Candidate and atomically freeze
  the current Outline, prose, Canon, Projection, and realized Planning facts.

## Explicit non-goals

- Do not implement `FinalizationService`, Canon extraction, Projection writes,
  typed Planning realization, or post-finalization outline locking here.
- Do not add editable setting-library, memory, arc, or plot-progress modules.
  Their existing Canon projection read APIs remain unchanged.
- Do not change `writer-core-v1.5.0`, add columns, or create a migration.
  Candidate basis fits in existing `draft_candidates.provenance_json`.
- Do not migrate or read a product database. Automated tests use only owned
  `novel_creator_test_%` databases.
- Do not call a real Provider, model, or public website.
- Do not add a second Seed/Bible/Planning/Outline/Session runtime.

## Public contracts introduced by this plan

Candidate JSON gains nine authority fields and one derived state:

```json
{
  "outlineRevisionId": "outline-revision-id",
  "outlineRevision": 2,
  "outlineHash": "64-lowercase-hex",
  "planningRevisionId": "planning-revision-id",
  "planningRevision": 3,
  "planningHash": "64-lowercase-hex",
  "canonRevision": 4,
  "projectionRevision": 4,
  "projectionHash": "64-lowercase-hex",
  "basisStatus": "current"
}
```

`basisStatus` is exactly `current` or `stale`. It is derived by comparing the
stored candidate basis with the current Outline Head and its bound Planning
revision. Missing legacy basis is always `stale`; the server never guesses.
Canon/Projection fields preserve the exact generation baseline; Phase 5 will
separately reject finalization if the live Canon/Projection authority drifted.

The public names deliberately use `outlineRevisionId`, not
`chapterOutlineRevisionId`, because the value describes Candidate basis rather
than Session entry provenance.

### Task 1: Amend active Phase 3 authority without falsifying old acceptance

**Files:**

- Modify:
  `docs/superpowers/specs/2026-07-11-writer-core-v1-design.md`
- Modify:
  `docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md`
- Modify:
  `docs/superpowers/specs/2026-07-24-phase-3-story-planning-design.md`
- Modify:
  `docs/superpowers/specs/2026-07-26-phase-3c-story-blocks-outlines-design.md`
- Modify:
  `docs/superpowers/plans/2026-07-30-phase-3d-boundary-and-acceptance.md`
- Modify:
  `docs/acceptance/2026-07-24-phase-3a-planning-aggregate.md`

- [ ] **Step 1: Add a precedence notice to each superseded specification**

Insert this notice immediately below each document title:

```markdown
> **2026-07-31 precedence notice:** Where this document permits replacing a
> confirmed Seed/Bible, treats a drafting ChapterSession as an Outline freeze,
> or invalidates an adopted Outline merely because Planning Head advances,
> `docs/superpowers/specs/2026-07-31-immutable-boundaries-revision-design.md`
> takes precedence.
```

- [ ] **Step 2: Replace the two obsolete Phase 3D scenario definitions**

In
`docs/superpowers/plans/2026-07-30-phase-3d-boundary-and-acceptance.md`,
replace `unused-outline-supersession` and `selection-aba` with:

```markdown
- `baseline-lock`: after first Seed, Contract, and Bible confirmation, the UI
  exposes no replacement action and direct mutation attempts return the fixed
  public conflict without changing any head.
- `outline-adjustment-before-finalization`: after a drafting ChapterSession
  exists, the author adjusts and adopts a new Outline through visible UI;
  existing prose remains, the old Candidate becomes stale, and a newly saved
  Candidate is current.
```

Keep the old implementation plan history around these bullets intact.

- [ ] **Step 3: Mark the old Phase 3A A->B->A result as historical**

Append this exact amendment to the acceptance report:

```markdown
## 2026-07-31 authority amendment

The A->B->A seed-selection behavior recorded above was valid for the superseded
Phase 3A contract only. It is not current product authority. The first confirmed
Seed is now terminal under
`docs/superpowers/specs/2026-07-31-immutable-boundaries-revision-design.md`;
new acceptance must prove that a second selection is refused.
```

- [ ] **Step 4: Verify documentation consistency**

Run:

```powershell
git diff --check
Select-String -Path docs/superpowers/specs/*.md,docs/superpowers/plans/*.md,docs/acceptance/*.md -Pattern '2026-07-31 precedence notice|2026-07-31 authority amendment'
```

Expected: `git diff --check` exits 0; the four precedence notices and one
acceptance amendment are present.

- [ ] **Step 5: Commit the authority amendment**

```powershell
git add docs/superpowers/specs/2026-07-11-writer-core-v1-design.md docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md docs/superpowers/specs/2026-07-24-phase-3-story-planning-design.md docs/superpowers/specs/2026-07-26-phase-3c-story-blocks-outlines-design.md docs/superpowers/plans/2026-07-30-phase-3d-boundary-and-acceptance.md docs/acceptance/2026-07-24-phase-3a-planning-aggregate.md
git diff --cached --check
git commit -m "docs: align phase 3 immutable boundaries"
```

### Task 2: Make the first Seed selection terminal

**Files:**

- Modify: `backend/http_errors.py`
- Modify: `backend/services/seeds.py:168-197,579-637`
- Test: `backend/tests/unit/test_seed_service.py`
- Test: `backend/tests/integration/test_seed_revisions.py`
- Test: `backend/tests/api/test_seed_routes.py`

- [ ] **Step 1: Write failing service tests**

Add tests that construct two candidate seeds, select Seed A, then assert:

```python
selected = await service.select(select_command(seed_a, selection_revision=0))
assert selected.capabilities.canEdit is False
assert selected.capabilities.canSelect is False

with pytest.raises(SeedAlreadyConfirmed):
    await service.select(select_command(seed_b, selection_revision=1))

assert repository.selection["seed_id"] == seed_a
assert repository.replace_selection_calls == []
```

Also assert a selected seed cannot be edited even when no finalized chapter
exists. The test must fail against the old `candidate and not history_locked`
capability rule.

- [ ] **Step 2: Run the focused RED tests**

Run:

```powershell
python -m pytest backend/tests/unit/test_seed_service.py -q
```

Expected: FAIL because the selected Seed still reports `canEdit=true` or the
second selection reaches `replace_selection`.

- [ ] **Step 3: Implement the terminal selection rule**

Change the capability derivation to:

```python
capabilities = SeedMutationCapabilities(
    referenced=referenced,
    hasFinalChapters=has_final_chapters,
    canEdit=candidate and not selected and not referenced,
    canSelect=candidate and not selected and not referenced,
    canArchive=candidate and not selected,
    canRestore=archived and not selected,
    canPermanentlyDelete=not selected and not referenced,
)
```

In `select`, reject any existing project selection before calculating the
target Seed capability:

```python
selection = await self.repository.lock_selection(session, command.project_id)
current_revision = _selection_revision(selection)
if current_revision != command.expected_selection_revision:
    raise SeedConflict()
if selection is not None:
    raise SeedAlreadyConfirmed()
```

Always call `insert_selection`; remove the reachable
`replace_selection` branch. Keep selection-revision history for the first
selection only.

Define `SeedAlreadyConfirmed` as a safe `409` `PublicDomainError` with the
fixed public code `seed_already_confirmed`. Keep `SeedLocked` for other
historical dependency locks.

- [ ] **Step 4: Add integration and API invariants**

In the integration test, select A, attempt B, then query both
`project_seed_selection` and `project_seed_selection_revisions`. Assert the
head still points to A and exactly one selection revision exists.

In the API test, POST a second valid selection body and assert:

```python
assert response.status_code == 409
assert response.json()["code"] == "seed_already_confirmed"
```

Do not assert the private service message.

- [ ] **Step 5: Run Seed GREEN tests**

Run:

```powershell
python -m pytest backend/tests/unit/test_seed_service.py backend/tests/integration/test_seed_revisions.py backend/tests/api/test_seed_routes.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/http_errors.py backend/services/seeds.py backend/tests/unit/test_seed_service.py backend/tests/integration/test_seed_revisions.py backend/tests/api/test_seed_routes.py
git diff --cached --check
git commit -m "fix: lock confirmed project seed"
```

### Task 3: Make Contract and Bible confirmation terminal

**Files:**

- Modify: `backend/services/contracts/drafts.py`
- Modify: `backend/services/contracts/history.py:660-780`
- Modify: `backend/services/contracts/__init__.py`
- Modify: `backend/services/bibles.py:427-503,590-850,1154-1168`
- Test: `backend/tests/unit/test_bible_service.py`
- Test: `backend/tests/integration/test_bible_revisions.py`
- Test: `backend/tests/api/test_bible_routes.py`
- Test: `backend/tests/unit/test_contract_service.py`
- Test: `backend/tests/integration/test_contract_drafts.py`
- Test: `backend/tests/api/test_contract_routes.py`

- [ ] **Step 1: Write failing Bible tests**

Confirm revision 1, then assert the read model and every write path:

```python
draft_state = await service.get_draft(project_id)
assert draft_state.can_edit is False
assert draft_state.can_confirm is False
assert draft_state.can_clone is False

for mutation in (
    lambda: service.save_draft(save_command),
    lambda: service.clone_draft(clone_command),
    lambda: service.confirm(confirm_command),
):
    with pytest.raises(BibleAlreadyConfirmed):
        await mutation()
```

Use the existing command factories and fake repository conventions in
`test_bible_service.py`; do not introduce a parallel fake.

- [ ] **Step 2: Run the Bible RED test**

```powershell
python -m pytest backend/tests/unit/test_bible_service.py -q
```

Expected: FAIL because a confirmed head still enables `can_clone`.

- [ ] **Step 3: Add one service guard and apply it at every Bible mutation**

Add:

```python
@staticmethod
def _require_unconfirmed_head(head) -> None:
    if head is not None and int(head.get("revision") or 0) > 0:
        raise BibleAlreadyConfirmed()
```

Define `BibleAlreadyConfirmed` as a safe `409` `PublicDomainError` with code
`bible_already_confirmed`.

Call it after locking/reading the Bible Head inside the transaction for save,
clone, and confirmation. Provider generation may still produce a transient
preview, but the save guard prevents it from creating a product draft after
confirmation. A byte-for-byte retry of the successful confirmation idempotency
key still replays the stored success; apply the new guard only before a new
mutation. In `_draft_view`, when the head revision is greater than zero, force:

```python
can_edit = False
can_confirm = False
can_clone = False
reasons = _unique_reasons(reasons, ("bible_confirmed",))
```

Keep confirmed revision history readable.

- [ ] **Step 4: Lock the Contract clone boundary**

Replace the body of `ContractHistoryService.clone_revision` after input and
project validation with a current-head read followed by:

```python
if head is not None and int(head.get("revision") or 0) > 0:
    raise ContractAlreadyConfirmed()
```

Define and export `ContractAlreadyConfirmed` as a safe `409`
`PublicDomainError` with code `contract_already_confirmed`. The public clone
route remains as a compatibility boundary and returns this fixed conflict; it
can never create a new draft.

- [ ] **Step 5: Add Contract terminal regression tests**

Confirm revision 1, call `clone_revision`, and assert
`ContractAlreadyConfirmed`. Also exercise the clone API and assert:

```python
assert response.status_code == 409
assert response.json()["code"] == "contract_already_confirmed"
```

Then assert the confirmed Contract Head remains revision 1 and there is no
active Contract Draft.

- [ ] **Step 6: Add Bible integration and API coverage**

For Bible, assert a post-confirmation clone/save attempt returns:

```python
assert response.status_code == 409
assert response.json()["code"] == "bible_already_confirmed"
```

Then assert the Bible Head is still revision 1 and no second revision or active
draft exists.

- [ ] **Step 7: Run baseline GREEN tests**

```powershell
python -m pytest backend/tests/unit/test_bible_service.py backend/tests/integration/test_bible_revisions.py backend/tests/api/test_bible_routes.py backend/tests/unit/test_contract_service.py backend/tests/integration/test_contract_drafts.py backend/tests/api/test_contract_routes.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 8: Commit**

```powershell
git add backend/services/contracts/drafts.py backend/services/contracts/history.py backend/services/contracts/__init__.py backend/services/bibles.py backend/tests/unit/test_bible_service.py backend/tests/integration/test_bible_revisions.py backend/tests/api/test_bible_routes.py backend/tests/unit/test_contract_service.py backend/tests/integration/test_contract_drafts.py backend/tests/api/test_contract_routes.py
git diff --cached --check
git commit -m "fix: lock confirmed creation baseline"
```

### Task 4: Remove replacement controls from the baseline UI

**Files:**

- Modify: `frontend/src/stores/seedStore.js`
- Modify: `frontend/src/views/ProjectSeedsView.vue`
- Modify: `frontend/src/components/seeds/SeedCard.vue`
- Modify: `frontend/src/stores/creationContractStore.js`
- Modify: `frontend/src/components/project/ContractHeadSummary.vue`
- Modify: `frontend/src/components/project/CreationContractWizard.vue`
- Modify:
  `frontend/src/components/project/contract/ContractHistoryDrawer.vue`
- Modify: `frontend/src/stores/bibleStore.js`
- Modify: `frontend/src/application/bible/bibleWorkspaceController.js`
- Modify: `frontend/src/views/ProjectBibleView.vue`
- Modify: `frontend/src/components/bible/BibleEditor.vue`
- Test: `frontend/tests/unit/seedStore.test.mjs`
- Test: `frontend/tests/unit/projectSeedsView.test.mjs`
- Test: `frontend/tests/unit/creationContractStore.test.mjs`
- Test: `frontend/tests/unit/projectContractView.test.mjs`
- Test: `frontend/tests/unit/bibleStore.test.mjs`
- Test: `frontend/tests/unit/bibleWorkspaceController.test.mjs`
- Test: `frontend/tests/unit/projectBibleView.test.mjs`

- [ ] **Step 1: Write UI RED tests**

Add assertions using the existing SFC/controller harnesses:

```js
assert.equal(store.selected.capabilities.canEdit, false)
assert.equal(store.selected.capabilities.canSelect, false)
assert.equal(rendered.includes('选择此种子'), false)
assert.equal(rendered.includes('调整未来设计'), false)
assert.equal(rendered.includes('创建新版本'), false)
assert.match(rendered, /已确认，作为项目永久基线/)
assert.match(rendered, /确认这个种子并进入创作契约/)
assert.match(rendered, /确认后不可更换/)
```

Also assert Seed, Contract, and Bible stores do not expose a successful local
replacement path after confirmation.

- [ ] **Step 2: Run frontend RED tests**

```powershell
node --test frontend/tests/unit/seedStore.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/creationContractStore.test.mjs frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs frontend/tests/unit/projectBibleView.test.mjs
```

Expected: at least one FAIL because Contract and Bible replacement actions
remain.

- [ ] **Step 3: Implement capability-only UI**

Delete the Contract and Bible clone actions and their controller/store
branches. Keep confirmed history display read-only. Render the immutable label
when a confirmed head exists:

```js
const baselineLocked = computed(() => (
  Number(store.head?.revision || 0) > 0
))
```

Seed buttons continue to read only the server-provided capabilities; do not
infer lock state from route order or finalized-chapter count. The low-level API
client may retain clone methods for compatibility tests, but no product UI or
store invokes them. Before the first Seed selection, the visible primary action
must say “确认这个种子并进入创作契约” and its confirmation surface must say
“确认后不可更换”; cancel performs no write.

- [ ] **Step 4: Run frontend GREEN tests**

Run the same `node --test` command.

Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/stores/seedStore.js frontend/src/views/ProjectSeedsView.vue frontend/src/components/seeds/SeedCard.vue frontend/src/stores/creationContractStore.js frontend/src/components/project/ContractHeadSummary.vue frontend/src/components/project/CreationContractWizard.vue frontend/src/components/project/contract/ContractHistoryDrawer.vue frontend/src/stores/bibleStore.js frontend/src/application/bible/bibleWorkspaceController.js frontend/src/views/ProjectBibleView.vue frontend/src/components/bible/BibleEditor.vue frontend/tests/unit/seedStore.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/creationContractStore.test.mjs frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs frontend/tests/unit/projectBibleView.test.mjs
git diff --cached --check
git commit -m "fix: present confirmed baselines as immutable"
```

### Task 5: Permit Outline adjustment during a drafting ChapterSession

**Files:**

- Modify: `backend/services/chapter_outlines.py:240-620,840-930,1626-1633`
- Test: `backend/tests/unit/test_chapter_outline_service.py`
- Test: `backend/tests/integration/test_chapter_outline_lifecycle.py`
- Test: `backend/tests/api/test_chapter_outline_routes.py`

- [ ] **Step 1: Write service RED tests**

Create a state with a drafting Session and adopted Outline revision 1. Assert:

```python
state = await service.get_state(project_id)
assert state.capabilities.create_draft is True
assert state.capabilities.edit_draft is False
assert state.capabilities.generate is False  # until the new draft exists
assert state.capabilities.start_session is False

draft = await service.create_draft(
    CreateChapterOutlineDraft(project_id=project_id, chapter_number=7)
)
assert draft.content == adopted_outline.content
```

After creating the draft, assert `edit_draft`, `generate`, and `confirm` are
true when their existing prerequisites are met. Add a separate finalized
Session fixture and assert every Outline mutation is false/rejected.

- [ ] **Step 2: Run Outline RED tests**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_service.py -q
```

Expected: FAIL with the existing
`active ChapterSession makes Outline read-only` behavior.

- [ ] **Step 3: Copy the current Outline Head into an adjustment draft**

`ChapterOutlineRepository.lock_outline_head` already returns the joined current
revision, including decoded `content`. Reuse it; do not add another query.
When creating a draft and no current draft exists, use:

```python
content = (
    self._editable_from_outline(head["content"])
    if head is not None and head.get("content") is not None
    else EditableChapterOutlineContent()
)
```

The new draft still binds the current Planning/Canon/Projection authorities and
uses `base_head_revision=head_revision`.

- [ ] **Step 4: Replace the blanket Session lock with finalization-aware logic**

Replace `_require_no_active_session` with:

```python
def _require_outline_mutable(self, active_session) -> None:
    if active_session is None:
        return
    status = active_session.get("effective_status", active_session["status"])
    if status != "drafting":
        raise ChapterOutlineConflict(
            "finalized chapter makes Outline immutable"
        )
```

Call it from create, save, generate, and confirm/adopt operations. Do not call
it from read paths.

When creating a draft and no active draft exists, initialize its content and
basis from `read_head_revision` if a head exists; otherwise keep the existing
empty-first-draft behavior. A drafting Session is not modified.

- [ ] **Step 5: Derive corrected capabilities**

Use:

```python
session_is_drafting = (
    active_result is None or active_result.status == "drafting"
)
mutations_allowed = (
    not archived
    and session_is_drafting
    and authorities is not None
)
```

`start_session` remains false whenever any active Session exists.
`generate` no longer requires `active_session is None`; it uses the normal
current-draft, Provider-binding, pending-operation, and Projection checks.
Replace the reason `activeSessionPinsAuthorities` with
`finalizedChapterLocksOutline` only for a non-drafting Session.

- [ ] **Step 6: Add integration and API lifecycle coverage**

Exercise this exact sequence:

```text
adopt Outline r1
create drafting Session pinned to r1
create draft copied from r1
save changed draft
adopt Outline r2
read Session -> still pinned to r1
read Outline Head -> r2
```

Assert no Session row is updated and no WorkingDraft/Candidate is deleted.
The API test must perform mutations through Chapter Outline routes and inspect
only public method/path/status and response fields.

- [ ] **Step 7: Run Outline GREEN tests**

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_service.py backend/tests/integration/test_chapter_outline_lifecycle.py backend/tests/api/test_chapter_outline_routes.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 8: Commit**

```powershell
git add backend/services/chapter_outlines.py backend/tests/unit/test_chapter_outline_service.py backend/tests/integration/test_chapter_outline_lifecycle.py backend/tests/api/test_chapter_outline_routes.py
git diff --cached --check
git commit -m "feat: allow outline adjustment before finalization"
```

### Task 6: Stamp Candidate basis and derive staleness

**Files:**

- Modify: `backend/domain/drafts.py`
- Modify: `backend/services/chapter_sessions.py:335-390`
- Modify: `backend/routers/chapter_sessions.py:123-173`
- Test: `backend/tests/unit/test_chapter_session_service.py`
- Test: `backend/tests/integration/test_authoritative_chapter_session.py`
- Test: `backend/tests/api/test_chapter_session_routes.py`

- [ ] **Step 1: Write Candidate-basis RED tests**

Save Candidate A under Outline r1, advance Outline Head to r2, and save
Candidate B. Assert:

```python
workspace = await service.get(project_id, chapter_number)
assert workspace.candidates[0].basis_status == "stale"
assert workspace.candidates[0].outline_revision == 1
assert workspace.candidates[1].basis_status == "current"
assert workspace.candidates[1].outline_revision == 2
assert workspace.candidates[1].canon_revision == 4
assert workspace.session.chapter_outline_revision == 1
```

Add a legacy Candidate with no basis fields and assert `stale`.
Add a finalized-Session fixture and assert saving another Candidate raises
`ChapterSessionConflict`.

- [ ] **Step 2: Run Candidate RED tests**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_service.py -q
```

Expected: FAIL because Candidate provenance currently records only
`workingDraftRevision`.

- [ ] **Step 3: Extend the domain view**

Add these frozen fields to `DraftCandidateView`:

```python
outline_revision_id: str | None
outline_revision: int | None
outline_hash: str | None
planning_revision_id: str | None
planning_revision: int | None
planning_hash: str | None
canon_revision: int | None
projection_revision: int | None
projection_hash: str | None
basis_status: str
```

Do not add `locked`, `finalizable`, or a writable status field.

- [ ] **Step 4: Reuse the current Outline authority transactionally**

`ChapterSessionRepository.read_current_outline` already joins the current
Outline Head to its bound Planning revision and returns these existing keys:

```python
{
    "chapter_outline_revision_id": "outline-revision-id",
    "chapter_outline_revision": 2,
    "chapter_outline_hash": "64-lowercase-hex",
    "planning_revision_id": "planning-revision-id",
    "planning_revision": 3,
    "planning_hash": "64-lowercase-hex",
    "canon_revision": 4,
    "projection_revision": 4,
    "projection_hash": "64-lowercase-hex",
}
```

Call it with `chapter_session["chapter_num"]` from both `save_candidate` and
`_workspace`. Do not use the Session pins or the separate current Planning Head
aliases as Candidate authority. This preserves an adopted Outline when a later
Planning Head advances.

- [ ] **Step 5: Stamp provenance at Candidate save**

Before inserting the Candidate, require a current Outline authority and write:

```python
"provenance": {
    "source": "explicit-save-candidate",
    "workingDraftRevision": int(draft["revision"]),
    "outlineRevisionId": authority["chapter_outline_revision_id"],
    "outlineRevision": int(authority["chapter_outline_revision"]),
    "outlineHash": authority["chapter_outline_hash"],
    "planningRevisionId": authority["planning_revision_id"],
    "planningRevision": int(authority["planning_revision"]),
    "planningHash": authority["planning_hash"],
    "canonRevision": int(authority["canon_revision"]),
    "projectionRevision": int(authority["projection_revision"]),
    "projectionHash": authority["projection_hash"],
}
```

If no current authority exists, raise
`ChapterSessionPreconditionFailed("current Outline authority is required")`.
Before reading the WorkingDraft, apply the same effective-status rule as
`save_working_draft`: only `drafting` may save a Candidate.

- [ ] **Step 6: Derive `basis_status` without rewriting history**

In `_workspace`, read the current authority once. Map each Candidate:

```python
matches = (
    provenance.get("outlineRevisionId")
        == authority["chapter_outline_revision_id"]
    and provenance.get("outlineRevision")
        == authority["chapter_outline_revision"]
    and provenance.get("outlineHash") == authority["chapter_outline_hash"]
    and provenance.get("planningRevisionId") == authority["planning_revision_id"]
    and provenance.get("planningRevision") == authority["planning_revision"]
    and provenance.get("planningHash") == authority["planning_hash"]
)
basis_status = "current" if matches else "stale"
```

Never update old Candidate rows during reads.

- [ ] **Step 7: Expose the safe public fields**

Add the ten fields to `_public_workspace`. Do not expose raw provenance,
provider output, source payload, prompt text, DSN, or keys.

- [ ] **Step 8: Run Candidate GREEN tests**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_service.py backend/tests/integration/test_authoritative_chapter_session.py backend/tests/api/test_chapter_session_routes.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 9: Commit**

```powershell
git add backend/domain/drafts.py backend/services/chapter_sessions.py backend/routers/chapter_sessions.py backend/tests/unit/test_chapter_session_service.py backend/tests/integration/test_authoritative_chapter_session.py backend/tests/api/test_chapter_session_routes.py
git diff --cached --check
git commit -m "feat: track candidate outline basis"
```

### Task 7: Make pre-finalization Outline adjustment explicit in the UI

**Files:**

- Modify: `frontend/src/stores/planningStore.js`
- Modify: `frontend/src/application/planning/chapterOutlineController.js`
- Modify:
  `frontend/src/components/planning/ChapterOutlineWorkspace.vue`
- Modify: `frontend/src/stores/chapterSessionStore.js`
- Modify: `frontend/src/views/ChapterWriterView.vue`
- Test: `frontend/tests/unit/planningStore.test.mjs`
- Test: `frontend/tests/unit/chapterOutlineController.test.mjs`
- Test: `frontend/tests/unit/chapterOutlineWorkspace.test.mjs`
- Test: `frontend/tests/unit/chapterSessionStore.test.mjs`
- Test: `frontend/tests/unit/projectPlanningView.test.mjs`

- [ ] **Step 1: Write UI RED tests**

For a drafting Session, assert the Outline workspace renders:

```js
assert.equal(view.canAdjustOutline, true)
assert.match(rendered, /调整本章小纲/)
assert.doesNotMatch(rendered, /Session 已创建，小纲只读/)
```

For Candidate rows:

```js
assert.match(rendered, /依据当前小纲/)
assert.match(rendered, /依据旧小纲，不能定稿/)
```

Add a store test where current Outline Head is r2, `activeSession` and the
loaded workspace Session are pinned to r1, and assert
`openAuthoritative()` accepts the workspace instead of throwing authority
drift.

Assert the writer view exposes a visible router link back to the current
project's StoryBlock/Outline workspace; no `window.location`, `page.evaluate`,
or hidden route mutation.

- [ ] **Step 2: Run UI RED tests**

```powershell
node --test frontend/tests/unit/planningStore.test.mjs frontend/tests/unit/chapterOutlineController.test.mjs frontend/tests/unit/chapterOutlineWorkspace.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/projectPlanningView.test.mjs
```

Expected: FAIL because the active Session currently suppresses Outline
mutations and Candidate basis is not rendered.

- [ ] **Step 3: Accept immutable Session entry provenance**

Change `workspaceMatchesAuthority` so an existing active Session is validated
against `current.activeSession`, while a newly created Session is validated
against the current Planning and Outline Head:

```js
const expectedPlanningRevisionId = (
  active?.planningRevisionId ?? planning?.planningRevisionId
)
const expectedPlanningRevision = (
  active?.planningRevision ?? planning?.revision
)
const expectedPlanningHash = (
  active?.planningHash ?? planning?.contentHash
)
const expectedOutlineRevisionId = (
  active?.outlineRevisionId ?? outline?.outlineRevisionId
)
const expectedOutlineRevision = (
  active?.outlineRevision ?? outline?.revision
)
const expectedOutlineHash = (
  active?.outlineHash ?? outline?.contentHash
)
```

Compare the loaded Session to those six values. Do not require Session pins to
equal the current Outline Head when `activeSession` exists.

- [ ] **Step 4: Consume server capabilities directly**

Remove client logic that equates `activeSession` with read-only. Use:

```js
const canAdjustOutline = computed(() => (
  state.value?.activeSession?.status === 'drafting'
  && (
    state.value?.capabilities?.createDraft === true
    || state.value?.capabilities?.editDraft === true
  )
))
```

The actual write buttons still bind to their exact server capability. Do not
invent a client finalization state.

- [ ] **Step 5: Present Outline adoption as current working authority**

Change user-facing “确认后永久不可修改” Outline copy to:

```text
采用后作为当前写作依据；正文定稿前仍可调整。
```

Use “采用小纲” / “更新当前小纲” for the existing confirm route. Keep the API
method name unchanged in this phase to avoid a compatibility-only rename.

- [ ] **Step 6: Parse and render Candidate basis**

Validate `basisStatus` as `current` or `stale` when accepting workspace JSON.
Render current/stale badges and preserve every Candidate in chronological
order. Do not automatically create a replacement Candidate after an Outline
change; the author must explicitly save one from the current WorkingDraft.

- [ ] **Step 7: Run UI GREEN tests**

Run the same `node --test` command.

Expected: all selected tests PASS.

- [ ] **Step 8: Commit**

```powershell
git add frontend/src/stores/planningStore.js frontend/src/application/planning/chapterOutlineController.js frontend/src/components/planning/ChapterOutlineWorkspace.vue frontend/src/stores/chapterSessionStore.js frontend/src/views/ChapterWriterView.vue frontend/tests/unit/planningStore.test.mjs frontend/tests/unit/chapterOutlineController.test.mjs frontend/tests/unit/chapterOutlineWorkspace.test.mjs frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/projectPlanningView.test.mjs
git diff --cached --check
git commit -m "feat: support outline adjustment before finalization"
```

### Task 8: Correct the formal Phase 3 UI-only browser acceptance

**Files:**

- Modify: `frontend/e2e/phase3-story-planning.spec.ts`
- Modify only if required by an observed runner defect:
  `frontend/e2e/runtime-observer.mjs`
- Modify only if required by a tested runner contract:
  `frontend/e2e/run-phase3.mjs`
- Test: `scripts/tests/phase3Suite.test.mjs`
- Test: `scripts/tests/runtime-observer.test.mjs`

- [ ] **Step 1: Replace obsolete scenario expectations**

Keep the existing fixtures, locators, and UI-only constraints, but replace the
old A->B->A and automatic supersession assertions with:

```text
@baseline-lock
  select Seed A
  confirm Contract
  confirm Bible
  revisit Seed and Bible pages through visible navigation
  assert replacement controls are absent

@outline-adjustment-before-finalization
  adopt Outline r1
  enter writer and save Candidate A
  return through visible navigation
  adjust and adopt Outline r2
  return to writer
  assert prose and Candidate A remain
  assert Candidate A is stale
  explicitly save Candidate B
  assert Candidate B is current
```

Do not add `page.request`, `page.route`, browser `fetch`, axios, direct database
writes from the spec, or a shadow product chain.

- [ ] **Step 2: Keep the runner contract tests RED-first**

If the scenario tag/name set changes, first update
`scripts/tests/phase3Suite.test.mjs` to assert the exact new scenarios and run:

```powershell
node --test scripts/tests/phase3Suite.test.mjs scripts/tests/runtime-observer.test.mjs
```

Expected: FAIL until the spec and runner metadata agree.

- [ ] **Step 3: Implement only the scenario change**

Use existing safe diagnostics. Failure output may contain loopback
method/path/status and fixed category counts only. Never print request body,
response body, Provider text, DSN, environment values, or secrets.

- [ ] **Step 4: Run the runner support tests**

```powershell
node --test scripts/tests/phase3Suite.test.mjs scripts/tests/runtime-observer.test.mjs scripts/tests/run-tests.test.mjs
```

Expected: all selected tests PASS.

- [ ] **Step 5: Run one focused browser scenario**

```powershell
$env:PHASE3_GREP='@outline-adjustment-before-finalization'
npm run test:browser:phase3
Remove-Item Env:PHASE3_GREP
```

Expected: the focused scenario passes; runner ledger reports zero owned
process, port, temp-root, Vite `deps_temp`, and test-database residue.

- [ ] **Step 6: Commit the formal gate implementation**

Stage the complete Task5 runner file set plus the corrected spec, because these
files started as one uncommitted formal-gate work item:

```powershell
git add frontend/e2e/runtime-observer.mjs frontend/e2e/phase3-story-planning.spec.ts frontend/e2e/playwright.phase3.config.ts frontend/e2e/run-phase3.mjs frontend/package.json package.json scripts/run-tests.mjs scripts/tests/run-tests.test.mjs scripts/tests/runtime-observer.test.mjs scripts/tests/phase3Suite.test.mjs
git diff --cached --check
git commit -m "test: add phase 3 immutable boundary gate"
```

### Task 9: Fresh verification, review, and acceptance evidence

**Files:**

- Create:
  `docs/acceptance/2026-07-31-phase-3-immutable-boundary-alignment.md`

- [ ] **Step 1: Inspect the final diff before expensive gates**

```powershell
git status --short --branch
git diff --check
git log --oneline -12
```

Expected: only the planned acceptance report may be untracked; no unrelated
worktree path appears.

- [ ] **Step 2: Run fresh unit and focused backend tests**

```powershell
npm test
python -m pytest backend/tests/unit/test_seed_service.py backend/tests/unit/test_contract_service.py backend/tests/unit/test_bible_service.py backend/tests/unit/test_chapter_outline_repository.py backend/tests/unit/test_chapter_outline_service.py backend/tests/unit/test_chapter_session_repository.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_seed_routes.py backend/tests/api/test_bible_routes.py backend/tests/api/test_chapter_outline_routes.py backend/tests/api/test_chapter_session_routes.py -q
```

Expected: exit 0 and all tests PASS.

- [ ] **Step 3: Run integration and build gates serially**

```powershell
npm run test:integration
npm run build
```

Expected: both commands exit 0. Do not overlap MySQL, build, or browser gates.

- [ ] **Step 4: Run the complete formal Phase 3 browser gate once**

```powershell
npm run test:browser:phase3
```

Expected: every configured Phase 3 scenario passes and the final resource
ledger is zero. Do not loop on failure; use `systematic-debugging`, form one
root-cause hypothesis, and rerun only the smallest reproducer.

- [ ] **Step 5: Audit owned residue**

Check only runner-owned resources:

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'run-phase3|playwright.phase3|novel_creator_test_'
} | Select-Object ProcessId,Name,CommandLine
Get-NetTCPConnection -State Listen | Where-Object {
  $_.LocalAddress -in @('127.0.0.1','::1')
} | Select-Object LocalAddress,LocalPort,OwningProcess
Get-ChildItem $env:TEMP -Force | Where-Object {
  $_.Name -match 'phase3|novel-creator'
} | Select-Object FullName
Get-ChildItem frontend/node_modules/.vite -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like 'deps_temp_*' } |
  Select-Object FullName
```

Query only schema names matching `novel_creator_test_%` through the repository's
existing test-database audit helper. Do not read product schemas and do not stop
normal `mysqld`.

Expected: no proven runner-owned process, port, temp root, Vite cache, or test
database remains.

- [ ] **Step 6: Perform serial specification and quality review**

First run a specification review against
`2026-07-31-immutable-boundaries-revision-design.md` until
Critical/Important/Minor is `0/0/0`. Then, and only then, run a separate code
quality review until `0/0/0`. Reviewers must inspect the actual diff and fresh
test summaries, not only commit messages.

- [ ] **Step 7: Write the acceptance report**

Record:

```markdown
# Phase 3 Immutable Boundary Alignment Acceptance

- Branch and exact HEAD
- Seed second-selection refusal result
- Contract/Bible post-confirmation refusal result
- Drafting-Session Outline r1 -> r2 result
- Session entry provenance remains r1
- Candidate A stale / Candidate B current result
- Unit, integration, build, and browser passed/failed/skipped counts
- Specification review: Critical/Important/Minor = 0/0/0
- Quality review: Critical/Important/Minor = 0/0/0
- Owned process/port/temp/Vite/test-DB residue = 0
- Phase 5 deferred work: finalization atomic lock and Canon realization
```

Do not include request/response bodies, Provider output, DSNs, keys, or large
logs.

- [ ] **Step 8: Commit acceptance evidence**

```powershell
git add docs/acceptance/2026-07-31-phase-3-immutable-boundary-alignment.md
git diff --cached --check
git commit -m "docs: accept phase 3 immutable boundaries"
```

- [ ] **Step 9: Final clean-state verification**

```powershell
git status --short --branch
git diff --check
git rev-parse HEAD
```

Expected: branch is clean and the reported HEAD is the acceptance commit.

## Phase 5 follow-on boundary

After this plan passes, write a separate plan for the finalization transaction.
That plan must validate `Candidate.basisStatus == current` server-side, extract
one typed `FinalizationChangeSet`, obtain one author confirmation, and in one
transaction freeze Outline and prose, append Canon, project read-only setting/
memory/arc/plot projections, and advance typed Planning realization. It must
also introduce the final-chapter guard that makes the Outline operations in
Task 5 permanently unavailable. None of those writes belong in Phase 3.
