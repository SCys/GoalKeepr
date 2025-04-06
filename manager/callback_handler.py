from aiogram import types

from . import manager

log = manager.logger

@manager.dp.callback_query()
async def callback_handler(query: types.CallbackQuery):
    for func, args, kwargs in manager.callback_handlers:
        await func(query, *args, **kwargs)
        
    log.warning(f"Unknown callback: {query.data}")
