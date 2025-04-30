import asyncio
import re
from datetime import datetime, timedelta, timezone

from aiogram import types
from aiogram.enums import ChatMemberStatus
from aiogram.filters import IS_MEMBER, IS_NOT_MEMBER, ChatMemberUpdatedFilter
from loguru import logger

from manager import manager
from manager.group import settings_get
from utils.advertising import check_advertising

from ..utils.llm import check_spams_with_llm
from .helpers import accepted_member, build_captcha_message, HANDLE_PERMISSIONS
from .session import Session

SUPPORT_GROUP_TYPES = ["supergroup", "group"]
DELETED_AFTER = 30
RE_TG_NAME = re.compile(r"^@[a-zA-Z0-9_]{5,32}$")


@manager.register("chat_member", ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def member_captcha(event: types.ChatMemberUpdated):
    """
    处理新成员加入群组的验证逻辑
    """
    chat = event.chat
    member = event.new_chat_member

    # 检查是否为支持的群组类型
    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    # 确保成员对象存在
    if not member:
        return

    member_id = member.user.id
    member_name = member.user.username
    member_fullname = member.user.full_name

    # 构建日志前缀，包含群组和成员信息
    log_prefix = f"[验证] 群组:{chat.id}({chat.title}) 成员:{member_id}"
    if member_name:
        log_prefix += f"(@{member_name})"
    log_prefix += f" 名称:{member_fullname}"

    # 必须是普通成员或者被限制的成员
    if not isinstance(member, (types.ChatMemberRestricted, types.ChatMemberMember)):
        logger.info(f"{log_prefix} | 状态不符 | 当前状态:{member.status}")
        return

    # 忽略太久之前的事件
    if datetime.now(timezone.utc) > event.date + timedelta(seconds=60):
        logger.warning(f"{log_prefix} | 事件过期 | 事件时间:{event.date}")
        return

    # FIXME 大量请求可能来自很久之前的邀请链接，所以暂时跳过此项检查
    # 忽略发自管理员的邀请
    # if event.from_user and await manager.is_admin(chat, event.from_user):
    #     logger.info(f"{log_prefix} | 管理员邀请")
    #     return

    rdb = await manager.get_redis()
    if not rdb:
        logger.warning("Redis connection failed")
        return

    new_member_check_method = await settings_get(
        rdb, chat.id, "new_member_check_method", "ban"
    )

    now = event.date
    logger.info(
        f"{log_prefix} | 新成员加入 | 时间:{now} | 处理方式:{new_member_check_method}"
    )

    # none
    if new_member_check_method == "none":
        logger.info(f"{log_prefix} | 无作为 | 新成员加入")
        return

    # 收紧新成员权限，禁止发送消息
    try:
        if not await chat.restrict(
            member_id,
            permissions=HANDLE_PERMISSIONS,
        ):
            logger.error(f"{log_prefix} | 权限不足 | 无法限制用户")
            return
    except Exception as e:
        logger.error(f"{log_prefix} | 限制失败 | 错误:{e}")
        return

    logger.info(f"{log_prefix} | 权限限制成功")

    # 手动解封
    if new_member_check_method == "silence":
        # 通告15秒并且告知管理员可以通过 /group_setting 命令修改设置
        await manager.send(
            chat.id,
            f"新成员 {member_id} 加入群组，请管理员手动解封\n\n"
            f"管理员可以通过 /group_setting 命令修改设置",
            auto_deleted_at=event.date + timedelta(seconds=15),
        )
        logger.info(f"{log_prefix} | 静默处理 | 新成员加入")
        return

    # 静默2周
    elif new_member_check_method == "sleep_2weeks":
        if not await chat.restrict(
            member_id,
            permissions=types.ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            ),
            until_date=timedelta(days=14),
        ):
            logger.error(f"{log_prefix} | 权限不足 | 无法限制用户")
            return

        await manager.send(
            chat.id,
            f"新成员 {member_id} 加入群组，已静默2周。\n\n"
            f"管理员可以通过 /group_setting 命令修改设置",
            auto_deleted_at=event.date + timedelta(seconds=15),
        )
        logger.info(f"{log_prefix} | 静默2周 | 新成员加入")
        return

    # 获取会话信息
    session = await Session.get(chat, member, event, now)
    if not session:
        logger.error(f"{log_prefix} | 会话创建失败")
        return

    # 等待其他机器人检查
    await asyncio.sleep(3)
    if _member := await manager.chat_member(chat, member_id):
        # 忽略未被限制的成员
        # if _member.status != ChatMemberStatus.RESTRICTED:
        if not isinstance(_member, types.ChatMemberRestricted):
            status_name = ChatMemberStatus(member.status).name
            logger.info(f"{log_prefix} | 用户状态变更 | 当前状态:{status_name}")
            return

        # 忽略可以发送消息的成员
        if _member.can_send_messages:
            logger.info(f"{log_prefix} | 用户已有发言权限")
            return

        member = _member
    else:
        logger.error(f"{log_prefix} | 获取成员信息失败")

    # 收集需要检查的文本
    strings_will_be_check = [member_fullname]

    # 如果有用户名，获取额外信息
    if member_name:
        session.member_username = member_name

        # 检查用户bio
        user_info = await manager.get_user_extra_info(member_name)
        if user_info:
            bio = user_info["bio"]
            if bio:
                strings_will_be_check.append(bio)
                session.member_bio = bio
                logger.debug(f"{log_prefix} | 获取用户Bio | Bio:{bio}")

    # 使用LLM检查是否有垃圾信息
    try:
        llm_start_time = datetime.now()
        logger.debug(f"{log_prefix} | 开始LLM检查")

        spams_result = await check_spams_with_llm(
            [member],
            session,
            strings_will_be_check,
            now,
        )
        if spams_result and len(spams_result) > 0:
            # 过滤掉不需要的内容
            spams_result = [item for item in spams_result if item[0] == member_id]

            if spams_result:
                llm_cost_time = datetime.now() - llm_start_time
                logger.warning(
                    f"{log_prefix} | LLM检测到广告 | "
                    f"原因:{spams_result[0][1]} | "
                    f"耗时:{llm_cost_time.total_seconds():.2f}秒"
                )

    except Exception as e:
        logger.exception(f"{log_prefix} | LLM检查失败 | 错误:{e}")

    # 检查广告和敏感关键字
    for txt in strings_will_be_check:
        contains_adv, matched_word = check_advertising(txt)

        if contains_adv:
            try:
                await manager.send(
                    chat.id,
                    f"用户 {member_id} 的名或者BIO明确包含广告内容，已经被剔除。\n"
                    f"Message from {member_id} contains advertising content and has been removed.",
                    auto_deleted_at=event.date + timedelta(seconds=DELETED_AFTER),
                )

                log_details = f"匹配词:{matched_word}"
                if session.member_username:
                    log_details += f" | 用户名:@{session.member_username}"
                if session.member_bio:
                    log_details += f" | Bio:{session.member_bio}"

                logger.warning(f"{log_prefix} | 检测到广告内容 | {log_details}")

                # 禁止包含广告的用户
                await chat.ban(
                    member_id, until_date=timedelta(days=30), revoke_messages=True
                )
                logger.info(f"{log_prefix} | 用户已被封禁 | 封禁时长:30天")

                return
            except Exception as e:
                logger.error(f"{log_prefix} | 封禁用户失败 | 错误:{e}")

    # 生成验证码消息
    message_content, reply_markup = await build_captcha_message(member, now)

    # 发送验证消息
    reply = await manager.bot.send_message(
        chat.id, message_content, parse_mode="markdown", reply_markup=reply_markup
    )
    logger.info(f"{log_prefix} | 已发送验证消息 | 消息ID:{reply.message_id}")

    # 创建临时会话并设置自动删除
    await manager.lazy_session(
        chat.id,
        -1,
        member_id,
        "new_member_check",
        now + timedelta(seconds=DELETED_AFTER),
    )
    await manager.delete_message(chat, reply, now + timedelta(seconds=DELETED_AFTER))
    logger.debug(f"{log_prefix} | 设置验证消息自动删除 | 时长:{DELETED_AFTER}秒")


