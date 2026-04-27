"""
成员验证会话管理模块
Member captcha session management module

Redis Key: chat_captcha-{chat_id}-{user_id}  (Hash)
Dedup Key: chat_captcha-dedup-{chat_id}-{user_id}  (String, SETNX)
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple

from orjson import dumps, loads
from loguru import logger

from manager import manager
from .config import (
    CAPTCHA_REDIS_KEY_PREFIX,
    CAPTCHA_TTL_DEFAULT,
    CAPTCHA_TTL_EXTENDED,
    CAPTCHA_JOIN_THRESHOLD_KICK,
    CAPTCHA_JOIN_THRESHOLD_RESET,
    CAPTCHA_DEDUP_TTL,
)


class CaptchaSession:
    """
    入群验证频率控制会话

    Redis Hash 字段:
      join_count: str      — 当前 TTL 窗口内入群次数
      first_join_ts: str   — 窗口内首次入群时间 (ISO)
      last_join_ts: str    — 最近入群时间 (ISO)
      last_cost: str       — 上次验证耗时(秒)
      last_icon: str       — 上次正确图标(emoji)
      last_answer: str     — 上次正确答案(图标名称 key)
      last_options: str    — 上次选项列表 (JSON)
      total_joins: str     — 总入群次数(跨窗口累计)
      state: str           — normal / throttled / blocked
      chat_id: str
      user_id: str
    """

    # ------------------------------------------------------------------
    # Key 构建
    # ------------------------------------------------------------------

    @staticmethod
    def make_key(chat_id: int, user_id: int) -> str:
        """构建 Redis Hash key"""
        return f"{CAPTCHA_REDIS_KEY_PREFIX}-{chat_id}-{user_id}"

    @staticmethod
    def make_dedup_key(chat_id: int, user_id: int) -> str:
        """构建去重锁 key"""
        return f"{CAPTCHA_REDIS_KEY_PREFIX}-dedup-{chat_id}-{user_id}"

    # ------------------------------------------------------------------
    # 核心：入群频率检查 + 去重
    # ------------------------------------------------------------------

    @staticmethod
    async def check_and_record(
        chat_id: int, user_id: int, now: Optional[datetime] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        检查入群频率并记录本次入群。

        返回:
          (should_proceed, session_dict)
            - should_proceed=True  → 正常走验证流程
            - should_proceed=False → 应 Kick（频率过高）或重复事件

        去重逻辑:
          用 SETNX 原子锁防止同一事件被并发重复处理。
          锁 TTL=10s，足够覆盖单次事件处理周期。
        """
        if now is None:
            now = datetime.now(timezone.utc)

        rdb = await manager.get_redis()
        if not rdb:
            # Redis 不可用，降级：总是放行
            logger.warning("Redis 不可用，CaptchaSession 降级放行")
            return True, {}

        session_key = CaptchaSession.make_key(chat_id, user_id)
        dedup_key = CaptchaSession.make_dedup_key(chat_id, user_id)

        # 1) 去重锁：SETNX 原子操作
        acquired = await rdb.set(dedup_key, "1", nx=True, ex=CAPTCHA_DEDUP_TTL)
        if not acquired:
            logger.debug(f"去重锁命中，跳过重复事件 chat={chat_id} user={user_id}")
            return False, {"state": "duplicate"}

        # 2) 读取已有 session
        existing = await rdb.hgetall(session_key)
        # redis-py 返回 dict[bytes, bytes]，转成 dict[str, str]
        data: Dict[str, str] = {}
        if existing:
            data = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                    for k, v in existing.items()}

        now_iso = now.isoformat()
        is_new = len(data) == 0

        if is_new:
            # 首次入群
            data = {
                "join_count": "1",
                "first_join_ts": now_iso,
                "last_join_ts": now_iso,
                "last_cost": "0",
                "last_icon": "",
                "last_answer": "",
                "last_options": "",
                "total_joins": "1",
                "state": "normal",
                "chat_id": str(chat_id),
                "user_id": str(user_id),
            }
            await rdb.hset(session_key, mapping=data)
            await rdb.expire(session_key, CAPTCHA_TTL_DEFAULT)
            logger.info(f"CaptchaSession 新建 chat={chat_id} user={user_id} TTL={CAPTCHA_TTL_DEFAULT}s")
            return True, data

        # 3) 已有记录：更新计数
        join_count = int(data.get("join_count", "0")) + 1
        total_joins = int(data.get("total_joins", "0")) + 1
        current_state = data.get("state", "normal")
        new_state = current_state
        new_ttl = CAPTCHA_TTL_DEFAULT

        if join_count >= CAPTCHA_JOIN_THRESHOLD_KICK:
            # 频率过高 → throttled
            new_state = "throttled"
            new_ttl = CAPTCHA_TTL_EXTENDED
            logger.warning(
                f"CaptchaSession 频率触发 chat={chat_id} user={user_id} "
                f"join_count={join_count} threshold={CAPTCHA_JOIN_THRESHOLD_KICK} → throttled"
            )
        elif current_state == "throttled" and join_count <= CAPTCHA_JOIN_THRESHOLD_RESET:
            # 频率降回正常
            new_state = "normal"
            new_ttl = CAPTCHA_TTL_DEFAULT
            logger.info(
                f"CaptchaSession 频率恢复 chat={chat_id} user={user_id} "
                f"join_count={join_count} → normal"
            )

        # 4) 写回
        data["join_count"] = str(join_count)
        data["total_joins"] = str(total_joins)
        data["last_join_ts"] = now_iso
        data["state"] = new_state

        await rdb.hset(session_key, mapping={
            "join_count": str(join_count),
            "total_joins": str(total_joins),
            "last_join_ts": now_iso,
            "state": new_state,
        })
        await rdb.expire(session_key, new_ttl)

        if new_state == "throttled":
            logger.info(
                f"CaptchaSession throttled chat={chat_id} user={user_id} "
                f"join_count={join_count} TTL={new_ttl}s → 应 Kick"
            )
            return False, data

        logger.debug(
            f"CaptchaSession 放行 chat={chat_id} user={user_id} "
            f"join_count={join_count} state={new_state}"
        )
        return True, data

    # ------------------------------------------------------------------
    # 记录验证码答案
    # ------------------------------------------------------------------

    @staticmethod
    async def record_answer(
        chat_id: int,
        user_id: int,
        icon: str,
        answer: str,
        options: str,
    ) -> None:
        """在发送验证消息后，记录图标、正确答案、选项列表"""
        rdb = await manager.get_redis()
        if not rdb:
            return

        session_key = CaptchaSession.make_key(chat_id, user_id)
        exists = await rdb.exists(session_key)
        if not exists:
            logger.warning(f"record_answer 时 session 不存在 chat={chat_id} user={user_id}")
            return

        await rdb.hset(session_key, mapping={
            "last_icon": icon,
            "last_answer": answer,
            "last_options": options,
        })
        logger.debug(f"CaptchaSession 记录答案 chat={chat_id} user={user_id} icon={icon} answer={answer}")

    # ------------------------------------------------------------------
    # 记录验证耗时（用户通过验证后）
    # ------------------------------------------------------------------

    @staticmethod
    async def record_cost(chat_id: int, user_id: int, cost_seconds: float) -> None:
        """记录用户通过验证的耗时"""
        rdb = await manager.get_redis()
        if not rdb:
            return

        session_key = CaptchaSession.make_key(chat_id, user_id)
        await rdb.hset(session_key, "last_cost", str(cost_seconds))
        logger.debug(f"CaptchaSession 记录耗时 chat={chat_id} user={user_id} cost={cost_seconds:.2f}s")

    # ------------------------------------------------------------------
    # 读取 session
    # ------------------------------------------------------------------

    @staticmethod
    async def get(chat_id: int, user_id: int) -> Optional[Dict[str, str]]:
        """读取完整 session 数据"""
        rdb = await manager.get_redis()
        if not rdb:
            return None

        session_key = CaptchaSession.make_key(chat_id, user_id)
        existing = await rdb.hgetall(session_key)
        if not existing:
            return None

        return {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in existing.items()}

    # ------------------------------------------------------------------
    # 删除 session（用户被管理员接受/拒绝后清理）
    # ------------------------------------------------------------------

    @staticmethod
    async def delete(chat_id: int, user_id: int) -> None:
        """删除 session"""
        rdb = await manager.get_redis()
        if not rdb:
            return

        session_key = CaptchaSession.make_key(chat_id, user_id)
        await rdb.delete(session_key)
        logger.debug(f"CaptchaSession 删除 chat={chat_id} user={user_id}")


