import argparse
import os.path
import sys
from configparser import ConfigParser
from datetime import datetime
from functools import wraps
from typing import Optional

import loguru
from aiogram import Bot, Dispatcher, executor, types
from aiogram.utils.exceptions import BadRequest, MessageCantBeDeleted, MessageToDeleteNotFound

import database

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
            logger.error("telegram token is missing")
            sys.exit(1)

        self.bot = Bot(token=token)
        logger.info("bot is setup")

        self.dp = Dispatcher(self.bot)
        logger.info("dispatcher is setup")

    def load_handlers(self):
        for func, type, args, kwargs in self.handlers:
            method = getattr(self.dp, f"{type}_handler")
            if callable(method):
                method(*args, **kwargs)(func)

                logger.info("dispatcher:{}({},{})({})", method.__name__, args, kwargs, func)

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

        except BadRequest:
            logger.error(f"chat {chat.id} member {member_id} check failed")

        except Exception:
            logger.exception(f"chat {chat.id} member {member_id} check exception")

    async def delete_message(self, chat: int, msg: int):
        """
        删除消息
        chat: chat with msg
        msg: msg will be deleted
        deleted_at: message deleted after the timestamp
        """
        try:
            await self.bot.delete_message(chat, msg)
            logger.info("chat {} message {} deleted", chat, msg)
        except MessageCantBeDeleted:
            logger.warning(f"chat {chat} message {msg} can not be deleted")
        except MessageToDeleteNotFound:
            logger.warning(f"chat {chat} message {msg} is deleted")
        except Exception:
            logger.exception(f"chat {chat} message {msg} delete error")
            return False

        return True

    async def lazy_delete_message(self, chat: int, msg: int, deleted_at: datetime):
        """
        延缓删除消息
        chat: chat with msg
        msg: msg will be deleted
        deleted_at: message deleted after the timestamp
        """
        await database.execute(
            "insert into lazy_delete_messages(chat,msg,deleted_at) values($1,$2,$3)",
            (chat, msg, deleted_at),
        )

        logger.debug(f"chat {chat} message {msg} delete at {deleted_at}")

    async def lazy_session(self, chat: int, msg: int, member: int, type: str, deleted_at: datetime):
        """
        延缓检查的会话
        """
        await database.execute(
            "insert into lazy_sessions(chat,msg,member,type,checkout_at) values($1,$2,$3,$4,$5)",
            (chat, msg, member, type, deleted_at),
        )

        logger.debug(f"chat {chat} message {msg} member {member} after {deleted_at}")

    async def lazy_session_delete(self, chat: int, member: int, type: str):
        """
        延缓检查的会话
        """
        await database.execute(
            "delete from lazy_sessions where chat=$1 and member=$2 and type=$3",
            (chat, member, type),
        )

        logger.debug(f"chat {chat} member {member} lazy session {type} is deleted")


manager = Manager()
