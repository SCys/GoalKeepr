from datetime import datetime, timedelta

from aiogram import Bot, types
from aiogram.enums import ChatMemberStatus
from matplotlib.pyplot import isinteractive
from numpy import isin

from manager import manager

logger = manager.logger


@manager.register_event("new_member_check")
async def new_member_check(bot: Bot, chat_id: int, message_id: int, member_id: int):
    try:
        chat = await bot.get_chat(chat_id)
    except Exception as e:
        logger.warning(f"bot get chat {chat_id} failed: {e}")
        return

    member = await manager.chat_member(chat, member_id)
    if member is None:
        logger.warning(f"bot get chat {chat_id} failed: member is not found")
        return

    prefix = f"chat {chat_id}({chat.title}) msg {message_id}"

    # status = member.status
    if isinstance(member, types.ChatMemberAdministrator):
        logger.info(f"{prefix} member {member_id} is admin")
        return
    elif isinstance(member, types.ChatMemberOwner):
        logger.info(f"{prefix} member {member_id} is owner")
        return
    elif isinstance(member, types.ChatMemberLeft):
        logger.info(f"{prefix} member {member_id} is left")
        return
    elif isinstance(member, types.ChatMemberBanned):
        logger.info(f"{prefix} member {member_id} is kicked")
        return
    elif isinstance(member, types.ChatMemberMember):
        logger.info(f"{prefix} member {member_id} is member")
        return
    elif isinstance(member, types.ChatMemberRestricted) and member.can_send_messages:
        logger.info(f"{prefix} member {member_id} can send messages")
        return

    logger.info(f"{prefix} member {member_id} status is {member.status}")

    try:
        await chat.ban(member_id, revoke_messages=True, until_date=timedelta(seconds=60))

        # 45秒后解除禁言
        await manager.lazy_session(chat.id, message_id, member_id, "unban_member", datetime.now() + timedelta(seconds=45))

        logger.info(f"{prefix} member {member_id} is kicked by timeout")
    except Exception as e:
        logger.warning(f"{prefix} member {member_id} kick error {e}")


@manager.register_event("unban_member")
async def unban_member(bot: Bot, chat_id: int, message_id: int, member_id: int):
    try:
        chat = await bot.get_chat(chat_id)
        # member = await manager.chat_member(chat, member_id)
    except Exception as e:
        logger.warning(f"bot get chat {chat_id} failed: {e}")
        return

    prefix = f"chat {chat_id}({chat.title}) msg {message_id}"

    try:
        await bot.unban_chat_member(chat_id, member_id, only_if_banned=True)
        logger.info(f"{prefix} member {member_id} is unbanned")
    except Exception as e:
        logger.warning(f"{prefix} member {member_id} unbanned error {e}")
