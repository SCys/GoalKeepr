#!/usr/bin/env python3
"""
GoalKeepr - Telegram group management bot (captcha + admin utils)
支持通过环境变量或命令行参数指定配置文件和数据目录，
以便源码树 (src/) 与配置/数据 (main.ini + data/) 分离部署。
"""
import argparse
import os
import sys
from datetime import datetime

# --- Early path / config setup (before other imports that may read env) ---
def _setup_runtime_paths():
    """Parse --config / --data-dir early so that database and manager pick up the env vars."""
    parser = argparse.ArgumentParser(
        description="GoalKeepr Telegram Bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=os.environ.get("GOALKEEPR_CONFIG"),
        help="Path to main.ini (or set GOALKEEPR_CONFIG env)",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("GOALKEEPR_DATA_DIR"),
        help="Directory for main.db and Telethon session file (or set GOALKEEPR_DATA_DIR env)",
    )
    # Use parse_known_args so extra args (e.g. from uv) don't break us.
    args, _ = parser.parse_known_args(sys.argv[1:])

    if args.config:
        os.environ["GOALKEEPR_CONFIG"] = args.config
    if args.data_dir:
        os.environ["GOALKEEPR_DATA_DIR"] = args.data_dir

_setup_runtime_paths()

# Now safe to import modules that consume GOALKEEPR_* env vars at import/use time.
import asyncio

import database
from manager import manager
from handlers import *  # Import handlers to register them
from handlers.commands.image import worker as txt2img_worker
from handlers.member_captcha.events import new_member_check, unban_member, safety_timeout_check

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

SQL_FETCH_LAZY_DELETE_MESSAGES = (
    "select id,chat,msg from lazy_delete_messages where deleted_at < datetime('now','localtime') order by deleted_at limit 500"
)
SQL_FETCH_SESSIONS = "select id,chat,msg,member,type from lazy_sessions where checkout_at < datetime('now','localtime') order by checkout_at limit 500"

async def lazy_messages() -> int:
    """
    处理延迟删除信息
    """
    processed = 0
    try:
        # Process Redis tasks
        rdb = await manager.get_redis()
        if rdb:
            try:
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
                        logger.exception(f"lazy_messages redis task {task} error: {e}")
                        await rdb.zrem("lazy_delete_messages", task)
            except Exception as e:
                logger.error(f"lazy_messages redis error: {e}")
                manager.rdb = None  # will retry connect next tick

        # Process SQLite tasks
        rows = await database.execute_fetch(SQL_FETCH_LAZY_DELETE_MESSAGES)
        
        for row in rows:
            # row: id, chat, msg
            if await manager.delete_message(row[1], row[2]):
                await database.execute("delete from lazy_delete_messages where id=?", (row[0],))
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
            try:
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
                                logger.error(f"lazy_session handler missing: {session_type}")
                                remove_task = True
                            else:
                                try:
                                    await func(manager.client, chat, msg, member)
                                    remove_task = True
                                except Exception as e:
                                    logger.error(f"lazy_session func {session_type} error: {e}")
                    except Exception as e:
                        logger.error(f"lazy_sessions redis task {task} error: {e}")
                        remove_task = True
                    
                    if remove_task:
                        await rdb.zrem("lazy_sessions", task)
                        logger.info(f"lazy session is touched: {task} (redis)")
                        processed += 1
            except Exception as e:
                logger.error(f"lazy_sessions redis error: {e}")
                manager.rdb = None

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
                # func signature: await func(bot, chat, msg, member) -> changed to func(chat, msg, member) or use manager.client
                # The original signature was func(bot, ...). 
                # We need to update the event handlers signature too.
                # Passing manager.client as first arg to maintain compatibility if possible,
                # or better, update handlers to not expect bot.
                # For now, pass client.
                try:
                    await func(manager.client, chat, msg, member)
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
        processed = await lazy_messages()
        processed += await lazy_sessions()
        await asyncio.sleep(0.25 if processed else 1.0)

async def startup_cleanup():
    """启动时清理可能残留的 Redis 数据。"""
    try:
        rdb = await manager.get_redis()
        if not rdb:
            return

        cursor = 0
        total = 0
        while True:
            cursor, keys = await rdb.scan(cursor, match="captcha_cb_map:*", count=100)
            if keys:
                await rdb.delete(*keys)
                total += len(keys)
            if cursor == 0:
                break
        if total:
            logger.warning(f"启动清理：已清除 {total} 个残留 callback_map（重启导致失效）")
        else:
            logger.debug("启动清理：无残留 callback_map")
    except Exception as e:
        logger.warning(f"启动清理 Redis 残留数据失败（已忽略，继续启动）: {e}")


async def main():
    config_path = os.environ.get("GOALKEEPR_CONFIG")
    manager.setup(config_path=config_path)

    # Initialize database tables
    await database.execute(SQL_CREATE_MESSAGES)
    await database.execute(SQL_CREATE_NEW_MEMBER_SESSION)

    # Cleanup stale Redis data from previous run
    await startup_cleanup()

    # Start tasks
    asyncio.create_task(txt2img_worker())
    asyncio.create_task(worker_loop())
    
    logger.info("主进程开始运行")
    try:
        await manager.start()
        await manager.client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("主进程收到退出信号，正在断开连接…")
    except asyncio.CancelledError:
        logger.info("主进程收到退出信号，正在断开连接…")
    except Exception as e:
        logger.error(f"主进程断开连接时发生错误: {e}")

    await manager.stop()

if __name__ == "__main__":
    asyncio.run(main())