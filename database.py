import aiosqlite


def connection():
    return aiosqlite.connect("./data/main.db", timeout=15.0)


async def execute(query: str, *args, **kwargs):
    async with connection() as conn:
        await conn.execute(query, *args, **kwargs)
        await conn.commit()
