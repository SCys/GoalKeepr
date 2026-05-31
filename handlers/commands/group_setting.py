from datetime import datetime, timedelta
import time

from telethon import events, Button

from manager import manager
from manager.group import NEW_MEMBER_CHECK_METHODS, PENDING_KEY_PREFIX, settings_get, settings_set
from handlers.member_captcha.config import VerificationMode, get_chat_type

log = manager.logger

SUPPORT_TYPES = ["private", "group", "supergroup", "channel"]


def _method_display(method: str) -> str:
    """解析存储值，返回用户可读的显示名。"""
    if method.startswith("sleep_custom:"):
        days = method.split(":")[1]
        return f"自定义静默（{days}天）"
    return NEW_MEMBER_CHECK_METHODS.get(method, f"未知({method})")


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

    rdb = await manager.get_redis()
    if not rdb:
        log.error("Redis connection failed")
        return

    new_member_check_method = await settings_get(rdb, chat.id, "new_member_check_method", VerificationMode.BAN)
    new_member_check_method_name = _method_display(new_member_check_method)

    text = "⚙️ 群组设置面板\n\n"
    text += "📋 当前配置：\n"
    text += f"🔹 新成员处理方式：{new_member_check_method_name}({new_member_check_method})\n\n"
    text += "👇 点击下方按钮修改设置"

    keyboard = [
        [
            Button.inline("认证剔除", b"su:nm:ban"),
            Button.inline("手动解封", b"su:nm:silence"),
            Button.inline("无作为", b"su:nm:none"),
        ],
        [
            Button.inline("静默1周", b"su:nm:sleep_1week"),
            Button.inline("静默2周", b"su:nm:sleep_2weeks"),
            Button.inline("自定义静默", b"su:nm:sleep_custom"),
        ],
        [Button.inline("取消", b"su:_:cancel")],
    ]

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

    rdb = await manager.get_redis()
    if not rdb:
        log.error("Redis connection failed")
        await event.answer()
        return

    try:
        if data == "su:_:cancel":
            await msg.delete()
            await event.answer()
            return

        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "su" or parts[1] != "nm":
            await event.answer()
            return

        value = parts[2]

        # 自定义静默：进入两阶段输入流程
        if value == "sleep_custom":
            pending_key = f"{PENDING_KEY_PREFIX}{chat.id}"
            await rdb.hset(pending_key, mapping={
                "type":    "sleep_custom",
                "msg_id":  str(msg.id),
                "user_id": str(user.id),
                "created": str(int(time.time())),
            })
            await rdb.expire(pending_key, 60)

            text = "⚙️ 自定义静默时长\n\n"
            text += "请在回复中输入天数（1-365天）\n"
            text += "发送数字即可，例如：7\n"
            text += "\n⏱ 限时 60 秒，超时需重新操作"
            await manager.client.edit_message(chat, msg.id, text)
            await event.answer()
            return

        key = "new_member_check_method"
        await settings_set(rdb, chat.id, {key: value})

        new_member_check_method = await settings_get(rdb, chat.id, "new_member_check_method", VerificationMode.BAN)
        new_member_check_method_name = _method_display(new_member_check_method)

        text = "✅ 设置已成功更新！\n\n"
        text += "📋 当前群组配置：\n"
        text += f"🔹 新成员处理方式：{new_member_check_method_name}\n"
        text += "\n如需进一步调整，请再次使用 /group_setting 命令"

        log.info(f"群组 {chat.id} 更新设置: {key} = {value}")
        await manager.client.edit_message(chat, msg.id, text)
        await manager.delete_message(chat.id, msg.id, datetime.now() + timedelta(seconds=15))
    except Exception as e:
        log.error(f"处理设置回调时出错: {e}")
    finally:
        await event.answer()


@manager.register("message")
async def handle_pending_input(event: events.NewMessage.Event):
    """两阶段设置：处理管理员对「自定义静默」的回复"""
    chat = await event.get_chat()
    user = await event.get_sender()

    rdb = await manager.get_redis()
    if not rdb:
        return

    pending_key = f"{PENDING_KEY_PREFIX}{chat.id}"
    raw = await rdb.hgetall(pending_key)
    if not raw:
        return

    pending = {k.decode(): v.decode() for k, v in raw.items()}
    if pending.get("type") != "sleep_custom":
        return

    if str(user.id) != pending.get("user_id"):
        await event.answer("不是本人操作，忽略", alert=True)
        return

    reply_to = getattr(event.message, "reply_to_msg_id", None)
    expected_msg_id = int(pending.get("msg_id", 0))
    if reply_to != expected_msg_id:
        return

    text = (event.message.text or "").strip()
    if not text.isdigit():
        await event.respond("❌ 请输入有效数字（1-365）", reply_to=event.message.id, silent=True)
        return

    days = int(text)
    if days < 1 or days > 365:
        await event.respond("❌ 范围应为 1-365 天", reply_to=event.message.id, silent=True)
        return

    method_value = f"sleep_custom:{days}"
    await settings_set(rdb, chat.id, {"new_member_check_method": method_value})
    await rdb.delete(pending_key)

    confirm_text = (
        f"✅ 设置已成功更新！\n\n"
        f"📋 当前群组配置：\n"
        f"🔹 新成员处理方式：{_method_display(method_value)}\n\n"
        f"如需进一步调整，请再次使用 /group_setting 命令"
    )
    await manager.client.edit_message(chat, expected_msg_id, confirm_text)
    await manager.delete_message(chat.id, event.message.id, datetime.now() + timedelta(seconds=5))
