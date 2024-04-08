import re
from datetime import timedelta

import translators as ts
from aiogram import types
from aiogram.filters import Command
from manager import manager

logger = manager.logger

RE_CLEAR = re.compile(r"/tr(@[a-zA-Z0-9]+)?\s?")
DELETED_AFTER = 5


@manager.register("message", Command("tr", ignore_case=True, ignore_mention=True))
async def translate(msg: types.Message):
    user = msg.from_user

    target = msg
    content = msg.text
    if msg.reply_to_message:
        content = msg.reply_to_message.text
        target = msg.reply_to_message

    content = RE_CLEAR.sub("", content, 1)

    if not content:
        await msg.answer("Please send me a text to translate")
        return

    # split content with space, if first argument in en, zh, convert it to en
    to_language = "zh-CN"
    parts = content.split(" ", 1)
    if len(parts) > 1 and parts[0] in ["en", "zh"]:
        to_language = "en" if parts[0] == "en" else "zh-CN"
        content = parts[1]

    try:
        result = ts.translate_text(content, to_language=to_language, translator="google")
        await target.reply(result)
    except Exception as e:
        logger.exception("translate failed")

        await manager.reply(
            msg,
            "Translate failed, please try again later.",
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )

    logger.info(f"user ({user.full_name} / {user.id}) start a translate task")
