# Writer Core Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从干净 `4b85e8d` 建立 Writer Core V1 的一次性 Schema、Canon 唯一事实源、确定性投影、事务/幂等基础和真实产品只读状态页，并彻底退出旧写作状态链。

**Architecture:** 正常应用启动只校验 Schema manifest，不执行 DDL；显式初始化/重置脚本负责一次性建库。Canon repository 只能接收显式事务连接，CanonService 在一个事务里追加 revision、实体/别名/事件并替换投影；前端第一阶段只读取项目、种子和 Writer Core 状态，不提供任意 Canon 写接口，也不再调用旧章节/设定/故事块/定稿链。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、aiomysql、MySQL 8、pytest/pytest-asyncio、Vue 3、Pinia、Vite、Node `node:test`、Playwright。

---

## 0. Scope and non-negotiable boundaries

本计划只实现 M1。它不调用 Provider，不生成正文，不接触真实数据库，直到所有 disposable MySQL 测试和浏览器测试通过并由产品主控单独批准产品库重置命令。

M1 完成时的真实产品切片是：

`首页 -> 永乐大典项目 -> 三个种子 -> Writer Core 状态（Schema / Canon head / Projection head）`

旧 Writer 入口在 M1 明确显示“写作内核正在重建，当前不可写”，而不是继续暴露旧 chapters/tempDrafts/versions/finalize/settings/story-block API。M1 不为了保留旧页面而保留第二套事实源。

本计划最多授予 L4 `M1 No-Provider Ready`，不得宣称 Provider Ready、Live Ready 或 30 章 Product Ready。

## 1. Locked file structure

### New backend files

```text
backend/__init__.py                         Python package boundary
backend/schema_version.py                  expected version/hash and startup verification
backend/schema_manifest.py                 ordered bootstrap fragment manifest
backend/schema/00_metadata.sql             schema metadata
backend/schema/10_core.sql                 project/seed/provider/model binding
backend/schema/20_contracts.sql             creation/style contracts and asset refs
backend/schema/30_planning.sql              volume/story block/stage/scene task
backend/schema/40_drafts.sql                sessions/working drafts/candidates/finals/change sets
backend/schema/50_canon.sql                 entities/aliases/revisions/events
backend/schema/60_projections.sql           current state/memory/arc/plot projections and head
backend/schema/70_corpus.sql                corpus/style/experience/reference use
backend/domain/canon.py                     Canon types, normalization and hard-conflict rules
backend/repositories/canon.py               SQL operations that require an explicit connection
backend/services/canon.py                   revision/idempotency/identity orchestration
backend/services/projections.py             deterministic pure projection builder
backend/routers/canon.py                    read-only Canon/projection/state API
backend/serializers/provider.py             secret-free provider response mapping
backend/security/redaction.py               validation/error/log secret scrubbing
backend/scripts/initialize_database.py      explicit fresh bootstrap
backend/scripts/reset_writer_core_data.py   explicit preserve-and-reset command
backend/tests/support/fakes.py               unit transaction fakes
backend/tests/support/disposable_mysql.py    guarded disposable database fixture
backend/tests/unit/*.py                      domain/database/schema tests
backend/tests/api/*.py                       read-only API and secret tests
backend/tests/integration/*.py               real MySQL transaction tests
scripts/run-tests.mjs                        cross-platform root test dispatcher
```

### New frontend files

```text
frontend/src/views/WriterUnavailableView.vue
frontend/src/components/project/WriterCoreStateCard.vue
frontend/tests/unit/writerCoreApi.test.mjs
frontend/tests/unit/providerRedaction.test.mjs
frontend/e2e/milestone1.spec.ts
frontend/playwright.config.ts
```

### Modified files

```text
package.json
backend/requirements-dev.txt
backend/config.py
backend/database.py
backend/main.py
backend/routers/projects.py
backend/routers/providers.py
backend/routers/seeds.py
frontend/package.json
frontend/src/api/db/client.js
frontend/src/router/index.js
frontend/src/views/ProjectView.vue
frontend/src/stores/providerStore.js
frontend/src/components/settings/ProviderForm.vue
```

### Deleted files

```text
backend/schema.sql
backend/migrations/20260705_state_provenance_phase1_2.sql
backend/migrations/20260705_state_provenance_phase1_2_rollback.sql
backend/routers/chapters.py
backend/routers/novel.py
backend/routers/settings_library.py
backend/routers/story_blocks.py
backend/routers/volumes.py
backend/routers/correction_tasks.py
backend/routers/project_state.py
backend/routers/provenance_support.py
backend/routers/export.py
```

这些删除只发生在新的实施 worktree。`tmp` 历史证据不纳入提交，也不在本里程碑物理清理归档目录。

## Task 1: Create the isolated implementation worktree

**Files:** No product files changed.

- [ ] **Step 1: Verify the source commit**

Run:

```powershell
git cat-file -t 4b85e8d
git show -s --format=%H 4b85e8d
```

Expected: `commit` and full hash beginning with `4b85e8d`.

- [ ] **Step 2: Create a clean branch and worktree from the exact baseline**

Run from `D:\Projects\Novel_Creater`:

```powershell
git worktree add C:\Users\zhangjun\.codex\worktrees\writer-core-v1\Novel_Creater -b codex/writer-core-v1 4b85e8d
```

Expected: worktree created at commit `4b85e8d`.

- [ ] **Step 3: Prove no dirty files were inherited**

Run:

```powershell
git -C C:\Users\zhangjun\.codex\worktrees\writer-core-v1\Novel_Creater status --short --branch
git -C C:\Users\zhangjun\.codex\worktrees\writer-core-v1\Novel_Creater ls-files --others --exclude-standard
```

Expected: branch line only; second command has no output.

- [ ] **Step 4: Bring in only the approved design and plans**

Run:

```powershell
git -C C:\Users\zhangjun\.codex\worktrees\writer-core-v1\Novel_Creater checkout codex/writer-core-v1-design -- docs/superpowers/specs/2026-07-11-writer-core-v1-design.md docs/superpowers/plans/2026-07-11-writer-core-v1-roadmap.md docs/superpowers/plans/2026-07-11-writer-core-foundation.md
```

Expected: exactly three documentation files are added; no product code from the design branch is imported.

- [ ] **Step 5: Commit the execution contract**

```powershell
git add docs/superpowers
git commit -m "docs: add writer core v1 execution contract"
```

## Task 2: Establish official test entrypoints

**Files:**

- Create: `scripts/run-tests.mjs`
- Create: `scripts/tests/run-tests.test.mjs`
- Create: `backend/requirements-dev.txt`
- Create: `pytest.ini`
- Create: `backend/tests/unit/test_test_entrypoint.py`
- Create: `frontend/tests/unit/testEntrypoint.test.mjs`
- Modify: `package.json`
- Modify: `frontend/package.json`
- Move: `frontend/tests/promptQuality.test.mjs` to `frontend/tests/legacy/promptQuality.test.mjs`

- [ ] **Step 1: Record the legacy Prompt baseline without changing product prompts**

Run:

```powershell
node --test frontend/tests/promptQuality.test.mjs
```

Expected historical evidence: 3 tests run and 3 fail. These assertions describe the retired rule-driven Prompt behavior and conflict with the approved V1 generation boundary. This result is baseline evidence only and is not a Ready gate. Do not change product Prompt code to satisfy it.

- [ ] **Step 2: Write dispatcher behavior tests and verify RED**

`scripts/tests/run-tests.test.mjs` imports pure discovery behavior from `scripts/run-tests.mjs` and verifies stable explicit `.test.mjs` discovery, exclusion of non-test files/directories, empty and unknown suite exit code 2 with usage output, and import without command-line execution.

Run:

```powershell
node --test scripts/tests/run-tests.test.mjs
```

Expected: FAIL because the dispatcher module or required behavior is absent. Then add the minimum cross-platform dispatcher and rerun the same command to GREEN.

- [ ] **Step 3: Add the official dispatcher and package entrypoints**

The dispatcher uses `spawnSync(..., shell: false)`, `process.execPath` for Node, and `process.env.PYTHON || 'python'` for Python. It uses `readdirSync` to discover and stably sort only direct `*.test.mjs` files in `scripts/tests/` and `frontend/tests/unit/`, passing explicit file paths to Node. It supports `unit`, `frontend-unit`, `integration`, and `browser`, rejects empty or unknown suites with exit code 2 and usage, and immediately propagates a failing child exit code. If a required formal test directory is empty, `unit` and `frontend-unit` fail closed with exit code 2 before spawning Node, so `node --test` can never fall back to repository-wide discovery. If a child command cannot start, stderr identifies the command plus the spawn error code/message without logging environment values.

Set root scripts to:

```json
{
  "scripts": {
    "test": "node scripts/run-tests.mjs unit",
    "test:integration": "node scripts/run-tests.mjs integration",
    "test:browser": "node scripts/run-tests.mjs browser",
    "test:milestone1": "node scripts/run-tests.mjs unit integration browser"
  }
}
```

Set frontend scripts to:

```json
{
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "vite build",
    "preview": "vite preview --host 127.0.0.1",
    "test:unit": "node ../scripts/run-tests.mjs frontend-unit"
  }
}
```

Move the old Prompt test with `git mv` into `frontend/tests/legacy/`. Formal test discovery never scans `legacy` or `tmp`. Add simple backend and frontend entrypoint smoke tests under their official unit directories, plus the required Python package initializers.

- [ ] **Step 4: Add and verify development test dependencies**

Create `backend/requirements-dev.txt`:

```text
pytest>=8.2,<9
pytest-asyncio>=0.23,<1
```

Create `pytest.ini`:

```ini
[pytest]
testpaths = backend/tests
asyncio_mode = auto
markers =
    mysql: requires an explicitly configured disposable MySQL server
```

Run:

```powershell
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
npm test
npm --prefix frontend run test:unit
npm --prefix frontend run build
git diff --check
```

Expected: all formal unit tests and the production build pass. Dispatcher behavior tests also prove empty formal directories fail closed and child startup errors are diagnosable. `npm test` output contains neither `tmp` nor `legacy`; the 3/3 legacy Prompt failure remains historical evidence, not a formal failure and not a Ready claim.

