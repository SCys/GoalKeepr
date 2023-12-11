"""
校验新入群成员

现在提供静默规则如下：

- 如果进群立即发言（在机器人反应前），则认为会被立即 Ban 60s

如果管理员设置高级设置，可以提供 website 的检测
"""

import asyncio
import re
import random
from datetime import datetime, timedelta, timezone

from aiogram import types, Bot
from aiogram.types.chat import Chat
from aiogram.types.message import Message
from aiogram.types.user import User
from aiogram.enums import ChatMemberStatus
from typing import Union

from manager import manager

SUPPORT_GROUP_TYPES = ["supergroup", "group"]
WELCOME_TEXT = (
    "欢迎 [%(title)s](tg://user?id=%(user_id)d) ，点击 *%(icon)s* 按钮后才能发言。\n\n *30秒* 内不操作即会被送走。\n\n"
    "Welcome [%(title)s](tg://user?id=%(user_id)d). \n\n"
    "You would be allowed to send the message after choosing the right option for [*%(icon)s*] through pressing the correct button"
)
DELETED_AFTER = 30

RE_BAD_USERNAME = re.compile(r"[a-z]+_[a-z]+[0-9]+")

logger = manager.logger

ICONS = {
    "爱心|Love": "❤️️",
    "感叹号|Exclamation mark": "❗",
    "问号|Question mark": "❓",
    "壹|One": "1⃣",
    "贰|Two": "2⃣",
    "叁|Three": "3⃣",
    "肆|Four": "4⃣",
    "伍|Five": "5⃣",
    "陆|Six": "6⃣",
    "柒|Seven": "7⃣",
    "捌|Eight": "8⃣",
    "玖|Nine": "9⃣",
    "乘号|Multiplication number": "✖",
    "加号|Plus": "➕",
    "减号|Minus": "➖",
    "除号|Divisor": "➗",
    "禁止|Prohibition": "🚫",
    "美元|US Dollar": "💲",
    "A": "🅰",
    "B": "🅱",
    "O": "🅾",
    "彩虹旗|Rainbow flag": "🏳‍🌈",
    "眼睛|Eye": "👁",
    "脚印|Footprints": "👣",
    "汽车|Car": "🚗",
    "飞机|Aircraft": "✈️",
    "火箭|Rocket": "🚀",
    "帆船|Sailboat": "⛵️",
    "警察|Police": "👮",
    "信|Letter": "✉",
    "1/2": "½",
    "雪花|Snowflake": "❄",
    "眼镜|Eyeglasses": "👓",
    "手枪|Pistol": "🔫",
    "炸弹|Bomb": "💣",
    "骷髅|Skull": "💀",
    "骰子|Dice": "🎲",
    "音乐|Music": "🎵",
    "电影|Movie": "🎬",
    "电话|Telephone": "☎️",
    "电视|Television": "📺",
    "相机|Camera": "📷",
    "计算机|Computer": "💻",
    "手机|Mobile phone": "📱",
    "钱包|Wallet": "👛",
    "钱|Money": "💰",
    "书|Book": "📖",
    "信封|Envelope": "✉️",
    "礼物|Gift": "🎁",
}


@manager.register("chat_member")
async def member_captcha(event: types.ChatMemberUpdated):
    chat = event.chat
    member = event.new_chat_member

    if not member:
        return

    member_id = member.user.id
    member_name = member.user.full_name

    prefix = f"chat {chat.id}({chat.title}) chat member updated member {member_id}({member_name})"

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
        logger.info(f"{prefix} administrator {event.from_user.id} added members")
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
    except Exception:
        logger.exception(f"{prefix} no right to restrict")
        return

    logger.info(f"{prefix} is restricted")

    # if not await manager.delete_message(chat.id, event.message_id):
    #     await manager.lazy_delete_message(chat.id, event.message_id, now)

    # 睡眠3秒，兼容其他Bot处理事情
    await asyncio.sleep(2)
    # logger.debug(f"{prefix} new member event wait 5s")

    # 如果已经被剔除，则不做处理
    member = await manager.chat_member(chat, member_id)
    if not member or not member.is_member:
        logger.info(f"{prefix} is left or kicked")
        return

    if member.can_send_messages:
        logger.info(f"{prefix} rights is accepted")
        return

    # checkout message sent after join 10ms
    try:
        if rdb := await manager.get_redis():
            key = f"{chat.id}_{member.id}"
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
        await manager.lazy_delete_message(chat.id, reply.message_id, now + timedelta(seconds=DELETED_AFTER))


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

    now = datetime.now()

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
                if not await manager.delete_message(chat.id, msg.message_id):
                    await manager.lazy_delete_message(chat.id, msg.message_id, now)

                await accepted_member(chat, msg, member.user)

                logger.info(
                    f"{prefix} admin {operator.id}({manager.username(operator)}) "
                    f"accept new member {member_id}({manager.username(member)})",
                )

            # reject
            elif op == "X":
                if not await manager.delete_message(chat.id, msg.message_id):
                    await manager.lazy_delete_message(chat.id, msg.message_id, now)

                await chat.ban(member_id, until_date=timedelta(days=30), revoke_messages=True)
                # await chat.unban(member_id)

                logger.warning(
                    f"{prefix} admin {operator.id}({manager.username(operator)}) kick "
                    f"member {member_id}({manager.username(member)})"
                )

            else:
                logger.warning(f"{prefix} admin {operator.id}({manager.username(operator)}) invalid data {data}")

    # user is chat member
    elif is_self:
        if data.endswith("__!"):
            await manager.lazy_delete_message(chat.id, msg.message_id, msg.date)

            await accepted_member(chat, msg, operator)

            logger.info(f"{prefix} user {operator.id}({manager.username(operator)}) click ok button")

        elif data.endswith("__?"):
            content, reply_markup = build_new_member_message(operator, msg.date)

            await msg.edit_text(content, parse_mode="markdown")
            await msg.edit_reply_markup(reply_markup=reply_markup)

            logger.info(f"{prefix} user {operator.id}({manager.username(operator)}) click error button, reload")

        else:
            logger.warning(f"{prefix} member {operator.id}({manager.username(operator)}) invalid data {data}")

    await query.answer(show_alert=False)


