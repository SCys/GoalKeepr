import json

from aiogram import types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from manager import manager
from manager.group import NEW_MEBMER_CHECK_METHODS, settings_get, settings_set

log = manager.logger


@manager.register("message", Command("setting", ignore_case=True, ignore_mention=True))
async def setting_command(msg: types.Message):
    chat = msg.chat
    user = msg.from_user
    if not await manager.is_admin(chat, user):
        await chat.delete_message(msg.message_id)
        return

    rdb = await manager.get_redis()
    if not rdb:
        log.error("Redis connection failed")
        return
    
    settings = await settings_get(rdb, chat.id)

    new_member_check_method = settings.get("new_member_check_method", "ban")
    new_member_check_method_name = NEW_MEBMER_CHECK_METHODS.get(new_member_check_method, "未知")

    # 构建说明
    text = f"当前设置：\n"
    text += f"新成员处理方法: {new_member_check_method_name}\n"
    text += f"点击按钮修改设置"

    # 构建按钮 - 使用JSON结构的callback_data
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="禁止",
                    callback_data=json.dumps({"action": "setting_update", "key": "new_member_check_method", "value": "ban"}),
                )
            ],
            [
                InlineKeyboardButton(
                    text="静默",
                    callback_data=json.dumps(
                        {"action": "setting_update", "key": "new_member_check_method", "value": "silence"}
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="无作为",
                    callback_data=json.dumps({"action": "setting_update", "key": "new_member_check_method", "value": "none"}),
                )
            ],
        ]
    )

    await msg.send_message(text, reply_markup=keyboard, disable_web_page_preview=True, disable_notification=True)
    log.info(f"群组 {chat.id} 调用设置命令")


@manager.register("callback_query")
async def setting_callback(query: types.CallbackQuery):
    if not await manager.is_admin(query.message.chat, query.from_user):
        log.warning(f"用户 {query.from_user.id} 尝试修改群组设置，但不是管理员")
        return
    
    rdb = await manager.get_redis()
    if not rdb:
        log.error("Redis connection failed")
        return

    try:
        data = json.loads(query.data)
        if data["action"] == "setting_update":
            key = data["key"]
            value = data["value"]

            # 更新设置
            await settings_set(rdb, query.message.chat.id, {key: value})

            # 读取更新后的设置
            settings = await settings_get(rdb, query.message.chat.id)
            new_member_check_method = settings.get("new_member_check_method", "ban")
            new_member_check_method_name = NEW_MEBMER_CHECK_METHODS.get(new_member_check_method, "未知")

            # 更新消息文本
            text = f"设置已更新！\n\n"
            text += f"当前设置：\n"
            text += f"新成员处理方法: {new_member_check_method_name}\n"

            log.info(f"群组 {query.message.chat.id} 更新设置: {key} = {value}")

            await query.answer("设置已更新")
            await query.message.edit_text(text)
    except (json.JSONDecodeError, KeyError) as e:
        log.error(f"处理设置回调时出错: {e}")
        await query.answer("处理请求时出错")

    return
