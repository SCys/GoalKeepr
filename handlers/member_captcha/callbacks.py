"""
成员验证回调处理模块
Member captcha callback handling module
"""

from datetime import timedelta, datetime, timezone
from typing import Optional, Any

from telethon import events
from loguru import logger

from manager import manager, RedisUnavailableError
from .config import (
    SUPPORT_GROUP_TYPES,
    CallbackOperation,
    DEFAULT_BAN_DAYS,
    get_chat_type,
)
from .exceptions import LogContext
from .helpers import (
    accepted_member,
    build_captcha_message,
    load_captcha_answer,
    delete_captcha_answer,
    SECURITY_MODE_CALLBACK_PREFIX,
)
from .security_mode import remove_from_new_members_list, is_in_new_members_list


def _user_full_name(user: Any) -> str:
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    return f"{first} {last}".strip() or ""


async def _resolve_callback_message(event: events.CallbackQuery.Event) -> Optional[Any]:
    """
    兼容不同 Telethon 事件对象：优先使用 event.message，
    不存在时回退到 await event.get_message()。
    """
    msg = getattr(event, "message", None)
    if msg is not None:
        return msg

    getter = getattr(event, "get_message", None)
    if callable(getter):
        try:
            return await getter()
        except Exception as e:
            logger.debug(f"获取回调消息失败: {e}")
    return None


async def validate_callback_conditions(
    event: events.CallbackQuery.Event,
) -> Optional[str]:
    """
    验证回调查询的基本条件。event 为 Telethon CallbackQuery.Event。
    """
    msg = await _resolve_callback_message(event)
    if not msg:
        return "消息不存在"

    chat = await event.get_chat()
    operator = await event.get_sender()
    if not operator:
        return "操作者不存在"

    if get_chat_type(chat) not in SUPPORT_GROUP_TYPES:
        return "不支持的群组类型"

    # 确保是机器人自己发送的消息（Telethon 中 message.out 表示己方发出）
    if not getattr(msg, "out", False):
        return "非机器人消息"

    # 判断是否为验证消息（通过按钮布局：2 行，首行 5 按钮，次行 2 按钮）
    markup = getattr(msg, "reply_markup", None)
    if not markup or not getattr(markup, "rows", None):
        return "按钮布局不正确"
    rows = markup.rows
    if len(rows) != 2:
        return "按钮布局不正确"
    if len(rows[0].buttons) != 5 or len(rows[1].buttons) != 2:
        return "按钮布局不正确"

    data = event.data
    if data is None:
        return "无回调数据"
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")

    # 把解码后的 data 挂到 event 上供后续使用
    setattr(event, "_decoded_data", data)
    return None


async def handle_admin_operation(
    chat: Any, msg: Any, data: str, log_prefix: str
) -> bool:
    """处理管理员操作。"""
    try:
        items = data.split("_")
        if len(items) != 4:
            logger.warning(f"{log_prefix} | 数据格式错误")
            return False

        member_id, _, action_type, op = items
        if action_type != "admin":
            logger.warning(f"{log_prefix} | 非管理员操作数据: {data}")
            return False
        member_id = int(member_id)
        try:
            user = await manager.client.get_entity(member_id)
        except Exception as e:
            logger.error(f"{log_prefix} | 获取成员失败 | 成员ID:{member_id} | {e}")
            return False

        member_info = f"目标成员:{member_id}"
        if getattr(user, "username", None):
            member_info += f"(@{user.username})"

        if op == CallbackOperation.ACCEPT:
            await manager.delete_message(chat, msg)
            await accepted_member(chat, msg, user)
            logger.info(f"{log_prefix} | 管理员接受成员 | {member_info}")
            return True

        elif op == CallbackOperation.REJECT:
            await manager.delete_message(chat, msg)
            await manager.client.edit_permissions(
                chat,
                member_id,
                view_messages=False,
                until_date=timedelta(days=DEFAULT_BAN_DAYS),
            )
            logger.warning(
                f"{log_prefix} | 管理员拒绝成员 | {member_info} | 封禁时长:{DEFAULT_BAN_DAYS}天"
            )
            return True

        else:
            logger.warning(f"{log_prefix} | 未知操作类型 | 操作:{op}")
            return False

    except Exception as e:
        logger.error(f"{log_prefix} | 管理员操作处理失败 | 错误:{e}")
        return False


async def handle_self_verification(
    chat: Any, msg: Any, data: str, operator: Any, log_prefix: str
) -> bool:
    """处理用户自验证（从 Redis 读取正确答案进行验证）。"""
    try:
        # 解析 data: "member_id_timestamp_icon_key"
        parts = data.split("_")
        if len(parts) != 3:
            logger.warning(f"{log_prefix} | 验证回调数据格式错误: {data}")
            return False

        member_id = int(parts[0])
        clicked_key = parts[2]

        chat_id = chat.id if hasattr(chat, "id") else chat

        correct_key = await load_captcha_answer(chat_id, member_id)
        if not correct_key:
            logger.warning(f"{log_prefix} | 验证答案已过期或不存在，可能已超时")
            # 答案不存在，视为验证流程出错，重新生成验证码
            msg_date = getattr(msg, "date", None) or datetime.now(timezone.utc)
            content, buttons = await build_captcha_message(operator, msg_date, chat_id)
            await manager.client.edit_message(
                chat, msg.id, content, parse_mode="md", buttons=buttons
            )
            return True

        # 验证后立即删除答案，防止重复使用
        await delete_captcha_answer(chat_id, member_id)

        if clicked_key == correct_key:
            # 验证成功
            await manager.delete_message(chat, msg, getattr(msg, "date", None))
            await accepted_member(chat, msg, operator)
            logger.info(f"{log_prefix} | 验证成功 | 成员已通过验证")
            return True
        else:
            # 验证失败，重新生成验证码
            logger.info(
                f"{log_prefix} | 验证失败 | 点击:{clicked_key} 正确答案:{correct_key}"
            )
            msg_date = getattr(msg, "date", None) or datetime.now(timezone.utc)
            content, buttons = await build_captcha_message(operator, msg_date, chat_id)
            await manager.client.edit_message(
                chat, msg.id, content, parse_mode="md", buttons=buttons
            )
            return True

    except Exception as e:
        logger.exception(f"{log_prefix} | 自验证处理失败 | 错误:{e}")
        return False


