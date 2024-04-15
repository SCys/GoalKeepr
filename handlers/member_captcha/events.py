from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.enums import ChatMemberStatus
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

    status = member.status
    if status == ChatMemberStatus.ADMINISTRATOR:
        logger.info(f"{prefix} member {member_id} is admin")
        return
    elif status == ChatMemberStatus.CREATOR:
        logger.info(f"{prefix} member {member_id} is creator")
        return
    elif status == ChatMemberStatus.LEFT:
        logger.info(f"{prefix} member {member_id} is left")
        return
    elif status == ChatMemberStatus.KICKED:
        logger.info(f"{prefix} member {member_id} is kicked")
        return
    elif status == ChatMemberStatus.MEMBER:
        logger.info(f"{prefix} member {member_id} is member")
        return

    if status == ChatMemberStatus.RESTRICTED and member.can_send_messages:
        logger.info(f"{prefix} member {member_id} rights is accepted")
        return

    logger.info(f"{prefix} member {member_id} status is {status}")

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
