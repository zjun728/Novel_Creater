# Phase 2C Story Engine and Creation Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `subagent-driven-development`, `test-driven-development`, and
> `verification-before-completion`.

**Goal:** Deliver generation/manual entry of story engines and an immutable
creation contract that freezes the exact seed generation, styles, experience
cards, and necessary corpus fragments.

**Architecture:** Existing transactional engine/contract services remain the
base, but every result is fenced by `selection_revision`. Deterministic rules
only filter impossible assets; the `seed` model may rank the remainder. Low
confidence returns no recommendation. Contract confirmation is one idempotent
transaction over a complete preview manifest.

**Depends on:** Phase 2A assets/bindings and Phase 2B selection generation.

---

## Task 1: Fence story-engine batches by seed-selection generation

**Files:**

- Modify: `backend/domain/story_engines.py`
- Modify: `backend/repositories/story_engines.py`
- Modify: `backend/services/story_engines.py`
- Modify: `backend/gateways/story_engine_provider.py`
- Modify: `backend/routers/story_engines.py`
- Modify: `backend/tests/unit/test_story_engine_domain.py`
- Modify: `backend/tests/unit/test_story_engine_service.py`
- Modify: `backend/tests/unit/test_story_engine_gateway.py`
- Modify: `backend/tests/api/test_story_engine_routes.py`
- Modify: `backend/tests/integration/test_story_engine_batches.py`

- [ ] **Step 1: Write generation-drift tests**

Every manual/provider batch freezes:

```text
projectId
selectionRevision
seedId / seedRevisionId / seedHash
bindingRevisionId / bindingHash (provider only)
requestHash / idempotencyKey
```

Reselecting the same seed revision at a new selection generation makes all old
batches superseded. Retry of the original request remains readable as history
but cannot be selected for the new contract.

- [ ] **Step 2: Run red**

```powershell
python -m pytest backend/tests/unit/test_story_engine_domain.py backend/tests/unit/test_story_engine_service.py backend/tests/unit/test_story_engine_gateway.py backend/tests/api/test_story_engine_routes.py backend/tests/integration/test_story_engine_batches.py -q
```

- [ ] **Step 3: Implement and preserve the good gateway boundary**

Keep provider calls outside transactions, strict three-option structured output,
idempotency, request hash, uncertainty handling, no raw response storage, and
secret scanning. Add selection-generation validation before reservation and
before publication.

Manual entry accepts the same typed fields as a generated option and never
requires a Ready model.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_story_engine_domain.py backend/tests/unit/test_story_engine_service.py backend/tests/unit/test_story_engine_gateway.py backend/tests/api/test_story_engine_routes.py backend/tests/integration/test_story_engine_batches.py -q
git add backend
git commit -m "feat: fence story engines by seed selection"
```

## Task 2: Recommend eligible assets and bounded corpus fragments

**Files:**

- Modify: `backend/domain/asset_recommendations.py`
- Create: `backend/domain/corpus_recommendations.py`
- Modify: `backend/services/assets.py`
- Create: `backend/services/corpus_recommendations.py`
- Modify: `backend/repositories/corpus.py`
- Create: `backend/gateways/asset_recommendation_provider.py`
- Create: `backend/prompts/asset_recommendation.py`
- Modify: `backend/routers/assets.py`
- Modify: `backend/tests/unit/test_asset_recommendation.py`
- Create: `backend/tests/unit/test_asset_recommendation_gateway.py`
- Create: `backend/tests/unit/test_asset_recommendation_service.py`
- Create: `backend/tests/unit/test_corpus_recommendation_service.py`
- Modify: `backend/tests/api/test_asset_routes.py`

- [ ] **Step 1: Write failure-first recommendation tests**

Prove:

- deterministic filter excludes wrong genre/stage/status/prohibited direction;
- deterministic asset eligibility reads the exact version/hash of the Phase 2A
  recommendation taxonomy and never infers typed tags from free text;
- no remaining candidate returns an empty recommendation;
- no `default-rank`, forced count, or auto-selection exists;
- no Ready `seed` binding returns `rankingUnavailable` plus full-browse access;
- model ranking only receives eligible bounded summaries plus current
  seed/engine/style facts;
- low confidence or invalid output returns empty recommendations with a public
  reason;
- accepted output includes stable asset revision IDs, short reasons, confidence,
  and a frozen input manifest;
- corpus retrieval considers only active/readable revisions, searches source
  tags, titles, chapter headings, and normalized Unicode n-gram overlap, then
  selects at most 20 candidate fragments;
- each corpus candidate sent to the model contains at most 300 characters and
  the complete corpus candidate budget is at most 4,000 characters;
- accepted corpus recommendations include source ID/revision/hash, chapter and
  fragment ID/hash, exact suggested range, use, short reason, and confidence;
- missing/low-confidence corpus matches return an empty recommendation and full
  manual browser access;
- response never includes large examples, unbounded corpus text, storage path,
  or raw Provider output.

- [ ] **Step 2: Run red**

```powershell
python -m pytest backend/tests/unit/test_asset_recommendation.py backend/tests/unit/test_asset_recommendation_gateway.py backend/tests/unit/test_asset_recommendation_service.py backend/tests/unit/test_corpus_recommendation_service.py backend/tests/api/test_asset_routes.py -q
```

- [ ] **Step 3: Implement the two-stage service**

Perform deterministic eligibility and bounded corpus candidate retrieval
in-process. Use the backend `seed` binding for one strict ranking call over the
eligible asset summaries and bounded fragment candidates. Never silently fall
back to a fabricated deterministic order after a model failure.
Recommendations are advisory and are persisted as an immutable attempt with
taxonomy, selection, engine, style, corpus candidate, and binding manifest
hashes. They are not copied into the contract draft until the author explicitly
selects them.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_asset_recommendation.py backend/tests/unit/test_asset_recommendation_gateway.py backend/tests/unit/test_asset_recommendation_service.py backend/tests/unit/test_corpus_recommendation_service.py backend/tests/api/test_asset_routes.py -q
git add backend
git commit -m "feat: rank eligible creative assets"
```

