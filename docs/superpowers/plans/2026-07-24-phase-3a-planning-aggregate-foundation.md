# Phase 3A Planning Aggregate Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `subagent-driven-development` to implement this plan task-by-task. Every task
> uses `test-driven-development`; after implementation use
> `requesting-code-review`, then `verification-before-completion`.

**Goal:** Replace the old deterministic mutable Planning foundation with the
single revisioned Planning aggregate and final v1.5 persistence fence, while
truthfully preventing ChapterSession creation until a confirmed Outline exists.

**Architecture:** `planning_drafts` is the only editable Planning state and
`project_planning_heads` is the only confirmed future-plan authority.
`planning_revisions` stores immutable canonical aggregates. Outline tables are
created in their final form now so `chapter_sessions` can pin exact Planning,
StoryBlock, and Outline revisions/hashes without another schema change.
Chapter creation reads those exact pins and fails closed when an Outline is
missing.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, aiomysql, MySQL 8, pytest,
Vue 3, Pinia 3, Node test runner.

---

## Scope and non-goals

This plan implements package 3A only. It does not add AI generation, the three
reachable planning pages, Outline authoring UI, a browser runner, or Canon
writes. Those are packages 3B–3D.

The implementation must physically remove:

- the four old planning tables;
- `CreateInitialPlan`;
- `PlanningService._initial_bundle`;
- `POST /api/projects/:projectId/planning/initial`;
- client/store `createInitial`;
- all production fallback copy mentioning `典籍知识`, `第一卷 山河初启`, or hardcoded
  3500/4500/5200 planning values;
- ChapterSession reads/writes of `volume_plan_id`,
  `planning_manifest_hash`, `planning_snapshot_json`, and
  `expected_story_block_revision`.

## Frozen public values

Use these exact status sets:

```python
PLANNING_DRAFT_STATUSES = {"active", "confirmed", "superseded"}
PLANNING_ATTEMPT_STATUSES = {
    "pending", "succeeded", "failed", "superseded",
}
PLANNING_NODE_LIFECYCLES = {"active", "retired"}
CONFIRMATION_STATUSES = {"pending", "succeeded", "failed"}
OUTLINE_DRAFT_STATUSES = {"active", "confirmed", "superseded"}
```

Planning revision 0 means “no confirmed Planning” and has null ID/hash. Planning
revision numbers start at 1. Node revisions start at 1.

Planning JSON uses camelCase canonical keys. SQL and repository row keys remain
snake_case. Public API also uses camelCase.

---

### Task 1: Reconcile Phase 2 facts and freeze the Phase 3A file contract

**Files:**
- Modify: `CURRENT_PROJECT_STATE.md`
- Modify: `PRODUCT_DEVELOPMENT_PLAN.md`
- Modify: `DEVELOPMENT_LOG.md`
- Modify: `STORY_QUALITY_CHARTER.md`
- Test: `scripts/tests/phase3PlanContract.test.mjs`

- [ ] **Step 1: Write the failing documentation contract**

Create `scripts/tests/phase3PlanContract.test.mjs`:

```javascript
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const read = path => readFile(new URL(`../../${path}`, import.meta.url), 'utf8')

test('current facts name Phase 2 complete and Phase 3 story planning active', async () => {
  const [state, product, log, charter] = await Promise.all([
    read('CURRENT_PROJECT_STATE.md'),
    read('PRODUCT_DEVELOPMENT_PLAN.md'),
    read('DEVELOPMENT_LOG.md'),
    read('STORY_QUALITY_CHARTER.md'),
  ])
  assert.match(state, /当前完成阶段：\\*\\*Phase 2/)
  assert.match(state, /唯一下一步[\\s\\S]*Phase 3/)
  assert.match(product, /\\| Phase 2 .*已完成门禁/)
  assert.match(product, /\\| Phase 3 .*进行中/)
  assert.match(log, /f11faad/)
  assert.doesNotMatch(charter, /split_unfinalized_content/)
})
```

- [ ] **Step 2: Run the contract and verify RED**

Run:

```powershell
node --test scripts/tests/phase3PlanContract.test.mjs
```

Expected: FAIL because current facts still identify Phase 1/Phase 2 as the next
stage and the charter still contains `split_unfinalized_content`.

- [ ] **Step 3: Reconcile only committed facts**

Update the four Markdown files to state:

```markdown
- Canonical release branch: `main`.
- Current completed phase: Phase 2 Creative Foundation.
- Phase 2 acceptance commit chain ends at `f11faad`.
- Current delivery branch: `codex/phase3-story-planning`.
- Current work is Phase 3 Story Planning.
- Product DB, Real Provider, Phase 4 Writer Loop, Phase 5 Finalization, and
  Content Quality remain not evaluated.
```

Remove the obsolete `split_unfinalized_content` action. Preserve the rule that
an unfinished scene may end naturally and remaining future tasks roll to the
next chapter.

- [ ] **Step 4: Run GREEN and check the diff**

Run:

```powershell
node --test scripts/tests/phase3PlanContract.test.mjs
git diff --check
```

Expected: `1 passed`, no whitespace errors.

- [ ] **Step 5: Commit**

```powershell
git add CURRENT_PROJECT_STATE.md PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md STORY_QUALITY_CHARTER.md scripts/tests/phase3PlanContract.test.mjs
git commit -m "docs: start phase three story planning"
```

---

### Task 2: Define the closed Planning aggregate domain

**Files:**
- Replace: `backend/domain/planning.py`
- Create: `backend/domain/chapter_outlines.py`
- Create: `backend/tests/unit/test_planning_domain.py`
- Create: `backend/tests/unit/test_chapter_outline_domain.py`

- [ ] **Step 1: Write RED tests for identity, relations, and hashing**

Create tests using these exact imports:

```python
from backend.domain.planning import (
    DraftPlanningAggregate,
    PlanningDomainError,
    normalize_planning_aggregate,
    validate_confirmable_planning,
)
```

The test fixture must contain one Volume, two Plots, one StoryBlock, one Stage,
and two SceneTasks. Assert:

```python
normalized = normalize_planning_aggregate(
    DraftPlanningAggregate.model_validate(payload),
    previous_confirmed=None,
    previous_draft=None,
    id_factory=iter(ids).__next__,
)
assert normalized.active_story_block_id == ids[3]
assert normalized.story_blocks[0].volume_id == ids[0]
assert normalized.story_blocks[0].plot_ids == (ids[1], ids[2])
assert normalized.volumes[0].revision == 1
assert normalized.content_hash == canonical_hash(
    normalized.model_dump(mode="json", by_alias=True, exclude={"content_hash"})
)
```

The draft fixture references newly created nodes by their request-local
`clientNodeKey`. Normalization returns only formal IDs in the persisted
aggregate.

Add exact negative tests:

