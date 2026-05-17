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
    ]
    for sql in statements:
        await execute(sql)


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
