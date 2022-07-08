from datetime import timedelta

from aiogram import types
from aiogram.dispatcher.storage import FSMContext

from manager import manager

SUPPORT_GROUP_TYPES = ["supergroup", "group"]

DELETED_AFTER = 15
BAN_MEMBER = 60  # 60s
logger = manager.logger


@manager.register("message", commands=["k"])
async def k(msg: types.Message, state: FSMContext):
    chat = msg.chat
    user = msg.from_user
    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    # check permission
    if not user or not await manager.is_admin(chat, user):
        logger.warning(f"{prefix} user {user.id}({user.first_name}) is not admin")
        return

    msgReply = msg.reply_to_message
    if not msgReply:
        logger.info(f"{prefix} no reply message")
        return

    # 如果回复的是一个新加入信息，则直接踢掉用户
    if msgReply.new_chat_members:
        for member in msgReply.new_chat_members:
            resp = await kick_member(chat, msg, user, member)
            await manager.lazy_delete_message(chat.id, resp.message_id, msg.date + timedelta(seconds=DELETED_AFTER))

        return

    # ignore
    elif msgReply.left_chat_member:
        logger.info(f"{prefix} is left chat member message, ignored")
        return

    resp = await kick_member(chat, msg, user, msgReply.from_user)
    for i in [msg, resp, msgReply]:
        await manager.lazy_delete_message(chat.id, i.message_id, msg.date + timedelta(seconds=DELETED_AFTER))


async def kick_member(chat: types.Chat, msg: types.Message, administrator, member: types.User):
    """
    从 chat 踢掉对应的成员
    """
    # FIXME check member permission
    # if member and await manager.is_admin(chat, member.id):
    #     print("member is administrator:", chat.id, administrator.id, member.id)
    #     return

    id = member.id

    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    # baned 60s
    if not await chat.kick(id, until_date=timedelta(seconds=BAN_MEMBER)):
        logger.warning(f"{prefix} user {id}({member.first_name}) is not kickable, maybe he is administrator")
        return

    # 踢掉的用户将会保持在Baned状态，一定时间
    # await chat.unban(id)

    logger.info(f"{prefix} user {id}({member.first_name}) is kicked")
    username = manager.user_title(member)
    return await msg.answer(
        f"{username} 被剔除/kicked",
        disable_web_page_preview=True,
        disable_notification=True,
    )
