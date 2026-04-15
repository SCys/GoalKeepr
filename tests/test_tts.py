"""测试 utils/tts.py 中的 Edge TTS 功能"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import io


pytestmark = pytest.mark.asyncio


class TestEdgeTTS:
    """测试 Edge TTS 相关函数"""

    def test_supported_languages(self):
        """验证支持的语言列表"""
        from utils.tts import SUPPORT_LANGUAGES

        assert "zh-CN" in SUPPORT_LANGUAGES
        assert "en" in SUPPORT_LANGUAGES
        assert "ja" in SUPPORT_LANGUAGES
        assert SUPPORT_LANGUAGES["zh-CN"] == "zh-CN-XiaoxiaoNeural"
        assert SUPPORT_LANGUAGES["en"] == "en-US-AriaNeural"
        assert SUPPORT_LANGUAGES["ja"] == "ja-JP-NanamiNeural"


class TestEdgeExt:
    """测试 edge_ext 函数"""

    async def test_successful_audio_generation(self):
        """测试成功的音频生成"""
        from utils.tts import edge_ext

        async def mock_stream():
            yield {"type": "audio", "data": b"audio_chunk_1"}
            yield {"type": "audio", "data": b"audio_chunk_2"}
            yield {"type": "WordBoundary", "data": b"boundary_data"}

        mock_communicate_class = MagicMock()
        mock_communicate_class.return_value.stream = MagicMock(return_value=mock_stream())

        with patch("utils.tts.edge_tts.Communicate", mock_communicate_class):
            result = await edge_ext("Hello World", "zh-CN")
            assert result == b"audio_chunk_1audio_chunk_2"

    async def test_empty_audio_data(self):
        """测试空音频数据"""
        from utils.tts import edge_ext

        async def mock_stream():
            yield {"type": "WordBoundary", "data": b"boundary"}

        mock_communicate = MagicMock()
        mock_communicate.stream = MagicMock(return_value=mock_stream())

        with patch("utils.tts.edge_tts.Communicate", return_value=mock_communicate):
            result = await edge_ext("Hello", "zh-CN")
            assert result == b""

    async def test_stream_exception_handling(self):
        """测试流式处理异常"""
        from utils.tts import edge_ext

        mock_communicate = MagicMock()
        mock_communicate.stream = MagicMock(side_effect=Exception("Stream error"))

        with patch("utils.tts.edge_tts.Communicate", return_value=mock_communicate):
            with pytest.raises(Exception):
                await edge_ext("Hello", "zh-CN")


class TestReplyTts:
    """测试 reply_tts 函数"""

    async def test_successful_reply(self):
        """测试成功的语音回复"""
        from utils.tts import reply_tts

        async def mock_stream():
            yield {"type": "audio", "data": b"audio_data"}

        mock_communicate = MagicMock()
        mock_communicate.stream = MagicMock(return_value=mock_stream())

        mock_msg = MagicMock()
        mock_msg.chat_id = -100123456789
        mock_msg.id = 123

        mock_audio_segment = MagicMock()
        mock_audio_instance = MagicMock()
        mock_audio_instance.export = MagicMock()
        mock_audio_segment.from_file = MagicMock(return_value=mock_audio_instance)

        mock_manager = MagicMock()
        mock_manager.client.send_file = AsyncMock()

        with patch("utils.tts.edge_tts.Communicate", return_value=mock_communicate):
            with patch("utils.tts.AudioSegment", mock_audio_segment):
                with patch("utils.tts.manager", mock_manager):
                    result = await reply_tts(mock_msg, "Hello World", show_original=False)

                    assert result is True
                    mock_manager.client.send_file.assert_called()

    async def test_show_original_with_caption(self):
        """测试显示原文的回复"""
        from utils.tts import reply_tts

        async def mock_stream():
            yield {"type": "audio", "data": b"audio_data"}

        mock_communicate = MagicMock()
        mock_communicate.stream = MagicMock(return_value=mock_stream())

        mock_msg = MagicMock()
        mock_msg.chat_id = -100123456789
        mock_msg.id = 123

        mock_audio_segment = MagicMock()
        mock_audio_instance = MagicMock()
        mock_audio_instance.export = MagicMock()
        mock_audio_segment.from_file = MagicMock(return_value=mock_audio_instance)

        mock_manager = MagicMock()
        mock_manager.client.send_file = AsyncMock()

        with patch("utils.tts.edge_tts.Communicate", return_value=mock_communicate):
            with patch("utils.tts.AudioSegment", mock_audio_segment):
                with patch("utils.tts.manager", mock_manager):
                    result = await reply_tts(mock_msg, "Hello", show_original=True, lang="zh-CN")

                    assert result is True

    async def test_edge_ext_failure(self):
        """测试 edge_ext 失败的情况"""
        from utils.tts import reply_tts

        mock_msg = MagicMock()
        mock_msg.chat_id = -100123456789

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("utils.tts.edge_ext", AsyncMock(side_effect=Exception("TTS error"))):
            with patch("utils.tts.manager", mock_manager):
                result = await reply_tts(mock_msg, "Hello")

                assert result is False

    async def test_empty_audio_result(self):
        """测试空音频结果"""
        from utils.tts import reply_tts

        mock_msg = MagicMock()
        mock_msg.chat_id = -100123456789

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("utils.tts.edge_ext", AsyncMock(return_value=b"")):
            with patch("utils.tts.manager", mock_manager):
                result = await reply_tts(mock_msg, "Hello")

                assert result is False
