# P0-C Global Topic Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Keep one implementation owner because the schema, immutable versioning, and candidate-to-project transaction share state. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a production global Topic Center where an author can manually gather public market evidence, start an AI discussion from either evidence or a blank idea, explicitly save versioned directions and candidate seeds, and atomically create a project whose existing project Seed remains pending manual confirmation.

**Architecture:** Add one bounded `topics` context beside Writer Core. It owns global discussions, immutable discussion messages and model operations, versioned directions, versioned candidate seeds, archive state, and idempotent handoff receipts. It reuses the existing immutable `market_snapshots` evidence authority and the configured application fallback Provider. The handoff command pins one global candidate version, creates the existing project foundation, writes one candidate into the existing `creative_seeds / revisions / head` authority with provenance, and records the result in one transaction. It never creates or confirms a second project Seed authority. The frontend exposes the four approved global routes through one information-first Topic Center shell; project Seed remains the only place where the copied seed can be edited and explicitly confirmed.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, existing async MySQL adapter, existing bounded OpenAI-compatible JSON transport, Vue 3, Pinia, Vue Router, Naive UI, Node test runner, pytest, Playwright.

---

## Product and authority boundary

This plan implements the approved flow only:

```text
public market metadata or blank author idea
-> explicit AI discussion
-> optional saved direction
-> explicit saved candidate version
-> atomic project creation from one selected version
-> existing project Seed candidate, still unconfirmed
-> author edits/checks and confirms on /projects/:projectId/seeds
```

The old source at `D:/Projects/Novel_Creater_before_writer_core_refactor_4b85e8d` and the approved mockup `tmp/brainstorm-topic-center-flow-v2.html` are visual/interaction references only. No old Store, project-bound market object, legacy route, or old Seed authority may be restored.

### Stable public API

Keep the existing market evidence reads and explicit source commands:

- `GET /api/market-sources`
- `GET /api/market-sources/{source_id}`
- `GET /api/market-sources/{source_id}/snapshots`
- `GET /api/market-sources/{source_id}/snapshots/{snapshot_id}`
- `POST /api/market-sources/{source_id}/manual-import`
- `POST /api/market-sources/{source_id}/refresh`

Add these bounded Topic Center queries:

- `GET /api/topic-discussions?offset={n}&limit={1..100}`
- `GET /api/topic-discussions/{discussion_id}`
- `GET /api/topic-directions?offset={n}&limit={1..100}`
- `GET /api/topic-directions/{direction_id}`
- `GET /api/topic-candidates?status={active|archived}&offset={n}&limit={1..100}`
- `GET /api/topic-candidates/{candidate_id}`

Add the Plan A command contracts plus the one required archive command:

- `POST /api/topic-discussions`
- `POST /api/topic-discussions/{discussion_id}/messages`
- `POST /api/topic-discussions/{discussion_id}/directions`
- `POST /api/topic-discussions/{discussion_id}/candidates`
- `POST /api/topic-candidates/{candidate_id}/archive`
- `POST /api/topic-candidates/{candidate_id}/versions/{version}/projects`

Remove these superseded public routes from the formal route inventory after the frontend cutover:

- `PUT /api/market-sources/{source_id}/schedule`
- `POST /api/projects/{project_id}/market-analyses`
- `GET /api/projects/{project_id}/market-analyses/{analysis_id}`
- `POST /api/projects/{pid}/seed-inspiration`

The implementation may leave their old service modules temporarily importable for regression compatibility, but no router, runtime, frontend client, Store, or page may call them. The market scheduler must not start in application lifespan.

### Stable author payloads

`TopicDirectionPayload` has exactly these required non-blank fields:

```json
{
  "title": "小城民俗经营悬疑",
  "genreOpportunity": "民俗悬疑稳定，经营成长切入稀缺。",
  "targetAudience": "偏爱规则谜题和稳步经营成长的长篇读者。",
  "readerPromise": "每个地方旧俗既是谜题也是可经营资源。",
  "differentiation": "用地方治理和产业积累替代单纯升级打怪。",
  "longFormPotential": "县、府、州、天下四级扩张可支撑二百万字。",
  "risks": "避免堆砌民俗设定和重复解谜。",
  "evidenceSummary": "来自明确钉住的公开榜单快照，仅作选题参考。"
}
```

`TopicCandidatePayload` has exactly these required non-blank fields:

```json
{
  "title": "典镇山河",
  "genre": "东方奇幻",
  "logline": "衰败典吏以地方香火重建失序山河。",
  "targetAudience": "偏爱经营、制度成长和群像推进的男频长篇读者。",
  "protagonist": "被贬到边县的年轻典吏。",
  "desire": "守住县城并查明山河失序的根源。",
  "coreConflict": "重建秩序必须借助正在吞噬人心的旧神规则。",
  "worldPressure": "香火衰败、地方割据与旧神复苏同步加剧。",
  "openingHook": "主角上任当夜，县志中被抹去的村庄重新出现。",
  "differentiation": "以基层治理和制度建设承载东方诡异升级。",
  "storyPromise": "每次治理都解决现实困局，也揭开更大的山河旧账。",
  "longFormPotential": "从一县扩展至一府、一州和天下秩序重建。",
  "marketBasis": "引用的公开榜单只证明读者兴趣，不声称作品内容事实。"
}
```

Existing project `SeedPayload` adds optional backward-compatible `targetAudience`, `storyPromise`, `longFormPotential`, and `marketBasis` strings with empty defaults. A Topic Center handoff always supplies all thirteen fields. Old nine-field revisions must continue decoding byte-for-byte and keep their previous content hashes.

### Persistence boundary

