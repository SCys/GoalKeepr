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
    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    user = msg.from_user

    # check permission
    if not user or not await manager.is_admin(chat, user):
        logger.warning(f"chat {chat.id}({chat.title}) msg {msg.message_id} user {user.id}({user.first_name}) is not admin")
        return

    msgReply = msg.reply_to_message
    if not msgReply:
        return

    # checkout target member
    if msgReply.new_chat_members:
        for member in msgReply.new_chat_members:
            await kick_member(chat, msg, user, member)

        return

    # ignore
    elif msgReply.left_chat_member:
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

    # baned 60s
    if not await chat.kick(id, until_date=timedelta(seconds=BAN_MEMBER)):
        logger.warning(
            f"chat {chat.id}({chat.title}) msg {msg.message_id} user {administrator.id}({administrator.first_name}) failed to kick {id}"
        )
        return

    # 踢掉的用户将会保持在Baned状态，一定时间
    # await chat.unban(id)

    logger.info(f"chat {chat.id}({chat.title}) msg {msg.message_id} member {id}({manager.user_title(member)}) is kicked")

    username = manager.user_title(member)

    return await msg.answer(
        f"{username} 被剔除/kicked",
        disable_web_page_preview=True,
        disable_notification=True,
    )
