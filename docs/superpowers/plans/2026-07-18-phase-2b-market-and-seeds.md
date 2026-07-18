# Phase 2B Market Evidence and Seed Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `subagent-driven-development`; use `systematic-debugging` for adapter/parser
> failures and `test-driven-development` for every product behavior.

**Goal:** Replace the unreachable fake market chain with evidence-backed source
snapshots and deliver an independent seed module whose active-selection
generation cannot revive an older downstream chain.

**Architecture:** Source adapters collect only public, unauthenticated ranking
facts into immutable snapshots. A scheduler leases due sources without holding
network calls inside transactions. Market analysis reads a frozen snapshot
manifest. Seeds store explicit provenance, immutable revisions, and one
monotonic project selection generation.

**Depends on:** Phase 2A exact schema and route shell.

---

## Task 1: Replace the old market router with source adapters

**Files:**

- Delete: `backend/routers/market.py`
- Create: `backend/domain/market.py`
- Create: `backend/domain/market_sources.py`
- Create: `backend/repositories/market.py`
- Create: `backend/services/market_sources.py`
- Create: `backend/services/market_snapshots.py`
- Create: `backend/gateways/market_sources/base.py`
- Create: `backend/gateways/market_sources/qidian_public_rank.py`
- Create: `backend/gateways/market_sources/qq_reading_public_rank.py`
- Create: `backend/gateways/market_sources/manual_snapshot.py`
- Create: `backend/routers/market_sources.py`
- Create: `backend/assets/market-sources-v1.0.0/manifest.json`
- Create: `backend/assets/market-sources-v1.0.0/sources.json`
- Create: `backend/scripts/seed_market_sources.py`
- Modify: `backend/main.py`
- Create: `backend/tests/fixtures/market/qidian_newsign.html`
- Create: `backend/tests/fixtures/market/qq_male_popular.html`
- Create: `backend/tests/unit/test_market_source_adapters.py`
- Create: `backend/tests/unit/test_market_source_manifest.py`
- Create: `backend/tests/unit/test_seed_market_sources.py`
- Create: `backend/tests/unit/test_market_snapshot_service.py`
- Create: `backend/tests/api/test_market_source_routes.py`
- Create: `backend/tests/integration/test_market_snapshots.py`

- [ ] **Step 1: Write closed adapter contracts**

Define strict normalized values:

```python
MarketEntry(
    rank=1,
    title="...",
    author="...",
    category="...",
    work_url="https://...",
    public_metrics={},
)
MarketSnapshot(
    platform="qidian",
    ranking_name="newsign",
    category="male",
    captured_at=...,
    source_url="https://www.qidian.com/rank/newsign/",
    entries=(...),
)
```

Reject duplicate ranks, blank identity fields, non-HTTP(S) work/source URLs,
redirects off the adapter allowlist, oversized bodies, unbounded entry counts,
login/CAPTCHA/interstitial pages, and unknown HTML. Never substitute fallback
books or partially parsed data.

Before transport is called, the adapter also requires a versioned source-policy
record with:

```text
status = verified_public | manual_only | disabled
checkedAt
evidenceURL
evidenceHash
allowedOrigins / pathPrefixes
requestIntervalSeconds
policyVersion
```

Only `verified_public` permits automatic network access. `manual_only`,
`disabled`, missing, expired, or hash-invalid policy fails before opening a
request. The author cannot override this boundary in the UI.

- [ ] **Step 2: Run red**

```powershell
python -m pytest backend/tests/unit/test_market_source_manifest.py backend/tests/unit/test_seed_market_sources.py backend/tests/unit/test_market_source_adapters.py backend/tests/unit/test_market_snapshot_service.py backend/tests/api/test_market_source_routes.py backend/tests/integration/test_market_snapshots.py -q
```

- [ ] **Step 3: Implement public adapters**

Adapters use injected HTTP transport, bounded timeout/body size, redirect
rejection, and fixed user-visible failure codes. Initial automatic URLs:

