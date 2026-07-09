from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import importlib

from telethon import types

from handlers.member_captcha.config import VerificationMode


NOW = datetime(2026, 7, 9, 10, 0, 0, tzinfo=timezone.utc)


def _fake_chat():
    return SimpleNamespace(id=-100123, title="Test Group", megagroup=True, broadcast=False)


def _fake_user():
    return SimpleNamespace(id=42, username="newbie", first_name="New", last_name="User")


class FakeJoinEvent:
    chat_id = -100123
    user_joined = True
    user_added = False
    original_update = SimpleNamespace(pts=123)
    action_message = SimpleNamespace(
        id=99,
        action=types.MessageActionChatAddUser(users=[42]),
        date=NOW,
    )

    def __init__(self, chat, user):
        self._chat = chat
        self._user = user
        self.delete = AsyncMock()

    async def get_chat(self):
        return self._chat

    async def get_user(self):
        return self._user


async def test_silence_mode_stops_when_permission_restriction_fails(monkeypatch, mock_manager):
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
        AsyncMock(return_value=VerificationMode.SILENCE),
    )
    restrict = AsyncMock(return_value=False)
    handle_silence = AsyncMock()
    monkeypatch.setattr(member_captcha_module, "restrict_member_permissions", restrict)
    monkeypatch.setattr(member_captcha_module, "handle_silence_mode", handle_silence)

    chat = _fake_chat()
    user = _fake_user()
    await member_captcha_module.member_captcha(FakeJoinEvent(chat, user))

    restrict.assert_awaited_once_with(chat, user)
    handle_silence.assert_not_awaited()


async def test_custom_sleep_mode_restricts_for_configured_days(monkeypatch, mock_manager):
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
        "sleep_custom:10",
        "chat -100123 member 42",
        NOW,
    )

    assert result is True
    restrict.assert_awaited_once_with(chat, 42, timedelta(days=10))
    send.assert_awaited_once()
