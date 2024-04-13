from datetime import timedelta
from aiogram import types
from manager import manager
import aioredis
from typing import List
from orjson import dumps, loads

from .utils import count_tokens
from .func_user import ban_user, allow_user, update_user_quota, count_user, total_user_requested

DELETED_AFTER = 5
logger = manager.logger

HELPER_TEXT = """Usage:
/chat reset - 重置会话|Reset the conversation
/chat detail - 查看会话详情|View conversation details
/chat settings:system_prompt <text> - 设置对话系统的提示|Set the prompt for the conversation system
/chat settings:clear - 清除对话设置|Clear the conversation settings
"""


async def operations_person(
    rdb: "aioredis.Redis", chat: types.Chat, msg: types.Message, user: types.User, subcommand: str, arguments: List[str]
):
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
        chat_history = await rdb.get(f"chat:history:{user.id}")
        if chat_history:
            chat_history = loads(chat_history)
            tokens = 0
            for i in chat_history:
                tokens += count_tokens(i["content"])

            # expired at
            expired_at = await rdb.ttl(f"chat:history:{user.id}")

            await manager.reply(
                msg,
                f"会话历史中共有{len(chat_history)}条消息，总共{tokens}个Token，将会在{expired_at}秒后过期。\n"
                f"There are {len(chat_history)} messages in the chat history, "
                f"a total of {tokens} tokens, and it will expire in {expired_at} seconds.",
                auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
            )
        else:
            await manager.reply(msg, f"没有会话历史\nNo chat history.", auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER))

        return True

    # settings
    elif subcommand == "settings:system_prompt" and len(arguments) > 1:
        # 设置对话系统的提示
        prompt = " ".join(arguments[1:])
        await rdb.set(f"chat:settings:{user.id}", dumps({"prompt_system": prompt}), ex=3600)
        await msg.reply(f"你的对话中系统Prompt设置成功。\nYour chat system prompt has been set.")
        return True

    elif subcommand == "settings:clear":
        # 清除对话设置
        await rdb.delete(f"chat:settings:{user.id}")
        await msg.reply(f"你的对话设置已被清除。\nYour chat settings have been cleared.")
        return True

    # select models
    elif subcommand == "settings:model" and len(arguments) > 1:
        # 设置对话系统的模型
        model = " ".join(arguments[1:])
        await rdb.set(f"chat:settings:{user.id}", dumps({"model": model}), ex=3600)
        await msg.reply(f"你的对话系统模型设置成功。\nYour chat system model has been set.")
        return True

    return False


async def operations_admin(
    rdb: "aioredis.Redis", chat: types.Chat, msg: types.Message, user: types.User, subcommand: str, arguments: List[str]
) -> bool:
    administrator = manager.config["ai"]["administrator"]
    if not administrator or user.id != int(administrator):
        return False

    target_user_id = None
    pre_msg = msg.reply_to_message
    if pre_msg and pre_msg.from_user:
        target_user_id = pre_msg.from_user.id
    elif len(arguments) > 1:
        target_user_id = int(arguments[1])
        arguments.pop(1)

    if subcommand == "admin:ban" and target_user_id:
        await ban_user(rdb, target_user_id)
        await msg.reply(
            f"用户{target_user_id}禁用chat命令。\nUser {target_user_id} has been disabled from using the chat command."
        )
        logger.info(f"admin:ban {target_user_id}")
        return True
    elif subcommand == "admin:allow" and target_user_id:
        await allow_user(rdb, target_user_id)
        await msg.reply(f"用户{target_user_id}可以使用chat命令了。\nUser {target_user_id} can use the chat command.")
        logger.info(f"admin:allow {target_user_id}")
        return True
    elif subcommand == "admin:quota" and target_user_id:
        quota = int(arguments[1])
        await update_user_quota(rdb, target_user_id, quota)
        await manager.reply(
            msg,
            f"用户{user.id}的配额已经设置为{quota}。\nUser {user.id}'s quota has been set to {quota}.",
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )
        logger.info(f"admin:quota {target_user_id} {quota}")
        return True
    elif subcommand == "admin:stats":
        total_used = await total_user_requested(rdb)
        total_user = await count_user(rdb)
        await manager.reply(
            msg,
            f"请求量:{total_used} 用户:{total_user}\nTotal requests:{total_used} users:{total_user}",
            auto_deleted_at=msg.date + timedelta(seconds=DELETED_AFTER),
        )
        logger.info(f"admin:stats {total_used} {total_user}")
        return True

    # get user stats from redis
    elif subcommand == "admin:stats_user" and target_user_id:
        user_key = f"chat:user:{target_user_id}"

        # check exists
        if not await rdb.exists(user_key):
            await msg.reply(f"用户{target_user_id}不存在\nUser {target_user_id} not exists")
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

    return False
