from aiogram import exceptions, types
from aiogram.filters import Command
import re
from manager import manager
import tiktoken
from orjson import loads, dumps
from datetime import datetime
import aioredis
from typing import List

"""
user info as hash in redis, key prefix is chat:user:{{ user_id }}. 

include hash:

- disabled: bool (default False)
- count: integer (default 0)
- quota: integer (default -1, means no limit)
- last: datetime string (default '1970-01-01T00:00:00Z')
"""

DELETED_AFTER = 5
BAN_MEMBER = 300  # 300s

logger = manager.logger

RE_CLEAR = re.compile(r"/chat(@[a-zA-Z0-9]+\s?)?")


async def generate_text(chat: types.Chat, member: types.ChatMember, prompt: str):
    config = manager.config

    host = config["ai"]["proxy_host"]
    if not host:
        logger.error("proxy host is empty")
        return

    proxy_token = config["ai"]["proxy_token"]

    # default prompts
    prompt_system = "You are a chatbot. You are a helpful and friendly chatbot."
    chat_history = [
        # last message
        {"role": "user", "content": prompt},
    ]

    rdb = await manager.get_redis()
    if rdb:
        # 每个用户独立的对话设置
        settings = await rdb.get(f"chat:settings:{member.id}")
        if settings:
            prompt_system = settings.get("prompt_system", prompt_system)

        # 从Redis获取之前的对话历史
        prev_chat_history = await rdb.get(f"chat:history:{member.id}")
        if prev_chat_history:
            # convert prev_chat_history to list
            prev_chat_history = loads(prev_chat_history)
            chat_history = [*prev_chat_history, *chat_history]

            # 限制Tokens数字为32k，并且删除多余的历史记录
            tokens = 0
            for i, msg in enumerate(chat_history):
                tokens += count_tokens(msg["content"])
                if tokens > 31000:  # 1k system prompt?
                    chat_history = chat_history[i:]
                    break

    # request openai v1 like api
    url = f"{host}/v1/chat/completions"
    data = {
        "model": "gemini-pro",
        "max_tokens": 32000,  # 32k for gemini-pro
        "temperature": 0.9,
        "top_p": 1,
        "top_k": 1,
        "messages": [{"role": "system", "content": prompt_system}, *chat_history],
    }

    session = await manager.bot.session.create_session()
    async with session.post(url, json=data, headers={"Authorization": f"Bearer {proxy_token}"}) as response:
        if response.status != 200:
            logger.error(f"generate text error: {response.status} {await response.text()}")
            return

        data = await response.json()

        # check error
        if "error" in data:
            code = data["error"]["code"]
            message = data["error"]["message"]
            logger.error(f"generate text error: {code} {message}")
            return

        text = data["choices"][0]["message"]["content"]
        if rdb:
            # 保存到Redis，确保保存的TTL为10分钟
            chat_history.append({"role": "assistant", "content": text})
            await rdb.set(f"chat:history:{member.id}", dumps(chat_history), ex=600)

        return text


@manager.register("message", Command("chat", ignore_case=True, ignore_mention=True))
async def chat(msg: types.Message):
    """Google Gemini Pro"""
    chat = msg.chat
    user = msg.from_user

    if chat.title is None:
        prefix = f"chat {chat.id} msg {msg.message_id}"
    else:
        prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    text = msg.text
    if text.startswith("/chat"):
        text = RE_CLEAR.sub("", text, 1).strip()
    if not text:
        logger.warning(f"{prefix} message without text, ignored")
        return

    rdb = await manager.get_redis()
    if not rdb:
        logger.error(f"{prefix} redis not connected")
        # reply system error with redis is missed
        await msg.reply("System error: Redis is missed.")
        return

    if not await check_user_permission(rdb, chat.id, user.id):
        logger.warning(f"{prefix} user {user.id} in chat {chat.id} has no permission")
        return

    # normal user
    if text == "reset":
        await rdb.delete(f"chat:history:{user.id}")
        await msg.reply(f"会话已经重置\nYour chat history has been reset.")
        return

    elif text == "detail":
        chat_history = await rdb.get(f"chat:history:{user.id}")
        if chat_history:
            chat_history = loads(chat_history)
            tokens = 0
            for i in chat_history:
                tokens += count_tokens(i["content"])

            # expired at
            expired_at = await rdb.ttl(f"chat:history:{user.id}")

            await msg.reply(
                f"会话历史中共有{len(chat_history)}条消息，总共{tokens}个Token，将会在{expired_at}秒后过期。\n"
                f"There are {len(chat_history)} messages in the chat history, "
                f"a total of {tokens} tokens, and it will expire in {expired_at} seconds."
            )
        else:
            await msg.reply(f"没有会话历史\nNo chat history.")
        return

    elif text == "help":
        await msg.reply(
            "使用方法：\n"
            # "/chat stat - 获取AI状态\n"
            "/chat reset - 重置会话\n"
            "/chat detail - 查看会话详情\n"
            "/chat settings:system_prompt <text> - 设置对话系统的提示\n"
            "/chat settings:clear - 清除对话设置\n"
            "Method of use:\n"
            # "/chat stat - Get AI status\n"
            "/chat reset - Reset the conversation\n"
            "/chat detail - View conversation details\n"
            "/chat settings:system_prompt <text> - Set the prompt for the conversation system\n"
            "/chat settings:clear - Clear the conversation settings"
        )
        return

    # settings or administrator
    try:
        # split the text into prompt and message
        parts = text.split(" ", 1)
        if len(parts) > 0:
            subcommand = parts[0]

            # user settings
            if subcommand == "settings:system_prompt" and len(parts) > 1:
                # 设置对话系统的提示
                prompt = " ".join(parts[1:])
                await rdb.set(f"chat:settings:{user.id}", dumps({"prompt_system": prompt}), ex=3600)
                await msg.reply(f"你的对话中系统Prompt设置成功。\nYour chat system prompt has been set.")
                return
            elif subcommand == "settings:clear":
                # 清除对话设置
                await rdb.delete(f"chat:settings:{user.id}")
                await msg.reply(f"你的对话设置已被清除。\nYour chat settings have been cleared.")
                return

            # administrator operations
            if await admin_operations(rdb, msg, chat, user, subcommand, parts):
                return
    except:
        pass

    if len(text) < 5:
        logger.warning(f"{prefix} message too short, ignored")
        return

    if len(text) > 1024:
        logger.warning(f"{prefix} message too long, ignored")
        return

    try:
        text_resp = await generate_text(chat, user, text)
        if not text_resp:
            logger.warning(f"{prefix} generate text error, ignored")
            return
    except Exception as e:
        logger.error(f"{prefix} text {text} error: {e}")
        await msg.reply(f"error: {e}")

    text_resp += "\n\n---\n\n *Powered by Google Gemini Pro*"
    success = False

    try:
        await msg.reply(text_resp, parse_mode="Markdown", disable_web_page_preview=True)
        success = True
    except exceptions.TelegramBadRequest as e:
        logger.warning(f"{prefix} invalid text {text_resp}, error: {e}")
        await msg.reply(text_resp, disable_web_page_preview=True)
        success = True
    except Exception as e:
        logger.error(f"{prefix} reply error: {e}")
        await msg.reply(f"error: {e}")

    if success:
        await increase_user_count(rdb, user.id)


