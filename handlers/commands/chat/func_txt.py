from dataclasses import dataclass

from aiogram import types
from aiohttp import ClientTimeout
from orjson import dumps, loads

from manager import manager

from ...utils import count_tokens

logger = manager.logger


@dataclass
class ModelDescription:
    name: str
    input_length: int
    output_length: int
    rate_minute: float
    rate_daily: float


CONVERSATION_TTL = 3600
DEFUALT_MODEL = "gemini-1.5-flash"
SUPPORTED_MODELS = {
    "gemini-1.5-flash": ModelDescription(
        name="Gemini 1.5 Flash",
        input_length=1048576,
        output_length=8192,
        rate_minute=15,
        rate_daily=1500,
    ),
    # "gemini-1.5-pro": ModelDescription(
    #     name="Gemini 1.5 Pro",
    #     input_length=2097152,
    #     output_length=8192,
    #     rate_minute=2,
    #     rate_daily=50,
    # ),
    "mixtral-8x7b-32768": ModelDescription(
        name="Mixtral 8x7b from Groq",
        input_length=32768,
        output_length=2048,
        rate_minute=0,
        rate_daily=0,
    ),
    "gemma2-9b-it": ModelDescription(
        name="Gemma2 9b IT from Groq",
        input_length=4096,
        output_length=2048,
        rate_minute=0,
        rate_daily=0,
    ),
}


async def generate_text(chat: types.Chat, member: types.User, prompt: str):
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

    # first key as default model
    model_name = DEFUALT_MODEL
    model_input_length = SUPPORTED_MODELS[model_name].input_length

    rdb = await manager.get_redis()
    if rdb:
        # 获取全局设置
        settings_global = await rdb.get("chat:settings:global")
        settings_global = loads(settings_global) if settings_global else {}

        # global disabled flag
        if settings_global.get("disabled", False):
            return "系统正在维护中...|System is under maintenance..."

        # 每个用户独立的对话设置
        settings_person = await rdb.get(f"chat:settings:{member.id}")
        settings_person = loads(settings_person) if settings_person else {}

        prompt_system_person = settings_person.get("prompt_system")
        if prompt_system_person:
            prompt_system = str(prompt_system_person).strip()

        # global model
        model_global = settings_global.get("model")
        model_person = settings_person.get("model")

        if model_person in SUPPORTED_MODELS:
            model_name = model_person
        elif model_global in SUPPORTED_MODELS:
            model_name = model_global

        # fallback to default model
        if not model_name or model_name not in SUPPORTED_MODELS:
            model_name = DEFUALT_MODEL

        model_input_length = SUPPORTED_MODELS[model_name].input_length

        truncate_input = min(model_input_length * 0.99, model_input_length - 1024)

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
                if tokens > truncate_input:
                    chat_history = chat_history[0 : i - 1]
                    break

    # request openai v1 like api
    url = f"{host}/v1/chat/completions"
    data = {
        "model": model_name,
        "max_tokens": model_input_length,
        "temperature": 0.75,
        # "top_p": 1,
        # "top_k": 1,
        "messages": [
            {"role": "system", "content": prompt_system},
            *chat_history,
        ],
    }

    # show use model info
    logger.info(f"chat {chat.id} user {member.id} generate txt use model {model_name}({model_name})")

    session = await manager.bot.session.create_session()  # type: ignore
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
            await rdb.set(f"chat:history:{member.id}", dumps(chat_history), ex=CONVERSATION_TTL)

        return text + f"\n\nPower by {model_name}"
