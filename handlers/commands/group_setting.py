from datetime import datetime, timedelta, timezone

from telethon import events, Button

from manager import manager, RedisUnavailableError
from manager.group import (
    NEW_MEBMER_CHECK_METHODS,
    SECURITY_MODE_OFF_CALLBACK,
    SECURITY_MODE_ON_CALLBACK_PREFIX,
    SECURITY_MODE_WINDOW_NAMES,
    SECURITY_MODE_AUTO_EXIT_NAMES,
    settings_get,
    settings_set,
)
from handlers.member_captcha.config import get_chat_type
from handlers.member_captcha.security_mode import (
    clear_security_mode,
    is_security_mode,
    set_security_mode,
    get_auto_exit_minutes,
)
from handlers.member_captcha.helpers import SECURITY_MODE_ENTERED_AUTO, SECURITY_MODE_ENTERED_MANUAL

log = manager.logger

SUPPORT_TYPES = ["private", "group", "supergroup", "channel"]


@manager.register("message", pattern=r"(?i)^/group_setting(\s|$)|^/group_setting@\w+")
async def group_setting_command(event: events.NewMessage.Event):
    chat = await event.get_chat()
    user = await event.get_sender()
    if get_chat_type(chat) not in SUPPORT_TYPES:
        return
    if not await manager.is_admin(chat, user):
        return

    try:
        await event.delete()
    except Exception:
        pass

    try:
        rdb = await manager.require_redis()
    except RedisUnavailableError as e:
        log.warning(f"群组设置需要 Redis: {e}")
        try:
            await event.respond("⚠️ 群组设置依赖 Redis，当前不可用，请检查配置或稍后重试。")
        except Exception:
            pass
        return

    new_member_check_method = await settings_get(rdb, chat.id, "new_member_check_method", "ban")
    new_member_check_method_name = NEW_MEBMER_CHECK_METHODS.get(new_member_check_method, "未知")
    security_threshold = await settings_get(rdb, chat.id, "security_mode_join_threshold", "10")
    security_window = await settings_get(rdb, chat.id, "security_mode_window_seconds", "300")
    security_window_name = SECURITY_MODE_WINDOW_NAMES.get(security_window, "5分钟")
    security_auto_exit = await settings_get(rdb, chat.id, "security_mode_auto_exit_minutes", "30")
    security_auto_exit_name = SECURITY_MODE_AUTO_EXIT_NAMES.get(security_auto_exit, "30 分钟后")
    sm_on = await is_security_mode(rdb, chat.id)

    text = "⚙️ 群组设置面板\n\n"
    text += "📋 当前配置：\n"
    text += f"🔹 新成员处理方式：{new_member_check_method_name}({new_member_check_method})\n"
    text += f"🔹 安全模式：{security_threshold} 人 / {security_window_name} 内超过则静默待审核\n"
    text += f"🔹 安全模式自动解除：{security_auto_exit_name}"
    if sm_on:
        text += "\n\n🛡️ 【当前已开启安全模式】"
    text += "\n\n👇 点击下方按钮修改设置"

    keyboard = [
        [
            Button.inline("认证剔除", b"su:nm:ban"),
            Button.inline("手动解封", b"su:nm:silence"),
            Button.inline("无作为", b"su:nm:none"),
        ],
        [
            Button.inline("静默1周", b"su:nm:sleep_1week"),
            Button.inline("静默2周", b"su:nm:sleep_2weeks"),
        ],
        [
            Button.inline("阈值5", b"su:sm_th:5"),
            Button.inline("阈值10", b"su:sm_th:10"),
            Button.inline("阈值20", b"su:sm_th:20"),
        ],
        [
            Button.inline("窗口3秒", b"su:sm_win:3"),
            Button.inline("窗口5分", b"su:sm_win:300"),
            Button.inline("窗口10分", b"su:sm_win:600"),
            Button.inline("窗口30分", b"su:sm_win:1800"),
        ],
        [
            Button.inline("自动解除:关", b"su:sm_exit:0"),
            Button.inline("15分", b"su:sm_exit:15"),
            Button.inline("30分", b"su:sm_exit:30"),
            Button.inline("60分", b"su:sm_exit:60"),
        ],
        [Button.inline("取消", b"su:_:cancel")],
    ]
    if sm_on:
        keyboard.append([Button.inline("🛡️ 解除安全模式", SECURITY_MODE_OFF_CALLBACK.encode())])
    else:
        keyboard.append([Button.inline("🛡️ 手动开启安全模式", (SECURITY_MODE_ON_CALLBACK_PREFIX + "1").encode())])

    reply = await event.respond(
        text,
        buttons=keyboard,
        link_preview=False,
        silent=True,
    )
    log.info(f"群组 {chat.id} 调用设置命令")
    await manager.delete_message(chat.id, reply.id, datetime.now() + timedelta(seconds=25))