Create `backend/schema/19_topics.sql` with these eight tables and no others:

1. `topic_discussions` — identity, title, `active` status, timestamps;
2. `topic_discussion_messages` — immutable ordered `user|assistant` messages and message hash;
3. `topic_discussion_requests` — idempotency key, request hash, input manifest, Provider/model snapshot without API key, `reserved|running|succeeded|failed|outcome_unknown`, user/assistant message IDs, result hash, fixed public error, timestamps;
4. `topic_directions` — identity, `current_version`, timestamps;
5. `topic_direction_versions` — immutable payload, content hash, explicit discussion/message/evidence basis;
6. `topic_candidates` — identity, `active|archived`, `current_version`, timestamps;
7. `topic_candidate_versions` — immutable payload, content hash, explicit discussion/message/evidence basis;
8. `topic_project_handoffs` — candidate/version/hash, request/idempotency hashes, project ID, project Seed ID/revision/hash, timestamp.

Direction and candidate identity rows act as their single head via `current_version`; separate head tables and a second evidence copy are prohibited. Basis JSON contains only stable IDs and hashes resolved under lock. Candidate versions referenced by a handoff remain readable after archive and are never physically deleted.

### Explicit non-goals

- no automatic refresh, scheduler setting, background polling, source login, CAPTCHA bypass, chapter-text scraping, or invented fallback market sample;
- no mandatory market evidence or mandatory direction before starting a discussion;
- no automatic creation of a direction, candidate, project, or confirmed project Seed from an AI response;
- no candidate comparison dashboard, scoring engine, recommendation feed, vector search, graph, team workflow, or plugin system;
- no second project Seed table, selection row, confirmation command, or bidirectional sync after handoff;
- no changes to Contract, Bible, Planning, ChapterSession, Finalization, Canon, or Projection semantics;
- no product database mutation during deterministic implementation tests; schema work uses disposable MySQL only.

## Scope and file map

**Create:**

- `backend/schema/19_topics.sql`
- `backend/domain/topics.py`
- `backend/repositories/topics.py`
- `backend/services/topic_discussions.py`
- `backend/services/topic_library.py`
- `backend/services/topic_project_handoffs.py`
- `backend/gateways/topic_discussion_provider.py`
- `backend/prompts/topic_discussion.py`
- `backend/domain/routers/topics.py`
- `backend/tests/unit/test_topics_domain.py`
- `backend/tests/unit/test_topics_repository.py`
- `backend/tests/unit/test_topic_discussion_prompt.py`
- `backend/tests/unit/test_topic_discussion_provider.py`
- `backend/tests/unit/test_topic_discussion_service.py`
- `backend/tests/unit/test_topic_library_service.py`
- `backend/tests/unit/test_topic_project_handoff.py`
- `backend/tests/api/test_topic_routes.py`
- `backend/tests/integration/test_topic_center_mysql.py`
- `frontend/src/application/topics/topicContracts.js`
- `frontend/src/stores/topicCenterStore.js`
- `frontend/src/views/TopicCenterView.vue`
- `frontend/src/components/topics/TopicCenterHeader.vue`
- `frontend/src/components/topics/MarketDiscoveryPanel.vue`
- `frontend/src/components/topics/TopicDiscussionPanel.vue`
- `frontend/src/components/topics/TopicDirectionsPanel.vue`
- `frontend/src/components/topics/TopicCandidatesPanel.vue`
- `frontend/src/components/topics/CreateProjectFromCandidateDialog.vue`
- `frontend/tests/unit/topicContracts.test.mjs`
- `frontend/tests/unit/topicCenterStore.test.mjs`
- `frontend/tests/unit/topicCenterRoutes.test.mjs`
- `frontend/tests/unit/topicCenterView.test.mjs`
- `frontend/e2e/p0-c-topic-center.spec.ts`
- `frontend/e2e/run-p0-c.mjs`

**Modify:**

- `backend/schema_manifest.py`
- `backend/schema_version.py`
- `backend/domain/seeds.py`
- `backend/services/project_lifecycle.py`
- `backend/services/seeds.py`
- `backend/repositories/projects.py`
- `backend/repositories/seeds.py`
- `backend/domain/market_sources.py`
- `backend/gateways/market_sources/manual_snapshot.py`
- `backend/assets/market-sources-v1.0.0/manifest.json`
- `backend/assets/market-sources-v1.0.0/sources.json`
- `backend/scripts/seed_market_sources.py`
- `backend/domain/routers/market_sources.py`
- `backend/domain/routers/seeds.py`
- `backend/main.py`
- `backend/tests/unit/test_schema_manifest.py`
- `backend/tests/unit/test_schema_version.py`
- `backend/tests/unit/test_initialize_database.py`
- `backend/tests/integration/test_schema_bootstrap.py`
- `backend/tests/unit/test_market_source_manifest.py`
- `backend/tests/unit/test_market_source_adapters.py`
- `backend/tests/unit/test_main_lifespan.py`
- `backend/tests/unit/test_project_creation.py`
- `backend/tests/unit/test_seed_domain.py`
- `backend/tests/unit/test_seed_service.py`
- `backend/tests/api/test_route_inventory.py`
- `frontend/src/api/db/client.js`
- `frontend/src/router/projectRoutes.js`
- `frontend/src/components/layout/productShell.js`
- `frontend/src/stores/marketSourceStore.js`
- `frontend/src/views/ProjectSeedsView.vue`
- `frontend/src/components/seeds/SeedCard.vue`
- `frontend/tests/unit/productShell.test.mjs`
- `frontend/tests/unit/projectRoutes.test.mjs`
- `frontend/tests/unit/projectSeedsView.test.mjs`
- `frontend/tests/unit/marketSourceStore.test.mjs`
- `frontend/package.json`
- `package.json`
- `scripts/run-tests.mjs`

