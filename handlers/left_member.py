from datetime import timedelta

from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from aiogram.types import Message

from manager import manager

SUPPORT_GROUP_TYPES = ["supergroup", "group"]


@manager.register("message", content_types=[types.ContentType.LEFT_CHAT_MEMBER])
async def left_member(msg: Message, state: FSMContext):
    chat = msg.chat
    user = msg.from_user
    member = msg.left_chat_member

    # chat checked
    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # ignore others remove member
    if manager.bot.id == user.id:
        await manager.lazy_delete_message(chat.id, msg.message_id, msg.date + timedelta(seconds=5))

    manager.logger.info(
        "chat {}({}) message {} member {}({}) is left",
        chat.id,
        chat.title,
        msg.message_id,
        member.id,
        manager.user_title(member),
    )
