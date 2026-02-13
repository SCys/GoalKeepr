import asyncio
import aiosqlite
import os
from typing import Optional

# Ensure data directory exists
os.makedirs("./data", exist_ok=True)

_conn: Optional[aiosqlite.Connection] = None
_conn_lock = asyncio.Lock()
_conn_use_lock = asyncio.Lock()

async def connection() -> aiosqlite.Connection:
    """
    复用单个连接，避免频繁创建开销。
    """
    global _conn
    if _conn is None:
        async with _conn_lock:
            if _conn is None:
                _conn = await aiosqlite.connect("./data/main.db", timeout=30.0)
    return _conn


async def execute(query: str, *args, **kwargs):
    """
    Execute a query and commit the changes.
    Creates a new connection for each call to avoid thread reuse issues.
    """
    async with _conn_use_lock:
        conn = await connection()
        await conn.execute(query, *args, **kwargs)
        await conn.commit()


async def execute_fetch(query: str, *args, **kwargs):
    """
    Execute a query and return the results.
    Creates a new connection for each call to avoid thread reuse issues.
    """
    async with _conn_use_lock:
        conn = await connection()
        cursor = await conn.execute(query, *args, **kwargs)
        rows = await cursor.fetchall()
        await cursor.close()
        return rows


async def close() -> None:
    """关闭数据库连接"""
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None
