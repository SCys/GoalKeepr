from datetime import timedelta
from aiogram import exceptions, types
from aiogram.filters import Command
import re
from manager import manager
from orjson import loads, dumps

from .utils import count_tokens
from .func_adv import operations_admin, operations_person
from .func_txt import generate_text
from .func_user import check_user_permission, increase_user_count

"""
user info as hash in redis, key prefix is chat:user:{{ user_id }}. 

include hash:

- disabled: bool (default False)
- count: integer (default 0)
- quota: integer (default -1, means no limit)
- last: datetime string (default '1970-01-01T00:00:00Z')
"""

DELETED_AFTER = 5
BAN_MEMBER = 300  # 300s

logger = manager.logger

RE_CLEAR = re.compile(r"/chat(@[a-zA-Z0-9]+\s?)?")


@manager.register("message", Command("chat", ignore_case=True, ignore_mention=True))
async def chat(msg: types.Message):
    chat = msg.chat
    user = msg.from_user

    if chat.title is None:
        prefix = f"chat {chat.id} msg {msg.message_id}"
    else:
        prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    text = msg.text
    if text.startswith("/chat"):
        text = RE_CLEAR.sub("", text, 1).strip()
    if not text:
        logger.warning(f"{prefix} message without text, ignored")
        return

    rdb = await manager.get_redis()
    if not rdb:
        logger.error(f"{prefix} redis not connected")
        # reply system error with redis is missed
        await msg.reply("System error: Redis is missed.")
        return

    if not await check_user_permission(rdb, chat.id, user.id):
        logger.warning(f"{prefix} user {user.id} in chat {chat.id} has no permission")
        await manager.reply(
            msg,
            "你还没有权限使用这个功能。| You don't have permission to use this feature.",
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )
        await manager.delete_message(chat, msg, msg.date + timedelta(seconds=DELETED_AFTER * 2))
        return

    try:
        # split the text into prompt and message
        parts = text.split(" ", 1)
        subcommand = parts[0]

        if await operations_person(rdb, chat, msg, user, subcommand, parts):
            await manager.delete_message(chat, msg, msg.date + timedelta(seconds=DELETED_AFTER))
            return

        # administrator operations
        if await operations_admin(rdb, chat, msg, user, subcommand, parts):
            await manager.delete_message(chat, msg, msg.date + timedelta(seconds=DELETED_AFTER))
            return
    except:
        logger.exception(f"{prefix} operations error")

    if len(text) < 3:
        logger.warning(f"{prefix} message too short, ignored")
        return

    # if len(text) > 1024:
    #     logger.warning(f"{prefix} message too long, ignored")
    #     return

    try:
        text_resp = await generate_text(chat, user, text)
        if not text_resp:
            logger.warning(f"{prefix} generate text error, ignored")
            return
    except Exception as e:
        logger.error(f"{prefix} text {text} error: {e}")
        await msg.reply(f"error: {e}")

    text_resp += "\n\n---\n\n *Powered by Google Gemini Pro*"
    success = False

    try:
        text_resp = re.sub(r"[.!]", lambda x: "\\" + x.group(), text_resp)

        await msg.reply(text_resp, parse_mode="MarkdownV2", disable_web_page_preview=True)
        success = True
    except exceptions.TelegramBadRequest as e:
        logger.warning(f"{prefix} invalid text {text_resp}, error: {e}")
        await msg.reply(text_resp, disable_web_page_preview=True)
        success = True
    except Exception as e:
        logger.error(f"{prefix} reply error: {e}")
        await msg.reply(f"error: {e}")

    if success:
        await increase_user_count(rdb, user.id)
        logger.info(f"{prefix} do chat command, send token {count_tokens(text)}, response token {count_tokens(text_resp)}")
