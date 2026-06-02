import asyncio

from telethon import events
from manager import manager
from ..member_captcha.stats import STATS_KEY, FIELD_GROUP_JOINS, FIELD_VERIFICATIONS, FIELD_SUCCESS, FIELD_FAILED

logger = manager.logger


@manager.register("message", pattern=r"(?i)^/system_usage$")
async def system_usage(event: events.NewMessage.Event):
    """查看系统使用统计（仅限管理员）。"""

    sender = await event.get_sender()
    if not sender:
        return

    # 权限检查：全局 admin / 群组 admin
    global_admin = manager.config["telegram"].get("admin")
    if str(sender.id) != global_admin:
        chat_id = event.chat_id
        if not await manager.is_admin(chat_id, sender.id):
            return  # 无权限直接忽略

    rdb = await manager.get_redis()
    if not rdb:
        return

    try:
        chat = await event.get_chat()
        if getattr(chat, "title", None):
            key = f"{STATS_KEY}:{chat.id}"
            persons_key = f"{STATS_KEY}:{chat.id}:persons"
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
            f"入群人次: {joins}",
            f"验证次数: {verifications}",
            f"验证成功: {success}",
            f"验证失败: {failed}",
            f"唯一用户: {persons_count}",
            f"成功率: {rate}",
        ]
        await event.reply("\n".join(lines))
    except asyncio.TimeoutError:
        logger.warning("system_usage 获取统计超时")
        await event.reply("获取统计超时，请稍后重试。")
    except Exception as e:
        logger.warning("system_usage 获取统计失败: %s", e)
        await event.reply("获取统计失败，请稍后重试。")
