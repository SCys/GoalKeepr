from aiogram import exceptions, types
from aiogram.filters import Command

from manager import manager
import tiktoken
from orjson import loads, dumps

DELETED_AFTER = 5
BAN_MEMBER = 300  # 300s

logger = manager.logger


async def get_stat():
    config = manager.config

    host = config["ai"]["proxy_host"]
    if not host:
        logger.error("google gemini host is empty")
        return

    url = f"{host}/api/ai/google/gemini/text_generation"
    session = await manager.bot.session.create_session()
    async with session.get(url) as response:
        if response.status != 200:
            logger.error(f"get stat error: {response.status} {await response.text()}")
            return

        data = await response.json()

        # check error
        if "error" in data:
            code = data["error"]["code"]
            message = data["error"]["message"]
            logger.error(f"get stat error: {code} {message}")
            return

        return data["data"]


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
    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    text = msg.text
    text = text.replace("/chat", "", 1).strip()
    if not text:
        logger.warning(f"{prefix} message without text, ignored")
        return
    
    rdb = await manager.get_redis()

    if text == "stat":
        try:
            stat = await get_stat()
            if not stat:
                logger.warning(f"{prefix} get stat error, ignored")
                return

            total = stat["total"]
            qps = stat["qps"]
            await msg.reply(f"total: {total}\nqps: {qps}")
        except Exception as e:
            logger.error(f"{prefix} get stat error: {e}")
            await msg.reply(f"error: {e}")

        return

    elif text == "reset":
        if rdb:
            await rdb.delete(f"chat:history:{user.id}")
            await msg.reply(f"会话已经重置\nYour chat history has been reset.")

        return
    
    elif text == 'detail':
        if rdb:
            chat_history = await rdb.get(f"chat:history:{user.id}")
            if chat_history:
                chat_history = loads(chat_history)
                tokens = 0
                for msg in chat_history:
                    tokens += count_tokens(msg["content"])
                await msg.reply(f"会话历史中共有{len(chat_history)}条消息，总共{tokens}个Token\nThere are {len(chat_history)} messages in the chat history, a total of {tokens} tokens.")
            else:
                await msg.reply(f"没有会话历史\nNo chat history.")
        return


    # split the text into prompt and message
    try:
        if rdb:
            parts = text.split(" ", 1)
            if len(parts) > 1:
                subcommand, text = parts
                if subcommand == "settings:prompt_system":
                    # 设置对话系统的提示
                    await rdb.set(f"chat:settings:{user.id}", dumps({"prompt_system": text}), ex=3600)
                    await msg.reply(f"你的对话中系统Prompt设置成功。\nYour chat system prompt has been set.")
                    return
                elif subcommand == "settings:clear":
                    # 清除对话设置
                    await rdb.delete(f"chat:settings:{user.id}")
                    await msg.reply(f"你的对话设置已被清除。\nYour chat settings have been cleared.")
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

    try:
        await msg.reply(text_resp, parse_mode="Markdown", disable_web_page_preview=True)
    except exceptions.TelegramBadRequest as e:
        logger.warning(f"{prefix} invalid text {text_resp}, error: {e}")
        await msg.reply(text_resp, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"{prefix} reply error: {e}")
        await msg.reply(f"error: {e}")


def count_tokens(string: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens
