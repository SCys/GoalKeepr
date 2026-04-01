from datetime import datetime, timedelta, timezone

from telethon import types
from manager import manager

from .security_mode import (
    is_in_new_members_list,
    remove_from_new_members_list,
    clear_security_mode,
    is_security_mode,
)
from manager import RedisUnavailableError

logger = manager.logger

# 安全模式自动解除时的群通知（时间统一为 UTC）
SECURITY_MODE_AUTO_OFF_MESSAGE = (
    "🛡️ *安全模式已自动解除*\n\n"
    "解除时间：{exit_time} UTC\n"
    "新成员将恢复为验证码验证流程。\n\n"
    "Security mode has been automatically turned off (UTC: {exit_time})."
)


@manager.register_event("new_member_check")
async def new_member_check(chat_id: int, message_id: int, member_id: int):
    try:
        chat = await manager.client.get_entity(chat_id)
    except Exception as e:
        logger.warning(f"bot get chat {chat_id} failed: {e}")
        return

    try:
        # get_permissions returns the effective permissions of the user in the chat
        perms = await manager.client.get_permissions(chat, member_id)
    except Exception as e:
        logger.warning(f"bot get member {member_id} in chat {chat_id} failed: {e}")
        return

    prefix = f"chat {chat_id} msg {message_id}"

    if perms.is_admin or perms.is_creator:
        logger.info(f"{prefix} member {member_id} is admin/creator")
        return

    if not perms.is_banned:
        # User can send messages, so they are likely verified or normal member
        logger.info(f"{prefix} member {member_id} can send messages")
        return

    logger.info(f"{prefix} member {member_id} has restricted rights (timeout)")

    try:
        # Kick (Ban temporarily)
        # view_messages=False hides the chat (ban)
        await manager.client.edit_permissions(
            chat, member_id, view_messages=False, until_date=timedelta(seconds=60)
        )

        # 45秒后解除禁言 (Schedule unban)
        await manager.lazy_session(
            chat_id,
            message_id,
            member_id,
            "unban_member",
            datetime.now() + timedelta(seconds=45),
        )

        logger.info(f"{prefix} member {member_id} is kicked by timeout")
    except Exception as e:
        logger.warning(f"{prefix} member {member_id} kick error {e}")


@manager.register_event("security_mode_auto_off")
async def security_mode_auto_off(chat_id: int, message_id: int, member_id: int):
    """安全模式到期后自动解除，并向群内发送带解除时间的提示。"""
    try:
        rdb = await manager.require_redis()
    except RedisUnavailableError:
        logger.warning("security_mode_auto_off: Redis 不可用，跳过")
        return
    if not await is_security_mode(rdb, chat_id):
        logger.debug(f"chat {chat_id} 安全模式已由管理员提前解除，跳过自动解除通知")
        return
    await clear_security_mode(rdb, chat_id)
    try:
        exit_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        text = SECURITY_MODE_AUTO_OFF_MESSAGE.format(exit_time=exit_time)
        await manager.client.send_message(chat_id, text, parse_mode="md")
        logger.info(f"chat_id={chat_id} 安全模式已自动解除并已发送提示")
    except Exception as e:
        logger.warning(f"security_mode_auto_off chat {chat_id} send message error: {e}")


@manager.register_event("security_mode_kick")
async def security_mode_kick(chat_id: int, message_id: int, member_id: int):
    """安全模式：30 分钟内未被管理员通过的新成员将被移出群组。"""
    try:
        rdb = await manager.require_redis()
    except RedisUnavailableError:
        logger.warning("security_mode_kick: Redis 不可用，跳过")
        return
    if not await is_in_new_members_list(rdb, chat_id, member_id):
        logger.debug(
            f"chat {chat_id} member {member_id} 已被管理员处理或已不在待审核列表，跳过踢出"
        )
        return
    try:
        chat = await manager.client.get_entity(chat_id)
    except Exception as e:
        logger.warning(f"security_mode_kick get chat {chat_id} failed: {e}")
        return
    try:
        await manager.client.edit_permissions(
            chat,
            member_id,
            view_messages=False,
            until_date=timedelta(seconds=60),
        )
        await remove_from_new_members_list(rdb, chat_id, member_id)
        logger.info(f"chat {chat_id} member {member_id} 安全模式超时未审核，已移出群组")
    except Exception as e:
        logger.warning(
            f"security_mode_kick chat {chat_id} member {member_id} error: {e}"
        )


@manager.register_event("unban_member")
async def unban_member(chat_id: int, message_id: int, member_id: int):
    try:
        chat = await manager.client.get_entity(chat_id)
    except Exception as e:
        logger.warning(f"bot get chat {chat_id} failed: {e}")
        return

    prefix = f"chat {chat_id} msg {message_id}"

    try:
        # Unban: Grant default permissions (View/Send)
        # Setting rights to True explicitly
        await manager.client.edit_permissions(
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
            until_date=0,
        )
        logger.info(f"{prefix} member {member_id} is unbanned")
    except Exception as e:
        logger.warning(f"{prefix} member {member_id} unbanned error {e}")
