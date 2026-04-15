"""
成员验证主模块
Member captcha main module
"""

import asyncio
from datetime import timedelta, datetime, timezone
from telethon import events, types
from loguru import logger

from manager import manager, RedisUnavailableError
from .config import VerificationMode, DELETED_AFTER, MEMBER_CHECK_WAIT_TIME
from .exceptions import LogContext, PermissionError, PermissionError
from .validators import (
    validate_basic_conditions,
    get_verification_method,
    handle_silence_mode,
    create_verification_session,
)
from .security import (
    restrict_member_permissions,
    get_member_info_for_check,
    perform_security_checks,
)
from .security_mode import (
    incr_join_counter,
    should_enter_security_mode,
    is_security_mode,
    set_security_mode,
    get_auto_exit_minutes,
    add_to_new_members_list,
    SECURITY_MODE_PENDING_MINUTES,
)
from .helpers import (
    build_captcha_message,
    build_security_mode_pending_message,
    SECURITY_MODE_ENTERED_AUTO,
    SECURITY_MODE_ENTERED_MANUAL,
)
from .callbacks import process_callback_query
from .join_queue import publish_join_event


@manager.register("chat_member")
async def member_captcha(event: events.ChatAction.Event):
    """
    处理新成员加入群组的验证逻辑（快速路径）
    1. 基本验证
    2. 限制权限
    3. 发布入群事件
    4. 启动后台验证任务（异步执行后续耗时操作）
    5. 立即返回
    """
    chat = await event.get_chat()
    user = await event.get_user()
    if not user:
        logger.warning(f"chat_member 事件无用户信息 chat_id={event.chat_id}")
        await event.delete()
        return

    # 基本条件验证
    validation_error = await validate_basic_conditions(event, chat, user)
    if validation_error:
        log_context = LogContext(chat, user.id, user.username, _full_name(user))
        logger.info(f"{log_context.log_prefix} | {validation_error}")
        await event.delete()
        return

    log_context = LogContext(chat, user.id, user.username, _full_name(user))

    # 获取验证方法配置
    checker_type = await get_verification_method(chat.id)
    now = (
        event.action_message.date
        if getattr(event, "action_message", None)
        else getattr(event, "date", None)
    ) or datetime.now(timezone.utc)

    await event.delete()

    if checker_type == VerificationMode.NONE:
        logger.info(f"{log_context.log_prefix} | 无作为 | 新成员加入")
        return

    # 收紧新成员权限，禁止发送消息（核心安全操作，必须同步完成）
    try:
        await restrict_member_permissions(chat, user)
    except Exception as e:
        logger.error(f"{log_context.log_prefix} | 权限不足 | {e}")
        return

    logger.info(
        f"{log_context.log_prefix} | 新成员加入，权限限制成功 | 时间:{now} | 处理方式:{checker_type}"
    )

    # Redis 可用时：入群事件入队，用于统计和重复检测
    try:
        rdb = await manager.require_redis()
    except RedisUnavailableError:
        rdb = None
    if rdb:
        now_ts = (
            now.timestamp()
            if getattr(now, "timestamp", None)
            else datetime.now(timezone.utc).timestamp()
        )
        # publish_join_event 返回 False 表示去重跳过了
        if not await publish_join_event(
            rdb,
            chat.id,
            user.id,
            now_ts,
            checker_type,
            getattr(user, "username", None),
            _full_name(user),
        ):
            # 去重跳过，不启动后台任务
            logger.debug(f"{log_context.log_prefix} | 入群事件去重，跳过后续处理")
            return

    # 启动后台验证任务（异步执行耗时操作）
    asyncio.create_task(
        _process_member_verification_background(
            chat, user, now, checker_type, log_context, rdb is not None
        )
    )
    logger.debug(f"{log_context.log_prefix} | 已启动后台验证任务")
    # 立即返回，不阻塞事件处理


