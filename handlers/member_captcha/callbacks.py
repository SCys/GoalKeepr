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
        return "message not found"

    chat = await event.get_chat()
    operator = await event.get_sender()
    if not operator:
        return "operator not found"

    if get_chat_type(chat) not in SUPPORT_GROUP_TYPES:
        return "unsupported group type"

    # Telethon: msg.out means sent by the bot itself
    if not getattr(msg, "out", False):
        return "not a bot message"

    # Verify it's a captcha message by button layout: 2 rows, first row 5 buttons, second row 2 buttons
    markup = getattr(msg, "reply_markup", None)
    if not markup or not getattr(markup, "rows", None):
        return "invalid button layout"
    rows = markup.rows
    if len(rows) != 2:
        return "invalid button layout"
    if len(rows[0].buttons) != 5 or len(rows[1].buttons) != 2:
        return "invalid button layout"

    data = event.data
    if data is None:
        return "no callback data"
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")

    # attach decoded data to event for downstream use
    setattr(event, "_decoded_data", data)
    return None


async def handle_admin_operation(chat: Any, msg: Any, data: str, log_prefix: str) -> bool:
    """处理管理员操作。"""
    try:
        items = data.split("__")
        if len(items) != 3:
            logger.warning(f"{log_prefix} | invalid data format")
            return False

        member_id, _, op = items
        member_id = int(member_id)
        try:
            user = await manager.client.get_entity(member_id)
        except Exception as e:
            logger.error(f"{log_prefix} | failed to fetch member | member_id:{member_id} | {e}")
            return False

        member_info = f"target:{member_id}"
        if getattr(user, "username", None):
            member_info += f"(@{user.username})"

        if op == CallbackOperation.ACCEPT:
            await manager.delete_message(chat, msg)
            await delete_callback_map(chat.id, msg.id)
            from .session import CaptchaSession
            await CaptchaSession.delete(chat.id, member_id)
            await accepted_member(chat, msg, user)
            logger.info(f"{log_prefix} | admin accepted member | {member_info}")
            return True

        elif op == CallbackOperation.REJECT:
            await manager.delete_message(chat, msg)
            await delete_callback_map(chat.id, msg.id)
            from .session import CaptchaSession
            await CaptchaSession.delete(chat.id, member_id)
            await manager.client.edit_permissions(
                chat, member_id,
                view_messages=False,
                until_date=timedelta(days=DEFAULT_BAN_DAYS),
            )
            logger.warning(f"{log_prefix} | admin rejected member | {member_info} | ban_days:{DEFAULT_BAN_DAYS}")
            return True

        else:
            logger.warning(f"{log_prefix} | unknown operation | op:{op}")
            return False

    except Exception as e:
        logger.error(f"{log_prefix} | admin operation failed | error:{e}")
        return False


async def handle_self_verification(chat: Any, msg: Any, data: str, operator: Any, log_prefix: str) -> bool:
    """处理用户自验证。从 Redis 读取正确答案进行比较。"""
    try:
        parts = data.split("__")
        if len(parts) != 3:
            logger.warning(f"{log_prefix} | invalid self-verify data | data={data}")
            return False

        chosen_key = parts[2]

        from .session import CaptchaSession
        session_data = await CaptchaSession.get(chat.id, operator.id)
        if not session_data:
            logger.warning(f"{log_prefix} | session not found during self-verification")
            return False

        correct_answer = session_data.get("last_answer", "")

        if chosen_key == correct_answer:
            await manager.delete_message(chat, msg, getattr(msg, "date", None))
            await delete_callback_map(chat.id, msg.id)
            await CaptchaSession.delete(chat.id, operator.id)
            await accepted_member(chat, msg, operator)
            logger.info(f"{log_prefix} | verification passed | member accepted")
            return True

        else:
            from .config import DELETED_AFTER, CAPTCHA_MAX_RETRY

            # 递增重试次数，超过上限直接 Kick
            retry_count = await CaptchaSession.record_retry(chat.id, operator.id)
            if retry_count >= CAPTCHA_MAX_RETRY:
                await manager.delete_message(chat, msg)
                await delete_callback_map(chat.id, msg.id)
                await CaptchaSession.delete(chat.id, operator.id)
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
                    f"{log_prefix} | retry limit exceeded, kicking | "
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

            logger.info(f"{log_prefix} | verification failed | regenerated captcha | chosen={chosen_key} correct={correct_answer}")
            return True

    except Exception as e:
        logger.error(f"{log_prefix} | self-verification failed | error:{e}")
        return False


async def process_callback_query(event: events.CallbackQuery.Event) -> None:
    """处理回调查询的主要逻辑。"""
    validation_error = await validate_callback_conditions(event)
    if validation_error:
        logger.debug(f"callback validation failed: {validation_error}")
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
        logger.debug(f"{log_prefix} | callback data decoded | hash={raw_data} -> data={data}")
    else:
        logger.warning(f"{log_prefix} | callback_map miss | hash={raw_data}")
        # 验证已过期，提示用户
        try:
            await event.answer("验证已过期，请重新入群获取新的验证。", alert=True)
        except Exception:
            pass
        return

    is_admin = await manager.is_admin(chat, operator)
    is_self = data.startswith(f"{operator.id}__")

    if not (is_admin or is_self):
        logger.warning(f"{log_prefix} | insufficient permissions | not admin and not self")
        await event.answer()
        return

    # 按操作类型分流：O/X 为管理员操作，其余为自验证
    parts = data.split("__")
    is_admin_op = len(parts) == 3 and parts[2] in (CallbackOperation.ACCEPT, CallbackOperation.REJECT)

    try:
        if is_admin_op:
            if not is_admin:
                logger.warning(f"{log_prefix} | non-admin attempted admin operation")
                await event.answer()
                return
            logger.debug(f"{log_prefix} | admin operation | data:{data}")
            await handle_admin_operation(chat, msg, data, log_prefix)
        elif is_self:
            logger.debug(f"{log_prefix} | member self-verification | data:{data}")
            await handle_self_verification(chat, msg, data, operator, log_prefix)
        else:
            logger.warning(f"{log_prefix} | cannot determine operation type | data:{data}")
    except Exception as e:
        logger.error(f"{log_prefix} | callback processing failed | error:{e}")
    finally:
        await event.answer()
