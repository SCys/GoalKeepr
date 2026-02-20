from datetime import datetime, timedelta

from telethon import events

from manager import manager
from utils.asr import openai_whisper
from handlers.member_captcha.config import get_chat_type

logger = manager.logger

SUPPORT_GROUP_TYPES = ["supergroup", "group", "private"]


@manager.register("message", pattern=r"(?i)^/asr(\s|$)|^/asr@\w+")
async def asr(event: events.NewMessage.Event):
    chat = await event.get_chat()
    if get_chat_type(chat) not in SUPPORT_GROUP_TYPES:
        return

    user = await event.get_sender()
    if not user:
        return

    reply_msg = await event.get_reply_message()
    if not reply_msg:
        return

    if not reply_msg.voice and not reply_msg.media:
        return

    raw = await manager.client.download_media(reply_msg, bytes)
    if not raw:
        return

    try:
        text = await openai_whisper(raw)
        if not text:
            return
    except Exception as e:
        logger.exception("asr failed")
        await manager.reply(reply_msg, "asr failed", datetime.now() + timedelta(seconds=5))
        return

    await manager.reply(reply_msg, text)
    name = getattr(user, "first_name", "") or ""
    if getattr(user, "last_name", None):
        name = f"{name} {user.last_name}".strip()
    logger.info(f"chat {chat.id} user {name} is using asr")
