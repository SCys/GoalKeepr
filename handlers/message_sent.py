from datetime import datetime, timedelta

from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from manager import manager

SUPPORT_GROUP_TYPES = ["supergroup", "group"]

logger = manager.logger


@manager.register("message", content_types=[types.ContentType.TEXT])
async def message_sent(msg: types.Message, state: FSMContext):
    chat = msg.chat
    member = msg.from_user

    prefix = f"[message_sent]chat {chat.id}({chat.title}) msg {msg.message_id}"

    # 忽略太久之前的信息
    now = datetime.now()
    if now > msg.date + timedelta(seconds=60):
        logger.warning(f"{prefix} date is ignored:{now} > {msg.date + timedelta(seconds=60)}")
        return

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # ignore from administrator
    if member and await manager.is_admin(chat, member):
        return

    # store member last message id and date
    if rdb := await manager.get_redis():
        key = f"{chat.id}_{member.id}"

        if await rdb.exists(key):
            async with rdb.pipeline(transaction=True) as pipe:
                await (
                    pipe.expire(key, 5)
                    .hset(key, "message", msg.message_id)
                    .hset(key, "message_date", msg.date.isoformat())
                    .hset(key, "message_text", msg.text)
                    .execute()
                )

            logger.info(f"{prefix} update redis record {key} {msg.message_id} {msg.date}")
        else:
            async with rdb.pipeline(transaction=True) as pipe:
                await (
                    pipe.hmset(
                        key,
                        {
                            "message": msg.message_id,
                            "message_date": msg.date.isoformat(),
                            "message_content": msg.text,
                        },
                    )
                    .expire(key, 5)
                    .execute()
                )

            logger.debug(f"{prefix} add redis record {key} {msg.message_id} {msg.date}")
