from datetime import datetime, timedelta, timezone

from manager import manager
from manager.group import resolve_chat_entity
from .config import DEFAULT_BAN_DAYS
from .stats import stats_incr, FIELD_FAILED

logger = manager.logger


async def _kick_member(client, chat_id: int, member_id: int, reason: str) -> bool:
    """
    获取群组和成员实体，检查权限，然后踢出成员。

    根据 reason 决定踢出时长:
      - "advertising" → 30 天封禁（不调度 unban_member）
      - "llm"         → 60 秒封禁（需调度 unban_member）
      - 其他           → 60 秒封禁（需调度 unban_member）

    Returns:
      True  — 成功踢出
      False — 未踢出（管理员/已通过验证/已被 ban/已离开/权限获取失败）

    重要：若成员已被 /sb、管理员拒绝、广告检测等封禁（view_messages=False），
    不得再次 edit_permissions，否则会把永久/30 天 ban 覆盖成 60s。
    """
    try:
        chat = await resolve_chat_entity(client, chat_id)
    except Exception as e:
        logger.warning(f"chat {chat_id} get failed: {e}")
        return False

    try:
        perms = await client.get_permissions(chat, member_id)
    except ValueError as e:
        logger.info(f"chat {chat_id} member {member_id} entity not cached in session, skip kick")
        return False
    except Exception as e:
        logger.warning(f"member {member_id} in chat {chat_id} get failed: {e}")
        return False

    prefix = f"chat {chat_id}"

    if perms.is_admin or perms.is_creator:
        logger.info(f"{prefix} member {member_id} is admin/creator, skip kick")
        return False

    if getattr(perms, "has_left", False):
        logger.info(f"{prefix} member {member_id} already left, skip kick")
        return False

    # 检查是否已经被管理员封禁（已被移出群或禁止查看消息 view_messages=False）
    # 注意：验证码初始阶段只禁言（send_messages=False），不能误判为已封禁。
    participant = getattr(perms, "participant", None)
    banned_rights = getattr(participant, "banned_rights", None)
    is_view_banned = banned_rights and getattr(banned_rights, "view_messages", False) is True

    if is_view_banned:
        from .session import CaptchaSession
        if not await CaptchaSession.is_restricted(chat_id, member_id):
            logger.info(f"{prefix} member {member_id} already banned by admin/view_banned, skip kick")
            return False

    if getattr(perms, "send_messages", False):
        logger.info(f"{prefix} member {member_id} already accepted, skip kick")
        return False

    logger.info(f"{prefix} member {member_id} timeout kick (reason={reason})")

    if reason == "advertising":
        await manager.hide_member(chat, member_id, timedelta(days=DEFAULT_BAN_DAYS))
        logger.info(f"{prefix} member {member_id} banned {DEFAULT_BAN_DAYS} days for advertising")
        return True

    # llm 或 default → 真正踢出成员（从群组中移除）
    if await manager.kick_member(chat, member_id):
        logger.info(f"{prefix} member {member_id} kicked from chat")
    else:
        logger.warning(f"{prefix} kick_participant failed, fallback to hide_member")
        await manager.hide_member(chat, member_id, timedelta(seconds=60))
    return True


def _should_schedule_unban(reason: str) -> bool:
    """广告 30 天封禁不应在 60s 后自动解封。"""
    return reason != "advertising"


@manager.register_event("new_member_check")
async def new_member_check(client, chat_id: int, message_id: int, member_id: int):
    from .session import CaptchaSession

    reason = await CaptchaSession.is_flagged(chat_id, member_id) or "default"

    kicked = False
    try:
        kicked = await _kick_member(client, chat_id, member_id, reason)
    finally:
        await manager.lazy_session_delete(chat_id, member_id, "safety_timeout_check")
        if kicked:
            if _should_schedule_unban(reason):
                await manager.lazy_session(
                    chat_id,
                    message_id,
                    member_id,
                    "unban_member",
                    datetime.now() + timedelta(seconds=60),
                )
            logger.info(
                f"chat {chat_id} msg {message_id} member {member_id} is kicked by timeout "
                f"(reason={reason}, unban={_should_schedule_unban(reason)})"
            )
            rdb = await manager.get_redis()
            await stats_incr(rdb, FIELD_FAILED, chat_id, member_id)

            # 发送超时/被踢提示（30秒后自动删除，防止群消息混乱）
            try:
                now_dt = datetime.now(timezone.utc)
                user = await manager.get_user_info(member_id)
                name = user.full_name if user else str(member_id)
                if reason == "llm":
                    notice = (
                        f"⚠️ 成员 [{name}](tg://user?id={member_id}) 验证超时且未通过 AI 安全评估，已被移出群组（60秒后解禁）。\n\n"
                        f"> Member [{name}](tg://user?id={member_id}) verification timed out and failed AI security check."
                    )
                elif reason == "advertising":
                    notice = (
                        f"🚫 成员 [{name}](tg://user?id={member_id}) 触发广告规则，已被封禁 {DEFAULT_BAN_DAYS} 天。\n\n"
                        f"> Member [{name}](tg://user?id={member_id}) was banned for {DEFAULT_BAN_DAYS} days due to advertising."
                    )
                else:
                    notice = (
                        f"⏱️ 成员 [{name}](tg://user?id={member_id}) 验证超时（未在30秒内完成操作），已被移出群组（60秒后解禁）。\n\n"
                        f"> Member [{name}](tg://user?id={member_id}) verification timed out and has been removed."
                    )
                await manager.send(
                    chat_id,
                    notice,
                    parse_mode="md",
                    auto_deleted_at=now_dt + timedelta(seconds=30),
                )
            except Exception as e:
                logger.warning(f"send timeout kick notice failed: {e}")


