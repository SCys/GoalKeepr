import asyncio

from telethon import events
from manager import manager
from ..member_captcha.stats import STATS_KEY, FIELD_GROUP_JOINS, FIELD_VERIFICATIONS, FIELD_SUCCESS, FIELD_FAILED

logger = manager.logger


@manager.register("message", pattern=r"(?i)^/system_usage$")
async def system_usage(event: events.NewMessage.Event):
    """查看系统使用统计（仅限管理员）。"""
    chat_id = event.chat_id
    msg_id = event.id
    prefix = f"system_usage chat={chat_id} msg={msg_id}"

    try:
        sender = await event.get_sender()
    except Exception as e:
        logger.exception(f"{prefix} get_sender failed: {e}")
        return

    if not sender:
        logger.warning(f"{prefix} no sender, ignored")
        return

    sender_id = sender.id
    sender_name = getattr(sender, "username", None) or getattr(sender, "first_name", None) or sender_id
    prefix = f"{prefix} user={sender_id}({sender_name})"
    logger.info(f"{prefix} command received")

    # 权限检查：全局 admin / 群组 admin
    global_admin = (manager.config["telegram"].get("admin") or "").strip()
    is_global_admin = bool(global_admin) and str(sender_id) == global_admin
    if not is_global_admin:
        try:
            is_chat_admin = await manager.is_admin(chat_id, sender_id)
        except Exception as e:
            logger.exception(f"{prefix} is_admin check failed: {e}")
            try:
                await event.reply("权限检查失败，请稍后重试。")
            except Exception as reply_err:
                logger.error(f"{prefix} reply after is_admin failure also failed: {reply_err}")
            return

        if not is_chat_admin:
            logger.warning(
                f"{prefix} permission denied (not global admin {global_admin!r}, not chat admin)"
            )
            return  # 无权限直接忽略，避免暴露命令存在

    logger.debug(f"{prefix} permission ok (global_admin={is_global_admin})")

    rdb = await manager.get_redis()
    if not rdb:
        logger.warning(f"{prefix} redis is not ready, cannot fetch stats")
        try:
            await event.reply("Redis 未就绪，无法获取统计。")
        except Exception as e:
            logger.error(f"{prefix} reply redis-not-ready failed: {e}")
        return

    try:
        chat = await event.get_chat()
        if getattr(chat, "title", None):
            scope = f"group:{chat.id}"
            key = f"{STATS_KEY}:{chat.id}"
            persons_key = f"{STATS_KEY}:{chat.id}:persons"
        else:
            scope = "global"
            key = STATS_KEY
            persons_key = f"{STATS_KEY}:persons"

        logger.debug(f"{prefix} reading stats scope={scope} key={key}")

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
        logger.info(
            f"{prefix} ok scope={scope} joins={joins} verifications={verifications} "
            f"success={success} failed={failed} persons={persons_count} rate={rate}"
        )
    except asyncio.TimeoutError:
        logger.warning(f"{prefix} redis stats timeout (3s)")
        try:
            await event.reply("获取统计超时，请稍后重试。")
        except Exception as e:
            logger.error(f"{prefix} reply timeout message failed: {e}")
    except Exception as e:
        logger.exception(f"{prefix} fetch stats failed: {e}")
        try:
            await event.reply("获取统计失败，请稍后重试。")
        except Exception as reply_err:
            logger.error(f"{prefix} reply failure message failed: {reply_err}")