The market asset package remains `market-sources-v1.0.0` in this batch so existing deterministic IDs do not change. Add the three manual-only source definitions to the package, recompute `sources_file.sha256`, and update manifest/domain tests. Do not fabricate verified adapters for Fanqie, Qimao, or Shuqi; they appear with clear manual-import capability until an independently verified adapter exists.

---

### Task 1: Establish an isolated clean baseline

**Files:** None

- [ ] **Step 1: Create the isolated worktree**

Use branch `codex/p0-c-global-topic-center` under the ignored repository-local `.worktrees/` directory, following the `using-git-worktrees` skill. Start from local `main` commit `172357846398950a22a00d259a66ba80c37988e0` or its direct documentation-only descendant containing this plan.

- [ ] **Step 2: Preserve unrelated user files**

Run:

```powershell
git status --short --branch
git rev-parse HEAD
git diff --check
```

Expected: the isolated worktree is clean. `.review-worktrees/` and `tmp/brainstorm-topic-center-*.html` remain only in the main checkout and are never copied, staged, edited, or deleted.

- [ ] **Step 3: Run the deterministic baseline**

Run:

```powershell
npm test
npm run build
```

Expected: both exit `0`; no Provider, external network, product database, Vite server, or backend server is used.

### Task 2: Freeze Topic Center domain values and schema v1.14 with TDD

**Files:**

- Create: `backend/domain/topics.py`
- Create: `backend/schema/19_topics.sql`
- Create: `backend/tests/unit/test_topics_domain.py`
- Modify: `backend/schema_manifest.py`
- Modify: `backend/schema_version.py`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Modify: `backend/tests/unit/test_schema_version.py`
- Modify: `backend/tests/unit/test_initialize_database.py`
- Modify: `backend/tests/integration/test_schema_bootstrap.py`

- [ ] **Step 1: Write failing strict-domain tests**

Cover `TopicMessage`, `TopicDirectionPayload`, `TopicCandidatePayload`, immutable version refs, evidence refs, suggestion/result values, list/detail results, and fixed public errors. Prove:

```python
def test_candidate_requires_the_exact_thirteen_author_fields():
    assert set(TopicCandidatePayload.model_fields) == {
        "title", "genre", "logline", "target_audience", "protagonist",
        "desire", "core_conflict", "world_pressure", "opening_hook",
        "differentiation", "story_promise", "long_form_potential",
        "market_basis",
    }

def test_ai_result_is_only_a_suggestion_not_a_saved_identity():
    assert {"id", "version", "status"}.isdisjoint(
        TopicCandidateSuggestion.model_fields
    )

def test_evidence_reference_requires_id_and_hash():
    with pytest.raises(ValidationError):
        TopicEvidenceRef(snapshotId="snapshot-1", contentHash="")
```

All DTOs are strict, frozen, `extra="forbid"`, bounded, reject blank/control-only text, and use camelCase aliases only at the public boundary. Discussion input permits zero evidence refs.

- [ ] **Step 2: Write failing schema tests**

Assert `19_topics.sql` is in the manifest directly after `18_market.sql`, exact table names equal the eight-table persistence boundary, foreign keys use `ON DELETE RESTRICT` for immutable evidence/candidate history, handoff idempotency is unique, message sequence is unique per discussion, and no topic table references Contract, Bible, Planning, Canon, Projection, ChapterSession, or Finalization.

- [ ] **Step 3: Run RED**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_topics_domain.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py
```

Expected: tests fail because `backend.domain.topics` and `19_topics.sql` do not exist and the expected version is still `writer-core-v1.13.0`.

- [ ] **Step 4: Implement the domain and schema**

Add the exact eight tables, ordered constraints, JSON columns, hashes, timestamps, and status checks described above. Bump `EXPECTED_SCHEMA_VERSION` to `writer-core-v1.14.0`; add `19_topics.sql` to `FRAGMENTS`. This repository remains rebuild-only: do not add runtime DDL, migration-on-start, or compatibility branching.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_topics_domain.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py
git add -- backend/domain/topics.py backend/schema/19_topics.sql backend/schema_manifest.py backend/schema_version.py backend/tests/unit/test_topics_domain.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/integration/test_schema_bootstrap.py
git diff --cached --check
git commit -m "feat: define global topic center authority"
```

### Task 3: Add session-bound Topic Center persistence

**Files:**

- Create: `backend/repositories/topics.py`
- Create: `backend/tests/unit/test_topics_repository.py`

- [ ] **Step 1: Write failing repository tests**

Use the established fake-session style to cover:

