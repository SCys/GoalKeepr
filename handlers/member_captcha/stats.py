"""
验证统计计数器模块
Silent stats counters — never raises, never blocks more than 1s per Redis call.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

STATS_KEY = "stats:captcha"

# Fields in the stats hash
FIELD_GROUP_JOINS = "group_joins"
FIELD_VERIFICATIONS = "verifications"
FIELD_SUCCESS = "success"
FIELD_FAILED = "failed"


async def _safe_hincrby(rdb, key, field, amount=1):
    """HINCRBY with 1s timeout, silent on any error."""
    try:
        await asyncio.wait_for(rdb.hincrby(key, field, amount), timeout=1)
    except asyncio.TimeoutError:
        logger.warning("stats hincrby 超时 (%s:%s)", key, field)
    except Exception as exc:
        logger.warning("stats hincrby 失败 (%s:%s): %s", key, field, exc)


async def _safe_sadd(rdb, key, member):
    """SADD with 1s timeout, silent on any error."""
    try:
        await asyncio.wait_for(rdb.sadd(key, member), timeout=1)
    except asyncio.TimeoutError:
        logger.warning("stats sadd 超时 (%s)", key)
    except Exception as exc:
        logger.warning("stats sadd 失败 (%s): %s", key, exc)


async def stats_incr(rdb, field, chat_id=None, user_id=None):
    """
    递增统计计数器（全局 + 按群），遇错静默打日志。
    每条 Redis 命令独立超时控制（1s），一个失败不影响其他。
    """
    if not rdb:
        return

    await _safe_hincrby(rdb, STATS_KEY, field)
    if chat_id:
        await _safe_hincrby(rdb, f"{STATS_KEY}:{chat_id}", field)
    if user_id and field in (FIELD_GROUP_JOINS, FIELD_SUCCESS):
        await _safe_sadd(rdb, f"{STATS_KEY}:persons", str(user_id))
        if chat_id:
            await _safe_sadd(rdb, f"{STATS_KEY}:{chat_id}:persons", str(user_id))
