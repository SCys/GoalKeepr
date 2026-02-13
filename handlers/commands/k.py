from datetime import datetime, timedelta
from typing import Union

from telethon import events, types
from manager import manager

DELETED_AFTER = 5
BAN_MEMBER = 300  # 300s

logger = manager.logger


@manager.register("message", pattern=r"(?i)^/k$") 
# regex for exact match or ignoring case. 
# Or just pattern="/k" but that might match "/kill". 
# Telethon pattern is regex by default? No, default is not regex unless specified? 
# Telethon events.NewMessage(pattern=...) treats it as regex if string. 
# "^/k$" is safer.
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
                user = await manager.client.get_entity(user_id)
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
    从 chat 踢掉对应的成员
    """
    if member is None:
        return

    id = member.id
    prefix = f"chat {chat.id} msg {event.id}"

    try:
        # 剔除 (Ban)
        # edit_permissions with view_messages=False is banning.
        # until_date is optional.
        # But wait, 'kick' in this context means 'Kick and Unban later' (Soft Ban).
        # Telethon kick_participant is "Remove from group". If not banned, they can rejoin.
        # Aiogram's ban() is "Ban".
        # Code says: "剔除以后就在黑名单中" (After kicking, is in blacklist).
        # And then "unban_member" session is created.
        # So it is a BAN.
        
        await manager.client.edit_permissions(chat, member, view_messages=False)
        
    except Exception as e:
        logger.warning(f"{prefix} user {id} kick failed: {e}")
        return

    # 重新激活用户
    ts_free = datetime.now() + timedelta(seconds=BAN_MEMBER)
    # We pass 'chat.id' to lazy_session. lazy_session expects int.
    await manager.lazy_session(chat.id, event.id, id, "unban_member", ts_free)
    logger.info(f"{prefix} user {id} will unban after {ts_free}")

    logger.info(f"{prefix} user {id} is kicked")
    
    # Send notification
    # manager.username expects user object
    member_name = manager.username(member)
    admin_name = manager.username(administrator)
    
    return await event.reply(
        f"{member_name} 被剔除/is Kicked by {admin_name}",
        link_preview=False
    )