"""
成员验证回调处理模块
Member captcha callback handling module
"""

from datetime import timedelta, datetime, timezone
from typing import Optional, Any

from telethon import events
from loguru import logger

from manager import manager
from .config import SUPPORT_GROUP_TYPES, CallbackOperation, DEFAULT_BAN_DAYS, get_chat_type
from .exceptions import LogContext
from .helpers import accepted_member, build_captcha_message, get_callback_map, store_callback_map, delete_callback_map


def _user_full_name(user: Any) -> str:
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    return f"{first} {last}".strip() or ""


async def validate_callback_conditions(event: events.CallbackQuery.Event) -> Optional[str]:
    """
    验证回调查询的基本条件。event 为 Telethon CallbackQuery.Event。
    """
    msg = await event.get_message()
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


async def handle_admin_operation(chat: Any, msg: Any, data: str, log_prefix: str) -> bool:
    """处理管理员操作。"""
    try:
        items = data.split("__")
        if len(items) != 3:
            logger.warning(f"{log_prefix} | 数据格式错误")
            return False

        member_id, _, op = items
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
            await delete_callback_map(chat.id, msg.id)
            await accepted_member(chat, msg, user)
            logger.info(f"{log_prefix} | 管理员接受成员 | {member_info}")
            return True

        elif op == CallbackOperation.REJECT:
            await manager.delete_message(chat, msg)
            await delete_callback_map(chat.id, msg.id)
            await manager.client.edit_permissions(
                chat, member_id,
                view_messages=False,
                until_date=timedelta(days=DEFAULT_BAN_DAYS),
            )
            logger.warning(f"{log_prefix} | 管理员拒绝成员 | {member_info} | 封禁时长:{DEFAULT_BAN_DAYS}天")
            return True

        else:
            logger.warning(f"{log_prefix} | 未知操作类型 | 操作:{op}")
            return False

    except Exception as e:
        logger.error(f"{log_prefix} | 管理员操作处理失败 | 错误:{e}")
        return False


async def handle_self_verification(chat: Any, msg: Any, data: str, operator: Any, log_prefix: str) -> bool:
    """处理用户自验证。从 Redis 读取正确答案进行比较。"""
    try:
        parts = data.split("__")
        if len(parts) != 3:
            logger.warning(f"{log_prefix} | 自验证数据格式错误 | data={data}")
            return False

        chosen_key = parts[2]

        from .session import CaptchaSession
        session_data = await CaptchaSession.get(chat.id, operator.id)
        if not session_data:
            logger.warning(f"{log_prefix} | 自验证时 session 不存在")
            return False

        correct_answer = session_data.get("last_answer", "")

        if chosen_key == correct_answer:
            await manager.delete_message(chat, msg, getattr(msg, "date", None))
            await delete_callback_map(chat.id, msg.id)
            await accepted_member(chat, msg, operator)
            logger.info(f"{log_prefix} | 验证成功 | 成员已通过验证")
            return True

        else:
            from .config import DELETED_AFTER, CAPTCHA_MAX_RETRY

            # 递增重试次数，超过上限直接 Kick
            retry_count = await CaptchaSession.record_retry(chat.id, operator.id)
            if retry_count >= CAPTCHA_MAX_RETRY:
                await manager.delete_message(chat, msg)
                await delete_callback_map(chat.id, msg.id)
                await manager.lazy_session_delete(chat.id, operator.id, "new_member_check")
                await manager.client.edit_permissions(
                    chat, operator.id,
                    view_messages=False,
                    until_date=timedelta(seconds=60),
                )
                await manager.lazy_session(
                    chat.id, msg.id, operator.id, "unban_member",
                    datetime.now(timezone.utc) + timedelta(seconds=60),
                )
                logger.warning(
                    f"{log_prefix} | 重试次数超限Kick | "
                    f"retry={retry_count} max={CAPTCHA_MAX_RETRY}"
                )
                return True

            msg_date = getattr(msg, "date", None) or datetime.now(timezone.utc)
            content, buttons, answer_meta = await build_captcha_message(operator, msg_date)
            await manager.client.edit_message(chat, msg.id, content, parse_mode="md", buttons=buttons)

            await CaptchaSession.record_answer(
                chat.id, operator.id,
                icon=answer_meta["icon"],
                answer=answer_meta["answer"],
                options=answer_meta["options"],
            )

            # 更新 callback_map（消息内容变了，hash 也变了）
            await store_callback_map(chat.id, msg.id, answer_meta["callback_map"],
                                     ttl=DELETED_AFTER + 15)

            # 取消旧的超时踢人并重新计时
            await manager.lazy_session_delete(chat.id, operator.id, "new_member_check")
            await manager.lazy_session(
                chat.id, msg.id, operator.id, "new_member_check",
                msg_date + timedelta(seconds=DELETED_AFTER),
            )
            # 推迟消息自动删除时间
            await manager.delete_message(
                chat, msg,
                msg_date + timedelta(seconds=DELETED_AFTER),
            )

            logger.info(f"{log_prefix} | 验证失败 | 已重新生成验证码 | chosen={chosen_key} correct={correct_answer}")
            return True

    except Exception as e:
        logger.error(f"{log_prefix} | 自验证处理失败 | 错误:{e}")
        return False


async def process_callback_query(event: events.CallbackQuery.Event) -> None:
    """处理回调查询的主要逻辑。"""
    validation_error = await validate_callback_conditions(event)
    if validation_error:
        logger.debug(f"回调验证失败: {validation_error}")
        return

    msg = await event.get_message()
    operator = await event.get_sender()
    data = getattr(event, "_decoded_data", None) or (event.data.decode("utf-8") if isinstance(event.data, bytes) else event.data)

    if not msg or not operator or not data:
        return

    chat = await event.get_chat()
    log_context = LogContext(chat, operator.id, getattr(operator, "username", None), _user_full_name(operator), "[回调]")
    log_prefix = f"{log_context.log_prefix} 消息:{msg.id}"

    # 将 MD5 哈希解码为原始 callback data
    raw_data = data
    cb_map = await get_callback_map(chat.id, msg.id)
    if cb_map and data in cb_map:
        data = cb_map[data]
        logger.debug(f"{log_prefix} | 回调数据解码 | hash={raw_data} -> data={data}")
    else:
        logger.warning(f"{log_prefix} | callback_map 未命中 | hash={raw_data} | cb_map={cb_map}")

    is_admin = await manager.is_admin(chat, operator)
    is_self = data.startswith(f"{operator.id}__")

    if not (is_admin or is_self):
        logger.warning(f"{log_prefix} | 权限不足 | 非管理员且非本人操作")
        await event.answer()
        return

    # 按操作类型分流：O/X 为管理员操作，其余为自验证
    parts = data.split("__")
    is_admin_op = len(parts) == 3 and parts[2] in (CallbackOperation.ACCEPT, CallbackOperation.REJECT)

    try:
        if is_admin_op:
            if not is_admin:
                logger.warning(f"{log_prefix} | 非管理员尝试管理员操作")
                await event.answer()
                return
            logger.debug(f"{log_prefix} | 管理员操作 | 数据:{data}")
            await handle_admin_operation(chat, msg, data, log_prefix)
        elif is_self:
            logger.debug(f"{log_prefix} | 成员自验证 | 数据:{data}")
            await handle_self_verification(chat, msg, data, operator, log_prefix)
        else:
            logger.warning(f"{log_prefix} | 无法确定操作类型 | 数据:{data}")
    except Exception as e:
        logger.error(f"{log_prefix} | 回调处理失败 | 错误:{e}")
    finally:
        await event.answer()
