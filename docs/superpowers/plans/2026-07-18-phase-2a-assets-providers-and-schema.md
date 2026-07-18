# Phase 2A Assets, Providers, and Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `subagent-driven-development`; use `test-driven-development` for every
> behavior change and `verification-before-completion` before each commit.

**Goal:** Establish the exact Phase 2 schema, secure Provider/default-model
configuration, global creative-asset pages, and a content-addressed local corpus
with immutable lifecycle and reference protection.

**Architecture:** Schema is initialized only from an exact manifest. Application
settings contain one optional fallback Provider. Provider secrets remain
write-only. Approved styles/cards remain immutable system assets. Corpus bytes
are identified by SHA-256, copied into app-managed storage, parsed into immutable
source revisions, and protected by project references.

**Baseline:** Execute after the roadmap is committed on
`codex/phase2-creative-foundation`.

---

## Task 1: Build the exact v1.3 schema and aggregate fence

**Files:**

- Create: `backend/schema/12_application.sql`
- Modify: `backend/schema/10_core.sql`
- Modify: `backend/schema/15_assets.sql`
- Create: `backend/schema/18_market.sql`
- Modify: `backend/schema/20_contracts.sql`
- Create: `backend/schema/25_bible.sql`
- Modify: `backend/schema/30_planning.sql`
- Modify: `backend/schema/40_drafts.sql`
- Modify: `backend/schema_manifest.py`
- Modify: `backend/schema_version.py`
- Modify: `backend/domain/planning.py`
- Modify: `backend/domain/drafts.py`
- Modify: `backend/domain/story_engines.py`
- Modify: `backend/domain/contracts.py`
- Modify: `backend/repositories/seeds.py`
- Modify: `backend/repositories/assets.py`
- Modify: `backend/repositories/projects.py`
- Modify: `backend/repositories/story_engines.py`
- Modify: `backend/repositories/contracts.py`
- Modify: `backend/repositories/planning.py`
- Modify: `backend/repositories/chapter_sessions.py`
- Modify: `backend/services/seeds.py`
- Modify: `backend/services/story_engines.py`
- Modify: `backend/services/contracts.py`
- Modify: `backend/services/planning.py`
- Modify: `backend/services/chapter_sessions.py`
- Modify: `backend/routers/seeds.py`
- Modify: `backend/routers/story_engines.py`
- Modify: `backend/routers/contracts.py`
- Modify: `backend/scripts/reset_writer_core_data.py`
- Modify: `backend/scripts/prepare_milestone1_browser_db.py`
- Modify: `backend/scripts/prepare_milestone2_browser_db.py`
- Modify: `backend/scripts/verify_milestone2_product.py`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Modify: `backend/tests/unit/test_schema_version.py`
- Modify: `backend/tests/unit/test_reset_writer_core_data.py`
- Modify: `backend/tests/integration/test_schema_bootstrap.py`
- Modify: `backend/tests/integration/test_milestone2_product_rebuild.py`
- Modify: `backend/tests/unit/test_seed_service.py`
- Modify: `backend/tests/unit/test_project_creation.py`
- Modify: `backend/tests/unit/test_story_engine_service.py`
- Modify: `backend/tests/unit/test_contract_service.py`
- Modify: `backend/tests/unit/test_planning_service.py`
- Modify: `backend/tests/unit/test_chapter_session_service.py`
- Modify: `backend/tests/api/test_seed_routes.py`
- Modify: `backend/tests/api/test_story_engine_routes.py`
- Modify: `backend/tests/api/test_contract_routes.py`
- Modify: `backend/tests/api/test_planning_routes.py`
- Modify: `backend/tests/api/test_chapter_session_routes.py`
- Modify: `backend/tests/integration/test_seed_revisions.py`
- Modify: `backend/tests/integration/test_story_engine_batches.py`
- Modify: `backend/tests/integration/test_contract_drafts.py`
- Modify: `backend/tests/integration/test_contract_confirmation.py`

- [ ] **Step 1: Write failing schema contracts**

Assert:

