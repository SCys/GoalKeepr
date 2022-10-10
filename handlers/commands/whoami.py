from datetime import timedelta

from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from manager import manager

logger = manager.logger


@manager.register("message", commands=["id"])
async def whoami(msg: types.Message, state: FSMContext):
    """我的信息"""
    if msg.reply_to_message:
        user = msg.reply_to_message.from_user
    else:
        user = msg.from_user

    if not user or not user.id:
        return

    content = f"""ID：\t{user.id}\n完整名：\t{user.full_name}\n分享URL：{user.url}"""
    msg_reply = await msg.reply(content, disable_notification=True)
    logger.info(f"[id]chat {msg.chat.id}({msg.chat.title}) msg {msg.message_id} user {user.id}({user.first_name})")

    # auto delete after 5s at (super)group
    if msg.chat.type in ["supergroup", "group"]:
        await manager.lazy_delete_message(msg.chat.id, msg_reply.message_id, msg.date + timedelta(seconds=15))