- bounded recent discussion/direction/candidate queries with deterministic `updated_at DESC, id DESC` order;
- one discussion detail returning ordered immutable messages and recorded request status;
- candidate detail returning all versions newest first, including archived candidates;
- `lock_*` methods using `FOR UPDATE` only inside commands;
- snapshot evidence locks preserving caller order and requiring exact IDs/hashes;
- compare-and-swap of `current_version` for direction and candidate identities;
- archive compare-and-swap;
- handoff lookup by idempotency key and insertion of the frozen result;
- no repository method commits, opens a new transaction, or writes project Seed selection.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest -q backend/tests/unit/test_topics_repository.py
```

Expected: import failure for `backend.repositories.topics`.

- [ ] **Step 3: Implement the repository**

Use parameterized SQL only. JSON decoding is fail-closed. Query methods accept the caller's connection/session and cap `limit` at `100`; command methods require the caller's transaction. `lock_generation_inputs` reads the global application fallback and the selected Provider snapshot without returning the API key in any persisted manifest.

- [ ] **Step 4: Verify and commit**

```powershell
python -m pytest -q backend/tests/unit/test_topics_repository.py
git add -- backend/repositories/topics.py backend/tests/unit/test_topics_repository.py
git diff --cached --check
git commit -m "feat: persist global topic center records"
```

### Task 4: Cut market discovery over to manual-only product behavior

**Files:**

- Modify: `backend/domain/market_sources.py`
- Modify: `backend/gateways/market_sources/manual_snapshot.py`
- Modify: `backend/assets/market-sources-v1.0.0/sources.json`
- Modify: `backend/assets/market-sources-v1.0.0/manifest.json`
- Modify: `backend/scripts/seed_market_sources.py`
- Modify: `backend/domain/routers/market_sources.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/unit/test_market_source_manifest.py`
- Modify: `backend/tests/unit/test_market_source_adapters.py`
- Modify: `backend/tests/unit/test_main_lifespan.py`
- Modify: `backend/tests/api/test_route_inventory.py`

- [ ] **Step 1: Write failing capability tests**

Freeze five visible source definitions: current Qidian and QQ Reading plus manual-only Fanqie, Qimao, and Shuqi definitions. Tests must assert:

- all five are public metadata sources and none claims chapter text;
- Qidian/QQ retain only capabilities justified by their current policy;
- Fanqie/Qimao/Shuqi accept only author-supplied normalized snapshots whose work URLs match their canonical public book hosts/path rules;
- manual-only sources expose `canManualImport=true`, `canRefresh=false`, `canSchedule=false`;
- `/schedule` is absent from route inventory;
- application lifespan never constructs or starts the market scheduler.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest -q backend/tests/unit/test_market_source_manifest.py backend/tests/unit/test_market_source_adapters.py backend/tests/unit/test_main_lifespan.py backend/tests/api/test_route_inventory.py
```

- [ ] **Step 3: Implement the cutover**

Add the three manual-only definitions and canonical URL rules, recompute the source-file SHA-256, and return explicit `canManualImport`, `canRefresh`, and `canSchedule=false` fields from market source DTOs. Remove the schedule router and scheduler lifespan startup. Keep user-triggered `/refresh` only for a source whose verified policy and adapter actually permit it; otherwise return the existing fixed policy failure. Do not invent data when any source fails.

- [ ] **Step 4: Validate package and commit**

```powershell
python -m backend.scripts.seed_market_sources --validate-only
python -m pytest -q backend/tests/unit/test_market_source_manifest.py backend/tests/unit/test_market_source_adapters.py backend/tests/unit/test_main_lifespan.py backend/tests/api/test_route_inventory.py
git add -- backend/domain/market_sources.py backend/gateways/market_sources/manual_snapshot.py backend/assets/market-sources-v1.0.0/sources.json backend/assets/market-sources-v1.0.0/manifest.json backend/scripts/seed_market_sources.py backend/domain/routers/market_sources.py backend/main.py backend/tests/unit/test_market_source_manifest.py backend/tests/unit/test_market_source_adapters.py backend/tests/unit/test_main_lifespan.py backend/tests/api/test_route_inventory.py
git diff --cached --check
git commit -m "feat: expose manual topic market discovery"
```

### Task 5: Implement bounded AI topic discussions

**Files:**

- Create: `backend/prompts/topic_discussion.py`
- Create: `backend/gateways/topic_discussion_provider.py`
- Create: `backend/services/topic_discussions.py`
- Create: `backend/tests/unit/test_topic_discussion_prompt.py`
- Create: `backend/tests/unit/test_topic_discussion_provider.py`
- Create: `backend/tests/unit/test_topic_discussion_service.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing prompt and Provider tests**

The prompt accepts a bounded transcript plus zero to four pinned market snapshots and at most one direction/candidate version. It asks for strict JSON with:

```json
{
  "reply": "author-facing discussion text",
  "directionSuggestions": [],
  "candidateSuggestions": []
}
```

Each suggestion uses the exact payload contract but contains no ID/version/status. Tests reject raw Provider configuration, API keys, unsupported market claims, unpinned snapshot IDs, response bodies above the limit, invalid JSON, extra fields, and echoed private material.

- [ ] **Step 2: Write failing service tests**

Cover:

- creating a blank discussion without a project;
- reserving one user message and request in a short transaction;
- calling the Provider outside the transaction using only the configured global fallback model;
- terminalizing exactly one assistant message plus result hash;
- fixed `TOPIC_PROVIDER_NOT_READY`, `TOPIC_PROVIDER_FAILED`, `TOPIC_INVALID_RESPONSE`, `TOPIC_REQUEST_CONFLICT`, `TOPIC_REQUEST_IN_PROGRESS`, and `TOPIC_OUTCOME_UNKNOWN` codes;
- same-key/same-request replay returns the recorded result without a second Provider call;
- same key/different content conflicts;
- cancellation and uncertain commit never fabricate an assistant message;
- zero evidence is valid and evidence is never mandatory.

- [ ] **Step 3: Run RED**

```powershell
python -m pytest -q backend/tests/unit/test_topic_discussion_prompt.py backend/tests/unit/test_topic_discussion_provider.py backend/tests/unit/test_topic_discussion_service.py
```

- [ ] **Step 4: Implement the Provider lifecycle and service**

Wrap the existing `OpenAIJSONTransport` in `TopicDiscussionProviderGateway` with a 180-second timeout and 256 KiB response cap. Register/start/close it with the same lifespan ownership rules as other JSON gateways. Persist Provider ID/model/base URL hash and generation settings in the request manifest, never the API key or raw base URL. The assistant reply and suggestions remain discussion output until the author explicitly invokes a save command.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest -q backend/tests/unit/test_topic_discussion_prompt.py backend/tests/unit/test_topic_discussion_provider.py backend/tests/unit/test_topic_discussion_service.py backend/tests/unit/test_main_lifespan.py
git add -- backend/prompts/topic_discussion.py backend/gateways/topic_discussion_provider.py backend/services/topic_discussions.py backend/tests/unit/test_topic_discussion_prompt.py backend/tests/unit/test_topic_discussion_provider.py backend/tests/unit/test_topic_discussion_service.py backend/main.py backend/tests/unit/test_main_lifespan.py
git diff --cached --check
git commit -m "feat: add explicit ai topic discussions"
```