@manager.register_event("unban_member")
async def unban_member(client, chat_id: int, message_id: int, member_id: int):
    try:
        chat = await resolve_chat_entity(client, chat_id)
    except Exception as e:
        logger.warning(f"bot get chat {chat_id} failed: {e}")
        return

    prefix = f"chat {chat_id} msg {message_id}"

    # 检查成员当前权限，如果已经被管理员封禁（或已离开），不可自动解禁
    try:
        perms = await client.get_permissions(chat, member_id)
        if perms and (perms.is_admin or perms.is_creator or getattr(perms, "has_left", False)):
            return
        if perms and (getattr(perms, "is_banned", False) or getattr(perms, "view_messages", True) is False):
            from .session import CaptchaSession
            if not await CaptchaSession.is_restricted(chat_id, member_id):
                logger.info(f"{prefix} member {member_id} is permanently/externally banned, skip unban")
                return
    except ValueError as e:
        logger.info(f"{prefix} check member {member_id} entity not cached before unban, skip")
        return
    except Exception as e:
        logger.warning(f"{prefix} check member {member_id} perms before unban failed: {e}")

    if await manager.unban_member_full(chat, member_id):
        logger.info(f"{prefix} member {member_id} is unbanned")
    else:
        logger.warning(f"{prefix} member {member_id} unbanned error")


# 兜底超时检查：程序在 restrict → captcha 之间崩溃时，该 session 到期后执行。
# 检查成员是否已被解禁；没有则根据 flagged_reason 踢出（广告=30天，其他=60s）。
@manager.register_event("safety_timeout_check")
async def safety_timeout_check(client, chat_id: int, message_id: int, member_id: int):
    from .session import CaptchaSession

    reason = await CaptchaSession.is_flagged(chat_id, member_id) or "default"

    kicked = False
    try:
        kicked = await _kick_member(client, chat_id, member_id, reason)
    finally:
        if kicked:
            if _should_schedule_unban(reason):
                await manager.lazy_session(
                    chat_id,
                    message_id,
                    member_id,
                    "unban_member",
                    datetime.now() + timedelta(seconds=60),
                )
            logger.info(
                f"chat {chat_id} msg {message_id} member {member_id} is kicked by safety timeout "
                f"(reason={reason}, unban={_should_schedule_unban(reason)})"
            )
            rdb = await manager.get_redis()
            await stats_incr(rdb, FIELD_FAILED, chat_id, member_id)

@manager.register_event("first_msg_timeout")
async def first_msg_timeout(client, chat_id: int, message_id: int, member_id: int):
    """5分钟内未发言，触发防僵尸潜水踢出。"""
    rdb = await manager.get_redis()
    if rdb:
        watch_key = f"first_msg_watch:{chat_id}:{member_id}"
        is_watching = await rdb.get(watch_key)
        if not is_watching:
            logger.debug(f"chat {chat_id} member {member_id} already spoke or watch ended, skip first_msg_timeout")
            return
        await rdb.delete(watch_key)

        from manager.group import settings_get
        lurk_check = await settings_get(rdb, chat_id, "lurk_check_5min", "off")
        if lurk_check != "on":
            logger.debug(f"chat {chat_id} lurk_check_5min is off, skip kick")
            return

    try:
        chat = await resolve_chat_entity(client, chat_id)
        perms = await client.get_permissions(chat, member_id)
        if perms and (perms.is_admin or perms.is_creator or getattr(perms, "has_left", False)):
            return
    except Exception as e:
        logger.warning(f"check perms before first_msg_timeout failed: {e}")
        return

    kicked = False
    if await manager.kick_member(chat, member_id):
        kicked = True
    else:
        kicked = await manager.hide_member(chat, member_id, timedelta(seconds=60))

    if kicked:
        now_dt = datetime.now(timezone.utc)
        await manager.lazy_session(
            chat_id,
            0,
            member_id,
            "unban_member",
            now_dt + timedelta(seconds=60),
        )
        logger.info(f"chat {chat_id} member {member_id} kicked due to 5min lurk timeout")
        try:
            user = await manager.get_user_info(member_id)
            name = user.full_name if user else str(member_id)
            notice = (
                f"⏱️ 成员 [{name}](tg://user?id={member_id}) 入群 5 分钟未发言（触发防僵尸号机制），已被移出群组。\n\n"
                f"> Member [{name}](tg://user?id={member_id}) was removed for being inactive within 5 minutes of joining. Welcome to rejoin anytime!"
            )
            await manager.send(
                chat_id,
                notice,
                parse_mode="md",
                auto_deleted_at=now_dt + timedelta(seconds=30),
            )
        except Exception as e:
            logger.warning(f"send lurk timeout notice failed: {e}")
