import os.path
import sys
from configparser import ConfigParser
from datetime import datetime
from functools import wraps
from typing import Optional, Union

import aioredis
import loguru
from aiogram import Bot, Dispatcher, types

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
    "ai": {
        "google_gemini_host": "",
        "google_gemini_token": "",
        "proxy_host": "",
        "proxy_token": "",
        "administrator": 0,  # admin user id
        "manage_group": 0,  # manage group id
    },
    "image": {
        "users": [],  # allowed users(id list)
        "groups": [],  # allowed groups(id list)
    },
    "sd_api": {
        "endpoint": "",
    },
}


class Manager:
    """管理模块"""

    # aiogram instance
    bot: Bot
    dp: Dispatcher = Dispatcher()  # static dispatcher

    # redis connection
    rdb: Optional["aioredis.Redis"] = None

    # global config
    config = ConfigParser()

    # routes
    handlers = []
    events = {}

    # running status
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
        self.setup_logger()

        token = self.config["telegram"]["token"]
        if not token:
            logger.error("telegram token is missing")
            sys.exit(1)

        self.bot = Bot(token)
        # self.bot.session.proxy = 'http://10.1.3.16:3002'
        logger.info("bot is setup")

    def setup_logger(self):
        """设置logger"""
        logger = self.logger

        if self.config["default"].getboolean("debug", False):
            logger.remove()
            logger.add(sys.stderr, level=10)
            logger.debug("logger is setup with debug level")
            return

        logger.remove()
        logger.add(sys.stderr, level=20)
        logger.info("logger is setup")

    def load_handlers(self):
        dp = self.dp
        handlers = self.handlers

        for func, type_name, args, kwargs in handlers:
            observer = dp.observers.get(type_name, None)
            if not observer or not hasattr(observer, "register"):
                logger.warning(f"dispatcher:unknown type {type_name}")
                continue

            method = observer.register
            method(func, *args, **kwargs)
            logger.info(f"dispatcher {func.__name__}:{observer.event_name}.{method.__name__}({args}, {kwargs})")

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

    async def start(self):
        self.is_running = True

        if "admin" in self.config["telegram"]:
            admin = self.config["telegram"]["admin"]
            await self.bot.send_message(admin, "bot is started")

        await self.dp.start_polling(self.bot)

    async def stop(self):
        self.is_running = False

        await self.dp.stop_polling()

    def username(self, _user: Union[types.ChatMember, types.User]):
        """获取用户名"""

        if isinstance(_user, types.ChatMember):
            return _user.user.full_name

        return _user.full_name

    async def is_admin(self, chat: types.Chat, member: types.User):
        try:
            admins = await self.bot.get_chat_administrators(chat.id)
            # return len([i for i in admins if i.can_delete_messages and i.user.id == member.id]) > 0
            return len([i for i in admins if i.user.id == member.id]) > 0
        except Exception as e:
            logger.error(f"chat {chat.id} member {member.id} check failed:{e}")

        return False

    async def chat_member(self, chat: types.Chat, member_id: int):
        try:
            return await self.bot.get_chat_member(chat.id, member_id)
        except:
            logger.exception(f"chat {chat.id} member {member_id} check exception")

    async def delete_message(
        self, chat: Union[int, types.Chat], msg: Union[int, types.Message], deleted_at: Union[datetime, None] = None
    ):
        """
        延缓删除消息
        chat: chat with msg
        msg: msg will be deleted
        deleted_at: message deleted after the timestamp
        """
        if isinstance(chat, types.Chat):
            chat = chat.id

        if isinstance(msg, types.Message):
            msg = msg.message_id

        if deleted_at is not None:
            await database.execute(
                "insert into lazy_delete_messages(chat,msg,deleted_at) values($1,$2,$3)",
                (chat, msg, deleted_at),
            )
            logger.debug(f"chat {chat} message {msg} delete at {deleted_at}")
        else:
            try:
                await self.bot.delete_message(chat, msg)
                logger.info(f"chat {chat} message {msg} deleted")
            except Exception as e:
                logger.exception(f"chat {chat} message {msg} delete failed")

        return True

    async def lazy_session(self, chat: int, msg: int, member: int, type: str, deleted_at: datetime):
        await database.execute(
            "insert into lazy_sessions(chat,msg,member,type,checkout_at) values($1,$2,$3,$4,$5)",
            (chat, msg, member, type, deleted_at),
        )

        logger.debug(f"chat {chat} message {msg} member {member} after {deleted_at}")

    async def lazy_session_delete(self, chat: int, member: int, type: str):
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

    async def reply(self, msg: types.Message, content: str, auto_deleted_at: datetime = None, *args, **kwargs):
        """
        回复消息
        msg: reply to message
        content: reply content
        auto_deleted_at: message deleted after the timestamp
        """
        try:
            resp = await msg.reply(content, *args, **kwargs)
            logger.info(f"chat {msg.chat.id} message {msg.message_id} replied")
        except:
            logger.exception(f"chat {msg.chat.id} message {msg.message_id} reply error")
            return False

        if auto_deleted_at is not None:
            await self.delete_message(msg.chat, resp, auto_deleted_at)

        return True

    async def notification(self, content: str):
        if "admin" in self.config["telegram"]:
            admin = self.config["telegram"]["admin"]
            await self.bot.send_message(admin, content)

    async def get_redis(self):
        """setup redis connections"""
        if "redis" not in self.config:
            return None

        if self.rdb is None:
            redis_dsn = self.config["redis"]["dsn"]
            self.rdb = await aioredis.from_url(redis_dsn)

        return self.rdb


manager = Manager()
