from datetime import datetime
from orjson import dumps, loads
from typing import Optional, Union

from aiogram import types

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
    async def get(
        chat: Optional[types.Chat],
        member: Union[types.ChatMemberMember, types.ChatMemberRestricted],
        event: types.ChatMemberUpdated,
        now: datetime,
    ):
        if not chat:
            return
        
        # 创建会话
        session = Session(**{
            "id": f"member_captcha:{chat.id}:{member.user.id}",
            "chat": chat.title,
            "chat_id": chat.id,
            "member": member.user.full_name,
            "member_id": member.user.id,
            "member_username": member.user.username,
            "member_bio": None,
            "ts_create": event.date,
            "ts_update": now,
            "cost_captcha": 0,  # uint: seconds
            # flags
            "accepted": False,
            "timeout": False,
            "banned": False,
        })

        rdb = await manager.get_redis()
        if rdb:  # redis not ready
            if await rdb.exists(session.id):
                old_data = loads(await rdb.get(session.id))
                old_data["ts_update"] = now
                ts_create = datetime.fromtimestamp(old_data["ts_create"])
                old_data["cost_captcha"] = (now - ts_create).total_seconds()

            await rdb.set(session.id, dumps(session.__dict__), TTL_SESSION)

        return session
