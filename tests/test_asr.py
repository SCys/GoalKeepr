"""测试 utils/asr.py 中的 Whisper API 功能"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import io


pytestmark = pytest.mark.asyncio


class TestOpenaiWhisper:
    """测试 openai_whisper 函数"""

    async def test_successful_transcription(self):
        """测试成功的语音转录"""
        from utils.asr import openai_whisper

        # 模拟音频数据
        audio_data = io.BytesIO(b"fake_audio_data")

        # 模拟响应
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"text": "你好世界"})

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)
        mock_manager.config = {"asr": {"endpoint": "http://test-asr/whisper"}}

        with patch("utils.asr.manager", mock_manager):
            result = await openai_whisper(audio_data)
            assert result == "你好世界"

    async def test_missing_endpoint_config(self):
        """测试缺少 endpoint 配置"""
        from utils.asr import openai_whisper

        audio_data = io.BytesIO(b"fake_audio_data")

        mock_manager = MagicMock()
        mock_manager.config = {}

        mock_logger = MagicMock()
        # patch both manager and logger
        with patch("utils.asr.manager", mock_manager):
            with patch("utils.asr.logger", mock_logger):
                result = await openai_whisper(audio_data)
                assert result is None
                mock_logger.exception.assert_called()

    async def test_http_error_response(self):
        """测试 HTTP 错误响应"""
        from utils.asr import openai_whisper

        audio_data = io.BytesIO(b"fake_audio_data")

        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)
        mock_manager.config = {"asr": {"endpoint": "http://test-asr/whisper"}}

        with patch("utils.asr.manager", mock_manager):
            with pytest.raises(Exception) as exc_info:
                await openai_whisper(audio_data)
            assert "Internal Server Error" in str(exc_info.value)

    async def test_empty_text_response(self):
        """测试空文本响应"""
        from utils.asr import openai_whisper

        audio_data = io.BytesIO(b"fake_audio_data")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"text": ""})

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)
        mock_manager.config = {"asr": {"endpoint": "http://test-asr/whisper"}}

        with patch("utils.asr.manager", mock_manager):
            result = await openai_whisper(audio_data)
            assert result == ""

    async def test_timeout_config(self):
        """验证超时配置"""
        from utils.asr import openai_whisper
        from aiohttp import ClientTimeout

        audio_data = io.BytesIO(b"fake_audio_data")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"text": "test"})

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)
        mock_manager.config = {"asr": {"endpoint": "http://test-asr/whisper"}}

        with patch("utils.asr.manager", mock_manager):
            await openai_whisper(audio_data)

        # 验证 post 调用的 timeout 参数
        call_args = mock_session.post.call_args
        assert call_args is not None
        timeout_arg = call_args.kwargs.get('timeout')
        assert timeout_arg is not None
        assert timeout_arg.sock_read == 240