@manager.register_event("new_member_check")
async def new_member_check(bot: Bot, chat_id: int, message_id: int, member_id: int):
    try:
        chat = await bot.get_chat(chat_id)
    except Exception as e:
        logger.warning(f"bot get chat {chat_id} failed: {e}")
        return

    member = await manager.chat_member(chat, member_id)
    if member is None:
        logger.warning(f"bot get chat {chat_id} failed: member is not found")
        return

    prefix = f"chat {chat_id}({chat.title}) msg {message_id}"

    status = member.status
    if status == ChatMemberStatus.ADMINISTRATOR:
        logger.info(f"{prefix} member {member_id} is admin")
        return
    elif status == ChatMemberStatus.CREATOR:
        logger.info(f"{prefix} member {member_id} is creator")
        return
    elif status == ChatMemberStatus.LEFT:
        logger.info(f"{prefix} member {member_id} is left")
        return
    elif status == ChatMemberStatus.KICKED:
        logger.info(f"{prefix} member {member_id} is kicked")
        return

    if member.can_send_messages:
        logger.info(f"{prefix} member {member_id} rights is accepted")
        return

    logger.info(f"{prefix} member {member_id} status is {status}")

    try:
        await chat.ban(member_id, revoke_messages=True, until_date=timedelta(seconds=60))

        # 45秒后解除禁言
        await manager.lazy_session(chat.id, message_id, member_id, "unban_member", datetime.now() + timedelta(seconds=45))

        logger.info(f"{prefix} member {member_id} is kicked by timeout")
    except Exception as e:
        logger.warning(f"{prefix} member {member_id} kick error {e}")


@manager.register_event("unban_member")
async def unban_member(bot: Bot, chat_id: int, message_id: int, member_id: int):
    try:
        chat = await bot.get_chat(chat_id)
        # member = await manager.chat_member(chat, member_id)
    except Exception as e:
        logger.warning(f"bot get chat {chat_id} failed: {e}")
        return

    prefix = f"chat {chat_id}({chat.title}) msg {message_id}"

    try:
        await bot.unban_chat_member(chat_id, member_id, only_if_banned=True)
        logger.info(f"{prefix} member {member_id} is unbanned")
    except Exception as e:
        logger.warning(f"{prefix} member {member_id} unbanned error {e}")


def build_new_member_message(member: Union[types.ChatMemberRestricted, types.User], msg_timestamp):
    """
    构建新用户验证信息的按钮和文字内容
    """
    if isinstance(member, types.ChatMemberRestricted):
        member_id = member.user.id
    else:  # User
        member_id = member.id

    member_name = manager.username(member)

    # 用户组
    items = random.sample(list(ICONS.items()), k=5)
    button_user_ok, _ = random.choice(items)
    buttons_user = [
        types.InlineKeyboardButton(
            text=i[1], callback_data="__".join([str(member_id), str(msg_timestamp), "!" if button_user_ok == i[0] else "?"])
        )
        for i in items
    ]
    random.shuffle(buttons_user)

    # 管理组
    buttons_admin = [
        types.InlineKeyboardButton(text="✔", callback_data="__".join([str(member_id), str(msg_timestamp), "O"])),
        types.InlineKeyboardButton(text="❌", callback_data="__".join([str(member_id), str(msg_timestamp), "X"])),
    ]

    # 文字
    content = WELCOME_TEXT % {"title": member_name, "user_id": member_id, "icon": button_user_ok}

    return content, types.InlineKeyboardMarkup(inline_keyboard=[buttons_user, buttons_admin])


async def accepted_member(chat: Chat, msg: Message, user: User):
    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    try:
        await chat.restrict(
            user.id,
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
    except Exception as e:
        logger.error(f"{prefix} restrict {user.id} error {e}")
        return

    logger.info(f"{prefix} member {user.id}({manager.username(user)}) is accepted")

    title = manager.username(user)
    user_id = user.id
    content = (
        f"欢迎 [{title}](tg://user?id={user_id}) 加入群组，先请阅读群规。\n\n"
        f"Welcome [{title}](tg://user?id={user_id}). \n\n"
        "Please read the rules carefully before sending the message in the group."
    )

    try:
        photos = await user.get_profile_photos(0, 1)
        if photos.total_count == 0:
            content += (
                "\n\n请设置头像或显示头像，能够更好体现个性。\n\n"
                "Please choose your appropriate fancy profile photo and set it available in public. "
                "It would improve your experience in communicate with everyone here and knowing you faster and better."
            )
    except:
        logger.exception("get profile photos error")

    resp = await msg.answer(content, parse_mode="markdown")
    await manager.lazy_delete_message(chat.id, resp.message_id, msg.date + timedelta(seconds=DELETED_AFTER))
    await manager.lazy_session_delete(chat.id, user.id, "new_member_check")
