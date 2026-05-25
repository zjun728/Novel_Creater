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
          content MEDIUMTEXT DEFAULT NULL,
          created_at BIGINT NOT NULL,
          updated_at BIGINT NOT NULL,
          UNIQUE KEY uniq_chapter_beat_plan (project_id, chapter_num),
          INDEX idx_chapter_beat_plans_project (project_id, chapter_num)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """,
        "ALTER TABLE project_volumes ADD COLUMN stage_summary_report JSON DEFAULT NULL AFTER summary",
        "ALTER TABLE project_volumes ADD COLUMN summary_updated_at BIGINT DEFAULT NULL AFTER stage_summary_report",
        "ALTER TABLE project_volumes ADD COLUMN audit_report JSON DEFAULT NULL AFTER summary",
        "ALTER TABLE project_volumes ADD COLUMN audit_updated_at BIGINT DEFAULT NULL AFTER audit_report",
        "ALTER TABLE creative_seeds MODIFY emotional_promise TEXT DEFAULT NULL",
        "ALTER TABLE creative_seeds MODIFY style_target TEXT DEFAULT NULL",
        "ALTER TABLE creative_seeds ADD COLUMN ending_anchor TEXT DEFAULT NULL AFTER risk_notes",
    ]
    for sql in statements:
        try:
            await execute(sql)
        except Exception as exc:
            # MySQL 5.7 does not support ADD COLUMN IF NOT EXISTS.
            # Duplicate column errors are safe during local schema upgrades.
            if "Duplicate column" not in str(exc) and "1060" not in str(exc):
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