## Task 3: Freeze a complete generation-aware contract

**Files:**

- Modify: `backend/domain/contracts.py`
- Modify: `backend/repositories/contracts.py`
- Delete: `backend/services/contracts.py`
- Create: `backend/services/contracts/__init__.py`
- Create: `backend/services/contracts/drafts.py`
- Create: `backend/services/contracts/preview.py`
- Create: `backend/services/contracts/confirmation.py`
- Create: `backend/services/contracts/history.py`
- Modify: `backend/routers/contracts.py`
- Modify: `backend/tests/unit/test_contract_domain.py`
- Modify: `backend/tests/unit/test_contract_service.py`
- Modify: `backend/tests/api/test_contract_routes.py`
- Modify: `backend/tests/integration/test_contract_drafts.py`
- Modify: `backend/tests/integration/test_contract_confirmation.py`

- [ ] **Step 1: Define the complete contract payload**

The draft/confirmed contract contains:

```text
selectionRevision
seed revision/hash
story-engine option/hash
primary style revision/hash
optional secondary style revision/hash
ordered experience-card revisions/hashes
ordered corpus source revision + fragment/range manifests
target total words and expected volume/chapter capacity
chapter word-range preference
prohibited directions
free author notes
```

Manual confirmation does not require all eight model bindings Ready. Provider
readiness is checked only for the AI action being requested. Confirmation still
records the current binding revision/hash as reproducibility context if one
exists.

- [ ] **Step 2: Write red drift/atomicity tests**

Cover selection, seed, engine, asset head, corpus content/range, binding, draft
base, and contract-head drift. The preview reports all drift at once without
mutating the draft. Confirmation with a stable manifest:

- reserves idempotently;
- inserts creation/style contract and every reference;
- CAS-updates head;
- clears only the confirmed draft;
- commits once or rolls back all rows;
- returns the same result on retry.

Fragment manifests reject unknown IDs, hash mismatch, invalid ranges, duplicate
order, excessive total excerpt budget, and archived/deleted non-current
versions unless the draft explicitly pins an existing readable history version.

- [ ] **Step 3: Run red**

```powershell
python -m pytest backend/tests/unit/test_contract_domain.py backend/tests/unit/test_contract_service.py backend/tests/api/test_contract_routes.py backend/tests/integration/test_contract_drafts.py backend/tests/integration/test_contract_confirmation.py -q
```

- [ ] **Step 4: Implement revision-aware contract service**

