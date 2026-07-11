"""Immutable Writer Core reset fixture from ``4b85e8d:backend/schema.sql``."""

from __future__ import annotations

import json


LEGACY_BASELINE_COMMIT = "4b85e8d"
PROJECT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_PROJECT_ID = "99999999-9999-9999-9999-999999999999"
PROVIDER_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
OTHER_PROVIDER_ID = "88888888-8888-8888-8888-888888888888"
SEEDS = (
    ("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "永乐长明", "candidate"),
    ("cccccccc-cccc-cccc-cccc-cccccccccccc", "文渊山海", "candidate"),
    ("dddddddd-dddd-dddd-dddd-dddddddddddd", "典镇山河", "selected"),
)
SENTINELS = (
    "API_KEY_SENTINEL",
    "BASE_URL_SENTINEL",
    "DESCRIPTION_CHAPTER_SENTINEL",
    "PROVIDER_NOTES_SENTINEL",
    "PASSWORD_SENTINEL",
    "DSN_SENTINEL",
)

PROJECTS_DDL = """CREATE TABLE projects (
  id CHAR(36) PRIMARY KEY,
  title VARCHAR(200) NOT NULL DEFAULT '',
  genre VARCHAR(100) DEFAULT '',
  description TEXT DEFAULT NULL,
  target_words INT DEFAULT 100000,
  target_chapters INT DEFAULT 100,
  current_chapter_num INT DEFAULT 0,
  status VARCHAR(20) DEFAULT 'drafting',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_projects_status (status),
  INDEX idx_projects_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

PROVIDERS_DDL = """CREATE TABLE provider_profiles (
  id CHAR(36) PRIMARY KEY,
  name VARCHAR(200) NOT NULL DEFAULT '',
  provider_type VARCHAR(50) NOT NULL DEFAULT 'openai-compatible',
  base_url VARCHAR(500) DEFAULT '',
  api_key VARCHAR(500) DEFAULT '',
  model VARCHAR(200) DEFAULT '',
  stream TINYINT(1) DEFAULT 1,
  max_context_tokens INT DEFAULT 200000,
  max_output_tokens INT DEFAULT 4096,
  temperature DOUBLE DEFAULT 0.8,
  top_p DOUBLE DEFAULT 0.9,
  supports_json TINYINT(1) DEFAULT 1,
  supports_streaming TINYINT(1) DEFAULT 1,
  notes TEXT DEFAULT NULL,
  thinking JSON DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_providers_type (provider_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

SEEDS_DDL = """CREATE TABLE creative_seeds (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  title VARCHAR(200) DEFAULT '',
  genre VARCHAR(100) DEFAULT '',
  logline TEXT DEFAULT NULL,
  protagonist TEXT DEFAULT NULL,
  desire TEXT DEFAULT NULL,
  core_conflict TEXT DEFAULT NULL,
  world_pressure TEXT DEFAULT NULL,
  opening_hook TEXT DEFAULT NULL,
  emotional_promise TEXT DEFAULT NULL,
  differentiation TEXT DEFAULT NULL,
  style_target TEXT DEFAULT NULL,
  source VARCHAR(20) DEFAULT 'user',
  risk_notes TEXT DEFAULT NULL,
  ending_anchor TEXT DEFAULT NULL,
  status VARCHAR(20) DEFAULT 'candidate',
  created_at BIGINT NOT NULL,
  INDEX idx_seeds_project (project_id),
  INDEX idx_seeds_status (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

TASK_BINDINGS_DDL = """CREATE TABLE task_model_bindings (
  id CHAR(36) PRIMARY KEY,
  project_id CHAR(36) NOT NULL,
  writing_model_id CHAR(36) DEFAULT NULL,
  brainstorm_model_id CHAR(36) DEFAULT NULL,
  outline_model_id CHAR(36) DEFAULT NULL,
  audit_model_id CHAR(36) DEFAULT NULL,
  summary_model_id CHAR(36) DEFAULT NULL,
  extraction_model_id CHAR(36) DEFAULT NULL,
  market_model_id CHAR(36) DEFAULT NULL,
  polish_model_id CHAR(36) DEFAULT NULL,
  inherited_from_project_id CHAR(36) DEFAULT NULL,
  inherited_from_project_title VARCHAR(200) DEFAULT '',
  inherited_from_updated_at BIGINT DEFAULT NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX idx_bindings_project (project_id),
  INDEX idx_bindings_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""

LEGACY_DERIVED_TABLES = (
    "task_model_bindings", "chapters", "chapter_versions",
    "possibility_cards", "creative_bible", "sample_source", "sample_chunk",
    "experience_card", "writing_standard_candidate", "writing_standard",
    "characters", "plot_threads", "rolling_outlines", "project_volumes",
    "project_audit_reports", "correction_tasks", "canon_facts", "temp_drafts",
    "chapter_beat_plans", "story_blocks", "story_block_reviews", "market_items",
    "market_chat_messages", "market_direction_reports", "setting_entities",
    "setting_relations", "setting_change_events", "finalization_markers",
    "project_health_checks",
)


def _seed_values(seed_id: str, title: str, status: str):
    return (
        seed_id, PROJECT_ID, title, "历史", f"{title}的故事线",
        f"{title}主人公", "守护典籍", "朝局冲突", "天下大势", "开篇危机",
        "守护文明", "独特史观", "克制厚重", "user", "节奏风险", "完成大典",
        status, 100,
    )


async def create_legacy_writer_core(session) -> None:
    """Create the one accepted legacy preserve contract and representative rows."""
    await session.execute(PROJECTS_DDL)
    await session.execute(PROVIDERS_DDL)
    await session.execute(SEEDS_DDL)
    for table in LEGACY_DERIVED_TABLES:
        if table == "task_model_bindings":
            await session.execute(TASK_BINDINGS_DDL)
            await session.execute(
                "INSERT INTO task_model_bindings VALUES ("
                + ",".join(("%s",) * 15)
                + ")",
                (
                    "66666666-6666-6666-6666-666666666666", PROJECT_ID,
                    OTHER_PROVIDER_ID, OTHER_PROVIDER_ID, OTHER_PROVIDER_ID,
                    OTHER_PROVIDER_ID, OTHER_PROVIDER_ID, OTHER_PROVIDER_ID,
                    OTHER_PROVIDER_ID, OTHER_PROVIDER_ID, OTHER_PROJECT_ID,
                    "conflicting legacy binding", 999, 100, 200,
                ),
            )
            continue
        await session.execute(
            f"CREATE TABLE `{table}` (id INT PRIMARY KEY, payload LONGTEXT) ENGINE=InnoDB"
        )
        await session.execute(
            f"INSERT INTO `{table}` (id, payload) VALUES (1, %s)",
            (f"{table}-{SENTINELS[2]}-{SENTINELS[4]}-{SENTINELS[5]}",),
        )

    await session.execute(
        "INSERT INTO projects VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            PROJECT_ID, "永乐大典", "历史", SENTINELS[2], 1_000_000, 500,
            17, "active", 100, 200,
        ),
    )
    await session.execute(
        "INSERT INTO projects VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            OTHER_PROJECT_ID, "无关项目", "其他", "must be removed", 10_000, 10,
            0, "drafting", 50, 60,
        ),
    )
    for seed in SEEDS:
        await session.execute(
            "INSERT INTO creative_seeds VALUES ("
            + ",".join(("%s",) * 18)
            + ")",
            _seed_values(*seed),
        )
    await session.execute(
        "INSERT INTO creative_seeds VALUES (" + ",".join(("%s",) * 18) + ")",
        (
            "77777777-7777-7777-7777-777777777777", OTHER_PROJECT_ID,
            "无关种子", "其他", "无关", "无关", "无关", "无关", "无关", "无关",
            "无关", "无关", "无关", "user", None, None, "candidate", 50,
        ),
    )
    await session.execute(
        "INSERT INTO provider_profiles VALUES ("
        + ",".join(("%s",) * 17)
        + ")",
        (
            PROVIDER_ID, "联通云", "openai-compatible", SENTINELS[1], SENTINELS[0],
            "deepseek-v4-flash", 1, 128000, 8192, 0.7, 0.95, 1, 1,
            SENTINELS[3], None, 100, 200,
        ),
    )
    await session.execute(
        "INSERT INTO provider_profiles VALUES ("
        + ",".join(("%s",) * 17)
        + ")",
        (
            OTHER_PROVIDER_ID, "备用云", "openai-compatible",
            "https://DSN_SENTINEL.invalid", "PASSWORD_SENTINEL", "backup-model",
            0, 64000, 4096, 0.5, 0.9, 0, 0,
            "PROVIDER_NOTES_SENTINEL-2", json.dumps({"budget": 3}), 90, 190,
        ),
    )
