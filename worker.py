import asyncio

from aiogram.bot.bot import Bot

import database
from handlers.new_members import new_member_check  # NOQA: 引入处理器
from manager import manager

is_running = False


SQL_CREATE_MESSAGES = """
create table if not exists lazy_delete_messages(
    id integer primary key autoincrement,
    chat int,
    msg int,
    deleted_at timestamp with time zone
)
"""

SQL_CREATE_NEW_MEMBER_SESSION = """
create table if not exists lazy_sessions(
    id integer primary key autoincrement,
    chat int,
    msg int,
    member int,
    type text,
    checkout_at timestamp with time zone
)
"""

SQL_FETCH_LAZY_DELETE_MESSAGES = (
    "select id,chat,msg from lazy_delete_messages where deleted_at < datetime('now','localtime') order by deleted_at limit 500"
)
SQL_FETCH_SESSIONS = "select id,chat,msg,member,type from lazy_sessions where checkout_at < datetime('now','localtime') order by checkout_at limit 500"

logger = manager.logger
logger.level = "DEBUG"


async def lazy_messages(bot: Bot):
    """
    处理延迟删除信息
    """
    async with database.connection() as conn:
        proxy = await conn.execute(SQL_FETCH_LAZY_DELETE_MESSAGES)
        rows = [i for i in await proxy.fetchall()]
        await proxy.close()

        for row in rows:
            if await manager.delete_message(row[1], row[2]):
                await conn.execute("delete from lazy_delete_messages where id=$1", (row[0],))
                await conn.commit()


async def lazy_sessions(bot: Bot):
    """
    处理延迟会话
    """
    async with database.connection() as conn:
        proxy = await conn.execute(SQL_FETCH_SESSIONS)
        rows = [i for i in await proxy.fetchall()]
        await proxy.close()

    if not rows:
        return

    async with database.connection() as conn:
        for row in rows:
            id = row[0]
            chat = row[1]
            msg = row[2]
            member = row[3]
            session_type = row[4]

            func = manager.events.get(session_type)
            if func and callable(func):
                await func(bot, chat, msg, member)

            await conn.execute("delete from lazy_sessions where id=$1", (id,))
            logger.info(f"lazy session is touched:{id} {session_type}")

        await conn.commit()


async def main():
    manager.load_config()
    manager.setup()

    bot = manager.bot
    Bot.set_current(bot)

    async with database.connection() as conn:
        await conn.execute(SQL_CREATE_MESSAGES)
        await conn.execute(SQL_CREATE_NEW_MEMBER_SESSION)

        # 清理不必要的数据
        await conn.execute("delete from lazy_sessions where checkout_at < datetime('now','-60 seconds')")

    for name, func in manager.events.items():
        logger.info(f"event:{name} => {func}")

    is_running = True
    while is_running:
        await asyncio.sleep(0.25)

        await lazy_messages(bot)
        await lazy_sessions(bot)

    print("worker closed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        is_running = False
