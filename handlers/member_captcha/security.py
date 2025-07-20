"""
成员验证安全检查模块
Member captcha security check module
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, List
from aiogram import types
from loguru import logger

from manager import manager
from utils.advertising import check_advertising
from ..utils.llm import check_spams_with_llm

from .config import LLM_CHECK_TIMEOUT, DEFAULT_BAN_DAYS, DELETED_AFTER
from .exceptions import LogContext, PermissionError, SecurityCheckError
from .session import Session


async def restrict_member_permissions(chat: types.Chat, member_id: int, 
                                    until_date: Optional[timedelta] = None) -> bool:
    """
    限制成员权限的通用函数
    
    Args:
        chat: 聊天对象
        member_id: 成员ID
        until_date: 限制到期时间
        
    Returns:
        bool: 是否成功限制
        
    Raises:
        PermissionError: 权限不足时抛出
    """
    try:
        permissions = types.ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
        )
        result = await chat.restrict(member_id, permissions=permissions, until_date=until_date)
        if not result:
            raise PermissionError(f"限制成员 {member_id} 权限失败", chat.id, member_id)
        return True
    except Exception as e:
        logger.error(f"限制成员 {member_id} 权限失败: {e}")
        raise PermissionError(f"限制成员权限时发生错误: {e}", chat.id, member_id)


async def restore_member_permissions(chat: types.Chat, member_id: int) -> bool:
    """
    恢复成员权限
    
    Args:
        chat: 聊天对象
        member_id: 成员ID
        
    Returns:
        bool: 是否成功恢复
    """
    try:
        permissions = types.ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
        return await chat.restrict(member_id, permissions=permissions)
    except Exception as e:
        logger.error(f"恢复成员 {member_id} 权限失败: {e}")
        return False


async def get_member_info_for_check(member, session: Session) -> List[str]:
    """
    获取需要检查的成员信息
    
    Args:
        member: 成员对象
        session: 会话对象
        
    Returns:
        List[str]: 需要检查的文本列表
    """
    strings_to_check = [member.user.full_name]
    
    # 如果有用户名，获取额外信息
    if member.user.username:
        session.member_username = member.user.username
        
        try:
            # 检查用户bio
            user_info = await manager.get_user_extra_info(member.user.username)
            if user_info and user_info.get("bio"):
                bio = user_info["bio"]
                strings_to_check.append(bio)
                session.member_bio = bio
                logger.debug(f"获取用户Bio: {bio}")
        except Exception as e:
            logger.warning(f"获取用户 {member.user.username} 额外信息失败: {e}")
    
    return strings_to_check


async def perform_security_checks(member, session: Session, strings_to_check: List[str], 
                                 log_context: LogContext, now: datetime) -> bool:
    """
    执行安全检查（LLM检查和广告检查）
    
    Args:
        member: 成员对象
        session: 会话对象
        strings_to_check: 需要检查的文本列表
        log_context: 日志上下文
        now: 当前时间
        
    Returns:
        bool: True表示检查通过，False表示发现问题需要封禁
        
    Raises:
        SecurityCheckError: 安全检查过程中发生错误
    """
    try:
        # LLM检查
        await _perform_llm_check(member, session, strings_to_check, log_context, now)
        
        # 广告检查
        return await _perform_advertising_check(
            log_context.chat, member.user.id, strings_to_check, 
            session, log_context.log_prefix
        )
    except Exception as e:
        logger.exception(f"{log_context.log_prefix} | 安全检查失败 | 错误:{e}")
        raise SecurityCheckError(f"安全检查失败: {e}", log_context.chat.id, member.user.id)


async def _perform_llm_check(member, session: Session, strings_to_check: List[str],
                           log_context: LogContext, now: datetime) -> None:
    """执行LLM检查"""
    try:
        llm_start_time = datetime.now()
        logger.debug(f"{log_context.log_prefix} | 开始LLM检查")
        
        spams_result = await asyncio.wait_for(
            check_spams_with_llm([member], session, strings_to_check, now),
            timeout=LLM_CHECK_TIMEOUT
        )
        
        if spams_result and len(spams_result) > 0:
            # 过滤掉不需要的内容
            spams_result = [item for item in spams_result if item[0] == member.user.id]
            
            if spams_result:
                llm_cost_time = datetime.now() - llm_start_time
                logger.warning(
                    f"{log_context.log_prefix} | LLM检测到广告 | "
                    f"原因:{spams_result[0][1]} | "
                    f"耗时:{llm_cost_time.total_seconds():.2f}秒"
                )
    except asyncio.TimeoutError:
        logger.warning(f"{log_context.log_prefix} | LLM检查超时")
    except Exception as e:
        logger.exception(f"{log_context.log_prefix} | LLM检查失败 | 错误:{e}")


async def _perform_advertising_check(chat: types.Chat, member_id: int, 
                                   strings_to_check: List[str], session: Session, 
                                   log_prefix: str) -> bool:
    """执行广告检查"""
    for txt in strings_to_check:
        contains_adv, matched_word = check_advertising(txt)
        
        if contains_adv:
            await _handle_advertising_violation(
                chat, member_id, matched_word or "未知", 
                session, log_prefix
            )
            return False
    
    return True


async def _handle_advertising_violation(chat: types.Chat, member_id: int, matched_word: str,
                                      session: Session, log_prefix: str) -> None:
    """处理广告违规"""
    try:
        await manager.send(
            chat.id,
            f"用户 {member_id} 的名或者BIO明确包含广告内容，已经被剔除。\n"
            f"Message from {member_id} contains advertising content and has been removed.",
            auto_deleted_at=datetime.now() + timedelta(seconds=DELETED_AFTER),
        )
        
        log_details = f"匹配词:{matched_word}"
        if session.member_username:
            log_details += f" | 用户名:@{session.member_username}"
        if session.member_bio:
            log_details += f" | Bio:{session.member_bio}"
        
        logger.warning(f"{log_prefix} | 检测到广告内容 | {log_details}")
        
        # 禁止包含广告的用户
        await chat.ban(member_id, until_date=timedelta(days=DEFAULT_BAN_DAYS), revoke_messages=True)
        logger.info(f"{log_prefix} | 用户已被封禁 | 封禁时长:{DEFAULT_BAN_DAYS}天")
        
    except Exception as e:
        logger.error(f"{log_prefix} | 封禁用户失败 | 错误:{e}")
        raise SecurityCheckError(f"处理广告违规失败: {e}", chat.id, member_id)
