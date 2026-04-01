"""
安全模式：入群速率计数器与待审核列表
当周期内入群人数超过阈值时进入安全模式，新成员静默进入待审核列表，由管理员通过/拒绝。
"""

from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional

from redis.asyncio import Redis
from loguru import logger

from manager import manager
from manager.group import settings_get

from .config import MEMBER_CHECK_WAIT_TIME

# Redis key 前缀
JOIN_COUNTER_KEY = "member_join_count:"
SECURITY_MODE_KEY = "group:security_mode:"
NEW_MEMBERS_KEY = "group:new_members:"

# 周期窗口（秒）：3秒 / 5分钟 / 10分钟 / 30分钟
WINDOW_3S = MEMBER_CHECK_WAIT_TIME
WINDOW_5M = 5 * 60
WINDOW_10M = 10 * 60
WINDOW_30M = 30 * 60

# 安全模式待审核超时（分钟），超时未通过则踢出
SECURITY_MODE_PENDING_MINUTES = 30

# 默认触发安全模式的阈值（某窗口内入群人数超过此值即进入安全模式）
DEFAULT_SECURITY_MODE_THRESHOLD = 10

# 群设置中可选的窗口键名与秒数映射
SECURITY_WINDOW_OPTIONS = {
    "3": WINDOW_3S,
    "300": WINDOW_5M,
    "600": WINDOW_10M,
    "1800": WINDOW_30M,
}


async def _get_threshold_and_window(rdb: Redis, chat_id: int) -> Tuple[int, int]:
    """从群设置读取安全模式阈值和窗口（秒）。"""
    threshold = DEFAULT_SECURITY_MODE_THRESHOLD
    window = WINDOW_5M
    try:
        t = await settings_get(rdb, chat_id, "security_mode_join_threshold", str(DEFAULT_SECURITY_MODE_THRESHOLD))
        if t is not None:
            threshold = int(t) if isinstance(t, str) else int(t.get("value", DEFAULT_SECURITY_MODE_THRESHOLD))
    except (ValueError, TypeError):
        pass
    try:
        w = await settings_get(rdb, chat_id, "security_mode_window_seconds", "300")
        if w is not None:
            ws = w if isinstance(w, str) else str(getattr(w, "value", w) or "300")
            window = SECURITY_WINDOW_OPTIONS.get(ws, WINDOW_5M)
    except (ValueError, TypeError):
        pass
    return threshold, window


async def incr_join_counter(rdb: Redis, chat_id: int, user_id: int) -> Tuple[int, int, int, int]:
    """
    记录一次入群并返回各窗口内的计数。
    使用 sorted set，score 为时间戳，member 为 user_id:timestamp 避免重复。
    """
    key = f"{JOIN_COUNTER_KEY}{chat_id}"
    now = datetime.now(timezone.utc).timestamp()
    member = f"{user_id}:{now}"
    await rdb.zadd(key, {member: now})
    # 只保留最近 30 分钟，避免 key 无限增长
    await rdb.zremrangebyscore(key, 0, now - WINDOW_30M - 60)
    # 可选：设置 key 过期，防止长期不用的群占用内存
    await rdb.expire(key, WINDOW_30M + 3600)

    count_3s = await rdb.zcount(key, now - WINDOW_3S, now + 1)
    count_5m = await rdb.zcount(key, now - WINDOW_5M, now + 1)
    count_10m = await rdb.zcount(key, now - WINDOW_10M, now + 1)
    count_30m = await rdb.zcount(key, now - WINDOW_30M, now + 1)
    return int(count_3s), int(count_5m), int(count_10m), int(count_30m)


async def should_enter_security_mode(rdb: Redis, chat_id: int) -> bool:
    """
    根据当前各窗口计数与群设置阈值判断是否应进入安全模式。
    任一窗口计数 >= 阈值则返回 True。
    """
    key = f"{JOIN_COUNTER_KEY}{chat_id}"
    now = datetime.now(timezone.utc).timestamp()
    threshold, window_sec = await _get_threshold_and_window(rdb, chat_id)

    # 按配置的窗口取计数
    if window_sec == WINDOW_3S:
        count = await rdb.zcount(key, now - WINDOW_3S, now + 1)
    elif window_sec == WINDOW_10M:
        count = await rdb.zcount(key, now - WINDOW_10M, now + 1)
    elif window_sec == WINDOW_30M:
        count = await rdb.zcount(key, now - WINDOW_30M, now + 1)
    else:
        count = await rdb.zcount(key, now - WINDOW_5M, now + 1)
    return int(count) >= threshold


async def is_security_mode(rdb: Redis, chat_id: int) -> bool:
    """当前群是否处于安全模式。"""
    key = f"{SECURITY_MODE_KEY}{chat_id}"
    val = await rdb.get(key)
    return val is not None and (val == b"1" or val == "1")


async def set_security_mode(rdb: Redis, chat_id: int, ttl_seconds: int = 0) -> None:
    """进入安全模式。ttl_seconds=0 表示不自动过期，需管理员手动解除。"""
    key = f"{SECURITY_MODE_KEY}{chat_id}"
    if ttl_seconds > 0:
        await rdb.setex(key, ttl_seconds, "1")
    else:
        await rdb.set(key, "1")
    logger.info(f"chat_id={chat_id} 进入安全模式 (ttl={ttl_seconds}s)")


async def get_auto_exit_minutes(rdb: Redis, chat_id: int) -> int:
    """从群设置读取安全模式自动解除时长（分钟）。0 表示仅手动解除。"""
    try:
        v = await settings_get(rdb, chat_id, "security_mode_auto_exit_minutes", "30")
        if v is None:
            return 30
        n = int(v) if isinstance(v, str) else int(getattr(v, "value", v) or 30)
        return n if n >= 0 else 0
    except (ValueError, TypeError):
        return 30


async def clear_security_mode(rdb: Redis, chat_id: int) -> None:
    """解除安全模式。"""
    key = f"{SECURITY_MODE_KEY}{chat_id}"
    await rdb.delete(key)
    logger.info(f"chat_id={chat_id} 解除安全模式")


async def add_to_new_members_list(rdb: Redis, chat_id: int, user_id: int, join_ts: float) -> None:
    """将新成员加入待审核列表（sorted set，score=join_ts）。"""
    key = f"{NEW_MEMBERS_KEY}{chat_id}"
    await rdb.zadd(key, {str(user_id): join_ts})
    await rdb.expire(key, 3600 * 2)  # 列表 key 保留 2 小时


async def remove_from_new_members_list(rdb: Redis, chat_id: int, user_id: int) -> None:
    """从待审核列表移除（管理员通过/拒绝时调用）。"""
    key = f"{NEW_MEMBERS_KEY}{chat_id}"
    await rdb.zrem(key, str(user_id))


async def is_in_new_members_list(rdb: Redis, chat_id: int, user_id: int) -> bool:
    """是否仍在待审核列表中（未超时且未被管理员处理）。"""
    key = f"{NEW_MEMBERS_KEY}{chat_id}"
    score = await rdb.zscore(key, str(user_id))
    return score is not None