### Task 6: Implement versioned directions and candidate library

**Files:**

- Create: `backend/services/topic_library.py`
- Create: `backend/tests/unit/test_topic_library_service.py`

- [ ] **Step 1: Write failing command tests**

Cover these exact rules:

- save direction/candidate only from explicit existing discussion message IDs owned by the discussion;
- resolve every supplied snapshot ID to immutable ID/hash/source facts before writing basis JSON;
- omit direction/candidate ID to create version `1`;
- supply the same ID plus exact `expectedVersion` to append one immutable version and advance `current_version`;
- stale expected version conflicts;
- content replay with the same idempotency key returns the same version; different content conflicts;
- archiving hides a candidate from the active list but preserves all versions and existing handoffs;
- archived candidates reject new versions and new handoffs but remain readable;
- saving a suggestion never creates a project or project Seed.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest -q backend/tests/unit/test_topic_library_service.py
```

- [ ] **Step 3: Implement only the required commands and reads**

Use one transaction per save/archive command and one read connection per list/detail query. Do not add delete, restore, scoring, tags, or automatic merging. `continue discussion` is implemented by creating/opening a discussion with a pinned direction/candidate ref; it does not mutate the referenced version.

- [ ] **Step 4: Verify and commit**

```powershell
python -m pytest -q backend/tests/unit/test_topics_domain.py backend/tests/unit/test_topics_repository.py backend/tests/unit/test_topic_library_service.py
git add -- backend/services/topic_library.py backend/tests/unit/test_topic_library_service.py
git diff --cached --check
git commit -m "feat: add versioned topic directions and candidates"
```

### Task 7: Implement the atomic candidate-to-project Seed handoff

**Files:**

- Create: `backend/services/topic_project_handoffs.py`
- Create: `backend/tests/unit/test_topic_project_handoff.py`
- Modify: `backend/domain/seeds.py`
- Modify: `backend/services/project_lifecycle.py`
- Modify: `backend/services/seeds.py`
- Modify: `backend/repositories/projects.py`
- Modify: `backend/repositories/seeds.py`
- Modify: `backend/tests/unit/test_project_creation.py`
- Modify: `backend/tests/unit/test_seed_domain.py`
- Modify: `backend/tests/unit/test_seed_service.py`

- [ ] **Step 1: Freeze backward-compatible project Seed values**

Add the four optional text fields with empty defaults to `SeedPayload` and add an internal persisted provenance kind:

```python
class SeedTopicCandidateProvenance(_FrozenSeedModel):
    id: str
    version: int = Field(gt=0)
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")
```

`SeedProvenance.kind="topic_candidate"` requires `topicCandidate`, permits pinned snapshot provenance, and forbids project market-analysis/inspiration references. Do not add `topic_candidate` to the client-controlled `SeedProvenanceSelection`; only the handoff service may construct it after locking the global authority.

Tests prove old nine-field seed revision JSON still decodes with four empty defaults and its stored hash is not recomputed or rewritten.

- [ ] **Step 2: Write failing atomicity tests**

Using one transaction fake, assert the order:

```text
lock handoff key
lock candidate identity/version/snapshot refs
guard project creation
insert project foundation and model bindings
insert existing creative_seed identity/revision/head
insert handoff receipt
commit once
```

Inject failure at every step and assert one rollback, no returned project, no selected Seed row, and no handoff receipt. Same key/same candidate/version/title replays the same project and Seed revision; same key with any different input conflicts. Candidate `version`, content hash, and snapshot hashes must match under lock. The created Seed is status `candidate`, `selection_revision=0`, `is_selected=false`; no `project_selected_seeds` row is inserted.

- [ ] **Step 3: Refactor only session ownership, not lifecycle meaning**

Extract a tested internal `create_in_session` path from `ProjectLifecycleService.create` so both ordinary project creation and handoff use the identical foundation writes. Ordinary `create` still owns one transaction and returns the same DTO. Add a session-bound Seed insertion helper that accepts only an already validated `SeedPayload` and internally resolved `SeedProvenance`; existing public Seed create/edit/select behavior remains unchanged.

- [ ] **Step 4: Implement the handoff**

Derive project, Seed, and revision IDs deterministically from the handoff idempotency key. Build the project title from the explicit request; copy candidate genre/logline into project summary fields and all thirteen candidate fields into the project Seed. Record the exact project/Seed result before commit. Never call the public Seed selection command.

- [ ] **Step 5: Verify and commit**

```powershell
python -m pytest -q backend/tests/unit/test_topic_project_handoff.py backend/tests/unit/test_project_creation.py backend/tests/unit/test_seed_domain.py backend/tests/unit/test_seed_service.py
git add -- backend/services/topic_project_handoffs.py backend/tests/unit/test_topic_project_handoff.py backend/domain/seeds.py backend/services/project_lifecycle.py backend/services/seeds.py backend/repositories/projects.py backend/repositories/seeds.py backend/tests/unit/test_project_creation.py backend/tests/unit/test_seed_domain.py backend/tests/unit/test_seed_service.py
git diff --cached --check
git commit -m "feat: atomically hand topic candidates to projects"
```

### Task 8: Expose strict Topic Center routes and retire project-bound selection routes

**Files:**

- Create: `backend/domain/routers/topics.py`
- Create: `backend/tests/api/test_topic_routes.py`
- Modify: `backend/domain/routers/market_sources.py`
- Modify: `backend/domain/routers/seeds.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/api/test_route_inventory.py`

- [ ] **Step 1: Write failing API tests**

Dependency-override fakes must verify every stable query and command path, camelCase DTOs, strict unknown-field rejection, URL-decoded IDs, fixed public errors, status codes, archive behavior, and the handoff response:

```json
{
  "project": {"id": "project-1", "title": "典镇山河"},
  "seed": {"id": "seed-1", "revision": 1, "isSelected": false, "selectionRevision": 0},
  "handoff": {"candidateId": "candidate-1", "version": 2}
}
```

Route-inventory tests require every query/command above and reject the four superseded project-bound routes.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest -q backend/tests/api/test_topic_routes.py backend/tests/api/test_route_inventory.py
```

