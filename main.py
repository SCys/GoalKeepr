import asyncio
from datetime import datetime
import database
from manager import manager
from handlers import *  # Import handlers to register them
from handlers.commands.image import worker as txt2img_worker
from handlers.member_captcha import member_captcha, new_member_callback
from handlers.member_captcha.events import new_member_check, unban_member
from handlers.member_captcha.join_queue import process_join_events

logger = manager.logger

# Worker Logic (merged from worker.py)
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

SQL_CREATE_CAPTCHA_ANSWERS = """
create table if not exists captcha_answers(
    chat int,
    member int,
    answer text,
    expires_at timestamp with time zone,
    primary key(chat, member)
)
"""

SQL_FETCH_LAZY_DELETE_MESSAGES = "select id,chat,msg from lazy_delete_messages where deleted_at < datetime('now') order by deleted_at limit 500"
SQL_FETCH_SESSIONS = "select id,chat,msg,member,type from lazy_sessions where checkout_at < datetime('now') order by checkout_at limit 500"


async def lazy_messages() -> int:
    """
    处理延迟删除信息
    """
    processed = 0
    try:
        # Process Redis tasks
        rdb = await manager.get_redis()
        if rdb:
            now = datetime.now().timestamp()
            tasks = await rdb.zrangebyscore("lazy_delete_messages", 0, now)
            for task in tasks:
                if isinstance(task, bytes):
                    task = task.decode()
                try:
                    chat_id, msg_id = map(int, task.split(":"))
                    if await manager.delete_message(chat_id, msg_id):
                        await rdb.zrem("lazy_delete_messages", task)
                        processed += 1
                    else:
                        logger.warning(f"lazy_messages delete failed: {task}")
                except Exception as e:
                    logger.error(f"lazy_messages redis task {task} error: {e}")
                    await rdb.zrem("lazy_delete_messages", task)

        # Process SQLite tasks
        rows = await database.execute_fetch(SQL_FETCH_LAZY_DELETE_MESSAGES)

        for row in rows:
            # row: id, chat, msg
            if await manager.delete_message(row[1], row[2]):
                await database.execute(
                    "delete from lazy_delete_messages where id=?", (row[0],)
                )
                processed += 1
    except Exception as e:
        logger.error(f"lazy_messages error: {e}")
    return processed


async def lazy_sessions() -> int:
    """
    处理延迟会话
    """
    processed = 0
    try:
        # Process Redis tasks
        rdb = await manager.get_redis()
        if rdb:
            now = datetime.now().timestamp()
            tasks = await rdb.zrangebyscore("lazy_sessions", 0, now)
            for task in tasks:
                if isinstance(task, bytes):
                    task = task.decode()
                remove_task = False
                try:
                    # Format: chat:member:type:msg
                    parts = task.split(":")
                    if len(parts) != 4:
                        logger.error(f"lazy_sessions redis task format error: {task}")
                        remove_task = True
                    else:
                        chat = int(parts[0])
                        member = int(parts[1])
                        session_type = parts[2]
                        msg = int(parts[3])

                        func = manager.events.get(session_type)
                        if not func or not callable(func):
                            logger.error(
                                f"lazy_session handler missing: {session_type}"
                            )
                            remove_task = True
                        else:
                            try:
                                await func(chat, msg, member)
                                remove_task = True
                            except Exception as e:
                                logger.error(
                                    f"lazy_session func {session_type} error: {str(e)}"
                                )
                except Exception as e:
                    logger.error(f"lazy_sessions redis task {task} error: {e}")
                    remove_task = True

                if remove_task:
                    await rdb.zrem("lazy_sessions", task)
                    logger.info(f"lazy session is touched: {task} (redis)")
                    processed += 1

        # Process SQLite tasks
        rows = await database.execute_fetch(SQL_FETCH_SESSIONS)

        if not rows:
            return processed

        for row in rows:
            id = row[0]
            chat = row[1]
            msg = row[2]
            member = row[3]
            session_type = row[4]

            func = manager.events.get(session_type)
            if func and callable(func):
                try:
                    await func(chat, msg, member)
                except Exception as e:
                    logger.error(f"lazy_session func {session_type} error: {e}")
                    continue
            else:
                logger.error(f"lazy_session handler missing: {session_type}")

            await database.execute("delete from lazy_sessions where id=?", (id,))
            logger.info(f"lazy session is touched:{id} {session_type}")
            processed += 1
    except Exception as e:
        logger.error(f"lazy_sessions error: {e}")
    return processed


async def worker_loop():
    logger.info("Worker loop started")
    while manager.is_running:
        try:
            processed = await lazy_messages()
            processed += await lazy_sessions()
            rdb = await manager.get_redis()
            if rdb:
                processed += await process_join_events(rdb, block_seconds=2.0)
            await asyncio.sleep(0.25 if processed else 1.0)
        except Exception as e:
            logger.error(f"worker_loop error: {e}", exc_info=True)
            await asyncio.sleep(5.0)  # 避免死循环


async def main():
    manager.setup()

    # Initialize database tables
    await database.execute(SQL_CREATE_MESSAGES)
    await database.execute(SQL_CREATE_NEW_MEMBER_SESSION)
    await database.execute(SQL_CREATE_CAPTCHA_ANSWERS)

    await manager.start()

    # 在主连接建立完成后再启动后台任务，避免 worker 读取到 is_running=False 后直接退出
    bg_tasks = [
        asyncio.create_task(txt2img_worker()),
        asyncio.create_task(worker_loop()),
    ]

    logger.info("主进程开始运行")
    try:
        await manager.client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("主进程收到退出信号，正在断开连接…")
    except asyncio.CancelledError:
        logger.info("主进程收到退出信号，正在断开连接…")
    except Exception as e:
        logger.error(f"主进程断开连接时发生错误: {e}")

    await manager.stop()
    for task in bg_tasks:
        task.cancel()
    await asyncio.gather(*bg_tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
