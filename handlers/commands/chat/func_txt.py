from aiogram import types
from manager import manager
from orjson import loads, dumps

from .utils import count_tokens

logger = manager.logger

output_format_contorl = "response output format as telegram markdown v2."


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
        "model": "gemini-1.0-pro",
        "max_tokens": 30720,  # 32k for gemini-pro
        "temperature": 0.9,
        "top_p": 1,
        "top_k": 1,
        "messages": [
            {"role": "system", "content": output_format_contorl},
            {"role": "system", "content": prompt_system},
            *chat_history,
        ],
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
