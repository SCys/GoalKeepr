import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import types
from aiogram.enums import ChatMemberStatus
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from loguru import logger

from manager import manager
from manager.group import settings_get
from utils.advertising import check_advertising

from ..utils.llm import check_spams_with_llm
from .helpers import accepted_member, build_captcha_message
from .session import Session

# 常量配置
SUPPORT_GROUP_TYPES = ["supergroup", "group"]
DELETED_AFTER = 30
MEMBER_CHECK_WAIT_TIME = 3  # 等待其他机器人检查的时间
LLM_CHECK_TIMEOUT = 20  # LLM检查超时时间
DEFAULT_BAN_DAYS = 30  # 默认封禁天数
EVENT_EXPIRY_SECONDS = 60  # 事件过期时间

RE_TG_NAME = re.compile(r"^@[a-zA-Z0-9_]{5,32}$")


class MemberVerificationError(Exception):
    """成员验证相关错误"""

    pass


class LogContext:
    """日志上下文管理器"""

    def __init__(
        self,
        chat: types.Chat,
        member_id: int,
        member_name: Optional[str] = None,
        member_fullname: Optional[str] = None,
        prefix: str = "[验证]",
    ):
        self.chat = chat
        self.member_id = member_id
        self.member_name = member_name
        self.member_fullname = member_fullname
        self.prefix = prefix
        self._log_prefix = None

    @property
    def log_prefix(self) -> str:
        if self._log_prefix is None:
            self._log_prefix = f"{self.prefix} 群组:{self.chat.id}({self.chat.title}) 成员:{self.member_id}"
            if self.member_name:
                self._log_prefix += f"(@{self.member_name})"
            if self.member_fullname:
                self._log_prefix += f" 名称:{self.member_fullname}"
        return self._log_prefix


async def restrict_member_permissions(chat: types.Chat, member_id: int, until_date: Optional[timedelta] = None) -> bool:
    """
    限制成员权限的通用函数

    Args:
        chat: 聊天对象
        member_id: 成员ID
        until_date: 限制到期时间

    Returns:
        bool: 是否成功限制
    """
    try:
        permissions = types.ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
        )
        return await chat.restrict(member_id, permissions=permissions, until_date=until_date)
    except Exception as e:
        logger.error(f"限制成员 {member_id} 权限失败: {e}")
        return False


async def validate_basic_conditions(event: types.ChatMemberUpdated, chat: types.Chat, member) -> Optional[str]:
    """
    验证基本条件

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


async def get_member_info_for_check(member, session: Session):
    """
    获取需要检查的成员信息

    Returns:
        List[str]: 需要检查的文本列表
    """
    strings_to_check = [member.user.full_name]

    # 如果有用户名，获取额外信息
    if member.user.username:
        session.member_username = member.user.username

        # 检查用户bio
        user_info = await manager.get_user_extra_info(member.user.username)
        if user_info and user_info.get("bio"):
            bio = user_info["bio"]
            strings_to_check.append(bio)
            session.member_bio = bio
            logger.debug(f"获取用户Bio: {bio}")

    return strings_to_check


async def perform_security_checks(member, session: Session, strings_to_check, log_context: LogContext, now: datetime) -> bool:
    """
    执行安全检查（LLM检查和广告检查）

    Returns:
        bool: True表示检查通过，False表示发现问题需要封禁
    """
    # LLM检查
    try:
        llm_start_time = datetime.now()
        logger.debug(f"{log_context.log_prefix} | 开始LLM检查")

        spams_result = await asyncio.wait_for(
            check_spams_with_llm([member], session, strings_to_check, now), timeout=LLM_CHECK_TIMEOUT
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
    except Exception as e:
        logger.exception(f"{log_context.log_prefix} | LLM检查失败 | 错误:{e}")

    # 广告检查
    for txt in strings_to_check:
        contains_adv, matched_word = check_advertising(txt)

        if contains_adv:
            await _handle_advertising_violation(
                log_context.chat, member.user.id, matched_word or "未知", session, log_context.log_prefix
            )
            return False

    return True


async def _handle_advertising_violation(chat: types.Chat, member_id: int, matched_word: str, session: Session, log_prefix: str):
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


async def handle_silence_mode(
    chat: types.Chat, member_id: int, member_fullname: str, check_method: str, log_prefix: str
) -> bool:
    """
    处理静默模式

    Returns:
        bool: 是否成功处理
    """
    if check_method == "silence":
        await manager.send(
            chat.id,
            f"新成员 [{member_fullname}](tg://user?id={member_id}) 加入群组，请管理员手动解封。"
            f"Welcome to the group, please wait for admin to unmute you.",
            parse_mode="markdown",
        )
        logger.info(f"{log_prefix} | 静默处理 | 新成员加入")
        return True

    elif check_method == "sleep_1week":
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

    elif check_method == "sleep_2weeks":
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

    rdb = await manager.get_redis()
    if not rdb:
        logger.warning("Redis connection failed")
        return

    new_member_check_method = await settings_get(rdb, chat.id, "new_member_check_method", "ban")

    now = event.date
    logger.info(f"{log_context.log_prefix} | 新成员加入 | 时间:{now} | 处理方式:{new_member_check_method}")

    # none
    if new_member_check_method == "none":
        logger.info(f"{log_context.log_prefix} | 无作为 | 新成员加入")
        return

    # 收紧新成员权限，禁止发送消息
    if not await restrict_member_permissions(chat, member.user.id):
        logger.error(f"{log_context.log_prefix} | 权限不足 | 无法限制用户")
        return

    logger.info(f"{log_context.log_prefix} | 权限限制成功")

    # 处理静默模式
    if new_member_check_method in ["silence", "sleep_1week", "sleep_2weeks"]:
        if await handle_silence_mode(
            chat, member.user.id, member.user.full_name, new_member_check_method, log_context.log_prefix
        ):
            return

    # 获取会话信息 - 由于之前已经验证过member类型，这里进行类型转换
    session = await Session.get(chat, member, event, now)  # type: ignore
    if not session:
        logger.error(f"{log_context.log_prefix} | 会话创建失败")
        return

    # 等待其他机器人检查
    await asyncio.sleep(MEMBER_CHECK_WAIT_TIME)
    if _member := await manager.chat_member(chat, member.user.id):
        # 忽略未被限制的成员
        if not isinstance(_member, types.ChatMemberRestricted):
            status_name = ChatMemberStatus(getattr(_member, "status", "unknown")).name
            logger.info(f"{log_context.log_prefix} | 用户状态变更 | 当前状态:{status_name}")
            return

        # 忽略可以发送消息的成员
        if _member.can_send_messages:
            logger.info(f"{log_context.log_prefix} | 用户已有发言权限")
            return

        member = _member
    else:
        logger.error(f"{log_context.log_prefix} | 获取成员信息失败")

    # 收集需要检查的文本
    strings_to_check = await get_member_info_for_check(member, session)

    # 执行安全检查
    if not await perform_security_checks(member, session, strings_to_check, log_context, now):
        return  # 检查失败，用户已被处理

    # 生成验证码消息
    message_content, reply_markup = await build_captcha_message(member, now)

    # 发送验证消息
    reply = await manager.bot.send_message(chat.id, message_content, parse_mode="markdown", reply_markup=reply_markup)
    logger.info(f"{log_context.log_prefix} | 已发送验证消息 | 消息ID:{reply.message_id}")

    # 创建临时会话并设置自动删除
    await manager.lazy_session(
        chat.id,
        -1,
        member.user.id,
        "new_member_check",
        now + timedelta(seconds=DELETED_AFTER),
    )
    await manager.delete_message(chat, reply, now + timedelta(seconds=DELETED_AFTER))
    logger.debug(f"{log_context.log_prefix} | 设置验证消息自动删除 | 时长:{DELETED_AFTER}秒")


async def validate_callback_conditions(query: types.CallbackQuery) -> Optional[str]:
    """
    验证回调查询的基本条件

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


