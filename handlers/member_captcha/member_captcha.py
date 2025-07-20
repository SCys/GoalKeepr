"""
成员验证主模块
Member captcha main module
"""

from datetime import timedelta
from aiogram import types
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from loguru import logger

from manager import manager
from .config import VerificationMode, DELETED_AFTER
from .exceptions import LogContext
from .validators import (
    validate_basic_conditions, get_verification_method, handle_silence_mode,
    wait_and_check_member_status, create_verification_session
)
from .security import (
    restrict_member_permissions, get_member_info_for_check, perform_security_checks
)
from .helpers import build_captcha_message
from .callbacks import process_callback_query


@manager.register("chat_member", ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def member_captcha(event: types.ChatMemberUpdated):
    """
    处理新成员加入群组的验证逻辑
    """
    chat = event.chat
    member = event.new_chat_member

    # 基本条件验证
    validation_error = await validate_basic_conditions(event, chat, member)
    if validation_error:
        if member:
            log_context = LogContext(chat, member.user.id, member.user.username, member.user.full_name)
            logger.info(f"{log_context.log_prefix} | {validation_error}")
        return

    # 创建日志上下文
    log_context = LogContext(chat, member.user.id, member.user.username, member.user.full_name)

    # FIXME 大量请求可能来自很久之前的邀请链接，所以暂时跳过此项检查
    # 忽略发自管理员的邀请
    # if event.from_user and await manager.is_admin(chat, event.from_user):
    #     logger.info(f"{log_context.log_prefix} | 管理员邀请")
    #     return

    # 获取验证方法配置
    new_member_check_method = await get_verification_method(chat.id)
    now = event.date

    logger.info(
        f"{log_context.log_prefix} | 新成员加入 | 时间:{now} | 处理方式:{new_member_check_method}"
    )

    # 无操作模式
    if new_member_check_method == VerificationMode.NONE:
        logger.info(f"{log_context.log_prefix} | 无作为 | 新成员加入")
        return

    # 收紧新成员权限，禁止发送消息
    if not await restrict_member_permissions(chat, member.user.id):
        logger.error(f"{log_context.log_prefix} | 权限不足 | 无法限制用户")
        return

    logger.info(f"{log_context.log_prefix} | 权限限制成功")

    # 处理静默模式
    if new_member_check_method in [VerificationMode.SILENCE, VerificationMode.SLEEP_1WEEK, VerificationMode.SLEEP_2WEEKS]:
        if await handle_silence_mode(chat, member.user.id, member.user.full_name,
                                   new_member_check_method, log_context.log_prefix):
            return

    # 创建验证会话
    session = await create_verification_session(chat, member, event, now, log_context)
    if not session:
        return

    # 等待并检查成员状态
    updated_member = await wait_and_check_member_status(chat, member.user.id, log_context)
    if updated_member is None:
        return

    # 使用更新后的成员对象
    member = updated_member

    # 收集需要检查的文本
    strings_to_check = await get_member_info_for_check(member, session)

    # 执行安全检查
    if not await perform_security_checks(member, session, strings_to_check, log_context, now):
        return  # 检查失败，用户已被处理

    # 生成验证码消息
    message_content, reply_markup = await build_captcha_message(member, now)

    # 发送验证消息
    reply = await manager.bot.send_message(
        chat.id, message_content, parse_mode="markdown", reply_markup=reply_markup
    )
    logger.info(f"{log_context.log_prefix} | 已发送验证消息 | 消息ID:{reply.message_id}")

    # 创建临时会话并设置自动删除
    # At this point, member is guaranteed to be ChatMemberRestricted with user attribute
    if isinstance(member, (types.ChatMemberRestricted, types.ChatMemberMember)):
        member_id = member.user.id
    else:
        member_id = log_context.member_id
    await manager.lazy_session(
        chat.id,
        -1,
        member_id,
        "new_member_check",
        now + timedelta(seconds=DELETED_AFTER),
    )
    await manager.delete_message(chat, reply, now + timedelta(seconds=DELETED_AFTER))
    logger.debug(f"{log_context.log_prefix} | 设置验证消息自动删除 | 时长:{DELETED_AFTER}秒")


@manager.register("callback_query")
async def new_member_callback(query: types.CallbackQuery):
    """
    处理用户点击验证按钮后的逻辑
    """
    await process_callback_query(query)