from aiogram import types
from manager import manager


@manager.register("message")
async def default_handler(msg: types.Message):
    pass
