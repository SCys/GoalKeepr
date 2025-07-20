"""
成员验证逻辑模块
Member captcha validation logic module
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from aiogram import types
from aiogram.enums import ChatMemberStatus
from loguru import logger

from manager import manager
from manager.group import settings_get

from .config import (
    SUPPORT_GROUP_TYPES, EVENT_EXPIRY_SECONDS, VerificationMode,
    MEMBER_CHECK_WAIT_TIME
)
from .exceptions import LogContext, ValidationError
from .security import restrict_member_permissions
from .session import Session


async def validate_basic_conditions(event: types.ChatMemberUpdated, chat: types.Chat, 
                                  member) -> Optional[str]:
    """
    验证基本条件
    
    Args:
        event: 聊天成员更新事件
        chat: 聊天对象
        member: 成员对象
        
    Returns:
        Optional[str]: 如果验证失败，返回失败原因；成功返回None
    """
    # 检查群组类型
    if chat.type not in SUPPORT_GROUP_TYPES:
        return "不支持的群组类型"
    
    # 确保成员对象存在
    if not member:
        return "成员对象不存在"
    
    # 检查成员状态
    if not isinstance(member, (types.ChatMemberRestricted, types.ChatMemberMember)):
        return f"成员状态不符，当前状态: {getattr(member, 'status', 'unknown')}"
    
    # 检查事件时效性
    if datetime.now(timezone.utc) > event.date + timedelta(seconds=EVENT_EXPIRY_SECONDS):
        return f"事件过期，事件时间: {event.date}"
    
    return None


async def get_verification_method(chat_id: int) -> str:
    """
    获取群组的验证方法配置
    
    Args:
        chat_id: 群组ID
        
    Returns:
        str: 验证方法
    """
    rdb = await manager.get_redis()
    if not rdb:
        logger.warning("Redis connection failed")
        return VerificationMode.BAN
    
    result = await settings_get(rdb, chat_id, "new_member_check_method", VerificationMode.BAN)
    # Convert to string if result is a dictionary or ensure it's a string
    if isinstance(result, dict):
        return str(result.get("value", VerificationMode.BAN))
    return str(result)


async def handle_silence_mode(chat: types.Chat, member_id: int, member_fullname: str, 
                            check_method: str, log_prefix: str) -> bool:
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


async def wait_and_check_member_status(chat: types.Chat, member_id: int, 
                                     log_context: LogContext) -> Optional[types.ChatMember]:
    """
    等待并检查成员状态
    
    Args:
        chat: 聊天对象
        member_id: 成员ID
        log_context: 日志上下文
        
    Returns:
        Optional[types.ChatMember]: 更新后的成员对象，如果检查失败返回None
    """
    # 等待其他机器人检查
    await asyncio.sleep(MEMBER_CHECK_WAIT_TIME)
    
    try:
        _member = await manager.chat_member(chat, member_id)
        if not _member:
            logger.error(f"{log_context.log_prefix} | 获取成员信息失败")
            return None
        
        # 忽略未被限制的成员
        if not isinstance(_member, types.ChatMemberRestricted):
            status_name = ChatMemberStatus(getattr(_member, 'status', 'unknown')).name
            logger.info(f"{log_context.log_prefix} | 用户状态变更 | 当前状态:{status_name}")
            return None

        # 忽略可以发送消息的成员
        if _member.can_send_messages:
            logger.info(f"{log_context.log_prefix} | 用户已有发言权限")
            return None

        return _member
    except Exception as e:
        logger.error(f"{log_context.log_prefix} | 检查成员状态失败 | 错误:{e}")
        return None


async def create_verification_session(chat: types.Chat, member, event: types.ChatMemberUpdated, 
                                    now: datetime, log_context: LogContext) -> Optional[Session]:
    """
    创建验证会话
    
    Args:
        chat: 聊天对象
        member: 成员对象
        event: 聊天成员更新事件
        now: 当前时间
        log_context: 日志上下文
        
    Returns:
        Optional[Session]: 创建的会话对象，失败返回None
    """
    try:
        session = await Session.get(chat, member, event, now)  # type: ignore
        if not session:
            logger.error(f"{log_context.log_prefix} | 会话创建失败")
            return None
        return session
    except Exception as e:
        logger.error(f"{log_context.log_prefix} | 创建会话失败 | 错误:{e}")
        return None
