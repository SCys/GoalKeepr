import asyncio
import re
from datetime import datetime, timedelta

from telethon import events
from manager import manager
from ..member_captcha.stats import STATS_KEY, FIELD_GROUP_JOINS, FIELD_VERIFICATIONS, FIELD_SUCCESS, FIELD_FAILED

logger = manager.logger

DELETED_AFTER = 60  # 无权限提示的自动删除时间（秒）

def _is_global_admin(user_id: int) -> bool:
    """全局 admin（[telegram] admin 配置的单个用户 ID）。"""
    admin_raw = manager.config["telegram"].get("admin", "").strip()
    return admin_raw.isdigit() and user_id == int(admin_raw)


@manager.register("message", pattern=r"(?i)^/captcha_stats(?:@[a-zA-Z0-9_]+)?(?:\s+-?\d+)?$")
async def captcha_stats(event: events.NewMessage.Event):
    """查看验证统计。用法: /captcha_stats [群ID]

    权限：全局 admin 可查全局和任意群；群管理员只能查本群
    （群内不带参数时默认本群）；其他人一律拒绝。
    """
    text = event.raw_text.strip()
    # 群 ID 是负数（-100...），必须允许前导负号，同时支持 @bot 形式
    m = re.match(r"(?i)^/captcha_stats(?:@[a-zA-Z0-9_]+)?(?:\s+(-?\d+))?\s*$", text)
    group_id = int(m.group(1)) if m and m.group(1) else None

    sender = await event.get_sender()
    sender_id = sender.id if sender else 0

    if not _is_global_admin(sender_id):
        if event.is_group or event.is_channel:
            if not sender or not await manager.is_admin(event.chat_id, sender_id):
                logger.warning(f"chat {event.chat_id} user {sender_id} denied captcha_stats")
                await manager.reply(
                    event,
                    "🚫 只有群管理员可以查看本群统计。\n\n> Only group admins can view stats.",
                    auto_deleted_at=datetime.now() + timedelta(seconds=DELETED_AFTER),
                )
                return
            # 群管理员只能查本群：不带参数默认本群，指定其他群则拒绝
            if group_id is None:
                group_id = event.chat_id
            elif group_id != event.chat_id:
                await manager.reply(
                    event,
                    "🚫 只能查看本群的统计。\n\n> You can only view stats of this group.",
                    auto_deleted_at=datetime.now() + timedelta(seconds=DELETED_AFTER),
                )
                return
        else:
            await manager.reply(
                event,
                "🚫 没有查看统计的权限。\n\n> You are not allowed to view stats.",
                auto_deleted_at=datetime.now() + timedelta(seconds=DELETED_AFTER),
            )
            return

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
