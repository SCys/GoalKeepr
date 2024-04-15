"""
校验新入群成员

现在提供静默规则如下：

- 如果进群立即发言（在机器人反应前），则认为会被立即 Ban 60s

如果管理员设置高级设置，可以提供 website 的检测
"""

import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import types
from aiogram.enums import ChatMemberStatus

from manager import manager
from .helpers import accepted_member, build_new_member_message

SUPPORT_GROUP_TYPES = ["supergroup", "group"]
DELETED_AFTER = 30

logger = manager.logger


@manager.register("chat_member")
async def member_captcha(event: types.ChatMemberUpdated):
    chat = event.chat
    member = event.new_chat_member

    if not member:
        logger.info(f"chat {chat.id} member is None")
        return

    member_id = member.user.id
    member_name = member.user.full_name

    prefix = f"chat {chat.id}({chat.title}) chat member updated member {member_id}({member_name})"

    if member.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED]:
        status_name = ChatMemberStatus(member.status).name
        logger.info(f"{prefix} status is {status_name}({member.status})")
        return

    # 忽略太久之前的信息
    now_ = datetime.now(timezone.utc)
    if now_ > event.date + timedelta(seconds=60):
        logger.warning(f"{prefix} date is ignored:{now_} > {event.date + timedelta(seconds=60)}")
        return
    now = event.date

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # ignore from administrator
    if event.from_user and await manager.is_admin(chat, event.from_user):
        logger.info(f"{prefix} administrator {event.from_user.id} update member permission")
        return

    try:
        logger.info(f"{prefix} found new member at {now_} ttl is {now_ - event.date}")
    except Exception as e:
        logger.error(f"check point #1 failed:{e}")

    try:
        # 收紧权限
        await chat.restrict(
            member_id,
            permissions=types.ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            ),
        )
    except Exception as e:
        logger.error(f"{prefix} no right to restrict: {e}")
        return

    logger.info(f"{prefix} is restricted")

    # 睡眠3秒，兼容其他Bot处理事情
    await asyncio.sleep(3)
    # logger.debug(f"{prefix} new member event wait 5s")

    # 如果已经被剔除，则不做处理
    member = await manager.chat_member(chat, member_id)
    if not member or member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.KICKED]:
        status_name = ChatMemberStatus(member.status).name
        logger.info(f"{prefix} member status is {status_name}({member.status})")
        return

    if member.can_send_messages:
        logger.info(f"{prefix} member {member_id} can send messages")
        return

    # checkout message sent after join 10ms
    try:
        if rdb := await manager.get_redis():
            key = f"{chat.id}_{member_id}"
            if await rdb.exists(key):
                message_id: bytes = await rdb.hget(key, "message")
                message_content: bytes = await rdb.hget(key, "message_content")
                message_date: bytes = await rdb.hget(key, "message_date")

                message_id = int(message_id.decode())
                message_content = message_content.decode()
                message_date = message_date.decode()

                logger.warning(f"{prefix} found message {message_id}({message_content}) ")

                await chat.ban(member_id, until_date=timedelta(seconds=60), revoke_messages=True)
                await chat.delete_message(message_id)
                return
    except Exception as e:
        logger.error(f"{prefix} redis error:{e}")

    message_content, reply_markup = build_new_member_message(member, now)

    # reply = await msg.reply(content, parse_mode="markdown", reply_markup=reply_markup)
    reply = await manager.bot.send_message(chat.id, message_content, parse_mode="markdown", reply_markup=reply_markup)

    await manager.lazy_session(chat.id, -1, member_id, "new_member_check", now + timedelta(seconds=DELETED_AFTER))
    await manager.delete_message(chat, reply, now + timedelta(seconds=DELETED_AFTER))


@manager.register(
    "callback_query",
    lambda q: q.message.reply_markup is not None,
)
async def new_member_callback(query: types.CallbackQuery):
    msg = query.message
    chat = msg.chat
    operator = query.from_user

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # only support myself
    if not msg.from_user.is_bot or manager.bot.id != msg.from_user.id:
        return

    # 判断是否需要处理
    if (
        msg.reply_markup.inline_keyboard is None
        or len(msg.reply_markup.inline_keyboard) != 2
        or len(msg.reply_markup.inline_keyboard[0]) != 5
        or len(msg.reply_markup.inline_keyboard[1]) != 2
    ):
        return

    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    data = query.data
    is_admin = await manager.is_admin(chat, operator)
    is_self = data.startswith(f"{operator.id}__")

    if not any([is_admin, is_self]):
        logger.warning(f"{prefix} invalid status", prefix)
        await query.answer(show_alert=False)
        return

    # operator is admin
    if is_admin and not is_self:
        items = data.split("__")
        if len(items) != 3:
            logger.warning(f"{prefix} admin {operator.id}({manager.username(operator)}) invalid data {data}")
        else:
            member_id, _, op = items
            member = await manager.chat_member(chat, member_id)

            # accept
            if op == "O":
                await manager.delete_message(chat, msg)
                await accepted_member(chat, msg, member.user)

                logger.info(
                    f"{prefix} admin {operator.id}({manager.username(operator)}) "
                    f"accept new member {member_id}({manager.username(member)})",
                )

            # reject
            elif op == "X":
                await manager.delete_message(chat, msg)
                await chat.ban(member_id, until_date=timedelta(days=30), revoke_messages=True)

                logger.warning(
                    f"{prefix} admin {operator.id}({manager.username(operator)}) kick "
                    f"member {member_id}({manager.username(member)})"
                )

            else:
                logger.warning(f"{prefix} admin {operator.id}({manager.username(operator)}) invalid data {data}")

    # user is chat member
    elif is_self:
        if data.endswith("__!"):
            await manager.delete_message(chat, msg, msg.date)

            await accepted_member(chat, msg, operator)

            logger.info(f"{prefix} user {operator.id}({manager.username(operator)}) is accepted")

        elif data.endswith("__?"):
            content, reply_markup = build_new_member_message(operator, msg.date)

            await msg.edit_text(content, parse_mode="markdown")
            await msg.edit_reply_markup(reply_markup=reply_markup)

            logger.info(f"{prefix} user {operator.id}({manager.username(operator)}) click error button, reload")

        else:
            logger.warning(f"{prefix} member {operator.id}({manager.username(operator)}) invalid data {data}")

    await query.answer(show_alert=False)
