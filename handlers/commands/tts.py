import re
from datetime import datetime

import edge_tts
from aiogram import types
from aiogram.filters import Command

from manager import manager
from utils.tts import reply_tts

logger = manager.logger


SUPPORT_GROUP_TYPES = ["supergroup", "group", "private"]

RE_CLEAR = re.compile(r"/tts(@[a-zA-Z0-9]+\s?)?")


@manager.register("message", Command("tts", ignore_case=True, ignore_mention=True))
async def tts(msg: types.Message):
    chat = msg.chat
    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    user = msg.from_user
    if not user:
        return

    txt = msg.text
    if msg.reply_to_message:
        txt = msg.reply_to_message.text

    if not txt:
        return

    if txt.startswith("/tts"):
        txt = RE_CLEAR.sub("", txt, 1)

    txt = txt.strip()
    if not txt:
        return

    if msg.reply_to_message:
        await reply_tts(msg.reply_to_message, txt)
    else:
        await reply_tts(msg, txt)
    logger.info(f"chat {chat.id} user {user.full_name} is using tts")