```text
https://www.qidian.com/rank/newsign/
https://book.qq.com/book-rank
```

The source registry stores adapter key and public configuration, never cookies,
headers, credentials, or arbitrary executable URLs. The manual adapter accepts a
strict JSON snapshot that follows the same normalized contract.

Seed the versioned built-in source definitions only through the explicit
`seed_market_sources` command used by database initialization/reset preparation;
normal startup does not ensure or mutate source rows. A source lacking current
policy evidence is shipped as `manual_only`, so manual public-snapshot import
works while automatic refresh remains honestly unavailable.

- [ ] **Step 4: Persist immutable source snapshots**

For each refresh:

1. reserve an attempt and copy source configuration;
2. fetch/parse outside a database transaction;
3. calculate canonical content hash;
4. transactionally insert or reuse the immutable snapshot and entries;
5. update last-success/head only after complete publication;
6. on failure retain last success and store only fixed public code/message.

Expose source inventory, public status, snapshot history, snapshot detail, manual
import, and explicit refresh routes. Do not expose raw HTML or exceptions.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_market_source_manifest.py backend/tests/unit/test_seed_market_sources.py backend/tests/unit/test_market_source_adapters.py backend/tests/unit/test_market_snapshot_service.py backend/tests/api/test_market_source_routes.py backend/tests/integration/test_market_snapshots.py -q
git add backend
git commit -m "feat: add evidence-backed market sources"
```

## Task 2: Add lease-based scheduled refresh

**Files:**

- Create: `backend/services/market_scheduler.py`
- Create: `backend/runtime/market_scheduler.py`
- Modify: `backend/main.py`
- Create: `backend/tests/unit/test_market_scheduler.py`
- Create: `backend/tests/integration/test_market_scheduler_leases.py`
- Modify: `backend/tests/api/test_market_source_routes.py`

- [ ] **Step 1: Write timing and lease tests**

Use an injected clock and executor. Cover:

- disabled/no-due source performs no fetch;
- one worker atomically acquires a bounded lease;
- another worker skips a live lease;
- network fetch occurs after the reservation transaction closes;
- success advances `next_run_at` from completion time;
- failure records a bounded backoff and retains last success;
- expired lease is recoverable;
- shutdown cancels future work and awaits in-flight task cleanup;
- scheduler output contains source display ID/status only.
- schedule update uses source `expectedRevision` and request idempotency;
- `manual_only` or `disabled` sources reject schedule enable before mutation.

- [ ] **Step 2: Run red**

```powershell
python -m pytest backend/tests/unit/test_market_scheduler.py backend/tests/integration/test_market_scheduler_leases.py -q
```

- [ ] **Step 3: Implement the local scheduler**

Start one optional background loop from FastAPI lifespan after schema
verification. Poll no more often than once per minute. It must not execute DDL,
call a model, or delay server readiness. Add application settings for enable,
interval, and next-run display; automatic refresh is off until a source schedule
is explicitly enabled.

Expose:

```text
PUT /api/market-sources/:sourceId/schedule
{
  "expectedRevision": 3,
  "enabled": true,
  "intervalMinutes": 360,
  "idempotencyKey": "..."
}
```

The response returns only public source/schedule revision, enabled state,
interval, next-run time, policy status, and recovery reason.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_market_scheduler.py backend/tests/integration/test_market_scheduler_leases.py backend/tests/unit/test_schema_version.py -q
git add backend
git commit -m "feat: schedule bounded market refresh"
```

## Task 3: Add frozen market analysis without fake facts

**Files:**

- Create: `backend/domain/market_analysis.py`
- Create: `backend/gateways/market_analysis_provider.py`
- Create: `backend/prompts/market_analysis.py`
- Create: `backend/services/market_analysis.py`
- Modify: `backend/repositories/market.py`
- Modify: `backend/routers/market_sources.py`
- Create: `backend/tests/unit/test_market_analysis_prompt.py`
- Create: `backend/tests/unit/test_market_analysis_gateway.py`
- Create: `backend/tests/unit/test_market_analysis_service.py`
- Create: `backend/tests/integration/test_market_analysis.py`
- Modify: `backend/tests/api/test_market_source_routes.py`