```python
assert EXPECTED_SCHEMA_VERSION == "writer-core-v1.3.0"
assert FRAGMENTS == (
    "00_metadata.sql", "10_core.sql", "12_application.sql",
    "15_assets.sql", "18_market.sql", "20_contracts.sql",
    "25_bible.sql", "30_planning.sql", "40_drafts.sql",
    "50_canon.sql", "60_projections.sql", "70_corpus.sql",
)
```

Also assert every active-chain table stores `selection_revision`; all Bible rows
store contract revision/hash; market snapshots and corpus revisions are
immutable; application settings have one singleton row; and normal application
startup still performs only schema metadata verification.

Keep `project_selected_seeds` as the single active head and add immutable
history:

```text
project_seed_selection_revisions
  primary key (project_id, selection_revision)
  exact seed revision/hash and selected_at

project_selected_seeds
  one row per project
  active selection revision plus exact seed revision/hash
  foreign key to the immutable selection revision
```

Engines, contracts, Bibles, planning roots, and chapter sessions reference the
immutable `(project_id, selection_revision)` identity. A head change never
updates a historical selection row.

- [ ] **Step 2: Run the schema tests red**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/integration/test_schema_bootstrap.py -q
```

Expected: fail because v1.3 fragments and contracts do not exist.

- [ ] **Step 3: Add the exact schema**

Define:

- `application_settings(singleton_id, fallback_provider_id, revision,
  updated_at)`;
- `corpus_blobs(content_hash, byte_length, storage_key, created_at)`;
- logical corpus source identity, immutable source revisions, active head, and
  archive timestamps; each source revision freezes author-supplied display name,
  reference tags, notes, and provenance separately from content identity;
- market source, refresh state, snapshot, entry, snapshot manifest, and analysis
  tables;
- Provider profile revision plus idempotent mutation-request ledger;
- market source policy/schedule revision, enabled flag, interval, next run, and
  lease state;
- seed-inspiration, asset-recommendation, and style-trial attempt/request
  ledgers with input manifest hash, idempotency key, status, and safe result
  identity;
- `selection_revision` on story-engine batches/options, contract drafts,
  creation contracts, and confirmation requests;
- fragment-level contract refs with source revision/hash, chapter/fragment ID,
  fragment hash, character range, use, and order;
- Bible drafts, generation attempts, immutable revisions, head, and confirmation
  requests;
- selection/contract/Bible revision+hash refs on each planning root;
- selection/contract/Bible/planning manifest refs on each chapter session.

Story-block/stage/scene rows inherit their generation through the immutable
planning root. Working drafts and candidates inherit it through the immutable
chapter session. Update the existing planning/session services and their tests
to populate and validate these refs even though Phase 2 does not expose new
Planning or Writer navigation.

Chapter-session upstream refs are immutable after insert; only session status
and finalization timestamp may change. Every query that returns an active
session, working draft, or candidate must join the session and compare its
selection, contract, Bible, and planning manifest identity to the current
project heads. Mismatch returns read-only `superseded`, never active.

The schema manifest inserts exactly one revision-0 application-settings row and
no external-source data. Project creation and the guarded reset insert a
revision-0 Bible head in the same bootstrap transaction as the existing
contract head. There is no request-time “ensure row exists” fallback.

Provider lifecycle states are exact:

```text
active       key and Base URL present; enabled may be true or false
unconfigured key empty; Base URL may remain; enabled false; not deleted
deleted      key and Base URL empty; enabled false; deleted_at present
```

Every Provider mutation increments `revision`. Clear-key idempotency and result
recovery use the request ledger. All FKs from immutable history to referenced
seed/selection/asset/corpus/contract/Bible revisions use `RESTRICT`; a service
dependency-count defect must not cascade-delete historical chains.

Mechanically update every existing selected-seed reader and write path before
the schema commit: seed selection inserts one immutable selection row then CAS
updates the active head; story-engine, contract, planning, and session
repositories read the active head and persist its generation. The existing M1/M2
browser preparation scripts remain test setup only, but must create valid v1.3
rows until their obsolete M2 runner is deleted in Phase 2C. No runtime fallback
may read an old table shape.

Use project ownership FKs, immutable unique identities, CHECK constraints,
InnoDB, and `utf8mb4_0900_ai_ci`. Do not add `ALTER TABLE`, `IF NOT EXISTS`,
runtime DDL, or compatibility readers.

- [ ] **Step 4: Reconcile the explicit development reset**

The reset remains a guarded reset, not a migration. Update its target to v1.3
and preserve only the approved project identity, three seeds, and Provider
configuration. Recreate all derived tables empty. Do not run it against the
product database in this package.

Update the frozen-source fixture/test so only explicitly recognized current
source manifests are accepted. Unknown source/hash aborts before DROP.

- [ ] **Step 5: Run disposable MySQL green**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_seed_service.py backend/tests/unit/test_project_creation.py backend/tests/unit/test_story_engine_service.py backend/tests/unit/test_contract_service.py backend/tests/unit/test_planning_service.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_seed_routes.py backend/tests/api/test_story_engine_routes.py backend/tests/api/test_contract_routes.py backend/tests/api/test_planning_routes.py backend/tests/api/test_chapter_session_routes.py backend/tests/integration/test_seed_revisions.py backend/tests/integration/test_story_engine_batches.py backend/tests/integration/test_contract_drafts.py backend/tests/integration/test_contract_confirmation.py backend/tests/integration/test_schema_bootstrap.py backend/tests/integration/test_milestone2_product_rebuild.py -q
```

