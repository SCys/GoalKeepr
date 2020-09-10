from datetime import timedelta
import random

from aiogram import types
from aiogram.bot.bot import Bot
from aiogram.dispatcher.storage import FSMContext
from aiogram.types.inline_keyboard import InlineKeyboardMarkup
from aiogram.utils.exceptions import MessageToDeleteNotFound

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
}


def build_new_member_message(member, msg_timestamp):
    title = manager.user_title(member)

    # 用户组
    items = random.sample(list(ICONS.items()), k=3)
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


@manager.register("message", content_types=[types.ContentType.NEW_CHAT_MEMBERS])
async def new_members(msg: types.Message, state: FSMContext):
    chat = msg.chat
    members = msg.new_chat_members
    now = msg.date

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # ignore from administrator
    if msg.from_user and await manager.is_admin(chat, msg.from_user):
        logger.info(
            "chat {} msg {} administrator {} added user {}", chat.id, msg.message_id, msg.from_user.id, [i.id for i in members]
        )
        return

    for member in members:
        if member.is_bot:  # 不删除 Bot
            continue

        title = manager.user_title(member)
        logger.info("found new member:{} {}({})", chat.id, member.id, title)

        # mute it
        await chat.restrict(
            member.id,
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
        )

        content, reply_markup = build_new_member_message(member, now)

        # send button
        reply = await msg.reply(content, parse_mode="markdown", reply_markup=reply_markup)

        await manager.lazy_session(
            chat.id, msg.message_id, member.id, "new_member_check", now + timedelta(seconds=DELETED_AFTER)
        )
        await manager.lazy_delete_message(chat.id, msg.message_id, now + timedelta(seconds=DELETED_AFTER + 5))
        await manager.lazy_delete_message(chat.id, reply.message_id, now + timedelta(seconds=DELETED_AFTER + 5))


@manager.register(
    "callback_query",
    lambda q: q.message.reply_to_message is not None and q.message.reply_to_message.new_chat_members is not None,
)
async def new_member_callback(query: types.CallbackQuery):
    msg = query.message
    chat = msg.chat

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    prev_msg = msg.reply_to_message
    if not prev_msg:
        print("no reply message")
        await query.answer(show_alert=False)
        return

    members = prev_msg.new_chat_members
    if not members:
        print("no members")
        await query.answer(show_alert=False)
        return

    member = query.from_user

    data = query.data
    is_admin = await manager.is_admin(chat, member)
    is_self = data.startswith(f"{member.id}__") and len([i.id for i in prev_msg.new_chat_members if i.id == member.id]) > 0

    if not any([is_admin, is_self]):
        print("no admin and no self")
        await query.answer(show_alert=False)
        return

    # chooses = msg.reply_markup.inline_keyboard[0]

    # operator is admin
    if is_admin and not is_self:
        # accept
        if data.endswith("__O"):
            # delete now
            await manager.lazy_delete_message(chat.id, msg.reply_to_message.message_id, msg.date)
            await manager.lazy_delete_message(chat.id, msg.message_id, msg.date)

            for i in members:
                await accepted_member(chat, msg, i)

                logger.info(
                    "chat {}({}) msg {} administrator {}({}) accept new member {}({})",
                    chat.id,
                    chat.title,
                    msg.message_id,
                    msg.from_user.id,
                    manager.user_title(msg.from_user),
                    i.id,
                    manager.user_title(i),
                )

        # reject
        elif data.endswith("__X"):
            # delete now
            await manager.lazy_delete_message(chat.id, msg.reply_to_message.message_id, msg.date)
            await manager.lazy_delete_message(chat.id, msg.message_id, msg.date)

            # until_date = msg.date + timedelta(seconds=60)
            for i in members:
                # await chat.kick(i.id, until_date=until_date)

                await chat.kick(i.id)
                # await chat.unban(i.id)

                logger.warning(
                    "chat {}({}) msg {} administrator {}({}) kick member {}({})",
                    chat.id,
                    chat.title,
                    msg.message_id,
                    msg.from_user.id,
                    manager.user_title(msg.from_user),
                    i.id,
                    manager.user_title(i),
                )

        else:
            logger.warning(
                "chat {}({}) msg {} administrator {}({}) invalid data {}",
                chat.id,
                chat.title,
                msg.message_id,
                msg.from_user.id,
                manager.user_title(msg.from_user),
                data,
            )

    # user is chat member
    elif is_self:
        if data.endswith("__!"):
            await manager.lazy_delete_message(chat.id, msg.reply_to_message.message_id, msg.date)
            await manager.lazy_delete_message(chat.id, msg.message_id, msg.date)

            await accepted_member(chat, msg, member)

            logger.info(
                "chat {}({}) msg {} user {}({}) click ok button",
                chat.id,
                chat.title,
                msg.message_id,
                member.id,
                manager.user_title(member),
            )

        elif data.endswith("__?"):
            content, reply_markup = build_new_member_message(member, msg.date)

            await msg.edit_text(content, parse_mode="markdown")
            await msg.edit_reply_markup(reply_markup=reply_markup)

            logger.info(
                "chat {}({}) msg {} user {}({}) click error button, resort user's buttons",
                chat.id,
                chat.title,
                msg.message_id,
                member.id,
                manager.user_title(member),
            )

        else:
            logger.warning(
                "chat {}({}) msg {} member {}({}) invalid data {}",
                chat.id,
                chat.title,
                msg.message_id,
                member.id,
                manager.user_title(member),
                data,
            )

    await query.answer(show_alert=False)


@manager.register_event("new_member_check")
async def new_member_check(bot: Bot, chat_id: int, message_id: int, member_id: int):
    chat = await bot.get_chat(chat_id)
    member = await chat.get_member(member_id)

    if member.is_chat_admin():
        logger.info("chat {}({}) member {}({}) is admin", chat.id, chat.title, member_id, manager.user_title(member))
        return

    if not member.is_chat_member():
        logger.warning("chat {}({}) member {}({}) is kicked", chat.id, chat.title, member_id, manager.user_title(member))
        return

    # if member.can_send_messages or member.can_post_messages:
    #     logger.info("chat {}({}) member {}({}) is accepted", chat.id, chat.title, member_id, manager.user_title(member))
    #     return

    await bot.kick_chat_member(chat_id, member_id, until_date=45)  # baned 45s
    await bot.unban_chat_member(chat_id, member_id)
    logger.info(
        "chat {}({}) msg {} member {}({}) is kicked by timeout",
        chat.id,
        chat.title,
        message_id,
        member_id,
        manager.user_title(member),
    )


async def accepted_member(chat, msg, member):
    await chat.restrict(
        member.id,
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )

    logger.info(
        "chat {}({}) msg {} member {}({}) is accepted",
        chat.id,
        chat.title,
        msg.message_id,
        member.id,
        manager.user_title(member),
    )

    resp = await msg.answer(
        "欢迎 [%(title)s](tg://user?id=%(user_id)d) 加入群组，先请阅读群规。" % {"title": manager.user_title(member), "user_id": member.id},
        parse_mode="markdown",
    )
    await manager.lazy_delete_message(chat.id, resp.message_id, msg.date + timedelta(seconds=DELETED_AFTER))
    await manager.lazy_session_delete(chat.id, member.id, "new_member_check")
