# M2A Schema, Domain, Seeds, and Bindings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the M1 placeholders as `writer-core-v1.1.0` and deliver immutable seed revisions, seed selection, versioned eight-task model bindings, Provider soft deletion, and contract head revision 0 without invoking a Provider.

**Architecture:** Strict frozen domain values own canonical JSON and hashes. Session-bound repositories own SQL, services own transactions and CAS, and project creation delegates binding initialization rather than embedding binding rules. The empty-schema manifest remains the only DDL path; there is no runtime migration or compatibility layer.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, aiomysql, MySQL 8.4, pytest.

---

### Task 0: Reproducible isolated Python environment

**Files:**
- Create: `backend/requirements-m2.lock.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Write the exact resolved lock**

```text
fastapi==0.115.0
starlette==0.38.6
uvicorn==0.49.0
pydantic==2.13.4
httpx==0.28.1
aiomysql==0.2.0
pytest==8.4.2
pytest-asyncio==0.26.0
annotated-types==0.7.0
anyio==4.12.1
certifi==2026.2.25
click==8.3.1
colorama==0.4.6
h11==0.16.0
httpcore==1.0.9
idna==3.11
iniconfig==2.3.0
packaging==26.0
pluggy==1.6.0
pydantic-core==2.46.4
Pygments==2.20.0
PyMySQL==1.1.1
sniffio==1.3.1
typing-extensions==4.15.0
typing-inspection==0.4.2
```

- [ ] **Step 2: Ignore only the local virtual environment directory**

Add `.venv-m2/` under Python caches/dependencies in `.gitignore`; do not ignore lock files.

- [ ] **Step 3: Create and populate the isolated environment**

```powershell
py -3.12 -m venv .venv-m2
& .\.venv-m2\Scripts\Activate.ps1
python -m pip install pip==25.0.1
python -m pip install -r backend/requirements-m2.lock.txt
```

- [ ] **Step 4: Verify dependency consistency**

```powershell
python -m pip check
python -c "import fastapi,starlette,uvicorn,pydantic,httpx,aiomysql,pytest; print('m2-venv-ready')"
```

Expected: `pip check` reports no broken requirements and the import command prints `m2-venv-ready`. Machine-global `pip check` results are irrelevant and must not be recorded as M2 evidence.

- [ ] **Step 5: Commit the reproducibility boundary**

```powershell
git add backend/requirements-m2.lock.txt .gitignore
git commit -m "build: lock M2 Python environment"
```

Every later Python command in all M2 plans assumes `.venv-m2` is activated in that execution shell.

### Task 1: Canonical JSON, seed values, and binding values

**Files:**
- Create: `backend/domain/json_contracts.py`
- Create: `backend/domain/seeds.py`
- Create: `backend/domain/model_bindings.py`
- Create: `backend/tests/unit/test_m2_json_contracts.py`
- Create: `backend/tests/unit/test_seed_domain.py`
- Create: `backend/tests/unit/test_model_bindings.py`

- [ ] **Step 1: Write strict-domain RED tests**

```python
from pydantic import ValidationError
import pytest

from backend.domain.json_contracts import canonical_hash
from backend.domain.model_bindings import TASK_KEYS, BindingItem, BindingRevision
from backend.domain.seeds import SeedPayload


def test_seed_payload_is_strict_and_hash_is_stable():
    payload = SeedPayload(
        title="典镇山河", genre="架空历史穿越", logline="以典籍与工艺重建秩序",
        protagonist="沈砚", desire="活下去并掌握选择权", coreConflict="知识与权力争夺",
        worldPressure="秩序崩坏", openingHook="典籍异变", differentiation="文明经营群像",
    )
    assert canonical_hash(payload) == canonical_hash(SeedPayload.model_validate(payload.model_dump()))
    with pytest.raises(ValidationError):
        SeedPayload.model_validate({**payload.model_dump(), "legacyField": True})


