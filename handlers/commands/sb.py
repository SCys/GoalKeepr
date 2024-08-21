from datetime import timedelta
from typing import Union

from aiogram import types
from aiogram.filters import Command

from manager import manager

DELETED_AFTER = 3

logger = manager.logger


@manager.register("message", Command("sb", ignore_case=True, ignore_mention=True))
async def sb(msg: types.Message):
    """将用户放入黑名单"""
    chat = msg.chat
    user = msg.from_user
    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    # check permission
    if not await manager.is_admin(chat, user):
        logger.warning(f"{prefix} user {user.id}({user.first_name}) is not admin")
        return

    msg_reply = msg.reply_to_message
    if not msg_reply:
        logger.info(f"{prefix} no reply message")
        return

    await manager.delete_message(chat, msg_reply, msg.date + timedelta(seconds=DELETED_AFTER))

    # 如果回复的是一个新加入信息，则直接踢掉用户
    if msg_reply.new_chat_members:
        for member in msg_reply.new_chat_members:
            resp = await ban_member(chat, msg, user, member)
            await manager.delete_message(chat, resp, msg.date + timedelta(seconds=DELETED_AFTER))

        return

    # ignore
    elif msg_reply.left_chat_member:
        logger.info(f"{prefix} is left chat member message, ignored")
        return

    if resp := await ban_member(chat, msg, user, msg_reply.from_user):
        await manager.delete_message(chat, resp, msg.date + timedelta(seconds=DELETED_AFTER))
    await manager.delete_message(chat, msg, msg.date + timedelta(seconds=DELETED_AFTER))


async def ban_member(chat: types.Chat, msg: types.Message, administrator: types.User, member: Union[types.User, None]):
    """
    将用户放入黑名单
    """
    if member is None:
        return

    id = member.id

    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    # 剔除以后就在黑名单中
    if not await chat.ban(id, revoke_messages=True):
        logger.warning(f"{prefix} user {id}({member.first_name}) ban is failed")
        return

    logger.info(f"{prefix} user {id}({member.first_name}) is baned")
    return await msg.answer(
        f"{manager.username(member)} 进入黑名单/is Baned by {manager.username(administrator)}",
        disable_web_page_preview=True,
        disable_notification=True,
    )
