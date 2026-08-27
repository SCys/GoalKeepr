"""Tests for first message safety check, 5-minute lurk timeout, and group setting toggles."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from handlers.default import default_handler, _is_fast_safe_greeting
from handlers.member_captcha.events import first_msg_timeout
from handlers.commands.group_setting import group_setting_callback
from manager.group import settings_set, settings_get

CHAT_ID = -100123456
USER_ID = 888999
NOW = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)

def _make_msg(text="Hello", chat_id=CHAT_ID, sender_id=USER_ID):
    chat = SimpleNamespace(id=chat_id, title="Test Group", megagroup=True)
    sender = SimpleNamespace(id=sender_id, first_name="Test", last_name="User", username="testuser")
    msg = SimpleNamespace(
        id=1001,
        text=text,
        chat_id=chat_id,
        delete=AsyncMock(),
        get_chat=AsyncMock(return_value=chat),
        get_sender=AsyncMock(return_value=sender),
    )
    return msg

@pytest.mark.asyncio
async def test_fast_safe_greetings():
    assert _is_fast_safe_greeting("大家好") is True
    assert _is_fast_safe_greeting("Hello all") is True
    assert _is_fast_safe_greeting("新人报道") is True
    assert _is_fast_safe_greeting("代开发票 微信:12345") is False

@pytest.mark.asyncio
async def test_first_message_clean_greeting_clears_watch(mock_manager, fake_redis):
    # Set watch key in Redis
    await fake_redis.set(f"first_msg_watch:{CHAT_ID}:{USER_ID}", "1")
    await settings_set(fake_redis, CHAT_ID, {"first_msg_check": "on"})

    msg = _make_msg(text="大家好！")
    await default_handler(msg)

    # Watch key should be popped/deleted
    assert await fake_redis.get(f"first_msg_watch:{CHAT_ID}:{USER_ID}") is None
    # Timeout task should be deleted
    mock_manager.lazy_session_delete.assert_awaited_with(CHAT_ID, USER_ID, "first_msg_timeout")
    # Message should not be deleted
    msg.delete.assert_not_awaited()

@pytest.mark.asyncio
async def test_first_message_advertising_kicks(mock_manager, fake_redis, mock_advertising_config):
    await fake_redis.set(f"first_msg_watch:{CHAT_ID}:{USER_ID}", "1")
    await settings_set(fake_redis, CHAT_ID, {"first_msg_check": "on"})

    msg = _make_msg(text="兼职刷单 广告推广")
    await default_handler(msg)

    # Message should be deleted
    msg.delete.assert_awaited()
    # User should be banned 60s
    mock_manager.hide_member.assert_awaited()
    # Notice should be sent
    mock_manager.send.assert_awaited()

@pytest.mark.asyncio
async def test_lurk_timeout_kicks_inactive_user(mock_manager, fake_redis):
    # User watched and lurk check is on
    await fake_redis.set(f"first_msg_watch:{CHAT_ID}:{USER_ID}", "1")
    await settings_set(fake_redis, CHAT_ID, {"lurk_check_5min": "on"})

    mock_manager.client.get_permissions = AsyncMock(
        return_value=SimpleNamespace(is_admin=False, is_creator=False, has_left=False)
    )

    with patch("handlers.member_captcha.events.resolve_chat_entity", new=AsyncMock(return_value=SimpleNamespace(id=CHAT_ID))):
        await first_msg_timeout(mock_manager.client, CHAT_ID, 0, USER_ID)

    mock_manager.hide_member.assert_awaited()
    # Watch key deleted
    assert await fake_redis.get(f"first_msg_watch:{CHAT_ID}:{USER_ID}") is None

@pytest.mark.asyncio
async def test_lurk_timeout_skips_when_off(mock_manager, fake_redis):
    await fake_redis.set(f"first_msg_watch:{CHAT_ID}:{USER_ID}", "1")
    await settings_set(fake_redis, CHAT_ID, {"lurk_check_5min": "off"})

    with patch("handlers.member_captcha.events.resolve_chat_entity", new=AsyncMock(return_value=SimpleNamespace(id=CHAT_ID))):
        await first_msg_timeout(mock_manager.client, CHAT_ID, 0, USER_ID)

    mock_manager.kick_member.assert_not_awaited()

@pytest.mark.asyncio
async def test_group_setting_toggle_callbacks(mock_manager, fake_redis):
    chat = SimpleNamespace(id=CHAT_ID, title="Test Group", megagroup=True)
    admin = SimpleNamespace(id=USER_ID, first_name="Admin")
    mock_manager.is_admin = AsyncMock(return_value=True)

    # Toggle first_msg_check
    event1 = SimpleNamespace(
        data=b"su:tg:first_msg_check",
        get_message=AsyncMock(return_value=SimpleNamespace(id=999)),
        get_chat=AsyncMock(return_value=chat),
        get_sender=AsyncMock(return_value=admin),
        answer=AsyncMock(),
    )
    await group_setting_callback(event1)
    val = await settings_get(fake_redis, CHAT_ID, "first_msg_check")
    assert val == "on"

    # Toggle lurk_check_5min
    event2 = SimpleNamespace(
        data=b"su:tg:lurk_check_5min",
        get_message=AsyncMock(return_value=SimpleNamespace(id=999)),
        get_chat=AsyncMock(return_value=chat),
        get_sender=AsyncMock(return_value=admin),
        answer=AsyncMock(),
    )
    await group_setting_callback(event2)
    val2 = await settings_get(fake_redis, CHAT_ID, "lurk_check_5min")
    assert val2 == "on"
