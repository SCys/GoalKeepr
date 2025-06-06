import os.path
import sys
from configparser import ConfigParser
from datetime import datetime
from functools import wraps
from typing import List, Optional, Union

import aiohttp
import aioredis
import loguru
from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramBadRequest
from bs4 import BeautifulSoup, Tag

import database

from .settings import SETTINGS_TEMPLATE

logger = loguru.logger


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
    callback_handlers: List

    # running status
    is_running = False

    logger = logger

    def setup(self):
        self.load_config()

        self.setup_logger()

        token = self.config["telegram"]["token"]
        if not token:
            logger.error("telegram token is missing")
            sys.exit(1)

        self.bot = Bot(token)
        # DEBUG PROXY
        # self.bot.session.proxy = 'http://10.1.3.16:3002'
        logger.info("bot is setup")

        self.setup_handlers()
        self.setup_callback()

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

    def setup_handlers(self):
        """
        设置事件处理
        """
        for func, type_name, args, kwargs in self.handlers:
            observer = self.dp.observers.get(type_name, None)
            if not observer or not hasattr(observer, "register"):
                logger.warning(f"dispatcher:unknown type {type_name}")
                continue

            method = observer.register
            method(func, *args, **kwargs)
            logger.info(
                f"dispatcher {func.__name__}:{observer.event_name}.{method.__name__}({args}, {kwargs})"
            )

    def setup_callback(self):
        # list callback handler
        for func, args, kwargs in self.callback_handlers:
            logger.info(f"dispatcher callback_query {func.__name__} is registered")

        self.dp.callback_query.register(self._callback_handler)
        logger.info("dispatcher callback_query is setup")


    def register(self, type_name, *args, **kwargs):
        """
        延迟注册到 Dispatcher
        """

        def wrapper(func):
            if type_name == "callback_query":
                self.callback_handlers.append((func, args, kwargs))
                logger.info(f"dispatcher callback_query {func.__name__} is registered")
            else:
                self.handlers.append((func, type_name, args, kwargs))
                logger.info(f"dispatcher {func.__name__}:{type_name}({args}, {kwargs})")

            @wraps(func)
            async def _wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

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
            return _user.user.full_name  # type: ignore

        return _user.full_name

    async def is_admin(self, chat: types.Chat, member: types.User):
        try:
            admins = await self.bot.get_chat_administrators(chat.id)
            return len([i for i in admins if i.user.id == member.id]) > 0
        except Exception as e:
            logger.error(f"chat {chat.id} member {member.id} check failed:{e}")

        return False

    async def chat_member(self, chat: types.Chat, member_id: int):
        try:
            return await self.bot.get_chat_member(chat.id, member_id)
        except:
            logger.exception(f"chat {chat.id} member {member_id} check exception")

    async def get_user_extra_info(self, username: str):
        """
        通过解析 Telegram 用户页面的 HTML，获取头像 URL 和 bio 信息
        :param username: Telegram 用户名（不带@）
        :return: 用户的头像 URL 和 bio 信息
        """
        url = f"https://t.me/{username}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }

        try:
            session = await self.create_session()
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15, sock_read=12),
            ) as response:
                if response.status != 200:
                    return {
                        "error": f"Failed to fetch page for {username}, status: {response.status}"
                    }

                page_content = await response.text()
                soup = BeautifulSoup(page_content, "html.parser")

                # 提取头像 URL
                image_tag = soup.find("img", {"class": "tgme_page_photo_image"})
                if isinstance(image_tag, Tag):
                    image_url = image_tag.get("src")
                else:
                    image_url = None

                # 提取 bio 信息
                bio_tag = soup.find("div", {"class": "tgme_page_description"})
                bio = bio_tag.text.strip() if bio_tag else None

                return {"bio": bio, "image_url": image_url}
        except Exception as e:
            logger.error(f"Failed to fetch page for {username}: {e}")
            return

    async def delete_message(
        self,
        chat: Union[int, types.Chat],
        msg: Union[int, types.Message, None],
        deleted_at: Union[datetime, None] = None,
    ):
        """
        延缓删除消息
        chat: chat with msg
        msg: msg will be deleted
        deleted_at: message deleted after the timestamp
        """
        if msg is None:
            return True

        id_chat: int = chat.id if isinstance(chat, types.Chat) else chat
        id_message: int = msg.message_id if isinstance(msg, types.Message) else msg

        if deleted_at is not None:
            await database.execute(
                "insert into lazy_delete_messages(chat,msg,deleted_at) values($1,$2,$3)",
                (id_chat, id_message, deleted_at),
            )
            logger.debug(f"chat {id_chat} message {id_message} delete at {deleted_at}")
        else:
            try:
                await self.bot.delete_message(id_chat, id_message)
                logger.info(f"chat {id_chat} message {id_message} deleted")
            except TelegramBadRequest:
                logger.warning(f"chat {id_chat} message {id_message} not found")
            except Exception as e:
                logger.exception(f"chat {id_chat} message {id_message} delete failed")

        return True

    async def lazy_session(
        self, chat: int, msg: int, member: int, type: str, deleted_at: datetime
    ):
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
        auto_deleted_at = kwargs.pop("auto_deleted_at", None)

        try:
            resp = await self.bot.send_message(chat, msg, **kwargs)
            logger.info(f"chat {chat} message {msg} sent")
        except:
            logger.exception(f"chat {chat} message {msg} send error")
            return False

        if auto_deleted_at is not None:
            await self.delete_message(chat, resp, auto_deleted_at)

        return True

    async def reply(self, msg: types.Message, content: str, *args, **kwargs):
        """
        回复消息
        msg: reply to message
        content: reply content
        auto_deleted_at: message deleted after the timestamp
        """
        auto_deleted_at = kwargs.pop("auto_deleted_at", None)
        if auto_deleted_at is None:
            # first arg is datetime, set it as auto_deleted_at
            if len(args) > 0 and isinstance(args[0], datetime):
                auto_deleted_at = args[0]
                args = args[1:]

        try:
            resp = await msg.reply(content, *args, **kwargs)
            logger.info(f"chat {msg.chat.id} message {msg.message_id} replied")
        except:
            logger.exception(f"chat {msg.chat.id} message {msg.message_id} reply error")
            return False

        if auto_deleted_at is not None:
            await self.delete_message(msg.chat, resp, auto_deleted_at)

        return True

    async def edit_text(self, chat: int, msg: int, content: str, *args, **kwargs):
        """
        编辑消息
        chat: chat with msg
        msg: msg will be edited
        content: new content
        """
        auto_deleted_at = kwargs.pop("auto_deleted_at", None)
        if auto_deleted_at is None:
            # first arg is datetime, set it as auto_deleted_at
            if len(args) > 0 and isinstance(args[0], datetime):
                auto_deleted_at = args[0]
                args = args[1:]

        try:
            await self.bot.edit_message_text(
                content, chat_id=chat, message_id=msg, *args, **kwargs
            )
            logger.info(f"chat {chat} message {msg} edited")
        except:
            logger.exception(f"chat {chat} message {msg} edit error")
            return False

        if auto_deleted_at is not None:
            await self.delete_message(chat, msg, auto_deleted_at)

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

    async def create_session(self):
        return await self.bot.session.create_session()  # type: ignore

    async def _callback_handler(self, query: types.CallbackQuery):
        """
        默认回调处理程序
        """

        for func, args, kwargs in self.callback_handlers:
            await func(query, *args, **kwargs)
            logger.info(f"callback_query {func.__name__} is called with message {query.message}")