- [ ] **Step 1: Write strict analysis contracts**

The request freezes ordered snapshot IDs/hashes, `market` binding
revision/hash, prompt policy version, request hash, and idempotency key. Output
contains only:

```text
currentHeat[]
growthDirections[]
crowding[]
opportunities[]
uncertainties[]
sourceCoverage
```

Every statement references one or more snapshot IDs. Predictions are marked as
inference. Provider failure creates a failed attempt and no synthetic analysis.
No hidden retry/repair or raw provider response is persisted.

- [ ] **Step 2: Run red**

```powershell
python -m pytest backend/tests/unit/test_market_analysis_prompt.py backend/tests/unit/test_market_analysis_gateway.py backend/tests/unit/test_market_analysis_service.py backend/tests/integration/test_market_analysis.py backend/tests/api/test_market_source_routes.py -q
```

- [ ] **Step 3: Implement using the backend gateway**

Resolve the project's `market` task binding server-side. Build a bounded prompt
from normalized snapshots only. Parse one strict structured response outside the
transaction, scan for secret/raw-copy violations, then publish idempotently if
the snapshot and binding manifest still match.

Manual seed work must remain available when analysis is Not Ready.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_market_analysis_prompt.py backend/tests/unit/test_market_analysis_gateway.py backend/tests/unit/test_market_analysis_service.py backend/tests/integration/test_market_analysis.py backend/tests/api/test_market_source_routes.py -q
git add backend
git commit -m "feat: analyze frozen market snapshots"
```

## Task 4: Make selection revision a non-revivable aggregate generation

**Files:**

- Modify: `backend/domain/seeds.py`
- Modify: `backend/repositories/seeds.py`
- Modify: `backend/services/seeds.py`
- Modify: `backend/routers/seeds.py`
- Modify: `backend/repositories/projects.py`
- Modify: `backend/services/project_lifecycle.py`
- Modify: `backend/tests/unit/test_seed_domain.py`
- Modify: `backend/tests/unit/test_seed_service.py`
- Modify: `backend/tests/api/test_seed_routes.py`
- Modify: `backend/tests/integration/test_seed_revisions.py`
- Modify: `backend/tests/unit/test_project_creation.py`

- [ ] **Step 1: Reproduce A→B→A**

Create seed A revision 1 and seed B revision 1. Select A, create downstream
facts tied to selection 1, select B, then reselect the exact same A revision.
Assert:

```python
assert active.selection_revision == 3
assert old_a_contract.selection_revision == 1
assert old_a_contract.readiness == "superseded"
assert active.contract_ready is False
```

Also test that editing the currently selected seed advances selection generation
and supersedes its old downstream chain.

- [ ] **Step 2: Write mutation-lock and finalization-boundary tests**

Server-side selection/edit/archive/restore/delete must acquire the project
mutation lock and reject while a draft/finalization operation owns the project.
After the first finalized chapter:

- selected or historically referenced seeds cannot edit/select/delete;
- unreferenced candidates can still create/edit;
- unreferenced candidates can permanently delete with expected revisions;
- referenced non-selected seeds can archive/restore but not physically delete.

- [ ] **Step 3: Run red**

```powershell
python -m pytest backend/tests/unit/test_seed_domain.py backend/tests/unit/test_seed_service.py backend/tests/api/test_seed_routes.py backend/tests/integration/test_seed_revisions.py backend/tests/unit/test_project_creation.py -q
```

- [ ] **Step 4: Implement generation-aware readiness**

Return active selection as a separate aggregate DTO, not by inferring current
status from matching seed hashes. Project readiness queries must compare
selection revision plus seed revision/hash. Archive/restore and physical-delete
eligibility are explicit server facts.

Do not delete old downstream rows. They remain queryable as read-only
superseded history and cannot become an active branch.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_seed_domain.py backend/tests/unit/test_seed_service.py backend/tests/api/test_seed_routes.py backend/tests/integration/test_seed_revisions.py backend/tests/unit/test_project_creation.py -q
git add backend
git commit -m "feat: fence seed selection generations"
```

