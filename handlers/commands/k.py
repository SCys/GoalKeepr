from datetime import datetime, timedelta

from aiogram import types
from aiogram.filters import Command
from manager import manager

DELETED_AFTER = 5
BAN_MEMBER = 300  # 300s

logger = manager.logger


@manager.register("message", Command("k", ignore_case=True, ignore_mention=True))
async def k(msg: types.Message):
    """踢人功能"""
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

    # 如果回复的是一个新加入信息，则直接踢掉用户
    if msg_reply.new_chat_members:
        for member in msg_reply.new_chat_members:
            await manager.delete_message(
                chat, await kick_member(chat, msg, user, member), msg.date + timedelta(seconds=DELETED_AFTER)
            )

        return

    # ignore
    elif msg_reply.left_chat_member:
        logger.info(f"{prefix} is left chat member message, ignored")
        return

    if resp := await kick_member(chat, msg, user, msg_reply.from_user):
        await manager.delete_message(chat, resp, msg.date + timedelta(seconds=DELETED_AFTER))

    for i in [msg, msg_reply]:
        await manager.delete_message(chat, i, msg.date + timedelta(seconds=DELETED_AFTER))


async def kick_member(chat: types.Chat, msg: types.Message, administrator: types.User, member: types.User):
    """
    从 chat 踢掉对应的成员
    """
    id = member.id

    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    # 剔除以后就在黑名单中
    if not await chat.ban(id):
        logger.warning(f"{prefix} user {id}({member.first_name}) kick failed, maybe he is administrator")
        return

    # 重新激活用户
    ts_free = datetime.now() + timedelta(seconds=BAN_MEMBER)
    await manager.lazy_session(chat.id, msg.message_id, id, "unban_member", ts_free)
    logger.info(f"{prefix} user {id}({member.first_name}) will unban after {ts_free}")

    logger.info(f"{prefix} user {id}({member.first_name}) is kicked")
    return await msg.answer(
        f"{manager.username(member)} 被剔除/is Kicked by {manager.username(administrator)}",
        disable_web_page_preview=True,
        disable_notification=True,
    )
