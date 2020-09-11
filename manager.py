import argparse
from types import MemberDescriptorType
from aiogram.types.chat import Chat
from aiogram.types.message import Message
from aiogram.utils.exceptions import BadRequest, MessageToDeleteNotFound
import loguru
import os.path
import sys
from configparser import ConfigParser
from datetime import datetime
from functools import wraps
from typing import Optional

from aiogram import Bot, Dispatcher, executor, types

import database

# logging.basicConfig(level=logging.DEBUG)

logger = loguru.logger


class Manager:
    config = ConfigParser()
    bot: Optional[Bot] = None
    dp: Optional[Dispatcher] = None

    handlers = []
    events = {}

    is_running = False

    logger = logger

    def load_config(self):
        config = self.config

        for key, section in {"default": {"debug": False}, "telegram": {"token": ""}}.items():
            config.setdefault(key, section)

        # load file
        if os.path.isfile("main.ini"):
            try:
                with open("main.ini", "r") as fobj:
                    config.read_file(fobj)
            except IOError:
                pass

        # load cmd arguments
        parser = argparse.ArgumentParser(description="goalkeepr arguments:")
        parser.add_argument("--token", dest="token", help="telegram bot token", type=str)
        args = parser.parse_args()
        if args.token:
            config["telegram"]["token"] = args.token

    def setup(self, ignoreHandlers=False):
        token = manager.config["telegram"]["token"]
        if not token:
            logger.error("[Manager]telegram token is missing")
            sys.exit(1)

        self.bot = Bot(token=token)
        logger.info("[Manager]bot is setup")

        self.dp = Dispatcher(self.bot)
        logger.info("[Manager]dispatcher is setup")

    def load_handlers(self):
        for func, type, args, kwargs in self.handlers:
            method = getattr(self.dp, f"{type}_handler")
            if callable(method):
                method(*args, **kwargs)(func)

                logger.info("[Manager]dispatcher:{}({},{})({})", method.__name__, args, kwargs, func)

    def register(self, type, *router_args, **router_kwargs):
        """
        延迟注册到 Dispatcher
        """

        def wrapper(func):
            self.handlers.append((func, type, router_args, router_kwargs))

            @wraps(func)
            async def wrappered(*args, **kwargs):
                return func(*args, **kwargs)

            return wrappered

        return wrapper

    def register_event(self, type):
        """
        将函数添加到事件处理内

        type: 对应 lazy_session 函数的类型

        函数会这样 await func(bot, chat_id, message_id, user_id) 调用
        """

        def wrapper(func):
            self.events[type] = func

            @wraps(func)
            async def wrappered(*args, **kwargs):
                return func(*args, **kwargs)

            return wrappered

        return wrapper

    def start(self):
        self.is_running = True

        executor.start_polling(self.dp, fast=True)

    def stop(self):
        self.is_running = False

        self.dp.stop_polling()

    def user_title(self, user):
        if isinstance(user, types.ChatMember):
            user = user.user

        if None in [user.first_name, user.last_name]:
            return f"{user.first_name or ''}{user.last_name or ''}"

        return " ".join([user.first_name, user.last_name])

    async def is_admin(self, chat: types.Chat, member: types.User):
        admins = await self.bot.get_chat_administrators(chat.id)
        return len([i for i in admins if i.is_chat_admin() and i.user.id == member.id]) > 0

    async def chat_member(self, chat: types.Chat, member_id: int):
        try:
            return await self.bot.get_chat_member(chat.id, member_id)

        except BadRequest as e:
            logger.error("chat {} member {} check error:{}", chat.id, member_id, str(e))

        except Exception:
            logger.exception("chat {} member {} check exception", chat.id, member_id)

    async def delete_message(self, chat: int, msg: int):
        """
        延缓删除消息
        chat: chat with msg
        msg: msg will be deleted
        deleted_at: message deleted after the timestamp
        """
        try:
            await self.bot.delete_message(chat, msg)
            logger.info("chat {} message {} deleted", chat, msg)
        except MessageToDeleteNotFound:
            logger.warning("chat {} message {} is deleted", chat, msg)
        except Exception:
            logger.exception("chat {} message {} delete error", chat, msg)
            return False

        return True

    async def lazy_delete_message(self, chat: int, msg: int, deleted_at: datetime):
        """
        延缓删除消息
        chat: chat with msg
        msg: msg will be deleted
        deleted_at: message deleted after the timestamp
        """

        async with database.connection() as conn:
            await conn.execute(
                "insert into lazy_delete_messages(chat,msg,deleted_at) values($1,$2,$3)", (chat, msg, deleted_at),
            )
            await conn.commit()

        logger.debug("chat {} message {} delete at {}", chat, msg, deleted_at)

    async def lazy_session(self, chat: int, msg: int, member: int, type: str, deleted_at: datetime):
        """
        延缓检查的会话
        """
        async with database.connection() as conn:
            await conn.execute(
                "insert into lazy_sessions(chat,msg,member,type,checkout_at) values($1,$2,$3,$4,$5)",
                (chat, msg, member, type, deleted_at),
            )
            await conn.commit()

        logger.debug("chat {} message {} member {} after {}", chat, msg, member, deleted_at)

    async def lazy_session_delete(self, chat: int, member: int, type: str):
        """
        延缓检查的会话
        """
        async with database.connection() as conn:
            await conn.execute(
                "delete from lazy_sessions where chat=$1 and member=$2 and type=$3", (chat, member, type),
            )
            await conn.commit()

        logger.debug("chat {} member {} lazy session {} is deleted", chat, member, type)


manager = Manager()