async def _process_member_verification_background(
    chat, user, now, checker_type, log_context, redis_available: bool
):
    """
    后台处理成员验证的耗时操作：
    1. 安全模式检测
    2. 等待3秒（让其他机器人先处理）
    3. 权限复查
    4. 安全检查（LLM+广告）
    5. 发送验证码
    6. 设置延迟踢出
    """
    try:
        rdb = None
        if redis_available:
            try:
                rdb = await manager.require_redis()
            except RedisUnavailableError:
                rdb = None

        # 仅在对新成员做验证码验证（BAN 模式）时参与安全模式计数与判断
        if rdb and checker_type == VerificationMode.BAN:
            await incr_join_counter(rdb, chat.id, user.id)
            if await should_enter_security_mode(rdb, chat.id):
                await set_security_mode(rdb, chat.id)
                # 进入安全模式后：按群设置调度自动解除，并发送带退出时间说明的提示（时间统一 UTC）
                auto_exit_minutes = await get_auto_exit_minutes(rdb, chat.id)
                now_utc = (
                    now.astimezone(timezone.utc)
                    if getattr(now, "tzinfo", None)
                    else now.replace(tzinfo=timezone.utc)
                )
                enter_time_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
                if auto_exit_minutes > 0:
                    exit_at = now_utc + timedelta(minutes=auto_exit_minutes)
                    await manager.lazy_session(
                        chat.id, 0, 0, "security_mode_auto_off", exit_at
                    )
                    exit_time_str = exit_at.strftime("%Y-%m-%d %H:%M")
                    try:
                        await manager.client.send_message(
                            chat.id,
                            SECURITY_MODE_ENTERED_AUTO.format(
                                enter_time=enter_time_str,
                                exit_minutes=auto_exit_minutes,
                                exit_time=exit_time_str,
                            ),
                            parse_mode="md",
                        )
                    except Exception as e:
                        logger.warning(
                            f"发送安全模式进入提示失败 chat_id={chat.id} err={e}"
                        )
                else:
                    try:
                        await manager.client.send_message(
                            chat.id,
                            SECURITY_MODE_ENTERED_MANUAL.format(
                                enter_time=enter_time_str
                            ),
                            parse_mode="md",
                        )
                    except Exception as e:
                        logger.warning(
                            f"发送安全模式进入提示失败 chat_id={chat.id} err={e}"
                        )
            if await is_security_mode(rdb, chat.id):
                # 安全模式：静默加入待审核列表，发一条待审核消息，30 分钟无管理员操作则踢出
                now_ts = now.timestamp()
                await add_to_new_members_list(rdb, chat.id, user.id, now_ts)
                content, buttons = build_security_mode_pending_message(user, now)
                reply = await manager.client.send_message(
                    chat.id, content, parse_mode="md", buttons=buttons
                )
                logger.info(
                    f"{log_context.log_prefix} | 安全模式 | 已加入待审核列表 | 消息ID:{reply.id}"
                )
                await manager.lazy_session(
                    chat.id,
                    reply.id,
                    user.id,
                    "security_mode_kick",
                    now + timedelta(minutes=SECURITY_MODE_PENDING_MINUTES),
                )
                return

        # 处理静默模式
        if checker_type in [
            VerificationMode.SILENCE,
            VerificationMode.SLEEP_1WEEK,
            VerificationMode.SLEEP_2WEEKS,
        ]:
            if await handle_silence_mode(
                chat, user.id, _full_name(user), checker_type, log_context.log_prefix
            ):
                return

        # 创建验证会话
        session = await create_verification_session(chat, user, now, log_context)
        if not session:
            return

        # 等待其他机器人检查（3秒）
        await asyncio.sleep(MEMBER_CHECK_WAIT_TIME)

        user_permissions = await manager.chat_member_permissions(chat, user.id)
        if not user_permissions:
            logger.error(f"{log_context.log_prefix} | 获取用户权限失败")
            return
        if not user_permissions.is_banned:
            logger.info(
                f"{log_context.log_prefix} | 用户被其他机器人或者管理员允许，已经解除限制"
            )
            return
        if user_permissions.has_left:
            logger.info(f"{log_context.log_prefix} | 用户已离开群组")
            return

        # 收集需要检查的文本
        check_list = await get_member_info_for_check(user, session)

        # 执行安全检查
        if not await perform_security_checks(
            user, session, check_list, log_context, now
        ):
            return

        # 生成验证码消息
        message_content, buttons = await build_captcha_message(user, now, chat.id)

        # 发送验证消息
        reply = await manager.client.send_message(
            chat.id, message_content, parse_mode="md", buttons=buttons
        )
        logger.info(f"{log_context.log_prefix} | 已发送验证消息 | 消息ID:{reply.id}")

        await manager.lazy_session(
            chat.id,
            reply.id,
            user.id,
            "new_member_check",
            now + timedelta(seconds=12),
        )
        await manager.delete_message(
            chat, reply, now + timedelta(seconds=DELETED_AFTER)
        )
        logger.debug(
            f"{log_context.log_prefix} | 设置验证超时 | 时长:{12}秒"
        )

    except Exception as e:
        logger.error(f"{log_context.log_prefix} | 后台验证任务失败 | 错误:{e}")


def _full_name(user: types.User) -> str:
    parts = [user.first_name or "", user.last_name or ""]
    return " ".join(x for x in parts if x).strip() or ""


@manager.register("callback_query")
async def new_member_callback(event: events.CallbackQuery.Event):
    """处理用户点击验证按钮后的逻辑"""
    await process_callback_query(event)
