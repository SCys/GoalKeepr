"""
校验新入群成员
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone

from aiogram import types
from aiogram.enums import ChatMemberStatus
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from loguru import logger

from manager import manager

from .helpers import accepted_member, build_captcha_message

SUPPORT_GROUP_TYPES = ["supergroup", "group"]
DELETED_AFTER = 30
RE_TG_NAME = re.compile(r"^@[a-zA-Z0-9_]{5,32}$")


@manager.register("chat_member", ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def member_captcha(event: types.ChatMemberUpdated):
    chat = event.chat
    member = event.new_chat_member

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    if not member:
        return

    member_id = member.user.id
    member_name = member.user.username

    log_prefix = f"chat {chat.id}({chat.title}) member {member_id}"
    if member_name:
        log_prefix += f"({member_name})"

    # 必须是普通成员或者被限制的成员
    if not isinstance(member, (types.ChatMemberRestricted, types.ChatMemberMember)):
        logger.info(f"{log_prefix} status is {member.status}")
        return

    # 忽略太久之前的事件
    if datetime.now(timezone.utc) > event.date + timedelta(seconds=60):
        logger.warning(f"{log_prefix} too old: {event.date}")
        return

    # FIXME 大量请求可能来自很久之前的邀请链接，所以暂时跳过此项检查
    # 忽略发自管理员的邀请
    # if event.from_user and await manager.is_admin(chat, event.from_user):
    #     logger.info(f"{log_prefix} invite from admin")
    #     return

    now = event.date
    logger.info(f"{log_prefix} found new member at {now} ttl is {now - event.date}")

    # 收紧权限
    try:
        if not await chat.restrict(
            member_id,
            permissions=types.ChatPermissions(
                can_send_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            ),
        ):
            logger.error(f"{log_prefix} no right to restrict")
            return
    except Exception as e:
        logger.error(f"{log_prefix} no right to restrict: {e}")
        return

    logger.info(f"{log_prefix} is restricted")

    # wait for other bot check
    await asyncio.sleep(3)
    if _member := await manager.chat_member(chat, member_id):
        # ignore member is not restricted
        # if _member.status != ChatMemberStatus.RESTRICTED:
        if not isinstance(_member, types.ChatMemberRestricted):
            status_name = ChatMemberStatus(member.status).name
            logger.info(f"{log_prefix} member is not restricted, current status is {status_name}")
            return

        # ignore member can send messages
        if _member.can_send_messages:
            logger.info(f"{log_prefix} member can send messages")
            return

        member = _member
    else:
        logger.error(f"{log_prefix} get member failed")

    # 记录分数，分数越高，则加强更多检查
    score = 0
    bio = None
    if member_name:
        # 检查 bio, 如果内置了 telegram 的 https://t.me/+ 开头的链接，则默认静默超过5分钟
        user_info = await manager.get_user_extra_info(member_name)
        if user_info:
            bio = user_info["bio"]
            if bio:
                if "https://t.me/+" in bio:
                    logger.info(f"{log_prefix} member bio found https://t.me/+, bad score +50")
                    score = score + 50
                if RE_TG_NAME.search(bio):
                    logger.info(f"{log_prefix} member bio found tg username, bad score +50")
                    score = score + 50

        logger.warning(f"{log_prefix} score more then zero, member {member_name}({member_id}) with bio:{bio}")
    else:
        logger.info(f"{log_prefix} member has no username, bad score +10")
        score = score + 10

    # 频繁加入群，加倍检查？
    # try:
    #     if rdb := await manager.get_redis():
    #         key = f"{chat.id}_{member_id}"
    #         if await rdb.exists(key):
    #             message_id: bytes = await rdb.hget(key, "message")
    #             message_content: bytes = await rdb.hget(key, "message_content")
    #             message_date: bytes = await rdb.hget(key, "message_date")
    #             message_id = int(message_id.decode())
    #             message_content = message_content.decode()
    #             message_date = message_date.decode()
    #             logger.warning(f"{log_prefix} found message {message_id}({message_content}) ")
    #             await chat.ban(member_id, until_date=timedelta(seconds=60), revoke_messages=True)
    #             await chat.delete_message(message_id)
    #             return
    # except Exception as e:
    #     logger.error(f"{log_prefix} redis error:{e}")

    message_content, reply_markup = await build_captcha_message(member, now)

    reply = await manager.bot.send_message(chat.id, message_content, parse_mode="markdown", reply_markup=reply_markup)

    await manager.lazy_session(chat.id, -1, member_id, "new_member_check", now + timedelta(seconds=DELETED_AFTER))
    await manager.delete_message(chat, reply, now + timedelta(seconds=DELETED_AFTER))


@manager.register(
    "callback_query",
    lambda q: q.message.reply_markup is not None,
)
async def new_member_callback(query: types.CallbackQuery):
    """
    处理用户点击后的逻辑
    """
    msg = query.message
    if not msg:
        return

    chat = msg.chat
    operator = query.from_user
    if not operator:
        return

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    if not isinstance(msg, types.Message):
        return

    user = msg.from_user
    if not user or not user.is_bot or manager.bot.id != user.id:
        return

    # 判断是否需要处理
    reply_markup = msg.reply_markup
    if (
        not reply_markup
        or reply_markup.inline_keyboard is None
        or len(reply_markup.inline_keyboard) != 2
        or len(reply_markup.inline_keyboard[0]) != 5
        or len(reply_markup.inline_keyboard[1]) != 2
    ):
        return

    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    data = query.data
    if not data:
        logger.warning(f"{prefix} no data")
        return

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
            member_id = int(member_id)
            member = await manager.chat_member(chat, member_id)

            if not member:
                return

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
            content, reply_markup = await build_captcha_message(operator, msg.date)

            await msg.edit_text(content, parse_mode="markdown")
            await msg.edit_reply_markup(reply_markup=reply_markup)

            logger.info(f"{prefix} user {operator.id}({manager.username(operator)}) click error button, reload")

        else:
            logger.warning(f"{prefix} member {operator.id}({manager.username(operator)}) invalid data {data}")

    await query.answer(show_alert=False)
