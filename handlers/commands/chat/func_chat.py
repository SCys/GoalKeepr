import re
from datetime import timedelta

from telethon import events

from manager import manager

from .func_adv import operations_admin, operations_person
from .func_user import check_user_permission, increase_user_count
from ...utils import count_tokens, tg_generate_text

"""
user info as hash in redis, key prefix is chat:user:{{ user_id }}.

include hash:
- disabled: bool (default False)
- count: integer (default 0)
- quota: integer (default -1, means no limit)
- last: datetime string (default '1970-01-01T00:00:00Z')
"""

DELETED_AFTER = 5
OUTPUT_MAX_LENGTH = 3500
RE_CLEAR = re.compile(r"(?i)/chat(@[a-zA-Z0-9]+\s?)?")

logger = manager.logger


@manager.register("message", pattern=r"(?i)^/chat(\s|$)|^/chat@\w+")
async def chat(event: events.NewMessage.Event):
    chat_entity = await event.get_chat()
    user = await event.get_sender()

    prefix = f"chat {event.chat_id}({getattr(chat_entity, 'title', '')}) msg {event.id}"

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    text = event.text or ""
    if text.startswith("/chat"):
        text = RE_CLEAR.sub("", text, 1).strip()

    reply_msg = await event.get_reply_message()
    if reply_msg and reply_msg.text:
        text = f"{reply_msg.text}\n{text}"
        if text.startswith("/chat"):
            text = RE_CLEAR.sub("", text, 1).strip()

    if not text:
        logger.warning(f"{prefix} message without text, ignored")
        return

    rdb = await manager.get_redis()
    if not rdb:
        logger.error(f"{prefix} redis not connected")
        await event.reply("System error: Redis is missed.")
        return

    if not await check_user_permission(rdb, event.chat_id, user.id):
        logger.warning(f"{prefix} user {user.id} in chat {event.chat_id} has no permission")
        await manager.reply(
            event,
            "你还没有权限使用这个功能。| You don't have permission to use this feature.",
            auto_deleted_at=event.date + timedelta(seconds=DELETED_AFTER),
        )
        await manager.delete_message(event.chat_id, event, event.date + timedelta(seconds=DELETED_AFTER * 2))
        return

    try:
        parts = text.split(" ", 1)
        subcommand = parts[0]

        if await operations_person(rdb, chat_entity, event, user, subcommand, parts):
            await manager.delete_message(event.chat_id, event, event.date + timedelta(seconds=DELETED_AFTER))
            return

        if await operations_admin(rdb, chat_entity, event, user, subcommand, parts):
            await manager.delete_message(event.chat_id, event, event.date + timedelta(seconds=DELETED_AFTER))
            return
    except Exception:
        logger.exception(f"{prefix} operations error")

    if len(text) < 3:
        logger.warning(f"{prefix} message too short, ignored")
        return

    try:
        text_resp = await tg_generate_text(chat_entity.id if hasattr(chat_entity, "id") else event.chat_id, user.id, text)
        if not text_resp:
            logger.warning(f"{prefix} generate text error, ignored")
            return
    except Exception as e:
        logger.exception(f"{prefix} generate text failed")
        text_resp = f"生成回复失败，请稍后再试。| Failed to generate response, please try again later.\n ```{e}```"

    success = False
    try:
        if len(text_resp) > OUTPUT_MAX_LENGTH:
            for i in range(0, len(text_resp), OUTPUT_MAX_LENGTH):
                part = text_resp[i : i + OUTPUT_MAX_LENGTH]
                await event.reply(part, parse_mode="md")
        else:
            await event.reply(text_resp, parse_mode="md")
        success = True
    except Exception:
        logger.exception(f"{prefix} invalid text format (markdown), fallback to plain")
        try:
            if len(text_resp) > OUTPUT_MAX_LENGTH:
                for i in range(0, len(text_resp), OUTPUT_MAX_LENGTH):
                    part = text_resp[i : i + OUTPUT_MAX_LENGTH]
                    await event.reply(part, link_preview=False)
            else:
                await event.reply(text_resp, link_preview=False)
            success = True
        except Exception as e2:
            logger.exception(f"{prefix} reply failed")
            await manager.reply(
                event,
                "生成回复失败，请稍后再试。| Failed to generate response, please try again later.",
                auto_deleted_at=event.date + timedelta(seconds=DELETED_AFTER),
            )

    if not success:
        await manager.delete_message(event.chat_id, event, event.date + timedelta(seconds=DELETED_AFTER))
        return

    await increase_user_count(rdb, user.id)
    logger.info(f"{prefix} do chat command, send token {count_tokens(text)}, response token {count_tokens(text_resp)}")
