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
