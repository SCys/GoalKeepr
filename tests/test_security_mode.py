"""
Tests for handlers/member_captcha/security_mode.py
测试安全模式功能
"""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
class TestSecurityMode:
    """测试安全模式功能"""

    async def test_should_enter_security_mode(self, mock_redis):
        """测试是否应该进入安全模式"""
        from handlers.member_captcha.security_mode import should_enter_security_mode

        # 模拟 zcount 返回值。默认阈值 5，6 >= 5 所以返回 True
        mock_redis.zcount = AsyncMock(return_value=6)

        # Patch _get_threshold_and_window 以返回固定阈值和窗口，避免依赖群设置
        with patch(
            "handlers.member_captcha.security_mode._get_threshold_and_window",
            AsyncMock(return_value=(5, 300)),
        ):
            result = await should_enter_security_mode(mock_redis, -1001085650365)
        assert result is True

    async def test_should_not_enter_security_mode(self, mock_redis):
        """测试不应该进入安全模式"""
        from handlers.member_captcha.security_mode import should_enter_security_mode

        # 模拟 zcount 返回值为 3，小于默认阈值 5，返回 False
        mock_redis.zcount = AsyncMock(return_value=3)

        with patch(
            "handlers.member_captcha.security_mode._get_threshold_and_window",
            AsyncMock(return_value=(5, 300)),
        ):
            result = await should_enter_security_mode(mock_redis, -1001085650365)
        assert result is False

    async def test_is_security_mode_true(self, mock_redis):
        """测试安全模式已开启"""
        from handlers.member_captcha.security_mode import is_security_mode

        mock_redis.get = AsyncMock(return_value=b"1")

        result = await is_security_mode(mock_redis, -1001085650365)
        assert result is True

    async def test_is_security_mode_false(self, mock_redis):
        """测试安全模式未开启"""
        from handlers.member_captcha.security_mode import is_security_mode

        mock_redis.get = AsyncMock(return_value=None)

        result = await is_security_mode(mock_redis, -1001085650365)
        assert result is False

    async def test_set_security_mode(self, mock_redis):
        """测试设置安全模式"""
        from handlers.member_captcha.security_mode import set_security_mode

        await set_security_mode(mock_redis, -1001085650365)

        assert mock_redis.set.called

    async def test_clear_security_mode(self, mock_redis):
        """测试清除安全模式"""
        from handlers.member_captcha.security_mode import clear_security_mode

        await clear_security_mode(mock_redis, -1001085650365)

        assert mock_redis.delete.called

    async def test_incr_join_counter(self, mock_redis):
        """测试增加入群计数"""
        from handlers.member_captcha.security_mode import incr_join_counter

        await incr_join_counter(mock_redis, -1001085650365, 123456789)

        assert mock_redis.zadd.called
        assert mock_redis.zremrangebyscore.called
        assert mock_redis.expire.called
        # incr_join_counter 使用 zcount 获取各窗口计数
        assert mock_redis.zcount.called
