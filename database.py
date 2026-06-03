import asyncio
import aiosqlite
import os
from pathlib import Path
from typing import Optional
import loguru

# Configurable via env for deployments where src/ and data/ are separated (e.g. systemd)
DATA_DIR = os.environ.get("GOALKEEPR_DATA_DIR", "./data")
DB_PATH = str(Path(DATA_DIR) / "main.db")

_conn: Optional[aiosqlite.Connection] = None
_conn_use_lock = asyncio.Lock()

logger = loguru.logger

async def connection() -> aiosqlite.Connection:
    """
    复用单个连接，避免频繁创建开销。
    """
    global _conn
    if _conn is None:
        async with _conn_use_lock:
            if _conn is None:
                Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
                _conn = await aiosqlite.connect(DB_PATH, timeout=30.0)
    return _conn


async def execute(query: str, *args, **kwargs):
    """
    Execute a query and commit the changes.
    Creates a new connection for each call to avoid thread reuse issues.
    """
    conn = await connection()
    async with _conn_use_lock:
        await conn.execute(query, *args, **kwargs)
        await conn.commit()


async def execute_fetch(query: str, *args, **kwargs):
    """
    Execute a query and return the results.
    """
    conn = await connection()
    async with _conn_use_lock:
        cursor = await conn.execute(query, *args, **kwargs)
        rows = await cursor.fetchall()
        await cursor.close()
        return rows


async def close() -> None:
    """关闭数据库连接"""
    global _conn
    if _conn is not None:
        async with _conn_use_lock:
            if _conn is not None:
                await _conn.close()
                _conn = None
