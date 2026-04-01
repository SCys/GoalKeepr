from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from openai import APIError, APIStatusError, AsyncOpenAI
from orjson import dumps, loads
import telegramify_markdown

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


def _openai_error_to_message(e: APIError) -> str:
    """将 OpenAI 库异常转换为对用户友好的中文错误信息。"""
    if isinstance(e, APIStatusError):
        code = e.status_code
        if code == 400:
            return "请求参数错误，请检查输入内容"
        if code == 401:
            return "AI服务认证失败，请检查配置"
        if code == 403:
            return "无权访问AI服务，请检查权限配置"
        if code == 429:
            return "请求过于频繁，请稍后重试"
        if code in (502, 503, 504):
            return f"AI服务暂时不可用 ({code})，请稍后重试"
        return f"服务器错误 ({code})，请稍后重试"
    # 超时、连接错误等
    err = str(e).lower()
    if "timeout" in err or "timed out" in err:
        return "请求超时，请稍后重试"
    if "connection" in err or "connect" in err:
        return "无法连接到AI服务，请检查网络连接或服务地址"
    return f"请求失败: {str(e)}"


async def _chat_completion_request(
    host: str,
    proxy_token: str,
    model: str,
    messages: List[Dict[str, Any]],
    **kwargs: Any,
) -> str:
    """
    使用 OpenAI 兼容客户端请求 chat/completions，自动重试与统一异常处理。
    """
    base_url = f"{host.rstrip('/')}/v1"
    timeout = httpx.Timeout(180.0, connect=15.0, read=170.0)

    async with AsyncOpenAI(
        base_url=base_url,
        api_key=proxy_token,
        timeout=timeout,
        max_retries=3,
    ) as client:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs,
            )
            content = response.choices[0].message.content
            if content is None:
                raise ValueError("AI服务返回空内容，请稍后重试")
            return content
        except APIError as e:
            logger.warning(f"API请求异常 - 模型: {model}, 错误: {e}")
            raise ValueError(_openai_error_to_message(e)) from e
        except ValueError:
            raise
        except Exception as e:
            logger.exception(f"未预期的错误 - 模型: {model}, 错误: {e}")
            raise ValueError(f"请求失败: {str(e)}") from e


async def tg_generate_text(chat_id: int, member_id: int, prompt: str) -> Optional[str]:
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
        settings_person = await rdb.get(f"chat:settings:{member_id}")
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
        prev_chat_history = await rdb.get(f"chat:history:{member_id}")
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

    # Log model usage information
    logger.info(f"chat {chat_id} user {member_id} generate txt use model {model_name}({SUPPORTED_MODELS[model_name].name})")

    try:
        text = await _chat_completion_request(
            host,
            proxy_token,
            model_name,
            chat_history,
            max_tokens=4096,
        )

        if rdb:
            # 保存到Redis，确保保存对话历史
            chat_history.append({"role": "assistant", "content": text})
            await rdb.set(f"chat:history:{member_id}", dumps(chat_history), ex=CONVERSATION_TTL)

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

    logger.info(f"generate txt use model {model_name}")
    return await _chat_completion_request(host, proxy_token, model_name, messages, **kwargs)
