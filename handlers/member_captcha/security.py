"""
成员验证安全检查模块
Member captcha security check module
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Any

from loguru import logger
from telethon import types

from manager import manager
from utils.advertising import check_advertising
from ..utils.llm import check_spams_with_llm

from .config import LLM_CHECK_TIMEOUT, DEFAULT_BAN_DAYS, DELETED_AFTER
from .exceptions import LogContext, PermissionError, SecurityCheckError
from .session import Session


async def restrict_member_permissions(chat: Any, user: types.User, until_date: Optional[timedelta] = None) -> bool:
    """使用 Telethon edit_permissions 限制成员发言等权限。"""
    try:
        await manager.client.edit_permissions(
            chat,
            user,
            send_messages=False,
            send_media=False,
            send_stickers=False,
            send_gifs=False,
            send_games=False,
            send_inline=False,
            embed_link_previews=False,
            until_date=until_date,
        )
        return True
    except Exception as e:
        logger.error(f"failed to restrict permissions for member {user.id}: {e}")
        raise PermissionError(f"error restricting member permissions: {e}", getattr(chat, "id", chat), user.id)


async def restore_member_permissions(chat: Any, user: types.User) -> bool:
    """恢复成员权限（Telethon edit_permissions 全部放开发言等）。"""
    try:
        await manager.client.edit_permissions(
            chat,
            user,
            send_messages=True,
            send_media=True,
            send_stickers=True,
            send_gifs=True,
            send_games=True,
            send_inline=True,
            embed_link_previews=True,
            until_date=None,
        )
        return True
    except Exception as e:
        logger.error(f"failed to restore permissions for member {user.id}: {e}")
        return False


async def get_member_info_for_check(user: types.User, session: Session) -> List[str]:
    """
    获取需要检查的成员信息。user 需有 .user (first_name, last_name, username)。
    """
    strings_to_check = [f"{user.first_name} {user.last_name}".strip()]

    if user.username:
        session.member_username = user.username

        try:
            # 检查用户bio
            user_info = await manager.get_user_extra_info(user.username)
            if user_info and user_info.get("bio"):
                bio = user_info["bio"]
                strings_to_check.append(bio)
                session.member_bio = bio
                logger.debug(f"fetched user bio: {bio}")
        except Exception as e:
            logger.warning(f"failed to fetch extra info for user {user.username}: {e}")

    return strings_to_check


async def perform_security_checks(
    user: types.User, session: Session, check_list: List[str], log_context: LogContext, now: datetime
) -> bool:
    """
    执行安全检查（LLM检查和广告检查）

    Args:
        user: 用户对象
        session: 会话对象
        check_list: 需要检查的文本列表
        log_context: 日志上下文
        now: 当前时间

    Returns:
        bool: True表示检查通过，False表示发现问题需要封禁

    Raises:
        SecurityCheckError: 安全检查过程中发生错误
    """
    try:
        # LLM检查
        llm_found_spam = await _perform_llm_check(user, session, check_list, log_context, now)
        if llm_found_spam:
            return False

        # 广告检查
        return await _perform_advertising_check(
            log_context.chat, user.id, check_list, session, log_context.log_prefix
        )
    except Exception as e:
        logger.exception(f"{log_context.log_prefix} | security check failed | error:{e}")
        raise SecurityCheckError(f"安全检查失败: {e}", log_context.chat.id, user.id)


async def _perform_llm_check(
    user: types.User, session: Session, check_list: List[str], log_context: LogContext, now: datetime
) -> bool:
    """执行LLM检查，返回 True 表示检测到 spam（应封禁）。"""
    try:
        llm_start_time = datetime.now()
        logger.debug(f"{log_context.log_prefix} | starting LLM check")

        spams_result = await asyncio.wait_for(
            check_spams_with_llm([user], session, check_list, now), timeout=LLM_CHECK_TIMEOUT
        )

        if spams_result and len(spams_result) > 0:
            # 过滤掉不需要的内容
            spams_result = [item for item in spams_result if item[0] == user.id]

            if spams_result:
                llm_cost_time = datetime.now() - llm_start_time
                logger.warning(
                    f"{log_context.log_prefix} | LLM detected spam | "
                    f"reason:{spams_result[0][1]} | "
                    f"elapsed:{llm_cost_time.total_seconds():.2f}s"
                )
                session.banned = True
                return True
    except asyncio.TimeoutError:
        logger.warning(f"{log_context.log_prefix} | LLM check timed out")
    except Exception as e:
        logger.exception(f"{log_context.log_prefix} | LLM check failed | error:{e}")

    return False


async def _perform_advertising_check(
    chat: Any, member_id: int, strings_to_check: List[str], session: Session, log_prefix: str
) -> bool:
    """执行广告检查"""
    for txt in strings_to_check:
        contains_adv, matched_word = check_advertising(txt)

        if contains_adv:
            await _handle_advertising_violation(chat, member_id, matched_word or "未知", session, log_prefix)
            return False

    return True


async def _handle_advertising_violation(
    chat: Any, member_id: int, matched_word: str, session: Session, log_prefix: str
) -> None:
    """处理广告违规"""
    try:
        await manager.send(
            chat.id,
            f"用户 {member_id} 的名或者BIO明确包含广告内容，已经被剔除。\n"
            f"Message from {member_id} contains advertising content and has been removed.",
            auto_deleted_at=datetime.now() + timedelta(seconds=DELETED_AFTER),
        )

        log_details = f"matched:{matched_word}"
        if session.member_username:
            log_details += f" | username:@{session.member_username}"
        if session.member_bio:
            log_details += f" | bio:{session.member_bio}"

        logger.warning(f"{log_prefix} | advertising content detected | {log_details}")

        # 封禁用户（Telethon: view_messages=False + until_date）
        await manager.client.edit_permissions(
            chat,
            member_id,
            view_messages=False,
            until_date=timedelta(days=DEFAULT_BAN_DAYS),
        )
        logger.info(f"{log_prefix} | user banned | ban_days:{DEFAULT_BAN_DAYS}")

    except Exception as e:
        logger.error(f"{log_prefix} | failed to ban user | error:{e}")
        raise SecurityCheckError(f"处理广告违规失败: {e}", chat.id, member_id)
