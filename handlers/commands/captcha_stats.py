import asyncio

from telethon import events
from manager import manager
from ..member_captcha.stats import STATS_KEY, FIELD_GROUP_JOINS, FIELD_VERIFICATIONS, FIELD_SUCCESS, FIELD_FAILED

logger = manager.logger


@manager.register("message", pattern=r"(?i)^/captcha_stats(\s+\d+)?$")
async def captcha_stats(event: events.NewMessage.Event):
    """查看验证统计。用法: /captcha_stats [群ID]"""
    import re

    text = event.raw_text.strip()
    m = re.match(r"(?i)^/captcha_stats(?:\s+(\d+))?\s*$", text)
    group_id = int(m.group(1)) if m and m.group(1) else None

    rdb = await manager.get_redis()
    if not rdb:
        await event.reply("Redis 未配置，无法获取统计。")
        return

    try:
        if group_id:
            key = f"{STATS_KEY}:{group_id}"
            persons_key = f"{STATS_KEY}:{group_id}:persons"
        else:
            key = STATS_KEY
            persons_key = f"{STATS_KEY}:persons"

        raw, persons_count = await asyncio.wait_for(
            asyncio.gather(rdb.hgetall(key), rdb.scard(persons_key)),
            timeout=3,
        )

        joins = int(raw.get(FIELD_GROUP_JOINS.encode(), b"0"))
        verifications = int(raw.get(FIELD_VERIFICATIONS.encode(), b"0"))
        success = int(raw.get(FIELD_SUCCESS.encode(), b"0"))
        failed = int(raw.get(FIELD_FAILED.encode(), b"0"))

        total = success + failed
        rate = f"{success / total * 100:.1f}%" if total > 0 else "N/A"

        lines = [
            f"群 ID: {group_id}" if group_id else "全局统计",
            f"入群人次: {joins}",
            f"验证次数: {verifications}",
            f"验证成功: {success}",
            f"验证失败: {failed}",
            f"唯一用户: {persons_count}",
            f"成功率: {rate}",
        ]
        await event.reply("\n".join(lines))
    except asyncio.TimeoutError:
        await event.reply("获取统计超时，请稍后重试。")
    except Exception as e:
        logger.warning("captcha_stats 获取失败: %s", e)
        await event.reply("获取统计失败，请稍后重试。")
