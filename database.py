import aiosqlite


def connection():
    return aiosqlite.connect("./data/main.db")


async def execute(query: str, *args, **kwargs):
    async with connection() as conn:
        await conn.execute(query, *args, **kwargs)
        await conn.commit()
