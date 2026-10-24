"""/captcha_stats 命令回归测试：负数群 ID 解析 + 权限控制。"""

import importlib
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

# handlers/commands/__init__.py 里 from .captcha_stats import captcha_stats 把子模块属性
# 遮蔽成了函数，import ... as 会拿到函数而非模块，必须用 importlib 取真模块
cs_mod = importlib.import_module("handlers.commands.captcha_stats")
from handlers.member_captcha.stats import stats_incr, FIELD_GROUP_JOINS, FIELD_SUCCESS


def _make_event(text, chat_id=-100999, sender_id=42, is_group=True, reply=None):
    return NS(
        raw_text=text,
        chat_id=chat_id,
        is_group=is_group,
        is_channel=False,
        get_sender=AsyncMock(return_value=NS(id=sender_id)),
        reply=reply or AsyncMock(),
    )


@pytest.fixture
def admin_config(mock_manager):
    mock_manager.config["telegram"]["admin"] = "777"
    mock_manager.is_admin = AsyncMock(return_value=False)
    mock_manager.reply = AsyncMock()
    return mock_manager


class TestPermission:
    async def test_global_admin_queries_global(self, admin_config, fake_redis):
        event = _make_event("/captcha_stats", sender_id=777)
        await cs_mod.captcha_stats(event)
        event.reply.assert_called_once()
        assert "全局统计" in event.reply.call_args[0][0]

    async def test_global_admin_queries_any_group(self, admin_config, fake_redis):
        """负数群 ID 必须可用（回归：旧正则只匹配正数）。"""
        event = _make_event("/captcha_stats -100123456", sender_id=777)
        await cs_mod.captcha_stats(event)
        event.reply.assert_called_once()
        assert "群 ID: -100123456" in event.reply.call_args[0][0]

    async def test_global_admin_queries_with_bot_mention(self, admin_config, fake_redis):
        """支持带有 @bot_username 的命令形式。"""
        event = _make_event("/captcha_stats@my_bot -100123456", sender_id=777)
        await cs_mod.captcha_stats(event)
        event.reply.assert_called_once()
        assert "群 ID: -100123456" in event.reply.call_args[0][0]

    async def test_group_admin_defaults_to_own_group(self, admin_config, fake_redis):
        """群管理员在群内不带参数 → 默认查本群（不再是全局）。"""
        admin_config.is_admin = AsyncMock(return_value=True)
        event = _make_event("/captcha_stats", chat_id=-100999, sender_id=42)
        await cs_mod.captcha_stats(event)
        event.reply.assert_called_once()
        assert "群 ID: -100999" in event.reply.call_args[0][0]

    async def test_group_admin_querying_other_group_denied(self, admin_config, fake_redis):
        admin_config.is_admin = AsyncMock(return_value=True)
        event = _make_event("/captcha_stats -100123456", chat_id=-100999, sender_id=42)
        await cs_mod.captcha_stats(event)
        event.reply.assert_not_called()
        admin_config.reply.assert_called_once()
        assert "本群" in admin_config.reply.call_args[0][1]

    async def test_regular_member_denied(self, admin_config, fake_redis):
        admin_config.is_admin = AsyncMock(return_value=False)
        event = _make_event("/captcha_stats", sender_id=42)
        await cs_mod.captcha_stats(event)
        event.reply.assert_not_called()
        admin_config.reply.assert_called_once()
        assert "管理员" in admin_config.reply.call_args[0][1]

    async def test_private_non_admin_denied(self, admin_config, fake_redis):
        event = _make_event("/captcha_stats", chat_id=42, sender_id=42, is_group=False)
        await cs_mod.captcha_stats(event)
        event.reply.assert_not_called()
        admin_config.reply.assert_called_once()


class TestStatsOutput:
    async def test_output_reflects_counters(self, admin_config, fake_redis):
        await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100999, user_id=1)
        await stats_incr(fake_redis, FIELD_SUCCESS, chat_id=-100999, user_id=1)

        event = _make_event("/captcha_stats -100999", sender_id=777)
        await cs_mod.captcha_stats(event)

        text = event.reply.call_args[0][0]
        assert "群 ID: -100999" in text
        assert "入群人次: 1" in text
        assert "验证成功: 1" in text
        assert "唯一用户: 1" in text
        assert "成功率: 100.0%" in text
