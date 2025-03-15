import aiosqlite

global_conn = None


def connection():
    global global_conn
    
    if global_conn is None:
        global_conn = aiosqlite.connect("./data/main.db")

    return global_conn


async def execute(query: str, *args, **kwargs):
    async with connection() as conn:
        await conn.execute(query, *args, **kwargs)
        await conn.commit()
