from datetime import datetime, timedelta
import time

from telethon import events

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

async def _render_setting_panel(rdb, chat_id: int):
    """构建设置面板的文本与内联键盘。"""
    new_member_check_method = await settings_get(rdb, chat_id, "new_member_check_method", VerificationMode.BAN)
    new_member_check_method_name = _method_display(new_member_check_method or VerificationMode.BAN)

    first_msg_check = await settings_get(rdb, chat_id, "first_msg_check", "off")
    lurk_check_5min = await settings_get(rdb, chat_id, "lurk_check_5min", "off")

    first_msg_status = "【已开启 🟢】" if first_msg_check == "on" else "【已关闭 ⚪】"
    lurk_status = "【已开启 🟢】" if lurk_check_5min == "on" else "【已关闭 ⚪】"

    text = "⚙️ **群组设置面板 | Group Settings**\n\n"
    text += "📋 **当前配置**：\n"
    text += f"🔹 **新成员入群处理**：`{new_member_check_method_name}`\n"
    text += f"🔹 **首句安全审查**：{first_msg_status}\n"
    text += f"🔹 **5分钟潜水检测**：{lurk_status}\n\n"
    text += "👇 点击下方按钮修改设置："

    first_msg_btn_text = f"首句审查: {'开启 🟢' if first_msg_check == 'on' else '关闭 ⚪'}"
    lurk_btn_text = f"5分潜水: {'开启 🟢' if lurk_check_5min == 'on' else '关闭 ⚪'}"

    keyboard = [
        [
            manager.inline_button("认证剔除", "su:nm:ban"),
            manager.inline_button("手动解封", "su:nm:silence"),
            manager.inline_button("无作为", "su:nm:none"),
        ],
        [
            manager.inline_button("静默1周", "su:nm:sleep_1week"),
            manager.inline_button("静默2周", "su:nm:sleep_2weeks"),
            manager.inline_button("自定义静默", "su:nm:sleep_custom"),
        ],
        [
            manager.inline_button(first_msg_btn_text, "su:tg:first_msg_check"),
            manager.inline_button(lurk_btn_text, "su:tg:lurk_check_5min"),
        ],
        [manager.inline_button("取消", "su:_:cancel")],
    ]
    return text, keyboard

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

    text, keyboard = await _render_setting_panel(rdb, chat.id)

    reply = await event.respond(
        text,
        buttons=keyboard,
        parse_mode="md",
    )

    log.info(f"群组 {chat.id} 调用设置命令")
    await manager.delete_message(chat.id, reply.id, datetime.now() + timedelta(seconds=45))

@manager.register("callback_query")
async def group_setting_callback(event: events.CallbackQuery.Event):
    data = event.data
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    if not data.startswith("su:"):
        return

    msg = await event.get_message()
    chat = await event.get_chat()
    user = await event.get_sender()
    if not await manager.is_admin(chat, user):
        log.warning(f"用户 {user.id} 尝试修改群组设置，但不是管理员")
        await event.answer("⚠️ 只有群管理员可以修改设置", alert=True)
        return

    rdb = await manager.get_redis()
    if not rdb:
        log.error("Redis connection failed")
        await event.answer("Redis 连接失败")
        return

    try:
        if data == "su:_:cancel":
            await msg.delete()
            await event.answer()
            return

        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "su":
            await event.answer()
            return

        op_type = parts[1]
        value = parts[2]

        if op_type == "tg":
            # 开关切换：first_msg_check 或 lurk_check_5min
            setting_key = value
            curr_val = await settings_get(rdb, chat.id, setting_key, "off")
            new_val = "off" if curr_val == "on" else "on"
            await settings_set(rdb, chat.id, {setting_key: new_val})
            log.info(f"群组 {chat.id} 切换设置: {setting_key} = {new_val}")

            text, keyboard = await _render_setting_panel(rdb, chat.id)
            await manager.edit_text(chat.id, msg.id, text, buttons=keyboard, parse_mode="md")
            await event.answer(f"已更新为: {'开启' if new_val == 'on' else '关闭'}")
            return

        elif op_type == "nm":
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

                text = "⚙️ **自定义静默时长**\n\n"
                text += "请在回复中输入天数（1-365天）\n"
                text += "发送数字即可，例如：`7`\n"
                text += "\n⏱ 限时 60 秒，超时需重新操作"
                await manager.edit_text(chat.id, msg.id, text, parse_mode="md")
                await event.answer()
                return

            key = "new_member_check_method"
            await settings_set(rdb, chat.id, {key: value})
            log.info(f"群组 {chat.id} 更新设置: {key} = {value}")

            text, keyboard = await _render_setting_panel(rdb, chat.id)
            await manager.edit_text(chat.id, msg.id, text, buttons=keyboard, parse_mode="md")
            await manager.delete_message(chat.id, msg.id, datetime.now() + timedelta(seconds=20))
            await event.answer("入群验证方式已更新")
            return

    except Exception as e:
        log.error(f"处理设置回调时出错: {e}")
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

    saved = {k.decode(): v.decode() for k, v in raw.items()} if isinstance(list(raw.keys())[0], bytes) else raw

    if str(user.id) != saved.get("user_id"):
        return

    try:
        await event.delete()
    except Exception:
        pass

    await rdb.delete(pending_key)

    text = event.text.strip()
    msg_id = int(saved.get("msg_id", 0))

    if not text.isdigit() or not (1 <= int(text) <= 365):
        err_text = f"❌ 输入无效「{text}」，必须是 1 到 365 之间的纯数字天数。请重新使用 /group_setting 设置。"
        await manager.edit_text(chat.id, msg_id, err_text)
        await manager.delete_message(chat.id, msg_id, datetime.now() + timedelta(seconds=10))
        return

    days = int(text)
    value = f"sleep_custom:{days}"
    key = "new_member_check_method"
    await settings_set(rdb, chat.id, {key: value})

    log.info(f"群组 {chat.id} 通过两阶段输入更新设置: {key} = {value}")

    updated_text, keyboard = await _render_setting_panel(rdb, chat.id)
    await manager.edit_text(chat.id, msg_id, updated_text, buttons=keyboard, parse_mode="md")
    await manager.delete_message(chat.id, msg_id, datetime.now() + timedelta(seconds=20))
