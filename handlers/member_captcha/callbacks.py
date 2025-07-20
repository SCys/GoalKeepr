"""
成员验证回调处理模块
Member captcha callback handling module
"""

from datetime import timedelta
from typing import Optional
from aiogram import types
from loguru import logger

from manager import manager
from .config import SUPPORT_GROUP_TYPES, CallbackOperation, DEFAULT_BAN_DAYS
from .exceptions import LogContext
from .helpers import accepted_member, build_captcha_message


async def validate_callback_conditions(query: types.CallbackQuery) -> Optional[str]:
    """
    验证回调查询的基本条件
    
    Args:
        query: 回调查询对象
        
    Returns:
        Optional[str]: 如果验证失败，返回失败原因；成功返回None
    """
    msg = query.message
    if not msg:
        return "消息不存在"

    chat = msg.chat
    operator = query.from_user
    if not operator:
        return "操作者不存在"

    # 检查是否为支持的群组类型
    if chat.type not in SUPPORT_GROUP_TYPES:
        return "不支持的群组类型"

    if not isinstance(msg, types.Message):
        return "消息类型不正确"

    # 确保是机器人自己发送的消息
    user = msg.from_user
    if not user or not user.is_bot or manager.bot.id != user.id:
        return "非机器人消息"

    # 判断是否为验证消息（通过检查按钮布局）
    reply_markup = msg.reply_markup
    if (
        not reply_markup
        or reply_markup.inline_keyboard is None
        or len(reply_markup.inline_keyboard) != 2
        or len(reply_markup.inline_keyboard[0]) != 5
        or len(reply_markup.inline_keyboard[1]) != 2
    ):
        return "按钮布局不正确"

    data = query.data
    if not data:
        return "无回调数据"

    return None


async def handle_admin_operation(chat: types.Chat, msg: types.Message, data: str, 
                                log_prefix: str) -> bool:
    """
    处理管理员操作
    
    Args:
        chat: 聊天对象
        msg: 消息对象
        data: 回调数据
        log_prefix: 日志前缀
        
    Returns:
        bool: 是否成功处理
    """
    try:
        items = data.split("__")
        if len(items) != 3:
            logger.warning(f"{log_prefix} | 数据格式错误")
            return False
        
        member_id, _, op = items
        member_id = int(member_id)
        member = await manager.chat_member(chat, member_id)

        if not member:
            logger.error(f"{log_prefix} | 获取成员失败 | 成员ID:{member_id}")
            return False

        member_info = f"目标成员:{member_id}"
        if member.user.username:
            member_info += f"(@{member.user.username})"

        # 接受新成员
        if op == CallbackOperation.ACCEPT:
            await manager.delete_message(chat, msg)
            await accepted_member(chat, msg, member.user)
            logger.info(f"{log_prefix} | 管理员接受成员 | {member_info}")
            return True

        # 拒绝新成员
        elif op == CallbackOperation.REJECT:
            await manager.delete_message(chat, msg)
            await chat.ban(member_id, until_date=timedelta(days=DEFAULT_BAN_DAYS), revoke_messages=True)
            logger.warning(f"{log_prefix} | 管理员拒绝成员 | {member_info} | 封禁时长:{DEFAULT_BAN_DAYS}天")
            return True

        else:
            logger.warning(f"{log_prefix} | 未知操作类型 | 操作:{op}")
            return False
            
    except Exception as e:
        logger.error(f"{log_prefix} | 管理员操作处理失败 | 错误:{e}")
        return False


async def handle_self_verification(chat: types.Chat, msg: types.Message, data: str, 
                                 operator: types.User, log_prefix: str) -> bool:
    """
    处理用户自验证
    
    Args:
        chat: 聊天对象
        msg: 消息对象
        data: 回调数据
        operator: 操作者
        log_prefix: 日志前缀
        
    Returns:
        bool: 是否成功处理
    """
    try:
        # 验证成功
        if data.endswith(f"__{CallbackOperation.SUCCESS}"):
            await manager.delete_message(chat, msg, msg.date)
            await accepted_member(chat, msg, operator)
            logger.info(f"{log_prefix} | 验证成功 | 成员已通过验证")
            return True

        # 验证失败，重新加载验证码
        elif data.endswith(f"__{CallbackOperation.RETRY}"):
            content, reply_markup = await build_captcha_message(operator, msg.date)
            await msg.edit_text(content, parse_mode="markdown")
            await msg.edit_reply_markup(reply_markup=reply_markup)
            logger.info(f"{log_prefix} | 验证失败 | 已重新生成验证码")
            return True

        else:
            logger.warning(f"{log_prefix} | 未知验证操作 | 数据:{data}")
            return False
            
    except Exception as e:
        logger.error(f"{log_prefix} | 自验证处理失败 | 错误:{e}")
        return False


async def process_callback_query(query: types.CallbackQuery) -> None:
    """
    处理回调查询的主要逻辑
    
    Args:
        query: 回调查询对象
    """
    # 基本条件验证
    validation_error = await validate_callback_conditions(query)
    if validation_error:
        logger.debug(f"回调验证失败: {validation_error}")
        return

    # 在验证通过后，这些值都不会为None，使用断言确保类型安全
    msg = query.message
    operator = query.from_user
    data = query.data
    
    assert msg is not None and isinstance(msg, types.Message)
    assert operator is not None
    assert data is not None
    
    chat = msg.chat

    # 构建日志上下文
    callback_log_context = LogContext(chat, operator.id, operator.username, 
                                    operator.full_name, "[回调]")
    log_prefix = f"{callback_log_context.log_prefix} 消息:{msg.message_id}"

    # 检查操作者身份：管理员或本人
    is_admin = await manager.is_admin(chat, operator)
    is_self = data.startswith(f"{operator.id}__")

    if not any([is_admin, is_self]):
        logger.warning(f"{log_prefix} | 权限不足 | 非管理员且非本人操作")
        await query.answer(show_alert=False)
        return

    try:
        # 管理员操作处理
        if is_admin and not is_self:
            logger.debug(f"{log_prefix} | 管理员操作 | 数据:{data}")
            await handle_admin_operation(chat, msg, data, log_prefix)

        # 新成员自己操作处理
        elif is_self:
            logger.debug(f"{log_prefix} | 成员自验证 | 数据:{data}")
            await handle_self_verification(chat, msg, data, operator, log_prefix)

    except Exception as e:
        logger.error(f"{log_prefix} | 回调处理失败 | 错误:{e}")
    finally:
        await query.answer(show_alert=False)
