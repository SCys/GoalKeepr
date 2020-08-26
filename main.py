#!/usr/bin/python3

import logging
import sys

from aiogram import Bot, Dispatcher, executor
from aiogram.types import ContentType

import handlers
from manager import manager


def main():
    manager.load_config()
    manager.setup()

    dp = manager.dp

    # setup handlers
    dp.message_handler(content_types=[ContentType.NEW_CHAT_MEMBERS])(handlers.new_members)
    dp.callback_query_handler(
        lambda q: q.message.reply_to_message is not None and q.message.reply_to_message.new_chat_members is not None
    )(handlers.new_member_callback)
    
    dp.message_handler(content_types=[ContentType.LEFT_CHAT_MEMBER])(handlers.left_members)

    try:
        executor.start_polling(dp, fast=True)
    except KeyboardInterrupt:
        dp.stop_polling()

        sys.exit(0)


if __name__ == "__main__":
    main()
