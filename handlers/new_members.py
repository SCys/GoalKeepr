from datetime import datetime, timezone
from typing import ContextManager, List

from aiogram import Bot, types
from aiogram.dispatcher.storage import FSMContext
from aiogram.utils import markdown

from manager import manager

SUPPORT_GROUP_TYPES = ["supergroup", "group"]
WELCOME_TEXT = "欢迎 _%(title)s_ ，点击 **感叹号** 按钮后才能发言\n如果 *30秒* 内不操作即会将你剔除。"


async def new_members(msg: types.Message, state: FSMContext):
    chat = msg.chat
    members = msg.new_chat_members
    now = datetime.now(timezone.utc)

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # ignore from administrator
    if msg.from_user and await manager.is_admin(chat, msg.from_user):
        pass

    for member in members:
        if member.is_bot:
            continue

        if None in [member.first_name, member.last_name]:
            title = f"{member.first_name or ''}{member.last_name or ''}"
        else:
            title = " ".join([member.first_name, member.last_name])

        print("new_member", chat.id, member.id, title)

        # mute it
        await chat.restrict(
            member.id,
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
        )

        # send button
        await msg.reply(
            WELCOME_TEXT % {"title": title},
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(text="❗", callback_data="__".join([str(member.id), str(now), "!"])),
                        types.InlineKeyboardButton(text="✔", callback_data="__".join([str(member.id), str(now), "O"])),
                        types.InlineKeyboardButton(text="❌", callback_data="__".join([str(member.id), str(now), "X"])),
                    ],
                ]
            ),
        )


async def new_member_callback(query: types.CallbackQuery):
    msg = query.message
    chat = msg.chat

    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    prev_msg = msg.reply_to_message
    if not prev_msg:
        print("no reply message")
        return

    members = prev_msg.new_chat_members
    if not members:
        print("no members")
        return

    member = query.from_user

    data = query.data
    is_admin = await manager.is_admin(chat, member)
    is_self = data.startswith(f"{member.id}__") and len([i.id for i in prev_msg.new_chat_members if i.id == member.id]) > 0

    if not any([is_admin, is_self]):
        print("no admin and no self")
        return

    chooses = msg.reply_markup.inline_keyboard[0]
    first = chooses[0]
    second = chooses[1]
    third = chooses[2]

    if is_admin and not is_self:
        if data == second.callback_data:
            for i in members:
                await chat.restrict(
                    i.id,
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                )
                await msg.answer("welcome")
                print("administrator accepted new members:", chat.id, i.id, is_admin, is_self)

        elif data == third.callback_data:
            for i in members:
                await chat.kick(i.id, until_date=45)  # baned 45s
                print("administrator reject new members:", chat.id, i.id, is_admin, is_self)

        else:
            print("administrator invalid choose:", chat.id, member)
            await msg.reply("?")

    elif is_self:
        if data == first.callback_data:
            await chat.restrict(
                member.id,
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            )

            print("welcome member:", member.id, chat.id)

            await msg.answer("welcome")

        else:
            print("member invalid choose:", chat.id, member.id, data)

