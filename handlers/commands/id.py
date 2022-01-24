from datetime import timedelta

from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from manager import manager

logger = manager.logger


@manager.register("message", commands=["id"])
async def id(msg: types.Message, state: FSMContext):
    if msg.reply_to_message:
        user = msg.reply_to_message.from_user
    else:
        user = msg.from_user

    if not user or not user.id:
        return

    msg_reply = await msg.reply(f"""id:\t{user.id}\nname:\t{user.full_name}\nbot:\t{user.is_bot}""", disable_notification=True)
    logger.info(f"chat {msg.chat.id}({msg.chat.title}) msg {msg.message_id} user {user.id}({user.first_name})")

    chat = msg.chat
    await manager.lazy_delete_message(chat.id, msg_reply.id, msg.date + timedelta(seconds=5))
