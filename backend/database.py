"""
数据库连接池管理
使用 aiomysql 异步驱动
"""
import aiomysql
from config import MYSQL_CONFIG

pool = None


async def get_pool():
    global pool
    if pool is None:
        pool = await aiomysql.create_pool(**MYSQL_CONFIG)
    return pool


async def ensure_schema():
    """Create v0.6 setting-library tables when an older local DB is opened."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS setting_entities (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          entity_type VARCHAR(40) NOT NULL DEFAULT 'character',
          name VARCHAR(200) NOT NULL DEFAULT '',
          category VARCHAR(100) DEFAULT '',
          summary TEXT DEFAULT NULL,
          status VARCHAR(30) DEFAULT 'active',
          importance INT DEFAULT 3,
          aliases JSON DEFAULT NULL,
          tags JSON DEFAULT NULL,
          profile JSON DEFAULT NULL,
          first_chapter INT DEFAULT NULL,
          last_chapter INT DEFAULT NULL,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          INDEX idx_setting_entities_project (project_id),
          INDEX idx_setting_entities_type (project_id, entity_type),
          INDEX idx_setting_entities_name (project_id, name),
          INDEX idx_setting_entities_status (project_id, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS setting_relations (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          source_entity_id CHAR(36) NOT NULL,
          target_entity_id CHAR(36) NOT NULL,
          relation_type VARCHAR(80) DEFAULT '',
          stance VARCHAR(40) DEFAULT '',
          summary TEXT DEFAULT NULL,
          is_hidden TINYINT(1) DEFAULT 0,
          evidence TEXT DEFAULT NULL,
          chapter_num INT DEFAULT NULL,
          status VARCHAR(30) DEFAULT 'active',
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          INDEX idx_setting_relations_project (project_id),
          INDEX idx_setting_relations_source (project_id, source_entity_id),
          INDEX idx_setting_relations_target (project_id, target_entity_id),
          INDEX idx_setting_relations_status (project_id, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS setting_change_events (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          entity_type VARCHAR(40) DEFAULT '',
          entity_id CHAR(36) DEFAULT NULL,
          entity_name VARCHAR(200) DEFAULT '',
          change_type VARCHAR(80) DEFAULT 'update',
          field_path VARCHAR(200) DEFAULT '',
          old_value TEXT DEFAULT NULL,
          new_value TEXT DEFAULT NULL,
          chapter_num INT DEFAULT NULL,
          evidence TEXT DEFAULT NULL,
          confidence DOUBLE DEFAULT 0.8,
          status VARCHAR(30) DEFAULT 'pending_review',
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          INDEX idx_setting_changes_project (project_id),
          INDEX idx_setting_changes_entity (project_id, entity_id),
          INDEX idx_setting_changes_status (project_id, status),
          INDEX idx_setting_changes_chapter (project_id, chapter_num)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS market_chat_messages (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          role VARCHAR(20) NOT NULL DEFAULT 'user',
          content MEDIUMTEXT DEFAULT NULL,
          metadata JSON DEFAULT NULL,
          created_at BIGINT NOT NULL,
          INDEX idx_market_chat_project (project_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS market_direction_reports (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          keywords VARCHAR(200) DEFAULT '',
          content_json JSON DEFAULT NULL,
          created_at BIGINT NOT NULL,
          INDEX idx_market_direction_project (project_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS rolling_outlines (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          far_vision JSON DEFAULT NULL,
          current_volume JSON DEFAULT NULL,
          near_chapters JSON DEFAULT NULL,
          updated_at BIGINT NOT NULL,
          UNIQUE INDEX idx_outline_project (project_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS project_volumes (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          volume_num INT NOT NULL DEFAULT 1,
          title VARCHAR(200) DEFAULT '',
          start_chapter INT NOT NULL DEFAULT 1,
          end_chapter INT NOT NULL DEFAULT 1,
          target_words INT DEFAULT 0,
          core_goal TEXT DEFAULT NULL,
          main_conflict TEXT DEFAULT NULL,
          key_characters JSON DEFAULT NULL,
          summary TEXT DEFAULT NULL,
          foreshadowing_plan JSON DEFAULT NULL,
          unresolved_items JSON DEFAULT NULL,
          handoff_point TEXT DEFAULT NULL,
          stage_summary_report JSON DEFAULT NULL,
          summary_updated_at BIGINT DEFAULT NULL,
          audit_report JSON DEFAULT NULL,
          audit_updated_at BIGINT DEFAULT NULL,
          status VARCHAR(30) DEFAULT 'planned',
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          INDEX idx_project_volumes_project (project_id),
          INDEX idx_project_volumes_num (project_id, volume_num),
          INDEX idx_project_volumes_range (project_id, start_chapter, end_chapter),
          INDEX idx_project_volumes_status (project_id, status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS project_audit_reports (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          report_type VARCHAR(40) NOT NULL DEFAULT 'global',
          title VARCHAR(200) DEFAULT '',
          report_json JSON DEFAULT NULL,
          created_at BIGINT NOT NULL,
          INDEX idx_project_audits_project (project_id, created_at),
          INDEX idx_project_audits_type (project_id, report_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS correction_tasks (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          source_type VARCHAR(40) NOT NULL DEFAULT 'global_audit',
          source_id CHAR(36) DEFAULT NULL,
          target_module VARCHAR(40) DEFAULT 'general',
          title VARCHAR(300) NOT NULL DEFAULT '',
          description TEXT DEFAULT NULL,
          severity VARCHAR(30) DEFAULT 'minor',
          issue_type VARCHAR(50) DEFAULT 'general',
          chapter_refs JSON DEFAULT NULL,
          related_items JSON DEFAULT NULL,
          suggested_action TEXT DEFAULT NULL,
          status VARCHAR(30) DEFAULT 'pending',
          metadata JSON DEFAULT NULL,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          INDEX idx_correction_tasks_project (project_id, status),
          INDEX idx_correction_tasks_source (project_id, source_type, source_id),
          INDEX idx_correction_tasks_module (project_id, target_module)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS chapter_beat_plans (
          id VARCHAR(80) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          chapter_num INT NOT NULL,
          story_block_id CHAR(36) DEFAULT NULL,
          block_stage_id VARCHAR(80) DEFAULT NULL,
          block_stage_snapshot JSON DEFAULT NULL,
          beat_plan_source VARCHAR(64) DEFAULT NULL,
          derived_from_story_block TINYINT(1) DEFAULT 0,
          derived_reason TEXT DEFAULT NULL,
          content MEDIUMTEXT DEFAULT NULL,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          UNIQUE KEY uniq_chapter_beat_plan (project_id, chapter_num),
          INDEX idx_chapter_beat_plans_project (project_id, chapter_num),
          INDEX idx_chapter_beat_plans_story_block (project_id, story_block_id),
          INDEX idx_chapter_beat_plans_stage (project_id, story_block_id, block_stage_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS story_blocks (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          volume_id CHAR(36) DEFAULT NULL,
          block_num INT NOT NULL DEFAULT 1,
          status VARCHAR(30) DEFAULT 'active',
          title VARCHAR(200) DEFAULT '',
          goal TEXT DEFAULT NULL,
          story_function VARCHAR(120) DEFAULT '',
          entry_state TEXT DEFAULT NULL,
          exit_target TEXT DEFAULT NULL,
          main_pressure TEXT DEFAULT NULL,
          key_characters JSON DEFAULT NULL,
          stage_plan JSON DEFAULT NULL,
          completed_stages JSON DEFAULT NULL,
          next_stage_suggestion TEXT DEFAULT NULL,
          unresolved_questions JSON DEFAULT NULL,
          dont_advance_yet JSON DEFAULT NULL,
          carry_over_to_next_chapter JSON DEFAULT NULL,
          capacity_assessment VARCHAR(40) DEFAULT 'normal',
          chapter_refs JSON DEFAULT NULL,
          lock_state JSON DEFAULT NULL,
          review_history JSON DEFAULT NULL,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          CHECK (status IN ('active','completed','paused','closed')),
          INDEX idx_story_blocks_project (project_id, block_num),
          INDEX idx_story_blocks_status (project_id, status),
          INDEX idx_story_blocks_volume (project_id, volume_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS story_block_reviews (
          id CHAR(36) PRIMARY KEY,
          project_id CHAR(36) NOT NULL,
          story_block_id CHAR(36) NOT NULL,
          chapter_num INT DEFAULT NULL,
          decision VARCHAR(60) NOT NULL DEFAULT 'continue_current_block',
          review_json JSON DEFAULT NULL,
          created_at BIGINT NOT NULL,
          CHECK (decision IN ('continue_current_block','adjust_remaining_stages','split_unfinalized_content','complete_current_block','open_new_block')),
          INDEX idx_story_block_reviews_project (project_id, story_block_id, created_at),
          INDEX idx_story_block_reviews_decision (project_id, decision)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS sample_source (
          id CHAR(36) PRIMARY KEY,
          source_type VARCHAR(40) NOT NULL DEFAULT 'local_report',
          title VARCHAR(300) NOT NULL DEFAULT '',
          author VARCHAR(120) DEFAULT '',
          file_name VARCHAR(300) DEFAULT '',
          file_hash VARCHAR(120) DEFAULT '',
          source_note TEXT DEFAULT NULL,
          status VARCHAR(30) DEFAULT 'imported',
          imported_at BIGINT DEFAULT NULL,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          INDEX idx_sample_source_type (source_type),
          INDEX idx_sample_source_status (status),
          INDEX idx_sample_source_title (title)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS sample_chunk (
          id CHAR(36) PRIMARY KEY,
          source_id CHAR(36) NOT NULL,
          chunk_order INT NOT NULL DEFAULT 0,
          chapter_label VARCHAR(200) DEFAULT '',
          window_role VARCHAR(80) DEFAULT 'report_card',
          abstract_notes_json JSON DEFAULT NULL,
          metrics_json JSON DEFAULT NULL,
          raw_hash VARCHAR(120) DEFAULT '',
          status VARCHAR(30) DEFAULT 'imported',
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          INDEX idx_sample_chunk_source (source_id, chunk_order),
          INDEX idx_sample_chunk_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS experience_card (
          id CHAR(36) PRIMARY KEY,
          source_id CHAR(36) DEFAULT NULL,
          source_card_ref VARCHAR(200) DEFAULT '',
          source_title VARCHAR(300) DEFAULT '',
          title VARCHAR(300) NOT NULL DEFAULT '',
          status VARCHAR(30) NOT NULL DEFAULT 'candidate',
          card_type VARCHAR(60) DEFAULT 'imported_sample',
          chapter_skeleton TEXT DEFAULT NULL,
          story_block_span TEXT DEFAULT NULL,
          protagonist_progression TEXT DEFAULT NULL,
          supporting_character_method TEXT DEFAULT NULL,
          emotional_dwell TEXT DEFAULT NULL,
          scene_dwell TEXT DEFAULT NULL,
          dialogue_naturalness TEXT DEFAULT NULL,
          setting_exposure TEXT DEFAULT NULL,
          answers_and_suspense TEXT DEFAULT NULL,
          anti_ai_notes TEXT DEFAULT NULL,
          genre_tags JSON DEFAULT NULL,
          avoid_patterns JSON DEFAULT NULL,
          chunk_ids JSON DEFAULT NULL,
          metrics_json JSON DEFAULT NULL,
          safety_flags JSON DEFAULT NULL,
          review_note TEXT DEFAULT NULL,
          reviewed_at BIGINT DEFAULT NULL,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          CHECK (status IN ('candidate','reviewed','rejected','merged','archived')),
          INDEX idx_experience_card_status (status),
          INDEX idx_experience_card_source (source_id),
          INDEX idx_experience_card_title (title)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS writing_standard_candidate (
          id CHAR(36) PRIMARY KEY,
          name VARCHAR(200) NOT NULL DEFAULT '',
          category VARCHAR(120) DEFAULT '样本库 / 人工审核',
          status VARCHAR(30) NOT NULL DEFAULT 'draft',
          source_card_ids JSON DEFAULT NULL,
          merged_guidance JSON DEFAULT NULL,
          audit_focus JSON DEFAULT NULL,
          safety_policy JSON DEFAULT NULL,
          review_note TEXT DEFAULT NULL,
          promoted_standard_id CHAR(36) DEFAULT NULL,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          CHECK (status IN ('draft','reviewing','approved','rejected','promoted')),
          INDEX idx_standard_candidate_status (status),
          INDEX idx_standard_candidate_promoted (promoted_standard_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        """
        CREATE TABLE IF NOT EXISTS writing_standard (
          id CHAR(36) PRIMARY KEY,
          name VARCHAR(200) NOT NULL DEFAULT '',
          category VARCHAR(120) DEFAULT '样本库 / 人工审核',
          version VARCHAR(40) DEFAULT 'v1',
          short_rule TEXT DEFAULT NULL,
          guidance_json JSON DEFAULT NULL,
          audit_focus JSON DEFAULT NULL,
          source_candidate_id CHAR(36) DEFAULT NULL,
          source_type VARCHAR(40) DEFAULT 'experience_card',
          status VARCHAR(30) DEFAULT 'active',
          no_direct_imitation TINYINT(1) DEFAULT 1,
          safety_flags JSON DEFAULT NULL,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          INDEX idx_writing_standard_status (status),
          INDEX idx_writing_standard_source_candidate (source_candidate_id),
          INDEX idx_writing_standard_name (name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        "ALTER TABLE chapters ADD COLUMN story_block_id CHAR(36) DEFAULT NULL AFTER title",
        "ALTER TABLE chapters ADD INDEX idx_chapters_story_block (project_id, story_block_id)",
        "ALTER TABLE chapter_beat_plans ADD COLUMN story_block_id CHAR(36) DEFAULT NULL AFTER chapter_num",
        "ALTER TABLE chapter_beat_plans ADD COLUMN block_stage_id VARCHAR(80) DEFAULT NULL AFTER story_block_id",
        "ALTER TABLE chapter_beat_plans ADD COLUMN block_stage_snapshot JSON DEFAULT NULL AFTER block_stage_id",
        "ALTER TABLE chapter_beat_plans ADD COLUMN beat_plan_source VARCHAR(64) DEFAULT NULL AFTER block_stage_snapshot",
        "ALTER TABLE chapter_beat_plans ADD COLUMN derived_from_story_block TINYINT(1) DEFAULT 0 AFTER beat_plan_source",
        "ALTER TABLE chapter_beat_plans ADD COLUMN derived_reason TEXT DEFAULT NULL AFTER derived_from_story_block",
        "ALTER TABLE story_blocks ADD COLUMN carry_over_to_next_chapter JSON DEFAULT NULL AFTER dont_advance_yet",
        "ALTER TABLE chapter_beat_plans ADD INDEX idx_chapter_beat_plans_story_block (project_id, story_block_id)",
        "ALTER TABLE chapter_beat_plans ADD INDEX idx_chapter_beat_plans_stage (project_id, story_block_id, block_stage_id)",
        "ALTER TABLE project_volumes ADD COLUMN stage_summary_report JSON DEFAULT NULL AFTER summary",
        "ALTER TABLE project_volumes ADD COLUMN foreshadowing_plan JSON DEFAULT NULL AFTER summary",
        "ALTER TABLE project_volumes ADD COLUMN unresolved_items JSON DEFAULT NULL AFTER foreshadowing_plan",
        "ALTER TABLE project_volumes ADD COLUMN handoff_point TEXT DEFAULT NULL AFTER unresolved_items",
        "ALTER TABLE project_volumes ADD COLUMN summary_updated_at BIGINT DEFAULT NULL AFTER stage_summary_report",
        "ALTER TABLE project_volumes ADD COLUMN audit_report JSON DEFAULT NULL AFTER summary",
        "ALTER TABLE project_volumes ADD COLUMN audit_updated_at BIGINT DEFAULT NULL AFTER audit_report",
        "ALTER TABLE creative_seeds MODIFY emotional_promise TEXT DEFAULT NULL",
        "ALTER TABLE creative_seeds MODIFY style_target TEXT DEFAULT NULL",
        "ALTER TABLE creative_seeds ADD COLUMN ending_anchor TEXT DEFAULT NULL AFTER risk_notes",
        "ALTER TABLE creative_bible ADD COLUMN writing_profile JSON DEFAULT NULL AFTER world_rules",
        "ALTER TABLE task_model_bindings ADD COLUMN inherited_from_project_id CHAR(36) DEFAULT NULL AFTER polish_model_id",
        "ALTER TABLE task_model_bindings ADD COLUMN inherited_from_project_title VARCHAR(200) DEFAULT '' AFTER inherited_from_project_id",
        "ALTER TABLE task_model_bindings ADD COLUMN inherited_from_updated_at BIGINT DEFAULT NULL AFTER inherited_from_project_title",
        "ALTER TABLE task_model_bindings ADD INDEX idx_bindings_updated (updated_at)",
    ]
    for sql in statements:
        try:
            await execute(sql)
        except Exception as exc:
            # MySQL 5.7 does not support ADD COLUMN IF NOT EXISTS.
            # Duplicate column errors are safe during local schema upgrades.
            duplicate_schema_change = (
                "Duplicate column" in str(exc)
                or "Duplicate key name" in str(exc)
                or "1060" in str(exc)
                or "1061" in str(exc)
            )
            if not duplicate_schema_change:
                raise


async def close_pool():
    global pool
    if pool:
        pool.close()
        await pool.wait_closed()
        pool = None


async def get_connection():
    p = await get_pool()
    return await p.acquire()


async def release_connection(conn):
    p = await get_pool()
    p.release(conn)


async def execute(sql, args=None):
    """执行写操作，返回 lastrowid"""
    conn = await get_connection()
    try:
        async with conn.cursor() as cur:
            await cur.execute(sql, args)
            return cur.lastrowid
    finally:
        await release_connection(conn)


async def fetchone(sql, args=None):
    """查询单行"""
    conn = await get_connection()
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, args)
            return await cur.fetchone()
    finally:
        await release_connection(conn)


async def fetchall(sql, args=None):
    """查询多行"""
    conn = await get_connection()
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, args)
            return await cur.fetchall()
    finally:
        await release_connection(conn)
