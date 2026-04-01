"""
入群事件队列：限制成功后发布到 Redis，由独立消费者处理。
用于：周期内爆群/机器人浪潮统计、重复加入检测与处理。
"""

import json
from datetime import datetime, timezone
from typing import Optional, Any

from redis.asyncio import Redis
from loguru import logger

from manager import manager

# Redis 入群队列 List key（LPUSH / BRPOP）
MEMBER_JOIN_QUEUE = "member_join_queue"

# 重复加入：按用户维度的近期入群记录 Sorted Set，key = recent_joins:chat:{chat_id}:user:{user_id}，score=ts
RECENT_JOINS_USER_PREFIX = "recent_joins:chat:"
RECENT_JOINS_USER_SUFFIX = ":user:"

# 重复加入检测：时间窗口（秒）、阈值（同一用户同群在窗口内加入次数）、动作
REPEAT_JOIN_WINDOW_SECONDS = 10 * 60  # 10 分钟
REPEAT_JOIN_THRESHOLD = 2  # >=2 次视为重复加入
REPEAT_JOIN_ACTION = "log"  # log | kick | ban

# 全局入群计数（可选告警）：key 为 member_join_global_count，Sorted Set score=ts，用于统计全平台短时入群量
GLOBAL_JOIN_COUNT_KEY = "member_join_global_count"
GLOBAL_JOIN_ALERT_SENT_KEY = "member_join_global_alert_sent"  # 同一窗口内只告警一次
GLOBAL_JOIN_WINDOW = 5 * 60  # 5 分钟
GLOBAL_JOIN_ALERT_THRESHOLD = 200  # 5 分钟内全平台入群超过此数可告警（可选）


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


async def publish_join_event(
    rdb: Redis,
    chat_id: int,
    user_id: int,
    ts: Optional[float] = None,
    checker_type: str = "",
    username: Optional[str] = None,
    full_name: Optional[str] = None,
) -> bool:
    """
    限制成功后将入群事件写入 Redis 队列，供消费者统计与重复加入处理。
    """
    try:
        ts = ts or _now_ts()
        payload = {
            "chat_id": chat_id,
            "user_id": user_id,
            "ts": ts,
            "checker_type": checker_type or "ban",
            "username": username or "",
            "full_name": full_name or "",
        }
        await rdb.lpush(MEMBER_JOIN_QUEUE, json.dumps(payload))
        return True
    except Exception as e:
        logger.warning(f"入群事件入队失败 chat_id={chat_id} user_id={user_id} err={e}")
        return False


async def _handle_repeated_join(rdb: Redis, chat_id: int, user_id: int, ts: float, count: int) -> None:
    """重复加入时的动作：log / kick / ban。"""
    action = REPEAT_JOIN_ACTION
    logger.warning(
        f"重复加入检测 chat_id={chat_id} user_id={user_id} 窗口内次数={count} 动作={action}"
    )
    if action == "kick":
        try:
            await manager.client.edit_permissions(chat_id, user_id, view_messages=False)
            logger.info(f"重复加入已踢出 chat_id={chat_id} user_id={user_id}")
        except Exception as e:
            logger.error(f"重复加入踢出失败 chat_id={chat_id} user_id={user_id} err={e}")
    elif action == "ban":
        try:
            from datetime import timedelta
            from .config import DEFAULT_BAN_DAYS
            await manager.client.edit_permissions(
                chat_id, user_id,
                view_messages=False,
                until_date=timedelta(days=DEFAULT_BAN_DAYS),
            )
            logger.info(f"重复加入已封禁 chat_id={chat_id} user_id={user_id} {DEFAULT_BAN_DAYS}天")
        except Exception as e:
            logger.error(f"重复加入封禁失败 chat_id={chat_id} user_id={user_id} err={e}")


async def _process_one_join_event(rdb: Redis, payload: dict) -> None:
    """处理单条入群事件：更新近期入群、重复加入检测、可选全局统计。"""
    chat_id = int(payload["chat_id"])
    user_id = int(payload["user_id"])
    ts = float(payload["ts"])

    # 1) 重复加入：按用户记录近期入群次数
    user_key = f"{RECENT_JOINS_USER_PREFIX}{chat_id}{RECENT_JOINS_USER_SUFFIX}{user_id}"
    await rdb.zadd(user_key, {str(ts): ts})
    await rdb.zremrangebyscore(user_key, 0, ts - REPEAT_JOIN_WINDOW_SECONDS)
    await rdb.expire(user_key, REPEAT_JOIN_WINDOW_SECONDS + 60)
    count = await rdb.zcard(user_key)
    if count >= REPEAT_JOIN_THRESHOLD:
        await _handle_repeated_join(rdb, chat_id, user_id, ts, count)

    # 2) 可选：全局入群计数（用于浪潮告警，同一窗口内只告警一次）
    try:
        await rdb.zadd(GLOBAL_JOIN_COUNT_KEY, {f"{chat_id}:{user_id}:{ts}": ts})
        await rdb.zremrangebyscore(GLOBAL_JOIN_COUNT_KEY, 0, ts - GLOBAL_JOIN_WINDOW)
        await rdb.expire(GLOBAL_JOIN_COUNT_KEY, GLOBAL_JOIN_WINDOW + 60)
        global_count = await rdb.zcard(GLOBAL_JOIN_COUNT_KEY)
        if global_count >= GLOBAL_JOIN_ALERT_THRESHOLD:
            alert_key = GLOBAL_JOIN_ALERT_SENT_KEY
            if await rdb.set(alert_key, "1", nx=True, ex=GLOBAL_JOIN_WINDOW):
                logger.warning(f"全平台入群浪潮 窗口={GLOBAL_JOIN_WINDOW}s 入群数={global_count}")
                await manager.notification(
                    f"⚠️ 入群浪潮告警：过去 {GLOBAL_JOIN_WINDOW // 60} 分钟内全平台入群 {global_count} 次"
                )
    except Exception as e:
        logger.debug(f"全局入群统计跳过 err={e}")


async def process_join_events(rdb: Redis, block_seconds: float = 2.0) -> int:
    """
    从 Redis 队列中消费入群事件并处理。返回本轮处理条数。
    应在独立协程中循环调用（如 worker_loop 中）。
    """
    processed = 0
    try:
        # BRPOP 阻塞 block_seconds 秒，一次取一条
        result = await rdb.brpop(MEMBER_JOIN_QUEUE, timeout=int(block_seconds) or 1)
        if not result:
            return 0
        _key, raw = result
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"入群事件 JSON 解析失败 raw={raw!r} err={e}")
            return 1
        await _process_one_join_event(rdb, payload)
        processed += 1
        # 本轮继续非阻塞取出剩余若干条，避免积压
        for _ in range(99):
            raw = await rdb.rpop(MEMBER_JOIN_QUEUE)
            if raw is None:
                break
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
                await _process_one_join_event(rdb, payload)
                processed += 1
            except Exception as e:
                logger.error(f"入群事件处理失败 raw={raw!r} err={e}")
    except Exception as e:
        logger.error(f"process_join_events error: {e}")
    return processed
