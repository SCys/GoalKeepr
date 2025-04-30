from pprint import pp
from aiogram import types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from manager import manager
from manager.group import NEW_MEBMER_CHECK_METHODS, settings_get, settings_set

log = manager.logger

SUPPORT_TYPES = ["private", "group", "supergroup", "channel"]


@manager.register(
    "message", Command("group_setting", ignore_case=True, ignore_mention=True)
)
async def group_setting_command(msg: types.Message):
    chat = msg.chat
    user = msg.from_user

    # check types
    if chat.type not in SUPPORT_TYPES:
        return

    if not await manager.is_admin(chat, user):
        await chat.delete_message(msg.message_id)
        return

    rdb = await manager.get_redis()
    if not rdb:
        log.error("Redis connection failed")
        return

    new_member_check_method = await settings_get(rdb, chat.id, "new_member_check_method", "ban")
    new_member_check_method_name = NEW_MEBMER_CHECK_METHODS.get(
        new_member_check_method, "未知"
    )

    # 构建说明
    text = f"⚙️ 群组设置面板\n\n"
    text += f"📋 当前配置：\n"
    text += f"🔹 新成员处理方式：{new_member_check_method_name}({new_member_check_method})\n\n"
    text += f"👇 点击下方按钮修改设置"

    # 构建按钮，使用简化的callback_data格式 "su:nm:<value>"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="认证剔除", callback_data="su:nm:ban"),
                InlineKeyboardButton(text="自动静默", callback_data="su:nm:silence"),
                InlineKeyboardButton(text="无作为", callback_data="su:nm:none"),
            ],
            [
                InlineKeyboardButton(text="取消", callback_data="su:_:cancel"),
            ],
        ]
    )

    await msg.answer(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
        disable_notification=True,
    )
    log.info(f"群组 {chat.id} 调用设置命令")


@manager.register("callback_query")
async def group_setting_callback(query: types.CallbackQuery):
    # 检查callback_data是否以"su:nm:"开头
    # 这可以防止其他回调数据干扰
    if not query.data.startswith("su:"):
        return
    
    if not await manager.is_admin(query.message.chat, query.from_user):
        log.warning(f"用户 {query.from_user.id} 尝试修改群组设置，但不是管理员")
        return
    
    rdb = await manager.get_redis()
    if not rdb:
        log.error("Redis connection failed")
        return

    try:
        if query.data == "su:_:cancel":
            await query.message.delete()
            return

        # 使用':'分隔解析callback_data，例如 "su:nm:ban"
        parts = query.data.split(":")
        if len(parts) != 3 or parts[0] != "su" or parts[1] != "nm":
            return

        value = parts[2]
        key = "new_member_check_method"

        # 更新设置
        await settings_set(rdb, query.message.chat.id, {key: value})

        # 读取更新后的设置
        new_member_check_method = await settings_get(rdb, query.message.chat.id, "new_member_check_method", "ban")
        new_member_check_method_name = NEW_MEBMER_CHECK_METHODS.get(
            new_member_check_method, "未知"
        )

        # 更新消息文本
        text = f"✅ 设置已成功更新！\n\n"
        text += f"📋 当前群组配置：\n"
        text += f"🔹 新成员处理方式：{new_member_check_method_name}\n"
        text += f"\n如需进一步调整，请再次使用 /group_setting 命令"

        log.info(f"群组 {query.message.chat.id} 更新设置: {key} = {value}")

        await query.answer("设置已更新")
        await query.message.edit_text(text)
    except Exception as e:
        log.error(f"处理设置回调时出错: {e}")
        await query.answer("处理请求时出错")

    return
