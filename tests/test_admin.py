"""Tests for manager.is_admin and system commands."""
from __future__ import annotations
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest

@pytest.mark.asyncio
async def test_is_admin_perms_none_returns_false():
    """When get_permissions returns None, is_admin must return False (P1.2 fix)."""
    from manager.manager import Manager
    mgr = Manager()
    mgr.client = SimpleNamespace(get_permissions=AsyncMock(return_value=None))
    assert await mgr.is_admin(-100123, 456) is False

@pytest.mark.asyncio
async def test_is_admin_admin_or_creator():
    from manager.manager import Manager
    mgr = Manager()
    # is_admin True
    mgr.client = SimpleNamespace(get_permissions=AsyncMock(return_value=SimpleNamespace(is_admin=True, is_creator=False)))
    assert await mgr.is_admin(-100123, 456) is True

    # is_creator True
    mgr.client = SimpleNamespace(get_permissions=AsyncMock(return_value=SimpleNamespace(is_admin=False, is_creator=True)))
    assert await mgr.is_admin(-100123, 456) is True

    # regular member
    mgr.client = SimpleNamespace(get_permissions=AsyncMock(return_value=SimpleNamespace(is_admin=False, is_creator=False)))
    assert await mgr.is_admin(-100123, 456) is False

def test_system_command_patterns():
    """Verify /system_usage and /system_groups match with or without @botusername (P2.6 fix)."""
    usage_pat = re.compile(r"(?i)^/system_usage(?:@[a-zA-Z0-9_]+)?$")
    assert usage_pat.match("/system_usage")
    assert usage_pat.match("/SYSTEM_USAGE")
    assert usage_pat.match("/system_usage@my_bot")
    assert usage_pat.match("/system_usage@bot_123")
    assert not usage_pat.match("/system_usage extra")
    assert not usage_pat.match("/other")

    groups_pat = re.compile(r"(?i)^/system_groups(?:@[a-zA-Z0-9_]+)?$")
    assert groups_pat.match("/system_groups")
    assert groups_pat.match("/SYSTEM_GROUPS")
    assert groups_pat.match("/system_groups@my_bot")
    assert not groups_pat.match("/system_groups extra")
    assert not groups_pat.match("/other")


@pytest.mark.asyncio
async def test_lazy_session_delete_clears_sqlite_even_with_redis():
    """Verify lazy_session_delete deletes from SQLite fallback even when Redis is present (P3.9 fix)."""
    from manager.manager import Manager

    async def fake_zscan(key, match=None):
        if False:
            yield None

    mgr = Manager()
    fake_rdb = AsyncMock()
    fake_rdb.zscan_iter = fake_zscan
    mgr.get_redis = AsyncMock(return_value=fake_rdb)

    with patch("manager.manager.database.execute", new=AsyncMock()) as mock_db_exec:
        await mgr.lazy_session_delete(-100123, 456, "captcha_timeout")
        mock_db_exec.assert_awaited_once_with(
            "delete from lazy_sessions where chat=? and member=? and type=?",
            (-100123, 456, "captcha_timeout"),
        )
