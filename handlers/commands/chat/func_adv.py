from datetime import timedelta
from typing import List

import aioredis
from aiogram import types
from orjson import dumps, loads

from manager import manager

from ...utils import count_tokens
from ...utils.txt import CONVERSATION_TTL, DEFAULT_MODEL, SUPPORTED_MODELS
from .func_user import allow_user, ban_user, count_user, total_user_requested, update_user_quota

DELETED_AFTER = 15
logger = manager.logger

HELPER_TEXT = f"""每个会话超时时间|Conversation timeout: {CONVERSATION_TTL}s\n
使用|Usage:

/chat reset - 重置会话|Reset the conversation
/chat detail - 查看会话详情|View conversation details
/chat model - 查看当前会话的模型|View the current model of the conversation
/chat models - 查看支持的模型|View supported models
/chat settings:system_prompt <text> - 设置对话系统的提示，限制1024个字符|Set the prompt for the conversation system, limit 1024 characters
/chat settings:model <model_name> - 设置对话系统的模型|Set the model for the conversation system
/chat settings:clear - 清除对话设置|Clear the conversation settings
"""


ADMIN_HELPER_TEXT = """
管理员命令|Administrator commands:

/chat admin:ban <user_id> - 禁用用户|Ban the user.
/chat admin:allow <user_id> - 允许用户|Allow the user.
/chat admin:quota <user_id> <quota> - 设置用户配额|Set the quota for the user.
/chat admin:stats - 获取全局统计信息|Get global statistics.
/chat admin:user <user_id> - 获取用户统计信息|Get user statistics.
/chat admin:settings <key> <value> - 设置全局设置|Set global settings.
/chat admin:settings:models - 设置全局默认模型|Set global default model.
"""


async def operations_person(
    rdb: "aioredis.Redis", chat: types.Chat, msg: types.Message, user: types.User, subcommand: str, arguments: List[str]
):
    """
    Operations for normal users.

    This function provides a variety of operations for normal users,
    such as resetting the conversation, viewing the conversation details,
    viewing the supported models, and setting the model for the conversation.

    Parameters:
        rdb (aioredis.Redis): The Redis client.
        chat (types.Chat): The chat where the command is sent.
        msg (types.Message): The message that contains the command.
        user (types.User): The user who sent the command.
        subcommand (str): The subcommand of the command.
        arguments (List[str]): The arguments of the command.

    Returns:
        bool: Whether the command is handled successfully.
    """
    if subcommand == "help":
        await msg.reply(HELPER_TEXT)
        return True

    # simple commands
    if subcommand == "reset":
        await rdb.delete(f"chat:history:{user.id}")
        await manager.reply(
            msg,
            f"会话已经重置\nYour chat history has been reset.",
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )
        return True

    elif subcommand == "detail":
        txt = ""

        chat_history = await rdb.get(f"chat:history:{user.id}")
        if chat_history:
            chat_history = loads(chat_history)
            tokens = 0
            for i in chat_history:
                tokens += count_tokens(i["content"])

            # expired at
            expired_at = await rdb.ttl(f"chat:history:{user.id}")

            txt = (
                f"会话历史中共有{len(chat_history)}条消息，总共{tokens}个Token，将会在{expired_at}秒后过期。\n"
                f"There are {len(chat_history)} messages in the chat history, "
                f"a total of {tokens} tokens, and it will expire in {expired_at} seconds.\n"
            )

        # show current model
        settings_global = await rdb.get(f"chat:settings:global")
        settings_person = await rdb.get(f"chat:settings:{user.id}")
        settings_global = loads(settings_global) if settings_global else {}
        settings_person = loads(settings_person) if settings_person else {}

        model = settings_person.get(
            "model",
            settings_global.get("model", "gemini-1.0-pro"),
        )

        await manager.reply(
            msg,
            txt + f"当前会话模型为|Current conversation model is: {model}",
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )

        return True

    elif subcommand == "models":
        # 一行行列出支持的模型，包括 key 和 name，还有 input_length 等介绍
        models_txt = "\n".join(
            [
                f"Key: {key}\n\t{value.name}\n\tInput length: {value.input_length}tokens"
                for key, value in SUPPORTED_MODELS.items()
            ]
        )
        await manager.reply(
            msg,
            f"支持的模型|Supported models:\n{models_txt}"
            f"\n通过命令|Use command: /chat settings:model <Key> 来设置模型|to set the model.",
        )
        return True

    elif subcommand.startswith("settings:"):
        settings_person = await rdb.get(f"chat:settings:{user.id}")
        settings_person = loads(settings_person) if settings_person else {}

        # settings
        if subcommand == "settings:system_prompt" and len(arguments) > 1:
            # 设置对话系统的提示
            prompt = " ".join(arguments[1:])
            settings_person["prompt_system"] = prompt[:1024]  # limit 1024 characters
            await manager.reply(
                msg,
                f"你的系统提示设置成功。\nSystem prompt set successfully.",
                auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
            )
            return True

        elif subcommand == "settings:clear":
            # 清除对话设置
            settings_person = {}
            await manager.reply(
                msg,
                f"你的对话设置已被清除。\nYour chat settings have been cleared.",
                auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
            )

        # select models
        elif subcommand == "settings:model" and len(arguments) > 1:
            # 设置对话系统的模型
            model = " ".join(arguments[1:])
            if model not in SUPPORTED_MODELS:
                await manager.reply(
                    msg,
                    f"不支持的模型\nUnsupported model",
                    auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
                )
                return True

            settings_person["model"] = model
            await manager.reply(
                msg,
                f"你的对话系统模型设置成功。\nYour chat system model has been set.",
                auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
            )

        else:
            return False

        await rdb.set(f"chat:settings:{user.id}", dumps(settings_person))
        return True

    return False


