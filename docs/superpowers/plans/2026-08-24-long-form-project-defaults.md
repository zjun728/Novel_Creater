# Long-Form Project Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make newly created projects default to 2,400,000 words and 720 chapters without changing existing projects or explicit user inputs.

**Architecture:** Keep `CreateProject` as the backend authority for new-project defaults. Mirror only the missing-project fallback in `StoryEngineStep.vue`; do not add a shared configuration layer, migration, or new UI.

**Tech Stack:** Python 3, Pydantic, FastAPI, pytest, Vue 3, Node test runner.

---

### Task 1: Lock the backend default contract with failing tests

**Files:**
- Modify: `backend/tests/unit/test_project_creation.py:120-195`
- Modify: `backend/tests/api/test_product_routes.py:295-305`

- [ ] **Step 1: Update the unit expectations before implementation**

Change the title-only command, persisted command, and returned result assertions to:

```python
"target_words": 2_400_000,
"target_chapters": 720,
```

- [ ] **Step 2: Update the API expectation before implementation**

Assert both public response fields:

```python
assert created.json()["targetWords"] == 2_400_000
assert created.json()["targetChapters"] == 720
```

- [ ] **Step 3: Run the focused backend tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_creation.py backend/tests/api/test_product_routes.py -q
```

Expected: failures show the old defaults `100000` and `100`.

### Task 2: Implement the backend authority

**Files:**
- Modify: `backend/services/project_lifecycle.py:24-32`

- [ ] **Step 1: Change only the Pydantic command defaults**

```python
class CreateProject(BaseModel):
    # existing configuration and fields stay unchanged
    target_words: int = 2_400_000
    target_chapters: int = 720
```

- [ ] **Step 2: Run the focused backend tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/unit/test_project_creation.py backend/tests/api/test_product_routes.py -q
```

Expected: all selected tests pass.

### Task 3: Lock and implement the frontend fallback

**Files:**
- Modify: `frontend/tests/unit/projectContractView.test.mjs`
- Modify: `frontend/src/components/project/contract/StoryEngineStep.vue:195-207`

- [ ] **Step 1: Add a failing source-contract test**

Add:

```javascript
test('story engine missing-project capacity fallback uses the long-form default', async () => {
  const component = await source('src/components/project/contract/StoryEngineStep.vue')
  assert.match(component, /projectWords[\s\S]*?2_400_000/u)
  assert.doesNotMatch(component, /projectWords[\s\S]*?:\s*100_000/u)
})
```

- [ ] **Step 2: Run the focused frontend test and verify RED**

Run:

```powershell
node --test frontend/tests/unit/projectContractView.test.mjs
```

Expected: the new long-form fallback assertion fails against `100_000`.

- [ ] **Step 3: Change the missing-project fallback**

In `provisionalCapacity()`, preserve the draft and project precedence and change only the final fallback:

```javascript
const target = Number(existing?.targetTotalWords)
  || (Number.isInteger(projectWords) && projectWords > 0 ? projectWords : 2_400_000)
```

- [ ] **Step 4: Run the focused frontend test and verify GREEN**

Run:

```powershell
node --test frontend/tests/unit/projectContractView.test.mjs
```

Expected: all tests in the file pass.

### Task 4: Full verification and delivery

**Files:**
- Verify all modified code, tests, spec, and this plan.

- [ ] **Step 1: Run repository tests**

```powershell
npm test
```

Expected: backend, scripts, and frontend unit suites pass.

- [ ] **Step 2: Run the production build**

```powershell
npm run build
```

Expected: Vite production build completes successfully.

- [ ] **Step 3: Check scope and whitespace**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only the planned tracked files plus the pre-existing untracked `.review-worktrees/` appear.

- [ ] **Step 4: Commit and push**

```powershell
git add backend/services/project_lifecycle.py backend/tests/unit/test_project_creation.py backend/tests/api/test_product_routes.py frontend/src/components/project/contract/StoryEngineStep.vue frontend/tests/unit/projectContractView.test.mjs docs/superpowers/plans/2026-08-24-long-form-project-defaults.md
git commit -m "feat: default new projects to long-form scale"
git push origin main
```

Expected: `main` and `origin/main` point to the new implementation commit; `.review-worktrees/` remains untouched.
