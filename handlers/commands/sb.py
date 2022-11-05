from datetime import timedelta

from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from manager import manager

DELETED_AFTER = 5

logger = manager.logger


@manager.register("message", commands=["sb"], commands_ignore_caption=True, commands_ignore_mention=True)
async def sb(msg: types.Message, state: FSMContext):
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

    await manager.lazy_delete_message(chat.id, msg_reply.message_id, msg.date + timedelta(seconds=DELETED_AFTER))

    # 如果回复的是一个新加入信息，则直接踢掉用户
    if msg_reply.new_chat_members:
        for member in msg_reply.new_chat_members:
            resp = await ban_member(chat, msg, user, member)
            await manager.lazy_delete_message(chat.id, resp.message_id, msg.date + timedelta(seconds=DELETED_AFTER))

        return

    # ignore
    elif msg_reply.left_chat_member:
        logger.info(f"{prefix} is left chat member message, ignored")
        return

    resp = await ban_member(chat, msg, user, msg_reply.from_user)
    for i in [msg, resp]:
        await manager.lazy_delete_message(chat.id, i.message_id, msg.date + timedelta(seconds=DELETED_AFTER))


async def ban_member(chat: types.Chat, msg: types.Message, administrator: types.User, member: types.User):
    """
    将用户放入黑名单
    """
    id = member.id

    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    # 剔除以后就在黑名单中
    if not await chat.kick(id, revoke_messages=True):
        logger.warning(f"{prefix} user {id}({member.first_name}) ban is failed")
        return

    logger.info(f"{prefix} user {id}({member.first_name}) is baned")
    return await msg.answer(
        f"{manager.username(member)} 进入黑名单/is Baned by {manager.username(administrator)}",
        disable_web_page_preview=True,
        disable_notification=True,
    )
