import aiosqlite
import os

# Ensure data directory exists
os.makedirs("./data", exist_ok=True)

async def connection():
    """
    Create a new connection each time, explicitly returning the raw connection.
    This avoids any thread reuse issues with aiosqlite.
    """
    conn = await aiosqlite.connect("./data/main.db", timeout=30.0)
    return conn


async def execute(query: str, *args, **kwargs):
    """
    Execute a query and commit the changes.
    Creates a new connection for each call to avoid thread reuse issues.
    """
    conn = await connection()
    try:
        await conn.execute(query, *args, **kwargs)
        await conn.commit()
    finally:
        await conn.close()


async def execute_fetch(query: str, *args, **kwargs):
    """
    Execute a query and return the results.
    Creates a new connection for each call to avoid thread reuse issues.
    """
    conn = await connection()
    try:
        cursor = await conn.execute(query, *args, **kwargs)
        rows = await cursor.fetchall()
        await cursor.close()
        return rows
    finally:
        await conn.close()
