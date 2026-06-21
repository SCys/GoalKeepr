from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Union
import asyncio
import time

import telegramify_markdown
from aiohttp import ClientTimeout, ClientResponse, ClientError, ServerTimeoutError, ClientConnectorError
from aiohttp.client_exceptions import ClientResponseError, ClientPayloadError, ServerDisconnectedError
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


BASIC_SYSTEM_PROMPT = "You are a helpful assistant in a Telegram chat. Keep responses concise and useful."
CONVERSATION_TTL = 1800
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

# 当 chat_model 配置的值不在 SUPPORTED_MODELS 中时使用的保守默认上下文长度（用于 /chat 历史截断）。
# 128k 对绝大多数现代模型是安全的默认值；已知模型会使用其精确的 input_length。
DEFAULT_INPUT_LENGTH = 128000


def get_ai_chat_model() -> str:
    """从 [ai] chat_model 读取 /chat 使用的模型名；未配置时回退 DEFAULT_MODEL。
    支持任意后端支持的模型标识符（不限于 SUPPORTED_MODELS 的 keys）。"""
    try:
        config = manager.config
        if config and config.has_section("ai"):
            m = str(config["ai"].get("chat_model", "")).strip()
            if m:
                return m
    except Exception:
        pass
    return DEFAULT_MODEL


def get_spam_models() -> list[str]:
    """从 [ai] spam_models 读取入群 LLM 检测模型列表；支持 ; 或 , 分隔。"""
    try:
        config = manager.config
        if config and config.has_section("ai"):
            raw = str(config["ai"].get("spam_models", "")).strip()
            if raw:
                parts = [p.strip() for p in raw.replace(",", ";").split(";") if p.strip()]
                if parts:
                    return parts
    except Exception:
        pass
    # 默认使用的模型列表，按优先级顺序排列
    logger.info("Using default spam models")
    return ["gemini-3.1-flash-lite", "gemma-4-31b-it"]


def get_image_optimize_models() -> list[str]:
    """从 [ai] image_optimize_models 读取 /image 提示词优化模型列表；支持 ; 或 , 分隔。"""
    try:
        config = manager.config
        if config and config.has_section("ai"):
            raw = str(config["ai"].get("image_optimize_models", "")).strip()
            if raw:
                parts = [p.strip() for p in raw.replace(",", ";").split(";") if p.strip()]
                if parts:
                    return parts
    except Exception:
        pass
    return ["deepseek-r1", "gemini-flash"]


