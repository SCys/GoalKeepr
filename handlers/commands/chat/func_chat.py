from aiogram import exceptions, types
from aiogram.filters import Command
import re
from manager import manager
from orjson import loads, dumps

from .utils import count_tokens
from .func_admin import admin_operations
from .func_txt import generate_text
from .func_user import check_user_permission, increase_user_count

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

    if len(text) < 3:
        logger.warning(f"{prefix} message too short, ignored")
        return

    # if len(text) > 1024:
    #     logger.warning(f"{prefix} message too long, ignored")
    #     return

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
        logger.info(f"{prefix} do chat command, send token {count_tokens(text)}, response token {count_tokens(text_resp)}")
