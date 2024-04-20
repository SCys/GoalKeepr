from aiogram import types
from manager import manager

from .raw_handlers import message_counter


@manager.register("message")
async def default_handler(msg: types.Message):
    await message_counter(msg.chat, msg, msg.from_user, msg.from_user)