def count_tokens(string: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens


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
        return True
    elif subcommand == "admin:allow" and target_user_id:
        if pre_msg and pre_msg.from_user:
            await allow_user(rdb, target_user_id)
        else:
            await allow_user(rdb, user.id)

        return True
    elif subcommand == "admin:quota" and target_user_id:
        try:
            quota = int(arguments[1])
            await update_user_quota(rdb, target_user_id, quota)
            await msg.reply(f"用户{user.id}的配额已经设置为{quota}。\nUser {user.id}'s quota has been set to {quota}.")
        except:
            await msg.reply(f"设置配额失败。\nFailed to set quota.")
        return True
    elif subcommand == "admin:total_used":
        total = await total_user_requested(rdb)
        await msg.reply(f"总共请求了{total}次。\nA total of {total} requests have been made.")
        return True
    elif subcommand == "admin:total_user":
        total = await count_user(rdb)
        await msg.reply(f"总共有{total}个用户。\nThere are a total of {total} users.")
        return True

    return False


async def check_user_permission(rdb: "aioredis.Redis", chat_id: int, uid: int) -> bool:
    administrator = manager.config["ai"]["administrator"]

    # miss administator
    if not administrator:
        return False

    if uid == int(administrator):
        return True

    raw = await rdb.hget(f"chat:user:{uid}", "disabled")
    if raw is None or raw == 1:
        return False

    # check qutoa
    quota = await rdb.hget(f"chat:user:{uid}", "quota")
    if quota and int(quota) > 0:
        count = await rdb.hget(f"chat:user:{uid}", "count")
        if count and int(count) >= int(quota):
            return False

    return True


async def init_user(rdb: "aioredis.Redis", uid: int):
    await rdb.hset(f"chat:user:{uid}", "disabled", 0)
    await rdb.hset(f"chat:user:{uid}", "count", 0)
    await rdb.hset(f"chat:user:{uid}", "quota", -1)
    await rdb.hset(f"chat:user:{uid}", "last", "1970-01-01T00:00:00Z")


async def ban_user(rdb: "aioredis.Redis", uid: int):
    # check & set
    if not await rdb.hexists(f"chat:user:{uid}", "disabled"):
        await init_user(rdb, uid)
        return

    await rdb.hset(f"chat:user:{uid}", "disabled", 1)


async def allow_user(rdb: "aioredis.Redis", uid: int):
    # check & set, use hexists
    if not await rdb.hexists(f"chat:user:{uid}", "disabled"):
        await init_user(rdb, uid)
        return

    await rdb.hset(f"chat:user:{uid}", "disabled", 0)


async def increase_user_count(rdb: "aioredis.Redis", uid: int):
    # check & set
    if not await rdb.hexists(f"chat:user:{uid}", "count"):
        await init_user(rdb, uid)
        return

    await rdb.hincrby(f"chat:user:{uid}", "count", 1)
    await rdb.hset(f"chat:user:{uid}", "last", datetime.now().isoformat())


async def update_user_quota(rdb: "aioredis.Redis", uid: int, quota: int):
    # check & set
    if not await rdb.hexists(f"chat:user:{uid}", "quota"):
        await init_user(rdb, uid)
        return

    await rdb.hset(f"chat:user:{uid}", "quota", quota)


async def count_user(rdb: "aioredis.Redis") -> int:
    # use scan
    cursor = b"0"
    total = 0
    while cursor:
        cursor, keys = await rdb.scan(cursor, match="chat:user:*", count=100)
        total += len(keys)

    return total


async def total_user_requested(rdb: "aioredis.Redis") -> int:
    """
    计算所有的 chat:user:{uid}:count 总量
    """
    # use scan
    cursor = b"0"
    total = 0
    while cursor:
        cursor, keys = await rdb.scan(cursor, match="chat:user:*", count=100)
        for key in keys:
            count = await rdb.hget(key, "count")
            if count:
                total += int(count)

    return total