Expected: fresh v1.3 creates in exact order; wrong version/hash fails closed;
reset tests use only disposable databases.

- [ ] **Step 6: Commit**

```powershell
git add backend/schema backend/schema_manifest.py backend/schema_version.py backend/domain/planning.py backend/domain/drafts.py backend/domain/story_engines.py backend/domain/contracts.py backend/repositories/seeds.py backend/repositories/assets.py backend/repositories/projects.py backend/repositories/story_engines.py backend/repositories/contracts.py backend/repositories/planning.py backend/repositories/chapter_sessions.py backend/services/seeds.py backend/services/story_engines.py backend/services/contracts.py backend/services/planning.py backend/services/chapter_sessions.py backend/routers/seeds.py backend/routers/story_engines.py backend/routers/contracts.py backend/scripts/reset_writer_core_data.py backend/scripts/prepare_milestone1_browser_db.py backend/scripts/prepare_milestone2_browser_db.py backend/scripts/verify_milestone2_product.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_seed_service.py backend/tests/unit/test_project_creation.py backend/tests/unit/test_story_engine_service.py backend/tests/unit/test_contract_service.py backend/tests/unit/test_planning_service.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_seed_routes.py backend/tests/api/test_story_engine_routes.py backend/tests/api/test_contract_routes.py backend/tests/api/test_planning_routes.py backend/tests/api/test_chapter_session_routes.py backend/tests/integration/test_seed_revisions.py backend/tests/integration/test_story_engine_batches.py backend/tests/integration/test_contract_drafts.py backend/tests/integration/test_contract_confirmation.py backend/tests/integration/test_schema_bootstrap.py backend/tests/integration/test_milestone2_product_rebuild.py
git commit -m "feat: establish phase two schema"
```

## Task 2: Finish the write-only Provider boundary

**Files:**

- Modify: `backend/routers/providers.py`
- Modify: `backend/serializers/provider.py`
- Create: `backend/services/provider_profiles.py`
- Create: `backend/gateways/provider_connection.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/api/test_provider_redaction.py`
- Modify: `backend/tests/control_plane/test_provider_public_boundary.py`
- Create: `backend/tests/unit/test_provider_profile_service.py`
- Create: `backend/tests/unit/test_provider_connection_gateway.py`
- Modify: `frontend/src/stores/providerStore.js`
- Modify: `frontend/src/components/settings/ProviderForm.vue`
- Modify: `frontend/src/components/settings/ProviderSettings.vue`
- Modify: `frontend/tests/unit/providerRedaction.test.mjs`
- Create: `frontend/tests/unit/providerSettings.test.mjs`

- [ ] **Step 1: Write failing public-boundary tests**

For list/create/update/delete/test/clear responses and every handled error,
recursively reject:

```text
apiKey api_key baseURL base_url authorization token password
```

Test connection must return exactly:

```json
{"ok":true,"code":"connected","latencyMs":12,"publicMessage":"连接成功"}
```

The gateway receives saved secret fields through a private repository projection,
uses a bounded timeout and no retry, and maps upstream errors to fixed public
codes without returning URL, headers, body, or exception text.

