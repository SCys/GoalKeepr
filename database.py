import aiosqlite


async def connection():
    # Create a new connection each time, avoiding thread reuse issues
    return await aiosqlite.connect("./data/main.db", timeout=30.0)


async def execute(query: str, *args, timeout=30.0, **kwargs):
    async with await connection() as conn:
        await conn.execute(query, *args, **kwargs)
        await conn.commit()
