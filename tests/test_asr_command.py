"""测试 handlers/commands/asr.py 中的 ASR 命令"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta


pytestmark = pytest.mark.asyncio


class TestASRCommand:
    """测试 asr 命令"""

    async def test_asr_with_voice_message(self):
        """测试语音消息的语音识别"""
        from handlers.commands.asr import asr

        # 模拟回复消息 (语音)
        mock_reply_msg = MagicMock()
        mock_reply_msg.voice = True
        mock_reply_msg.media = True
        mock_reply_msg.id = 123

        # 模拟事件
        mock_event = MagicMock()
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)
        mock_event.chat_id = -100123456789

        # 模拟聊天
        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Test Group"

        # 模拟用户
        mock_user = MagicMock()
        mock_user.first_name = "Test"
        mock_user.last_name = None

        # 模拟 manager
        mock_manager = MagicMock()
        mock_manager.client = MagicMock()
        mock_manager.client.download_media = AsyncMock(return_value=b"fake_audio_data")
        mock_manager.reply = AsyncMock()
        mock_manager.logger = MagicMock()

        # 模拟 ASR 转录
        with patch("handlers.commands.asr.manager", mock_manager):
            with patch("handlers.commands.asr.openai_whisper", AsyncMock(return_value="你好世界")):
                with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                    with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                        await asr(mock_event)

                        # 验证调用了回复
                        assert mock_manager.reply.called

    async def test_asr_with_media_message(self):
        """测试带媒体消息的语音识别"""
        from handlers.commands.asr import asr

        mock_reply_msg = MagicMock()
        mock_reply_msg.voice = False
        mock_reply_msg.media = True
        mock_reply_msg.id = 123

        mock_event = MagicMock()
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.client = MagicMock()
        mock_manager.client.download_media = AsyncMock(return_value=b"audio_data")
        mock_manager.reply = AsyncMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.asr.manager", mock_manager):
            with patch("handlers.commands.asr.openai_whisper", AsyncMock(return_value="Hello")):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                    await asr(mock_event)

                    assert mock_manager.reply.called

    async def test_asr_without_reply(self):
        """测试没有回复消息"""
        from handlers.commands.asr import asr

        mock_event = MagicMock()
        mock_event.get_reply_message = AsyncMock(return_value=None)

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.asr.manager", mock_manager):
            await asr(mock_event)

            # 不应该有任何操作
            pass

    async def test_asr_without_voice_or_media(self):
        """测试非语音或媒体消息"""
        from handlers.commands.asr import asr

        mock_reply_msg = MagicMock()
        mock_reply_msg.voice = False
        mock_reply_msg.media = False

        mock_event = MagicMock()
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.asr.manager", mock_manager):
            await asr(mock_event)

            # 不处理非语音/媒体消息
            pass

    async def test_asr_download_failure(self):
        """测试下载失败"""
        from handlers.commands.asr import asr

        mock_reply_msg = MagicMock()
        mock_reply_msg.voice = True
        mock_reply_msg.media = True

        mock_event = MagicMock()
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)

        mock_manager = MagicMock()
        mock_manager.client = MagicMock()
        mock_manager.client.download_media = AsyncMock(return_value=None)
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.asr.manager", mock_manager):
            await asr(mock_event)

            # 下载失败不继续处理
            pass

    async def test_asr_empty_result(self):
        """测试 ASR 返回空结果"""
        from handlers.commands.asr import asr

        mock_reply_msg = MagicMock()
        mock_reply_msg.voice = True
        mock_reply_msg.media = True

        mock_event = MagicMock()
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.client = MagicMock()
        mock_manager.client.download_media = AsyncMock(return_value=b"audio_data")
        mock_manager.reply = AsyncMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.asr.manager", mock_manager):
            with patch("handlers.commands.asr.openai_whisper", AsyncMock(return_value=None)):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                    await asr(mock_event)

                    # 空结果不回复
                    pass

    async def test_asr_exception_handling(self):
        """测试异常处理"""
        from handlers.commands.asr import asr

        mock_reply_msg = MagicMock()
        mock_reply_msg.voice = True
        mock_reply_msg.media = True

        mock_event = MagicMock()
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)
        mock_event.date = MagicMock()
        mock_event.date.__add__ = lambda self, other: MagicMock()

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.client = MagicMock()
        mock_manager.client.download_media = AsyncMock(return_value=b"audio_data")
        mock_manager.reply = AsyncMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.asr.manager", mock_manager):
            with patch("handlers.commands.asr.openai_whisper", AsyncMock(side_effect=Exception("ASR error"))):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                    await asr(mock_event)

                    # 验证记录了异常
                    mock_manager.logger.exception.assert_called()
                    # 验证回复了错误消息
                    assert mock_manager.reply.called

    async def test_asr_logs_user_info(self):
        """测试记录用户信息日志"""
        from handlers.commands.asr import asr

        mock_reply_msg = MagicMock()
        mock_reply_msg.voice = True
        mock_reply_msg.media = True

        mock_event = MagicMock()
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)
        mock_event.chat_id = -100123456789

        mock_chat = MagicMock()
        mock_chat.id = -100123456789

        mock_user = MagicMock()
        mock_user.first_name = "Test"
        mock_user.last_name = "User"

        mock_manager = MagicMock()
        mock_manager.client = MagicMock()
        mock_manager.client.download_media = AsyncMock(return_value=b"audio_data")
        mock_manager.reply = AsyncMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.asr.manager", mock_manager):
            with patch("handlers.commands.asr.openai_whisper", AsyncMock(return_value="Hello")):
                with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                    with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                        await asr(mock_event)

                        # 验证记录了用户信息
                        assert mock_manager.logger.info.called
                        call_args = mock_manager.logger.info.call_args[0][0]
                        assert "Test User" in call_args

    async def test_asr_unsupported_group_type(self):
        """测试不支持的群组类型"""
        from handlers.commands.asr import asr
        from handlers.member_captcha.config import get_chat_type

        mock_reply_msg = MagicMock()
        mock_reply_msg.voice = True

        mock_event = MagicMock()
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)

        mock_chat = MagicMock()
        mock_chat.title = "Channel"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        # 模拟不支持的聊天类型
        with patch("handlers.commands.asr.manager", mock_manager):
            with patch("handlers.commands.asr.get_chat_type", return_value="channel"):
                with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                    await asr(mock_event)

                    # 不支持的类型不处理
                    pass


class TestASRSupportedGroups:
    """测试支持的群组类型"""

    def test_supported_group_types(self):
        """验证支持的群组类型"""
        from handlers.commands.asr import SUPPORT_GROUP_TYPES

        assert "supergroup" in SUPPORT_GROUP_TYPES
        assert "group" in SUPPORT_GROUP_TYPES
        assert "private" in SUPPORT_GROUP_TYPES
