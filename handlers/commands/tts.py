import re
from telethon import events

from manager import manager
from utils.tts import reply_tts
from handlers.member_captcha.config import get_chat_type

logger = manager.logger

SUPPORT_GROUP_TYPES = ["supergroup", "group", "private"]

RE_CLEAR = re.compile(r"(?i)/tts(@[a-zA-Z0-9]+\s?)?")


@manager.register("message", pattern=r"(?i)^/tts(\s|$)|^/tts@\w+")
async def tts(event: events.NewMessage.Event):
    chat = await event.get_chat()
    if get_chat_type(chat) not in SUPPORT_GROUP_TYPES:
        return

    user = await event.get_sender()
    if not user:
        return

    txt = event.text or ""
    reply_msg = await event.get_reply_message()
    if reply_msg and reply_msg.text:
        txt = reply_msg.text

    if not txt:
        return

    if re.match(RE_CLEAR, txt):
        txt = RE_CLEAR.sub("", txt, 1)

    txt = txt.strip()
    if not txt:
        return

    target = reply_msg if reply_msg else event
    await reply_tts(target, txt)
    name = getattr(user, "first_name", "") or ""
    if getattr(user, "last_name", None):
        name = f"{name} {user.last_name}".strip()
    logger.info(f"chat {chat.id} user {name} is using tts")