## Task 5: Add provenance and explicit seed-creation commands

**Files:**

- Modify: `backend/domain/seeds.py`
- Modify: `backend/repositories/seeds.py`
- Modify: `backend/services/seeds.py`
- Modify: `backend/routers/seeds.py`
- Create: `backend/gateways/seed_provider.py`
- Create: `backend/prompts/seed.py`
- Create: `backend/services/seed_generation.py`
- Create: `backend/tests/unit/test_seed_generation_service.py`
- Create: `backend/tests/unit/test_seed_prompt.py`
- Modify: `backend/tests/api/test_seed_routes.py`
- Modify: `backend/tests/integration/test_seed_revisions.py`

- [ ] **Step 1: Define provenance and draft-generation contracts**

Seed provenance is optional and immutable per seed revision:

```text
kind = manual | market_snapshot | market_analysis | ai_chat
snapshot IDs/hashes
analysis ID/hash
source URLs/timestamps/public notes
```

AI generation returns transient proposals or a stored generation attempt; it
does not insert a `creative_seed`. Only `POST /projects/:id/seeds` creates a seed
after the author submits the ordinary seed form.

`POST /api/projects/:id/seed-inspiration` accepts a bounded current transcript
plus frozen market snapshot/analysis IDs and returns one safe assistant turn.
The transcript remains non-authoritative working state in the page and is not a
Seed, Contract, or Canon entity. Saving a proposed idea uses the ordinary seed
creation command and freezes only safe provenance IDs/hashes and the author's
final edited seed payload, not the raw chat transcript.
For retry recovery, the attempt ledger stores the request hash and bounded,
validated assistant result; it never stores the raw transcript or Provider
response.

- [ ] **Step 2: Test no implicit persistence**

Assert a generation/chat request leaves seed count unchanged. Explicit Save as
Seed creates one revision with selected provenance. Retrying either command with
the same idempotency key is stable.

- [ ] **Step 3: Implement and run tests**

```powershell
python -m pytest backend/tests/unit/test_seed_generation_service.py backend/tests/unit/test_seed_prompt.py backend/tests/api/test_seed_routes.py backend/tests/integration/test_seed_revisions.py -q
```

The backend resolves the `seed` task binding. It never accepts Provider/model
identity from the browser. Manual seed CRUD remains model-independent.

- [ ] **Step 4: Commit**

```powershell
git add backend
git commit -m "feat: add explicit seed provenance workflow"
```

## Task 6: Build the project Seeds page

**Files:**

- Create: `frontend/src/views/ProjectSeedsView.vue`
- Create: `frontend/src/components/seeds/MarketEvidencePanel.vue`
- Create: `frontend/src/components/seeds/SeedEditor.vue`
- Move: `frontend/src/components/seed/SeedCard.vue` to
  `frontend/src/components/seeds/SeedCard.vue`
- Rewrite: `frontend/src/stores/seedStore.js`
- Create: `frontend/src/stores/marketSourceStore.js`
- Delete: `frontend/src/stores/marketStore.js`
- Delete: `frontend/src/components/market/MarketRadar.vue`
- Delete: `frontend/src/components/market/MarketCard.vue`
- Delete: `frontend/src/components/market/AIChatPanel.vue`
- Delete: `frontend/src/prompts/market.js`
- Delete: `frontend/src/prompts/marketDirections.js`
- Delete: `frontend/src/prompts/seed.js`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: `frontend/tests/unit/seedStore.test.mjs`
- Create: `frontend/tests/unit/marketSourceStore.test.mjs`
- Create: `frontend/tests/unit/projectSeedsView.test.mjs`
- Modify: `frontend/tests/unit/projectRoutes.test.mjs`
- Modify: `frontend/tests/unit/productShell.test.mjs`