- [ ] **Step 2: Run focused tests red**

```powershell
python -m pytest backend/tests/api/test_provider_redaction.py backend/tests/control_plane/test_provider_public_boundary.py backend/tests/unit/test_provider_profile_service.py backend/tests/unit/test_provider_connection_gateway.py -q
node --test frontend/tests/unit/providerRedaction.test.mjs frontend/tests/unit/providerSettings.test.mjs
```

- [ ] **Step 3: Move Provider writes into a transaction service**

Keep HTTP parsing in the router, secret access in the repository/service, and
connection behavior in the gateway. Add:

```text
POST /api/providers/:providerId/test-connection
POST /api/providers/:providerId/clear-api-key
```

`clear-api-key` requires the current Provider revision and an idempotency key,
clears the API key atomically, disables the Provider, preserves the private Base
URL, and returns only the public projection. Blank update fields continue to
mean preserve. Soft-delete remains the only command that wipes both key and Base
URL.

- [ ] **Step 4: Make the form secret-ephemeral**

The edit form always opens with blank secret/Base URL fields. The component owns
these values locally; Pinia never stores them. Clear the local values in
`finally`, on close, and on unmount. One red danger dialog is required only for
clear API key. Connection test feedback uses toast/status text and never echoes
configuration.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest backend/tests/api/test_provider_redaction.py backend/tests/control_plane/test_provider_public_boundary.py backend/tests/unit/test_provider_profile_service.py backend/tests/unit/test_provider_connection_gateway.py -q
node --test frontend/tests/unit/providerRedaction.test.mjs frontend/tests/unit/providerSettings.test.mjs
git add backend/routers/providers.py backend/serializers/provider.py backend/services/provider_profiles.py backend/gateways/provider_connection.py backend/main.py backend/tests frontend/src/stores/providerStore.js frontend/src/components/settings/ProviderForm.vue frontend/src/components/settings/ProviderSettings.vue frontend/tests/unit/providerRedaction.test.mjs frontend/tests/unit/providerSettings.test.mjs
git commit -m "feat: complete provider secret boundary"
```

## Task 3: Add global fallback and correct project-binding inheritance

**Files:**

- Create: `backend/domain/application_settings.py`
- Create: `backend/repositories/application_settings.py`
- Create: `backend/services/application_settings.py`
- Create: `backend/routers/application_settings.py`
- Modify: `backend/repositories/model_bindings.py`
- Modify: `backend/services/model_bindings.py`
- Modify: `backend/services/project_lifecycle.py`
- Modify: `backend/main.py`
- Create: `backend/tests/unit/test_application_settings_service.py`
- Modify: `backend/tests/unit/test_model_binding_service.py`
- Modify: `backend/tests/integration/test_model_binding_revisions.py`
- Create: `frontend/src/stores/applicationSettingsStore.js`
- Create: `frontend/src/views/ApplicationSettingsView.vue`
- Create: `frontend/src/views/ProjectModelSettingsView.vue`
- Move: `frontend/src/components/settings/TaskModelBinding.vue` to
  `frontend/src/components/project/settings/TaskModelBinding.vue`
- Modify: `frontend/src/components/settings/ProviderSettings.vue`
- Create: `frontend/src/stores/modelBindingStore.js`
- Modify: `frontend/src/stores/providerStore.js`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/tests/unit/modelBindingStore.test.mjs`
- Modify: `frontend/tests/unit/projectRoutes.test.mjs`
- Modify: `frontend/tests/unit/productShell.test.mjs`

- [ ] **Step 1: Write inheritance matrix tests**

Cover:

1. inherit the complete eight-task snapshot of the most recently created,
   unarchived, fully Ready project;
2. same creation time resolves by project ID stable order;
3. never inherit a partial/stale/not-ready snapshot task-by-task;
4. otherwise bind all eight tasks to the Ready explicit fallback;
5. otherwise bind all eight to the first Ready Provider ordered by
   `(sort_order, created_at, id)`;
6. otherwise create eight `unbound` items and allow project creation.

- [ ] **Step 2: Run red**

