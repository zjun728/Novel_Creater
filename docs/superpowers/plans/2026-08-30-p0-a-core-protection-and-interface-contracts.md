# P0-A Core Protection and Interface Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the existing Writer Core invariants and publish strict, testable read-contract types that later P0 plans can reuse without changing current lifecycle or write semantics.

**Architecture:** Reuse the repository's existing authority, finalization, Canon/Projection, contract, Bible, and pinned-manuscript tests instead of duplicating their business logic. Add one documentation contract that assigns every planned API to an existing authority or a new bounded context, plus one pure Pydantic module for workbench bootstrap and volume-index response values. P0-A adds no routes, repositories, schema migration, frontend page, Provider call, or product-database write.

**Tech Stack:** Python 3.12, Pydantic v2, pytest/pytest-asyncio, existing Node test dispatcher, MySQL 8.4 disposable integration fixtures, Markdown.

---

## Scope and file map

**Create:**

- `docs/superpowers/contracts/2026-08-30-p0-author-product-interfaces.md` — exact ownership, lifecycle, route, and transaction boundaries for Plans B–G.
- `backend/domain/workbench.py` — strict immutable values for workbench bootstrap, volume summaries, and one-volume chapter indexes.
- `backend/tests/unit/test_workbench_domain.py` — contract and cross-field validation tests for those values.

**Do not modify in P0-A:**

- `backend/main.py` or any router registration;
- `backend/schema/*.sql`;
- `backend/services/chapter_sessions.py`, `backend/services/finalization_commit.py`, Canon/Projection services, contract services, or Bible services;
- any file under `frontend/src`;
- `.env.local.json`, product databases, Provider profiles, or model bindings.

The later plan owning an endpoint will add its router, service, repository, schema, frontend client, and route-inventory entry. P0-A only fixes the contract so those plans cannot invent conflicting authorities.

### Task 1: Prove the pre-change Writer Core baseline

**Files:** None

- [ ] **Step 1: Confirm the exact checkout and preserve unrelated files**

Run:

```powershell
git status --short --branch
git rev-parse HEAD
```

Expected: branch `main`; the already-known untracked `.review-worktrees/` and `tmp/brainstorm-topic-center-*.html` may remain, but no task step may stage, edit, or delete them.

