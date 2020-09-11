import asyncio
from datetime import datetime, timedelta
import random

from aiogram import types
from aiogram.bot.bot import Bot
from aiogram.dispatcher.storage import FSMContext
from aiogram.types.message import Message
from aiogram.types.user import User

from manager import manager

SUPPORT_GROUP_TYPES = ["supergroup", "group"]
WELCOME_TEXT = "欢迎 [%(title)s](tg://user?id=%(user_id)d) ，点击 *%(icon)s* 按钮后才能发言\n如果 *30秒* 内不操作即会被送走。"
DELETED_AFTER = 30

logger = manager.logger

ICONS = {
    "爱心": "❤️️",
    "感叹号": "❗",
    "问号": "❓",
    "壹": "1⃣",
    "贰": "2⃣",
    "叁": "3⃣",
    "肆": "4⃣",
    "伍": "5⃣",
    "陆": "6⃣",
    "柒": "7⃣",
    "捌": "8⃣",
    "玖": "9⃣",
    "乘号": "✖",
    "加号": "➕",
    "减号": "➖",
    "除号": "➗",
    "禁止": "🚫",
    "美元": "💲",
    "A": "🅰",
    "B": "🅱",
    "O": "🅾",
    "彩虹旗": "🏳‍🌈",
    "眼睛": "👁",
    "脚印": "👣",
}


@manager.register("message", content_types=[types.ContentType.NEW_CHAT_MEMBERS])
async def new_members(msg: types.Message, state: FSMContext):
    chat = msg.chat
    members = msg.new_chat_members

    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    # 忽略太久之前的信息
    now = datetime.now()
    if now > msg.date + timedelta(seconds=60):
        logger.warning("{} date is ignored:{} > {}", prefix, now, msg.date + timedelta(seconds=60))
        return
    now = msg.date

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # ignore from administrator
    if msg.from_user and await manager.is_admin(chat, msg.from_user):
        logger.info("{} administrator {} added members", prefix, msg.from_user.id)
        return

    for member in members:
        if member.is_bot:
            continue

        logger.info("{} restrict new member:{}({})", prefix, member.id, manager.user_title(member))

        # 收紧权限
        await chat.restrict(
            member.id,
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
        )

    # 睡眠5秒，兼容其他Bot处理事情
    await asyncio.sleep(5)
    # logger.debug("{} new member event wait 5s", prefix)

    now = datetime.now()

    # 开始发出验证信息
    for i in members:
        if i.is_bot:
            continue

        # 如果已经被剔除，则不做处理
        member = await manager.chat_member(chat, i.id)
        if not member.is_member:
            logger.info("{} new member {}({}) is kicked", prefix, member.id, manager.user_title(member))
            continue

        if member.is_chat_admin():
            logger.info("{} new member {}({}) is admin", prefix, member.id, manager.user_title(member))
            continue

        if member.can_send_messages:
            logger.info("{} new member {}({}) rights is accepted", prefix, member.id, manager.user_title(member))
            continue

        content, reply_markup = build_new_member_message(i, now)

        reply = await msg.reply(content, parse_mode="markdown", reply_markup=reply_markup)

        await manager.lazy_session(chat.id, msg.message_id, i.id, "new_member_check", now + timedelta(seconds=DELETED_AFTER))
        await manager.lazy_delete_message(chat.id, reply.message_id, now + timedelta(seconds=DELETED_AFTER))

    if not await manager.delete_message(chat.id, msg.message_id):
        await manager.lazy_delete_message(chat.id, msg.message_id, now)


