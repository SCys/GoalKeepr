from datetime import timedelta

from telethon import events, types
from manager import manager

DELETED_AFTER = 3

logger = manager.logger


@manager.register("message", pattern=r"(?i)^/sb$")
async def sb(event: events.NewMessage.Event):
    """将用户放入黑名单"""
    chat = await event.get_chat()
    sender = await event.get_sender()
    prefix = f"chat {event.chat_id} msg {event.id}"

    if not sender:
        logger.warning(f"{prefix} message has no sender, ignoring")
        return

    # check permission
    if not await manager.is_admin(event.chat_id, sender.id):
        logger.warning(f"{prefix} user {sender.id} is not an admin")
        return

    reply = await event.get_reply_message()
    if not reply:
        logger.info(f"{prefix} no reply message found")
        return

    await manager.delete_message(event.chat_id, reply.id, event.date + timedelta(seconds=DELETED_AFTER))

    # 如果回复的是一个新加入信息，则直接踢掉用户
    if isinstance(reply.action, types.MessageActionChatAddUser):
        for user_id in reply.action.users:
            try:
                user = await manager.client.get_entity(user_id)
                resp = await ban_member(chat, event, sender, user)
                await manager.delete_message(event.chat_id, resp, event.date + timedelta(seconds=DELETED_AFTER))
            except Exception as e:
                logger.error(f"Failed to ban user {user_id}: {e}")
        return

    # ignore
    elif isinstance(reply.action, types.MessageActionChatDeleteUser):
        logger.info(f"{prefix} is a member-left message, ignoring")
        return

    reply_sender = await reply.get_sender()
    if resp := await ban_member(chat, event, sender, reply_sender):
        await manager.delete_message(event.chat_id, resp, event.date + timedelta(seconds=DELETED_AFTER))

    await manager.delete_message(event.chat_id, event.id, event.date + timedelta(seconds=DELETED_AFTER))


async def ban_member(chat, event, administrator, member):
    """
    将用户放入黑名单
    """
    if member is None:
        return

    id = member.id
    prefix = f"chat {chat.id} msg {event.id}"

    # 剔除以后就在黑名单中
    try:
        # edit_permissions(view_messages=False) bans the user.
        await manager.client.edit_permissions(chat, member, view_messages=False)
    except Exception as e:
        logger.warning(f"{prefix} failed to ban user {id}: {e}")
        return

    logger.info(f"{prefix} user {id} banned")
    
    member_name = manager.username(member)
    admin_name = manager.username(administrator)

    return await event.reply(
        f"{member_name} 进入黑名单/is Banned by {admin_name}",
        link_preview=False
    )