@manager.register("callback_query")
async def new_member_callback(query: types.CallbackQuery):
    """
    处理用户点击验证按钮后的逻辑
    """
    msg = query.message
    if not msg:
        return

    chat = msg.chat
    operator = query.from_user
    if not operator:
        return

    # 检查是否为支持的群组类型
    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    if not isinstance(msg, types.Message):
        return

    # 确保是机器人自己发送的消息
    user = msg.from_user
    if not user or not user.is_bot or manager.bot.id != user.id:
        return

    # 判断是否为验证消息（通过检查按钮布局）
    reply_markup = msg.reply_markup
    if (
        not reply_markup
        or reply_markup.inline_keyboard is None
        or len(reply_markup.inline_keyboard) != 2
        or len(reply_markup.inline_keyboard[0]) != 5
        or len(reply_markup.inline_keyboard[1]) != 2
    ):
        return

    # 构建日志前缀
    log_prefix = f"[回调] 群组:{chat.id}({chat.title}) 消息:{msg.message_id}"

    data = query.data
    if not data:
        logger.warning(f"{log_prefix} | 无回调数据")
        return

    # 添加操作者信息到日志前缀
    operator_info = f"操作者:{operator.id}"
    if operator.username:
        operator_info += f"(@{operator.username})"
    log_prefix += f" | {operator_info}"

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

        items = data.split("__")
        if len(items) != 3:
            logger.warning(f"{log_prefix} | 数据格式错误")
        else:
            member_id, _, op = items
            member_id = int(member_id)
            member = await manager.chat_member(chat, member_id)

            if not member:
                logger.error(f"{log_prefix} | 获取成员失败 | 成员ID:{member_id}")
                return

            member_info = f"目标成员:{member_id}"
            if member.user.username:
                member_info += f"(@{member.user.username})"

            # 接受新成员
            if op == "O":
                await manager.delete_message(chat, msg)
                await accepted_member(chat, msg, member.user)

                logger.info(f"{log_prefix} | 管理员接受成员 | {member_info}")

            # 拒绝新成员
            elif op == "X":
                await manager.delete_message(chat, msg)
                await chat.ban(
                    member_id, until_date=timedelta(days=30), revoke_messages=True
                )

                logger.warning(
                    f"{log_prefix} | 管理员拒绝成员 | {member_info} | 封禁时长:30天"
                )

            else:
                logger.warning(f"{log_prefix} | 未知操作类型 | 操作:{op}")

    # 新成员自己操作处理
    elif is_self:
        logger.debug(f"{log_prefix} | 成员自验证 | 数据:{data}")

        # 验证成功
        if data.endswith("__!"):
            await manager.delete_message(chat, msg, msg.date)
            await accepted_member(chat, msg, operator)

            logger.info(f"{log_prefix} | 验证成功 | 成员已通过验证")

        # 验证失败，重新加载验证码
        elif data.endswith("__?"):
            content, reply_markup = await build_captcha_message(operator, msg.date)

            await msg.edit_text(content, parse_mode="markdown")
            await msg.edit_reply_markup(reply_markup=reply_markup)

            logger.info(f"{log_prefix} | 验证失败 | 已重新生成验证码")

        else:
            logger.warning(f"{log_prefix} | 未知验证操作 | 数据:{data}")

    await query.answer(show_alert=False)
