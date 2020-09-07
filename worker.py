import asyncio

import aiogram.utils.exceptions
from aiogram.bot.bot import Bot

import database
from handlers.new_members import new_member_check
from manager import manager

is_running = False


SQL_CREATE_MESSAGES = "create table if not exists lazy_delete_messages(id integer primary key autoincrement,chat int,msg int,deleted_at timestamp with time zone)"
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

logger = manager.logger
logger.level = "DEBUG"


async def lazy_messages(bot: Bot):
    """
    处理延迟删除信息
    """
    async with database.connection() as conn:
        proxy = await conn.execute(
            "select id,chat,msg from lazy_delete_messages where deleted_at < datetime('now','localtime') order by deleted_at limit 500"
        )
        rows = [i for i in await proxy.fetchall()]
        await proxy.close()

    async with database.connection() as conn:
        for row in rows:

            try:
                await bot.delete_message(row[1], row[2])
            except aiogram.utils.exceptions.MessageToDeleteNotFound:
                pass

            await conn.execute("delete from lazy_delete_messages where id=$1", (row[0],))
            logger.debug("[worker]message is deleted:{} {}", row[1], row[2])

        await conn.commit()


async def lazy_sessions(bot: Bot):
    """
    处理延迟会话
    """
    async with database.connection() as conn:
        proxy = await conn.execute(
            "select id,chat,msg,member,type from lazy_sessions where checkout_at < datetime('now','localtime') order by checkout_at limit 500"
        )
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
            logger.info("[worker]lazy session is touched:{} {}", id, session_type)

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
        logger.info("[worker]event:{} => {}", name, func)

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