@manager.register("callback_query")
async def group_setting_callback(event: events.CallbackQuery.Event):
    data = event.data
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    if not data.startswith("su:"):
        return

    msg = event.message
    chat = await event.get_chat()
    user = await event.get_sender()
    if not await manager.is_admin(chat, user):
        log.warning(f"用户 {user.id} 尝试修改群组设置，但不是管理员")
        await event.answer()
        return

    try:
        rdb = await manager.require_redis()
    except RedisUnavailableError as e:
        log.warning(f"群组设置回调需要 Redis: {e}")
        await event.answer("Redis 不可用", alert=True)
        return

    try:
        if data == "su:_:cancel":
            await msg.delete()
            await event.answer()
            return
        if data == SECURITY_MODE_OFF_CALLBACK:
            await manager.lazy_session_delete(chat.id, 0, "security_mode_auto_off")
            await clear_security_mode(rdb, chat.id)
            exit_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            log.info(f"群组 {chat.id} 管理员解除安全模式")
            await manager.client.edit_message(
                chat,
                msg.id,
                f"✅ *已解除安全模式*\n\n解除时间：{exit_time_str} UTC\n新成员将恢复为验证码验证流程。",
                parse_mode="md",
            )
            await manager.delete_message(chat.id, msg.id, datetime.now() + timedelta(seconds=10))
            await event.answer()
            return

        if data.startswith(SECURITY_MODE_ON_CALLBACK_PREFIX):
            if await is_security_mode(rdb, chat.id):
                await manager.client.edit_message(chat, msg.id, "⚠️ 当前已在安全模式中，无需重复开启。")
            else:
                await set_security_mode(rdb, chat.id)
                now = datetime.now(timezone.utc)
                auto_exit_minutes = await get_auto_exit_minutes(rdb, chat.id)
                enter_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
                if auto_exit_minutes > 0:
                    exit_at = now + timedelta(minutes=auto_exit_minutes)
                    await manager.lazy_session(chat.id, 0, 0, "security_mode_auto_off", exit_at)
                    exit_time_str = exit_at.strftime("%Y-%m-%d %H:%M")
                    body = SECURITY_MODE_ENTERED_AUTO.format(
                        enter_time=enter_time_str,
                        exit_minutes=auto_exit_minutes,
                        exit_time=exit_time_str,
                    )
                else:
                    body = SECURITY_MODE_ENTERED_MANUAL.format(enter_time=enter_time_str)
                try:
                    await manager.client.send_message(chat.id, body, parse_mode="md")
                except Exception as e:
                    log.warning(f"手动开启安全模式后发送提示失败: {e}")
                await manager.client.edit_message(chat, msg.id, "✅ 已手动开启安全模式，已向群内发送提示。")
            await manager.delete_message(chat.id, msg.id, datetime.now() + timedelta(seconds=10))
            await event.answer()
            return

        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "su":
            await event.answer()
            return
        if parts[1] not in ("nm", "sm_th", "sm_win", "sm_exit"):
            await event.answer()
            return

        value = parts[2]
        if parts[1] == "nm":
            key = "new_member_check_method"
            await settings_set(rdb, chat.id, {key: value})
        elif parts[1] == "sm_th":
            key = "security_mode_join_threshold"
            await settings_set(rdb, chat.id, {key: value})
        elif parts[1] == "sm_win":
            key = "security_mode_window_seconds"
            await settings_set(rdb, chat.id, {key: value})
        elif parts[1] == "sm_exit":
            key = "security_mode_auto_exit_minutes"
            await settings_set(rdb, chat.id, {key: value})
        else:
            await event.answer()
            return

        new_member_check_method = await settings_get(rdb, chat.id, "new_member_check_method", "ban")
        new_member_check_method_name = NEW_MEBMER_CHECK_METHODS.get(new_member_check_method, "未知")
        security_threshold = await settings_get(rdb, chat.id, "security_mode_join_threshold", "10")
        security_window = await settings_get(rdb, chat.id, "security_mode_window_seconds", "300")
        security_window_name = SECURITY_MODE_WINDOW_NAMES.get(security_window, "5分钟")
        security_auto_exit = await settings_get(rdb, chat.id, "security_mode_auto_exit_minutes", "30")
        security_auto_exit_name = SECURITY_MODE_AUTO_EXIT_NAMES.get(security_auto_exit, "30 分钟后")

        text = "✅ 设置已成功更新！\n\n"
        text += "📋 当前群组配置：\n"
        text += f"🔹 新成员处理方式：{new_member_check_method_name}\n"
        text += f"🔹 安全模式：{security_threshold} 人 / {security_window_name}\n"
        text += f"🔹 安全模式自动解除：{security_auto_exit_name}\n"
        text += "\n如需进一步调整，请再次使用 /group_setting 命令"

        log.info(f"群组 {chat.id} 更新设置: {key} = {value}")
        await manager.client.edit_message(chat, msg.id, text)
        await manager.delete_message(chat.id, msg.id, datetime.now() + timedelta(seconds=15))
    except Exception as e:
        log.error(f"处理设置回调时出错: {e}")
    finally:
        await event.answer()
