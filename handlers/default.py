from aiogram import Bot, types
from manager import manager

logger = manager.logger


@manager.register("message")
async def default(message: types.Message, bot: Bot):
    # await bot.forward_message(from_chat_id=message.chat.id, chat_id=message.chat.id, message_id=message.message_id)
    # logger.debug(f"Message: {message}")
    pass