async def _api_request(url: str, data: Dict[str, Any], proxy_token: str) -> Dict[str, Any]:
    """
    发送API请求到LLM提供商并处理常见错误情况
    包含重试机制和详细的错误处理
    """
    session = await manager.create_session()

    # 根据模型类型设置不同的超时时间
    model_name = data.get("model", DEFAULT_MODEL)

    # Some proxies inject stream_options without stream=True, causing vLLM 400.
    # Explicitly set stream=False for non-streaming callers to prevent this.
    data.setdefault("stream", False)
    
    # 默认超时设置
    timeout_config = ClientTimeout(
        total=180,  # 3分钟总超时
        connect=15,
        sock_read=170,  # 2分50秒读取超时
        sock_connect=20,
    )
    
    # 重试配置
    max_retries = 3
    retry_delay = 1  # 初始重试延迟（秒）
    
    # 可重试的HTTP状态码
    retryable_status_codes = {502, 503, 504, 429}
    
    for attempt in range(max_retries):
        try:
            start_time = time.time()
            
            async with session.post(
                url,
                json=data,
                headers={"Authorization": f"Bearer {proxy_token}"},
                timeout=timeout_config,
            ) as response:
                
                request_time = time.time() - start_time
                
                # 记录请求信息
                logger.info(f"API request | model={model_name} status={response.status} "
                           f"elapsed={request_time:.2f}s attempt={attempt + 1}/{max_retries}")
                
                # 处理不同的HTTP状态码
                if response.status == 200:
                    try:
                        response_data = await response.json()
                        
                        # 检查响应中的错误
                        if "error" in response_data:
                            error_info = response_data["error"]
                            error_code = error_info.get("code", "unknown")
                            error_message = error_info.get("message", "Unknown error")
                            
                            logger.error(f"API response error | model={model_name} "
                                       f"code={error_code} message={error_message}")
                            
                            # 根据错误代码决定是否重试
                            if error_code in ["rate_limit_exceeded", "server_error"] and attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay * (2 ** attempt))
                                continue
                                
                            raise ValueError(f"AI服务返回错误: {error_message}")
                        
                        return response_data
                        
                    except Exception as json_error:
                        logger.error(f"failed to parse response JSON | model={model_name} error={str(json_error)}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay * (2 ** attempt))
                            continue
                        raise ValueError("响应格式错误，请稍后重试")
                
                # 处理特定的HTTP错误状态码
                elif response.status == 400:
                    error_text = await response.text()
                    logger.error(f"bad request | model={model_name} status=400 detail={error_text}")
                    raise ValueError("请求参数错误，请检查输入内容")
                
                elif response.status == 401:
                    logger.error(f"auth failed | model={model_name} status=401")
                    raise ValueError("AI服务认证失败，请检查配置")
                
                elif response.status == 403:
                    logger.error(f"forbidden | model={model_name} status=403")
                    raise ValueError("无权访问AI服务，请检查权限配置")
                
                elif response.status == 429:
                    error_text = await response.text()
                    logger.warning(f"rate limited | model={model_name} status=429 attempt={attempt + 1}")
                    
                    if attempt < max_retries - 1:
                        # 对于429错误，使用更长的重试延迟
                        retry_wait = retry_delay * (3 ** attempt)
                        logger.info(f"retrying after {retry_wait}s...")
                        await asyncio.sleep(retry_wait)
                        continue
                    
                    raise ValueError("请求过于频繁，请稍后重试")
                
                elif response.status in retryable_status_codes:
                    error_text = await response.text()
                    logger.warning(f"server error | model={model_name} status={response.status} "
                                 f"attempt={attempt + 1} detail={error_text}")
                    
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay * (2 ** attempt))
                        continue
                    
                    raise ValueError(f"AI服务暂时不可用 ({response.status})，请稍后重试")
                
                else:
                    # 其他HTTP错误
                    error_text = await response.text()
                    logger.error(f"HTTP error | model={model_name} status={response.status} "
                               f"detail={error_text}")
                    raise ValueError(f"服务器错误 ({response.status})，请稍后重试")
        
        # 处理网络异常
        except ClientConnectorError as e:
            logger.error(f"connection error | model={model_name} attempt={attempt + 1} error={str(e)}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))
                continue
            
            raise ValueError("无法连接到AI服务，请检查网络连接或服务地址")
        
        except ServerTimeoutError as e:
            logger.error(f"server timeout | model={model_name} attempt={attempt + 1} error={str(e)}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))
                continue
            
            raise ValueError("服务器响应超时，请稍后重试")
        
        except asyncio.TimeoutError as e:
            logger.error(f"request timeout | model={model_name} attempt={attempt + 1} error={str(e)}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))
                continue
            
            raise ValueError("请求超时，请稍后重试")
        
        except ClientPayloadError as e:
            logger.error(f"payload error | model={model_name} attempt={attempt + 1} error={str(e)}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))
                continue
            
            raise ValueError("请求数据格式错误，请重试")
        
        except ServerDisconnectedError as e:
            logger.error(f"server disconnected | model={model_name} attempt={attempt + 1} error={str(e)}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))
                continue
            
            raise ValueError("服务器连接中断，请稍后重试")
        
        except ClientError as e:
            logger.error(f"client error | model={model_name} attempt={attempt + 1} error={str(e)}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))
                continue
            
            raise ValueError("网络请求失败，请稍后重试")
    
        except RuntimeError as e:
            logger.error(f"runtime error | model={model_name} attempt={attempt + 1} error={str(e)}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))
                continue
            
            raise ValueError("AI服务发生错误，请稍后重试")
        
        except ValueError:
            # ValueError是我们自定义的错误，不需要重试
            raise
        
        except Exception as e:
            logger.exception(f"unexpected error | model={model_name} attempt={attempt + 1} error={str(e)}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))
                continue
            
            raise ValueError(f"请求失败: {str(e)}")
    
    # 如果所有重试都失败了，抛出最终错误
    raise ValueError("所有重试都失败了，请稍后重试")


async def tg_generate_text(chat_id: int, member_id: int, prompt: str) -> Optional[str]:
    config = manager.config

    host = config["ai"]["proxy_host"]
    if not host:
        logger.error("proxy host is empty")
        return None

    proxy_token = config["ai"]["proxy_token"]

    # Basic fixed system prompt for the simplified 30min TTL session feature.
    # (No per-user/global overrides in the reset basic version.)
    prompt_system = BASIC_SYSTEM_PROMPT
    chat_history = [
        {"role": "user", "content": prompt},
    ]

    # Always use the default model in the basic version (advanced per-user model selection removed).
    # chat_model 现在支持任意后端模型名（不限于 SUPPORTED_MODELS keys）。
    model_name = get_ai_chat_model()
    model_desc = SUPPORTED_MODELS.get(model_name)
    if model_desc:
        model_input_length = model_desc.input_length
        display_name = model_desc.name
    else:
        model_input_length = DEFAULT_INPUT_LENGTH
        display_name = model_name
        logger.info(f"chat_model '{model_name}' not listed in SUPPORTED_MODELS, using default input length {DEFAULT_INPUT_LENGTH} and raw name for display")

    rdb = await manager.get_redis()
    if rdb:
        # No global "disabled", no per-user settings/model/prompt (simplified).
        truncate_input = min(model_input_length * 0.99, model_input_length - 1024)

        # Load previous conversation history (per-user, 30min TTL).
        prev_chat_history = await rdb.get(f"chat:history:{member_id}")
        if prev_chat_history:
            prev_chat_history = loads(prev_chat_history)
            # Drop any leading system message from previous saves to avoid duplicate systems
            # (we will re-insert the current BASIC_SYSTEM_PROMPT).
            if prev_chat_history and prev_chat_history[0].get("role") == "system":
                prev_chat_history = prev_chat_history[1:]
            chat_history = [*prev_chat_history, *chat_history]

            # Limit by tokens and drop oldest excess (reuse original truncation logic).
            tokens = 0
            for i, msg in enumerate(chat_history):
                tokens += count_tokens(msg["content"])
                if tokens > truncate_input:
                    chat_history = chat_history[0 : i - 1]
                    break

    # Insert the basic system prompt (always present for the basic feature).
    if prompt_system:
        chat_history.insert(0, {"role": "system", "content": prompt_system})

    # API request preparation
    url = f"{host}/v1/chat/completions"
    data = {
        "model": model_name,
        "max_tokens": 4096,  # fixed reasonable output limit
        "messages": chat_history,
    }

    # Log model usage information
    logger.info(f"chat {chat_id} user {member_id} generating text with model {model_name} ({display_name})")

    try:
        response_data = await _api_request(url, data, proxy_token)
        text = response_data["choices"][0]["message"]["content"]

        if rdb:
            # Save full history (incl. system) back with the 30min TTL.
            chat_history.append({"role": "assistant", "content": text})
            await rdb.set(f"chat:history:{member_id}", dumps(chat_history), ex=CONVERSATION_TTL)

        return telegramify_markdown.markdownify(text + f"\n\nPowered by *{display_name}*")
    except ValueError as e:
        return str(e)


async def chat_completions(messages: List[Dict[str, Any]], model_name: Optional[str] = None, **kwargs) -> Optional[str]:
    config = manager.config

    host = config["ai"]["proxy_host"]
    if not host:
        logger.error("proxy host is empty")
        return

    if not model_name:
        model_name = get_ai_chat_model()

    proxy_token = config["ai"]["proxy_token"]

    # API request preparation
    url = f"{host}/v1/chat/completions"
    data = {
        "model": model_name,
        "messages": messages,  # [{"role": "user", "content": prompt}],
        **kwargs,
    }

    response_data = await _api_request(url, data, proxy_token)
    logger.debug(f"text generated with model {model_name}")
    return response_data["choices"][0]["message"]["content"]