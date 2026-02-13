from datetime import timedelta

from telethon import events, utils, types
from manager import manager

logger = manager.logger


@manager.register("message", pattern="/id")
async def whoami(event: events.NewMessage.Event):
    """我的信息"""
    if event.is_reply:
        reply = await event.get_reply_message()
        user = await reply.get_sender()
    else:
        user = await event.get_sender()

    if not user:
        return

    # Telethon user: id, first_name, last_name, username
    full_name = utils.get_display_name(user)
    user_url = f"https://t.me/{user.username}" if getattr(user, 'username', None) else "N/A"

    content = f"""ID：\t{user.id}\n完整名：\t{full_name}\n分享URL：{user_url}"""
    
    # Send reply
    # reply() returns the Message object
    msg_reply = await event.reply(content, parse_mode='html')
    
    chat_title = "Private"
    if event.chat:
        chat_title = getattr(event.chat, 'title', 'Private')

    logger.info(f"[id]chat {event.chat_id}({chat_title}) msg {event.id} user {user.id}({getattr(user, 'first_name', '')})")

    # auto delete after 5s at (super)group
    if event.is_group or event.is_channel:
        # manager.delete_message expects (chat_id, msg_id, time)
        await manager.delete_message(event.chat_id, msg_reply.id, event.date + timedelta(seconds=15))