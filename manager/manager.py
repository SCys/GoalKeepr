import os.path
import sys
from configparser import ConfigParser
from datetime import datetime, timezone
from functools import wraps
from typing import Optional, Union, Tuple, Any
from urllib.parse import urlparse

import aiohttp
import database
import redis.asyncio as aioredis
import loguru
from telethon import TelegramClient, events, types, hints
from bs4 import BeautifulSoup, Tag

from .settings import SETTINGS_TEMPLATE

logger = loguru.logger


class RedisUnavailableError(RuntimeError):
    """Redis 未配置或不可用，依赖 Redis 的功能将无法使用。"""


def _redis_configured(config: ConfigParser) -> bool:
    return "redis" in config and config["redis"].get("dsn")


def _parse_proxy(proxy_url: str) -> Optional[Tuple[Any, ...]]:
    """
    将代理 URL 解析为 Telethon/PySocks 所需的 (scheme, host, port) 或 (scheme, host, port, username, password)。
    支持 socks5://host:port、socks5://user:pass@host:port、http://host:port 等格式。
    """
    proxy_url = (proxy_url or "").strip()
    if not proxy_url:
        return None
    try:
        r = urlparse(proxy_url)
        if not r.scheme or not r.hostname:
            return None
        scheme = r.scheme.lower()
        if scheme not in ("socks5", "http"):
            logger.warning(
                f"telegram proxy 仅支持 socks5/http，当前为 {scheme}，将按 socks5 使用"
            )
            if scheme == "https":
                scheme = "http"
            else:
                scheme = "socks5"
        host = r.hostname
        port = r.port or (1080 if "socks" in scheme else 80)
        if r.username is not None:
            return (scheme, host, port, r.username, r.password or "")
        return (scheme, host, port)
    except Exception as e:
        logger.warning(f"解析 telegram proxy 失败: {proxy_url}, {e}")
        return None


