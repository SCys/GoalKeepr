from datetime import datetime, timedelta

from telethon import events, Button

from manager import manager
from manager.group import NEW_MEBMER_CHECK_METHODS, settings_get, settings_set
from handlers.member_captcha.config import get_chat_type

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

    rdb = await manager.get_redis()
    if not rdb:
        log.error("Redis connection failed")
        return

    new_member_check_method = await settings_get(rdb, chat.id, "new_member_check_method", "ban")
    new_member_check_method_name = NEW_MEBMER_CHECK_METHODS.get(new_member_check_method, "未知")

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
        key = "new_member_check_method"
        await settings_set(rdb, chat.id, {key: value})

        new_member_check_method = await settings_get(rdb, chat.id, "new_member_check_method", "ban")
        new_member_check_method_name = NEW_MEBMER_CHECK_METHODS.get(new_member_check_method, "未知")

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
