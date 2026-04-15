"""测试 handlers/utils/txt.py 中的 LLM 对话功能"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta
import orjson


pytestmark = pytest.mark.asyncio


class TestChatCompletionRequest:
    """测试 _chat_completion_request 函数"""

    async def test_successful_request(self):
        """测试成功的 API 请求"""
        from handlers.utils.txt import _chat_completion_request

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test response from AI"

        mock_create = AsyncMock(return_value=mock_response)
        mock_chat = MagicMock()
        mock_chat.completions.create = mock_create
        mock_client = MagicMock()
        mock_client.chat = mock_chat

        with patch("handlers.utils.txt.AsyncOpenAI") as mock_openai_class:
            mock_openai_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_openai_class.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _chat_completion_request(
                host="https://api.example.com",
                proxy_token="test_token",
                model="deepseek-r1",
                messages=[{"role": "user", "content": "Hello"}],
            )

            assert result == "Test response from AI"

    async def test_api_status_error_400(self):
        """测试 API 返回 400 错误"""
        from handlers.utils.txt import _chat_completion_request
        from openai import APIStatusError

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.request = MagicMock()

        async def raise_error(*args, **kwargs):
            raise APIStatusError("Bad Request", response=mock_response, body=None)

        mock_create = AsyncMock(side_effect=raise_error)
        mock_chat = MagicMock()
        mock_chat.completions.create = mock_create
        mock_client = MagicMock()
        mock_client.chat = mock_chat

        with patch("handlers.utils.txt.AsyncOpenAI") as mock_openai_class:
            mock_openai_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_openai_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError) as exc_info:
                await _chat_completion_request(
                    host="https://api.example.com",
                    proxy_token="test_token",
                    model="deepseek-r1",
                    messages=[{"role": "user", "content": "Hello"}],
                )

            assert "请求参数错误" in str(exc_info.value)

    async def test_api_status_error_401(self):
        """测试 API 返回 401 认证失败"""
        from handlers.utils.txt import _chat_completion_request
        from openai import APIStatusError

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.request = MagicMock()

        async def raise_error(*args, **kwargs):
            raise APIStatusError("Unauthorized", response=mock_response, body=None)

        mock_create = AsyncMock(side_effect=raise_error)
        mock_chat = MagicMock()
        mock_chat.completions.create = mock_create
        mock_client = MagicMock()
        mock_client.chat = mock_chat

        with patch("handlers.utils.txt.AsyncOpenAI") as mock_openai_class:
            mock_openai_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_openai_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError) as exc_info:
                await _chat_completion_request(
                    host="https://api.example.com",
                    proxy_token="test_token",
                    model="deepseek-r1",
                    messages=[{"role": "user", "content": "Hello"}],
                )

            assert "认证失败" in str(exc_info.value)

    async def test_api_status_error_429(self):
        """测试 API 返回 429 速率限制"""
        from handlers.utils.txt import _chat_completion_request
        from openai import APIStatusError

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.request = MagicMock()

        async def raise_error(*args, **kwargs):
            raise APIStatusError("Rate Limit", response=mock_response, body=None)

        mock_create = AsyncMock(side_effect=raise_error)
        mock_chat = MagicMock()
        mock_chat.completions.create = mock_create
        mock_client = MagicMock()
        mock_client.chat = mock_chat

        with patch("handlers.utils.txt.AsyncOpenAI") as mock_openai_class:
            mock_openai_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_openai_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError) as exc_info:
                await _chat_completion_request(
                    host="https://api.example.com",
                    proxy_token="test_token",
                    model="deepseek-r1",
                    messages=[{"role": "user", "content": "Hello"}],
                )

            assert "频繁" in str(exc_info.value)

    async def test_api_status_error_5xx(self):
        """测试 API 返回 5xx 服务器错误"""
        from handlers.utils.txt import _chat_completion_request
        from openai import APIStatusError

        for status_code in [502, 503, 504]:
            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_response.request = MagicMock()

            async def raise_error(*args, **kwargs):
                raise APIStatusError("Server Error", response=mock_response, body=None)

            mock_create = AsyncMock(side_effect=raise_error)
            mock_chat = MagicMock()
            mock_chat.completions.create = mock_create
            mock_client = MagicMock()
            mock_client.chat = mock_chat

            with patch("handlers.utils.txt.AsyncOpenAI") as mock_openai_class:
                mock_openai_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_openai_class.return_value.__aexit__ = AsyncMock(return_value=None)

                with pytest.raises(ValueError) as exc_info:
                    await _chat_completion_request(
                        host="https://api.example.com",
                        proxy_token="test_token",
                        model="deepseek-r1",
                        messages=[{"role": "user", "content": "Hello"}],
                    )

                assert str(status_code) in str(exc_info.value)

    async def test_empty_response_content(self):
        """测试 AI 返回空内容"""
        from handlers.utils.txt import _chat_completion_request

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        mock_create = AsyncMock(return_value=mock_response)
        mock_chat = MagicMock()
        mock_chat.completions.create = mock_create
        mock_client = MagicMock()
        mock_client.chat = mock_chat

        with patch("handlers.utils.txt.AsyncOpenAI") as mock_openai_class:
            mock_openai_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_openai_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError) as exc_info:
                await _chat_completion_request(
                    host="https://api.example.com",
                    proxy_token="test_token",
                    model="deepseek-r1",
                    messages=[{"role": "user", "content": "Hello"}],
                )

            assert "空内容" in str(exc_info.value)

    async def test_network_error(self):
        """测试网络连接错误"""
        from handlers.utils.txt import _chat_completion_request

        mock_create = AsyncMock(side_effect=ConnectionError("Connection failed"))
        mock_chat = MagicMock()
        mock_chat.completions.create = mock_create
        mock_client = MagicMock()
        mock_client.chat = mock_chat

        with patch("handlers.utils.txt.AsyncOpenAI") as mock_openai_class:
            mock_openai_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_openai_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError) as exc_info:
                await _chat_completion_request(
                    host="https://api.example.com",
                    proxy_token="test_token",
                    model="deepseek-r1",
                    messages=[{"role": "user", "content": "Hello"}],
                )

            assert "无法连接" in str(exc_info.value) or "请求失败" in str(exc_info.value)

    async def test_timeout_error(self):
        """测试超时错误"""
        from handlers.utils.txt import _chat_completion_request
        from httpx import Timeout

        mock_create = AsyncMock(side_effect=Timeout("Request timeout"))
        mock_chat = MagicMock()
        mock_chat.completions.create = mock_create
        mock_client = MagicMock()
        mock_client.chat = mock_chat

        with patch("handlers.utils.txt.AsyncOpenAI") as mock_openai_class:
            mock_openai_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_openai_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError) as exc_info:
                await _chat_completion_request(
                    host="https://api.example.com",
                    proxy_token="test_token",
                    model="deepseek-r1",
                    messages=[{"role": "user", "content": "Hello"}],
                )

            assert "超时" in str(exc_info.value) or "请求失败" in str(exc_info.value)


class TestTgGenerateText:
    """测试 tg_generate_text 函数"""

    async def test_successful_generation(self):
        """测试成功生成回复"""
        from handlers.utils.txt import tg_generate_text

        mock_manager = MagicMock()
        mock_manager.config = MagicMock()
        mock_manager.config.__getitem__ = lambda _, key: {
            "ai": {"proxy_host": "https://api.example.com", "proxy_token": "test_token"}
        }.get(key, {})
        mock_manager.get_redis = AsyncMock(return_value=None)

        with patch("handlers.utils.txt.manager", mock_manager):
            with patch("handlers.utils.txt._chat_completion_request", AsyncMock(return_value="Test response")):
                result = await tg_generate_text(chat_id=-100123456789, member_id=123456, prompt="Hello")

                assert result is not None
                assert "Powered by" in result

    async def test_missing_proxy_host(self):
        """测试缺少 proxy_host 配置"""
        from handlers.utils.txt import tg_generate_text

        mock_manager = MagicMock()
        mock_manager.config = MagicMock()
        mock_manager.config.__getitem__ = lambda _, key: {"ai": {"proxy_host": "", "proxy_token": ""}}.get(key, {})
        mock_manager.get_redis = AsyncMock(return_value=None)
        mock_manager.logger = MagicMock()

        with patch("handlers.utils.txt.manager", mock_manager):
            result = await tg_generate_text(chat_id=-100123456789, member_id=123456, prompt="Hello")

            assert result is None

    async def test_global_disabled_setting(self):
        """测试全局禁用设置"""
        from handlers.utils.txt import tg_generate_text

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b'{"disabled": true}')

        mock_manager = MagicMock()
        mock_manager.config = MagicMock()
        mock_manager.config.__getitem__ = lambda _, key: {"ai": {"proxy_host": "http://test", "proxy_token": "token"}}.get(key, {})
        mock_manager.get_redis = AsyncMock(return_value=mock_redis)

        with patch("handlers.utils.txt.manager", mock_manager):
            result = await tg_generate_text(chat_id=-100123456789, member_id=123456, prompt="Hello")

            assert "维护" in result or "维护" in result

    async def test_ai_exception_handling(self):
        """测试 AI 异常处理"""
        from handlers.utils.txt import tg_generate_text

        mock_manager = MagicMock()
        mock_manager.config = MagicMock()
        mock_manager.config.__getitem__ = lambda _, key: {"ai": {"proxy_host": "http://test", "proxy_token": "token"}}.get(key, {})
        mock_manager.get_redis = AsyncMock(return_value=None)

        with patch("handlers.utils.txt.manager", mock_manager):
            with patch("handlers.utils.txt._chat_completion_request", AsyncMock(side_effect=ValueError("AI service error"))):
                result = await tg_generate_text(chat_id=-100123456789, member_id=123456, prompt="Hello")

                assert result == "AI service error"


class TestChatCompletions:
    """测试 chat_completions 函数"""

    async def test_successful_completion(self):
        """测试成功完成对话补全"""
        from handlers.utils.txt import chat_completions

        mock_manager = MagicMock()
        mock_manager.config = MagicMock()
        mock_manager.config.__getitem__ = lambda self, key: {
            "ai": {"proxy_host": "http://test", "proxy_token": "token"}
        }.get(key, {})

        with patch("handlers.utils.txt.manager", mock_manager):
            with patch("handlers.utils.txt._chat_completion_request", AsyncMock(return_value="Test response")):
                result = await chat_completions(
                    messages=[{"role": "user", "content": "Hello"}],
                    model_name="gemini-pro",
                )

                assert result == "Test response"

    async def test_default_model(self):
        """测试使用默认模型"""
        from handlers.utils.txt import chat_completions

        mock_manager = MagicMock()
        mock_manager.config = MagicMock()
        mock_manager.config.__getitem__ = lambda self, key: {
            "ai": {"proxy_host": "http://test", "proxy_token": "token"}
        }.get(key, {})

        with patch("handlers.utils.txt.manager", mock_manager):
            with patch("handlers.utils.txt._chat_completion_request", AsyncMock(return_value="Test")) as mock_request:
                await chat_completions(messages=[{"role": "user", "content": "Hello"}])

                call_args = mock_request.call_args
                assert call_args[1]["model"] == "deepseek-r1"

    async def test_missing_proxy_host(self):
        """测试缺少 proxy_host"""
        from handlers.utils.txt import chat_completions

        mock_manager = MagicMock()
        mock_manager.config = MagicMock()
        mock_manager.config.__getitem__ = lambda self, key: {"ai": {"proxy_host": ""}}.get(key, {})
        mock_manager.logger = MagicMock()

        with patch("handlers.utils.txt.manager", mock_manager):
            result = await chat_completions(messages=[{"role": "user", "content": "Hello"}])

            assert result is None


class TestModelDescriptions:
    """测试模型配置"""

    def test_supported_models_exist(self):
        """验证支持的模型列表"""
        from handlers.utils.txt import SUPPORTED_MODELS

        expected_models = ["gemini-pro", "gemini-flash", "gemini-flash-lite", "llama-4", "deepseek-r1", "grok", "qwen3", "gemma-3"]

        for model in expected_models:
            assert model in SUPPORTED_MODELS
            assert SUPPORTED_MODELS[model].input_length > 0
            assert SUPPORTED_MODELS[model].output_length > 0
            assert SUPPORTED_MODELS[model].rate_minute >= 0
            assert SUPPORTED_MODELS[model].rate_daily >= 0

    def test_model_description_structure(self):
        """验证模型描述结构"""
        from handlers.utils.txt import ModelDescription, SUPPORTED_MODELS

        for model_name, desc in SUPPORTED_MODELS.items():
            assert isinstance(desc.name, str)
            assert isinstance(desc.input_length, int)
            assert isinstance(desc.output_length, int)
            assert isinstance(desc.rate_minute, (int, float))
            assert isinstance(desc.rate_daily, (int, float))