- [ ] **Step 2: Run the deterministic lifecycle and authority slice**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_contract_service.py backend/tests/unit/test_bible_service.py backend/tests/unit/test_chapter_session_service.py backend/tests/unit/test_finalization_commit.py backend/tests/unit/test_manuscript_domain.py backend/tests/api/test_route_inventory.py backend/tests/unit/test_router_domain_boundary.py
```

Expected: exit `0`, all selected tests pass, no network access and no database access.

- [ ] **Step 3: Run the existing disposable-MySQL core slice once**

Use the repository-local configuration only as a source of the four server connection values. The wrapper below never maps `MYSQL_DB`, never names or opens a product database, restores any pre-existing `TEST_MYSQL_*` process values, and does not call a Provider.

Run:

```powershell
$config = Get-Content -LiteralPath '.env.local.json' -Raw | ConvertFrom-Json
$mapping = [ordered]@{
  TEST_MYSQL_HOST = [string]$config.MYSQL_HOST
  TEST_MYSQL_PORT = [string]$config.MYSQL_PORT
  TEST_MYSQL_USER = [string]$config.MYSQL_USER
  TEST_MYSQL_PASSWORD = [string]$config.MYSQL_PASSWORD
}
$previous = @{}
foreach ($name in $mapping.Keys) {
  $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$exitCode = 1
try {
  foreach ($name in $mapping.Keys) {
    [Environment]::SetEnvironmentVariable($name, $mapping[$name], 'Process')
  }
  $testArgs = @(
    '-m', 'pytest', '-q', '-m', 'mysql',
    'backend/tests/integration/test_authoritative_chapter_session.py::test_concurrent_different_chapters_create_only_authority_and_replay',
    'backend/tests/integration/test_atomic_finalization_mysql.py::test_atomic_finalization_rolls_back_late_failure_then_commits_and_replays',
    'backend/tests/integration/test_contract_confirmation.py::test_real_history_has_one_permanent_contract_baseline',
    'backend/tests/integration/test_bible_revisions.py::test_real_confirmed_bible_permanently_rejects_mutations_and_replays',
    'backend/tests/integration/test_manuscript_repository_mysql.py::test_active_and_archived_reads_keep_titles_gaps_and_pinned_historical_planning'
  )
  & python @testArgs
  $exitCode = $LASTEXITCODE
} finally {
  foreach ($name in $mapping.Keys) {
    [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
  }
}
if ($exitCode -ne 0) { exit $exitCode }
```

Expected: exit `0`; the fixture creates only a random `novel_creator_test_<32 lowercase hex>` database and removes it in teardown. A failure stops the task for diagnosis; do not retry automatically.

### Task 2: Publish the P0 boundary and API ownership contract

**Files:**

- Create: `docs/superpowers/contracts/2026-08-30-p0-author-product-interfaces.md`
- Reference: `docs/superpowers/specs/2026-08-30-p0-author-product-design.md`

- [ ] **Step 1: Create the contract document with the exact content below**

```markdown
# P0 Author Product Interface Contracts

- Design authority: `docs/superpowers/specs/2026-08-30-p0-author-product-design.md`
- Baseline: Writer Core on `main`
- Rule: reads may aggregate existing authorities; writes must call the owning command service.

## Permanent lifecycle rules

| Object | Before confirmation | After confirmation |
| --- | --- | --- |
| Project Seed | revise candidates and select explicitly | selected revision is the project seed authority |
| Creation Contract | draft, generate, compare, clone, confirm once | permanent read-only baseline; clone/save/reconfirm remain rejected |
| Creation Bible | edit, generate, compare, confirm once | permanent read-only baseline; clone/save/reconfirm remain rejected |
| Chapter | one authoritative drafting session | immutable final chapter plus pinned Outline/Planning authority |

No P0 route may weaken these rules.

## Query contracts

| Plan | Method and path | Class | Reads | Must not do |
| --- | --- | --- | --- | --- |
| B | `GET /api/projects/{project_id}/overview` | Q | project, seed/contract/Bible/Planning heads, Writer state, Canon/Projection heads, final-chapter aggregates, ContinuityIssue count | infer heads in the frontend or write status |
| F | `GET /api/projects/{project_id}/workbench/bootstrap?chapter={n}` | Q | server authority, requested chapter, current session or final chapter ref, pinned/current outline ref, Canon/Projection heads | create a ChapterSession or classify from 404/null in the frontend |
| F | `GET /api/projects/{project_id}/workbench/volumes` | Q | pinned final authorities plus the current confirmed Outline when present | return prose or full Planning/Outline JSON |
| F | `GET /api/projects/{project_id}/workbench/volumes/{volume_id}/chapters?cursor={opaque}&limit={1..100}` | Q | one stable volume and its bounded chapter index | scan or return the whole manuscript |
| E | `GET /api/projects/{project_id}/continuity/entities/{entity_id}` | Q | Bible/Planning future design and explicitly referenced Canon/Projection state | join identities by name or save a second fact copy |
| F | `GET /api/projects/{project_id}/workbench/chapters/{chapter_number}/audit` | Q | existing Finalization, ChangeSet, Canon events, Projection evidence, and pinned authority | create an audit fact or mutate history |

Historical volume membership comes only from the Planning/Outline pinned at finalization. A current chapter without a confirmed Outline is returned as unassigned with a stable blocked reason; the frontend never guesses a volume.

## New bounded-context commands

| Plan | Method and path | Class | Transaction boundary |
| --- | --- | --- | --- |
| C | `POST /api/topic-discussions` | N | create one global discussion; no project is required |
| C | `POST /api/topic-discussions/{discussion_id}/messages` | N | append one user message and one recorded model operation/result |
| C | `POST /api/topic-discussions/{discussion_id}/directions` | N | save an immutable direction version from an explicit message/evidence set |
| C | `POST /api/topic-discussions/{discussion_id}/candidates` | N | save an immutable global candidate version from explicit discussion state |
| C | `POST /api/topic-candidates/{candidate_id}/versions/{version}/projects` | N | atomically create the project, copy into existing project Seed revision/head, record provenance/idempotency, leave Seed unconfirmed |
| E | `POST /api/projects/{project_id}/continuity/issues` | N | create a process-debt record referencing existing chapter/Finalization/Canon identities |
| E | `PUT /api/projects/{project_id}/continuity/issues/{issue_id}/status` | N | change only `pending`, `resolved`, or `dismissed` status |

The topic-to-project command uses an idempotency key and returns the same project ID and project Seed revision on replay. It never creates a second project-seed snapshot authority and never auto-confirms the Seed.

## Existing write authorities retained

- Seed confirmation continues through the current project Seed selection service.
- Contract and Bible writes continue through their current pre-confirmation services.
- ChapterSession creation remains an explicit command after confirmed current Outline and synchronized Canon/Projection checks.
- WorkingDraft, draft operations, Candidate, FinalizationChangeSet, and atomic finalization keep their current routes and services.
- Canon/Projection routes remain read-only; finalization is the only P0 path that commits chapter facts and projection changes.
- A FinalizationChangeSet may apply the existing allow-listed future Planning patch inside the atomic transaction; it may not mark planned content as an occurred fact.

## Route cutover rule

After Plan F, `/projects/:projectId/workbench` and `/projects/:projectId/workbench/chapters/:chapterNumber` are the only mounted writing/reading components. Old write and manuscript URLs may be pure redirects only. They may not mount old views, load old stores, or call old APIs.
```

- [ ] **Step 2: Check the document for ambiguous authority or placeholders**

Run:

```powershell
rg -n -i "T`BD|TO`DO|待`定|由前端判断|自动确认|按名称合并" docs/superpowers/contracts/2026-08-30-p0-author-product-interfaces.md
```

Expected: only the prohibition against name-based identity matching may appear; no placeholder, frontend authority, or automatic confirmation appears as an allowed behavior.

- [ ] **Step 3: Commit the contract document alone**

Run:

```powershell
git add -- docs/superpowers/contracts/2026-08-30-p0-author-product-interfaces.md
git diff --cached --check
git commit -m "docs: define p0 author interface contracts"
```

Expected: one documentation-only commit; unrelated untracked files remain unstaged.

### Task 3: Add strict workbench read-contract values with TDD

**Files:**

- Create: `backend/domain/workbench.py`
- Create: `backend/tests/unit/test_workbench_domain.py`

- [ ] **Step 1: Write the failing domain tests**

Create `backend/tests/unit/test_workbench_domain.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.domain.workbench import (
    WorkbenchBlockedReason,
    WorkbenchBootstrap,
    WorkbenchChapterIndexItem,
    WorkbenchChapterIndexPage,
    WorkbenchFinalChapterReference,
    WorkbenchOutlineReference,
    WorkbenchSessionReference,
    WorkbenchVolumeReference,
    WorkbenchVolumeSummary,
    WorkbenchVolumeSummaryList,
)


HASH = "a" * 64


def volume() -> WorkbenchVolumeReference:
    return WorkbenchVolumeReference(id="volume-1", order=1, title="第一卷")


def outline() -> WorkbenchOutlineReference:
    return WorkbenchOutlineReference(id="outline-1", revision=1, content_hash=HASH)


def test_historical_bootstrap_has_only_pinned_read_authorities() -> None:
    value = WorkbenchBootstrap(
        project_id="project-1",
        requested_chapter=2,
        authoritative_chapter=3,
        mode="historical",
        volume=volume(),
        session=None,
        final_chapter=WorkbenchFinalChapterReference(
            id="final-2", chapter_number=2, content_hash=HASH,
        ),
        outline=outline(),
        available_actions=("view_chapter", "view_outline"),
        blocked_reasons=(),
        canon_revision=2,
        projection_revision=2,
        canon_projection_synchronized=True,
    )

    assert value.mode == "historical"
    assert value.final_chapter.chapter_number == 2
    assert value.session is None


def test_current_bootstrap_may_offer_explicit_session_creation_only() -> None:
    value = WorkbenchBootstrap(
        project_id="project-1",
        requested_chapter=3,
        authoritative_chapter=3,
        mode="current",
        volume=volume(),
        session=None,
        final_chapter=None,
        outline=outline(),
        available_actions=("view_outline", "create_session"),
        blocked_reasons=(),
        canon_revision=2,
        projection_revision=2,
        canon_projection_synchronized=True,
    )

    assert value.available_actions == ("view_outline", "create_session")


def test_current_session_rejects_create_session_action() -> None:
    with pytest.raises(ValidationError, match="create_session"):
        WorkbenchBootstrap(
            project_id="project-1",
            requested_chapter=3,
            authoritative_chapter=3,
            mode="current",
            volume=volume(),
            session=WorkbenchSessionReference(id="session-3", chapter_number=3),
            final_chapter=None,
            outline=outline(),
            available_actions=("create_session", "edit_draft"),
            blocked_reasons=(),
            canon_revision=2,
            projection_revision=2,
            canon_projection_synchronized=True,
        )


def test_future_bootstrap_has_no_authority_refs_or_actions() -> None:
    value = WorkbenchBootstrap(
        project_id="project-1",
        requested_chapter=5,
        authoritative_chapter=3,
        mode="future",
        volume=None,
        session=None,
        final_chapter=None,
        outline=None,
        available_actions=(),
        blocked_reasons=(WorkbenchBlockedReason(
            code="future_chapter", message="该章节尚未成为当前权威章节。",
        ),),
        canon_revision=2,
        projection_revision=2,
        canon_projection_synchronized=True,
    )

    assert value.available_actions == ()


@pytest.mark.parametrize(
    "changes",
    (
        {"mode": "historical", "requested_chapter": 3},
        {"mode": "current", "requested_chapter": 2},
        {"mode": "future", "requested_chapter": 2},
    ),
)
def test_mode_must_match_server_authoritative_chapter(changes: dict) -> None:
    payload = {
        "project_id": "project-1",
        "requested_chapter": 2,
        "authoritative_chapter": 3,
        "mode": "historical",
        "volume": volume(),
        "session": None,
        "final_chapter": WorkbenchFinalChapterReference(
            id="final-2", chapter_number=2, content_hash=HASH,
        ),
        "outline": outline(),
        "available_actions": ("view_chapter",),
        "blocked_reasons": (),
        "canon_revision": 2,
        "projection_revision": 2,
        "canon_projection_synchronized": True,
    }
    payload.update(changes)

    with pytest.raises(ValidationError):
        WorkbenchBootstrap.model_validate(payload)


def test_sync_flag_is_derived_from_both_heads() -> None:
    with pytest.raises(ValidationError, match="synchronization"):
        WorkbenchBootstrap(
            project_id="project-1",
            requested_chapter=3,
            authoritative_chapter=3,
            mode="current",
            volume=None,
            session=None,
            final_chapter=None,
            outline=None,
            available_actions=(),
            blocked_reasons=(WorkbenchBlockedReason(
                code="canon_projection_unsynchronized",
                message="Canon 与当前状态尚未同步。",
            ),),
            canon_revision=3,
            projection_revision=2,
            canon_projection_synchronized=True,
        )


def test_volume_index_is_bounded_ordered_and_contains_at_most_one_current() -> None:
    page = WorkbenchChapterIndexPage(
        project_id="project-1",
        volume=volume(),
        chapters=(
            WorkbenchChapterIndexItem(
                chapter_number=1, title="第一章", mode="historical",
                scalar_count=3200, finalized_at_ms=1000,
                final_chapter_id="final-1", session_id=None,
            ),
            WorkbenchChapterIndexItem(
                chapter_number=2, title="第二章", mode="current",
                scalar_count=None, finalized_at_ms=None,
                final_chapter_id=None, session_id="session-2",
            ),
        ),
        next_cursor=None,
        limit=100,
    )

    assert [item.chapter_number for item in page.chapters] == [1, 2]
    assert set(WorkbenchChapterIndexItem.model_fields).isdisjoint(
        {"content", "planning", "outline"}
    )
    with pytest.raises(ValidationError):
        WorkbenchChapterIndexPage.model_validate(
            {**page.model_dump(), "limit": 101}, strict=True,
        )
    with pytest.raises(ValidationError, match="current"):
        WorkbenchChapterIndexPage(
            project_id="project-1", volume=volume(),
            chapters=(page.chapters[1], page.chapters[1].model_copy(
                update={"chapter_number": 3, "session_id": "session-3"}
            )),
            next_cursor=None, limit=100,
        )


def test_volume_summary_list_keeps_unassigned_authority_explicit() -> None:
    value = WorkbenchVolumeSummaryList(
        project_id="project-1",
        volumes=(WorkbenchVolumeSummary(
            volume=volume(), finalized_chapter_count=2,
            first_finalized_chapter=1, last_finalized_chapter=2,
            contains_authoritative_chapter=False,
        ),),
        authoritative_chapter=3,
        unassigned_authoritative_chapter=3,
    )

    assert value.unassigned_authoritative_chapter == 3
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_workbench_domain.py
```

Expected: collection fails with `ModuleNotFoundError: No module named 'backend.domain.workbench'`.

- [ ] **Step 3: Implement the minimal strict domain values**

Create `backend/domain/workbench.py`:

```python
"""Strict immutable read contracts for the unified author workbench."""

from __future__ import annotations

import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


WorkbenchMode = Literal["historical", "current", "future"]
WorkbenchAction = Literal[
    "view_chapter", "view_outline", "create_session", "edit_draft",
    "run_ai_operation", "save_candidate", "compare_candidates",
    "audit_candidate", "finalize_candidate",
]
WorkbenchBlockCode = Literal[
    "project_archived", "future_chapter", "outline_required",
    "session_not_created", "canon_projection_unsynchronized",
    "finalization_in_progress",
]
ChapterIndexMode = Literal["historical", "current"]


class _StrictValue(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


def _safe_text(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise ValueError("text must be trimmed and non-empty")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("text must not contain control characters")
    return value


class WorkbenchVolumeReference(_StrictValue):
    id: str = Field(min_length=1)
    order: int = Field(ge=1)
    title: str = Field(min_length=1)

    _id_safe = field_validator("id")(_safe_text)
    _title_safe = field_validator("title")(_safe_text)


class WorkbenchOutlineReference(_StrictValue):
    id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    _id_safe = field_validator("id")(_safe_text)


class WorkbenchSessionReference(_StrictValue):
    id: str = Field(min_length=1)
    chapter_number: int = Field(ge=1)
    status: Literal["drafting"] = "drafting"

    _id_safe = field_validator("id")(_safe_text)


class WorkbenchFinalChapterReference(_StrictValue):
    id: str = Field(min_length=1)
    chapter_number: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    _id_safe = field_validator("id")(_safe_text)


class WorkbenchBlockedReason(_StrictValue):
    code: WorkbenchBlockCode
    message: str = Field(min_length=1, max_length=240)

    _message_safe = field_validator("message")(_safe_text)


class WorkbenchBootstrap(_StrictValue):
    project_id: str = Field(min_length=1)
    requested_chapter: int = Field(ge=1)
    authoritative_chapter: int = Field(ge=1)
    mode: WorkbenchMode
    volume: WorkbenchVolumeReference | None
    session: WorkbenchSessionReference | None
    final_chapter: WorkbenchFinalChapterReference | None
    outline: WorkbenchOutlineReference | None
    available_actions: tuple[WorkbenchAction, ...]
    blocked_reasons: tuple[WorkbenchBlockedReason, ...]
    canon_revision: int | None = Field(default=None, ge=0)
    projection_revision: int | None = Field(default=None, ge=0)
    canon_projection_synchronized: bool

    _project_id_safe = field_validator("project_id")(_safe_text)

    @model_validator(mode="after")
    def validate_authority_shape(self):
        expected_mode = (
            "historical" if self.requested_chapter < self.authoritative_chapter
            else "current" if self.requested_chapter == self.authoritative_chapter
            else "future"
        )
        if self.mode != expected_mode:
            raise ValueError("mode differs from server authoritative chapter")
        if len(set(self.available_actions)) != len(self.available_actions):
            raise ValueError("available actions must be unique")
        reason_codes = tuple(reason.code for reason in self.blocked_reasons)
        if len(set(reason_codes)) != len(reason_codes):
            raise ValueError("blocked reason codes must be unique")
        synchronized = (
            self.canon_revision is not None
            and self.projection_revision is not None
            and self.canon_revision == self.projection_revision
        )
        if self.canon_projection_synchronized != synchronized:
            raise ValueError("Canon/Projection synchronization flag is invalid")
        if self.mode == "historical":
            if self.final_chapter is None or self.outline is None or self.volume is None:
                raise ValueError("historical mode requires pinned final authorities")
            if self.session is not None:
                raise ValueError("historical mode cannot expose a drafting session")
            if set(self.available_actions) - {"view_chapter", "view_outline"}:
                raise ValueError("historical mode is read-only")
            if self.final_chapter.chapter_number != self.requested_chapter:
                raise ValueError("final chapter differs from request")
        elif self.mode == "current":
            if self.final_chapter is not None:
                raise ValueError("current mode cannot expose a final chapter")
            if self.session is not None:
                if self.session.chapter_number != self.requested_chapter:
                    raise ValueError("session differs from request")
                if "create_session" in self.available_actions:
                    raise ValueError("create_session is invalid when a session exists")
            elif set(self.available_actions) - {"view_outline", "create_session"}:
                raise ValueError("draft actions require a current session")
        else:
            if any((self.volume, self.session, self.final_chapter, self.outline)):
                raise ValueError("future mode cannot expose chapter authorities")
            if self.available_actions:
                raise ValueError("future mode has no actions")
            if "future_chapter" not in reason_codes:
                raise ValueError("future mode requires a stable blocked reason")
        return self


class WorkbenchVolumeSummary(_StrictValue):
    volume: WorkbenchVolumeReference
    finalized_chapter_count: int = Field(ge=0)
    first_finalized_chapter: int | None = Field(default=None, ge=1)
    last_finalized_chapter: int | None = Field(default=None, ge=1)
    contains_authoritative_chapter: bool

    @model_validator(mode="after")
    def validate_finalized_range(self):
        values = (self.first_finalized_chapter, self.last_finalized_chapter)
        if self.finalized_chapter_count == 0 and any(value is not None for value in values):
            raise ValueError("empty volume cannot expose a finalized range")
        if self.finalized_chapter_count > 0:
            if any(value is None for value in values):
                raise ValueError("non-empty volume requires a finalized range")
            if self.first_finalized_chapter > self.last_finalized_chapter:
                raise ValueError("finalized range is reversed")
        return self


class WorkbenchVolumeSummaryList(_StrictValue):
    project_id: str = Field(min_length=1)
    volumes: tuple[WorkbenchVolumeSummary, ...]
    authoritative_chapter: int | None = Field(default=None, ge=1)
    unassigned_authoritative_chapter: int | None = Field(default=None, ge=1)

    _project_id_safe = field_validator("project_id")(_safe_text)

    @model_validator(mode="after")
    def validate_authority_location(self):
        identities = tuple(item.volume.id for item in self.volumes)
        orders = tuple(item.volume.order for item in self.volumes)
        if len(set(identities)) != len(identities) or len(set(orders)) != len(orders):
            raise ValueError("volume identities and orders must be unique")
        if tuple(sorted(orders)) != orders:
            raise ValueError("volumes must be ordered")
        located = sum(item.contains_authoritative_chapter for item in self.volumes)
        if located > 1:
            raise ValueError("authoritative chapter can belong to one volume only")
        if self.unassigned_authoritative_chapter is not None:
            if self.unassigned_authoritative_chapter != self.authoritative_chapter or located:
                raise ValueError("unassigned authority must not also belong to a volume")
        return self


class WorkbenchChapterIndexItem(_StrictValue):
    chapter_number: int = Field(ge=1)
    title: str = Field(min_length=1)
    mode: ChapterIndexMode
    scalar_count: int | None = Field(default=None, ge=0)
    finalized_at_ms: int | None = Field(default=None, ge=0)
    final_chapter_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)

    _title_safe = field_validator("title")(_safe_text)

    @field_validator("final_chapter_id", "session_id")
    @classmethod
    def optional_id_safe(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value)

    @model_validator(mode="after")
    def validate_mode_shape(self):
        if self.mode == "historical":
            if None in (self.scalar_count, self.finalized_at_ms, self.final_chapter_id):
                raise ValueError("historical item requires final metadata")
            if self.session_id is not None:
                raise ValueError("historical item cannot expose a session")
        elif any(value is not None for value in (
            self.scalar_count, self.finalized_at_ms, self.final_chapter_id,
        )):
            raise ValueError("current item cannot expose final metadata")
        return self


class WorkbenchChapterIndexPage(_StrictValue):
    project_id: str = Field(min_length=1)
    volume: WorkbenchVolumeReference
    chapters: tuple[WorkbenchChapterIndexItem, ...]
    next_cursor: str | None = Field(default=None, min_length=1, max_length=512)
    limit: int = Field(ge=1, le=100)

    _project_id_safe = field_validator("project_id")(_safe_text)

    @field_validator("next_cursor")
    @classmethod
    def cursor_safe(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value)

    @model_validator(mode="after")
    def validate_page(self):
        numbers = tuple(item.chapter_number for item in self.chapters)
        if tuple(sorted(numbers)) != numbers or len(set(numbers)) != len(numbers):
            raise ValueError("chapters must be unique and ordered")
        if sum(item.mode == "current" for item in self.chapters) > 1:
            raise ValueError("page can expose at most one current chapter")
        if len(self.chapters) > self.limit:
            raise ValueError("page exceeds its declared limit")
        return self


__all__ = (
    "ChapterIndexMode", "WorkbenchAction", "WorkbenchBlockedReason",
    "WorkbenchBlockCode", "WorkbenchBootstrap", "WorkbenchChapterIndexItem",
    "WorkbenchChapterIndexPage", "WorkbenchFinalChapterReference",
    "WorkbenchMode", "WorkbenchOutlineReference", "WorkbenchSessionReference",
    "WorkbenchVolumeReference", "WorkbenchVolumeSummary",
    "WorkbenchVolumeSummaryList",
)
```

- [ ] **Step 4: Run the new tests and verify GREEN**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_workbench_domain.py
```

Expected: exit `0`, all tests in the new file pass.

- [ ] **Step 5: Run the adjacent domain slice**

Run:

```powershell
python -m pytest -q backend/tests/unit/test_workbench_domain.py backend/tests/unit/test_manuscript_domain.py backend/tests/unit/test_chapter_session_service.py backend/tests/unit/test_finalization_domain.py
```

Expected: exit `0`; no database, network, or Provider call.

- [ ] **Step 6: Commit the domain contract and tests**

Run:

```powershell
git add -- backend/domain/workbench.py backend/tests/unit/test_workbench_domain.py
git diff --cached --check
git commit -m "test: freeze workbench read contracts"
```

Expected: one commit containing only the domain contract and its unit tests.

### Task 4: Run the P0-A phase gate and stop at a safe commit

**Files:** None

- [ ] **Step 1: Run all deterministic tests**

Run:

```powershell
npm test
```

Expected: exit `0`; Python unit/API, root Node tests, and frontend unit tests all pass.

- [ ] **Step 2: Run the disposable integration suite once**

Use the same repository-local configuration boundary and run the full integration command exactly once:

```powershell
$config = Get-Content -LiteralPath '.env.local.json' -Raw | ConvertFrom-Json
$mapping = [ordered]@{
  TEST_MYSQL_HOST = [string]$config.MYSQL_HOST
  TEST_MYSQL_PORT = [string]$config.MYSQL_PORT
  TEST_MYSQL_USER = [string]$config.MYSQL_USER
  TEST_MYSQL_PASSWORD = [string]$config.MYSQL_PASSWORD
}
$previous = @{}
foreach ($name in $mapping.Keys) {
  $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$exitCode = 1
try {
  foreach ($name in $mapping.Keys) {
    [Environment]::SetEnvironmentVariable($name, $mapping[$name], 'Process')
  }
  & npm 'run' 'test:integration'
  $exitCode = $LASTEXITCODE
} finally {
  foreach ($name in $mapping.Keys) {
    [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
  }
}
if ($exitCode -ne 0) { exit $exitCode }
```

Expected: exit `0`; the test runner reports equal created/cleaned disposable databases and zero remaining task-owned test databases. Clear the four process variables in `finally`. Do not retry automatically on failure.

- [ ] **Step 3: Run the production frontend build**

Run:

```powershell
npm run build
```

Expected: exit `0`. No browser test is required because P0-A does not modify a frontend production path.

- [ ] **Step 4: Verify the exact committed scope and resource boundary**

Run:

```powershell
git log -3 --oneline
git status --short --branch
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 5173,8000 } | Select-Object LocalAddress,LocalPort,OwningProcess
```

Expected: two P0-A commits follow the approved design commit; only the pre-existing untracked review/prototype paths remain. P0-A owns no Vite/backend process, so it must not start or stop anything on ports 5173 or 8000. If another process is listening, report it without terminating it.

## Exit criteria

P0-A is complete only when:

- the existing lifecycle and atomicity baseline passed before changes;
- the interface contract assigns every P0 query/write to one owner and explicitly forbids implicit writes;
- workbench bootstrap and volume-index values are strict, immutable, cross-field validated, bounded to 100 items, and contain no prose or full Planning/Outline payload;
- no router, schema, frontend, Provider, or product-database behavior changed;
- the deterministic suite, disposable integration suite, and build all pass after the final code change;
- the task stops after the two safe commits and waits for review before Plan B.