- [ ] **Step 3: Implement router composition**

Construct services through explicit dependencies; no router performs SQL or state inference. Remove the old analysis/inspiration route decorators and unregister scheduler behavior. Register `topics.router` in `backend/main.py`. Do not change the existing project Seed create/edit/select paths.

- [ ] **Step 4: Verify and commit**

```powershell
python -m pytest -q backend/tests/api/test_topic_routes.py backend/tests/api/test_route_inventory.py backend/tests/api/test_market_source_routes.py backend/tests/api/test_seed_routes.py
git add -- backend/domain/routers/topics.py backend/tests/api/test_topic_routes.py backend/domain/routers/market_sources.py backend/domain/routers/seeds.py backend/main.py backend/tests/api/test_route_inventory.py
git diff --cached --check
git commit -m "feat: expose global topic center api"
```

### Task 9: Add strict frontend contracts, state, routes, and shell navigation

**Files:**

- Create: `frontend/src/application/topics/topicContracts.js`
- Create: `frontend/src/stores/topicCenterStore.js`
- Create: `frontend/tests/unit/topicContracts.test.mjs`
- Create: `frontend/tests/unit/topicCenterStore.test.mjs`
- Create: `frontend/tests/unit/topicCenterRoutes.test.mjs`
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/src/stores/marketSourceStore.js`
- Modify: `frontend/tests/unit/productShell.test.mjs`
- Modify: `frontend/tests/unit/projectRoutes.test.mjs`
- Modify: `frontend/tests/unit/marketSourceStore.test.mjs`

- [ ] **Step 1: Write failing response-contract tests**

Strict parsers reject missing/extra fields, invalid versions/hashes/statuses, mismatched candidate heads, malformed suggestions, and any handoff claiming `isSelected=true` or `selectionRevision>0`. They preserve Chinese author text without exposing hashes in presentation helpers.

- [ ] **Step 2: Write failing Store concurrency tests**

Cover latest-request guards for each list/detail, one active discussion, message send/replay, explicit save direction/candidate, archive, handoff busy state, stale response after route change, and retry after fixed failures. A successful handoff returns the project path but does not auto-confirm the Seed.

- [ ] **Step 3: Write failing route/shell tests**

Freeze:

```text
/topics/market       -> TopicMarket
/topics/discussions  -> TopicDiscussions
/topics/directions   -> TopicDirections
/topics/candidates   -> TopicCandidates
```

`选题中心` is the first global navigation item and remains selected for all four routes. Project navigation is unchanged. Browser refresh restores the current Topic Center route; there is no placeholder page.

- [ ] **Step 4: Run RED**

```powershell
node --test frontend/tests/unit/topicContracts.test.mjs frontend/tests/unit/topicCenterStore.test.mjs frontend/tests/unit/topicCenterRoutes.test.mjs frontend/tests/unit/productShell.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/marketSourceStore.test.mjs
```

- [ ] **Step 5: Implement API, Store, routes, and navigation**

Add `api.topics` and remove the client methods for market scheduling, project market analysis, and project seed inspiration. Reduce `marketSourceStore` to global source/snapshot/manual refresh state; no project activation or schedule state remains. Use server capabilities for buttons; never infer source or handoff authority from missing data.

- [ ] **Step 6: Verify and commit**

```powershell
node --test frontend/tests/unit/topicContracts.test.mjs frontend/tests/unit/topicCenterStore.test.mjs frontend/tests/unit/topicCenterRoutes.test.mjs frontend/tests/unit/productShell.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/marketSourceStore.test.mjs
git add -- frontend/src/application/topics/topicContracts.js frontend/src/stores/topicCenterStore.js frontend/tests/unit/topicContracts.test.mjs frontend/tests/unit/topicCenterStore.test.mjs frontend/tests/unit/topicCenterRoutes.test.mjs frontend/src/api/db/client.js frontend/src/router/projectRoutes.js frontend/src/components/layout/productShell.js frontend/src/stores/marketSourceStore.js frontend/tests/unit/productShell.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/marketSourceStore.test.mjs
git diff --cached --check
git commit -m "feat: add topic center frontend contracts"
```

### Task 10: Build the production Topic Center interface

**Files:**

- Create: `frontend/src/views/TopicCenterView.vue`
- Create: `frontend/src/components/topics/TopicCenterHeader.vue`
- Create: `frontend/src/components/topics/MarketDiscoveryPanel.vue`
- Create: `frontend/src/components/topics/TopicDiscussionPanel.vue`
- Create: `frontend/src/components/topics/TopicDirectionsPanel.vue`
- Create: `frontend/src/components/topics/TopicCandidatesPanel.vue`
- Create: `frontend/src/components/topics/CreateProjectFromCandidateDialog.vue`
- Create: `frontend/tests/unit/topicCenterView.test.mjs`

- [ ] **Step 1: Write failing structure and interaction tests**

Assert the approved information-first layout:

- page identity says what the current route is for;
- top local navigation exposes 市场热门 / AI 讨论 / 选题方向 / 候选种子库;
- Market page shows source freshness/failure, manual action, evidence list, AI discussion alongside it, and recent candidates below;
- a blank discussion can start with no selected evidence;
- evidence chips show exact attached snapshots and can be removed before send;
- AI suggestions have explicit `保存为方向` / `保存为候选种子` actions and never claim already saved;
- direction detail shows opportunity, reader, promise, differentiation, long-form potential, risk, and evidence;
- candidate detail shows all thirteen fields, version history, continue-discussion, archive, and create-project actions;
- create-project dialog names the exact candidate/version and explains that project Seed remains待确认;
- raw IDs, hashes, JSON, Provider settings, and internal revisions are hidden from the primary reading surface;
- keyboard send is Enter, newline is Shift+Enter, busy actions are disabled, errors retain typed content, and every scrollable content panel works independently.

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/topicCenterView.test.mjs
```