def test_binding_revision_always_contains_eight_keys_and_can_be_unbound():
    items = tuple(BindingItem(task_key=key, resolution_status="unbound") for key in TASK_KEYS)
    revision = BindingRevision(project_id="p1", revision=1, items=items)
    assert len(revision.items) == 8
    assert revision.binding_complete is True
    assert revision.binding_ready is False
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_m2_json_contracts.py backend/tests/unit/test_seed_domain.py backend/tests/unit/test_model_bindings.py -q
```

Expected: collection fails only because the three new domain modules/types do not exist.

- [ ] **Step 3: Implement the minimal strict values**

```python
# backend/domain/json_contracts.py
import hashlib
import json
from pydantic import BaseModel


def canonical_json(value: BaseModel | dict) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: BaseModel | dict) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
```

```python
# backend/domain/model_bindings.py
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

TASK_KEYS = ("seed", "planning", "writing", "audit", "summary", "extraction", "polish", "market")


class BindingItem(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    task_key: Literal["seed", "planning", "writing", "audit", "summary", "extraction", "polish", "market"]
    resolution_status: Literal["bound", "unbound"]
    provider_id: str | None = None
    provider_name_snapshot: str | None = None
    model_name_snapshot: str | None = None

    @model_validator(mode="after")
    def validate_resolution(self):
        values = (self.provider_id, self.provider_name_snapshot, self.model_name_snapshot)
        if self.resolution_status == "bound" and not all(values):
            raise ValueError("bound item requires provider and model snapshots")
        if self.resolution_status == "unbound" and any(value is not None for value in values):
            raise ValueError("unbound item cannot carry provider fields")
        return self


class BindingRevision(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    project_id: str = Field(min_length=1)
    revision: int = Field(gt=0)
    items: tuple[BindingItem, ...]

    @model_validator(mode="after")
    def validate_task_set(self):
        if tuple(sorted(item.task_key for item in self.items)) != tuple(sorted(TASK_KEYS)):
            raise ValueError("binding revision must contain every task exactly once")
        return self

    @property
    def binding_complete(self) -> bool:
        return len(self.items) == len(TASK_KEYS)

    @property
    def binding_ready(self) -> bool:
        return self.binding_complete and all(item.resolution_status == "bound" for item in self.items)
```

Implement `SeedPayload` with exactly the nine fields shown in the RED test, `ConfigDict(strict=True, frozen=True, extra="forbid")`, and non-empty bounded strings.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the Step 2 command. Expected: all focused domain tests pass and no DB/network fixture is created.

- [ ] **Step 5: Commit the domain contract**

```powershell
git add backend/domain/json_contracts.py backend/domain/seeds.py backend/domain/model_bindings.py backend/tests/unit/test_m2_json_contracts.py backend/tests/unit/test_seed_domain.py backend/tests/unit/test_model_bindings.py
git commit -m "feat: define M2 immutable domain values"
```

### Task 2: Rebuild the exact v1.1 Schema and manifest

**Files:**
- Modify: `backend/schema/10_core.sql`
- Create: `backend/schema/15_assets.sql`
- Modify: `backend/schema/20_contracts.sql`
- Modify: `backend/schema/70_corpus.sql`
- Modify: `backend/schema_manifest.py`
- Modify: `backend/schema_version.py`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Modify: `backend/tests/unit/test_schema_version.py`
- Modify: `backend/tests/unit/test_initialize_database.py`
- Modify: `backend/tests/integration/test_schema_bootstrap.py`

- [ ] **Step 1: Change tests to the approved v1.1 contract**

```python
from backend.schema_manifest import FRAGMENTS, created_table_names
from backend.schema_version import EXPECTED_SCHEMA_VERSION


def test_m2_schema_fragment_order_and_removed_placeholders():
    assert EXPECTED_SCHEMA_VERSION == "writer-core-v1.1.0"
    assert FRAGMENTS[:4] == ("00_metadata.sql", "10_core.sql", "15_assets.sql", "20_contracts.sql")
    names = set(created_table_names())
    assert {"creative_seed_revisions", "creative_seed_heads", "project_model_binding_revisions",
            "project_model_binding_items", "project_model_binding_heads", "style_template_heads",
            "experience_card_heads", "story_engine_batches", "project_contract_heads",
            "contract_confirmation_requests", "corpus_import_runs", "corpus_fragments"} <= names
    assert {"task_model_bindings", "task_model_binding_items", "contract_asset_refs"}.isdisjoint(names)
```

Add Disposable MySQL assertions for composite seed FKs, global assets without `project_id`, and successful creation of specialized reference FKs. After the test explicitly inserts one foundation project fixture, assert its eight binding task rows and revision-0 contract head; an empty Schema bootstrap does not create business rows by itself.

- [ ] **Step 2: Verify the schema tests are RED**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q
```

Expected: v1.0/version/fragment/table assertions fail.

- [ ] **Step 3: Implement the approved DDL in dependency order**

Set:

```python
FRAGMENTS = (
    "00_metadata.sql", "10_core.sql", "15_assets.sql", "20_contracts.sql",
    "30_planning.sql", "40_drafts.sql", "50_canon.sql", "60_projections.sql", "70_corpus.sql",
)
EXPECTED_SCHEMA_VERSION = "writer-core-v1.1.0"
```

Implement every table, column, state check, PK, unique key and FK from sections 5.6–5.7 of the approved spec. Keep these non-negotiable SQL rules:

```sql
CREATE TABLE creative_seed_heads (
  seed_id CHAR(36) PRIMARY KEY,
  revision_id CHAR(36) NOT NULL,
  revision INT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE KEY uq_seed_head_pair (seed_id, revision_id),
  FOREIGN KEY (seed_id, revision_id)
    REFERENCES creative_seed_revisions(seed_id, id) ON DELETE RESTRICT,
  CHECK (revision > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

```sql
CREATE TABLE project_contract_heads (
  project_id CHAR(36) PRIMARY KEY,
  revision INT NOT NULL DEFAULT 0,
  creation_contract_id CHAR(36) NULL,
  style_contract_id CHAR(36) NULL,
  creation_hash CHAR(64) NULL,
  style_hash CHAR(64) NULL,
  updated_at BIGINT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK ((revision=0 AND creation_contract_id IS NULL AND style_contract_id IS NULL
          AND creation_hash IS NULL AND style_hash IS NULL)
      OR (revision>0 AND creation_contract_id IS NOT NULL AND style_contract_id IS NOT NULL
          AND creation_hash IS NOT NULL AND style_hash IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

Place global style/experience/corpus revision and head tables in `15_assets.sql` so `20_contracts.sql` can create real FKs. Leave planning/draft/Canon/projection tables functionally unchanged. Remove project-scoped asset placeholders and the loose polymorphic ref.

- [ ] **Step 4: Verify unit and Disposable MySQL GREEN**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q
python -m pytest backend/tests/integration/test_schema_bootstrap.py -m mysql -q
```

Expected: both exit 0; fresh MySQL reports v1.1 and every FK creates in manifest order.

- [ ] **Step 5: Keep the verified Schema change uncommitted until Task 3 adapts all explicit callers**

```powershell
git status --short
```

Expected: only the Task 2 Schema/version/tests are modified. Do not create an intermediate commit that makes reset/bootstrap target removed tables.

### Task 3: Adapt explicit reset/bootstrap foundation creation

**Files:**
- Modify: `backend/scripts/reset_writer_core_data.py`
- Modify: `backend/scripts/bootstrap_writer_core_product.py`
- Modify: `backend/tests/unit/test_reset_writer_core_data.py`
- Modify: `backend/tests/unit/test_bootstrap_writer_core_product.py`
- Modify: `backend/tests/integration/test_reset_writer_core_data.py`
- Modify: `backend/tests/integration/test_bootstrap_writer_core_product.py`

- [ ] **Step 1: Write RED assertions for the new foundation**

Assert each preserved seed creates identity/revision 1/head; `典镇山河` selection references its exact revision/hash; binding revision 1 has eight items; contract head is revision 0; Provider lifecycle is active; Canon/Projection remain 0; every M2 derived table is empty.

- [ ] **Step 2: Run and verify RED against old INSERTs**

```powershell
python -m pytest backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_bootstrap_writer_core_product.py -q
```

Expected: old seed/binding table assumptions fail without accessing a real DB.

- [ ] **Step 3: Replace only the foundation insertion map**

Use `canonical_hash(SeedPayload(...))` for seed revision hashes. Insert in this order inside the existing single transaction: projects, Provider profiles, seed identities, seed revisions, seed heads, selected seed, binding revision, eight binding items, binding head, Canon 0, projection head 0, contract head 0. Do not preserve old contracts/assets/corpus/chapters.

- [ ] **Step 4: Run unit and disposable integration GREEN**

```powershell
python -m pytest backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_bootstrap_writer_core_product.py -q
python -m pytest backend/tests/integration/test_reset_writer_core_data.py backend/tests/integration/test_bootstrap_writer_core_product.py -m mysql -q
```

Expected: preserved project/seed/Provider facts match; M2 derived counts are zero; failure injection rolls back.

- [ ] **Step 5: Commit Schema and all explicit rebuild callers atomically**

```powershell
git add backend/schema backend/schema_manifest.py backend/schema_version.py backend/scripts/reset_writer_core_data.py backend/scripts/bootstrap_writer_core_product.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_bootstrap_writer_core_product.py backend/tests/integration/test_schema_bootstrap.py backend/tests/integration/test_reset_writer_core_data.py backend/tests/integration/test_bootstrap_writer_core_product.py
git commit -m "feat: rebuild writer core schema v1.1"
```

### Task 4: Immutable seed CRUD, selection CAS, and readiness

**Files:**
- Create: `backend/repositories/seeds.py`
- Create: `backend/services/seeds.py`
- Create: `backend/http_errors.py`
- Modify: `backend/routers/seeds.py`
- Modify: `backend/security/redaction.py`
- Create: `backend/tests/unit/test_seed_service.py`
- Create: `backend/tests/api/test_seed_routes.py`
- Create: `backend/tests/api/test_public_domain_errors.py`
- Modify: `backend/tests/api/test_product_routes.py`
- Create: `backend/tests/integration/test_seed_revisions.py`

- [ ] **Step 1: Write service/API RED tests**

Cover create identity/revision/head atomically, edit appends revision, editing selected seed advances selection, cross-project selection rejection, stale selection revision 409, final-chapter lock, dependency-aware archive, and `contractReady=false` after seed drift. Public error tests require every domain 4xx to return only `code`, `message`, and `correlationId`; secret/base URL/SQL sentinels must not survive anywhere in the envelope. Update `test_product_routes.py` away from monkeypatching the old router-level `fetchall` implementation.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_seed_service.py backend/tests/api/test_seed_routes.py backend/tests/api/test_public_domain_errors.py backend/tests/api/test_product_routes.py -q
```

Expected: write commands/service do not exist.

- [ ] **Step 3: Implement repository and transaction service**

Use commands with `expectedSelectionRevision` and `expectedSeedRevision`. Every mutation takes one transaction factory, locks project/seed/head/selection as needed, performs exact CAS, and raises stable `SeedConflict`, `SeedLocked`, or `SeedNotFound` errors. Routers translate them to 409/404 without exposing SQL.

Add a shared `PublicDomainError(status_code, code, message)` and a specific FastAPI handler installed by `install_error_handlers`. The handler creates the correlation ID server-side and serializes exactly `{code, message, correlationId}`. M2B/M2C routers reuse this boundary instead of returning arbitrary `HTTPException.detail` objects.

Freeze the route contract as: `GET|POST /api/projects/{pid}/seeds`, `PUT|DELETE /api/projects/{pid}/seeds/{seed_id}`, and `GET|PUT /api/projects/{pid}/selected-seed`. DELETE performs archive when dependency checks prevent physical deletion.

- [ ] **Step 4: Verify unit/API and MySQL GREEN**

```powershell
python -m pytest backend/tests/unit/test_seed_service.py backend/tests/api/test_seed_routes.py backend/tests/api/test_public_domain_errors.py backend/tests/api/test_product_routes.py -q
python -m pytest backend/tests/integration/test_seed_revisions.py -m mysql -q
```

Expected: concurrent stale writer loses; old revision rows and hashes never change.

- [ ] **Step 5: Commit seed workflow**

```powershell
git add backend/domain/seeds.py backend/repositories/seeds.py backend/services/seeds.py backend/http_errors.py backend/routers/seeds.py backend/security/redaction.py backend/tests/unit/test_seed_service.py backend/tests/api/test_seed_routes.py backend/tests/api/test_public_domain_errors.py backend/tests/api/test_product_routes.py backend/tests/integration/test_seed_revisions.py
git commit -m "feat: add immutable seed selection workflow"
```

### Task 5: Versioned bindings and Provider soft delete

**Files:**
- Create: `backend/repositories/model_bindings.py`
- Create: `backend/services/model_bindings.py`
- Create: `backend/routers/model_bindings.py`
- Modify: `backend/services/projects.py`
- Modify: `backend/repositories/projects.py`
- Modify: `backend/routers/projects.py`
- Modify: `backend/routers/providers.py`
- Modify: `backend/main.py`
- Create: `backend/tests/api/test_model_binding_routes.py`
- Create: `backend/tests/integration/test_model_binding_revisions.py`
- Modify: `backend/tests/unit/test_project_creation.py`
- Modify: `backend/tests/api/test_provider_redaction.py`

- [ ] **Step 1: Write RED tests for complete/ready, fallback, CAS, and deletion**

Assert eight rows always exist; unbound permits project creation; AI readiness requires active enabled complete Provider config; previous bindings copy by task; invalid items fall back in `sort_order, created_at, id` order; full-map PUT is CAS; delete clears key/base URL and marks deleted while historical snapshots/hash stay unchanged. Provider list/detail/binding/error serializers must remove the stored API-key and base-URL values even when they appear inside nested `notes`, `thinking` or arbitrary public strings, not merely omit field names.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_model_bindings.py backend/tests/unit/test_project_creation.py backend/tests/api/test_model_binding_routes.py backend/tests/api/test_provider_redaction.py -q
```

- [ ] **Step 3: Implement services and delegate project creation**

`ModelBindingService.initialize_project(session, project_id)` builds one immutable revision and head inside the existing project transaction. `replace_all(project_id, expected_revision, mapping)` requires exactly eight keys. Provider delete executes one transaction setting `enabled=0`, `lifecycle_status='deleted'`, `api_key=''`, `base_url=''`, and `deleted_at=clock()`; ordinary Provider queries exclude deleted rows.

Freeze the binding routes as `GET /api/projects/{pid}/bindings`, `GET /api/projects/{pid}/bindings/status`, and whole-map `PUT /api/projects/{pid}/bindings` with `expectedRevision` plus all eight task entries.

- [ ] **Step 4: Verify focused and MySQL GREEN**

```powershell
python -m pytest backend/tests/unit/test_model_bindings.py backend/tests/unit/test_project_creation.py backend/tests/api/test_model_binding_routes.py backend/tests/api/test_provider_redaction.py -q
python -m pytest backend/tests/integration/test_model_binding_revisions.py -m mysql -q
```

Expected: project create still atomically writes project, Canon0, projection0, binding revision/head and contract head0; deleted Provider cannot be resolved; public payloads contain no stored secret/base URL value.

- [ ] **Step 5: Commit and run the M2A checkpoint**

```powershell
git add backend/repositories/model_bindings.py backend/services/model_bindings.py backend/routers/model_bindings.py backend/services/projects.py backend/repositories/projects.py backend/routers/projects.py backend/routers/providers.py backend/main.py backend/tests/unit/test_model_bindings.py backend/tests/unit/test_project_creation.py backend/tests/api/test_model_binding_routes.py backend/tests/api/test_provider_redaction.py backend/tests/integration/test_model_binding_revisions.py
git commit -m "feat: version project model bindings"
python -m pytest backend/tests/unit backend/tests/api -q
python -m pytest backend/tests/integration/test_schema_bootstrap.py backend/tests/integration/test_seed_revisions.py backend/tests/integration/test_model_binding_revisions.py -m mysql -q
git diff --check
```

Expected: all commands exit 0; no service/Provider/product DB was touched. Stop for code and spec review before starting M2B/M2C.