- [ ] **Step 5: Commit**

```powershell
git add package.json scripts backend/requirements-dev.txt backend/__init__.py backend/tests pytest.ini frontend/package.json frontend/tests docs/superpowers/plans/2026-07-11-writer-core-foundation.md
git commit -m "test: add official writer core test entrypoints"
```

## Task 3: Replace runtime DDL with an explicit schema manifest

**Files:**

- Create: `backend/schema_manifest.py`
- Create: `backend/schema_version.py`
- Create: `backend/schema/00_metadata.sql`
- Create: `backend/schema/10_core.sql`
- Create: `backend/schema/20_contracts.sql`
- Create: `backend/schema/30_planning.sql`
- Create: `backend/schema/40_drafts.sql`
- Create: `backend/schema/50_canon.sql`
- Create: `backend/schema/60_projections.sql`
- Create: `backend/schema/70_corpus.sql`
- Create: `backend/scripts/__init__.py`
- Create: `backend/scripts/initialize_database.py`
- Create: `backend/tests/unit/test_schema_manifest.py`
- Create: `backend/tests/unit/test_schema_version.py`
- Create: `backend/tests/unit/test_initialize_database.py`
- Delete: `backend/schema.sql`
- Delete: `backend/migrations/20260705_state_provenance_phase1_2.sql`
- Delete: `backend/migrations/20260705_state_provenance_phase1_2_rollback.sql`

- [ ] **Step 1: Write tests that define the bootstrap contract**

```python
# backend/tests/unit/test_schema_manifest.py
from backend.schema_manifest import FRAGMENTS, created_table_names, manifest_hash, read_statements

EXPECTED_TABLES = {
    "schema_metadata", "projects", "creative_seeds", "project_selected_seeds", "provider_profiles",
    "task_model_bindings", "task_model_binding_items", "creation_contracts",
    "style_contracts", "contract_asset_refs", "volume_plans", "story_blocks",
    "story_stages", "scene_tasks", "chapter_sessions", "working_drafts",
    "draft_candidates", "final_chapters", "finalization_change_sets",
    "finalization_records", "canon_entities", "entity_aliases",
    "canon_revisions", "canon_events", "current_state_projections",
    "memory_views", "arc_projections", "plot_thread_projections",
    "projection_heads", "corpus_sources", "corpus_chapters",
    "style_templates", "experience_cards", "reference_uses",
}

def test_manifest_is_ordered_complete_and_has_no_runtime_alter():
    assert FRAGMENTS == (
        "00_metadata.sql", "10_core.sql", "20_contracts.sql", "30_planning.sql",
        "40_drafts.sql", "50_canon.sql", "60_projections.sql", "70_corpus.sql",
    )
    sql = "\n".join(read_statements())
    assert "ALTER TABLE" not in sql.upper()
    assert "CREATE DATABASE" not in sql.upper()
    assert set(created_table_names()) == EXPECTED_TABLES
    assert len(manifest_hash()) == 64
```

```python
# backend/tests/unit/test_schema_version.py
import pytest
from backend.schema_version import EXPECTED_SCHEMA_VERSION, SchemaMismatch, verify_schema_version

@pytest.mark.asyncio
async def test_missing_schema_is_rejected_without_ddl(fake_connection):
    fake_connection.fetchone_result = None
    with pytest.raises(SchemaMismatch, match="initialize_database"):
        await verify_schema_version(fake_connection)
    assert fake_connection.executed == [
        ("SELECT schema_version, manifest_hash FROM schema_metadata WHERE singleton_id=1", None)
    ]

@pytest.mark.asyncio
async def test_wrong_version_is_rejected(fake_connection):
    fake_connection.fetchone_result = {"schema_version": "old", "manifest_hash": "x"}
    with pytest.raises(SchemaMismatch, match=EXPECTED_SCHEMA_VERSION):
        await verify_schema_version(fake_connection)
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q`

Expected: FAIL because schema modules do not exist.

- [ ] **Step 3: Implement the immutable manifest**

```python
# backend/schema_manifest.py
from hashlib import sha256
from pathlib import Path
import re

SCHEMA_DIR = Path(__file__).with_name("schema")
FRAGMENTS = (
    "00_metadata.sql", "10_core.sql", "20_contracts.sql", "30_planning.sql",
    "40_drafts.sql", "50_canon.sql", "60_projections.sql", "70_corpus.sql",
)

STATEMENT_DELIMITER = ";-- statement"
STATEMENT_SPLIT = re.compile(
    rf"^[ \t]*{re.escape(STATEMENT_DELIMITER)}[ \t]*$",
    re.MULTILINE,
)
LEADING_SQL_COMMENTS = re.compile(
    r"\A(?:\s+|--[^\n]*(?:\n|\Z)|/\*.*?\*/)*",
    re.DOTALL,
)
CREATE_TABLE = re.compile(r"^CREATE\s+TABLE\s+([A-Za-z0-9_]+)\s*\(", re.IGNORECASE)

def read_statements() -> list[str]:
    statements = []
    for name in FRAGMENTS:
        text = (SCHEMA_DIR / name).read_text(encoding="utf-8")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        statements.extend(part.strip() for part in STATEMENT_SPLIT.split(text) if part.strip())
    return statements

def manifest_hash() -> str:
    payload = f"\n{STATEMENT_DELIMITER}\n".join(read_statements()).encode("utf-8")
    return sha256(payload).hexdigest()

def created_table_names() -> tuple[str, ...]:
    """Returns CREATE TABLE names in manifest order for behavior tests."""
    names = []
    for statement in read_statements():
        content_start = LEADING_SQL_COMMENTS.match(statement).end()
        if match := CREATE_TABLE.match(statement[content_start:]):
            names.append(match.group(1))
    return tuple(names)
```

```python
# backend/schema_version.py
class SchemaMismatch(RuntimeError):
    """The connected database is not the exact Writer Core manifest."""

EXPECTED_SCHEMA_VERSION = "writer-core-v1.0.0"

def _is_missing_table_error(exc) -> bool:
    """Recognizes only MySQL 1146 without exposing driver text."""
    errno = getattr(exc, "errno", None)
    if errno == 1146:
        return True
    if not exc.args:
        return False
    value = exc.args[0]
    if value == 1146:
        return True
    return isinstance(value, tuple) and bool(value) and value[0] == 1146

async def verify_schema_version(conn) -> None:
    try:
        row = await conn.fetchone(
            "SELECT schema_version, manifest_hash FROM schema_metadata WHERE singleton_id=1"
        )
    except Exception as exc:
        if not _is_missing_table_error(exc):
            raise
        raise SchemaMismatch(
            "Writer Core schema metadata table is missing; run backend.scripts.initialize_database"
        ) from exc
    from backend.schema_manifest import manifest_hash
    expected_hash = manifest_hash()
    if not row or row["schema_version"] != EXPECTED_SCHEMA_VERSION or row["manifest_hash"] != expected_hash:
        raise SchemaMismatch(f"Expected {EXPECTED_SCHEMA_VERSION}/{expected_hash}; explicitly reinitialize the development database")
```

Only MySQL missing-table error `1146` is translated into `SchemaMismatch`, and the translated message never includes raw driver text. Authentication, timeout and other operational errors are re-raised unchanged and do not receive reinitialization guidance. A missing metadata row or version/hash mismatch remains a `SchemaMismatch`.

- [ ] **Step 4: Define the exact schema invariants in the fragments**

Use MySQL 8, InnoDB and `utf8mb4_0900_ai_ci`. Every project-owned table has `FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE`. Use these exact state and uniqueness rules:

```sql
-- 00_metadata.sql
CREATE TABLE schema_metadata (
  singleton_id TINYINT PRIMARY KEY,
  schema_version VARCHAR(64) NOT NULL,
  manifest_hash CHAR(64) NOT NULL,
  initialized_at BIGINT NOT NULL,
  CHECK (singleton_id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;-- statement
```

Every fragment delimiter is the complete content of its own line. Delimiter-like text inside SQL strings or comments is ordinary content, and leading SQL comments do not hide the following `CREATE TABLE` from `created_table_names()`.

`10_core.sql` defines `projects`, `creative_seeds`, `project_selected_seeds`, `provider_profiles`, `task_model_bindings` and `task_model_binding_items`. `project_selected_seeds` breaks the circular project/seed foreign key while preserving the logical `selectedSeedId`; it has `project_id` as its primary key, `seed_id` as a unique key, and FKs to both owning rows. Required keys are:

```sql
UNIQUE KEY uq_seed_title (project_id, title)
UNIQUE KEY uq_binding_project (project_id)
UNIQUE KEY uq_binding_task (binding_id, task_key)
UNIQUE KEY uq_selected_seed (seed_id)
CHECK (status IN ('drafting','active','completed','archived'))
CHECK (seed status IN ('candidate','selected','archived'))
```

Provider rows contain `enabled TINYINT(1) NOT NULL DEFAULT 1` and `sort_order INT NOT NULL DEFAULT 0`; stable fallback order is `(sort_order, created_at, id)`. Secrets remain DB-only columns `api_key` and `base_url`.

`20_contracts.sql` defines one creation contract and one style contract per project, plus unique `(creation_contract_id, asset_type, asset_id)` references. Contract JSON is versioned with `revision INT NOT NULL` and immutable snapshots use `content_hash CHAR(64) NOT NULL`.

`30_planning.sql` enforces:

```sql
CHECK (story block status IN ('planned','active','completed','failed','redirected'))
CHECK (story stage status IN ('pending','in_progress','completed','cancelled'))
CHECK (scene task status IN ('pending','in_progress','completed','cancelled'))
UNIQUE KEY uq_volume_num (project_id, volume_num)
UNIQUE KEY uq_block_num (project_id, block_num)
UNIQUE KEY uq_stage_order (story_block_id, stage_order)
UNIQUE KEY uq_scene_order (story_stage_id, task_order)
```

No planning table contains target chapter count, continuation count or forced-hook fields.

`40_drafts.sql` uses immutable hashes and only these states:

