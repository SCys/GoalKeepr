"""Tests for per-group settings key compatibility and verification method lookup."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import importlib

import pytest
from telethon import types

from manager.group import (
    SETTINGS_KEY_PREFIX,
    settings_chat_id_candidates,
    settings_get,
    settings_set,
)
from handlers.member_captcha.config import VerificationMode


NOW = datetime(2026, 7, 9, 10, 0, 0, tzinfo=timezone.utc)
BARE_CHANNEL_ID = 1445219041
MARKED_CHANNEL_ID = -1001445219041


def test_settings_chat_id_candidates_channel():
    bare_first = settings_chat_id_candidates(BARE_CHANNEL_ID)
    assert bare_first[0] == BARE_CHANNEL_ID
    assert MARKED_CHANNEL_ID in bare_first

    marked_first = settings_chat_id_candidates(MARKED_CHANNEL_ID)
    assert marked_first[0] == MARKED_CHANNEL_ID
    assert BARE_CHANNEL_ID in marked_first


@pytest.mark.asyncio
async def test_settings_get_reads_bare_key_via_marked_id(fake_redis):
    await fake_redis.hset(
        f"{SETTINGS_KEY_PREFIX}{BARE_CHANNEL_ID}",
        mapping={"new_member_check_method": "sleep_2weeks"},
    )

    value = await settings_get(
        fake_redis, MARKED_CHANNEL_ID, "new_member_check_method", VerificationMode.BAN
    )
    assert value == "sleep_2weeks"


@pytest.mark.asyncio
async def test_settings_get_reads_marked_key_via_bare_id(fake_redis):
    await fake_redis.hset(
        f"{SETTINGS_KEY_PREFIX}{MARKED_CHANNEL_ID}",
        mapping={"new_member_check_method": "sleep_1week"},
    )

    value = await settings_get(
        fake_redis, BARE_CHANNEL_ID, "new_member_check_method", VerificationMode.BAN
    )
    assert value == "sleep_1week"


@pytest.mark.asyncio
async def test_settings_set_migrates_and_unifies_keys(fake_redis):
    # 旧数据写在 -100 key 上
    await fake_redis.hset(
        f"{SETTINGS_KEY_PREFIX}{MARKED_CHANNEL_ID}",
        mapping={"new_member_check_method": "ban", "legacy": "1"},
    )

    await settings_set(fake_redis, BARE_CHANNEL_ID, {"new_member_check_method": "sleep_2weeks"})

    primary = await fake_redis.hgetall(f"{SETTINGS_KEY_PREFIX}{BARE_CHANNEL_ID}")
    assert primary[b"new_member_check_method"] == b"sleep_2weeks"
    assert primary[b"legacy"] == b"1"

    # 旧 key 应被清理，避免继续分叉
    assert await fake_redis.hgetall(f"{SETTINGS_KEY_PREFIX}{MARKED_CHANNEL_ID}") == {}


@pytest.mark.asyncio
async def test_get_verification_method_uses_compatible_keys(fake_redis, mock_manager):
    await fake_redis.hset(
        f"{SETTINGS_KEY_PREFIX}{BARE_CHANNEL_ID}",
        mapping={"new_member_check_method": "sleep_2weeks"},
    )
    mock_manager.get_redis = AsyncMock(return_value=fake_redis)

    validators = importlib.import_module("handlers.member_captcha.validators")
    method = await validators.get_verification_method(MARKED_CHANNEL_ID)
    assert method == "sleep_2weeks"


def _fake_chat():
    return SimpleNamespace(id=BARE_CHANNEL_ID, title="Test Group", megagroup=True, broadcast=False)


def _fake_user():
    return SimpleNamespace(id=42, username="newbie", first_name="New", last_name="User")


class FakeJoinEvent:
    chat_id = MARKED_CHANNEL_ID
    user_joined = True
    user_added = False
    date = NOW
    original_update = SimpleNamespace(pts=123)
    # 模拟成员列表隐藏：无 service message
    action_message = None

    def __init__(self, chat, user):
        self._chat = chat
        self._user = user
        self.delete = AsyncMock()

    async def get_chat(self):
        return self._chat

    async def get_user(self):
        return self._user


@pytest.mark.asyncio
async def test_sleep_2weeks_without_action_message(monkeypatch, mock_manager):
    """无 action_message 的入群事件仍应读取群设置并走静默2周。"""
    member_captcha_module = importlib.import_module("handlers.member_captcha.member_captcha")

    monkeypatch.setattr(member_captcha_module, "validate_basic_conditions", AsyncMock(return_value=None))
    monkeypatch.setattr(
        member_captcha_module.CaptchaSession,
        "check_and_record",
        AsyncMock(return_value=(True, {})),
    )
    monkeypatch.setattr(member_captcha_module, "stats_incr", AsyncMock())
    monkeypatch.setattr(member_captcha_module, "record_group", AsyncMock())
    monkeypatch.setattr(
        member_captcha_module,
        "get_verification_method",
        AsyncMock(return_value=VerificationMode.SLEEP_2WEEKS),
    )
    handle_silence = AsyncMock(return_value=True)
    restrict = AsyncMock(return_value=True)
    create_session = AsyncMock()
    monkeypatch.setattr(member_captcha_module, "handle_silence_mode", handle_silence)
    monkeypatch.setattr(member_captcha_module, "restrict_member_permissions", restrict)
    monkeypatch.setattr(member_captcha_module, "create_verification_session", create_session)

    chat = _fake_chat()
    user = _fake_user()
    await member_captcha_module.member_captcha(FakeJoinEvent(chat, user))

    handle_silence.assert_awaited_once()
    assert handle_silence.await_args.args[3] == VerificationMode.SLEEP_2WEEKS
    # 静默成功后不应进入验证码会话
    create_session.assert_not_awaited()
    # sleep 模式限制由 handle_silence_mode 内部完成，外层不先永久 restrict
    restrict.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_silence_mode_sleep_2weeks_restricts_14_days(monkeypatch, mock_manager):
    validators = importlib.import_module("handlers.member_captcha.validators")

    restrict = AsyncMock(return_value=True)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(validators, "restrict_member_permissions", restrict)
    monkeypatch.setattr(validators.manager, "send", send)

    chat = _fake_chat()
    result = await validators.handle_silence_mode(
        chat,
        42,
        "New User",
        VerificationMode.SLEEP_2WEEKS,
        "chat test",
        NOW,
    )

    assert result is True
    restrict.assert_awaited_once_with(chat, 42, timedelta(days=14))
    # 通知目标应是 chat 实体，而不是裸 int id
    assert send.await_args.args[0] is chat
