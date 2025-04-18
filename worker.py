import asyncio

from aiogram import Bot

import database
from handlers.commands.image import worker as txt2img_worker  # NOQA: 引入处理器
from handlers.member_captcha.events import new_member_check, unban_member  # NOQA: 引入处理器
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
# logger.level('DEBUG')


async def lazy_messages(bot: Bot):
    """
    处理延迟删除信息
    """
    rows = await database.execute_fetch(SQL_FETCH_LAZY_DELETE_MESSAGES)
    
    for row in rows:
        if await manager.delete_message(row[1], row[2]):
            await database.execute("delete from lazy_delete_messages where id=$1", (row[0],))


async def lazy_sessions(bot: Bot):
    """
    处理延迟会话
    """
    rows = await database.execute_fetch(SQL_FETCH_SESSIONS)
    
    if not rows:
        return

    for row in rows:
        id = row[0]
        chat = row[1]
        msg = row[2]
        member = row[3]
        session_type = row[4]

        func = manager.events.get(session_type)
        if func and callable(func):
            await func(bot, chat, msg, member)

        await database.execute("delete from lazy_sessions where id=$1", (id,))
        logger.info(f"lazy session is touched:{id} {session_type}")


async def main():
    manager.load_config()
    manager.setup()

    bot = manager.bot

    # Initialize database tables
    await database.execute(SQL_CREATE_MESSAGES)
    await database.execute(SQL_CREATE_NEW_MEMBER_SESSION)
    
    # 清理不必要的数据
    await database.execute("delete from lazy_sessions where checkout_at < datetime('now','-60 seconds')")

    for name, func in manager.events.items():
        logger.info(f"event:{name} => {func}")

    is_running = True

    # 启动新成员检查
    asyncio.create_task(txt2img_worker())

    # 启动延迟删除消息
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
