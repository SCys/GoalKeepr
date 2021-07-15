from configparser import MAX_INTERPOLATION_DEPTH
from datetime import timedelta

from aiogram import types
from aiogram.dispatcher.storage import FSMContext

from manager import manager

SUPPORT_GROUP_TYPES = ["supergroup", "group"]

DELETED_AFTER = 5
logger = manager.logger


@manager.register("message", commands=["k"])
async def k(msg: types.Message, state: FSMContext):
    chat = msg.chat
    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # sender is administrator
    administrator = msg.from_user
    if not administrator or not await manager.is_admin(chat, administrator):
        print("ignore no permissin:", chat.id, administrator.id)
        return

    replyMsg = msg.reply_to_message
    if not replyMsg:
        return

    # checkout target member
    if replyMsg.new_chat_members:
        for member in replyMsg.new_chat_members:
            await kick_member(chat, msg, administrator, member)

        return

    # ignore
    elif replyMsg.left_chat_member:
        return

    member = await chat.get_member(replyMsg.from_user.id)
    resp = await kick_member(chat, msg, administrator, replyMsg.from_user)

    for i in [msg, resp, replyMsg]:
        await manager.lazy_delete_message(chat.id, i.message_id, msg.date + timedelta(seconds=DELETED_AFTER))


async def kick_member(chat: types.Chat, msg, administrator, member: types.User):
    """
    从 chat 踢掉对应的成员
    """
    # FIXME check member permission
    # if member and await manager.is_admin(chat, member.id):
    #     print("member is administrator:", chat.id, administrator.id, member.id)
    #     return

    id = member.id

    await chat.kick(id, until_date=45)  # baned 45s
    await chat.unban(id)

    logger.info(f"chat {chat.id}({chat.title}) msg {msg.message_id} member {id}({manager.user_title(member)}) is kicked")

    return await msg.answer(
        "用户 **%(title)s** 已经由 **%(administrator)s** 剔除，%(deleted_after)d 秒自毁。"
        % {
            "title": manager.user_title(member),
            "administrator": manager.user_title(administrator),
            "deleted_after": DELETED_AFTER,
        },
        parse_mode="markdown",
        disable_web_page_preview=True,
        disable_notification=True,
    )