```sql
CHECK (chapter session status IN ('drafting','final'))
UNIQUE KEY uq_working_draft_session (chapter_session_id)
UNIQUE KEY uq_candidate_hash (chapter_session_id, content_hash)
UNIQUE KEY uq_final_chapter_num (project_id, chapter_num)
UNIQUE KEY uq_changeset_candidate (draft_candidate_id, candidate_hash, expected_canon_revision)
UNIQUE KEY uq_finalization_idempotency (idempotency_key)
```

`50_canon.sql` uses the following core columns and constraints:

```sql
CREATE TABLE canon_entities (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  entity_type VARCHAR(24) NOT NULL,
  canonical_name VARCHAR(200) NOT NULL,
  normalized_name VARCHAR(200) NOT NULL,
  created_revision INT NOT NULL,
  created_at BIGINT NOT NULL,
KEY ix_entity_name (project_id, entity_type, normalized_name),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (entity_type IN ('person','organization','place','item'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE entity_aliases (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  entity_id CHAR(36) NOT NULL,
  alias VARCHAR(200) NOT NULL,
  normalized_alias VARCHAR(200) NOT NULL,
  created_revision INT NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_entity_alias (project_id, entity_id, normalized_alias),
  KEY ix_alias_lookup (project_id, normalized_alias),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (entity_id) REFERENCES canon_entities(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE canon_revisions (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision_number INT NOT NULL,
  parent_revision_number INT NOT NULL,
  idempotency_key CHAR(64) NOT NULL,
  source_type VARCHAR(32) NOT NULL,
  source_id CHAR(36) NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_revision_number (project_id, revision_number),
  UNIQUE KEY uq_revision_idempotency (project_id, idempotency_key),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CHECK (source_type IN ('bootstrap','finalization','manual_test'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement

CREATE TABLE canon_events (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  revision_id CHAR(36) NOT NULL,
  revision_number INT NOT NULL,
  event_order INT NOT NULL,
  entity_id CHAR(36) NULL,
  fact_kind VARCHAR(24) NOT NULL,
  field_path VARCHAR(200) NOT NULL,
  value_json JSON NOT NULL,
  evidence_json JSON NOT NULL,
  effective_start_chapter INT NULL,
  effective_end_chapter INT NULL,
  assertion_operator VARCHAR(16) NOT NULL,
  value_cardinality VARCHAR(12) NOT NULL,
  confirmation_status VARCHAR(16) NOT NULL,
  created_at BIGINT NOT NULL,
  UNIQUE KEY uq_event_order (project_id, revision_number, event_order),
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (revision_id) REFERENCES canon_revisions(id) ON DELETE RESTRICT,
  FOREIGN KEY (entity_id) REFERENCES canon_entities(id) ON DELETE RESTRICT,
  CHECK (fact_kind IN ('stable_definition','dynamic_event','claim')),
  CHECK (confirmation_status IN ('confirmed','rejected')),
  CHECK (assertion_operator IN ('equals','not_equals')),
  CHECK (value_cardinality IN ('single','multi')),
  CHECK (effective_start_chapter IS NULL OR effective_start_chapter > 0),
  CHECK (effective_end_chapter IS NULL OR effective_end_chapter > 0),
  CHECK (effective_end_chapter IS NULL OR effective_start_chapter IS NULL OR effective_end_chapter >= effective_start_chapter)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;-- statement
```

`60_projections.sql` gives each projection row `project_id`, `revision_number`, natural-key columns and `payload_json`; every natural key is unique within `(project_id, revision_number)`. `projection_heads` has one row per project with `canon_revision_number`, `projection_revision_number`, `updated_at`, and a check that both numbers are non-negative.

`70_corpus.sql` records raw source path/hash, normalized chapter text, style template payload, experience card payload and each generation reference use. It never stores Provider credentials.

- [ ] **Step 5: Implement explicit initialization**

`python -m backend.scripts.initialize_database --database <name> --confirm-create <name>` uses the injectable async core
`initialize_database(admin_session, database_name, confirm_name, now_ms)` and must:

1. reject database names not matching `^[A-Za-z0-9_]+$`;
2. require `--database` and `--confirm-create` to match exactly;
3. query whether the database exists, create it explicitly only when absent, and refuse an existing database containing any tables before executing schema statements;
4. select the validated name, execute every manifest statement in order in one bootstrap connection, and insert singleton metadata with the computed manifest hash;
5. if bootstrap fails after this script created the database, attempt to drop that new database; successful cleanup re-raises the original bootstrap error, while failed cleanup raises an `ExceptionGroup` containing both original errors and explicitly warns that the named database may remain partially initialized; never drop an existing empty database on failure;
6. print only database name, version, hash and table count;
7. never print DSN, password, Provider row, API key or base URL.

- [ ] **Step 6: Run unit tests**

Run: `python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py -q`

Expected: PASS; scan confirms fragments contain no `ALTER TABLE`, `CREATE DATABASE`, `USE`, `IF NOT EXISTS` or old compatibility table. Tests also prove safe `1146` translation versus unchanged operational errors, independent-line delimiter parsing, confirmation, empty-database ordering, metadata, secret-free output, successful cleanup and dual-error cleanup failure behavior without connecting to a database.

- [ ] **Step 7: Commit**

```powershell
git add backend/schema backend/schema_manifest.py backend/schema_version.py backend/scripts backend/tests docs/superpowers/plans/2026-07-11-writer-core-foundation.md
git rm backend/schema.sql backend/migrations/20260705_state_provenance_phase1_2.sql backend/migrations/20260705_state_provenance_phase1_2_rollback.sql
git commit -m "feat: define immutable writer core schema manifest"
```

## Task 4: Add explicit connection and transaction boundaries

**Files:**

- Create: `backend/__init__.py`
- Create: `backend/tests/support/fakes.py`
- Create: `backend/tests/unit/test_database_transaction.py`
- Create: `backend/tests/unit/test_backend_launcher.py`
- Create: `backend/tests/unit/test_main_lifespan.py`
- Create: `backend/tests/unit/test_no_runtime_ddl.py`
- Modify: `backend/config.py`
- Modify: `backend/database.py`
- Modify: `backend/main.py`
- Modify: `start_backend.bat`
- Modify: `backend/routers/*.py` (only package-qualify active `database` imports,
  including the lazy import in `helpers.py`; do not change route behavior)

- [ ] **Step 1: Write rollback and startup tests**

```python
# backend/tests/unit/test_database_transaction.py
import pytest
from backend import database

@pytest.mark.asyncio
async def test_transaction_commits_once(monkeypatch, fake_pool):
    monkeypatch.setattr(database, "get_pool", lambda: fake_pool)
    async with database.transaction() as conn:
        await conn.execute("INSERT INTO x VALUES (%s)", (1,))
    assert fake_pool.raw.begin_count == 1
    assert fake_pool.raw.commit_count == 1
    assert fake_pool.raw.rollback_count == 0
    assert fake_pool.release_count == 1

@pytest.mark.asyncio
async def test_transaction_rolls_back_and_releases(monkeypatch, fake_pool):
    monkeypatch.setattr(database, "get_pool", lambda: fake_pool)
    with pytest.raises(RuntimeError, match="projection failed"):
        async with database.transaction() as conn:
            await conn.execute("INSERT INTO x VALUES (%s)", (1,))
            raise RuntimeError("projection failed")
    assert fake_pool.raw.commit_count == 0
    assert fake_pool.raw.rollback_count == 1
    assert fake_pool.release_count == 1
```

Add fake-context startup tests that import `backend.main.lifespan` from the repository
root and prove verification happens exactly once before yielding, schema mismatch is
not swallowed, and pool closure runs after normal shutdown and application failure.
Also use controlled async events to prove two simultaneous first `get_pool()` calls
create one shared pool, and that `close_pool()` racing initialization waits and closes
that pool exactly once. Assert no symbol named `ensure_schema` exists in
`backend.database` and that the module contains no runtime `CREATE TABLE` or
`ALTER TABLE` statements. Add a launcher contract test that reads, but never runs,
`start_backend.bat` and requires the repository-root package entrypoint.

- [ ] **Step 2: Verify failure**

Run: `python -m pytest backend/tests/unit/test_database_transaction.py -q`

Expected: FAIL because `transaction()` and the fake support do not exist.

- [ ] **Step 3: Replace the database module**

Use a focused session wrapper; transaction-aware repositories never call module-level `execute()`:

```python
# backend/database.py
import asyncio
from contextlib import asynccontextmanager
import aiomysql
from backend.config import MYSQL_CONFIG

_pool = None
_pool_lock = asyncio.Lock()

class DatabaseSession:
    def __init__(self, raw):
        self.raw = raw

    async def execute(self, sql, args=None):
        async with self.raw.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return cursor.rowcount

    async def fetchone(self, sql, args=None):
        async with self.raw.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return await cursor.fetchone()

    async def fetchall(self, sql, args=None):
        async with self.raw.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(sql, args)
            return await cursor.fetchall()

async def get_pool():
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                _pool = await aiomysql.create_pool(**MYSQL_CONFIG)
    return _pool

async def close_pool():
    global _pool
    async with _pool_lock:
        pool = _pool
        _pool = None
        if pool is not None:
            pool.close()
            await pool.wait_closed()

@asynccontextmanager
async def connection():
    pool = await get_pool()
    raw = await pool.acquire()
    try:
        yield DatabaseSession(raw)
    finally:
        pool.release(raw)

@asynccontextmanager
async def transaction():
    pool = await get_pool()
    raw = await pool.acquire()
    try:
        await raw.begin()
        session = DatabaseSession(raw)
        try:
            yield session
        except BaseException as body_error:
            try:
                await raw.rollback()
            except BaseException as rollback_error:
                raise BaseExceptionGroup(
                    "transaction body failed and rollback also failed",
                    [body_error, rollback_error],
                ) from body_error
            raise
        else:
            await raw.commit()
    finally:
        pool.release(raw)

async def execute(sql, args=None):
    async with connection() as session:
        return await session.execute(sql, args)

async def fetchone(sql, args=None):
    async with connection() as session:
        return await session.fetchone(sql, args)

async def fetchall(sql, args=None):
    async with connection() as session:
        return await session.fetchall(sql, args)
```

Delete `ensure_schema()` and every runtime `CREATE/ALTER` string.

