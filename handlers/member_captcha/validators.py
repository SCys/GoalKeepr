"""
成员验证逻辑模块
Member captcha validation logic module
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Any

from loguru import logger
from telethon import events, types

from manager import manager, RedisUnavailableError
from manager.group import settings_get

from .config import (
    SUPPORT_GROUP_TYPES,
    EVENT_EXPIRY_SECONDS,
    VerificationMode,
    MEMBER_CHECK_WAIT_TIME,
    get_chat_type,
)
from .exceptions import LogContext, ValidationError
from .security import restrict_member_permissions
from .session import Session


async def validate_basic_conditions(
    event: events.ChatAction.Event, chat: types.Chat, user: Optional[types.User]
) -> Optional[str]:
    """
    验证基本条件。
    event: Telethon ChatAction.Event 等，需有 date/action_message.date
    chat: Telethon Chat/Channel，群组类型通过 get_chat_type(chat) 判断
    user: Telethon User
    """
    if get_chat_type(chat) not in SUPPORT_GROUP_TYPES:
        return "不支持的群组类型"

    if not user:
        return "用户对象不存在"

    event_time = (
        event.action_message.date
        if event.action_message
        else getattr(event, "date", None)
    )
    if event_time:
        # 确保 event_time 有时区信息
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        else:
            event_time = event_time.astimezone(timezone.utc)

        if datetime.now(timezone.utc) > event_time + timedelta(
            seconds=EVENT_EXPIRY_SECONDS
        ):
            return f"事件过期，事件时间: {event_time}"

    return None


async def get_verification_method(chat_id: int) -> str:
    """
    获取群组的验证方法配置

    Args:
        chat_id: 群组ID

    Returns:
        str: 验证方法
    """
    try:
        rdb = await manager.require_redis()
    except RedisUnavailableError:
        logger.debug("Redis 不可用，使用默认验证方式 ban")
        return VerificationMode.BAN

    try:
        result = await settings_get(
            rdb, chat_id, "new_member_check_method", VerificationMode.BAN
        )
        # Convert to string if result is a dictionary or ensure it's a string
        if isinstance(result, dict):
            return str(result.get("value", VerificationMode.BAN))
        return str(result)
    except Exception as e:
        logger.warning(f"获取验证方法失败，使用默认值: {e}")
        return VerificationMode.BAN


async def handle_silence_mode(
    chat: Any, member_id: int, member_fullname: str, check_method: str, log_prefix: str
) -> bool:
    """
    处理静默模式

    Args:
        chat: 聊天对象
        member_id: 成员ID
        member_fullname: 成员全名
        check_method: 检查方法
        log_prefix: 日志前缀

    Returns:
        bool: 是否成功处理
    """
    try:
        if check_method == VerificationMode.SILENCE:
            await manager.send(
                chat.id,
                f"新成员 [{member_fullname}](tg://user?id={member_id}) 加入群组，请管理员手动解封。"
                f"Welcome to the group, please wait for admin to unmute you.",
                parse_mode="markdown",
            )
            logger.info(f"{log_prefix} | 静默处理 | 新成员加入")
            return True

        elif check_method == VerificationMode.SLEEP_1WEEK:
            if await restrict_member_permissions(chat, member_id, timedelta(days=7)):
                await manager.send(
                    chat.id,
                    f"新成员 [{member_fullname}](tg://user?id={member_id}) 加入群组，已静默1周。"
                    f"Welcome to the group, you are muted for 1 week.",
                    parse_mode="markdown",
                )
                logger.info(f"{log_prefix} | 静默1周 | 新成员加入")
                return True
            else:
                logger.error(f"{log_prefix} | 权限不足 | 无法限制用户")
                return False

        elif check_method == VerificationMode.SLEEP_2WEEKS:
            if await restrict_member_permissions(chat, member_id, timedelta(days=14)):
                await manager.send(
                    chat.id,
                    f"新成员 [{member_fullname}](tg://user?id={member_id}) 加入群组，已静默2周。"
                    f"Welcome to the group, you are muted for 2 weeks.",
                    parse_mode="markdown",
                )
                logger.info(f"{log_prefix} | 静默2周 | 新成员加入")
                return True
            else:
                logger.error(f"{log_prefix} | 权限不足 | 无法限制用户")
                return False

        return False
    except Exception as e:
        logger.error(f"{log_prefix} | 静默模式处理失败 | 错误:{e}")
        return False


async def create_verification_session(
    chat: types.Chat, user: types.User, now: datetime, log_context: LogContext
) -> Optional[Session]:
    """
    创建验证会话

    Args:
        chat: 聊天对象
        user: 用户对象
        now: 当前时间
        log_context: 日志上下文

    Returns:
        Optional[Session]: 创建的会话对象，失败返回None
    """
    try:
        return await Session.create(chat, user, now)
    except Exception as e:
        logger.error(f"{log_context.log_prefix} | 创建会话失败 | 错误:{e}")
