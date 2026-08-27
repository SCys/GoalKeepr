from datetime import datetime, timedelta
from typing import Union

from telethon import events, types
from manager import manager

DELETED_AFTER = 5
BAN_MEMBER = 300  # 300s

logger = manager.logger


@manager.register("message", pattern=r"(?i)^/k(\s|$)|^/k@\w+")
# Support /k, /k<space>, /k@botname in groups (Telegram appends @bot to commands).
# The (\s|$) prevents matching /kill etc; ^/k@ handles bot-mention form.
async def k(event: events.NewMessage.Event):
    """踢人功能"""
    chat = await event.get_chat()
    sender = await event.get_sender()
    prefix = f"chat {event.chat_id}({getattr(chat, 'title', 'Private')}) msg {event.id}"

    if not sender:
        logger.warning(f"{prefix} message without user, ignored")
        return

    # check permission
    if not await manager.is_admin(event.chat_id, sender.id):
        logger.warning(f"{prefix} user {sender.id} is not admin")
        return

    reply = await event.get_reply_message()
    if not reply:
        logger.info(f"{prefix} no reply message")
        return

    # 如果回复的是一个新加入信息，则直接踢掉用户
    if isinstance(reply.action, types.MessageActionChatAddUser):
        for user_id in reply.action.users:
            # We need to get entity to ban? edit_permissions accepts ID.
            # But we need User object for logging/name.
            try:
                user = await manager.get_user_info(user_id)
                resp = await kick_member(chat, event, sender, user)
                await manager.delete_message(event.chat_id, resp, event.date + timedelta(seconds=DELETED_AFTER))
            except Exception as e:
                logger.error(f"Failed to kick user {user_id}: {e}")
        return

    # ignore left chat member
    elif isinstance(reply.action, types.MessageActionChatDeleteUser):
        logger.info(f"{prefix} is left chat member message, ignored")
        return

    reply_sender = await reply.get_sender()
    if resp := await kick_member(chat, event, sender, reply_sender):
        await manager.delete_message(event.chat_id, resp, event.date + timedelta(seconds=DELETED_AFTER))

    # Delete trigger and reply
    await manager.delete_message(event.chat_id, event.id, event.date + timedelta(seconds=DELETED_AFTER))
    await manager.delete_message(event.chat_id, reply.id, event.date + timedelta(seconds=DELETED_AFTER))


async def kick_member(chat, event, administrator, member):
    """
    从 chat 踢掉对应的成员（软踢：封禁后 BAN_MEMBER 秒自动解封）。

    若成员正在验证码流程中，必须先取消 new_member_check / safety_timeout_check，
    否则超时路径会覆盖 ban 时长并再调度一份 unban。
    """
    if member is None:
        return

    id = member.id
    prefix = f"chat {chat.id} msg {event.id}"

    # 取消验证超时与既有 unban，再由本命令单独调度 300s unban
    from handlers.member_captcha.helpers import cancel_pending_member_jobs
    await cancel_pending_member_jobs(chat.id, id)

    # 软踢：临时封禁 BAN_MEMBER 秒（Telegram 到期自动解封）
    if not await manager.hide_member(chat, id, until=timedelta(seconds=BAN_MEMBER)):
        logger.warning(f"{prefix} user {id} kick failed")
        return

    logger.info(f"{prefix} user {id} is kicked (temp ban {BAN_MEMBER}s)")
    
    member_name = manager.username(member)
    admin_name = manager.username(administrator)
    
    return await event.reply(
        f"{member_name} 被剔除/is Kicked by {admin_name}",
        link_preview=False
    )