- [ ] **Step 1: Write page-state tests**

Cover:

- source/snapshot freshness and failure with retained last success;
- manual snapshot import;
- schedule enable/disable/interval CAS, conflict reload, and policy-disabled
  explanation;
- analysis available/not-ready/failure without fake result;
- manual seed create/edit;
- AI/chat proposal stays unsaved until Save as Seed;
- multiple candidates and exactly one selected;
- selection A→B→A increments generation and project next action changes to
  Continue Contract;
- archive/restore and one danger dialog only for eligible permanent delete;
- operation overlay blocks seed switch, while ordinary loading does not lock the
  entire application;
- archived project renders read-only.

- [ ] **Step 2: Run red**

```powershell
node --test frontend/tests/unit/seedStore.test.mjs frontend/tests/unit/marketSourceStore.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
```

- [ ] **Step 3: Implement one Seeds module**

Add `/projects/:projectId/seeds`. Keep market evidence and inspiration inside
this module because “selection topic” is not a durable entity. Use tabs or
sections for Evidence, Inspiration, and Saved Seeds without creating separate
market projects or routes.

The seed editor uses ordinary labeled fields. No raw JSON or frontend prompt is
present. Selection executes immediately when allowed and does not add a
confirmation dialog. Permanent deletion has one red danger dialog.

Market Evidence shows a per-source manual Refresh action and a compact schedule
control. Schedule controls are disabled with the policy recovery explanation for
`manual_only`/`disabled` sources. A successful schedule change is immediate and
uses no confirmation dialog.

- [ ] **Step 4: Remove old direct-model market/seed code**

Delete the listed unreachable store/components/prompts and all imports. Do not
add redirects to them. Ensure the browser build contains no direct Provider call
for market or seed.

- [ ] **Step 5: Run tests and commit**

```powershell
node --test frontend/tests/unit/seedStore.test.mjs frontend/tests/unit/marketSourceStore.test.mjs frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
npm --prefix frontend run build
git add frontend
git commit -m "feat: add project seed workspace"
```

## Task 7: Phase 2B browser acceptance

**Files:**

- Create: `frontend/e2e/phase2b-market-seeds.spec.ts`
- Create: `frontend/e2e/run-phase2b.mjs`
- Create: `frontend/playwright.phase2b.config.ts`
- Modify: `frontend/package.json`
- Modify: `package.json`
- Modify: `scripts/run-tests.mjs`
- Create: `scripts/tests/phase2bSuite.test.mjs`
- Create: `docs/acceptance/2026-07-18-phase-2b-market-seeds.md`

- [ ] **Step 1: Build deterministic browser evidence**

Use manual snapshots and injected fake model gateways against a disposable
MySQL 8 database. The preparation command explicitly seeds the versioned market
source manifest. Do not fetch live websites or call a real model in this gate.

- [ ] **Step 2: Exercise the complete module**

Import separate Qidian/QQ snapshots, verify no fake combined rank, simulate one
source failure retaining last success, create three manual seeds, select A,
record a downstream fixture, select B then A, and verify the old A chain stays
superseded. Enable/disable a verified fixture source schedule without making a
live request; verify a manual-only source cannot enable. Refresh/direct-navigate,
Back/Forward, and narrow viewport.

- [ ] **Step 3: Run all gates**

```powershell
npm run test:browser:phase2b
npm test
npm run test:integration
npm run build
git diff --check
```

- [ ] **Step 4: Review, record, and commit**

After independent spec/quality review and fixes:

```powershell
git add frontend/e2e frontend/playwright.phase2b.config.ts frontend/package.json package.json scripts docs/acceptance/2026-07-18-phase-2b-market-seeds.md
git commit -m "test: accept market and seed workflow"
```
