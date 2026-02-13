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
    
    if perms.send_messages:
        # User can send messages, so they are likely verified or normal member
        logger.info(f"{prefix} member {member_id} can send messages")
        return

    logger.info(f"{prefix} member {member_id} has restricted rights (timeout)")

    try:
        # Kick (Ban temporarily)
        # view_messages=False hides the chat (ban)
        await client.edit_permissions(chat, member_id, view_messages=False, until_date=timedelta(seconds=60))

        # 45秒后解除禁言 (Schedule unban)
        await manager.lazy_session(chat_id, message_id, member_id, "unban_member", datetime.now() + timedelta(seconds=45))

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
        # Unban: Grant default permissions (View/Send)
        # Setting rights to True explicitly
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
            embed_links=True,
            until_date=0
        )
        logger.info(f"{prefix} member {member_id} is unbanned")
    except Exception as e:
        logger.warning(f"{prefix} member {member_id} unbanned error {e}")