import os.path
import sys
from configparser import ConfigParser
from datetime import datetime
from functools import wraps
from typing import Optional, Union

import aioredis
import loguru
from aiogram import Bot, Dispatcher, executor, types
from aiogram.utils.exceptions import (
    Unauthorized,
    BotBlocked,
    BotKicked,
    BadRequest,
    MessageCantBeDeleted,
    MessageToDeleteNotFound,
)
import openai

import database

logger = loguru.logger

SETTINGS_TEMPLATE = {
    "default": {"debug": False},
    "telegram": {"token": ""},  # telegram robot token
    "captcha": {
        "cloudflare_turnstile": False,  # enable cloudflare turnstile detector
        "cloudflare_turnstile_token": "",
        "google_recaptcha": False,  # enable google recaptcha detector
        "google_recaptcha_token": "",
    },
    "openai": {"api": "", "base_url": ""},
    "image": {
        "users": [],  # allowed users(id list)
        "groups": [],  # allowed groups(id list)
    },
}


class Manager:
    """管理模块"""

    bot: Bot
    dp: Dispatcher

    rdb: Optional[aioredis.Redis] = None

    config = ConfigParser()

    handlers = []
    events = {}

    is_running = False

    logger = logger

    def load_config(self):
        """加载 main.ini，默认会配置相关代码"""
        config = self.config

        # 设置默认模板
        for key, section in SETTINGS_TEMPLATE.items():
            config.setdefault(key, section)

        # 从文件读取
        if os.path.isfile("main.ini"):
            try:
                with open("main.ini", "r", encoding="utf-8") as f:
                    config.read_file(f)

                logger.info("settings is loaded from main.ini")
            except IOError:
                pass

    def setup(self):
        token = self.config["telegram"]["token"]
        if not token:
            logger.error("telegram token is missing")
            sys.exit(1)

        # setup image config
        try:
            self.config["image"]["users"] = [int(i) for i in self.config["image"]["users"].split(",")]
            self.config["image"]["groups"] = [int(i) for i in self.config["image"]["groups"].split(",")]
        except:
            logger.exception("image users or groups is invalid")

        # setup openai sdk config
        openai.api_key = self.config["openai"]["api"]
        openai.api_base = self.config["openai"]["base_url"]
        logger.info(f"openai is setup, base on {openai.api_base}")

        self.bot = Bot(token=token)
        logger.info("bot is setup")

        self.dp = Dispatcher(self.bot)
        logger.info("dispatcher is setup")

    def load_handlers(self):
        dp = self.dp
        handlers = self.handlers

        for func, type_name, args, kwargs in handlers:
            method = getattr(dp, f"register_{type_name}_handler")
            if not callable(method):
                continue

            method(func, *args, **kwargs)
            logger.info(f"dispatcher:{method.__name__}({func.__name__}, {args}, {kwargs})")

    def register(self, type_name, *router_args, **router_kwargs):
        """
        延迟注册到 Dispatcher
        """

        def wrapper(func):
            self.handlers.append((func, type_name, router_args, router_kwargs))

            @wraps(func)
            async def _wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return _wrapper

        return wrapper

    def register_event(self, type_name: str):
        """
        将函数添加到事件处理内

        type_name: 对应 lazy_session 函数的类型

        函数会这样 await func(bot, chat_id, message_id, user_id) 调用
        """

        def wrapper(func):
            self.events[type_name] = func

            @wraps(func)
            async def _wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return _wrapper

        return wrapper

    def start(self):
        self.is_running = True

        executor.start_polling(self.dp, fast=True)

    def stop(self):
        self.is_running = False

        self.dp.stop_polling()

    def username(self, _user: Union[types.ChatMember, types.User]):
        """获取用户名"""

        if isinstance(_user, types.ChatMember):
            return _user.user.full_name

        return _user.full_name

    async def is_admin(self, chat: types.Chat, member: types.User):
        try:
            admins = await self.bot.get_chat_administrators(chat.id)
            return len([i for i in admins if i.is_chat_admin() and i.user.id == member.id]) > 0
        except BadRequest as e:
            logger.error(f"chat {chat.id} member {member.id} check failed:{e}")

        return False

    async def chat_member(self, chat: types.Chat, member_id: int):
        try:
            return await self.bot.get_chat_member(chat.id, member_id)
        except BadRequest:
            logger.error(f"chat {chat.id} member {member_id} check failed")
        except:
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
            logger.info(f"chat {chat} message {msg} deleted")
        except BotBlocked:
            logger.info(f"chat {chat} message {msg} delete failed, bot blocked")
        except BotKicked:
            logger.info(f"chat {chat} message {msg} delete failed, bot kicked")
        except Unauthorized:
            logger.info(f"chat {chat} message {msg} delete failed, unauthorized(include kicked/blocked/...)")
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

    async def send(self, chat: int, msg: str, **kwargs):
        """
        发送消息
        chat: chat with msg
        msg: msg will be sent
        """
        try:
            await self.bot.send_message(chat, msg, **kwargs)
            logger.info(f"chat {chat} message {msg} sent")
        except:
            logger.exception(f"chat {chat} message {msg} send error")
            return False

        return True

    async def reply(self, chat: int, message_id: int, msg: str, **kwargs):
        """
        回复消息
        chat: chat with msg
        msg: msg will be sent
        """
        try:
            await self.bot.send_message(chat, msg, reply_to_message_id=message_id, **kwargs)
            logger.info(f"chat {chat} message {msg} sent")
        except:
            logger.exception(f"chat {chat} message {msg} send error")
            return False

        return True

    async def get_redis(self):
        """setup redis connections"""
        if "redis" not in self.config:
            return None

        if self.rdb is None:
            redis_dsn = self.config["redis"]["dsn"]
            self.rdb = await aioredis.from_url(redis_dsn)

        return self.rdb


manager = Manager()