async def handle_admin_operation(chat: types.Chat, msg: types.Message, data: str, log_prefix: str) -> bool:
    """
    处理管理员操作

    Returns:
        bool: 是否成功处理
    """
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
    if op == "O":
        await manager.delete_message(chat, msg)
        await accepted_member(chat, msg, member.user)
        logger.info(f"{log_prefix} | 管理员接受成员 | {member_info}")
        return True

    # 拒绝新成员
    elif op == "X":
        await manager.delete_message(chat, msg)
        await chat.ban(member_id, until_date=timedelta(days=DEFAULT_BAN_DAYS), revoke_messages=True)
        logger.warning(f"{log_prefix} | 管理员拒绝成员 | {member_info} | 封禁时长:{DEFAULT_BAN_DAYS}天")
        return True

    else:
        logger.warning(f"{log_prefix} | 未知操作类型 | 操作:{op}")
        return False


async def handle_self_verification(
    chat: types.Chat, msg: types.Message, data: str, operator: types.User, log_prefix: str
) -> bool:
    """
    处理用户自验证

    Returns:
        bool: 是否成功处理
    """
    # 验证成功
    if data.endswith("__!"):
        await manager.delete_message(chat, msg, msg.date)
        await accepted_member(chat, msg, operator)
        logger.info(f"{log_prefix} | 验证成功 | 成员已通过验证")
        return True

    # 验证失败，重新加载验证码
    elif data.endswith("__?"):
        content, reply_markup = await build_captcha_message(operator, msg.date)
        await msg.edit_text(content, parse_mode="markdown")
        await msg.edit_reply_markup(reply_markup=reply_markup)
        logger.info(f"{log_prefix} | 验证失败 | 已重新生成验证码")
        return True

    else:
        logger.warning(f"{log_prefix} | 未知验证操作 | 数据:{data}")
        return False


@manager.register("callback_query")
async def new_member_callback(query: types.CallbackQuery):
    """
    处理用户点击验证按钮后的逻辑
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
    callback_log_context = LogContext(chat, operator.id, operator.username, operator.full_name, "[回调]")
    log_prefix = f"{callback_log_context.log_prefix} 消息:{msg.message_id}"

    # 检查操作者身份：管理员或本人
    is_admin = await manager.is_admin(chat, operator)
    is_self = data.startswith(f"{operator.id}__")

    if not any([is_admin, is_self]):
        logger.warning(f"{log_prefix} | 权限不足 | 非管理员且非本人操作")
        await query.answer(show_alert=False)
        return

    # 管理员操作处理
    if is_admin and not is_self:
        logger.debug(f"{log_prefix} | 管理员操作 | 数据:{data}")
        await handle_admin_operation(chat, msg, data, log_prefix)

    # 新成员自己操作处理
    elif is_self:
        logger.debug(f"{log_prefix} | 成员自验证 | 数据:{data}")
        await handle_self_verification(chat, msg, data, operator, log_prefix)

    await query.answer(show_alert=False)
