from aiogram import types
from manager import manager

logger = manager.logger

@manager.register("message")
async def default_handler(msg: types.Message):
    logger.debug(f"default handler: chat {msg.chat.id}({msg.chat.title}) user {msg.from_user.id}({msg.from_user.full_name}) {msg.text}")
