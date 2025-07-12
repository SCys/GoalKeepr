from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Union

import telegramify_markdown
from aiogram import types
from aiohttp import ClientSession, ClientTimeout, ClientResponse
from orjson import dumps, loads

from manager import manager

from .base import count_tokens

logger = manager.logger


@dataclass
class ModelDescription:
    name: str
    input_length: int
    output_length: int
    rate_minute: float
    rate_daily: float


PROMPT_SYSTEM = None
CONVERSATION_TTL = 3600
DEFAULT_MODEL = "deepseek-r1"
SUPPORTED_MODELS = {
    "gemini-pro": ModelDescription(
        name="Gemini 2.5 Pro",
        input_length=1048576,
        output_length=65535,
        rate_minute=10,
        rate_daily=500,
    ),
    "gemini-flash": ModelDescription(
        name="Gemini 2.5 Flash",
        input_length=1048576,
        output_length=65535,
        rate_minute=10,
        rate_daily=500,
    ),
    "gemini-flash-lite": ModelDescription(
        name="Gemini 2.5 Flash Lite",
        input_length=1048576,
        output_length=65535,
        rate_minute=10,
        rate_daily=500,
    ),
    "llama-4": ModelDescription(
        name="Meta Llama 4 Maverick",
        input_length=128000,  # 128k
        output_length=4096,  # 4k
        rate_minute=5,
        rate_daily=1000,
    ),
    "deepseek-r1": ModelDescription(
        name="DeepSeek R1 0528",
        input_length=163840,  # 164k
        output_length=163840,  # 164k
        rate_minute=5,
        rate_daily=1000,
    ),
    "grok": ModelDescription(
        name="Grok 3",
        input_length=131072,
        output_length=65536,
        rate_minute=5,
        rate_daily=1000,
    ),
    "qwen3": ModelDescription(
        name="Qwen 3.2 235B A22",
        input_length=40960,  # 41k
        output_length=40960,  # 41k
        rate_minute=5,
        rate_daily=1000,
    ),
    "gemma-3": ModelDescription(
        name="Gemma 3 27b",
        input_length=96000,  # 96k
        output_length=8192,  # 8k
        rate_minute=5,
        rate_daily=1000,
    ),
}


async def _api_request(url: str, data: Dict[str, Any], proxy_token: str) -> Dict[str, Any]:
    """Make API request to LLM provider and handle common error cases"""
    session = await manager.bot.session.create_session()  # type: ignore

    # 根据模型类型设置不同的超时时间
    model_name = data.get("model", DEFAULT_MODEL)

    # 默认超时设置
    timeout_config = ClientTimeout(
        total=180,  # 3分钟总超时
        connect=15,
        sock_read=170,  # 2分50秒读取超时
        sock_connect=20,
    )

    try:
        async with session.post(
            url,
            json=data,
            headers={"Authorization": f"Bearer {proxy_token}"},
            timeout=timeout_config,
        ) as response:
            if response.status != 200:
                error_message = await response.text()
                error_code = response.status
                logger.error(f"API request error: {error_code} {error_message}")
                raise ValueError(f"System error: {error_code} {error_message}")

            response_data = await response.json()

            # check error
            if "error" in response_data:
                code = response_data["error"].get("code", "unknown")
                message = response_data["error"].get("message", "Unknown error")
                logger.error(f"API response error: {code} {message}")
                raise ValueError(message)

            return response_data
    except Exception as e:
        if not isinstance(e, ValueError):
            # 针对不同类型的异常提供更具体的错误信息
            if "SocketTimeoutError" in str(type(e)) or "TimeoutError" in str(type(e)):
                logger.error(f"Request timeout for model {model_name}: {str(e)}")
                raise ValueError(f"请求超时，模型 {model_name} 响应时间过长，请稍后重试")
            elif "ClientConnectorError" in str(type(e)):
                logger.error(f"Connection error: {str(e)}")
                raise ValueError("无法连接到AI服务，请检查网络连接")
            else:
                logger.exception("Unexpected error during API request")
                raise ValueError(f"请求失败: {str(e)}")
        raise


async def tg_generate_text(chat: types.Chat, member: types.User, prompt: str) -> Optional[str]:
    config = manager.config

    host = config["ai"]["proxy_host"]
    if not host:
        logger.error("proxy host is empty")
        return None

    proxy_token = config["ai"]["proxy_token"]

    # default prompts
    prompt_system = PROMPT_SYSTEM
    chat_history = [
        # last message
        {"role": "user", "content": prompt},
    ]

    # first key as default model
    model_name = DEFAULT_MODEL
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

        # Select model based on user and global settings
        model_person = settings_person.get("model")
        model_global = settings_global.get("model")

        if model_person in SUPPORTED_MODELS:
            model_name = model_person
        elif model_global in SUPPORTED_MODELS:
            model_name = model_global

        # fallback to default model
        if not model_name or model_name not in SUPPORTED_MODELS:
            model_name = DEFAULT_MODEL

        model_input_length = SUPPORTED_MODELS[model_name].input_length
        truncate_input = min(model_input_length * 0.99, model_input_length - 1024)

        # 从Redis获取之前的对话历史
        prev_chat_history = await rdb.get(f"chat:history:{member.id}")
        if prev_chat_history:
            # convert prev_chat_history to list
            prev_chat_history = loads(prev_chat_history)
            chat_history = [*prev_chat_history, *chat_history]

            # 限制Tokens数字，并且删除多余的历史记录
            tokens = 0
            for i, msg in enumerate(chat_history):
                tokens += count_tokens(msg["content"])
                if tokens > truncate_input:
                    chat_history = chat_history[0 : i - 1]
                    break

    if prompt_system:
        chat_history.insert(0, {"role": "system", "content": prompt_system})

    # API request preparation
    url = f"{host}/v1/chat/completions"
    data = {
        "model": model_name,
        "max_tokens": 4096,  # 设置一个合理的固定输出token限制
        "messages": chat_history,
    }

    # Log model usage information
    logger.info(f"chat {chat.id} user {member.id} generate txt use model {model_name}({SUPPORTED_MODELS[model_name].name})")

    try:
        response_data = await _api_request(url, data, proxy_token)
        text = response_data["choices"][0]["message"]["content"]

        if rdb:
            # 保存到Redis，确保保存对话历史
            chat_history.append({"role": "assistant", "content": text})
            await rdb.set(f"chat:history:{member.id}", dumps(chat_history), ex=CONVERSATION_TTL)

        return telegramify_markdown.markdownify(text + f"\n\nPowered by *{SUPPORTED_MODELS[model_name].name}*")
    except ValueError as e:
        return str(e)


async def chat_completions(messages: List[Dict[str, Any]], model_name: Optional[str] = None, **kwargs) -> Optional[str]:
    config = manager.config

    host = config["ai"]["proxy_host"]
    if not host:
        logger.error("proxy host is empty")
        return

    if not model_name:
        model_name = DEFAULT_MODEL

    proxy_token = config["ai"]["proxy_token"]

    # API request preparation
    url = f"{host}/v1/chat/completions"
    data = {
        "model": model_name,
        "messages": messages,  # [{"role": "user", "content": prompt}],
        **kwargs,
    }

    try:
        response_data = await _api_request(url, data, proxy_token)
        logger.info(f"generate txt use model {model_name}")
        return response_data["choices"][0]["message"]["content"]
    except ValueError as e:
        return str(e)