Replace the existing oversized module with the listed package. Move its public
imports through `backend/services/contracts/__init__.py`, split draft, preview,
confirmation, and history responsibilities, and delete the old module in the
same commit. Do not keep a second implementation or a compatibility wrapper.

Active head readiness compares the current selection generation and every frozen
upstream identity/hash. Old revisions are returned with explicit
`supersededReasons`.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_contract_domain.py backend/tests/unit/test_contract_service.py backend/tests/api/test_contract_routes.py backend/tests/integration/test_contract_drafts.py backend/tests/integration/test_contract_confirmation.py -q
git add backend
git commit -m "feat: freeze complete creation contracts"
```

## Task 4: Add backend style trial as a non-contract attempt

**Files:**

- Create: `backend/domain/style_trials.py`
- Create: `backend/gateways/style_trial_provider.py`
- Create: `backend/prompts/style_trial.py`
- Create: `backend/services/style_trials.py`
- Create: `backend/routers/style_trials.py`
- Modify: `backend/main.py`
- Create: `backend/tests/unit/test_style_trial_prompt.py`
- Create: `backend/tests/unit/test_style_trial_service.py`
- Create: `backend/tests/api/test_style_trial_routes.py`
- Delete: `frontend/src/stores/styleTrialStore.js`
- Delete: `frontend/src/prompts/styleTrial.js`

- [ ] **Step 1: Write bounded attempt tests**

Trial input freezes current selection, engine, primary/secondary style revisions,
`seed` binding revision, policy version, and a short author scenario. Output is
a bounded temporary sample with actual Provider/model identity and attempt
status. It is not a contract, candidate, or Canon fact and is never auto-selected.

Provider failure yields one failed attempt and no hidden repair/retry.

- [ ] **Step 2: Run red**

```powershell
python -m pytest backend/tests/unit/test_style_trial_prompt.py backend/tests/unit/test_style_trial_service.py backend/tests/api/test_style_trial_routes.py -q
```

- [ ] **Step 3: Implement backend-only execution**

Resolve the `seed` binding server-side. Store only the validated output and safe
manifest. Do not persist raw Provider response, prompts containing secrets, or
large corpus excerpts.

- [ ] **Step 4: Remove the frontend direct-model/localStorage path and commit**

```powershell
python -m pytest backend/tests/unit/test_style_trial_prompt.py backend/tests/unit/test_style_trial_service.py backend/tests/api/test_style_trial_routes.py -q
git add backend frontend/src/stores/styleTrialStore.js frontend/src/prompts/styleTrial.js
git commit -m "feat: move style trials behind backend gateway"
```

## Task 5: Rebuild the formal Contract page

**Files:**

- Create: `frontend/src/views/ProjectContractView.vue`
- Modify: `frontend/src/components/project/CreationContractWizard.vue`
- Delete: `frontend/src/components/project/contract/SeedSelectionStep.vue`
- Modify: `frontend/src/components/project/contract/StoryEngineStep.vue`
- Modify: `frontend/src/components/project/contract/StyleSelectionStep.vue`
- Modify: `frontend/src/components/project/contract/AssetScopeStep.vue`
- Modify: `frontend/src/components/project/contract/ContractPreviewStep.vue`
- Create: `frontend/src/components/project/contract/CapacityStep.vue`
- Create: `frontend/src/components/project/contract/ContractHistoryDrawer.vue`
- Create: `frontend/src/components/project/contract/StyleTrialPanel.vue`
- Modify: `frontend/src/stores/creationContractStore.js`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: `frontend/tests/unit/creationContractStore.test.mjs`
- Create: `frontend/tests/unit/projectContractView.test.mjs`
- Modify: `frontend/tests/unit/projectRoutes.test.mjs`
- Modify: `frontend/tests/unit/productShell.test.mjs`

- [ ] **Step 1: Write formal-flow tests**

The page requires an active seed selection. It displays that selection read-only
and offers Go to Seeds when missing. Its flow is:

1. choose/generated/manual story engine;
2. choose primary/secondary style, read examples, optionally run trial;
3. review recommendations and explicitly choose cards/corpus fragments;
4. enter length/capacity/prohibited directions;
5. preview all changes and confirm once.

Test explicit Save Draft, navigation guard for unsaved local changes, module-only
operation overlay, drift recovery, immutable confirmed state, New Revision from
history, archived read-only, and correct focus/live-region behavior.

- [ ] **Step 2: Run red**

```powershell
node --test frontend/tests/unit/creationContractStore.test.mjs frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
```

- [ ] **Step 3: Remove raw JSON and repeated seed selection**

`StoryEngineStep` uses ordinary named fields for manual input. Remove advanced
JSON editing, hard-coded genre/channel assumptions, and the seed-selection step.
The route is `/projects/:projectId/contract`.

Recommendations may be empty; full asset browser remains available. No
recommendation is checked automatically. Corpus selection is fragment/range
level with a visible bounded-preview budget.

- [ ] **Step 4: Implement history and future-only revision semantics**

Confirmed revision is read-only. “Adjust future design” clones one historical
revision into a new draft under the current selection generation. Old versions
show their pinned assets and superseded reasons. No delete/reset controls exist.

- [ ] **Step 5: Run tests and commit**

```powershell
node --test frontend/tests/unit/creationContractStore.test.mjs frontend/tests/unit/projectContractView.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
npm --prefix frontend run build
git add frontend
git commit -m "feat: add formal creation contract workspace"
```

## Task 6: Phase 2C browser acceptance

**Files:**

- Create: `frontend/e2e/phase2c-contract.spec.ts`
- Create: `frontend/e2e/run-phase2c.mjs`
- Create: `frontend/e2e/support/product-runner.mjs`
- Modify: `frontend/e2e/run-product-shell.mjs`
- Modify: `frontend/e2e/run-phase2a.mjs`
- Modify: `frontend/e2e/run-phase2b.mjs`
- Create: `frontend/playwright.phase2c.config.ts`
- Modify: `frontend/package.json`
- Modify: `package.json`
- Modify: `scripts/run-tests.mjs`
- Create: `scripts/tests/phase2cSuite.test.mjs`
- Modify: `scripts/tests/run-tests.test.mjs`
- Modify: `scripts/tests/browser-runner.test.mjs`
- Modify: `scripts/tests/server-log-observer.test.mjs`
- Modify: `scripts/tests/milestone1-browser-contract.test.mjs`
- Delete: `scripts/tests/milestone2-browser-contract.test.mjs`
- Delete: `scripts/tests/scan-m2-artifacts.test.mjs`
- Delete: `frontend/e2e/m2-settings-assets-corpus.spec.ts`
- Delete: `frontend/e2e/m2-wizard-manual.spec.ts`
- Delete: `frontend/e2e/m2-wizard-recovery.spec.ts`
- Delete: `frontend/e2e/m2-foundation-regression.spec.ts`
- Delete: `frontend/e2e/run-milestone2.mjs`
- Delete: `frontend/playwright.m2.config.ts`
- Create: `docs/acceptance/2026-07-18-phase-2c-contract.md`

- [ ] **Step 1: Write a manual no-model browser path**

Against disposable MySQL, select a seed, manually enter an engine, select exact
style/card/corpus fragments, enter capacity/prohibitions, preview, confirm, and
inspect history. This proves manual creation does not depend on Provider Ready.

- [ ] **Step 2: Write an injected-gateway path**

Generate exactly three options, run one style trial, return a low-confidence
empty asset recommendation, browse/select manually, and confirm. Simulate
selection drift and prove the old contract cannot reactivate.

- [ ] **Step 3: Remove old M2 browser authority**

First extract random disposable DB ownership, reserved ports, child lifecycle,
safe log observation, sentinel scanning, and cleanup into
`frontend/e2e/support/product-runner.mjs`. Make product-shell and Phase 2A/2B/2C
runners import the neutral support module and update its behavioral tests.

Then delete the listed M2 runner/spec/config, old M2 artifact-contract tests, and
package/script aliases. Retain no import of `run-milestone2.mjs` and no alias
that claims the retired Settings/JSON wizard is Phase 2 acceptance. Set the
temporary root/frontend default browser command to Phase 2C; Phase 2D will
replace it with the complete Phase 2 runner.

- [ ] **Step 4: Run and commit**

```powershell
npm run test:browser:phase2c
npm test
npm run test:integration
npm run build
git diff --check
```

After independent reviews and fixes:

```powershell
git add frontend/e2e frontend/playwright.phase2c.config.ts frontend/package.json package.json scripts docs/acceptance/2026-07-18-phase-2c-contract.md
git commit -m "test: accept creation contract workflow"
```