class Manager:
    """管理模块"""

    # Telethon instance
    client: TelegramClient

    # redis connection
    rdb: Optional[aioredis.Redis] = None

    # http session
    http_session: Optional[aiohttp.ClientSession] = None

    # global config
    config = ConfigParser()

    # routes
    handlers = []
    events = {}

    # running status
    is_running = False

    logger = logger

    def setup(self):
        self.load_config()

        self.setup_logger()

        token = self.config["telegram"]["token"]
        api_id = self.config["telegram"].get("api_id")
        api_hash = self.config["telegram"].get("api_hash")

        if not token:
            logger.error("telegram token is missing")
            sys.exit(1)

        if not api_id or not api_hash:
            logger.error(
                "telegram api_id 或 api_hash 未配置，请在 main.ini [telegram] 中填写（从 https://my.telegram.org 获取）"
            )
            sys.exit(1)

        # 解析代理（可选），格式如 socks5://127.0.0.1:1080 或 socks5://user:pass@host:port
        proxy = _parse_proxy(self.config["telegram"].get("proxy", ""))

        # Initialize Telethon Client (session name 'bot')
        self.client = TelegramClient(
            "bot",
            int(api_id) if api_id else 0,
            api_hash or "",
            proxy=proxy,
        )

        if proxy:
            logger.info("telethon client is setup (with proxy)")
        else:
            logger.info("telethon client is setup")

        self.setup_handlers()

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
        Registers handlers stored in self.handlers to the client.
        """
        logger.debug(f"setup_handlers: {len(self.handlers)} handlers registered")
        if not self.handlers:
            logger.warning("setup_handlers: no handlers found")

    def register(self, type_name, *args, **kwargs):
        """
        Decorator to register handlers.
        type_name: "message", "callback_query", "chat_member"
        kwargs: passed to event filter (e.g. pattern, outgoing)
        """

        def wrapper(func):
            event_cls = None
            if type_name == "message":
                event_cls = events.NewMessage
            elif type_name == "callback_query":
                event_cls = events.CallbackQuery
            elif type_name == "chat_member":
                event_cls = events.ChatAction
                # 只处理新成员加入（自己加入或被邀请）
                kwargs.setdefault("func", lambda e: e.user_joined or e.user_added)

            if event_cls:
                self.handlers.append((func, event_cls, args, kwargs))
                logger.debug(
                    f"handler {func.__name__} registered to client event {event_cls.__name__}"
                )
                return func
            else:
                logger.warning(f"Unknown event type {type_name}")
                # empty wrapper to avoid error
                return lambda x: x

        return wrapper

    def register_event(self, type_name: str):
        """
        将函数添加到事件处理内 (Internal events like lazy_session)
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

        # Actually register handlers to client
        for func, event_cls, args, kwargs in self.handlers:
            self.client.add_event_handler(func, event_cls(*args, **kwargs))
            logger.debug(
                f"handler {func.__name__} registered to client event {event_cls.__name__}"
            )

        token = self.config["telegram"]["token"]

        await self.client.start(bot_token=token)

        me = await self.client.get_me(input_peer=False)
        logger.info(f"bot started as {self.username(me)}")

        await self.check_redis()

        if "admin" in self.config["telegram"]:
            admin = int(self.config["telegram"]["admin"])
            try:
                await self.send(admin, "bot is started")
            except Exception as e:
                logger.debug(f"admin notification failed: {e}")

    async def stop(self):
        self.is_running = False
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await database.close()
        await self.client.disconnect()

    def username(self, user: hints.EntityLike):
        """获取用户名"""
        return (
            user.username
            if isinstance(user, types.User)
            else user.title
            if isinstance(user, types.Chat)
            else str(user)
        )

    async def is_admin(
        self,
        chat: Union[types.Chat, types.Channel, int],
        member: Union[types.User, int],
    ):
        try:
            if isinstance(chat, int):
                chat_id = chat
            else:
                chat_id = chat.id

            if isinstance(member, int):
                user_id = member
            else:
                user_id = member.id

            perms = await self.client.get_permissions(chat_id, user_id)
            return perms.is_admin or perms.is_creator
        except Exception as e:
            logger.error(f"check admin failed: {e}")
        return False

    async def chat_member_permissions(self, chat, member_id: int):
        try:
            return await self.client.get_permissions(chat, member_id)
        except Exception as e:
            logger.exception(f"chat member permissions check exception: {e}")
            return None

    async def get_user_extra_info(self, username: str):
        url = f"https://t.me/{username}"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            session = await self.create_session()
            async with session.get(url, headers=headers, timeout=15) as response:
                if response.status != 200:
                    return {"error": f"status {response.status}"}
                page_content = await response.text()
                soup = BeautifulSoup(page_content, "html.parser")
                image_tag = soup.find("img", {"class": "tgme_page_photo_image"})
                image_url = image_tag.get("src") if isinstance(image_tag, Tag) else None
                bio_tag = soup.find("div", {"class": "tgme_page_description"})
                bio = bio_tag.text.strip() if bio_tag else None
                return {"bio": bio, "image_url": image_url}
        except Exception as e:
            logger.error(f"Failed to fetch page: {e}")
            return

    async def delete_message(
        self,
        chat: Union[int, types.Chat, types.Channel],
        msg: Union[int, types.Message, None],
        deleted_at: Union[datetime, None] = None,
    ):
        if msg is None:
            return True

        # Resolve ID（Chat=普通群，Channel=超级组/频道）
        id_chat = chat
        if isinstance(chat, (types.Chat, types.Channel)):
            id_chat = chat.id

        id_message = msg
        if isinstance(msg, types.Message):
            id_message = msg.id

        if id_message is None:
            return False

        if deleted_at is not None:
            rdb = await self.get_redis()
            if rdb:
                try:
                    await rdb.zadd(
                        "lazy_delete_messages",
                        {f"{id_chat}:{id_message}": deleted_at.timestamp()},
                    )
                    logger.debug(
                        f"chat {id_chat} message {id_message} delete at {deleted_at} (redis)"
                    )
                    return True
                except Exception as e:
                    logger.error(f"lazy delete schedule failed (redis): {e}")
            try:
                await database.execute(
                    "insert into lazy_delete_messages(chat, msg, deleted_at) values(?,?,?)",
                    (id_chat, id_message, self._format_sqlite_datetime(deleted_at)),
                )
                logger.debug(
                    f"chat {id_chat} message {id_message} delete at {deleted_at} (sqlite)"
                )
                return True
            except Exception as e:
                logger.error(f"lazy delete schedule failed (sqlite): {e}")
                return False
        else:
            try:
                await self.client.delete_messages(id_chat, id_message)
                logger.info(f"chat {id_chat} message {id_message} deleted")
                return True
            except Exception as e:
                logger.error(f"chat {id_chat} message {id_message} delete failed: {e}")
                return False

    async def lazy_session(
        self, chat: int, msg: int, member: int, type: str, deleted_at: datetime
    ):
        rdb = await self.get_redis()
        if rdb:
            try:
                val = f"{chat}:{member}:{type}:{msg}"
                await rdb.zadd("lazy_sessions", {val: deleted_at.timestamp()})
                logger.debug(
                    f"chat {chat} message {msg} member {member} after {deleted_at} (redis)"
                )
                return
            except Exception as e:
                logger.error(f"lazy session schedule failed (redis): {e}")
        try:
            await database.execute(
                "insert into lazy_sessions(chat, msg, member, type, checkout_at) values(?,?,?,?,?)",
                (chat, msg, member, type, self._format_sqlite_datetime(deleted_at)),
            )
            logger.debug(
                f"chat {chat} message {msg} member {member} after {deleted_at} (sqlite)"
            )
        except Exception as e:
            logger.error(f"lazy session schedule failed (sqlite): {e}")

    async def lazy_session_delete(self, chat: int, member: int, type: str):
        rdb = await self.get_redis()
        if rdb:
            pattern = f"{chat}:{member}:{type}:*"
            async for member_val, _ in rdb.zscan_iter("lazy_sessions", match=pattern):
                await rdb.zrem("lazy_sessions", member_val)
            logger.debug(
                f"chat {chat} member {member} lazy session {type} is deleted (redis)"
            )
        # Always clean SQLite too, even if Redis was used, to avoid stale entries
        try:
            await database.execute(
                "delete from lazy_sessions where chat=? and member=? and type=?",
                (chat, member, type),
            )
            logger.debug(
                f"chat {chat} member {member} lazy session {type} is deleted (sqlite)"
            )
        except Exception as e:
            logger.error(f"lazy session delete failed (sqlite): {e}")

    async def send(self, chat: hints.EntityLike, msg: str, **kwargs):
        auto_deleted_at = kwargs.pop("auto_deleted_at", None)

        try:
            resp = await self.client.send_message(chat, msg, **kwargs)
            logger.info(f"message {resp.id} sent to {self.username(chat)}")
        except Exception as e:
            logger.exception(f"chat {chat} message {msg} send error: {e}")
            return False

        if auto_deleted_at is not None:
            await self.delete_message(chat, resp, auto_deleted_at)

        return True

    async def reply(self, msg, content: str, *args, **kwargs):
        auto_deleted_at = kwargs.pop("auto_deleted_at", None)
        if auto_deleted_at is None and len(args) > 0 and isinstance(args[0], datetime):
            auto_deleted_at = args[0]
            args = args[1:]

        try:
            resp = await msg.reply(content, *args, **kwargs)
            logger.info(f"replied to message {msg.id}")
        except Exception as e:
            logger.exception(f"reply error: {e}")
            return False

        if auto_deleted_at is not None:
            await self.delete_message(msg.chat_id, resp, auto_deleted_at)

        return True

    async def edit_text(self, chat: int, msg: int, content: str, *args, **kwargs):
        auto_deleted_at = kwargs.pop("auto_deleted_at", None)

        try:
            await self.client.edit_message(chat, msg, content, *args, **kwargs)
            logger.info(f"chat {chat} message {msg} edited")
        except Exception as e:
            logger.exception(f"edit error: {e}")
            return False

        if auto_deleted_at is not None:
            await self.delete_message(chat, msg, auto_deleted_at)

        return True

    async def notification(self, content: str):
        if "admin" in self.config["telegram"]:
            admin = self.config["telegram"]["admin"]
            await self.client.send_message(admin, content)

    def redis_configured(self) -> bool:
        """是否配置了 Redis（main.ini 中有 [redis] dsn）。"""
        return _redis_configured(self.config)

    async def get_redis(self):
        """
        获取 Redis 连接。未配置或连接失败时返回 None，调用方需做降级（如 SQLite）。
        """
        if not self.redis_configured():
            return None
        if self.rdb is None:
            redis_dsn = self.config["redis"]["dsn"]
            self.rdb = await aioredis.from_url(redis_dsn)
        return self.rdb

    async def require_redis(self):
        """
        获取 Redis 连接，供强依赖 Redis 的功能使用。
        未配置或不可用时抛出 RedisUnavailableError，由调用方统一处理（如提示用户或打日志后 return）。
        """
        rdb = await self.get_redis()
        if rdb is None:
            raise RedisUnavailableError("Redis 未配置或不可用")
        return rdb

    async def check_redis(self) -> bool:
        """
        启动时调用：尝试连接并 ping Redis，日志记录结果。不抛异常。
        """
        if not self.redis_configured():
            logger.debug("Redis 未配置，将使用 SQLite 等降级方案")
            return False
        try:
            rdb = await self.get_redis()
            if rdb:
                await rdb.ping()
                logger.info("Redis 连接正常 (startup check)")
                return True
        except Exception as e:
            logger.warning(f"Redis 启动检查失败: {e}")
        return False

    @staticmethod
    def _format_sqlite_datetime(dt: datetime) -> str:
        """
        格式化 datetime 为 SQLite UTC 字符串。
        若 dt 为 naive，视为 UTC 处理。
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    async def create_session(self) -> aiohttp.ClientSession:
        """
        创建或复用 HTTP 会话
        """
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.http_session
