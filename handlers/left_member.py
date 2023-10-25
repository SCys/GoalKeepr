from datetime import datetime, timedelta

from aiogram import types
from aiogram.types import Message

from manager import manager

SUPPORT_GROUP_TYPES = ["supergroup", "group"]


@manager.register("message", content_types=[types.ContentType.LEFT_CHAT_MEMBER])
async def left_member(msg: Message):
    chat = msg.chat
    user = msg.from_user
    member = msg.left_chat_member
    now = datetime.now()

    # chat checked
    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # ignore others remove member
    if manager.bot.id == user.id:
        await manager.lazy_delete_message(chat.id, msg.message_id, now + timedelta(seconds=5))

    manager.logger.info(
        f"chat {chat.id}({chat.title}) message {msg.message_id} " f"member {member.id}({manager.username(member)}) is left"
    )
