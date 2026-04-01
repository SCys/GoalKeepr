"""
Tests for handlers/member_captcha/member_captcha.py
测试入群验证主模块
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

from handlers.member_captcha.member_captcha import member_captcha, _full_name
from handlers.member_captcha.config import VerificationMode, get_chat_type


class TestGetChatType:
    """测试 get_chat_type 函数"""

    def test_private_chat(self):
        """测试私聊"""
        chat = MagicMock()
        chat.broadcast = False
        chat.megagroup = False
        chat.title = None
        assert get_chat_type(chat) == "private"

    def test_group_chat(self):
        """测试普通群"""
        chat = MagicMock()
        chat.broadcast = False
        chat.megagroup = False
        chat.title = "Test Group"
        assert get_chat_type(chat) == "group"

    def test_supergroup(self):
        """测试超级群"""
        chat = MagicMock()
        chat.broadcast = False
        chat.megagroup = True
        assert get_chat_type(chat) == "supergroup"

    def test_channel(self):
        """测试频道"""
        chat = MagicMock()
        chat.broadcast = True
        chat.megagroup = False
        chat.title = "Test Channel"
        assert get_chat_type(chat) == "channel"


class TestFullName:
    """测试 _full_name 函数"""

    def test_with_both_names(self):
        """测试有姓有名"""
        user = MagicMock(first_name="John", last_name="Doe")
        assert _full_name(user) == "John Doe"

    def test_with_only_first_name(self):
        """测试只有名字"""
        user = MagicMock(first_name="John", last_name=None)
        assert _full_name(user) == "John"

    def test_with_only_last_name(self):
        """测试只有姓"""
        user = MagicMock(first_name=None, last_name="Doe")
        assert _full_name(user) == "Doe"

    def test_with_no_names(self):
        """测试没有名字"""
        user = MagicMock(first_name=None, last_name=None)
        assert _full_name(user) == ""


@pytest.mark.asyncio
class TestMemberCaptcha:
    """测试 member_captcha 主函数"""

    async def test_no_user_info(self, mock_manager):
        """测试没有用户信息的情况"""
        event = MagicMock()
        event.get_chat = AsyncMock(return_value=MagicMock(id=-1001))
        event.get_user = AsyncMock(return_value=None)
        event.delete = AsyncMock()

        with patch(
            "handlers.member_captcha.member_captcha.validate_basic_conditions",
            AsyncMock(return_value="no_user"),
        ):
            await member_captcha(event)

            assert event.delete.called

    async def test_validation_error(self, mock_manager, mock_chat, mock_user):
        """测试验证失败的情况"""
        event = MagicMock()
        event.chat_id = -1001085650365
        event.get_chat = AsyncMock(return_value=mock_chat)
        event.get_user = AsyncMock(return_value=mock_user)
        event.action_message = MagicMock(date=datetime.now(timezone.utc))
        event.delete = AsyncMock()

        # 设置返回验证错误
        with patch(
            "handlers.member_captcha.member_captcha.validate_basic_conditions",
            AsyncMock(return_value="validation_failed"),
        ):
            await member_captcha(event)

            assert event.delete.called

    async def test_none_verification_mode(self, mock_manager, mock_chat, mock_user):
        """测试无验证模式"""
        event = MagicMock()
        event.chat_id = -1001085650365
        event.get_chat = AsyncMock(return_value=mock_chat)
        event.get_user = AsyncMock(return_value=mock_user)
        event.action_message = MagicMock(date=datetime.now(timezone.utc))
        event.delete = AsyncMock()

        with patch(
            "handlers.member_captcha.member_captcha.validate_basic_conditions",
            AsyncMock(return_value=None),
        ):
            with patch(
                "handlers.member_captcha.member_captcha.get_verification_method",
                AsyncMock(return_value=VerificationMode.NONE),
            ):
                await member_captcha(event)

                assert event.delete.called

    async def test_restrict_permissions_failed(
        self, mock_manager, mock_chat, mock_user
    ):
        """测试限制权限失败的情况"""
        event = MagicMock()
        event.chat_id = -1001085650365
        event.get_chat = AsyncMock(return_value=mock_chat)
        event.get_user = AsyncMock(return_value=mock_user)
        event.action_message = MagicMock(date=datetime.now(timezone.utc))
        event.delete = AsyncMock()

        with patch(
            "handlers.member_captcha.member_captcha.validate_basic_conditions",
            AsyncMock(return_value=None),
        ):
            with patch(
                "handlers.member_captcha.member_captcha.get_verification_method",
                AsyncMock(return_value=VerificationMode.BAN),
            ):
                with patch(
                    "handlers.member_captcha.member_captcha.restrict_member_permissions",
                    AsyncMock(side_effect=PermissionError("test")),
                ):
                    await member_captcha(event)

                    assert event.delete.called