Set `MYSQL_CONFIG["autocommit"] = True`; explicit transactions call `begin()` and hold one raw connection. Unit tests must prove all operations inside one transaction use the same `DatabaseSession` and raw connection.

The release boundary covers `begin()`, the yielded body, rollback and commit, and
calls `pool.release(raw)` exactly once after a successful acquire. A begin failure
must release without entering the body. A commit failure must propagate and release
without being reported as success or triggering a compensating rollback. If both the
body and rollback fail, raise a diagnostic exception group containing both original
errors; never replace the body error silently. Do not retry or switch connections.

Create the pool lock once at module import, never through a lazy check that crosses
an `await`. Pool creation uses double-checked locking so cached reads remain cheap
while simultaneous first callers cannot create competing pools. `close_pool()` uses
that same lock to take and clear the global pool and finish close/wait atomically with
respect to initialization.

Package-qualify `backend.config`, `backend.database`, `backend.routers` and
`backend.schema_version`. Mechanically change all active router imports from
`from database ...` to `from backend.database ...`, including function-local lazy
imports, while preserving the existing router registration and business logic.

- [ ] **Step 4: Make startup verify, never mutate, the schema**

`backend/main.py` must import with package-qualified paths and use:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with connection() as session:
            await verify_schema_version(session)
        yield
    finally:
        await close_pool()
```

No exception from schema verification is swallowed. Verification must complete
before lifespan yields, and `close_pool()` runs for verification failure, normal
shutdown and an exception raised after yield. The process refuses to serve requests
with missing or mismatched Schema.

`start_backend.bat` must change to the repository root with `cd /d "%~dp0"` and
invoke `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` (using the
existing preferred Python executable when present and the existing fallback
otherwise). It must not change into `backend` or launch `uvicorn main:app`; retain
the existing port, prompts and executable/dependency check behavior.

- [ ] **Step 5: Run tests**

Run: `python -m pytest backend/tests/unit/test_database_transaction.py backend/tests/unit/test_backend_launcher.py backend/tests/unit/test_main_lifespan.py backend/tests/unit/test_no_runtime_ddl.py backend/tests/unit/test_schema_version.py -q`

Expected: PASS; commit/rollback/release counts match exactly.

- [ ] **Step 6: Commit**

```powershell
git add backend/__init__.py backend/config.py backend/database.py backend/main.py backend/tests start_backend.bat
git commit -m "refactor: make database transactions explicit"
```

## Task 5: Define Canon identity and hard-conflict semantics

**Files:**

- Create: `backend/domain/__init__.py`
- Create: `backend/domain/canon.py`
- Create: `backend/tests/unit/test_canon_identity.py`
- Create: `backend/tests/unit/test_canon_conflicts.py`

- [x] **Step 1: Write exact identity and conflict tests**

```python
# backend/tests/unit/test_canon_identity.py
from backend.domain.canon import AliasResolution, normalize_name, resolve_alias

def test_name_normalization_is_exact_not_fuzzy():
    assert normalize_name("  沈砚　") == "沈砚"
    assert normalize_name("ＳＨＥＮ") == "shen"
    assert normalize_name("沈砚") != normalize_name("沈彦")

def test_alias_resolution_never_picks_one_of_multiple_entities():
    result = resolve_alias("掌柜", [{"entity_id": "a"}, {"entity_id": "b"}])
    assert result == AliasResolution(status="ambiguous", entity_ids=("a", "b"))
```

```python
# backend/tests/unit/test_canon_conflicts.py
from dataclasses import replace
from backend.domain.canon import CanonEventInput, find_hard_conflicts

def event(value, *, kind="stable_definition", status="confirmed", start=1, end=None):
    return CanonEventInput(
        entity_id="person-1", fact_kind=kind, field_path="identity.birthplace",
        value=value, evidence={"quote": "正文证据"},
        effective_start_chapter=start, effective_end_chapter=end,
        confirmation_status=status, assertion_operator="equals", value_cardinality="single",
    )

def test_confirmed_overlapping_stable_values_conflict():
    assert len(find_hard_conflicts([event("北平")], [event("应天")])) == 1

def test_claim_dynamic_change_and_non_overlapping_history_do_not_conflict():
    assert find_hard_conflicts([event("北平")], [event("应天", kind="claim")]) == []
    assert find_hard_conflicts([event("百户", kind="dynamic_event")], [event("千户", kind="dynamic_event")]) == []
    assert find_hard_conflicts([event("北平", start=1, end=5)], [event("应天", start=6)]) == []

def test_different_additive_values_are_not_mutually_exclusive():
    left = event("木工")
    right = event("算学")
    left = replace(left, field_path="skills", value_cardinality="multi")
    right = replace(right, field_path="skills", value_cardinality="multi")
    assert find_hard_conflicts([left], [right]) == []

def test_equals_and_not_equals_same_value_are_mutually_exclusive():
    denied = replace(event("北平"), assertion_operator="not_equals")
    assert len(find_hard_conflicts([event("北平")], [denied])) == 1
```

- [x] **Step 2: Verify failure**

Run: `python -m pytest backend/tests/unit/test_canon_identity.py backend/tests/unit/test_canon_conflicts.py -q`

Expected: FAIL because the domain module does not exist.

- [x] **Step 3: Implement closed enums and pure rules**

```python
# backend/domain/canon.py
from dataclasses import dataclass
from enum import StrEnum
import json
import unicodedata

class EntityType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    PLACE = "place"
    ITEM = "item"

class FactKind(StrEnum):
    STABLE_DEFINITION = "stable_definition"
    DYNAMIC_EVENT = "dynamic_event"
    CLAIM = "claim"

