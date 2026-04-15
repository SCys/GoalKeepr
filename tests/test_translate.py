"""测试 handlers/commands/translate.py 中的翻译功能"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta


pytestmark = pytest.mark.asyncio


class TestTranslateCommand:
    """测试 translate 命令"""

    async def test_translate_with_reply(self):
        """测试翻译回复消息"""
        from handlers.commands.translate import translate

        mock_reply_msg = MagicMock()
        mock_reply_msg.text = "Hello World"
        mock_reply_msg.id = 123

        mock_event = MagicMock()
        mock_event.text = "/tr"
        mock_event.is_reply = True
        mock_event.reply_to_msg_id = 123
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)
        mock_event.respond = AsyncMock()

        mock_user = MagicMock()
        mock_user.first_name = "Test"
        mock_user.last_name = None
        mock_user.id = 123456

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()
        mock_manager.reply = AsyncMock()
        mock_manager.delete_message = AsyncMock()

        with patch("handlers.commands.translate.strip_text_prefix", return_value="Hello World"):
            with patch("handlers.commands.translate.ts.translate_text", return_value="你好世界"):
                with patch("handlers.commands.translate.reply_tts", AsyncMock(return_value=True)):
                    with patch("handlers.commands.translate.manager", mock_manager):
                        with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                            await translate(mock_event)

    async def test_translate_without_user(self):
        """测试没有用户的情况"""
        from handlers.commands.translate import translate

        mock_event = MagicMock()
        mock_event.text = "/tr"
        mock_event.get_sender = AsyncMock(return_value=None)
        mock_event.logger = MagicMock()

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.translate.manager", mock_manager):
            await translate(mock_event)

            mock_manager.logger.warning.assert_called()

    async def test_translate_empty_content(self):
        """测试空内容"""
        from handlers.commands.translate import translate

        mock_event = MagicMock()
        mock_event.text = "/tr"
        mock_event.is_reply = False
        mock_event.get_reply_message = AsyncMock(return_value=None)
        mock_event.respond = AsyncMock()

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.translate.manager", mock_manager):
            with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                await translate(mock_event)

                assert mock_event.respond.called

    async def test_translate_to_english(self):
        """测试翻译成英文"""
        from handlers.commands.translate import translate

        mock_reply_msg = MagicMock()
        mock_reply_msg.text = "你好"
        mock_reply_msg.id = 123

        mock_event = MagicMock()
        mock_event.text = "/tr en 你好"
        mock_event.is_reply = True
        mock_event.reply_to_msg_id = 123
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)
        mock_event.respond = AsyncMock()

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()
        mock_manager.reply = AsyncMock()
        mock_manager.delete_message = AsyncMock()

        with patch("handlers.commands.translate.strip_text_prefix", return_value="en 你好"):
            with patch("handlers.commands.translate.ts.translate_text", return_value="Hello") as mock_translate:
                with patch("handlers.commands.translate.reply_tts", AsyncMock(return_value=True)):
                    with patch("handlers.commands.translate.manager", mock_manager):
                        with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                            await translate(mock_event)

                            mock_translate.assert_called_with("你好", to_language="en", translator="google")

    async def test_translate_to_japanese(self):
        """测试翻译成日文"""
        from handlers.commands.translate import translate

        mock_reply_msg = MagicMock()
        mock_reply_msg.text = "Hello"

        mock_event = MagicMock()
        mock_event.text = "/tr jp Hello"
        mock_event.is_reply = True
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()
        mock_manager.reply = AsyncMock()
        mock_manager.delete_message = AsyncMock()

        with patch("handlers.commands.translate.strip_text_prefix", return_value="jp Hello"):
            with patch("handlers.commands.translate.ts.translate_text", return_value="こんにちは"):
                with patch("handlers.commands.translate.reply_tts", AsyncMock(return_value=True)):
                    with patch("handlers.commands.translate.manager", mock_manager):
                        with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                            await translate(mock_event)

    async def test_translate_to_chinese(self):
        """测试翻译成中文"""
        from handlers.commands.translate import translate

        mock_reply_msg = MagicMock()
        mock_reply_msg.text = "Hello"

        mock_event = MagicMock()
        mock_event.text = "/tr zh Hello"
        mock_event.is_reply = True
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()
        mock_manager.reply = AsyncMock()
        mock_manager.delete_message = AsyncMock()

        with patch("handlers.commands.translate.strip_text_prefix", return_value="zh Hello"):
            with patch("handlers.commands.translate.ts.translate_text", return_value="你好") as mock_translate:
                with patch("handlers.commands.translate.reply_tts", AsyncMock(return_value=True)):
                    with patch("handlers.commands.translate.manager", mock_manager):
                        with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                            await translate(mock_event)

                            mock_translate.assert_called_with("Hello", to_language="zh-CN", translator="google")

    async def test_translate_default_language(self):
        """测试默认翻译成中文"""
        from handlers.commands.translate import translate

        mock_reply_msg = MagicMock()
        mock_reply_msg.text = "Hello"

        mock_event = MagicMock()
        mock_event.text = "/tr Hello"
        mock_event.is_reply = True
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()
        mock_manager.reply = AsyncMock()
        mock_manager.delete_message = AsyncMock()

        with patch("handlers.commands.translate.strip_text_prefix", return_value="Hello"):
            with patch("handlers.commands.translate.ts.translate_text", return_value="你好") as mock_translate:
                with patch("handlers.commands.translate.reply_tts", AsyncMock(return_value=True)):
                    with patch("handlers.commands.translate.manager", mock_manager):
                        with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                            await translate(mock_event)

                            mock_translate.assert_called_with("Hello", to_language="zh-CN", translator="google")

    async def test_translate_exception_handling(self):
        """测试翻译异常处理"""
        from handlers.commands.translate import translate

        mock_reply_msg = MagicMock()
        mock_reply_msg.text = "Hello"

        mock_event = MagicMock()
        mock_event.text = "/tr Hello"
        mock_event.is_reply = True
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)
        mock_event.date = MagicMock()
        mock_event.date.__add__ = lambda self, other: MagicMock()

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()
        mock_manager.reply = AsyncMock()
        mock_manager.delete_message = AsyncMock()

        with patch("handlers.commands.translate.strip_text_prefix", return_value="Hello"):
            with patch("handlers.commands.translate.ts.translate_text", side_effect=Exception("Translation error")):
                with patch("handlers.commands.translate.manager", mock_manager):
                    with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                        await translate(mock_event)

                        mock_manager.logger.exception.assert_called()

    async def test_translate_with_direct_text(self):
        """测试直接翻译文本内容"""
        from handlers.commands.translate import translate

        mock_event = MagicMock()
        mock_event.text = "/tr Hello World"
        mock_event.is_reply = False
        mock_event.get_reply_message = AsyncMock(return_value=None)

        mock_user = MagicMock()
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()
        mock_manager.reply = AsyncMock()
        mock_manager.delete_message = AsyncMock()

        with patch("handlers.commands.translate.strip_text_prefix", return_value="Hello World"):
            with patch("handlers.commands.translate.ts.translate_text", return_value="你好世界"):
                with patch("handlers.commands.translate.reply_tts", AsyncMock(return_value=True)):
                    with patch("handlers.commands.translate.manager", mock_manager):
                        with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                            await translate(mock_event)
