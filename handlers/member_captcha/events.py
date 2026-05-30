from datetime import datetime, timedelta

from manager import manager
from .config import DEFAULT_BAN_DAYS

logger = manager.logger


async def _kick_member(client, chat_id: int, member_id: int, reason: str) -> bool:
    """
    获取群组和成员实体，检查权限，然后踢出成员。

    根据 reason 决定踢出时长:
      - "advertising" → 30 天封禁
      - "llm"         → 60 秒封禁（需调度 unban_member）
      - 其他           → 60 秒封禁（需调度 unban_member）

    Returns:
      True  — 成功踢出（已调度 unban_member 或已永久封禁）
      False — 未踢出（用户是管理员/已解禁/权限获取失败）
    """
    try:
        chat = await client.get_entity(chat_id)
    except Exception as e:
        logger.warning(f"chat {chat_id} get failed: {e}")
        return False

    try:
        perms = await client.get_permissions(chat, member_id)
    except Exception as e:
        logger.warning(f"member {member_id} in chat {chat_id} get failed: {e}")
        return False

    prefix = f"chat {chat_id}"

    if perms.is_admin or perms.is_creator:
        logger.info(f"{prefix} member {member_id} is admin/creator, skip kick")
        return False

    if getattr(perms, 'send_messages', False):
        logger.info(f"{prefix} member {member_id} already accepted, skip kick")
        return False

    logger.info(f"{prefix} member {member_id} timeout kick (reason={reason})")

    if reason == "advertising":
        await client.edit_permissions(
            chat, member_id,
            view_messages=False,
            until_date=timedelta(days=DEFAULT_BAN_DAYS),
        )
        logger.info(f"{prefix} member {member_id} banned {DEFAULT_BAN_DAYS} days for advertising")
        return True

    # llm 或 default → 60s 封禁 + 调度 unban
    await client.edit_permissions(
        chat, member_id,
        view_messages=False,
        until_date=timedelta(seconds=60),
    )
    return True


@manager.register_event("new_member_check")
async def new_member_check(client, chat_id: int, message_id: int, member_id: int):
    from .session import CaptchaSession

    reason = await CaptchaSession.is_flagged(chat_id, member_id) or "default"

    kicked = False
    try:
        kicked = await _kick_member(client, chat_id, member_id, reason)
    finally:
        await manager.lazy_session_delete(chat_id, member_id, "safety_timeout_check")
        if kicked:
            await manager.lazy_session(
                chat_id, message_id, member_id, "unban_member",
                datetime.now() + timedelta(seconds=60),
            )
            logger.info(f"chat {chat_id} msg {message_id} member {member_id} is kicked by timeout")


@manager.register_event("unban_member")
async def unban_member(client, chat_id: int, message_id: int, member_id: int):
    try:
        chat = await client.get_entity(chat_id)
    except Exception as e:
        logger.warning(f"bot get chat {chat_id} failed: {e}")
        return

    prefix = f"chat {chat_id} msg {message_id}"

    try:
        await client.edit_permissions(
            chat,
            member_id,
            view_messages=True,
            send_messages=True,
            send_media=True,
            send_stickers=True,
            send_gifs=True,
            send_games=True,
            send_inline=True,
            embed_link_previews=True,
        )
        logger.info(f"{prefix} member {member_id} is unbanned")
    except Exception as e:
        logger.warning(f"{prefix} member {member_id} unbanned error {e}")


# 兜底超时检查：程序在 restrict → captcha 之间崩溃时，该 session 到期后执行。
# 检查成员是否已被解禁；没有则根据 flagged_reason 踢出（广告=30天，其他=60s）。
@manager.register_event("safety_timeout_check")
async def safety_timeout_check(client, chat_id: int, message_id: int, member_id: int):
    from .session import CaptchaSession

    reason = await CaptchaSession.is_flagged(chat_id, member_id) or "default"

    kicked = False
    try:
        kicked = await _kick_member(client, chat_id, member_id, reason)
    finally:
        if kicked:
            await manager.lazy_session(
                chat_id, message_id, member_id, "unban_member",
                datetime.now() + timedelta(seconds=60),
            )
            logger.info(f"chat {chat_id} msg {message_id} member {member_id} is kicked by safety timeout")