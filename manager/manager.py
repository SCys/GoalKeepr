import os
import os.path
import sys
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Optional, Union, Tuple, Any
from urllib.parse import urlparse

import aiohttp
import database
import redis.asyncio as aioredis
import loguru
from telethon import Button, TelegramClient, events, types, hints
from bs4 import BeautifulSoup, Tag

from .settings import SETTINGS_TEMPLATE

logger = loguru.logger


@dataclass
class UserInfo:
    """统一的用户信息（屏蔽底层库的 User 类型）。"""

    id: int
    first_name: str = ""
    last_name: Optional[str] = None
    username: Optional[str] = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name or ''}".strip()


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
            logger.warning(f"telegram proxy 仅支持 socks5/socks4/http，当前为 {scheme}，将按 socks5 使用")
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

    # optional website admin server
    web_server: Any = None

    _redis_warned = False

    logger = logger

    def setup(self, config_path: Optional[str] = None):
        self.load_config(config_path)

        self.setup_logger()
        self.is_running = True

        token = self.config["telegram"]["token"]
        api_id = self.config["telegram"].get("api_id")
        api_hash = self.config["telegram"].get("api_hash")

        if not token:
            logger.error("telegram token is missing")
            sys.exit(1)
            
        if not api_id or not api_hash:
            logger.error("telegram api_id 或 api_hash 未配置，请在 main.ini [telegram] 中填写（从 https://my.telegram.org 获取）")
            sys.exit(1)

        # 解析代理（可选），格式如 socks5://127.0.0.1:1080 或 socks5://user:pass@host:port
        proxy = _parse_proxy(self.config["telegram"].get("proxy", ""))

        # Data dir for session file (and DB via database module). Allows separating src/ from data/.
        data_dir = os.environ.get("GOALKEEPR_DATA_DIR", "./data")
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        session_path = os.path.join(data_dir, "bot")

        # Initialize Telethon Client. Use path in data_dir so session lives with DB.
        self.client = TelegramClient(
            session_path,
            int(api_id) if api_id else 0,
            api_hash or "",
            proxy=proxy,
        )

        if proxy:
            logger.info(f"telethon client is setup (with proxy), session in {session_path}")
        else:
            logger.info(f"telethon client is setup, session in {session_path}")

        self.setup_handlers()

    def load_config(self, config_path: Optional[str] = None):
        """加载配置文件。支持通过 GOALKEEPR_CONFIG 环境变量或参数指定路径，
        便于 src/ 与 main.ini 分离部署（systemd 等场景）。
        """
        config = self.config

        # 设置默认模板
        for key, section in SETTINGS_TEMPLATE.items():
            config.setdefault(key, section)

        if config_path is None:
            config_path = os.environ.get("GOALKEEPR_CONFIG") or "main.ini"

        # 从文件读取
        if os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config.read_file(f)

                logger.info(f"settings is loaded from {config_path}")
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
        pass

    def register(self, type_name, *args, **kwargs):
        """
        Decorator to register handlers.
        type_name: "message", "callback_query", "chat_member"
        kwargs: passed to event filter (e.g. pattern, outgoing)
        """

        def wrapper(func):
            event_cls = None
            if type_name == "raw":
                event_cls = events.Raw
            elif type_name == "message":
                event_cls = events.NewMessage
            elif type_name == "callback_query":
                event_cls = events.CallbackQuery
            elif type_name == "chat_member":
                event_cls = events.ChatAction

            if event_cls:
                self.handlers.append((func, event_cls, args, kwargs))
                logger.info(f"registered {func.__name__} for {type_name}")
            else:
                logger.warning(f"Unknown event type {type_name}")

            @wraps(func)
            async def _wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

            return _wrapper

        return wrapper
    
    def _apply_handlers(self):
        """Actually register handlers to client"""
        for func, event_cls, args, kwargs in self.handlers:
            self.client.add_event_handler(func, event_cls(*args, **kwargs))
            logger.info(f"handler {func.__name__} added to client")

    def register_event(self, type_name: str):
        """
        将函数添加到事件处理内 (Internal events like lazy_session)
        """

        def wrapper(func):
            self.events[type_name] = func

            @wraps(func)
            async def _wrapper(*args, **kwargs):
                # 必须 await 异步 handler，否则返回未调度的 coroutine
                return await func(*args, **kwargs)

            return _wrapper

        return wrapper

    async def start(self):
        self.is_running = True
        
        # Apply handlers before starting
        self._apply_handlers()

        token = self.config["telegram"]["token"]
        
        await self.client.start(bot_token=token)
        
        me = await self.client.get_me(input_peer=False)
        logger.info(f"bot started as {self.username(me)}")

        admin_raw = self.config["telegram"].get("admin", "").strip()
        if admin_raw.isdigit():
            admin = int(admin_raw)
            try:
                await self.send(admin, "bot is started")
            except Exception as e:
                logger.debug(f"admin notification failed: {e}")

        if self.config["web"].getboolean("enabled", False):
            from web_admin import AdminWebServer

            self.web_server = AdminWebServer(self, me.username or "")
            await self.web_server.start()

        await self.client.run_until_disconnected()

    async def stop(self):
        self.is_running = False
        if self.web_server is not None:
            await self.web_server.stop()
            self.web_server = None
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await database.close()
        await self.client.disconnect()

    def username(self, user: hints.EntityLike):
        """获取用户名"""
        if isinstance(user, UserInfo):
            return user.username or user.full_name or str(user.id)
        return user.username if isinstance(user, types.User) else user.title if isinstance(user, types.Chat) else getattr(user, "username", None) or str(user)

    async def is_admin(self, chat: Union[types.Chat, types.Channel, int], member: Union[types.User, int]):
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
            return not perms or perms.is_admin or perms.is_creator
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
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        try:
            proxy = self.config["telegram"].get("proxy", "")
            session = await self.create_session()
            async with session.get(url, headers=headers, timeout=15, proxy=proxy or None) as response:
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
        chat: Union[int, types.Chat],
        msg: Union[int, types.Message, None],
        deleted_at: Union[datetime, None] = None,
    ):
        if msg is None:
            return True

        # 解析真实 id：Channel/Chat/User 等 TL 对象统一取 .id
        id_chat = getattr(chat, "id", chat)
        id_message = getattr(msg, "id", msg)

        if id_message is None:
            return False

        # 防御：确保是 int，避免把 TL 对象 repr 写进存储
        try:
            id_chat = int(id_chat)
            id_message = int(id_message)
        except (TypeError, ValueError):
            logger.error(f"delete_message 收到非法 id: chat={chat!r} msg={msg!r}")
            return False

        if deleted_at is not None:
            rdb = await self.get_redis()
            if rdb:
                try:
                    await rdb.zadd(
                        "lazy_delete_messages", {f"{id_chat}:{id_message}": deleted_at.timestamp()}
                    )
                    logger.debug(f"chat {id_chat} message {id_message} delete at {deleted_at} (redis)")
                    return True
                except Exception as e:
                    logger.error(f"lazy delete schedule failed (redis): {e}")
                    self.rdb = None  # force re-validation on next use
            # fallback to sqlite (either no redis or redis op failed)
            try:
                await database.execute(
                    "insert into lazy_delete_messages(chat, msg, deleted_at) values(?,?,?)",
                    (id_chat, id_message, self._format_sqlite_datetime(deleted_at)),
                )
                logger.debug(f"chat {id_chat} message {id_message} delete at {deleted_at} (sqlite)")
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
                logger.debug(f"chat {chat} message {msg} member {member} after {deleted_at} (redis)")
                return
            except Exception as e:
                logger.error(f"lazy session schedule failed (redis): {e}")
                self.rdb = None  # force re-validation on next use
        # fallback
        try:
            await database.execute(
                "insert into lazy_sessions(chat, msg, member, type, checkout_at) values(?,?,?,?,?)",
                (chat, msg, member, type, self._format_sqlite_datetime(deleted_at)),
            )
            logger.debug(f"chat {chat} message {msg} member {member} after {deleted_at} (sqlite)")
        except Exception as e:
            logger.error(f"lazy session schedule failed (sqlite): {e}")

    async def lazy_session_delete(self, chat: int, member: int, type: str):
        rdb = await self.get_redis()
        if rdb:
            try:
                pattern = f"{chat}:{member}:{type}:*"
                async for member_val, _ in rdb.zscan_iter("lazy_sessions", match=pattern):
                    await rdb.zrem("lazy_sessions", member_val)
                logger.debug(f"chat {chat} member {member} lazy session {type} is deleted (redis)")
                return
            except Exception as e:
                logger.error(f"lazy session delete failed (redis): {e}")
                self.rdb = None  # force re-validation on next use
        # fallback
        try:
            await database.execute(
                "delete from lazy_sessions where chat=? and member=? and type=?",
                (chat, member, type),
            )
            logger.debug(f"chat {chat} member {member} lazy session {type} is deleted (sqlite)")
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
        admin = self.config["telegram"].get("admin", "").strip()
        if admin.isdigit():
            await self.client.send_message(admin, content)

    async def get_redis(self):
        if "redis" not in self.config:
            return None

        if self.rdb is None:
            redis_section = self.config["redis"]
            redis_dsn = redis_section.get("dsn", "") if hasattr(redis_section, "get") else str(redis_section)
            redis_dsn = (redis_dsn or "").strip()
            if not redis_dsn:
                return None
            try:
                client = aioredis.from_url(redis_dsn)
                await client.ping()
                self.rdb = client
            except Exception as e:
                if not self._redis_warned:
                    logger.warning(f"Redis configured but unreachable: {e}. Falling back to SQLite for sessions, lazy deletes, group settings, etc.")
                    self._redis_warned = True
                # leave self.rdb as None to allow retry on next get_redis call
                return None

        return self.rdb

    @staticmethod
    def _format_sqlite_datetime(dt: datetime) -> str:
        """
        格式化 datetime 为 SQLite 可比较的字符串
        """
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    async def create_session(self) -> aiohttp.ClientSession:
        """
        创建或复用 HTTP 会话
        """
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.http_session

    async def close_http_session(self) -> None:
        """关闭 HTTP 会话"""
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
            self.http_session = None
            logger.debug("http session closed")

    # ------------------------------------------------------------------
    # 统一 Telegram 操作接口（业务层只应调用以下方法，不直接使用 self.client）
    # 参数与返回值一律使用原生类型（int/str/datetime），屏蔽底层 TL 类型。
    # ------------------------------------------------------------------

    @staticmethod
    def inline_button(text: str, data):
        """构建内联回调按钮。data 为 str/bytes（超长请先 hash 缩短）。"""
        if isinstance(data, str):
            data = data.encode("utf-8")
        return Button.inline(text, data)

    @staticmethod
    def url_button(text: str, url: str):
        """构建内联 URL 按钮。"""
        return Button.url(text, url)

    async def send_text(
        self,
        chat_id: int,
        text: str,
        *,
        buttons: Optional[list] = None,
        parse_mode: Optional[str] = None,
        reply_to: Optional[int] = None,
        link_preview: bool = True,
    ) -> Optional[int]:
        """发送文本消息，成功返回 msg_id，失败返回 None。"""
        try:
            resp = await self.client.send_message(
                chat_id,
                text,
                buttons=buttons,
                parse_mode=parse_mode,
                reply_to=reply_to,
                link_preview=link_preview,
            )
            logger.info(f"chat {chat_id} message {resp.id} sent")
            return resp.id
        except Exception as e:
            logger.exception(f"chat {chat_id} send_text error: {e}")
            return None

    async def send_photo(
        self,
        chat_id: int,
        photo: bytes,
        *,
        caption: Optional[str] = None,
        buttons: Optional[list] = None,
        reply_to: Optional[int] = None,
    ) -> Optional[int]:
        """发送图片（bytes），成功返回 msg_id。"""
        try:
            resp = await self.client.send_file(
                chat_id, photo, caption=caption, buttons=buttons, reply_to=reply_to
            )
            logger.info(f"chat {chat_id} photo message {resp.id} sent")
            return resp.id
        except Exception as e:
            logger.exception(f"chat {chat_id} send_photo error: {e}")
            return None

    async def send_voice(
        self,
        chat_id: int,
        voice: bytes,
        *,
        caption: Optional[str] = None,
        reply_to: Optional[int] = None,
        silent: bool = False,
    ) -> Optional[int]:
        """发送语音（bytes，opus/ogg），成功返回 msg_id。"""
        try:
            resp = await self.client.send_file(
                chat_id, voice, voice_note=True, caption=caption, reply_to=reply_to, silent=silent
            )
            logger.info(f"chat {chat_id} voice message {resp.id} sent")
            return resp.id
        except Exception as e:
            logger.exception(f"chat {chat_id} send_voice error: {e}")
            return None

    async def download_media_bytes(self, msg: Any) -> Optional[bytes]:
        """下载消息中的媒体文件为 bytes，失败返回 None。"""
        try:
            return await self.client.download_media(msg, bytes)
        except Exception as e:
            logger.exception(f"download media error: {e}")
            return None

    async def get_user_info(self, user_id: int) -> Optional[UserInfo]:
        """按 id 获取用户信息（原生 UserInfo），失败返回 None。"""
        try:
            user = await self.client.get_entity(user_id)
        except Exception as e:
            logger.error(f"get_user_info {user_id} failed: {e}")
            return None
        if not isinstance(user, types.User):
            return None
        return UserInfo(
            id=user.id,
            first_name=user.first_name or "",
            last_name=user.last_name,
            username=user.username,
        )

    async def has_profile_photo(self, user: Any) -> Optional[bool]:
        """用户是否有公开头像。user 可以是 UserInfo / 底层 User / user_id。"""
        entity = user
        if isinstance(user, UserInfo) or isinstance(user, int):
            user_id = user.id if isinstance(user, UserInfo) else user
            try:
                entity = await self.client.get_entity(user_id)
            except Exception as e:
                logger.error(f"get entity {user_id} for profile photo failed: {e}")
                return None
        try:
            photos = await self.client.get_profile_photos(entity, limit=1)
            return bool(photos)
        except Exception as e:
            logger.exception(f"get profile photos error: {e}")
            return None

    # ---- 成员权限管理（业务语义，屏蔽底层黑名单/白名单差异）----

    async def mute_member(self, chat: Any, user: Any, until: Optional[timedelta] = None) -> bool:
        """全量禁言成员（不可发言/发媒体等）。until 为相对时长，None 表示直到手动解除。"""
        user_id = getattr(user, "id", user)
        try:
            await self.client.edit_permissions(
                chat,
                user_id,
                send_messages=False,
                send_media=False,
                send_stickers=False,
                send_gifs=False,
                send_games=False,
                send_inline=False,
                embed_link_previews=False,
                until_date=until,
            )
            return True
        except Exception as e:
            logger.error(f"failed to restrict permissions for member {user_id}: {e}")
            return False

    async def unmute_member(self, chat: Any, user: Any) -> bool:
        """恢复成员默认发言权限。"""
        user_id = getattr(user, "id", user)
        try:
            await self.client.edit_permissions(
                chat,
                user_id,
                send_messages=True,
                send_media=True,
                send_stickers=True,
                send_gifs=True,
                send_games=True,
                send_inline=True,
                embed_link_previews=True,
                until_date=None,
            )
            return True
        except Exception as e:
            logger.error(f"failed to restore permissions for member {user_id}: {e}")
            return False

    async def unban_member_full(self, chat: Any, user: Any) -> bool:
        """解除封禁并恢复全部权限（含 view_messages），用于 unban 场景。"""
        user_id = getattr(user, "id", user)
        try:
            await self.client.edit_permissions(
                chat,
                user_id,
                view_messages=True,
                send_messages=True,
                send_media=True,
                send_stickers=True,
                send_gifs=True,
                send_games=True,
                send_inline=True,
                embed_link_previews=True,
            )
            return True
        except Exception as e:
            logger.error(f"failed to unban member {user_id}: {e}")
            return False

    async def hide_member(self, chat: Any, user: Any, until: Optional[timedelta] = None) -> bool:
        """封禁成员（禁止查看消息/加入黑名单）。until 为相对时长，None 表示永久。"""
        user_id = getattr(user, "id", user)
        try:
            await self.client.edit_permissions(
                chat, user_id, view_messages=False, until_date=until
            )
            return True
        except Exception as e:
            logger.error(f"failed to ban member {user_id}: {e}")
            return False

    async def kick_member(self, chat: Any, user: Any) -> bool:
        """将成员从群组移除（软踢）。"""
        user_id = getattr(user, "id", user)
        try:
            await self.client.kick_participant(chat, user_id)
            return True
        except Exception as e:
            logger.warning(f"kick_participant {user_id} failed: {e}")
            return False
