"""测试 handlers/commands/sdxl.py 中的 SDXL 图像生成命令"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta


pytestmark = pytest.mark.asyncio


class TestSDXLCommand:
    """测试 sdxl 命令"""

    async def test_successful_image_generation(self):
        """测试成功的图像生成"""
        from handlers.commands.sdxl import sdxl

        # 模拟事件
        mock_event = MagicMock()
        mock_event.text = "/sdxl a cat"
        mock_event.id = 123
        mock_event.reply = AsyncMock()
        mock_event.chat_id = -100123456789

        # 模拟聊天
        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Test Group"

        # 模拟用户 (在允许的用户列表中)
        mock_user = MagicMock()
        mock_user.id = 123456
        mock_user.first_name = "Test"
        mock_user.last_name = None

        # 模拟 manager 和配置
        mock_manager = MagicMock()
        mock_manager.config = {
            "image": {
                "users": "123456,789012",
                "groups": "-1001000000000",
            }
        }
        mock_manager.logger = MagicMock()
        mock_manager.delete_message = AsyncMock()
        mock_manager.client = MagicMock()
        mock_manager.client.send_file = AsyncMock()

        # 模拟会话和响应
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.content_type = "image/png"
        mock_response.read = AsyncMock(return_value=b"fake_image_data")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("handlers.commands.sdxl.manager", mock_manager):
            with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                    await sdxl(mock_event)

                    # 验证调用了 send_file
                    assert mock_manager.client.send_file.called

    async def test_unauthorized_user(self):
        """测试未授权用户"""
        from handlers.commands.sdxl import sdxl

        mock_event = MagicMock()
        mock_event.text = "/sdxl test"
        mock_event.id = 123
        mock_event.reply = AsyncMock()
        mock_event.chat_id = -100123456789
        mock_event.date = MagicMock()
        mock_event.date.__add__ = lambda self, other: MagicMock()

        mock_chat = MagicMock()
        mock_chat.id = -100123456789

        # 用户不在允许列表中
        mock_user = MagicMock()
        mock_user.id = 999999
        mock_user.first_name = "Unauthorized"

        mock_manager = MagicMock()
        mock_manager.config = {
            "image": {
                "users": "123456",
                "groups": "-1001000000000",
            }
        }
        mock_manager.logger = MagicMock()
        mock_manager.delete_message = AsyncMock()

        with patch("handlers.commands.sdxl.manager", mock_manager):
            with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                    await sdxl(mock_event)

                    # 验证回复了无权限消息
                    assert mock_event.reply.called

    async def test_missing_user(self):
        """测试缺少用户"""
        from handlers.commands.sdxl import sdxl

        mock_event = MagicMock()
        mock_event.text = "/sdxl test"
        mock_event.id = 123

        mock_manager = MagicMock()
        mock_manager.config = {"image": {"users": "123456", "groups": "-1001000000000"}}
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.sdxl.manager", mock_manager):
            with patch.object(mock_event, "get_sender", AsyncMock(return_value=None)):
                await sdxl(mock_event)

                # 验证记录了警告
                mock_manager.logger.warning.assert_called()

    async def test_invalid_config(self):
        """测试无效配置"""
        from handlers.commands.sdxl import sdxl

        mock_event = MagicMock()
        mock_event.text = "/sdxl test"
        mock_event.id = 123

        mock_manager = MagicMock()
        mock_manager.config = {"image": {}}  # 缺少 users 和 groups
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.sdxl.manager", mock_manager):
            await sdxl(mock_event)

            # 配置无效，应该返回
            pass

    async def test_http_error_response(self):
        """测试 HTTP 错误响应"""
        from handlers.commands.sdxl import sdxl

        mock_event = MagicMock()
        mock_event.text = "/sdxl test"
        mock_event.id = 123
        mock_event.reply = AsyncMock()

        mock_chat = MagicMock()
        mock_chat.id = -100123456789

        mock_user = MagicMock()
        mock_user.id = 123456
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.config = {"image": {"users": "123456", "groups": ""}}
        mock_manager.logger = MagicMock()

        # 模拟 HTTP 错误
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("handlers.commands.sdxl.manager", mock_manager):
            with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                    await sdxl(mock_event)

                    # 验证回复了错误消息
                    assert mock_event.reply.called
                    assert "500" in str(mock_event.reply.call_args)

    async def test_json_error_response(self):
        """测试 JSON 错误响应"""
        from handlers.commands.sdxl import sdxl

        mock_event = MagicMock()
        mock_event.text = "/sdxl test"
        mock_event.id = 123
        mock_event.reply = AsyncMock()

        mock_chat = MagicMock()
        mock_chat.id = -100123456789

        mock_user = MagicMock()
        mock_user.id = 123456
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.config = {"image": {"users": "123456", "groups": ""}}
        mock_manager.logger = MagicMock()

        # 模拟 JSON 错误响应
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.content_type = "application/json"
        mock_response.json = AsyncMock(return_value={
            "error": {
                "code": 400,
                "message": "Bad request"
            }
        })

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("handlers.commands.sdxl.manager", mock_manager):
            with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                    await sdxl(mock_event)

                    # 验证回复了错误消息
                    assert mock_event.reply.called
                    assert "400" in str(mock_event.reply.call_args)

    async def test_invalid_json_response(self):
        """测试无效 JSON 响应"""
        from handlers.commands.sdxl import sdxl

        mock_event = MagicMock()
        mock_event.text = "/sdxl test"
        mock_event.id = 123
        mock_event.reply = AsyncMock()

        mock_chat = MagicMock()
        mock_chat.id = -100123456789

        mock_user = MagicMock()
        mock_user.id = 123456
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.config = {"image": {"users": "123456", "groups": ""}}
        mock_manager.logger = MagicMock()

        # 模拟无效 JSON
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.content_type = "application/json"
        mock_response.json = AsyncMock(side_effect=Exception("Invalid JSON"))

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("handlers.commands.sdxl.manager", mock_manager):
            with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                    await sdxl(mock_event)

                    # 验证回复了错误消息
                    assert mock_event.reply.called

    async def test_send_file_exception(self):
        """测试发送文件异常"""
        from handlers.commands.sdxl import sdxl

        mock_event = MagicMock()
        mock_event.text = "/sdxl test"
        mock_event.id = 123
        mock_event.reply = AsyncMock()

        mock_chat = MagicMock()
        mock_chat.id = -100123456789

        mock_user = MagicMock()
        mock_user.id = 123456
        mock_user.first_name = "Test"

        mock_manager = MagicMock()
        mock_manager.config = {"image": {"users": "123456", "groups": ""}}
        mock_manager.logger = MagicMock()
        mock_manager.client = MagicMock()
        mock_manager.client.send_file = AsyncMock(side_effect=Exception("Send error"))

        # 模拟成功响应
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.content_type = "image/png"
        mock_response.read = AsyncMock(return_value=b"image_data")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("handlers.commands.sdxl.manager", mock_manager):
            with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                    await sdxl(mock_event)

                    # 验证回复了错误消息
                    assert mock_event.reply.called

    async def test_logs_user_info(self):
        """测试记录用户信息日志"""
        from handlers.commands.sdxl import sdxl

        mock_event = MagicMock()
        mock_event.text = "/sdxl test"
        mock_event.id = 123
        mock_event.reply = AsyncMock()

        mock_chat = MagicMock()
        mock_chat.id = -100123456789
        mock_chat.title = "Test Group"

        mock_user = MagicMock()
        mock_user.id = 123456
        mock_user.first_name = "Test"
        mock_user.last_name = "User"

        mock_manager = MagicMock()
        mock_manager.config = {"image": {"users": "123456", "groups": ""}}
        mock_manager.logger = MagicMock()
        mock_manager.delete_message = AsyncMock()
        mock_manager.client = MagicMock()
        mock_manager.client.send_file = AsyncMock()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.content_type = "image/png"
        mock_response.read = AsyncMock(return_value=b"image_data")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("handlers.commands.sdxl.manager", mock_manager):
            with patch.object(mock_event, "get_chat", AsyncMock(return_value=mock_chat)):
                with patch.object(mock_event, "get_sender", AsyncMock(return_value=mock_user)):
                    await sdxl(mock_event)

                    # 验证记录了用户信息
                    assert mock_manager.logger.info.called
                    call_args = mock_manager.logger.info.call_args[0][0]
                    assert "Test User" in call_args
