from aiogram import types
from manager import manager
import aioredis
from typing import List

from .func_user import ban_user, allow_user, update_user_quota, count_user, total_user_requested

logger = manager.logger


async def admin_operations(
    rdb: "aioredis.Redis", msg: types.Message, chat: types.Chat, user: types.User, subcommand: str, arguments: List[str]
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
            f"用户{target_user_id}已经被禁用chat命令。\nUser {target_user_id} has been disabled from using the chat command."
        )
        logger.info(f"admin:ban {target_user_id}")
        return True
    elif subcommand == "admin:allow" and target_user_id:
        await allow_user(rdb, target_user_id)
        await msg.reply(f"用户{target_user_id}可以是用chat命令了。\nUser {target_user_id} can use the chat command.")
        logger.info(f"admin:allow {target_user_id}")
        return True
    elif subcommand == "admin:quota" and target_user_id:
        try:
            quota = int(arguments[1])
            await update_user_quota(rdb, target_user_id, quota)
            await msg.reply(f"用户{user.id}的配额已经设置为{quota}。\nUser {user.id}'s quota has been set to {quota}.")
            logger.info(f"admin:quota {target_user_id} {quota}")
        except:
            logger.exception(f"admin:quota {target_user_id} {quota}")
        return True
    elif subcommand == "admin:stats":
        total_used = await total_user_requested(rdb)
        total_user = await count_user(rdb)
        await msg.reply(f"请求量:{total_used} 用户:{total_user}\nTotal requests:{total_used} users:{total_user}")
        logger.info(f"admin:stats {total_used} {total_user}")
        return True

    # get user stats from redis
    elif subcommand == "admin:stats_user" and target_user_id:
        user_key = f"chat:user:{target_user_id}"

        # check exists
        if not await rdb.exists(user_key):
            await msg.reply(f"用户{target_user_id}不存在\nUser {target_user_id} not exists")
            return True

        disabled = await rdb.hget(user_key, "disabled")
        count = await rdb.hget(user_key, "count")
        quota = await rdb.hget(user_key, "quota")
        last = await rdb.hget(user_key, "last")

        disabled = "yes" if disabled and int(disabled) else "no"
        count = int(count) if count else 0
        quota = int(quota) if quota else -1
        last = last.decode() if last else "none"

        await msg.reply(
            f"用户{target_user_id}的状态：\n"
            f"禁用:{disabled} 请求次数:{count} 配额:{quota}\n最后请求时间:{last}\n"
            f"User {target_user_id} status:\n"
            f"Disabled:{disabled} Request count:{count} Quota:{quota}\nLast request time:{last}"
        )
        logger.info(f"admin:stats_user {target_user_id}")
        return True

    return False