async def handle_security_mode_admin_operation(
    chat: Any, msg: Any, data: str, log_prefix: str
) -> bool:
    """安全模式下的管理员通过/拒绝。data 格式: sm__member_id__ts__O 或 sm__member_id__ts__X。"""
    try:
        # 验证消息是否由机器人自己发送（防止回调注入）
        if not getattr(msg, "out", False):
            logger.warning(f"{log_prefix} | 安全模式回调：非机器人消息，拒绝处理")
            return False

        if not data.startswith(SECURITY_MODE_CALLBACK_PREFIX):
            return False
        parts = data[len(SECURITY_MODE_CALLBACK_PREFIX) :].split("_")
        # 格式应为: sm_{member_id}_{ts}_O/X → 去掉前缀后分割为3部分
        if len(parts) != 3:
            logger.warning(
                f"{log_prefix} | 安全模式回调数据格式错误: {data} | parts: {parts}"
            )
            return False
        member_id = int(parts[0])
        op = parts[2]  # 操作在第三部分

        try:
            rdb = await manager.require_redis()
        except RedisUnavailableError:
            logger.warning(f"{log_prefix} | Redis 不可用，安全模式操作跳过")
            return False

        # 验证成员是否在待审核列表中
        if not await is_in_new_members_list(rdb, chat.id, member_id):
            logger.warning(
                f"{log_prefix} | 成员 {member_id} 不在待审核列表中，可能已被处理"
            )
            return False

        try:
            user = await manager.client.get_entity(member_id)
        except Exception as e:
            logger.error(f"{log_prefix} | 获取成员失败 | 成员ID:{member_id} | {e}")
            return False

        if op == CallbackOperation.ACCEPT:
            await remove_from_new_members_list(rdb, chat.id, member_id)
            await manager.delete_message(chat, msg)
            await accepted_member(chat, msg, user)
            await manager.lazy_session_delete(chat.id, member_id, "security_mode_kick")
            logger.info(f"{log_prefix} | 安全模式管理员通过 | 成员:{member_id}")
            return True
        elif op == CallbackOperation.REJECT:
            await remove_from_new_members_list(rdb, chat.id, member_id)
            await manager.delete_message(chat, msg)
            await manager.client.edit_permissions(
                chat,
                member_id,
                view_messages=False,
                until_date=timedelta(days=DEFAULT_BAN_DAYS),
            )
            await manager.lazy_session_delete(chat.id, member_id, "security_mode_kick")
            logger.warning(
                f"{log_prefix} | 安全模式管理员拒绝 | 成员:{member_id} | 封禁{DEFAULT_BAN_DAYS}天"
            )
            return True
        return False
    except Exception as e:
        logger.error(f"{log_prefix} | 安全模式管理员操作失败 | 错误:{e}")
        return False


async def process_callback_query(event: events.CallbackQuery.Event) -> None:
    """处理回调查询的主要逻辑。"""
    msg = await _resolve_callback_message(event)
    operator = await event.get_sender()
    data = getattr(event, "_decoded_data", None) or (
        event.data.decode("utf-8") if isinstance(event.data, bytes) else event.data
    )
    if not msg or not operator or not data:
        return

    chat = await event.get_chat()
    log_context = LogContext(
        chat,
        operator.id,
        getattr(operator, "username", None),
        _user_full_name(operator),
        "[回调]",
    )
    log_prefix = f"{log_context.log_prefix} 消息:{msg.id}"

    # 安全模式回调：仅管理员，且 data 以 sm__ 开头
    if data.startswith(SECURITY_MODE_CALLBACK_PREFIX):
        if get_chat_type(chat) not in SUPPORT_GROUP_TYPES:
            await event.answer()
            return
        if not await manager.is_admin(chat, operator):
            logger.warning(f"{log_prefix} | 安全模式回调仅限管理员")
            await event.answer()
            return
        try:
            await handle_security_mode_admin_operation(chat, msg, data, log_prefix)
        except Exception as e:
            logger.error(f"{log_prefix} | 安全模式回调处理失败 | 错误:{e}")
        await event.answer()
        return

    validation_error = await validate_callback_conditions(event)
    if validation_error:
        logger.debug(f"回调验证失败: {validation_error}")
        return

    is_admin = await manager.is_admin(chat, operator)
    is_self = data.startswith(f"{operator.id}_")

    if not (is_admin or is_self):
        logger.warning(f"{log_prefix} | 权限不足 | 非管理员且非本人操作")
        await event.answer()
        return

    try:
        if is_admin and not is_self:
            logger.debug(f"{log_prefix} | 管理员操作 | 数据:{data}")
            await handle_admin_operation(chat, msg, data, log_prefix)
        elif is_self:
            logger.debug(f"{log_prefix} | 成员自验证 | 数据:{data}")
            await handle_self_verification(chat, msg, data, operator, log_prefix)
    except Exception as e:
        logger.error(f"{log_prefix} | 回调处理失败 | 错误:{e}")
    finally:
        await event.answer()
