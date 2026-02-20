from datetime import datetime
from orjson import dumps, loads
from typing import Optional, Any
from telethon import types
from manager import manager

# 7天缓冲会话TTL, unit: seconds
TTL_SESSION = 60 * 60 * 24 * 7

class Session:
    id: str  # member_captcha:chat_id:member_id
    chat: str
    chat_id: int
    member: str
    member_id: int
    member_username: Optional[str]
    member_bio: Optional[str]
    ts_create: datetime
    ts_update: datetime
    cost_captcha: float
    # flags
    accepted: bool
    timeout: bool
    banned: bool

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    async def save(self):
        rdb = await manager.get_redis()
        if not rdb:  # redis not ready
            return

        self.cost_captcha = (self.ts_update - self.ts_create).total_seconds()

        await rdb.set(self.id, dumps(self.__dict__), TTL_SESSION)

    @staticmethod
    async def create(chat: types.Chat, user: types.User, now: datetime) -> "Session":
        """member 需有 .user (id, username, first_name, last_name)。event 仅用于兼容，ts_create 用 now。"""
        session = Session(**{
            "id": f"member_captcha:{chat.id}:{user.id}",
            "chat": getattr(chat, "title", str(chat.id)),
            "chat_id": chat.id,
            "member": f"{user.first_name} {user.last_name}".strip(),
            "member_id": user.id,
            "member_username": user.username,
            "member_bio": None,
            "ts_create": now,
            "ts_update": now,
            "cost_captcha": 0,
            "accepted": False,
            "timeout": False,
            "banned": False,
        })

        rdb = await manager.get_redis()
        if rdb:  # redis not ready
            if await rdb.exists(session.id):
                old_data = loads(await rdb.get(session.id))
                old_data["ts_update"] = now
                # orjson 序列化的 datetime 可能带微秒，用 fromisoformat 解析
                ts_create_raw = old_data["ts_create"]
                ts_create = datetime.fromisoformat(ts_create_raw) if isinstance(ts_create_raw, str) else ts_create_raw
                old_data["cost_captcha"] = (now - ts_create).total_seconds()

            await rdb.set(session.id, dumps(session.__dict__), TTL_SESSION)
        return session
