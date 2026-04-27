"""
成员验证主模块
Member captcha main module
"""

import asyncio
from datetime import timedelta, datetime, timezone
from telethon import events, types
from loguru import logger

from manager import manager
from .config import VerificationMode, DELETED_AFTER, MEMBER_CHECK_WAIT_TIME
from .exceptions import LogContext
from .session import CaptchaSession
from .validators import (
    validate_basic_conditions,
    get_verification_method,
    handle_silence_mode,
    create_verification_session,
)
from .security import restrict_member_permissions, get_member_info_for_check, perform_security_checks
from .helpers import build_captcha_message
from .callbacks import process_callback_query


@manager.register("chat_member")
async def member_captcha(event: events.ChatAction.Event):
    """
    处理新成员加入群组的验证逻辑（Telethon ChatAction：user_joined / user_added）
    """
    chat = await event.get_chat()
    user = await event.get_user()
    if not user:
        logger.warning(f"chat_member 事件无用户信息 chat_id={event.chat_id}")
        return

    await event.delete()

    # 只处理新成员加入事件（不处理成员离开、被踢等事件）
    if not event.user_joined and not event.user_added:
        logger.debug(f"chat_member 事件非新成员加入 chat_id={event.chat_id} user_id={user.id}")
        return

    # 构建入群检查的唯一ID： chat_id-user_id
    session_id = f"{event.chat_id}-{user.id}"

    # 基本条件验证（内部会按 get_chat_type(chat) 判断群组类型）
    validation_error = await validate_basic_conditions(event, chat, user)
    if validation_error:
        log_context = LogContext(chat, user.id, user.username, _full_name(user))
        logger.info(f"{log_context.log_prefix} | {validation_error}")
        return

    log_context = LogContext(chat, user.id, user.username, _full_name(user))

    # ★ 频率控制 + 去重检查（最早执行）
    now = (
        event.action_message.date if getattr(event, "action_message", None) else getattr(event, "date", None)
    ) or datetime.now(timezone.utc)

    should_proceed, captcha_data = await CaptchaSession.check_and_record(chat.id, user.id, now)

    if not should_proceed:
        state = captcha_data.get("state", "unknown")
        if state == "throttled":
            # 频率过高 → Kick
            join_count = captcha_data.get("join_count", "?")
            logger.warning(
                f"{log_context.log_prefix} | 频率限制Kick | "
                f"24h内第{join_count}次入群 | state={state}"
            )
            try:
                await manager.client.edit_permissions(
                    chat, user.id,
                    view_messages=False,
                    until_date=timedelta(seconds=60),
                )
                # 60s 后自动 unban，让用户可重新加入
                await manager.lazy_session(
                    chat.id, 0, user.id, "unban_member",
                    now + timedelta(seconds=60),
                )
            except Exception as e:
                logger.error(f"{log_context.log_prefix} | Kick 失败 | {e}")
        # duplicate 或其他状态：静默跳过
        return

    # 获取验证方法配置
    new_member_check_method = await get_verification_method(chat.id)

    logger.info(f"{log_context.log_prefix} | 新成员加入 | 时间:{now} | 处理方式:{new_member_check_method}")

    if new_member_check_method == VerificationMode.NONE:
        logger.info(f"{log_context.log_prefix} | 无作为 | 新成员加入")
        return

    # 收紧新成员权限，禁止发送消息
    if not await restrict_member_permissions(chat, user):
        logger.error(f"{log_context.log_prefix} | 权限不足 | 无法限制用户")
        return

    logger.info(f"{log_context.log_prefix} | 权限限制成功")

    # 处理静默模式
    if new_member_check_method in [VerificationMode.SILENCE, VerificationMode.SLEEP_1WEEK, VerificationMode.SLEEP_2WEEKS]:
        if await handle_silence_mode(chat, user.id, _full_name(user), new_member_check_method, log_context.log_prefix):
            return

    # 创建验证会话（传入 event 以兼容 Session.get 的 event.date）
    session = await create_verification_session(chat, user, now, log_context)
    if not session:
        return

    await asyncio.sleep(MEMBER_CHECK_WAIT_TIME)

    user_permissions = await manager.chat_member_permissions(chat, user.id)
    if not user_permissions:
        logger.error(f"{log_context.log_prefix} | 获取用户权限失败")
        return
    if user_permissions.has_left:
        logger.info(f"{log_context.log_prefix} | 用户已离开群组")
        return

    # 收集需要检查的文本
    check_list = await get_member_info_for_check(user, session)

    # 执行安全检查
    if not await perform_security_checks(user, session, check_list, log_context, now):
        return

    # 生成验证码消息（返回文字 + Telethon buttons + 答案元数据）
    message_content, buttons, answer_meta = await build_captcha_message(user, now)

    # ★ 记录验证码答案到 CaptchaSession
    await CaptchaSession.record_answer(
        chat.id, user.id,
        icon=answer_meta["icon"],
        answer=answer_meta["answer"],
        options=answer_meta["options"],
    )
    logger.debug(f"{log_context.log_prefix} | 设置验证消息自动删除 | 时长:{DELETED_AFTER}秒")


def _full_name(user: types.User) -> str:
    parts = [user.first_name or "", user.last_name or ""]
    return " ".join(x for x in parts if x).strip() or ""


@manager.register("callback_query")
async def new_member_callback(event: events.CallbackQuery.Event):
    """处理用户点击验证按钮后的逻辑"""
    await process_callback_query(event)
