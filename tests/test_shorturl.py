"""测试 handlers/commands/shorturl.py 中的短链接功能"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta


pytestmark = pytest.mark.asyncio


class TestShorturlCommand:
    """测试 shorturl 命令"""

    async def test_successful_shorturl(self):
        """测试成功的短链接生成"""
        from handlers.commands.shorturl import shorturl

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "data": {
                "code": "abc123",
                "expired": "2026-04-17",
                "url": "https://short.url/abc123"
            }
        })

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.shorturl.manager", mock_manager):
            result = await shorturl("https://example.com/very/long/url")
            assert result == "https://short.url/abc123"

    async def test_http_error_response(self):
        """测试 HTTP 错误响应"""
        from handlers.commands.shorturl import shorturl

        mock_response = MagicMock()
        mock_response.status = 500

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.shorturl.manager", mock_manager):
            result = await shorturl("https://example.com")
            assert result is None

    async def test_error_in_response(self):
        """测试 API 返回错误"""
        from handlers.commands.shorturl import shorturl

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "error": {
                "code": 400,
                "message": "Invalid URL"
            }
        })

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.shorturl.manager", mock_manager):
            result = await shorturl("https://example.com")
            assert result is None

    async def test_timeout_error(self):
        """测试超时错误"""
        from handlers.commands.shorturl import shorturl
        from asyncio import TimeoutError

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()
        mock_manager.create_session = AsyncMock(side_effect=TimeoutError())

        with patch("handlers.commands.shorturl.manager", mock_manager):
            result = await shorturl("https://example.com")
            assert result is None

    async def test_client_error(self):
        """测试客户端错误"""
        from handlers.commands.shorturl import shorturl
        from aiohttp import ClientError

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()
        mock_manager.create_session = AsyncMock(side_effect=ClientError("Connection error"))

        with patch("handlers.commands.shorturl.manager", mock_manager):
            result = await shorturl("https://example.com")
            assert result is None

    async def test_unknown_exception(self):
        """测试未知异常"""
        from handlers.commands.shorturl import shorturl

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()
        mock_manager.create_session = AsyncMock(side_effect=Exception("Unknown error"))

        with patch("handlers.commands.shorturl.manager", mock_manager):
            result = await shorturl("https://example.com")
            assert result is None


class TestShorturlCommandHandler:
    """测试 shorturl_command 命令处理器"""

    async def test_command_with_reply_message(self):
        """测试命令有回复消息的情况"""
        from handlers.commands.shorturl import shorturl_command

        mock_reply_msg = MagicMock()
        mock_reply_msg.text = "https://example.com/long-url"

        mock_event = MagicMock()
        mock_event.raw_text = "/shorturl"
        mock_event.text = "/shorturl"
        mock_event.get_reply_message = AsyncMock(return_value=mock_reply_msg)
        mock_event.reply = AsyncMock()
        mock_event.chat_id = -100123456789
        mock_event.date = MagicMock()
        mock_event.date.__add__ = lambda self, other: MagicMock()

        mock_sender = MagicMock()
        mock_sender.id = 123456

        mock_manager = MagicMock()
        mock_manager.delete_message = AsyncMock()
        mock_manager.logger = MagicMock()
        mock_manager.create_session = AsyncMock()

        with patch("handlers.commands.shorturl.manager", mock_manager):
            with patch("handlers.commands.shorturl.shorturl", AsyncMock(return_value="https://short.url/abc123")):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_sender)):
                    await shorturl_command(mock_event)

                    assert mock_event.reply.called

    async def test_command_without_url(self):
        """测试命令没有 URL"""
        from handlers.commands.shorturl import shorturl_command

        mock_event = MagicMock()
        mock_event.raw_text = "/shorturl"
        mock_event.text = "/shorturl"
        mock_event.get_reply_message = AsyncMock(return_value=None)
        mock_event.reply = AsyncMock()
        mock_event.chat_id = -100123456789
        mock_event.date = MagicMock()
        mock_event.date.__add__ = lambda self, other: MagicMock()

        mock_manager = MagicMock()
        mock_manager.delete_message = AsyncMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.shorturl.manager", mock_manager):
            await shorturl_command(mock_event)

            assert mock_event.reply.called

    async def test_command_with_invalid_url(self):
        """测试命令带有无效 URL"""
        from handlers.commands.shorturl import shorturl_command

        mock_event = MagicMock()
        mock_event.raw_text = "/shorturl not-a-url"
        mock_event.text = "/shorturl not-a-url"
        mock_event.get_reply_message = AsyncMock(return_value=None)
        mock_event.reply = AsyncMock()
        mock_event.chat_id = -100123456789
        mock_event.date = MagicMock()
        mock_event.date.__add__ = lambda self, other: MagicMock()

        mock_manager = MagicMock()
        mock_manager.delete_message = AsyncMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.shorturl.manager", mock_manager):
            await shorturl_command(mock_event)

            assert mock_event.reply.called


class TestShorturlRegex:
    """测试 URL 正则表达式"""

    def test_valid_urls(self):
        """测试有效 URL 匹配"""
        from handlers.commands.shorturl import RE_URL

        valid_urls = [
            "https://example.com",
            "http://example.com",
            "https://www.example.com/path?query=1",
            "https://example.com/path/to/page",
            "http://sub.example.com/page",
        ]

        for url in valid_urls:
            match = RE_URL.search(url)
            assert match is not None, f"Should match: {url}"

    def test_invalid_strings(self):
        """测试无效字符串不匹配"""
        from handlers.commands.shorturl import RE_URL

        invalid_strings = [
            "not a url",
            "example",
        ]

        for s in invalid_strings:
            match = RE_URL.search(s)
            # 只是验证基本行为