@manager.register(
    "callback_query",
    lambda q: q.message.reply_to_message is not None and q.message.reply_to_message.new_chat_members is not None,
)
async def new_member_callback(query: types.CallbackQuery):
    msg = query.message
    chat = msg.chat

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    msg_prev = msg.reply_to_message
    if not msg_prev:
        logger.warning("{} is invalid", prefix, chat.id, chat.title, msg.message_id)
        await query.answer(show_alert=False)
        return

    members = msg_prev.new_chat_members
    if not members:
        logger.warning("{} members is empty", prefix, chat.id, chat.title, msg.message_id)
        await query.answer(show_alert=False)
        return

    operator = query.from_user

    data = query.data
    is_admin = await manager.is_admin(chat, operator)
    is_self = data.startswith(f"{operator.id}__") and len([i.id for i in msg_prev.new_chat_members if i.id == operator.id]) > 0

    if not any([is_admin, is_self]):
        logger.warning("{} invalid status", prefix)
        await query.answer(show_alert=False)
        return

    # chooses = msg.reply_markup.inline_keyboard[0]

    now = datetime.now()

    # operator is admin
    if is_admin and not is_self:
        # accept
        if data.endswith("__O"):
            if not await manager.delete_message(chat.id, msg.reply_to_message.message_id):
                await manager.lazy_delete_message(chat.id, msg.reply_to_message.message_id, now)

            if not await manager.delete_message(chat.id, msg.message_id):
                await manager.lazy_delete_message(chat.id, msg.message_id, now)

            for i in members:
                await accepted_member(chat, msg, i)

                logger.info(
                    "{} admin {}({}) accept new member {}({})",
                    prefix,
                    operator.id,
                    manager.user_title(operator),
                    i.id,
                    manager.user_title(i),
                )

        # reject
        elif data.endswith("__X"):
            if not await manager.delete_message(chat.id, msg.reply_to_message.message_id):
                await manager.lazy_delete_message(chat.id, msg.reply_to_message.message_id, now)

            if not await manager.delete_message(chat.id, msg.message_id):
                await manager.lazy_delete_message(chat.id, msg.message_id, now)

            until_date = now + timedelta(days=30)
            for i in members:
                await chat.kick(i.id, until_date=until_date)
                # await chat.unban(i.id)

                logger.warning(
                    "{} administrator {}({}) kick member {}({}), until {}",
                    prefix,
                    operator.id,
                    manager.user_title(operator),
                    i.id,
                    manager.user_title(i),
                    until_date,
                )

        else:
            logger.warning(
                "{} administrator {}({}) invalid data {}", prefix, operator.id, manager.user_title(operator), data,
            )

    # user is chat member
    elif is_self:
        if data.endswith("__!"):
            await manager.lazy_delete_message(chat.id, msg.reply_to_message.message_id, msg.date)
            await manager.lazy_delete_message(chat.id, msg.message_id, msg.date)

            await accepted_member(chat, msg, operator)

            logger.info("{} user {}({}) click ok button", prefix, operator.id, manager.user_title(operator))

        elif data.endswith("__?"):
            content, reply_markup = build_new_member_message(operator, msg.date)

            await msg.edit_text(content, parse_mode="markdown")
            await msg.edit_reply_markup(reply_markup=reply_markup)

            logger.info("{} user {}({}) click error button, reload", prefix, operator.id, manager.user_title(operator))

        else:
            logger.warning("{} member {}({}) invalid data {}", prefix, operator.id, manager.user_title(operator), data)

    await query.answer(show_alert=False)


@manager.register_event("new_member_check")
async def new_member_check(bot: Bot, chat_id: int, message_id: int, member_id: int):
    chat = await bot.get_chat(chat_id)
    member = await manager.chat_member(chat, member_id)

    prefix = f"chat {chat_id}({chat.title}) msg {message_id}"

    if member.is_chat_admin():
        logger.info("{} member {}({}) is admin", prefix, member_id, manager.user_title(member))
        return

    if not member.is_chat_member():
        logger.warning("{} member {}({}) is kicked", prefix, member_id, manager.user_title(member))
        return

    # FIXME 某些情况下可能会出现问题，比如获取不到权限
    if member.can_send_messages:
        logger.info("{} member {}({}) is accepted", prefix, member_id, manager.user_title(member))
        return

    await bot.kick_chat_member(chat_id, member_id, until_date=45)  # baned 45s
    await bot.unban_chat_member(chat_id, member_id)
    logger.info("{} member {}({}) is kicked by timeout", prefix, member_id, manager.user_title(member))


def build_new_member_message(member: User, msg_timestamp):
    """
    构建新用户验证信息的按钮和文字内容
    """
    title = manager.user_title(member)

    # 用户组
    items = random.sample(list(ICONS.items()), k=5)
    button_user_ok, _ = random.choice(items)
    buttons_user = [
        types.InlineKeyboardButton(
            text=i[1], callback_data="__".join([str(member.id), str(msg_timestamp), "!" if button_user_ok == i[0] else "?"])
        )
        for i in items
    ]
    random.shuffle(buttons_user)

    # 管理组
    buttons_admin = [
        types.InlineKeyboardButton(text="✔", callback_data="__".join([str(member.id), str(msg_timestamp), "O"])),
        types.InlineKeyboardButton(text="❌", callback_data="__".join([str(member.id), str(msg_timestamp), "X"])),
    ]

    # 文字
    content = WELCOME_TEXT % {"title": title, "user_id": member.id, "icon": button_user_ok}

    return content, types.InlineKeyboardMarkup(inline_keyboard=[buttons_user, buttons_admin])


async def accepted_member(chat, msg: Message, member):
    await chat.restrict(
        member.id,
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )

    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    logger.info("{} member {}({}) is accepted", prefix, msg.message_id, member.id, manager.user_title(member))

    resp = await msg.answer(
        "欢迎 [%(title)s](tg://user?id=%(user_id)d) 加入群组，先请阅读群规。" % {"title": manager.user_title(member), "user_id": member.id},
        parse_mode="markdown",
    )
    await manager.lazy_delete_message(chat.id, resp.message_id, msg.date + timedelta(seconds=DELETED_AFTER))
    await manager.lazy_session_delete(chat.id, member.id, "new_member_check")