```powershell
python -m pytest backend/tests/unit/test_application_settings_service.py backend/tests/unit/test_model_binding_service.py backend/tests/integration/test_model_binding_revisions.py -q
node --test frontend/tests/unit/modelBindingStore.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
```

- [ ] **Step 3: Implement application settings and inheritance**

Expose:

```text
GET /api/settings/application
PUT /api/settings/application/default-model
GET /api/settings/application/diagnostics
```

The PUT accepts `expectedRevision` and nullable `fallbackProviderId`, validates
readiness under the same transaction, and CAS-updates the singleton. Public
responses contain Provider display/model identity only.

Diagnostics return only schema version/manifest match, database reachability,
managed-corpus-store readiness, scheduler enabled/state, and application
version. They never return DB host/port/name/user, DSN, filesystem paths,
Provider configuration, environment values, or exception text.

Replace per-task inheritance/repair with whole-snapshot inheritance. Saving a
project binding remains an atomic eight-item revision.

Split project binding state and commands out of `providerStore.js` into the new
`modelBindingStore.js`; the Provider store retains only global Provider profile
state. Update the existing model-binding tests to import the new store.

- [ ] **Step 4: Split global and project UI**

`/settings/providers` manages Provider profiles only.
`/settings/application` manages the new-project fallback and safe diagnostics.
`/projects/:projectId/settings/models` defaults to one selector applying to all
tasks; an Advanced disclosure exposes eight selectors. Show the inherited
source/revision and readiness reasons. Archived projects are read-only.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_application_settings_service.py backend/tests/unit/test_model_binding_service.py backend/tests/integration/test_model_binding_revisions.py backend/tests/api/test_model_binding_routes.py -q
node --test frontend/tests/unit/modelBindingStore.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
git add backend frontend
git commit -m "feat: add model fallback and project bindings"
```

## Task 4: Replace Settings assets with global Creative Assets pages

**Files:**

- Modify: `backend/services/assets.py`
- Create: `backend/services/creative_assets.py`
- Create: `backend/domain/asset_eligibility.py`
- Create:
  `backend/assets/recommendation-taxonomy-v1.0.0/manifest.json`
- Create:
  `backend/assets/recommendation-taxonomy-v1.0.0/eligibility.json`
- Modify: `backend/routers/assets.py`
- Modify: `backend/tests/api/test_asset_routes.py`
- Create: `backend/tests/unit/test_asset_eligibility_manifest.py`
- Create: `frontend/src/views/assets/StyleLibraryView.vue`
- Create: `frontend/src/views/assets/ExperienceLibraryView.vue`
- Create: `frontend/src/components/assets/AssetDetailDrawer.vue`
- Modify: `frontend/src/stores/creationAssetStore.js`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/src/components/layout/Sidebar.vue`
- Modify: `frontend/src/components/layout/TopBar.vue`
- Delete: `frontend/src/components/settings/CreationAssetSettings.vue`
- Delete: `frontend/src/views/ExperienceCardsView.vue`
- Delete: `frontend/src/data/experienceCardProduct.js`
- Delete: `frontend/src/data/realCorpusExperienceCards.v3.json`
- Modify: `frontend/tests/unit/creationAssetStore.test.mjs`
- Modify: `frontend/tests/unit/projectRoutes.test.mjs`
- Modify: `frontend/tests/unit/productShell.test.mjs`
- Create: `frontend/tests/unit/creativeAssetViews.test.mjs`

- [ ] **Step 1: Write failing inventory and routing tests**

API inventory derives counts/package version from the seeded heads and never
hard-codes `10/64` in UI. Add search/filter tests for stable key, title, name,
category, genre, stage, and status. Route tests cover direct navigation,
refresh, Back/Forward, titles, breadcrumbs, and global sidebar selection.

The separate recommendation-taxonomy package maps every approved style/card
stable key and exact current asset hash to typed:

```text
genres
channels
creationStages
writingPurposes
prohibitedDirections
```

Its manifest is release-validated and content-hashed. Deterministic eligibility
uses only this typed metadata; it never infers eligibility by keyword-searching
free-text applicability fields. Updating recommendation metadata creates a new
taxonomy package version and never mutates the approved 10+64 asset package.

- [ ] **Step 2: Run red**