```python
@pytest.mark.parametrize("mutation", (
    "duplicate_client_key",
    "unknown_volume",
    "unknown_plot",
    "duplicate_order",
    "retired_active_block",
    "completed_lifecycle",
    "browser_supplied_new_id",
))
def test_invalid_aggregate_is_rejected(mutation, valid_payload):
    with pytest.raises(PlanningDomainError):
        normalize_planning_aggregate(
            DraftPlanningAggregate.model_validate(apply(mutation, valid_payload)),
            previous_confirmed=None,
            previous_draft=None,
            id_factory=lambda: "00000000-0000-0000-0000-000000000999",
        )
```

Add a separate historical deletion test with a non-empty confirmed basis:

```python
def test_previous_confirmed_node_cannot_disappear(confirmed_planning, adjustment_payload):
    omitted = omit_unreferenced_historical_plot(adjustment_payload)
    with pytest.raises(PlanningDomainError, match="historical node"):
        normalize_planning_aggregate(
            DraftPlanningAggregate.model_validate(omitted),
            previous_confirmed=confirmed_planning,
            previous_draft=adjustment_draft_before_omission,
            id_factory=lambda: "00000000-0000-0000-0000-000000000999",
        )
```

The fixture must omit a still-unreferenced historical node so no unknown
reference can make the test pass for the wrong reason.

Add separate multiple-save provenance tests:

```python
def test_server_issued_draft_id_remains_editable_across_saves(...): ...
def test_never_confirmed_draft_node_may_be_removed(...): ...
def test_unknown_browser_formal_id_is_rejected(...): ...
def test_confirmed_active_node_may_retire_but_never_reactivate_or_disappear(...): ...
```

The service supplies both baselines from locked server rows. The browser never
declares which IDs are historical or server-issued.

Also assert unchanged nodes retain revision/hash, changed content/order/parent
increments exactly once, and a retired historical ID cannot reactivate. Draft
normalization permits the initial empty graph, but
`validate_confirmable_planning(normalized)` rejects it until there is at least
one active Volume, at least one active Plot of any approved type, one active
StoryBlock, one Stage, and one SceneTask. The active StoryBlock may reference
only active Volume/Plot nodes. Plot type is categorization metadata and never a
confirmation gate.

Every node present in the previous confirmed Planning revision must still be
present in the next normalized aggregate. A historical active node may remain
active or change once to retired; it may never be omitted. Only a node created
and removed within the same never-confirmed Draft may disappear.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_planning_domain.py -q
```

Expected: import failure because the aggregate domain does not exist.

- [ ] **Step 3: Implement closed Pydantic inputs**

Replace old dataclass views with these public shapes and frozen `extra="forbid"`
configuration:

```python
class DraftNode(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    id: str | None = None
    client_key: str | None = Field(default=None, alias="clientNodeKey")
    revision: int | None = Field(default=None, ge=1)
    content_hash: str | None = Field(
        default=None, alias="contentHash", pattern=r"^[0-9a-f]{64}$"
    )
    lifecycle: Literal["active", "retired"] = "active"

class DraftVolume(DraftNode):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    core_change: str = Field(alias="coreChange", min_length=1, max_length=4000)
    main_pressure: str = Field(alias="mainPressure", max_length=4000)
    ensemble_focus: tuple[str, ...] = Field(alias="ensembleFocus")
    forbidden_events: tuple[str, ...] = Field(alias="forbiddenEvents")

class DraftPlot(DraftNode):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    plot_type: Literal[
        "main", "character", "relationship", "conflict", "mystery", "other"
    ] = Field(alias="plotType")
    story_question: str = Field(alias="storyQuestion", min_length=1, max_length=4000)
    future_direction: str = Field(alias="futureDirection", max_length=4000)
    expected_payoff: str = Field(alias="expectedPayoff", max_length=4000)
    related_characters: tuple[str, ...] = Field(alias="relatedCharacters")

class DraftSceneTask(DraftNode):
    order: int = Field(ge=1)
    task: str = Field(min_length=1, max_length=4000)
    completion_evidence: str = Field(
        alias="completionEvidence", min_length=1, max_length=4000
    )

class DraftStage(DraftNode):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=4000)
    dramatic_question: str = Field(
        alias="dramaticQuestion", min_length=1, max_length=4000
    )
    scene_tasks: tuple[DraftSceneTask, ...] = Field(alias="sceneTasks")

class DraftStoryBlock(DraftNode):
    order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    volume_ref: str = Field(alias="volumeRef")
    plot_refs: tuple[str, ...] = Field(alias="plotRefs", min_length=1)
    entry_situation: str = Field(alias="entrySituation", max_length=4000)
    block_goal: str = Field(alias="blockGoal", min_length=1, max_length=4000)
    main_pressure: str = Field(alias="mainPressure", max_length=4000)
    expected_change: str = Field(alias="expectedChange", max_length=4000)
    open_questions: tuple[str, ...] = Field(alias="openQuestions")
    involved_characters: tuple[str, ...] = Field(alias="involvedCharacters")
    stages: tuple[DraftStage, ...]

