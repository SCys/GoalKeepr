from datetime import datetime, timedelta

from telethon import types
from manager import manager

logger = manager.logger


@manager.register_event("new_member_check")
async def new_member_check(client, chat_id: int, message_id: int, member_id: int):
    try:
        chat = await client.get_entity(chat_id)
    except Exception as e:
        logger.warning(f"bot get chat {chat_id} failed: {e}")
        return

    try:
        # get_permissions returns the effective permissions of the user in the chat
        perms = await client.get_permissions(chat, member_id)
    except Exception as e:
        logger.warning(f"bot get member {member_id} in chat {chat_id} failed: {e}")
        return

    prefix = f"chat {chat_id} msg {message_id}"

    if perms.is_admin or perms.is_creator:
        logger.info(f"{prefix} member {member_id} is admin/creator")
        return

    # 如果用户已被接受（权限已恢复），跳过踢人。这是防御性检查，正常情况下
    # lazy_session 在用户通过验证时已被删除，不会触发此 handler。
    if getattr(perms, 'send_messages', False):
        logger.info(f"{prefix} member {member_id} already accepted, skipping kick")
        return

    # 超时触发意味着用户没有点击验证按钮（否则 lazy_session 会被删除）
    logger.info(f"{prefix} member {member_id} has restricted rights (timeout)")

    try:
        # Kick (Ban temporarily)
        # view_messages=False hides the chat (ban)
        await client.edit_permissions(chat, member_id, view_messages=False, until_date=timedelta(seconds=60))

        # 60秒后解除封禁，允许用户重新加入重试
        await manager.lazy_session(chat_id, message_id, member_id, "unban_member", datetime.now() + timedelta(seconds=60))

        # 清理兜底检查
        await manager.lazy_session_delete(chat_id, member_id, "safety_timeout_check")

        logger.info(f"{prefix} member {member_id} is kicked by timeout")
    except Exception as e:
        logger.warning(f"{prefix} member {member_id} kick error {e}")


@manager.register_event("unban_member")
async def unban_member(client, chat_id: int, message_id: int, member_id: int):
    try:
        chat = await client.get_entity(chat_id)
    except Exception as e:
        logger.warning(f"bot get chat {chat_id} failed: {e}")
        return

    prefix = f"chat {chat_id} msg {message_id}"

    try:
        # 清除所有限制，允许用户重新加入。重新加入后会重新触发 captcha 验证。
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


# 兜底超时检查：程序在 restrict → captcha 之间崩溃时，该 session 到期后执行
# 和正常超时 new_member_check 完全相同的逻辑：检查成员是否已被解禁（如管理员手动操作），
# 没有则踢出。不原谅任何超时。
@manager.register_event("safety_timeout_check")
async def safety_timeout_check(client, chat_id: int, message_id: int, member_id: int):
    try:
        chat = await client.get_entity(chat_id)
    except Exception as e:
        logger.warning(f"chat {chat_id} get failed: {e}")
        return

    try:
        perms = await client.get_permissions(chat, member_id)
    except Exception as e:
        logger.warning(f"member {member_id} in chat {chat_id} get failed: {e}")
        return

    prefix = f"chat {chat_id} msg {message_id}"

    if perms.is_admin or perms.is_creator:
        logger.info(f"{prefix} member {member_id} is admin/creator, skip safety check")
        return

    # 被其他用户手动解禁了 → 不处理
    if getattr(perms, 'send_messages', False):
        logger.info(f"{prefix} member {member_id} already accepted by others, skip safety check")
        return

    logger.info(f"{prefix} member {member_id} still restricted, safety timeout kick")

    try:
        await client.edit_permissions(chat, member_id, view_messages=False, until_date=timedelta(seconds=60))
        await manager.lazy_session(chat_id, message_id, member_id, "unban_member", datetime.now() + timedelta(seconds=60))
        logger.info(f"{prefix} member {member_id} is kicked by safety timeout")
    except Exception as e:
        logger.warning(f"{prefix} member {member_id} safety kick error {e}")