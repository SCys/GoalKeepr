from datetime import datetime, timedelta, timezone

from aiogram import types
from manager import manager

SUPPORT_GROUP_TYPES = ["supergroup", "group"]


@manager.register("message")
async def message_counter(msg: types.Message):
    logger = manager.logger

    chat = msg.chat
    member = msg.from_user
    text = msg.text

    prefix = f"[message_sent]chat {chat.id}({chat.title}) msg {msg.message_id}"

    if not text:
        # logger.debug(f"{prefix} message is not text")
        return

    # 忽略太久之前的信息
    now = datetime.now(timezone.utc)
    if now > msg.date + timedelta(seconds=60):
        logger.warning(f"{prefix} date is ignored:{now} > {msg.date + timedelta(seconds=60)}")
        return

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # ignore from administrator
    if member and await manager.is_admin(chat, member):
        return

    rdb = await manager.get_redis()
    if not rdb:
        return

    key = f"{chat.id}_{member.id}"

    # ignore if message is same
    if await rdb.exists(key):
        async with rdb.pipeline(transaction=True) as pipe:
            await (
                pipe.expire(key, 5)
                .hset(key, "message", msg.message_id)
                .hset(key, "message_date", msg.date.isoformat())
                .hset(key, "message_text", text)
                .execute()
            )

        logger.info(f"{prefix} update redis record {key} {msg.message_id} {msg.date}")
        return

    async with rdb.pipeline(transaction=True) as pipe:
        await (
            pipe.hmset(
                key,
                {
                    "message": msg.message_id,
                    "message_date": msg.date.isoformat(),
                    "message_content": text,
                },
            )
            .expire(key, 5)
            .execute()
        )

    logger.debug(f"{prefix} add redis record {key} {msg.message_id} {msg.date}")