class DraftPlanningAggregate(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    active_story_block_ref: str | None = Field(alias="activeStoryBlockRef")
    volumes: tuple[DraftVolume, ...]
    plots: tuple[DraftPlot, ...]
    story_blocks: tuple[DraftStoryBlock, ...] = Field(alias="storyBlocks")
```

Persisted node models require non-null server ID/revision/hash and contain no
`clientNodeKey`. Persisted `StoryBlock` uses only `volumeId/plotIds`, and
persisted `PlanningAggregate` uses `activeStoryBlockId` plus
`schemaVersion="planning-v1"` and `contentHash`.

- [ ] **Step 4: Write and run RED Outline-domain tests**

Create `backend/tests/unit/test_chapter_outline_domain.py` and require:

```python
from backend.domain.chapter_outlines import (
    DraftChapterOutline,
    ChapterOutlineDomainError,
    normalize_chapter_outline,
)

validated = normalize_chapter_outline(
    DraftChapterOutline.model_validate(outline_payload),
    planning=planning,
)
assert validated.chapter_number == 1
assert validated.story_block_ref.id == planning.story_blocks[0].id
```

Reject an input `contentHash`, unknown node IDs, mismatched node revision/hash,
a chapter number below 1, a capacity policy different from the contract
snapshot, and any extra field. Assert the persisted `ChapterOutline.contentHash`
is recomputed from the canonical normalized payload.

Run:

```powershell
python -m pytest backend/tests/unit/test_chapter_outline_domain.py -q
```

Expected: import failure because the Outline domain does not exist.

- [ ] **Step 5: Implement normalization and strict Outline values**

Implement pure helpers with these contracts:

```python
def normalize_planning_aggregate(
    draft: DraftPlanningAggregate,
    *,
    previous_confirmed: PlanningAggregate | None,
    previous_draft: PlanningAggregate | None,
    id_factory: Callable[[], str],
) -> PlanningAggregate:
    """Allocate new IDs, validate one-way relations, and derive local revisions."""

def planning_content_hash(value: Mapping[str, object]) -> str:
    return canonical_hash(value)

def validate_confirmable_planning(value: PlanningAggregate) -> None:
    """Reject an incomplete future plan before immutable confirmation."""
```

Rules:

1. new nodes have `clientNodeKey` and no formal identity;
2. existing nodes have formal ID/revision/hash and no client key;
3. normalize children before parents;
4. canonical node hash excludes `revision` and `contentHash`, but includes ID,
   lifecycle, order, parent, and normalized content;
5. accept a formal ID only if it exists in `previous_confirmed` or
   `previous_draft`; reject every other browser-supplied formal ID;
6. compare node content/revision first against `previous_draft`, falling back to
   `previous_confirmed` when no Draft version exists;
7. identical hash retains revision, otherwise revision is the latest
   server-side node revision + 1;
8. reject duplicate IDs/keys/orders and unknown relations;
9. reject target chapter counts and every unknown field through Pydantic;
10. compare the complete `previous_confirmed` ID set with the normalized ID set
   and reject any missing historical node before deriving the aggregate hash;
11. permit omission only for IDs found exclusively in `previous_draft`, because
    they were created and removed before confirmation;
12. derive the aggregate hash last.

Create frozen strict Outline models:

```python
class PlanningNodeRef(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    id: str
    revision: int = Field(ge=1)
    content_hash: str = Field(alias="contentHash", pattern=r"^[0-9a-f]{64}$")

class OutlineCapacityPolicy(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    target_min: int = Field(alias="targetMin", ge=1)
    target_max: int = Field(alias="targetMax", ge=1)
    soft_ceiling: int = Field(alias="softCeiling", ge=1)

class DraftChapterOutline(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    schema_version: Literal["chapter-outline-v1"] = Field(alias="schemaVersion")
    chapter_number: int = Field(alias="chapterNumber", ge=1)
    planning_revision_id: str = Field(alias="planningRevisionId")
    planning_revision: int = Field(alias="planningRevision", ge=1)
    planning_hash: str = Field(alias="planningHash", pattern=r"^[0-9a-f]{64}$")
    volume_ref: PlanningNodeRef = Field(alias="volumeRef")
    story_block_ref: PlanningNodeRef = Field(alias="storyBlockRef")
    stage_refs: tuple[PlanningNodeRef, ...] = Field(
        alias="stageRefs", min_length=1
    )
    scene_task_refs: tuple[PlanningNodeRef, ...] = Field(
        alias="sceneTaskRefs", min_length=1
    )
    chapter_goal: str = Field(alias="chapterGoal", min_length=1, max_length=4000)
    expected_characters: tuple[str, ...] = Field(alias="expectedCharacters")
    continuation: tuple[str, ...]
    planned_tasks: tuple[str, ...] = Field(alias="plannedTasks")
    scenes: tuple[str, ...] = Field(min_length=1)
    forbidden_early_events: tuple[str, ...] = Field(alias="forbiddenEarlyEvents")
    capacity_policy: OutlineCapacityPolicy = Field(alias="capacityPolicy")
```

Persisted `ChapterOutline` contains the same fields plus a required
`contentHash`. `normalize_chapter_outline` resolves every ref from the pinned
aggregate, requires exact revision/hash equality, validates the contract
capacity snapshot, and computes `contentHash` server-side over the canonical
payload with the hash field excluded. The browser cannot submit or replace that
hash.

Add exact negative tests proving the Outline is a closed active slice of the
confirmed aggregate:

- `volumeRef` is the active Volume named by `storyBlockRef.volumeId`;
- `storyBlockRef` is the current active StoryBlock;
- every `stageRef` is active and belongs to that StoryBlock;
- every `sceneTaskRef` is active and belongs to one of the selected Stages;
- an empty Stage or SceneTask reference tuple is rejected;
- a structurally valid but retired Volume, StoryBlock, Stage, or SceneTask is
  rejected;
- a node from another StoryBlock or Stage is rejected even when its
  ID/revision/hash triple is otherwise exact.

- [ ] **Step 6: Run GREEN**

```powershell
python -m pytest backend/tests/unit/test_planning_domain.py backend/tests/unit/test_chapter_outline_domain.py -q
git diff --check
```

Expected: all domain tests pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/domain/planning.py backend/domain/chapter_outlines.py backend/tests/unit/test_planning_domain.py backend/tests/unit/test_chapter_outline_domain.py
git commit -m "feat: define revisioned planning aggregate"
```

---

### Task 3: Replace the schema with exact v1.5 Planning and Outline tables

**Files:**
- Replace: `backend/schema/30_planning.sql`
- Modify: `backend/schema/40_drafts.sql`
- Modify: `backend/schema_version.py`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Modify: `backend/tests/unit/test_schema_version.py`
- Modify: `backend/tests/unit/test_initialize_database.py`
- Modify: `backend/tests/api/test_application_settings_routes.py`

- [ ] **Step 1: Change unit contracts to RED**

Change `EXPECTED_TABLES` by removing:

```python
{"volume_plans", "story_blocks", "story_stages", "scene_tasks"}
```

and adding:

```python
{
    "planning_drafts",
    "planning_generation_attempts",
    "planning_revisions",
    "project_planning_heads",
    "planning_confirmation_requests",
    "chapter_outline_drafts",
    "chapter_outline_generation_attempts",
    "chapter_outline_revisions",
    "project_chapter_outline_heads",
    "chapter_outline_confirmation_requests",
}
```

Add assertions that:

```python
assert EXPECTED_SCHEMA_VERSION == "writer-core-v1.5.0"
assert "expected_story_block_revision" not in _table_statement("chapter_sessions")
assert "volume_plan_id" not in _table_statement("chapter_sessions")
assert "planning_revision_id char(36) not null" in _table_statement("chapter_sessions")
assert "chapter_outline_revision_id char(36) not null" in _table_statement("chapter_sessions")
```

Assert v1.4 metadata is rejected read-only and no DDL is executed.

- [ ] **Step 2: Run RED schema unit tests**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/api/test_application_settings_routes.py -q
```

Expected: failures naming v1.4 and the four old tables.

- [ ] **Step 3: Replace `30_planning.sql`**

Create the ten tables in this exact dependency order:

```sql
CREATE TABLE planning_drafts (...);
CREATE TABLE planning_generation_attempts (...);
CREATE TABLE planning_revisions (...);
CREATE TABLE project_planning_heads (...);
CREATE TABLE planning_confirmation_requests (...);
CREATE TABLE chapter_outline_drafts (...);
CREATE TABLE chapter_outline_generation_attempts (...);
CREATE TABLE chapter_outline_revisions (...);
CREATE TABLE project_chapter_outline_heads (...);
CREATE TABLE chapter_outline_confirmation_requests (...);
```

Every project-owned table has `project_id CHAR(36) NOT NULL` and a composite
`UNIQUE KEY (project_id,id)` when referenced by another table.

Use these required columns:

```sql
-- shared Planning basis
selection_revision INT NOT NULL,
seed_id CHAR(36) NOT NULL,
seed_revision_id CHAR(36) NOT NULL,
seed_hash CHAR(64) NOT NULL,
contract_revision INT NOT NULL,
creation_contract_id CHAR(36) NOT NULL,
creation_hash CHAR(64) NOT NULL,
style_contract_id CHAR(36) NOT NULL,
style_hash CHAR(64) NOT NULL,
bible_revision INT NOT NULL,
bible_revision_id CHAR(36) NOT NULL,
bible_hash CHAR(64) NOT NULL
```

`planning_drafts` adds:

```sql
id, project_id, active_slot, base_head_revision, draft_revision,
content_json, content_hash, source_attempt_id, status, created_at, updated_at
```

and:

```sql
UNIQUE KEY uq_active_planning_draft (project_id, active_slot),
CHECK (active_slot IS NULL OR active_slot = 1),
CHECK (status IN ('active','confirmed','superseded')),
CHECK (
  (status='active' AND active_slot IS NOT NULL AND active_slot=1)
  OR
  (status IN ('confirmed','superseded') AND active_slot IS NULL)
)
```

`active_slot` is nullable. Confirming or superseding a Draft sets it to null so
 a later adjustment Draft can occupy slot 1. Outline Draft uses the same
bidirectional status/slot rule per project/chapter. `source_attempt_id` is
nullable and intentionally has no
database foreign key because an attempt already references its destination
Draft; adding the reverse FK would create a circular insert dependency. The
service may set it only after verifying the attempt belongs to the same project
and Draft.

`planning_revisions` adds immutable `revision`, `parent_revision`,
`content_json`, `content_hash`, `created_at`, with unique project revision and
unique project/id/revision/hash identities.

`planning_generation_attempts` freezes the complete package 3B operation
contract now:

```sql
id CHAR(36) PRIMARY KEY,
project_id CHAR(36) NOT NULL,
draft_id CHAR(36) NOT NULL,
operation_id CHAR(36) NOT NULL,
active_slot TINYINT NULL,
idempotency_key VARCHAR(64) NOT NULL,
request_fingerprint CHAR(64) NOT NULL,
binding_revision_id CHAR(36) NOT NULL,
binding_revision INT NOT NULL,
binding_hash CHAR(64) NOT NULL,
provider_id CHAR(36) NOT NULL,
model_name_snapshot VARCHAR(200) NOT NULL,
fencing_token BIGINT NOT NULL,
lease_expires_at BIGINT NOT NULL,
input_manifest_json JSON NOT NULL,
input_manifest_hash CHAR(64) NOT NULL,
result_content_json JSON NULL,
result_content_hash CHAR(64) NULL,
loaded_draft_revision INT NULL,
loaded_at BIGINT NULL,
failure_code VARCHAR(64) NULL,
status VARCHAR(24) NOT NULL,
created_at BIGINT NOT NULL,
updated_at BIGINT NOT NULL
```

Required constraints:

```sql
UNIQUE KEY uq_planning_operation (project_id, operation_id),
UNIQUE KEY uq_planning_generation_idempotency (project_id, idempotency_key),
UNIQUE KEY uq_active_planning_generation (draft_id, active_slot),
UNIQUE KEY uq_planning_fencing (draft_id, fencing_token),
CHECK (active_slot IS NULL OR active_slot=1),
CHECK (fencing_token > 0),
CHECK (lease_expires_at >= created_at),
CHECK (status IN ('pending','succeeded','failed','superseded')),
CHECK (
  (
    status='pending'
    AND active_slot IS NOT NULL
    AND active_slot=1
  )
  OR
  (status IN ('succeeded','failed','superseded') AND active_slot IS NULL)
),
CHECK (
  (result_content_json IS NULL AND result_content_hash IS NULL)
  OR
  (result_content_json IS NOT NULL AND result_content_hash IS NOT NULL)
),
CHECK (
  (loaded_draft_revision IS NULL AND loaded_at IS NULL)
  OR
  (
    loaded_draft_revision IS NOT NULL
    AND loaded_at IS NOT NULL
    AND status='succeeded'
  )
),
CHECK (
  (
    status='pending'
    AND result_content_json IS NULL
    AND result_content_hash IS NULL
    AND failure_code IS NULL
    AND loaded_draft_revision IS NULL
    AND loaded_at IS NULL
  )
  OR
  (
    status='succeeded'
    AND result_content_json IS NOT NULL
    AND result_content_hash IS NOT NULL
    AND failure_code IS NULL
  )
  OR
  (
    status='failed'
    AND result_content_json IS NULL
    AND result_content_hash IS NULL
    AND failure_code IS NOT NULL
    AND loaded_draft_revision IS NULL
    AND loaded_at IS NULL
  )
  OR
  (
    status='superseded'
    AND failure_code IS NULL
    AND loaded_draft_revision IS NULL
    AND loaded_at IS NULL
  )
)
```

It has same-project FKs to its Planning Draft and exact model-binding revision.
It stores only normalized result content and safe failure codes—never prompt or
raw Provider output. Terminal attempts set `active_slot=NULL`.

`project_planning_heads` permits only the exact revision-0 null triple or a
positive non-null ID/hash triple:

```sql
CHECK (
  (revision=0 AND planning_revision_id IS NULL AND content_hash IS NULL)
  OR
  (revision>0 AND planning_revision_id IS NOT NULL AND content_hash IS NOT NULL)
)
```

Confirmation requests store idempotency key, request fingerprint, status,
result revision ID/revision/hash, and timestamps.

Outline tables pin Planning ID/revision/hash plus `canon_revision`,
`projection_revision`, `projection_hash`, chapter number, content JSON/hash,
and the same draft/revision/head/request lifecycle.

`chapter_outline_generation_attempts` repeats the complete operation contract
above with `outline_draft_id` in place of `draft_id` and unique names scoped to
the Outline table. It must include operation ID, active slot, idempotency key,
request fingerprint, exact binding identity, provider/model public snapshot,
fencing token, lease expiry, safe input manifest/hash, normalized result/hash,
loaded Outline draft revision, failure code, status, and timestamps. Package
3B/3C may implement behavior against these columns but may not alter the
schema. It repeats the same bidirectional active-slot/status rule and the same
paired loaded-revision/loaded-at rule with its Outline column names. It also
repeats the exact pending/succeeded/failed/superseded result/failure
exclusivity rule with `loaded_outline_draft_revision`.

A superseded attempt may retain either no result or one normalized
result-content/hash pair as immutable evidence of a late fenced response. It
may never carry loaded metadata or overwrite a Draft. Raw Provider output is
still never stored.

Schema unit tests and the real MySQL bootstrap test must insert counterexamples
for both attempt tables and prove that MySQL rejects:

- `pending` with `active_slot=NULL`;
- a terminal status with `active_slot=1`;
- only one of loaded revision/loaded timestamp;
- loaded metadata on any status other than `succeeded`.
- `pending` with result or failure data;
- `succeeded` without a normalized result or with a failure code;
- `failed` without a safe failure code or with a normalized result;
- `superseded` with only one side of the result pair, any failure code, or any
  loaded metadata. Also prove that a superseded normalized result pair is
  accepted as evidence while the Draft remains unchanged.

- [ ] **Step 4: Rewrite ChapterSession pins**

In `40_drafts.sql`, make `chapter_sessions` use:

```sql
planning_revision_id CHAR(36) NOT NULL,
planning_revision INT NOT NULL,
planning_hash CHAR(64) NOT NULL,
story_block_id CHAR(36) NOT NULL,
story_block_revision INT NOT NULL,
story_block_hash CHAR(64) NOT NULL,
chapter_outline_revision_id CHAR(36) NOT NULL,
chapter_outline_revision INT NOT NULL,
chapter_outline_hash CHAR(64) NOT NULL,
expected_canon_revision INT NOT NULL
```

Add composite FKs to `planning_revisions` and `chapter_outline_revisions`.
Remove all old generation/volume/manifest/story-block-revision columns,
including `planning_snapshot_json`. A Session holds exact immutable
revision/hash pins; it does not persist a second Planning copy.

In the unused Phase 5 placeholder tables, replace the old mutable-planning
names now so no later runtime can depend on them:

```sql
-- finalization_change_sets
expected_planning_hash CHAR(64) NOT NULL,
expected_outline_hash CHAR(64) NOT NULL

-- final_chapters
planning_revision_id CHAR(36) NOT NULL,
planning_revision INT NOT NULL,
planning_hash CHAR(64) NOT NULL,
chapter_outline_revision_id CHAR(36) NOT NULL,
chapter_outline_revision INT NOT NULL,
chapter_outline_hash CHAR(64) NOT NULL
```

Remove `expected_story_block_revision` from change sets and
`story_block_revision` plus `planning_snapshot_json` from final chapters.
These tables remain unreachable until Phase 5 and do not gain a compatibility
column.

- [ ] **Step 5: Bump the exact version**

```python
EXPECTED_SCHEMA_VERSION = "writer-core-v1.5.0"
```

Update only current-version test expectations. Do not change
`backend/tests/support/frozen_writer_core_v11.py`.

- [ ] **Step 6: Run GREEN schema unit tests**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/api/test_application_settings_routes.py -q
git diff --check
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/schema/30_planning.sql backend/schema/40_drafts.sql backend/schema_version.py backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/api/test_application_settings_routes.py
git commit -m "feat: establish planning aggregate schema"
```

---

### Task 4: Prove the real MySQL bootstrap and generation fences

**Files:**
- Modify: `backend/tests/integration/test_schema_bootstrap.py`
- Modify: `backend/tests/support/disposable_mysql.py`

- [ ] **Step 1: Update the real-schema inventory to RED**

Replace the old four tables with the new ten tables in `EXPECTED_TABLES`.
Extend `_insert_foundation_project` with:

```sql
INSERT INTO project_planning_heads
  (project_id,revision,planning_revision_id,content_hash,updated_at)
VALUES (%s,0,NULL,NULL,%s)
```

Add a test named:

```python
async def test_planning_outline_and_session_reject_cross_generation_splices(
    disposable_mysql,
):
    ...
```

The test must create Planning revisions A/B, Outline revisions pinned to A/B,
then assert MySQL rejects:

- head revision/hash from different Planning rows;
- Outline A with Planning B;
- ChapterSession containing Planning A with Outline B.

StoryBlock ID/revision/hash membership is intentionally not a child-table FK;
`test_chapter_outline_domain.py` and the ChapterSession service tests prove that
closed JSON relationship.

- [ ] **Step 2: Run RED on Disposable MySQL**

```powershell
python -m pytest backend/tests/integration/test_schema_bootstrap.py -q
```

Expected: failure until the new fixtures and exact FKs are correct.

- [ ] **Step 3: Complete fixture helpers without product DB access**

Add helpers that insert canonical JSON using `canonical_json` and hashes using
`canonical_hash`. Do not hardcode the active product database name. Keep all
existing `disposable_mysql` safety checks.

- [ ] **Step 4: Run GREEN and residue check**

```powershell
python -m pytest backend/tests/integration/test_schema_bootstrap.py -q
git diff --check
```

Expected: all selected tests pass and the disposable fixture removes its exact
owned database.

- [ ] **Step 5: Commit**

```powershell
git add backend/tests/integration/test_schema_bootstrap.py backend/tests/support/disposable_mysql.py
git commit -m "test: prove planning schema fences"
```

---

### Task 5: Initialize and delete the Planning ownership graph atomically

**Files:**
- Modify: `backend/repositories/projects.py`
- Modify: `backend/services/project_lifecycle.py`
- Modify: `backend/tests/unit/test_project_creation.py`
- Modify: `backend/tests/integration/test_project_ownership_delete.py`
- Modify: `backend/tests/integration/test_project_archive.py`

- [ ] **Step 1: Write RED project-foundation tests**

Extend the fake repository sequence to:

```python
(
    "guard", "project", "revision", "projection",
    "contract", "bible", "planning", "binding",
)
```

Add:

```python
async def insert_planning_head0(self, session, project_id):
    self.calls.append(("planning", project_id))
```

Assert every injected failure rolls back the project and all heads.

Before running the package GREEN, replace every
`PlanningService.create_initial_plan` call in
`test_project_archive.py` with a current-schema integration fixture that
inserts a canonical Planning Draft/revision/head graph directly in the
Disposable MySQL transaction. The fixture must:

- use the new ten-table schema only;
- preserve the archived-read / archived-write assertions of the test;
- never import the old Planning service or old four-table DTOs;
- create no compatibility adapter that production code could call.

Update `test_project_ownership_delete.py` fixtures in the same step so they
insert and verify deletion of the new Planning/Outline ownership graph.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_project_creation.py -q
```

Expected: failure because project creation does not write Planning head 0.

- [ ] **Step 3: Implement head 0**

Add:

```python
async def insert_planning_head0(self, session, project_id: str) -> None:
    await session.execute(
        """INSERT INTO project_planning_heads
           (project_id,revision,planning_revision_id,content_hash,updated_at)
           VALUES (%s,0,NULL,NULL,%s)""",
        (project_id, self._clock()),
    )
```

Call it after Bible head 0 and before model-binding initialization in the same
project-creation transaction.

- [ ] **Step 4: Replace ownership order**

Remove the four old tables. Add new rows in child-before-parent order:

```python
"chapter_outline_confirmation_requests",
"project_chapter_outline_heads",
"chapter_outline_generation_attempts",
"chapter_outline_drafts",
"chapter_outline_revisions",
"planning_confirmation_requests",
"project_planning_heads",
"planning_generation_attempts",
"planning_drafts",
"planning_revisions",
```

Keep sessions/drafts/finalization rows before Outline rows.

At the end of this step, a source inventory over
`test_project_archive.py` and `test_project_ownership_delete.py` must contain no
`create_initial_plan`, `volume_plans`, `story_blocks` table insert,
`story_stages`, or `scene_tasks`.

- [ ] **Step 5: Run unit and Disposable MySQL GREEN**

```powershell
python -m pytest backend/tests/unit/test_project_creation.py backend/tests/integration/test_project_ownership_delete.py backend/tests/integration/test_project_archive.py -q
git diff --check
```

Expected: all selected tests pass; shared assets/providers/corpus remain.

- [ ] **Step 6: Commit**

```powershell
git add backend/repositories/projects.py backend/services/project_lifecycle.py backend/tests/unit/test_project_creation.py backend/tests/integration/test_project_ownership_delete.py backend/tests/integration/test_project_archive.py
git commit -m "feat: own planning project lifecycle"
```

---

### Task 6: Implement Planning draft, save, confirm, history, and read state

**Files:**
- Replace: `backend/repositories/planning.py`
- Replace: `backend/services/planning.py`
- Replace: `backend/tests/unit/test_planning_repository.py`
- Replace: `backend/tests/unit/test_planning_service.py`
- Create: `backend/tests/integration/test_planning_aggregate_lifecycle.py`

- [ ] **Step 1: Write RED service tests**

Use commands:

```python
@dataclass(frozen=True)
class CreatePlanningDraft:
    project_id: str
    idempotency_key: str

@dataclass(frozen=True)
class SavePlanningDraft:
    project_id: str
    draft_id: str
    expected_revision: int
    expected_hash: str
    content: Mapping[str, object]
    idempotency_key: str

@dataclass(frozen=True)
class ConfirmPlanningDraft:
    project_id: str
    draft_id: str
    expected_draft_revision: int
    expected_draft_hash: str
    idempotency_key: str
```

Test:

- no current Bible → precondition;
- at Planning Head revision 0, create uses contract capacity but emits one
  empty Draft with `baseHeadRevision=0` and no hardcoded story content;
- at Planning Head revision 1 or later with no active Draft, create clones the
  complete current immutable aggregate with every stable ID/revision/hash
  unchanged and sets `baseHeadRevision` to the locked Head revision;
- second create returns the same active draft;
- confirm rejects the initial empty/incomplete Draft;
- save CAS conflict preserves server draft;
- new node IDs come from injected server factory;
- confirm writes revision/head/request atomically;
- same key/same fingerprint replays;
- same key/different fingerprint conflicts;
- selection, contract, or Bible drift supersedes the draft;
- Canon head and Projection head differ at confirmation → precondition;
- synchronized Canon/Projection heads allow confirmation without writing either
  head;
- archived project rejects every mutation;
- history returns immutable revisions;
- read state returns separate `future_plan`, empty `actual_progress`, and
  synchronized Canon/Projection heads.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_planning_repository.py backend/tests/unit/test_planning_service.py -q
```

Expected: failures because the old initial-plan API is still present.

- [ ] **Step 3: Implement repository boundaries**

The repository must expose only session-bound methods:

```python
lock_active_project
read_project_any
read_current_basis
lock_planning_head
read_active_draft
read_draft
insert_draft
update_draft_cas
supersede_draft
find_confirmation
insert_confirmation_pending
insert_revision
advance_head_cas
finish_confirmation
list_revisions
read_projection_head
lock_projection_head
```

`read_current_basis` joins current selected seed, contract head/revision, style
contract, and Bible head/revision by exact IDs/revisions/hashes. It returns no
Provider secret.

- [ ] **Step 4: Implement service transactions**

Use `normalize_planning_aggregate` only in the service. Provider calls do not
exist in 3A. At Head revision 0, create an empty legal Draft:

```json
{
  "activeStoryBlockId": null,
  "volumes": [],
  "plots": [],
  "storyBlocks": []
}
```

At Head revision 1 or later, a create request with no active Draft clones the
entire immutable aggregate selected by the locked Head into a new active Draft.
It preserves every stable node ID, node revision, node hash, relationship, and
aggregate hash, and records the exact Head revision in `base_head_revision`.
The author adjusts this clone; they never reconstruct a confirmed graph from
the browser. If an active Draft already exists, create returns that same Draft
without cloning again.

On save, the service locks both authorities before normalization:

- `previous_confirmed` is the immutable revision selected by the locked
  Planning Head, or `None` at head revision 0;
- `previous_draft` is the current active Draft content before applying the
  request.

This lets the domain distinguish immutable historical IDs from server-issued
IDs that exist only in the unconfirmed Draft. Neither baseline comes from the
request body.

Capacity is returned separately from the confirmed contract and is not copied
as a StoryBlock chapter count.

Confirm order is:

```python
lock project
lock current basis
lock planning head
lock draft
lock Canon/Projection head in the same transaction snapshot
find/insert idempotency request
validate draft revision/hash and basis
require Canon revision == Projection revision
validate confirmable Planning completeness
insert immutable revision
advance head with expected revision
mark draft confirmed
finish confirmation
```

Any failure raises so the transaction rolls back.
Planning confirmation never rebuilds Projection and never writes Canon or
Projection. A Canon/Projection mismatch must occur before inserting a revision,
advancing the Planning head, changing Draft status, or completing the
idempotency request.

- [ ] **Step 5: Add real MySQL lifecycle and rollback tests**

Test revision `0 -> 1 -> 2`, including a real MySQL `Head=1/no active Draft`
create that clones the revision-1 content byte-for-byte with stable IDs and
`base_head_revision=1`. Also test exact history, stale draft conflict, A→B→A
selection never reactivating old Planning, and an injected failure after every
write point. Add a real MySQL mismatch case where Canon is one revision ahead
of Projection; confirmation must fail closed with zero Planning writes. Assert
the Planning head, revision, Draft, request, Canon head, and Projection head all
remain at the pre-command state after rollback.

- [ ] **Step 6: Run GREEN**

```powershell
python -m pytest backend/tests/unit/test_planning_repository.py backend/tests/unit/test_planning_service.py backend/tests/integration/test_planning_aggregate_lifecycle.py -q
git diff --check
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/repositories/planning.py backend/services/planning.py backend/tests/unit/test_planning_repository.py backend/tests/unit/test_planning_service.py backend/tests/integration/test_planning_aggregate_lifecycle.py
git commit -m "feat: add planning aggregate lifecycle"
```

---

### Task 7: Replace the Planning HTTP/client/store contract

**Files:**
- Replace: `backend/routers/planning.py`
- Replace: `backend/tests/api/test_planning_routes.py`
- Modify: `frontend/src/api/db/client.js`
- Replace: `frontend/src/stores/planningStore.js`
- Replace: `frontend/tests/unit/planningStore.test.mjs`
- Rewrite in place: `frontend/src/components/planning/PlanningWorkspace.vue`
- Modify: `frontend/tests/unit/phase2RuntimeInventory.test.mjs`

- [ ] **Step 1: Write RED API tests**

Freeze these 3A routes:

```text
GET  /api/projects/:pid/planning
GET  /api/projects/:pid/planning/history
POST /api/projects/:pid/planning/drafts
PUT  /api/projects/:pid/planning/drafts/:draftId
POST /api/projects/:pid/planning/drafts/:draftId/confirm
```

Assert `POST /planning/initial` is 404. Every request body is strict
`extra="forbid"`. Public responses contain no snake-case duplicate aliases,
prompt, raw output, Provider identity, secret, or SQL diagnostic.

- [ ] **Step 2: Run RED API tests**

```powershell
python -m pytest backend/tests/api/test_planning_routes.py -q
```

Expected: failures against the old initial route.

- [ ] **Step 3: Implement public DTOs and error mapping**

Use fixed codes:

```python
PlanningRequestInvalid
PlanningResourceNotFound
PlanningPreconditionFailed
PlanningConflict
PlanningArchived
```

Serialize:

```json
{
  "projectId": "p1",
  "basisStatus": "current",
  "head": {"revision": 0, "planningRevisionId": null, "contentHash": null},
  "draft": null,
  "futurePlan": null,
  "actualProgress": [],
  "canonProjectionStatus": {
    "canonRevision": 0,
    "projectionRevision": 0,
    "contentHash": "...",
    "synchronized": true
  },
  "capacityPolicy": {"targetMin": 3000, "targetMax": 5000, "softCeiling": 6000},
  "capabilities": {"view": true, "edit": true, "confirm": false, "generate": false}
}
```

Values come from services; the router must not join or infer readiness.

- [ ] **Step 4: Replace frontend transport and store**

Remove `api.planning.createInitial`. Add:

```javascript
get(projectId)
history(projectId)
createDraft(projectId, body)
saveDraft(projectId, draftId, body)
confirmDraft(projectId, draftId, body)
```

The single `planningStore` exposes:

```javascript
state
history
localContent
dirty
loading
saving
confirming
load
createDraft
editLocal
saveDraft
confirmDraft
discardLocal
invalidate
```

It ignores late responses from older projects and preserves dirty local content
on CAS failure.

- [ ] **Step 5: Rewrite `PlanningWorkspace.vue` in place**

For 3A it is a non-routed shared foundation that renders:

- head revision;
- active draft revision;
- “尚无已确认规划” when head is 0;
- separate “未来计划” and “已发生事实” labels;
- no initial-plan button;
- no hardcoded Volume/StoryBlock content;
- no AI button yet.

Do not create `PlanningWorkspaceV2.vue`.

- [ ] **Step 6: Run API and frontend GREEN**

```powershell
python -m pytest backend/tests/api/test_planning_routes.py -q
node --test frontend/tests/unit/planningStore.test.mjs frontend/tests/unit/phase2RuntimeInventory.test.mjs
npm run build
git diff --check
```

Expected: selected tests and build pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/routers/planning.py backend/tests/api/test_planning_routes.py frontend/src/api/db/client.js frontend/src/stores/planningStore.js frontend/tests/unit/planningStore.test.mjs frontend/src/components/planning/PlanningWorkspace.vue frontend/tests/unit/phase2RuntimeInventory.test.mjs
git commit -m "feat: expose planning aggregate foundation"
```

---

### Task 8: Replace ChapterSession pins and close the no-Outline path

**Files:**
- Modify: `backend/domain/drafts.py`
- Replace planning-related SQL in: `backend/repositories/chapter_sessions.py`
- Modify: `backend/services/chapter_sessions.py`
- Modify: `backend/routers/chapter_sessions.py`
- Modify: `backend/tests/unit/test_chapter_session_service.py`
- Modify: `backend/tests/api/test_chapter_session_routes.py`
- Modify: `backend/tests/unit/test_chapter_draft_generation_service.py`
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/chapterSessionStore.js`
- Modify: `frontend/src/views/ChapterWriterView.vue`
- Modify: `frontend/tests/unit/chapterSessionStore.test.mjs`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Modify: `frontend/tests/unit/phase2RuntimeInventory.test.mjs`

- [ ] **Step 1: Write RED exact-pin tests**

Replace `expectedStoryBlockRevision` creation input with:

```json
{
  "chapterNumber": 1,
  "expectedPlanningRevision": 1,
  "expectedPlanningHash": "64hex",
  "expectedOutlineRevision": 1,
  "expectedOutlineHash": "64hex",
  "expectedCanonRevision": 0
}
```

Assert:

- no current confirmed Outline → `ChapterSessionPreconditionFailed`;
- URL/body chapter mismatch → invalid request;
- Planning or Outline drift → conflict;
- Canon head and Projection head differ → precondition;
- synchronized Canon/Projection heads differ from the Outline baseline →
  conflict;
- current exact Outline → session row pins all exact IDs/revisions/hashes;
- no query or DTO contains an old
  volume/manifest/snapshot/expected-story-block field.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py backend/tests/unit/test_chapter_draft_generation_service.py -q
```

Expected: failures against old session fields.

- [ ] **Step 3: Replace domain and repository rows**

`ChapterSessionView` exposes:

```python
planning_revision_id: str
planning_revision: int
planning_hash: str
story_block_id: str
story_block_revision: int
story_block_hash: str
chapter_outline_revision_id: str
chapter_outline_revision: int
chapter_outline_hash: str
expected_canon_revision: int
```

`read_current_outline` joins the Outline head and revision to the current
Planning head by exact project/chapter/revision/hash. `read_projection_head`
returns Canon revision, Projection revision, and projection hash from the same
transaction snapshot. The repository never accepts browser-supplied IDs as
authority.

- [ ] **Step 4: Fail closed until package 3C authoring exists**

Keep the formal create route but make it succeed only if a current confirmed
Outline already exists in the database. In normal 3A UI there is no way to
create one, so the route truthfully returns the precondition instead of
bypassing Outline.

Before insert, the service requires:

```python
projection_head.canon_revision == projection_head.projection_revision
projection_head.canon_revision == outline.canon_revision
projection_head.projection_revision == outline.projection_revision
projection_head.content_hash == outline.projection_hash
```

Mismatch never triggers a rebuild or Canon mutation inside ChapterSession
creation.

Existing read/save-candidate behavior may operate only on rows already pinned
to the new schema. There is no old-row compatibility reader.

- [ ] **Step 5: Update the frontend request allowlist**

The API client and store send only the six expected values above. They do not
derive a StoryBlock revision from `planningStore.activeBlock`.

In 3A, `ChapterWriterView.vue` physically removes the old
`activeBlock.revision` create command. With no product Outline authoring route
yet, the create control is disabled and explains “请先完成并确认本章小纲”. Existing
already-pinned Sessions remain readable/editable. Package 3C will enable this
same control from the service-authoritative current Outline state; 3A must not
invent a temporary Outline or a second writer view.

Add runtime inventory assertions that `ChapterWriterView.vue`,
`chapterSessionStore.js`, and `client.js` contain no
`expectedStoryBlockRevision` creation path.

- [ ] **Step 6: Run GREEN**

```powershell
python -m pytest backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py backend/tests/unit/test_chapter_draft_generation_service.py -q
node --test frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/phase2RuntimeInventory.test.mjs
git diff --check
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/domain/drafts.py backend/repositories/chapter_sessions.py backend/services/chapter_sessions.py backend/routers/chapter_sessions.py backend/tests/unit/test_chapter_session_service.py backend/tests/api/test_chapter_session_routes.py backend/tests/unit/test_chapter_draft_generation_service.py frontend/src/api/db/client.js frontend/src/stores/chapterSessionStore.js frontend/src/views/ChapterWriterView.vue frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/phase2RuntimeInventory.test.mjs
git commit -m "feat: pin chapter sessions to planning outlines"
```

---

### Task 9: Remove obsolete schema/reset/verifier contracts

**Files:**
- Modify: `backend/scripts/reset_writer_core_data.py`
- Modify: `backend/scripts/verify_milestone2_product.py`
- Modify: `backend/tests/unit/test_reset_writer_core_data.py`
- Modify: `backend/tests/unit/test_verify_milestone2_product.py`
- Modify: `backend/tests/integration/test_milestone2_product_rebuild.py`
- Modify: `backend/tests/integration/test_seed_revisions.py`
- Modify: `backend/tests/unit/test_archived_write_inventory.py`
- Modify: `backend/tests/api/test_route_inventory.py`
- Modify: `scripts/tests/phase2Suite.test.mjs`

- [ ] **Step 1: Write RED retired-contract assertions**

Assert current production/runtime files contain none of:

```text
volume_plans
story_blocks SQL table
story_stages SQL table
scene_tasks SQL table
/planning/initial
expected_story_block_revision
planning_manifest_hash
planning_snapshot_json
create_initial_plan
```

Scope this inventory to current runtime and current verifiers; historical
Markdown and frozen v1.1 fixtures remain evidence and are excluded.

- [ ] **Step 2: Run RED focused tests**

```powershell
python -m pytest backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_verify_milestone2_product.py backend/tests/integration/test_milestone2_product_rebuild.py backend/tests/integration/test_seed_revisions.py backend/tests/unit/test_archived_write_inventory.py backend/tests/api/test_route_inventory.py -q
node --test scripts/tests/phase2Suite.test.mjs scripts/tests/phase3PlanContract.test.mjs
```

Expected: failures naming old table/route inventories.

- [ ] **Step 3: Retire compatibility reset behavior**

Remove every v1.1/v1.4-to-current transformation branch from
`reset_writer_core_data.py`. The only remaining destructive helper may operate
on an already exact v1.5 development schema, clear project-owned test data, and
rebuild contract/Bible/Planning/Canon/Projection heads at revision 0.

Any other schema version receives one fixed rejection instructing explicit
empty-database reinitialization through `initialize_database`. Do not preserve
projects or seeds across a schema change and do not add a v1.4 alias.

Keep `backend/tests/support/frozen_writer_core_v11.py` only as immutable
historical test evidence. Current runtime code must not import it.

- [ ] **Step 4: Update verifier counts**

Current verifiers read new Planning/Outline heads and require:

```python
planning_head_revision in {0, expected_positive_revision}
no orphan planning draft/revision/outline/session rows
no old table query
```

They do not claim Phase 3 Ready from a Phase 2 receipt.

- [ ] **Step 5: Run GREEN**

```powershell
python -m pytest backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_verify_milestone2_product.py backend/tests/integration/test_milestone2_product_rebuild.py backend/tests/integration/test_seed_revisions.py backend/tests/unit/test_archived_write_inventory.py backend/tests/api/test_route_inventory.py -q
node --test scripts/tests/phase2Suite.test.mjs scripts/tests/phase3PlanContract.test.mjs
git diff --check
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/scripts/reset_writer_core_data.py backend/scripts/verify_milestone2_product.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/unit/test_verify_milestone2_product.py backend/tests/integration/test_milestone2_product_rebuild.py backend/tests/integration/test_seed_revisions.py backend/tests/unit/test_archived_write_inventory.py backend/tests/api/test_route_inventory.py scripts/tests/phase2Suite.test.mjs
git commit -m "refactor: retire mutable planning foundation"
```

---

### Task 10: Review, verify, and record Phase 3A

**Files:**
- Create: `docs/acceptance/2026-07-24-phase-3a-planning-aggregate.md`
- Modify only if proven: `CURRENT_PROJECT_STATE.md`
- Modify only if proven: `DEVELOPMENT_LOG.md`

- [ ] **Step 1: Run independent spec review**

Review the full diff against:

```text
docs/superpowers/specs/2026-07-24-phase-3-story-planning-design.md
docs/superpowers/plans/2026-07-24-phase-3a-planning-aggregate-foundation.md
```

Required result: Critical 0 / Important 0 / Minor 0. Return every finding to the
same implementer and repeat until zero.

- [ ] **Step 2: Run independent quality review**

Start only after spec review is zero. Review transaction boundaries, hash
canonicalization, SQL ownership, public DTO leakage, stale response handling,
file size, and test behavior. Required result: 0/0/0.

- [ ] **Step 3: Run final gates serially**

```powershell
npm test
npm run test:integration
npm run build
git diff --check
```

Stop at the first failure. Use systematic debugging and RED → GREEN. Do not run
integration/build in parallel.

- [ ] **Step 4: Verify cleanup**

After integration, query only owned `novel_creator_test_%` database names and
verify `remaining=0`. Verify no owned backend/frontend process, port, or temp
root remains. Do not stop the user's normal MySQL service.

- [ ] **Step 5: Write the acceptance report from fresh output**

Record:

- exact HEAD and branch;
- exact Python/Node/frontend pass/skip/fail counts;
- exact integration created/cleaned/remaining counts;
- build module count;
- spec and quality review counts;
- Provider calls `0`;
- product DB reads/writes `0/0`;
- Phase 3B–3D, Real Provider, Product DB, and Content Quality not evaluated.

Do not copy numbers from Phase 2 or earlier runs.

- [ ] **Step 6: Run report contract and final status**

```powershell
node --test scripts/tests/phase3PlanContract.test.mjs
git diff --check
git status --short --branch
```

- [ ] **Step 7: Commit**

```powershell
git add docs/acceptance/2026-07-24-phase-3a-planning-aggregate.md CURRENT_PROJECT_STATE.md DEVELOPMENT_LOG.md
git commit -m "test: accept planning aggregate foundation"
git show --check --stat HEAD
git status --short --branch
```

Do not merge or push package 3A by itself unless the user explicitly changes
the Phase 3 branch policy. Continue to package 3B from the clean 3A commit.
