import aiosqlite

global_conn = None


async def connection():
    global global_conn
    
    if global_conn is None:
        global_conn = await aiosqlite.connect("./data/main.db", timeout=30.0)

    return global_conn


async def execute(query: str, *args, timeout=30.0, **kwargs):
    conn = await connection()
    await conn.execute(query, *args, **kwargs)
    await conn.commit()