# ------------------------------------------------------------------
# 保留旧 Session 类以兼容 security.py / validators.py 中仍引用的地方
# 逐步迁移到 CaptchaSession
# ------------------------------------------------------------------

class Session:
    """
    旧版 Session — 保留兼容，内部字段不变。
    新代码应优先使用 CaptchaSession。
    """
    id: str
    chat: str
    chat_id: int
    member: str
    member_id: int
    member_username: Optional[str]
    member_bio: Optional[str]
    ts_create: datetime
    ts_update: datetime
    cost_captcha: float
    accepted: bool
    timeout: bool
    banned: bool

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    async def save(self):
        rdb = await manager.get_redis()
        if not rdb:
            return
        self.cost_captcha = (self.ts_update - self.ts_create).total_seconds()
        TTL_SESSION = 60 * 60 * 24 * 7
        await rdb.set(self.id, dumps(self.__dict__), TTL_SESSION)

    @staticmethod
    async def create(chat, user, now: datetime) -> "Session":
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
        if rdb:
            if await rdb.exists(session.id):
                old_data = loads(await rdb.get(session.id))
                old_data["ts_update"] = now
                ts_create_raw = old_data["ts_create"]
                ts_create = datetime.fromisoformat(ts_create_raw) if isinstance(ts_create_raw, str) else ts_create_raw
                old_data["cost_captcha"] = (now - ts_create).total_seconds()
            TTL_SESSION = 60 * 60 * 24 * 7
            await rdb.set(session.id, dumps(session.__dict__), TTL_SESSION)
        return session