class ConfirmationStatus(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"

class AssertionOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"

class ValueCardinality(StrEnum):
    SINGLE = "single"
    MULTI = "multi"

@dataclass(frozen=True)
class CanonEventInput:
    entity_id: str | None
    fact_kind: FactKind
    field_path: str
    value: object
    evidence: dict
    effective_start_chapter: int | None
    effective_end_chapter: int | None
    confirmation_status: ConfirmationStatus
    assertion_operator: AssertionOperator
    value_cardinality: ValueCardinality

@dataclass(frozen=True)
class AliasResolution:
    status: str
    entity_ids: tuple[str, ...]

def normalize_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().casefold()

def resolve_alias(name: str, rows: list[dict]) -> AliasResolution:
    ids = tuple(sorted({str(row["entity_id"]) for row in rows}))
    return AliasResolution("missing" if not ids else "resolved" if len(ids) == 1 else "ambiguous", ids)

def _overlaps(left: CanonEventInput, right: CanonEventInput) -> bool:
    left_start = left.effective_start_chapter or 1
    right_start = right.effective_start_chapter or 1
    left_end = left.effective_end_chapter or 2**31 - 1
    right_end = right.effective_end_chapter or 2**31 - 1
    return max(left_start, right_start) <= min(left_end, right_end)

def _value_key(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _mutually_exclusive(left: CanonEventInput, right: CanonEventInput) -> bool:
    left_value = _value_key(left.value)
    right_value = _value_key(right.value)
    if left.assertion_operator == right.assertion_operator == AssertionOperator.EQUALS:
        return (
            left.value_cardinality == right.value_cardinality == ValueCardinality.SINGLE
            and left_value != right_value
        )
    return (
        {left.assertion_operator, right.assertion_operator}
        == {AssertionOperator.EQUALS, AssertionOperator.NOT_EQUALS}
        and left_value == right_value
    )

def find_hard_conflicts(existing: list[CanonEventInput], incoming: list[CanonEventInput]):
    conflicts = []
    for old in existing:
        for new in incoming:
            if (
                old.entity_id == new.entity_id
                and old.field_path == new.field_path
                and old.fact_kind == new.fact_kind == FactKind.STABLE_DEFINITION
                and old.confirmation_status == new.confirmation_status == ConfirmationStatus.CONFIRMED
                and _overlaps(old, new)
                and _mutually_exclusive(old, new)
            ):
                conflicts.append((old, new))
    return conflicts
```

Validate on construction: names and field paths must be non-empty; chapter bounds must be positive; end cannot precede start; confirmed events require non-empty evidence. Events for the same entity/field must use the same cardinality; a mismatch is an invalid ChangeSet that requires author correction, not an automatic conflict guess. Do not add fuzzy matching, rehome, find-or-create or name-based automatic merge.

- [x] **Step 4: Align Canon SQL with conflict semantics**

In `backend/schema/50_canon.sql`, replace opaque validity strings with:

```sql
effective_start_chapter INT NULL,
effective_end_chapter INT NULL,
assertion_operator VARCHAR(16) NOT NULL,
value_cardinality VARCHAR(12) NOT NULL,
CHECK (effective_start_chapter IS NULL OR effective_start_chapter > 0),
CHECK (effective_end_chapter IS NULL OR effective_end_chapter > 0),
CHECK (effective_end_chapter IS NULL OR effective_start_chapter IS NULL OR effective_end_chapter >= effective_start_chapter),
CHECK (assertion_operator IN ('equals','not_equals')),
CHECK (value_cardinality IN ('single','multi')),
```

- [x] **Step 5: Run tests and commit**

Run: `python -m pytest backend/tests/unit/test_canon_identity.py backend/tests/unit/test_canon_conflicts.py -q`

Expected: PASS.

```powershell
git add backend/domain backend/schema/50_canon.sql backend/tests/unit
git commit -m "feat: define canon identity and conflict boundary"
```

### Task 5 follow-up: validate complete incoming ChangeSets

- [x] Validate one cardinality per non-empty entity/field stable group across existing and incoming events, including incoming-only and dirty-history groups.
- [x] Compare both `existing × incoming` and unordered incoming pairs for hard conflicts without comparing existing history against itself.
- [x] Include canonical evidence JSON in the stable event key so only exact duplicate events collapse and reordered inputs return the same complete conflict tuple.
- [x] Deep-freeze strict JSON values and evidence into hashable immutable structures while preserving canonical JSON comparison.
- [x] Make event equality, hashing and key caching JSON-type-sensitive so booleans, integers, floats and nested variants remain distinct.
- [x] Reject alias identifiers and normalized aliases that are not exact strings; trim, deduplicate and sort valid entity IDs.
- [x] Group stable events by entity/field before cardinality validation and conflict candidate generation so unrelated scopes never enter pair evaluation.

## Task 6: Build deterministic projections as pure functions

**Files:**

- Create: `backend/services/__init__.py`
- Create: `backend/services/projections.py`
- Create: `backend/tests/unit/test_projections.py`

- [x] **Step 1: Write deterministic projection tests**

```python
# backend/tests/unit/test_projections.py
from backend.services.projections import build_projection_bundle

def test_projection_uses_one_confirmed_canon_stream():
    events = [
        {"id": "e1", "revision_number": 1, "event_order": 1, "entity_id": "p1",
         "fact_kind": "stable_definition", "field_path": "identity.name", "value": "沈砚",
         "confirmation_status": "confirmed", "evidence": {"quote": "沈砚抬头"}},
        {"id": "e2", "revision_number": 2, "event_order": 1, "entity_id": "p1",
         "fact_kind": "dynamic_event", "field_path": "status.rank", "value": "百户",
         "confirmation_status": "confirmed", "evidence": {"quote": "授百户"}},
        {"id": "e3", "revision_number": 2, "event_order": 2, "entity_id": "p1",
         "fact_kind": "claim", "field_path": "identity.origin", "value": "天外来客",
         "confirmation_status": "confirmed", "evidence": {"quote": "传闻"}},
    ]
    first = build_projection_bundle(2, events)
    second = build_projection_bundle(2, list(reversed(events)))
    assert first == second
    assert first.current_state["p1"]["status.rank"] == "百户"
    assert "identity.origin" not in first.current_state["p1"]
    assert [item["eventId"] for item in first.memories["p1"]] == ["e1", "e2", "e3"]

def test_arc_and_plot_views_are_filters_not_second_extractions():
    bundle = build_projection_bundle(1, [
        {"id": "a", "revision_number": 1, "event_order": 1, "entity_id": "p1",
         "fact_kind": "dynamic_event", "field_path": "arc.trust", "value": "动摇",
         "confirmation_status": "confirmed", "evidence": {}},
        {"id": "b", "revision_number": 1, "event_order": 2, "entity_id": None,
         "fact_kind": "dynamic_event", "field_path": "plot.gunpowder", "value": "推进",
         "confirmation_status": "confirmed", "evidence": {}},
    ])
    assert bundle.arcs["p1"]["arc.trust"] == "动摇"
    assert bundle.plot_threads["__global__"]["plot.gunpowder"] == "推进"
```

- [x] **Step 2: Verify failure**

Run: `python -m pytest backend/tests/unit/test_projections.py -q`

Expected: FAIL because projection service does not exist.

- [x] **Step 3: Implement one deterministic reducer**

Define immutable `ProjectionBundle(revision, current_state, memories, arcs, plot_threads, content_hash)`. Strictly validate and freeze each event, reject duplicate IDs and duplicate `(revision_number, event_order)` stream positions, then sort by `(revision_number, event_order, id)`. Ignore rejected events, place every confirmed event into memory, exclude claims from current state, and derive arc/plot views only by `field_path` prefix. Plot threads use `entity_id` or `__global__` as the outer natural key so the same field on different entities never overwrites. Compute `content_hash` from canonical sorted JSON of `{revision,currentState,memories,arcs,plotThreads}`.

The function accepts event rows only; it must not accept chapter text, a model client, a Prompt or an independent settings/memory input.

- [x] **Step 4: Run tests and commit**

Run: `python -m pytest backend/tests/unit/test_projections.py -q`

Expected: PASS and identical hash for reversed input.

```powershell
git add backend/services backend/tests/unit/test_projections.py
git commit -m "feat: derive all projections from canon events"
```

## Task 7: Implement atomic Canon revision commits

**Files:**

- Create: `backend/repositories/__init__.py`
- Create: `backend/repositories/canon.py`
- Create: `backend/services/canon.py`
- Create: `backend/tests/unit/test_canon_revision.py`
- Create: `backend/tests/unit/test_canon_idempotency.py`
- Create: `backend/tests/unit/test_canon_rollback.py`

- [ ] **Step 1: Write service tests against one fake transaction**

```python
# backend/tests/unit/test_canon_revision.py
import pytest
from backend.services.canon import CanonHeadMismatch, CommitCanonRevision, CanonService

@pytest.mark.asyncio
async def test_expected_head_mismatch_writes_nothing(canon_repo):
    canon_repo.head = 3
    service = CanonService(canon_repo)
    request = CommitCanonRevision(project_id="p", expected_head=2, idempotency_key="k", entities=(), aliases=(), events=())
    with pytest.raises(CanonHeadMismatch):
        await service.commit(request)
    assert canon_repo.write_calls == []
```

```python
# backend/tests/unit/test_canon_idempotency.py
@pytest.mark.asyncio
async def test_duplicate_idempotency_key_returns_first_revision(canon_repo):
    canon_repo.existing_idempotent_result = {"revisionNumber": 4, "id": "r4"}
    result = await CanonService(canon_repo).commit(request(expected_head=3, key="same"))
    assert result.revision_number == 4
    assert canon_repo.write_calls == []
```

```python
# backend/tests/unit/test_canon_rollback.py
@pytest.mark.asyncio
async def test_projection_failure_escapes_transaction_and_rolls_back(transaction_factory, canon_repo):
    canon_repo.raise_on_replace_projections = RuntimeError("projection failed")
    with pytest.raises(RuntimeError, match="projection failed"):
        await CanonService(canon_repo, transaction_factory=transaction_factory).commit(request())
    assert transaction_factory.rollback_count == 1
    assert transaction_factory.commit_count == 0
```

Also test: revision increments exactly once, every event receives the new revision, hard conflicts write nothing, an alias resolving to multiple entity IDs returns an ambiguity result instead of selecting one, and projection head equals Canon head before commit returns.

- [ ] **Step 2: Verify failure**

Run: `python -m pytest backend/tests/unit/test_canon_revision.py backend/tests/unit/test_canon_idempotency.py backend/tests/unit/test_canon_rollback.py -q`

Expected: FAIL because repository/service modules do not exist.

- [ ] **Step 3: Implement repository methods with mandatory sessions**

`backend/repositories/canon.py` exposes only methods whose first runtime argument is `session`: `lock_head(session, project_id) -> int`、`find_idempotent(session, project_id, key)`、`list_alias_matches(session, project_id, normalized_alias)`、`list_active_stable_events(session, project_id, entity_ids, field_paths)`、`insert_revision(session, row)`、`insert_entities(session, rows)`、`insert_aliases(session, rows)`、`insert_events(session, rows)`、`list_confirmed_events(session, project_id)`、`replace_projections(session, project_id, bundle)`、`advance_heads(session, project_id, revision, content_hash)`。

`lock_head` executes `SELECT canon_revision_number FROM projection_heads WHERE project_id=%s FOR UPDATE`. The project creation transaction always inserts revision 0 and projection head 0, so a missing head is data corruption, not a fallback case.

Projection replacement deletes only rows for the same project inside the current transaction, inserts the complete new bundle, then updates `projection_heads`. There is no public repository method to mutate one projection field independently.

- [ ] **Step 4: Implement service ordering**

```python
# backend/services/canon.py — required ordering
async def commit(self, request: CommitCanonRevision) -> CommitCanonResult:
    async with self.transaction_factory() as session:
        head = await self.repository.lock_head(session, request.project_id)
        existing = await self.repository.find_idempotent(
            session, request.project_id, request.idempotency_key
        )
        if existing:
            return CommitCanonResult.from_row(existing)
        if head != request.expected_head:
            raise CanonHeadMismatch(expected=request.expected_head, actual=head)

        await self._reject_alias_ambiguity(session, request)
        await self._reject_hard_conflicts(session, request)
        revision_number = head + 1
        revision = self._build_revision(request, revision_number)
        await self.repository.insert_revision(session, revision)
        await self.repository.insert_entities(session, self._entity_rows(request, revision_number))
        await self.repository.insert_aliases(session, self._alias_rows(request, revision_number))
        await self.repository.insert_events(session, self._event_rows(request, revision))
        events = await self.repository.list_confirmed_events(session, request.project_id)
        bundle = build_projection_bundle(revision_number, events)
        await self.repository.replace_projections(session, request.project_id, bundle)
        await self.repository.advance_heads(
            session, request.project_id, revision_number, bundle.content_hash
        )
        return CommitCanonResult.from_revision(revision, bundle.content_hash)
```

Generate IDs and timestamps before their insert calls. The idempotency key must already be a SHA-256 hex string; reject any other form. M1 accepts `source_type='manual_test'` only from internal service tests and does not expose this method as HTTP write API.

- [ ] **Step 5: Run all Canon unit tests**

Run: `python -m pytest backend/tests/unit/test_canon_*.py backend/tests/unit/test_projections.py -q`

Expected: PASS; fake transaction shows one session object across every repository call.

- [ ] **Step 6: Commit**

```powershell
git add backend/repositories backend/services/canon.py backend/tests/unit
git commit -m "feat: commit canon revisions atomically"
```

## Task 8: Expose read-only state and eliminate secret-bearing responses

**Files:**

- Create: `backend/routers/canon.py`
- Create: `backend/serializers/__init__.py`
- Create: `backend/serializers/provider.py`
- Create: `backend/security/__init__.py`
- Create: `backend/security/redaction.py`
- Create: `backend/tests/api/test_canon_routes.py`
- Create: `backend/tests/api/test_provider_redaction.py`
- Create: `backend/tests/api/test_secret_error_redaction.py`
- Modify: `backend/main.py`
- Modify: `backend/routers/projects.py`
- Modify: `backend/routers/providers.py`
- Modify: `backend/routers/seeds.py`
- Delete: incompatible backend routers listed in the locked file structure

### Task 8A: Make project creation a foundation transaction

**Additional files:**

- Create: `backend/repositories/projects.py`
- Create: `backend/services/projects.py`
- Create: `backend/tests/unit/test_project_creation.py`

- [ ] **Step 1: Write the project foundation transaction tests**

```python
# backend/tests/unit/test_project_creation.py
import pytest
from backend.services.projects import CreateProject, ProjectService, TASK_KEYS

@pytest.mark.asyncio
async def test_project_create_builds_revision_head_and_binding_on_one_session(project_repo, transaction_factory):
    project_repo.previous_bindings = {"writing": "enabled-previous"}
    project_repo.enabled_providers = [
        {"id": "fallback", "sort_order": 0, "created_at": 1},
        {"id": "enabled-previous", "sort_order": 1, "created_at": 2},
    ]
    result = await ProjectService(project_repo, transaction_factory).create(
        CreateProject(id="p1", title="新项目", genre="穿越", description="", target_words=100000, target_chapters=100)
    )
    assert result.id == "p1"
    assert project_repo.inserted_revision == {"project_id": "p1", "revision_number": 0, "parent_revision_number": 0}
    assert project_repo.inserted_head == {"project_id": "p1", "canon_revision_number": 0, "projection_revision_number": 0}
    assert project_repo.binding_items["writing"] == "enabled-previous"
    assert project_repo.binding_items["seed"] == "fallback"
    assert set(project_repo.binding_items) == set(TASK_KEYS)
    assert len({id(session) for session in project_repo.seen_sessions}) == 1
    assert transaction_factory.commit_count == 1

@pytest.mark.asyncio
async def test_project_create_rolls_back_every_foundation_row(project_repo, transaction_factory):
    project_repo.raise_on_insert_head = RuntimeError("head failed")
    with pytest.raises(RuntimeError, match="head failed"):
        await ProjectService(project_repo, transaction_factory).create(
            CreateProject(id="p1", title="新项目", genre="穿越", description="", target_words=100000, target_chapters=100)
        )
    assert transaction_factory.commit_count == 0
    assert transaction_factory.rollback_count == 1
    assert project_repo.committed_rows == []

@pytest.mark.asyncio
async def test_project_create_without_enabled_provider_creates_no_binding_items(project_repo, transaction_factory):
    project_repo.previous_bindings = {"writing": "disabled"}
    project_repo.enabled_providers = []
    await ProjectService(project_repo, transaction_factory).create(
        CreateProject(id="p1", title="新项目", genre="穿越", description="", target_words=100000, target_chapters=100)
    )
    assert project_repo.binding_items == {}
```

- [ ] **Step 2: Verify failure**

Run: `python -m pytest backend/tests/unit/test_project_creation.py -q`

Expected: FAIL because project repository/service do not exist.

- [ ] **Step 3: Implement the transaction in the required order**

```python
# backend/services/projects.py — create method
TASK_KEYS = ("seed", "planning", "writing", "audit", "summary", "extraction", "polish", "market")

async def create(self, command: CreateProject) -> ProjectResult:
    async with self.transaction_factory() as session:
        await self.repository.insert_project(session, command)
        await self.repository.insert_bootstrap_revision(session, command.id)
        await self.repository.insert_projection_head(session, command.id)
        enabled = await self.repository.list_enabled_providers(session)
        enabled_ids = {row["id"] for row in enabled}
        fallback_id = enabled[0]["id"] if enabled else None
        previous_snapshot = await self.repository.find_previous_binding_snapshot(session, command.id)
        previous = previous_snapshot.provider_ids if previous_snapshot else {}
        resolved = {
            task: previous.get(task) if previous.get(task) in enabled_ids else fallback_id
            for task in TASK_KEYS
        }
        resolved = {task: provider_id for task, provider_id in resolved.items() if provider_id}
        source_project_id = previous_snapshot.source_project_id if previous_snapshot else None
        await self.repository.insert_binding_snapshot(session, command.id, resolved, source_project_id)
        return ProjectResult.from_command(command)
```

Repository `list_enabled_providers` orders by `sort_order ASC, created_at ASC, id ASC`; `find_previous_binding_snapshot` orders projects by `created_at DESC, id DESC`. Bootstrap revision uses `source_type='bootstrap'` and a deterministic SHA-256 key for `project_id/revision-0`; head row stores both revisions as 0 and the hash of empty projections. `backend/routers/projects.py` calls only this service for create and never performs a second write.

- [ ] **Step 4: Run and commit the project transaction**

Run: `python -m pytest backend/tests/unit/test_project_creation.py -q`

Expected: PASS for success, fallback, no-model and rollback cases.

```powershell
git add backend/repositories/projects.py backend/services/projects.py backend/routers/projects.py backend/tests/unit/test_project_creation.py
git commit -m "feat: create projects with canon foundation atomically"
```

- [ ] **Step 1: Write API tests before changing routes**

```python
# backend/tests/api/test_provider_redaction.py
SECRET = "sk-plain-secret-must-never-leave-backend"
PRIVATE_URL = "https://private-provider.example/v1"

def assert_no_secret(payload):
    text = json.dumps(payload, ensure_ascii=False)
    assert SECRET not in text
    assert PRIVATE_URL not in text
    assert "apiKey" not in text and "api_key" not in text
    assert "baseURL" not in text and "base_url" not in text

def test_provider_list_create_update_and_binding_status_are_redacted(client, provider_row):
    for response in (
        client.get("/api/providers"),
        client.post("/api/providers", json=create_payload(SECRET, PRIVATE_URL)),
        client.put(f"/api/providers/{provider_row['id']}", json={"apiKey": SECRET}),
        client.get("/api/projects/project-1/bindings/status"),
    ):
        assert response.status_code < 400
        assert_no_secret(response.json())
```

`test_secret_error_redaction.py` sends an invalid Provider payload containing the sentinel key and private URL so FastAPI raises `RequestValidationError`; it asserts the 422 body and captured logs contain neither value. It also raises an internal Provider exception whose message includes both values and asserts the HTTP 500 body contains only a correlation ID and generic message.

```python
# backend/tests/api/test_canon_routes.py
def test_writer_core_state_reports_revision_sync(client):
    response = client.get("/api/projects/p1/writer-core/state")
    assert response.json() == {
        "projectId": "p1", "schemaVersion": "writer-core-v1.0.0",
        "canonHeadRevision": 2, "projectionHeadRevision": 2,
        "projectionInSync": True,
    }

def test_canon_router_has_no_write_route(app):
    canon_paths = {
        route.path: route.methods for route in app.routes
        if "/canon" in route.path or "/projections" in route.path
    }
    assert all(methods <= {"GET", "HEAD"} for methods in canon_paths.values())
```

- [ ] **Step 2: Verify the current Provider API leaks the key**

Run: `python -m pytest backend/tests/api/test_provider_redaction.py -q`

Expected: FAIL because current `SELECT *` responses include `apiKey` and `baseURL`.

- [ ] **Step 3: Add one secret-free serializer**

```python
# backend/serializers/provider.py
def provider_public(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "providerType": row["provider_type"],
        "model": row["model"],
        "enabled": bool(row["enabled"]),
        "sortOrder": row["sort_order"],
        "stream": bool(row["stream"]),
        "maxContextTokens": row["max_context_tokens"],
        "maxOutputTokens": row["max_output_tokens"],
        "temperature": row["temperature"],
        "topP": row["top_p"],
        "supportsJSON": bool(row["supports_json"]),
        "supportsStreaming": bool(row["supports_streaming"]),
        "notes": row.get("notes") or "",
        "thinking": row.get("thinking"),
        "hasKey": bool(row.get("api_key")),
        "hasBaseURL": bool(row.get("base_url")),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
```

All Provider list/create/update/binding response paths call this serializer. Error handlers log only provider ID, HTTP status and a generated correlation ID; never include request headers, upstream response body, key or URL.

`backend/security/redaction.py` recursively replaces values under case-insensitive keys `apiKey`, `api_key`, `authorization`, `baseURL`, `base_url`, `password` and `token` with `[REDACTED]`. Register dedicated FastAPI handlers for `RequestValidationError` and unexpected exceptions; handlers sanitize structured details before JSON serialization, never return `str(exc)`, and log only exception type plus correlation ID. Add a logging filter using the same redactor for the active application logger. Do not implement response-body substring rewriting; active success responses remain safe by construction through explicit serializers.

Update semantics are explicit: omitted `apiKey` keeps the old key; `clearApiKey: true` clears it. A blank string never accidentally replaces a stored key. Apply the same rule to `baseURL` with `clearBaseURL`.

- [ ] **Step 4: Implement the read-only router**

Register only:

```text
GET /api/projects/{pid}/writer-core/state
GET /api/projects/{pid}/canon/head
GET /api/projects/{pid}/canon/revisions
GET /api/projects/{pid}/canon/entities
GET /api/projects/{pid}/canon/entities/{entity_id}
GET /api/projects/{pid}/canon/events
GET /api/projects/{pid}/canon/aliases/resolve?name={name}
GET /api/projects/{pid}/projections/head
GET /api/projects/{pid}/projections/current-state
GET /api/projects/{pid}/projections/memories
GET /api/projects/{pid}/projections/arcs
GET /api/projects/{pid}/projections/plot-threads
```

Alias resolution returns HTTP 200 with `{status:'missing'|'resolved'|'ambiguous', entityIds:['entity-id']}`; ambiguity is expected product state, not a 500. Projection endpoints return 409 `projection_out_of_sync` if heads differ.

- [ ] **Step 5: Make project create/delete transactional and model binding deterministic**

Project create performs in one transaction: insert project, insert bootstrap revision 0, insert projection head 0, resolve each task binding, insert binding snapshot. Fixed task keys are:

```python
TASK_KEYS = (
    "seed", "planning", "writing", "audit",
    "summary", "extraction", "polish", "market",
)
```

The “previous project” is the most recently created other project ordered by `(created_at DESC, id DESC)`. For each task, copy that project's snapshot if its Provider remains enabled; otherwise choose the first enabled Provider ordered by `(sort_order, created_at, id)`. If none is enabled, leave the item absent; AI commands in subsequent milestones must block. Project deletion executes one `DELETE FROM projects WHERE id=%s` in a transaction and relies on FKs.

Project content state in M1 is:

```json
{
  "seedsCount": 3,
  "canonHeadRevision": 0,
  "hasFinalChapters": false,
  "writerEnabled": false
}
```

It must not query old chapters/tempDrafts/settings tables.

Replace `backend/routers/seeds.py` with one M1 read route, `GET /api/projects/{pid}/seeds`, joining `project_selected_seeds` so the selected row is serialized with `status='selected'`. Do not register seed POST/PUT/DELETE in M1; the unique selection command and seed-pool writes return in the M2 contract flow. This removes the old `ensure_project_without_chapter_content` dependency instead of emulating chapters with a fallback query.

- [ ] **Step 6: Remove old live routes and files**

`backend/main.py` registers only health, projects, providers, seeds and new Canon router. Keep `backend/routers/ai_proxy.py` as committed source reference but do not register it in M1; M2/M5 reactivates it only after its error/diagnostic paths pass the same secret boundary. Physically delete the incompatible state routers and their imports. Do not return synthetic `migrationUnavailable` or field-existence fallback objects.

- [ ] **Step 7: Run API tests and route inventory**

Run:

```powershell
python -m pytest backend/tests/api -q
rg -n "api_key|apiKey|base_url|baseURL|includeApiKeys|migrationUnavailable|SHOW COLUMNS|ensure_schema" backend
```

Expected: tests PASS. Search hits are limited to request models, DB-only Provider resolution, the redaction tests, and explicit secret fields in schema; no response/export/log path contains them.

- [ ] **Step 8: Commit**

```powershell
git add backend/main.py backend/routers backend/serializers backend/tests/api
git rm backend/routers/chapters.py backend/routers/novel.py backend/routers/settings_library.py backend/routers/story_blocks.py backend/routers/volumes.py backend/routers/correction_tasks.py backend/routers/project_state.py backend/routers/provenance_support.py backend/routers/export.py
git commit -m "feat: expose secret-free writer core state"
```

## Task 9: Prove bootstrap, transaction, idempotency and reset on disposable MySQL

**Files:**

- Create: `backend/tests/support/disposable_mysql.py`
- Create: `backend/tests/integration/conftest.py`
- Create: `backend/tests/integration/test_schema_bootstrap.py`
- Create: `backend/tests/integration/test_canon_atomic_commit.py`
- Create: `backend/tests/integration/test_canon_idempotency.py`
- Create: `backend/tests/integration/test_projection_rollback.py`
- Create: `backend/scripts/reset_writer_core_data.py`
- Create: `backend/tests/integration/test_reset_writer_core_data.py`

- [ ] **Step 1: Implement a guard before any integration test is allowed to connect**

```python
# backend/tests/support/disposable_mysql.py
import os
import re
import uuid

TEST_PREFIX = "novel_creator_test_"

def test_server_config() -> dict:
    required = ("TEST_MYSQL_HOST", "TEST_MYSQL_PORT", "TEST_MYSQL_USER", "TEST_MYSQL_PASSWORD")
    missing = [name for name in required if name not in os.environ]
    if missing:
        raise RuntimeError(f"Disposable MySQL requires explicit variables: {', '.join(missing)}")
    return {
        "host": os.environ["TEST_MYSQL_HOST"],
        "port": int(os.environ["TEST_MYSQL_PORT"]),
        "user": os.environ["TEST_MYSQL_USER"],
        "password": os.environ["TEST_MYSQL_PASSWORD"],
        "charset": "utf8mb4",
        "autocommit": True,
    }

def new_database_name() -> str:
    return f"{TEST_PREFIX}{uuid.uuid4().hex}"

def assert_disposable_name(name: str) -> None:
    if not re.fullmatch(r"novel_creator_test_[a-f0-9]{32}", name):
        raise RuntimeError(f"Refusing non-disposable database: {name}")
```

No test support code reads `MYSQL_HOST`, `MYSQL_DB` or the product default. The fixture creates one unique database, runs the same `schema_manifest` initializer, yields its config, then drops it in `finally` after calling `assert_disposable_name()` again.

- [ ] **Step 2: Write fresh bootstrap and mismatch tests**

`test_schema_bootstrap.py` must assert the exact expected table set from Task 3, metadata version/hash, all tables use InnoDB/utf8mb4, and the second initializer invocation refuses the non-empty database. It then corrupts the metadata version and proves application verification refuses startup without altering any table.

- [ ] **Step 3: Write real atomicity tests**

`test_canon_atomic_commit.py` creates a project with revision/head 0, commits one entity, alias and two events through `CanonService`, then asserts in the same database:

```text
canon_revisions: revision 1 exactly once
canon_events: two rows both revision 1
current_state_projections: payload matches confirmed non-claim state
memory_views: payload contains the same two event IDs
projection_heads: canon_revision_number = projection_revision_number = 1
```

`test_canon_idempotency.py` submits the identical request twice and asserts every table count is unchanged after the second call and both results have the same revision ID/hash.

`test_projection_rollback.py` injects a repository failure immediately before `advance_heads`; after the exception it asserts revision/events/entities/aliases/projections remain at their pre-call counts and heads remain 0.

Also submit the same stable field with overlapping chapters and a different value; assert the service raises a hard conflict and all counts remain unchanged.

- [ ] **Step 4: Implement the one-time preserve-and-reset command**

The only allowed product reset shape is:

```powershell
python -m backend.scripts.reset_writer_core_data --database novel_creator --project-title 永乐大典 --seed-title 永乐长明 --seed-title 文渊山海 --seed-title 典镇山河 --preferred-provider-name 联通云 --preferred-model deepseek-v4-flash --confirm-reset novel_creator --execute
```

Before `--execute`, default dry-run reports only counts, IDs, titles, provider display names/model IDs and table names. It must find exactly one enabled row whose name is `联通云` and model is `deepseek-v4-flash`; zero or multiple matches abort the reset rather than leaving empty or ambiguous bindings. It never prints descriptions containing chapter text, `api_key`, `base_url`, password or DSN.

Execution performs this exact sequence:

1. acquire an advisory lock `novel_creator_writer_core_reset`;
2. assert the target DB name equals `--confirm-reset`;
3. load exactly one project with the requested title;
4. load exactly the requested three seed titles and reject missing/duplicate titles;
5. load global Provider rows into process memory without logging secrets;
6. drop and recreate the named database with utf8mb4;
7. run the same immutable schema manifest;
8. insert the preserved project, three seeds and Provider rows;
9. insert the unique `project_selected_seeds` row for the `典镇山河` seed;
10. create bootstrap Canon revision/head 0 and empty deterministic projections;
11. bind every Task 8 task key to the enabled preferred Provider, or leave bindings empty if no enabled Provider exists;
12. verify all derived table counts are zero and release the lock.

This is a reset, not migration: it never reads or maps old chapters, versions, Canon facts, settings, memory, arcs, volumes, blocks, audits or QA data.

- [ ] **Step 5: Test reset only against disposable databases**

Seed a disposable database with the project, three seeds, one Provider containing a sentinel key, and fake rows in every old derived table. Run the reset command's internal function with `allow_product_database=False`. Assert project/seeds/provider survive, every V1 derived table is empty/head 0, task items bind to the preferred Provider, stdout/stderr do not contain the sentinel key, and the guarded test path rejects `novel_creator`. Only the CLI path with matching `--database`, `--confirm-reset` and `--execute` can set `allow_product_database=True`.

- [ ] **Step 6: Run integration tests**

Run only after setting the four explicit test-server variables:

```powershell
$env:TEST_MYSQL_HOST='127.0.0.1'
$env:TEST_MYSQL_PORT='3306'
$env:TEST_MYSQL_USER='root'
$env:TEST_MYSQL_PASSWORD='<local-test-password>'
npm run test:integration
```

Expected: PASS; every created DB name has the guarded prefix and is absent after the run.

- [ ] **Step 7: Commit**

```powershell
git add backend/tests/support backend/tests/integration backend/scripts/reset_writer_core_data.py
git commit -m "test: prove writer core transactions on disposable mysql"
```

## Task 10: Replace the project page with the real M1 product slice

**Files:**

- Create: `frontend/src/views/WriterUnavailableView.vue`
- Create: `frontend/src/components/project/WriterCoreStateCard.vue`
- Create: `frontend/tests/unit/writerCoreApi.test.mjs`
- Create: `frontend/tests/unit/providerRedaction.test.mjs`
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/views/ProjectView.vue`
- Modify: `frontend/src/stores/providerStore.js`
- Modify: `frontend/src/components/settings/ProviderForm.vue`

- [ ] **Step 1: Write API client tests**

```js
// frontend/tests/unit/writerCoreApi.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'

test('writerCore state uses the product API and performs no write', async () => {
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url, options })
    return new Response(JSON.stringify({
      projectId: 'p1', schemaVersion: 'writer-core-v1.0.0',
      canonHeadRevision: 0, projectionHeadRevision: 0, projectionInSync: true,
    }), { status: 200, headers: { 'content-type': 'application/json' } })
  }
  const { api } = await import('../../src/api/db/client.js')
  await api.writerCore.state('p1')
  assert.equal(calls.length, 1)
  assert.match(calls[0].url, /\/api\/projects\/p1\/writer-core\/state$/)
  assert.equal(calls[0].options.method, 'GET')
})
```

`providerRedaction.test.mjs` feeds a Provider API response containing only `hasKey/hasBaseURL` and asserts `providerStore` never invents `apiKey/baseURL`. It also scans the active API client source and asserts `includeApiKeys`, `/export/full`, `/canon-facts`, `/settings/change-events` and `/versions/` are absent.

- [ ] **Step 2: Verify tests fail against the old client**

Run: `npm --prefix frontend run test:unit`

Expected: FAIL because `api.writerCore` is absent and legacy endpoints remain.

- [ ] **Step 3: Reduce the active client to M1 APIs**

Keep health, projects, seeds, providers, bindings and AI Proxy helpers used by the retained Settings page. Add:

```js
writerCore: {
  state: projectId => get(`/projects/${projectId}/writer-core/state`),
},
canon: {
  head: projectId => get(`/projects/${projectId}/canon/head`),
  entities: (projectId, params = {}) => get(`/projects/${projectId}/canon/entities${queryString(params)}`),
  entity: (projectId, entityId) => get(`/projects/${projectId}/canon/entities/${entityId}`),
  resolveAlias: (projectId, name) => get(`/projects/${projectId}/canon/aliases/resolve?name=${encodeURIComponent(name)}`),
},
projections: {
  head: projectId => get(`/projects/${projectId}/projections/head`),
}
```

Do not expose event creation, projection rebuild, old Canon fact CRUD, export/import, settings, chapters, versions, temp drafts, beat plans, story blocks or correction APIs.

- [ ] **Step 4: Make Provider editing secret-safe**

The form displays “密钥已配置” from `hasKey`; it never receives or renders the stored key. Leaving the key field empty keeps the current key. Provide an explicit confirmation checkbox/button that sends `{clearApiKey:true}`. Apply the same pattern to base URL. Remove every “include API keys in export” control.

- [ ] **Step 5: Replace ProjectView with the M1 product page**

On mount, call exactly `projectStore.openProject(id)`, `seedStore.loadSeeds(id)` and `api.writerCore.state(id)`. Render:

- project title/genre/description;
- three seed cards, with `典镇山河` visibly selected;
- `WriterCoreStateCard` with Schema version, Canon head, Projection head and sync status;
- an explanation that derived writing data was reset by design;
- a disabled “进入写作台” action until the chapter-session milestone.

Do not import old writer, novel, setting, volume, story-block or correction stores. Direct navigation to `/writer/:projectId` renders `WriterUnavailableView` and provides one link back to the project page; it never mounts old `WriterView.vue`.

- [ ] **Step 6: Run frontend tests and production build**

Run:

```powershell
npm --prefix frontend run test:unit
npm --prefix frontend run build
```

Expected: PASS; build has no missing active API imports. Search confirms `ProjectView.vue` has no old store imports.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src frontend/tests/unit frontend/package.json frontend/package-lock.json
git commit -m "feat: expose writer core foundation in the product ui"
```

## Task 11: Add a small real-browser M1 test and exploratory gate

**Files:**

- Create: `backend/scripts/prepare_milestone1_browser_db.py`
- Create: `frontend/e2e/run-milestone1.mjs`
- Create: `frontend/e2e/milestone1.spec.ts`
- Create: `frontend/playwright.config.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

- [ ] **Step 1: Install the official browser dependency**

Run:

```powershell
npm --prefix frontend install --save-dev @playwright/test
npm --prefix frontend exec playwright install chromium
```

Expected: Playwright is recorded in `frontend/package.json`; no dependency is imported from `tmp/playwright-run`.

- [ ] **Step 2: Create a guarded browser DB runner**

`frontend/e2e/run-milestone1.mjs` must generate `novel_creator_test_<32 hex>`, call `python -m backend.scripts.prepare_milestone1_browser_db --database <name>`, spawn `playwright test e2e/milestone1.spec.ts` with backend `MYSQL_DB` set to that name, and call the guarded drop command in `finally`. It requires the same explicit `TEST_MYSQL_*` server variables and maps them to backend `MYSQL_*` only for the child process.

The preparation script runs the official schema initializer and inserts only:

- one project `永乐大典` with deterministic test ID `project-1`;
- seeds `永乐长明`, `文渊山海`, `典镇山河` with the latter selected;
- one enabled Provider with sentinel secret `browser-secret-must-not-leak` and private base URL;
- revision/head 0 and empty projections.

It never calls a Provider.

- [ ] **Step 3: Configure real web servers on loopback**

```ts
// frontend/playwright.config.ts
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: 'python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000',
      cwd: '..', url: 'http://127.0.0.1:8000/api/health', reuseExistingServer: false,
    },
    {
      command: 'npm --prefix frontend run dev -- --port 5173',
      cwd: '..', url: 'http://127.0.0.1:5173', reuseExistingServer: false,
    },
  ],
})
```

Set frontend `test:e2e` to `node e2e/run-milestone1.mjs`.

- [ ] **Step 4: Test one user goal from the actual page**

```ts
// frontend/e2e/milestone1.spec.ts
import { test, expect } from '@playwright/test'

test('author opens the preserved project and sees a clean synced foundation', async ({ page }) => {
  const leaks: string[] = []
  page.on('response', async response => {
    if (!response.url().includes('/api/')) return
    const body = await response.text().catch(() => '')
    if (/browser-secret-must-not-leak|private-provider\.example|api[_-]?key/i.test(body)) leaks.push(body)
  })
  const consoleErrors: string[] = []
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  await page.goto('/')
  await page.getByText('永乐大典', { exact: true }).click()
  await expect(page.getByText('永乐长明', { exact: true })).toBeVisible()
  await expect(page.getByText('文渊山海', { exact: true })).toBeVisible()
  await expect(page.getByText('典镇山河', { exact: true })).toBeVisible()
  await expect(page.getByText('已选定')).toBeVisible()
  await expect(page.getByText('writer-core-v1.0.0')).toBeVisible()
  await expect(page.getByText('Canon 0')).toBeVisible()
  await expect(page.getByText('Projection 0')).toBeVisible()
  await expect(page.getByText('状态同步')).toBeVisible()
  await expect(page.getByRole('button', { name: '进入写作台' })).toBeDisabled()
  expect(leaks).toEqual([])
  expect(consoleErrors).toEqual([])
})
```

Add this second small test; neither browser test may use direct API writes:

```ts
test('old writer URL cannot mount the retired writer chain', async ({ page }) => {
  await page.goto('/writer/project-1/1')
  await expect(page.getByRole('heading', { name: '写作内核尚未开放' })).toBeVisible()
  await expect(page.getByText('旧章节、临时草稿和版本定稿链已停用')).toBeVisible()
  await page.getByRole('link', { name: '返回项目' }).click()
  await expect(page).toHaveURL(/\/project\/project-1$/)
  await expect(page.getByText('永乐大典', { exact: true })).toBeVisible()
})
```

- [ ] **Step 5: Run fixed browser evidence**

Run with explicit disposable server variables: `npm run test:browser`

Expected: both tests PASS; the disposable database is dropped in `finally`.

- [ ] **Step 6: Product controller performs unscripted exploration**

Using headed Chromium, the product controller must manually vary this sequence: refresh during project load, back/forward twice, open settings then return, attempt direct old Writer URL, double-click project card, and temporarily run against a mismatched schema version. Capture screenshot, trace/network evidence and the associated commit hash. API/DB may be read for diagnosis but no direct write can substitute a page step.

Expected: no secret/old test name leaks, no silent fallback, and mismatched schema prevents backend service rather than repairing it.

- [ ] **Step 7: Commit**

```powershell
git add backend/scripts/prepare_milestone1_browser_db.py frontend/e2e frontend/playwright.config.ts frontend/package.json frontend/package-lock.json
git commit -m "test: verify milestone one through the real browser"
```

## Task 12: Reset the authorized local product DB and close M1

**Files:**

- Create: `docs/development/writer-core-m1-evidence.md`
- Modify: `docs/superpowers/specs/2026-07-11-writer-core-v1-design.md`

- [ ] **Step 1: Run the complete no-provider gate from a clean commit**

Run:

```powershell
git status --short
npm test
npm run test:integration
npm run test:browser
npm --prefix frontend run build
```

Expected: clean status before evidence generation and every command PASS. No Provider/model call occurs.

- [ ] **Step 2: Review the destructive command before release**

Run reset in dry-run mode without `--execute`. Confirm the report identifies exactly one `永乐大典` project, exactly the three approved seeds, the intended Provider display name/model, and only derived data for deletion. Confirm stdout/stderr contain no credential or base URL.

- [ ] **Step 3: Execute the already-authorized local reset once**

Run the exact command from Task 9 with `--execute`. This is the only M1 step that touches the local product database. Do not start the backend until the command reports matching version/hash and zero derived rows.

Expected: project, three seeds and Provider configuration preserved; `典镇山河` selected; all task bindings point to the unique enabled `联通云 / deepseek-v4-flash` row; Canon/Projection heads are 0; all derived writer tables are empty.

- [ ] **Step 4: Run the product page against the reset DB without Provider calls**

Start backend and frontend bound to `127.0.0.1`, open the real page manually, and repeat the fixed M1 user goal. Read API and DB state to correlate the same project ID and heads. Stop both services after evidence capture.

- [ ] **Step 5: Write evidence with an explicit level**

`docs/development/writer-core-m1-evidence.md` records:

```text
commit / branch / worktree
schema version and manifest hash
unit, disposable MySQL, fixed browser and exploratory commands/results
product page entry and same-run project/head evidence
secret scan result
Provider calls: none
evidence level: L4 M1 No-Provider Ready
known next dependency: M2 CreationContract and assets
```

Do not attach old e.* artifacts or claim Live/Product Ready.

- [ ] **Step 6: Run specification and code review**

Use a fresh reviewer to compare the diff to Sections 2–7, 15, 17 and Milestone 1 of the approved design. A second reviewer checks code quality, transaction safety, secret handling and test-entry integrity. Fix all blocking findings and rerun affected commands.

- [ ] **Step 7: Final verification and commit**

Run:

```powershell
git diff --check
git status --short
git log --oneline 4b85e8d..HEAD
```

Expected: no whitespace errors; only intended evidence/doc changes remain.

```powershell
git add docs/development/writer-core-m1-evidence.md docs/superpowers/specs/2026-07-11-writer-core-v1-design.md
git commit -m "docs: record writer core milestone one evidence"
```

Stop after M1. Do not begin CreationContract implementation until the product controller has audited the M1 result and activated the separate M2 plan.

## Self-review checklist for the executor

- [ ] The implementation branch descends from `4b85e8d`, not platform-rc or a dirty worktree.
- [ ] Startup contains no DDL and no compatibility fallback.
- [ ] Project/seed/Provider are the only preserved old-domain data.
- [ ] Canon has one entity ID system, exact aliases and explicit ambiguity.
- [ ] Only confirmed overlapping stable mutually exclusive values hard-block.
- [ ] Memory/state/arcs/plot threads are projections of one event stream.
- [ ] Revision/events/projections/head commit on one connection and one transaction.
- [ ] Duplicate idempotency key returns the original result without writes.
- [ ] No HTTP method can arbitrarily mutate Canon or a projection.
- [ ] No response, log, error, diagnostic, export or browser payload contains Provider secrets.
- [ ] `ProjectView` does not import old writing-state stores.
- [ ] No formal test or report imports from `tmp` or uses an e.* runner.
- [ ] Fixed browser tests begin with visible page interaction and perform no direct API write.
- [ ] M1 evidence is labeled L4 No-Provider Ready at most.
