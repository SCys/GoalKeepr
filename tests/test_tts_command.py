"""测试 handlers/commands/tts.py 中的 TTS 命令"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from handlers.member_captcha.config import get_chat_type

pytestmark = pytest.mark.asyncio


class TestTTSCommand:
    """测试 tts 命令"""

    async def test_tts_with_direct_text(self):
        """测试直接文本的 TTS"""
        from handlers.commands.tts import tts

        mock_event = MagicMock()
        mock_event.text = "/tts hello world"
        mock_event.reply = AsyncMock()
        mock_event.chat_id = -100123456789

        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Test Group"

        mock_user = MagicMock()
        mock_user.first_name = "Test"
        mock_user.last_name = None

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.tts.manager", mock_manager):
            with patch("handlers.commands.tts.get_chat_type", return_value="supergroup"):
                with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                    with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                        with patch("handlers.commands.tts.reply_tts", AsyncMock()):
                            await tts(mock_event)

                            # 验证调用了 reply_tts
                            handlers.commands.tts.reply_tts.assert_called_once()

    async def test_tts_with_reply_message(self):
        """测试回复消息的 TTS"""
        from handlers.commands.tts import tts

        mock_reply_msg = MagicMock()
        mock_reply_msg.text = "hello from reply"

        mock_event = MagicMock()
        mock_event.text = "/tts"
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)
        mock_event.chat_id = -100123456789

        mock_chat = MagicMock()
        mock_chat.id = -100123456789

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.tts.manager", mock_manager):
            with patch("handlers.commands.tts.get_chat_type", return_value="group"):
                with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                    with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                        with patch("handlers.commands.tts.reply_tts", AsyncMock()):
                            await tts(mock_event)

                            handlers.commands.tts.reply_tts.assert_called_once()

    async def test_tts_without_text(self):
        """测试没有文本的情况"""
        from handlers.commands.tts import tts

        mock_event = MagicMock()
        mock_event.text = "/tts"
        mock_event.get_reply_message = AsyncMock(return_value=None)

        mock_chat = MagicMock()

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.tts.manager", mock_manager):
            with patch("handlers.commands.tts.get_chat_type", return_value="private"):
                with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                    with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                        await tts(mock_event)

                        # 不应该调用 reply_tts
                        handlers.commands.tts.reply_tts.assert_not_called()

    async def test_tts_unsupported_chat_type(self):
        """测试不支持的聊天类型"""
        from handlers.commands.tts import tts

        mock_event = MagicMock()
        mock_event.text = "/tts test"

        mock_chat = MagicMock()
        mock_chat.title = "Channel"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.tts.manager", mock_manager):
            with patch("handlers.commands.tts.get_chat_type", return_value="channel"):
                with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                    await tts(mock_event)

                    # 不支持的类型不处理
                    handlers.commands.tts.reply_tts.assert_not_called()

    async def test_tts_no_user(self):
        """测试没有用户的情况"""
        from handlers.commands.tts import tts

        mock_event = MagicMock()
        mock_event.text = "/tts test"
        mock_event.get_sender = AsyncMock(return_value=None)

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.tts.manager", mock_manager):
            await tts(mock_event)

            # 没有用户，不处理
            handlers.commands.tts.reply_tts.assert_not_called()

    async def test_tts_reply_tts_failure(self):
        """测试 reply_tts 失败的情况"""
        from handlers.commands.tts import tts

        mock_event = MagicMock()
        mock_event.text = "/tts test"

        mock_chat = MagicMock()

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.tts.manager", mock_manager):
            with patch("handlers.commands.tts.get_chat_type", return_value="supergroup"):
                with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                    with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                        with patch("handlers.commands.tts.reply_tts", AsyncMock(return_value=False)):
                            await tts(mock_event)

    async def test_tts_logs_user_info(self):
        """测试记录用户信息日志"""
        from handlers.commands.tts import tts

        mock_event = MagicMock()
        mock_event.text = "/tts test"

        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Test Group"

        mock_user = MagicMock()
        mock_user.first_name = "Test"
        mock_user.last_name = "User"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.tts.manager", mock_manager):
            with patch("handlers.commands.tts.get_chat_type", return_value="supergroup"):
                with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                    with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                        with patch("handlers.commands.tts.reply_tts", AsyncMock()):
                            await tts(mock_event)

                            # 验证记录了用户信息
                            assert mock_manager.logger.info.called
                            call_args = mock_manager.logger.info.call_args[0][0]
                            assert "Test User" in call_args

    async def test_tts_with_bot_mention(self):
        """测试带 bot 提及的命令 /tts@botname"""
        from handlers.commands.tts import tts

        mock_event = MagicMock()
        mock_event.text = "/tts@GoalKeeprBot hello"
        mock_event.chat_id = -100123456789

        mock_chat = MagicMock()
        mock_chat.id = -100123456789

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.tts.manager", mock_manager):
            with patch("handlers.commands.tts.get_chat_type", return_value="supergroup"):
                with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                    with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                        with patch("handlers.commands.tts.reply_tts", AsyncMock()):
                            await tts(mock_event)

                            handlers.commands.tts.reply_tts.assert_called_once()
