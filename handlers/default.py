from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from manager import manager

logger = manager.logger


@manager.register("message")
async def new_members(msg: types.Message, ctx: FSMContext):
    # await bot.forward_message(from_chat_id=message.chat.id, chat_id=message.chat.id, message_id=message.message_id)
    # logger.debug(f"Message: {msg}")
    pass
