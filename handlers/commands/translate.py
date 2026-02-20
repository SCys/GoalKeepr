from datetime import timedelta
from telethon import events

import translators as ts

from manager import manager
from utils.tts import reply_tts
from ..utils import strip_text_prefix
from handlers.member_captcha.config import get_chat_type

logger = manager.logger

DELETED_AFTER = 5


@manager.register("message", pattern=r"(?i)^/tr(\s|$)|^/tr@\w+")
async def translate(event: events.NewMessage.Event):
    user = await event.get_sender()
    if not user:
        logger.warning("message without user, ignored")
        return

    content = event.text or ""
    target = event
    if event.is_reply and event.reply_to_msg_id:
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.text:
            content = reply_msg.text
            target = reply_msg

    content = strip_text_prefix(content)
    if not content:
        await event.respond("Please send me a text to translate")
        return

    to_language = "zh-CN"
    parts = content.split(" ", 1)
    if len(parts) > 1 and parts[0] in ["en", "zh", "jp"]:
        if parts[0] == "en":
            to_language = "en"
        elif parts[0] == "jp":
            to_language = "ja"
        else:
            to_language = "zh-CN"
        content = parts[1]

    try:
        result = ts.translate_text(content, to_language=to_language, translator="google")
        if isinstance(result, str):
            await reply_tts(target, result, show_original=True, lang=to_language)
    except Exception as e:
        logger.exception("translate failed")
        await manager.reply(
            event,
            "Translate failed, please try again later.",
            auto_deleted_at=event.date + timedelta(seconds=DELETED_AFTER),
        )

    name = getattr(user, "first_name", "") or ""
    if getattr(user, "last_name", None):
        name = f"{name} {user.last_name}".strip()
    logger.info(f"user ({name} / {user.id}) start a translate task to language {to_language}")
