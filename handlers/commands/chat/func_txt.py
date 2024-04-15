from aiogram import types
from manager import manager
from orjson import loads, dumps
from aiohttp import ClientTimeout

from .utils import count_tokens

logger = manager.logger


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

    MODEL_NAME = "gemini-1.5-pro"
    MODEL_INPUT_LENGTH = 1048576
    MODEL_OUTPUT_LENGTH = 8192
    MODEL_INPUT_LIMIT = min(MODEL_INPUT_LENGTH * 0.99, MODEL_INPUT_LENGTH - 1024)

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
                if tokens > MODEL_INPUT_LIMIT:
                    chat_history = chat_history[i:]
                    break

    # request openai v1 like api
    url = f"{host}/v1/chat/completions"
    data = {
        "model": MODEL_NAME,
        "max_tokens": MODEL_OUTPUT_LENGTH,
        "temperature": 0.75,
        "top_p": 1,
        "top_k": 1,
        "messages": [
            {"role": "system", "content": prompt_system},
            *chat_history,
        ],
    }

    session = await manager.bot.session.create_session()
    async with session.post(
        url,
        json=data,
        headers={"Authorization": f"Bearer {proxy_token}"},
        timeout=ClientTimeout(
            total=100,
            connect=5,
            sock_read=90,
            sock_connect=10,
        ),
    ) as response:
        if response.status != 200:
            error_message = await response.text()
            error_code = response.status
            logger.error(f"generate text error: {error_code} {error_message}")
            return f"System error: {error_code} {error_message}"

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