```powershell
python -m pytest backend/tests/api/test_asset_routes.py -q
node --test frontend/tests/unit/creationAssetStore.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs frontend/tests/unit/creativeAssetViews.test.mjs
```

- [ ] **Step 3: Implement canonical pages**

Add `/assets/styles` and `/assets/experience`. Both provide search, filters,
empty/error/retry states, version badges, and bounded detail drawers. Style
detail presents its approved example and use boundaries. Experience detail
presents the method, positive/negative examples, and usage without an
activation/publishing workflow.

`CreativeAssetService` is the public composition boundary used by the asset and
corpus routers. It delegates immutable system-asset reads and corpus lifecycle
to focused internal services; it does not duplicate their rules.

- [ ] **Step 4: Remove the parallel localStorage asset source**

Remove the listed files and every import/runtime persistence path that treats
frontend data as system-asset truth. Keep the approved backend 10+64 package
unchanged. `writingStyleStandards.js`, its sample micro-demo files, and
`realCorpusExperienceCardsV3.js` remain temporarily quarantined only because the
legacy Writer prompts still import them; they are not imported by canonical
Creative Assets/Contract pages and must be removed with the Phase 4 Writer
replacement. Do not break their live import graph in Phase 2A.

- [ ] **Step 5: Run release asset validation and commit**

```powershell
python -c "from pathlib import Path; from backend.domain.assets import load_asset_package; p=load_asset_package(Path('backend/assets/writer-core-v1.1.0/manifest.json'), mode='release'); print(len(p.styles), len(p.experience_cards))"
python -m pytest backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py backend/tests/unit/test_asset_eligibility_manifest.py backend/tests/api/test_asset_routes.py -q
node --test frontend/tests/unit/creationAssetStore.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs frontend/tests/unit/creativeAssetViews.test.mjs
git add backend frontend
git commit -m "feat: promote creative assets to product navigation"
```

Expected asset output: `10 64`.

## Task 5: Build content-addressed corpus storage and lifecycle

**Files:**

- Modify: `backend/domain/corpus.py`
- Modify: `backend/repositories/corpus.py`
- Modify: `backend/services/corpus_import.py`
- Create: `backend/services/corpus_library.py`
- Modify: `backend/routers/corpus.py`
- Modify: `backend/config.py`
- Modify: `backend/security/paths.py`
- Modify: `backend/tests/unit/test_corpus_discovery.py`
- Modify: `backend/tests/unit/test_corpus_paths.py`
- Create: `backend/tests/unit/test_corpus_library_service.py`
- Modify: `backend/tests/integration/test_corpus_import.py`
- Modify: `backend/tests/api/test_corpus_routes.py`
- Create: `frontend/src/views/assets/CorpusLibraryView.vue`
- Create: `frontend/src/components/assets/CorpusImportDialog.vue`
- Create: `frontend/src/components/assets/CorpusLifecycleMenu.vue`
- Modify: `frontend/src/stores/corpusStore.js`
- Modify: `frontend/src/router/projectRoutes.js`
- Delete: `frontend/src/components/settings/CorpusSettings.vue`
- Modify: `frontend/tests/unit/corpusStore.test.mjs`
- Create: `frontend/tests/unit/corpusLibraryView.test.mjs`

- [ ] **Step 1: Write failing CAS/lifecycle tests**

Prove:

- importing equal bytes from two paths creates one blob and distinct provenance
  only when the author chooses a distinct logical source;
- importing changed bytes creates a new immutable revision/head;
- display name/tags/notes are normalized, bounded, revisioned search metadata
  and never alter blob identity;
- deleting/moving the original file does not affect detail/fragment reads;
- a failed file copy or parse publishes no source revision;
- archive/restore is CAS and idempotent;
- referenced current/historical revisions cannot be physically deleted;
- an unreferenced archived revision needs one explicit danger command;
- storage keys are derived only from SHA-256 and never accept user paths;
- public responses never expose storage root, absolute source path, full raw
  bytes, or an unbounded excerpt.

- [ ] **Step 2: Run red**

```powershell
python -m pytest backend/tests/unit/test_corpus_decoding.py backend/tests/unit/test_corpus_parser.py backend/tests/unit/test_corpus_fragmenter.py backend/tests/unit/test_corpus_discovery.py backend/tests/unit/test_corpus_paths.py backend/tests/unit/test_corpus_library_service.py backend/tests/integration/test_corpus_import.py backend/tests/api/test_corpus_routes.py -q
```

- [ ] **Step 3: Implement stage/publish storage**

Read and hash the source outside a database transaction. Stage a same-filesystem
temporary blob under the configured managed corpus root, parse normalized
content, then inside one transaction insert/reuse the blob, insert immutable
source revision and fragments, and CAS the head. Finalizing a content-addressed
blob is idempotent. A failure before finalization deletes only the runner-owned
staging file. A database failure after finalization may leave an unreferenced
immutable blob; it publishes no source revision and a later identical import
reuses it. Never delete a finalized shared blob during rollback.

Never infer content identity from relative path. Keep provenance display name
and safe relative source label separate from the blob key.

- [ ] **Step 4: Implement library commands and UI**

Expose list/search/filter/detail/version/archive/restore/permanent-delete routes.
Add `/assets/corpus` with explicit Import, version history, bounded preview,
archive/restore, reference count, and one danger dialog for eligible permanent
delete. Import collects an optional display name, reference tags, and short
notes for later bounded retrieval. Referenced versions explain why delete is
unavailable and offer Archive.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_corpus_decoding.py backend/tests/unit/test_corpus_parser.py backend/tests/unit/test_corpus_fragmenter.py backend/tests/unit/test_corpus_discovery.py backend/tests/unit/test_corpus_paths.py backend/tests/unit/test_corpus_library_service.py backend/tests/integration/test_corpus_import.py backend/tests/api/test_corpus_routes.py -q
node --test frontend/tests/unit/corpusStore.test.mjs frontend/tests/unit/corpusLibraryView.test.mjs frontend/tests/unit/projectRoutes.test.mjs
git add backend frontend
git commit -m "feat: add managed corpus library"
```

## Task 6: Phase 2A browser and command gate

**Files:**

- Create: `frontend/e2e/phase2a-assets-settings.spec.ts`
- Create: `frontend/e2e/run-phase2a.mjs`
- Create: `frontend/playwright.phase2a.config.ts`
- Modify: `frontend/package.json`
- Modify: `package.json`
- Modify: `scripts/run-tests.mjs`
- Modify: `scripts/tests/run-tests.test.mjs`
- Create: `scripts/tests/phase2aSuite.test.mjs`
- Create: `docs/acceptance/2026-07-18-phase-2a-assets-providers.md`

- [ ] **Step 1: Build a disposable runner**

Reuse the Phase 1 runner's random DB, bounded ports, child cleanup, and sentinel
scanning. Seed synthetic Provider secrets but inject a fake connection gateway;
do not make external calls. Create a runner-owned corpus root and synthetic text.

- [ ] **Step 2: Write browser behaviors**

Verify all global routes, 10/64 inventory, asset search/details, corpus
import/version/archive/restore/delete protection, Provider edit/test/clear
secret behavior, global fallback, and project simple/advanced model binding.
Scan page, network bodies, console, service logs, screenshots, and report text
for secret/root sentinels.

- [ ] **Step 3: Register executable root commands**

Add root `build` as `npm --prefix frontend run build` and
`test:browser:phase2a` as the new runner. Add behavioral command-contract tests.
The old M2 Settings spec remains quarantined until Phase 2C extracts its shared
runner helpers and deletes the complete old M2 browser authority; it is not
executed or cited by Phase 2A acceptance.

- [ ] **Step 4: Run package gates**

```powershell
npm run test:browser:phase2a
npm test
npm run test:integration
npm run build
git diff --check
git status --short
```

Expected: all pass; integration created/cleaned counts match and remaining is
zero; only the acceptance report remains to be completed if it records the
fresh outputs.

- [ ] **Step 5: Independent review and commit**

Run spec and quality reviews, fix all Critical/Important findings, rerun the
gates, complete the acceptance report, and commit:

```powershell
git add frontend/e2e frontend/playwright.phase2a.config.ts frontend/package.json package.json scripts docs/acceptance/2026-07-18-phase-2a-assets-providers.md
git commit -m "test: accept phase two assets and settings"
```
