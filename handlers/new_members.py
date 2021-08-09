import asyncio
import random
from datetime import datetime, timedelta

from aiogram import types
from aiogram.bot.bot import Bot
from aiogram.dispatcher.storage import FSMContext
from aiogram.types.message import Message
from aiogram.types.user import User
from aiogram.utils.exceptions import NotEnoughRightsToRestrict
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
        logger.warning(f"{prefix} date is ignored:{now} > {msg.date + timedelta(seconds=60)}")
        return
    now = msg.date

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # ignore from administrator
    if msg.from_user and await manager.is_admin(chat, msg.from_user):
        logger.info(f"{prefix} administrator {msg.from_user.id} added members")
        return

    for member in members:
        if member.is_bot:
            continue

        logger.info(f"{prefix} restrict new member:{member.id}({manager.user_title(member)})")

        try:
            # 收紧权限
            await chat.restrict(
                member.id,
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            )
        except NotEnoughRightsToRestrict:
            logger.warning(f"{prefix} no right to restrict the member {member.id}({manager.user_title(member)}) rights")
            return

    if not await manager.delete_message(chat.id, msg.message_id):
        await manager.lazy_delete_message(chat.id, msg.message_id, now)

    # 睡眠5秒，兼容其他Bot处理事情
    await asyncio.sleep(5)
    # logger.debug(f"{prefix} new member event wait 5s")

    now = datetime.now()

    # 开始发出验证信息
    for i in members:
        if i.is_bot:
            continue

        # 如果已经被剔除，则不做处理
        member = await manager.chat_member(chat, i.id)
        if not member.is_member:
            logger.info(f"{prefix} new member {i.id}({manager.user_title(i)}) is kicked")
            continue

        if member.is_chat_admin():
            logger.info(f"{prefix} new member {i}({manager.user_title(i)}) is admin")
            continue

        if member.can_send_messages:
            logger.info(f"{prefix} new member {i}({manager.user_title(i)}) rights is accepted")
            continue

        content, reply_markup = build_new_member_message(i, now)

        # reply = await msg.reply(content, parse_mode="markdown", reply_markup=reply_markup)
        reply = await manager.bot.send_message(chat.id, content, parse_mode="markdown", reply_markup=reply_markup)

        await manager.lazy_session(chat.id, msg.message_id, i.id, "new_member_check", now + timedelta(seconds=DELETED_AFTER))
        await manager.lazy_delete_message(chat.id, reply.message_id, now + timedelta(seconds=DELETED_AFTER))


@manager.register(
    "callback_query",
    # lambda q: q.message.reply_to_message is not None and q.message.reply_to_message.new_chat_members is not None,
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
            logger.warning(f"{prefix} admin {operator.id}({manager.user_title(operator)}) invalid data {data}")
        else:
            member_id, _, op = items
            member = await manager.chat_member(chat, member_id)

            # accept
            if op == "O":
                if not await manager.delete_message(chat.id, msg.message_id):
                    await manager.lazy_delete_message(chat.id, msg.message_id, now)

                await accepted_member(chat, msg, member.user)

                logger.info(
                    f"{prefix} admin {operator.id}({manager.user_title(operator)}) accept new member {member_id}({manager.user_title(member)})",
                )

            # reject
            elif op == "X":
                if not await manager.delete_message(chat.id, msg.message_id):
                    await manager.lazy_delete_message(chat.id, msg.message_id, now)

                until_date = now + timedelta(days=30)
                await chat.kick(member_id, until_date=until_date)
                # await chat.unban(member_id)

                logger.warning(
                    f"{prefix} admin {operator.id}({manager.user_title(operator)}) kick member {member_id}({manager.user_title(member)}), until {until_date}",
                )

            else:
                logger.warning(f"{prefix} admin {operator.id}({manager.user_title(operator)}) invalid data {data}")

    # user is chat member
    elif is_self:
        if data.endswith("__!"):
            await manager.lazy_delete_message(chat.id, msg.message_id, msg.date)

            await accepted_member(chat, msg, operator)

            logger.info(f"{prefix} user {operator.id}({manager.user_title(operator)}) click ok button")

        elif data.endswith("__?"):
            content, reply_markup = build_new_member_message(operator, msg.date)

            await msg.edit_text(content, parse_mode="markdown")
            await msg.edit_reply_markup(reply_markup=reply_markup)

            logger.info(f"{prefix} user {operator.id}({manager.user_title(operator)}) click error button, reload")

        else:
            logger.warning(f"{prefix} member {operator.id}({manager.user_title(operator)}) invalid data {data}")

    await query.answer(show_alert=False)


@manager.register_event("new_member_check")
async def new_member_check(bot: Bot, chat_id: int, message_id: int, member_id: int):
    chat = await bot.get_chat(chat_id)
    member = await manager.chat_member(chat, member_id)

    prefix = f"chat {chat_id}({chat.title}) msg {message_id}"

    if member.is_chat_admin():
        logger.info(f"{prefix} member {member_id} is admin")
        return

    if not member.is_chat_member():
        logger.warning(f"{prefix} member {member_id} is kicked")
        return

    # FIXME 某些情况下可能会出现问题，比如获取不到权限
    if member.can_send_messages:
        logger.info(f"{prefix} member {member_id} is accepted")
        return

    await bot.kick_chat_member(chat_id, member_id, until_date=45)  # baned 45s
    await bot.unban_chat_member(chat_id, member_id)
    logger.info(f"{prefix} member {member_id} is kicked by timeout")


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


async def accepted_member(chat, msg: Message, user: User):
    await chat.restrict(
        user.id,
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )

    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    logger.info(f"{prefix} member {user.id}({manager.user_title(user)}) is accepted")

    content = "欢迎 [%(title)s](tg://user?id=%(user_id)d) 加入群组，先请阅读群规。" % {"title": manager.user_title(user), "user_id": user.id}

    try:
        photos = await user.get_profile_photos(0, 1)
        if photos.total_count == 0:
            content += "\n\n请设置头像或显示头像，能够更好体现个性。"
    except Exception:
        logger.exception("get profile photos error")

    resp = await msg.answer(content, parse_mode="markdown")
    await manager.lazy_delete_message(chat.id, resp.message_id, msg.date + timedelta(seconds=DELETED_AFTER))
    await manager.lazy_session_delete(chat.id, user.id, "new_member_check")