- [ ] **Step 3: Implement the shared view and four route modes**

Use the existing product typography, spacing, button, dialog, drawer, loading, empty, and error patterns. The Market page follows the approved `flow-v2` hierarchy but contains real server data only. Keep all four routes available for manual navigation; do not build a forced wizard or “continue next” chain.

- [ ] **Step 4: Verify responsive and accessibility behavior**

Unit tests must also prove associated labels, keyboard focus, `aria-live` for Provider progress/failure, no nested interactive controls, no horizontal page overflow at `390px`, and stable desktop two-column layout at `1440px`.

- [ ] **Step 5: Commit**

```powershell
node --test frontend/tests/unit/topicCenterView.test.mjs frontend/tests/unit/topicCenterStore.test.mjs frontend/tests/unit/topicCenterRoutes.test.mjs
npm run build
git add -- frontend/src/views/TopicCenterView.vue frontend/src/components/topics/TopicCenterHeader.vue frontend/src/components/topics/MarketDiscoveryPanel.vue frontend/src/components/topics/TopicDiscussionPanel.vue frontend/src/components/topics/TopicDirectionsPanel.vue frontend/src/components/topics/TopicCandidatesPanel.vue frontend/src/components/topics/CreateProjectFromCandidateDialog.vue frontend/tests/unit/topicCenterView.test.mjs
git diff --cached --check
git commit -m "feat: build the global topic center experience"
```

### Task 11: Complete the project Seed handoff experience and remove duplicate project UI

**Files:**

- Modify: `frontend/src/views/ProjectSeedsView.vue`
- Modify: `frontend/src/components/seeds/SeedCard.vue`
- Modify: `frontend/tests/unit/projectSeedsView.test.mjs`

- [ ] **Step 1: Write failing project Seed tests**

For a handed-off candidate, assert the project page:

- displays all thirteen fields and `来源：选题中心候选《典镇山河》版本 2`;
- displays `待确认` and an explicit author confirmation action;
- permits normal project Seed editing before confirmation through the existing Seed service;
- uses the existing confirmation route and does not call Topic Center on edit/confirm;
- becomes read-only under existing post-confirmation rules;
- contains no full market source manager, schedule UI, project market analysis, or project seed chat.

- [ ] **Step 2: Run RED**

```powershell
node --test frontend/tests/unit/projectSeedsView.test.mjs
```

- [ ] **Step 3: Implement the minimal cutover**

Remove `MarketEvidencePanel` and project inspiration controls from `ProjectSeedsView`. Preserve manual project Seed create/edit/confirm behavior. Extend the author-facing Seed card/editor only for the four new optional fields; do not redesign Contract/Bible navigation in this plan.

- [ ] **Step 4: Verify and commit**

```powershell
node --test frontend/tests/unit/projectSeedsView.test.mjs frontend/tests/unit/seedStore.test.mjs
git add -- frontend/src/views/ProjectSeedsView.vue frontend/src/components/seeds/SeedCard.vue frontend/tests/unit/projectSeedsView.test.mjs
git diff --cached --check
git commit -m "feat: present topic handoffs as pending project seeds"
```

### Task 12: Prove MySQL atomicity and the complete deterministic browser flow

**Files:**

- Create: `backend/tests/integration/test_topic_center_mysql.py`
- Create: `frontend/e2e/p0-c-topic-center.spec.ts`
- Create: `frontend/e2e/run-p0-c.mjs`
- Modify: `frontend/package.json`
- Modify: `package.json`
- Modify: `scripts/run-tests.mjs`

- [ ] **Step 1: Add disposable MySQL integration coverage**

Use `backend.tests.support.disposable_mysql` only. Cover schema bootstrap, discussion/message idempotency, concurrent candidate version compare-and-swap, archive preservation, handoff rollback at a forced failure, same-key replay, and exact foreign-key preservation after candidate archive. Assert the created project has one project Seed head, zero selected Seed rows, and unchanged Writer Core foundation revisions.

- [ ] **Step 2: Add the formal browser profile**

Register `browser-p0-c` in `scripts/run-tests.mjs` and package scripts. `run-p0-c.mjs` must:

- create and finally delete one exact disposable database;
- seed the five source definitions and deterministic public snapshot metadata;
- start a loopback fake OpenAI-compatible JSON Provider used only by this test;
- configure it as the application fallback;
- start the workspace backend and Vite on owned loopback ports;
- always terminate owned child processes and delete the disposable database;
- never access the product database or external network.

- [ ] **Step 3: Exercise the author flow in Playwright**

The spec must perform:

```text
open 选题中心
-> inspect five honest source states
-> manually import/select a snapshot
-> start a blank-capable AI discussion
-> send a message and receive suggestions
-> explicitly save one direction
-> explicitly save candidate "典镇山河"
-> continue discussion and save version 2
-> create a project from exact version 2
-> land on project Seed
-> verify pending/unconfirmed and provenance
-> edit one allowed field
-> manually confirm through the existing Seed route
```

Also verify archive/read history, browser refresh, back/forward route restoration, source failure without fake fallback data, independent panel scrolling, and no schedule control.

- [ ] **Step 4: Run targeted and full deterministic verification**

```powershell
python -m pytest -q backend/tests/unit/test_topics_domain.py backend/tests/unit/test_topics_repository.py backend/tests/unit/test_topic_discussion_prompt.py backend/tests/unit/test_topic_discussion_provider.py backend/tests/unit/test_topic_discussion_service.py backend/tests/unit/test_topic_library_service.py backend/tests/unit/test_topic_project_handoff.py backend/tests/api/test_topic_routes.py
node --test frontend/tests/unit/topicContracts.test.mjs frontend/tests/unit/topicCenterStore.test.mjs frontend/tests/unit/topicCenterRoutes.test.mjs frontend/tests/unit/topicCenterView.test.mjs frontend/tests/unit/projectSeedsView.test.mjs
npm test
npm run build
```

Expected: all exit `0` without MySQL environment variables or network.

- [ ] **Step 5: Run disposable MySQL and browser acceptance**

With only explicit `TEST_MYSQL_HOST`, `TEST_MYSQL_PORT`, `TEST_MYSQL_USER`, and `TEST_MYSQL_PASSWORD` bridged to the process:

```powershell
npm run test:integration
npm run test:browser:p0-c
```

Expected: both exit `0`; the runner reports the exact disposable database as deleted and all owned ports closed.

- [ ] **Step 6: Commit acceptance coverage**

```powershell
git add -- backend/tests/integration/test_topic_center_mysql.py frontend/e2e/p0-c-topic-center.spec.ts frontend/e2e/run-p0-c.mjs frontend/package.json package.json scripts/run-tests.mjs
git diff --cached --check
git commit -m "test: accept p0-c topic center flow"
```

### Task 13: Final review, Writer Core regression, and safe handoff

**Files:** All Plan C files only

- [ ] **Step 1: Run scope and ambiguity checks**

```powershell
rg -n -i "TBD|TODO|待定|按需实现|以后再做" docs/superpowers/plans/2026-08-30-p0-c-global-topic-center.md
rg -n "market-sources/.*/schedule|projects/.*/market-analyses|seed-inspiration" backend/main.py backend/domain/routers backend/tests/api/test_route_inventory.py frontend/src/api frontend/src/router frontend/src/stores frontend/src/views frontend/src/components
git diff main...HEAD --check
git status --short --branch
```

Expected: the plan contains no implementation placeholder. Superseded route strings appear only in negative route-inventory tests; they are absent from registered routers and production frontend code. Unrelated main-checkout files remain untouched.

- [ ] **Step 2: Run the full deterministic regression again**

```powershell
npm test
npm run build
```

Expected: all Python, script, and frontend unit/API tests pass and production build succeeds. No Provider or database is used.

- [ ] **Step 3: Review authority invariants**

Inspect the diff and confirm:

- Topic Center tables do not own project Seed selection;
- handoff is one transaction and creates no selected Seed row;
- Contract/Bible/Planning/Chapter/Finalization/Canon/Projection writes are untouched;
- AI output remains a suggestion until an explicit save command;
- market evidence is public metadata with immutable identity and honest freshness/failure;
- old project-bound selection routes and schedule UI/runtime are unreachable;
- no secret or Provider response body can appear in fixed public errors or persisted manifests.

- [ ] **Step 4: Request final code review and fix only verified findings**

Use the `requesting-code-review` skill against `main...HEAD`. Apply the `receiving-code-review` skill to every finding. Re-run the smallest affected tests after each fix and the full deterministic gate once after all fixes.

- [ ] **Step 5: Final commit and integration choice**

```powershell
git status --short --branch
git log --oneline --decorate main..HEAD
git diff --stat main...HEAD
```

Use the `finishing-a-development-branch` skill. Do not push, merge, reinitialize the product database, or run a real Provider acceptance unless the user explicitly selects that integration/deployment action after reviewing the completed implementation.

---

## Definition of done

Plan C is complete only when all are true:

- the four global Topic Center routes are production pages, not placeholders;
- five honest market source entries are visible, with manual-only capability where no verified adapter exists;
- a discussion can start from a blank idea and can optionally attach immutable evidence/direction/candidate context;
- Provider output is recorded but never auto-saves a direction/candidate/project;
- directions and candidates have immutable versions and an explicit current version;
- candidates can be archived without deleting referenced history;
- exact candidate version -> project handoff is atomic and idempotent;
- the copied project Seed is in the existing authority, editable before confirmation, and unconfirmed until the author explicitly confirms;
- project-bound market analysis/chat and scheduler UI/runtime are no longer reachable;
- deterministic unit/API/build, disposable MySQL, and formal browser gates pass;
- Writer Core lifecycle and write authorities remain unchanged.