async def operations_admin(
    rdb: "aioredis.Redis", chat: types.Chat, msg: types.Message, user: types.User, subcommand: str, arguments: List[str]
) -> bool:
    """
    Operations for administrators.

    This function provides a variety of operations for administrators,
    such as banning or allowing users, setting user quotas, and getting
    user and global statistics.

    Parameters:
        rdb (aioredis.Redis): The Redis client.
        chat (types.Chat): The chat where the command is sent.
        msg (types.Message): The message that contains the command.
        user (types.User): The user who sent the command.
        subcommand (str): The subcommand of the command.
        arguments (List[str]): The arguments of the command.

    Returns:
        bool: Whether the command is handled successfully.

    """
    administrator = manager.config["ai"]["administrator"]
    if not administrator or user.id != int(administrator):
        return False

    # global settings
    settings = await rdb.get(f"chat:settings:global")
    settings = loads(settings) if settings else {}

    if subcommand == "admin:help":
        # return ADMIN_HELPER_TEXT
        await manager.reply(
            msg,
            ADMIN_HELPER_TEXT,
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER * 2),
        )
        return True

    elif subcommand == "admin:ban":
        target_user_id = get_user_id(msg, arguments)
        if not target_user_id:
            await manager.reply(
                msg,
                "请回复一个用户或者提供一个用户ID。\nPlease reply to a user or provide a user ID.",
                auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
            )
            return False

        await ban_user(rdb, target_user_id)
        await manager.reply(
            msg,
            f"用户{target_user_id}禁用chat命令。\nUser {target_user_id} has been disabled from using the chat command.",
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )
        logger.info(f"admin:ban {target_user_id}")
        return True

    elif subcommand == "admin:allow":
        target_user_id = get_user_id(msg, arguments)
        if not target_user_id:
            await manager.reply(
                msg,
                "请回复一个用户或者提供一个用户ID。\nPlease reply to a user or provide a user ID.",
                auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
            )
            return False

        await allow_user(rdb, target_user_id)
        await manager.reply(
            msg,
            f"用户{target_user_id}可以使用chat命令了。\nUser {target_user_id} can use the chat command.",
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )
        logger.info(f"admin:allow {target_user_id}")
        return True

    elif subcommand == "admin:quota":
        target_user_id = get_user_id(msg, arguments)
        if not target_user_id:
            await manager.reply(
                msg,
                "请回复一个用户或者提供一个用户ID。\nPlease reply to a user or provide a user ID.",
                auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
            )
            return False

        quota = int(arguments[1])
        await update_user_quota(rdb, target_user_id, quota)
        await manager.reply(
            msg,
            f"用户{user.id}的配额已经设置为{quota}。\nUser {user.id}'s quota has been set to {quota}.",
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )
        logger.info(f"admin:quota {target_user_id} {quota}")
        return True

    # global stats
    elif subcommand == "admin:stats":
        total_used = await total_user_requested(rdb)
        total_user = await count_user(rdb)
        await manager.reply(
            msg,
            f"请求量|Total Requests:{total_used}\n用户|Users:{total_user}",
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )
        logger.info(f"admin:stats {total_used} {total_user}")
        return True

    # get user stats from redis
    elif subcommand == "admin:stats_user":
        target_user_id = get_user_id(msg, arguments)
        if not target_user_id:
            await manager.reply(
                msg,
                "请回复一个用户或者提供一个用户ID。\nPlease reply to a user or provide a user ID.",
                auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
            )
            return False

        user_key = f"chat:user:{target_user_id}"

        # check exists
        if not await rdb.exists(user_key):
            await manager.reply(
                msg,
                f"用户{target_user_id}不存在\nUser {target_user_id} not exists",
                auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
            )
            return True

        # basic info
        disabled = await rdb.hget(user_key, "disabled")
        count = await rdb.hget(user_key, "count")
        quota = await rdb.hget(user_key, "quota")
        last = await rdb.hget(user_key, "last")

        disabled = "yes" if disabled and int(disabled) else "no"
        count = int(count) if count else 0
        quota = int(quota) if quota else -1
        last = last.decode() if last else "none"

        # check user is setup prompt
        user_settings = await rdb.get(f"chat:settings:{target_user_id}")
        user_settings = loads(user_settings) if user_settings else {}
        user_is_setup_prompt_system = "yes" if "prompt_system" in user_settings and user_settings["prompt_system"] else "no"
        user_prompt_system_length = len(user_settings["prompt_system"]) if user_is_setup_prompt_system == "yes" else 0

        user_cached_history_detail = ""
        if user_chat_history := await rdb.get(f"chat:history:{target_user_id}"):
            user_chat_history = loads(user_chat_history)
            user_chat_history_length = len(user_chat_history)

            tokens = 0
            for i in user_chat_history:
                tokens += count_tokens(i["content"])
            user_chat_history_tokens_size = tokens
            user_chat_history_expired_at = await rdb.ttl(f"chat:history:{user.id}")

            # setup user_cached_history_detail
            user_cached_history_detail = (
                "\n聊天历史统计:\n"
                f"历史消息数量: {user_chat_history_length}\n"
                f"Token数量: {user_chat_history_tokens_size}\n"
                f"过期时间: {user_chat_history_expired_at}秒\n"
            )

        await manager.reply(
            msg,
            f"用户{target_user_id}的状态：\n"
            f"禁用:{disabled} 请求次数:{count} 配额:{quota}\n最后请求时间:{last}\n"
            f"设置System Prompt:{user_is_setup_prompt_system} 长度:{user_prompt_system_length}" + user_cached_history_detail,
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )
        logger.info(f"admin:stats_user {target_user_id}")
        return True

    # admin:settings:models
    elif subcommand == "admin:settings:models":
        # 获得支持的模型按钮列表，并且通过选择来设定为默认模型
        model_default = settings.get("model", DEFAULT_MODEL)
        models_buttons = [
            types.InlineKeyboardButton(
                text=f"{value.name} ({key})",
                callback_data=f"admin:settings:model {key}"
            )
            for key, value in SUPPORTED_MODELS.items()
        ]
        # 将按钮按行排列，每行最多2个按钮
        button_rows = []
        for i in range(0, len(models_buttons), 2):
            button_rows.append(models_buttons[i:i+2])
        
        await manager.reply(
            msg,
            f"现在默认模型：{model_default}，请选择要设置的模型",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=button_rows),
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER * 2),
        )

        return True

    return False


def get_user_id(msg: types.Message, arguments: List[str]):
    target_user_id = None
    pre_msg = msg.reply_to_message
    if pre_msg and pre_msg.from_user:
        target_user_id = pre_msg.from_user.id

    elif len(arguments) > 1:
        try:
            target_user_id = int(arguments[1])
        except ValueError:
            return

        arguments.pop(1)

    return target_user_id
