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
        self.user_left = False
        self.user_kicked = False
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


async def test_advertising_member_is_banned_without_captcha(monkeypatch, mock_manager):
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
        AsyncMock(return_value=VerificationMode.BAN),
    )
    monkeypatch.setattr(member_captcha_module, "restrict_member_permissions", AsyncMock(return_value=True))
    mark_restricted = AsyncMock()
    monkeypatch.setattr(member_captcha_module.CaptchaSession, "mark_restricted", mark_restricted)
    clear_restricted = AsyncMock()
    monkeypatch.setattr(member_captcha_module.CaptchaSession, "clear_restricted", clear_restricted)
    monkeypatch.setattr(member_captcha_module, "create_verification_session", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(member_captcha_module.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(
        member_captcha_module.manager,
        "chat_member_permissions",
        AsyncMock(return_value=SimpleNamespace(has_left=False)),
    )
    monkeypatch.setattr(member_captcha_module, "get_member_info_for_check", AsyncMock(return_value=[]))
    monkeypatch.setattr(member_captcha_module, "perform_security_checks", AsyncMock(return_value="advertising"))
    flag = AsyncMock()
    monkeypatch.setattr(member_captcha_module.CaptchaSession, "flag", flag)
    cancel_jobs = AsyncMock()
    monkeypatch.setattr(member_captcha_module, "cancel_pending_member_jobs", cancel_jobs)
    build_message = AsyncMock()
    monkeypatch.setattr(member_captcha_module, "build_captcha_message", build_message)

    chat = _fake_chat()
    user = _fake_user()
    await member_captcha_module.member_captcha(FakeJoinEvent(chat, user))

    flag.assert_awaited_once_with(chat.id, user.id, "advertising")
    mark_restricted.assert_awaited_once_with(chat.id, user.id)
    clear_restricted.assert_awaited_once_with(chat.id, user.id)
    cancel_jobs.assert_awaited_once_with(chat.id, user.id, delete_captcha_session=False)
    mock_manager.client.edit_permissions.assert_awaited_once_with(
        chat,
        user.id,
        view_messages=False,
        until_date=timedelta(days=30),
    )
    member_captcha_module.stats_incr.assert_any_await(
        mock_manager.get_redis.return_value,
        "failed",
        chat.id,
        user.id,
    )
    build_message.assert_not_awaited()
    mock_manager.client.send_message.assert_not_awaited()


async def test_ban_mode_marks_captcha_restriction(monkeypatch, mock_manager):
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
        AsyncMock(return_value=VerificationMode.BAN),
    )
    monkeypatch.setattr(member_captcha_module, "restrict_member_permissions", AsyncMock(return_value=True))
    mark_restricted = AsyncMock()
    monkeypatch.setattr(member_captcha_module.CaptchaSession, "mark_restricted", mark_restricted)
    monkeypatch.setattr(member_captcha_module, "create_verification_session", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(member_captcha_module.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(
        member_captcha_module.manager,
        "chat_member_permissions",
        AsyncMock(return_value=SimpleNamespace(has_left=False)),
    )
    monkeypatch.setattr(member_captcha_module, "get_member_info_for_check", AsyncMock(return_value=[]))
    monkeypatch.setattr(member_captcha_module, "perform_security_checks", AsyncMock(return_value=None))
    monkeypatch.setattr(
        member_captcha_module,
        "build_captcha_message",
        AsyncMock(return_value=("captcha", [], {"icon": "x", "answer": "x", "options": "[]", "callback_map": {}})),
    )
    monkeypatch.setattr(member_captcha_module.CaptchaSession, "record_answer", AsyncMock())
    monkeypatch.setattr(member_captcha_module, "store_callback_map", AsyncMock())
    monkeypatch.setattr(member_captcha_module.manager, "delete_message", AsyncMock())
    mock_manager.client.send_message = AsyncMock(return_value=SimpleNamespace(id=100))

    chat = _fake_chat()
    user = _fake_user()
    await member_captcha_module.member_captcha(FakeJoinEvent(chat, user))

    mark_restricted.assert_awaited_once_with(chat.id, user.id)


async def test_kicked_or_left_event_ignored(monkeypatch, mock_manager):
    """踢人或离开事件不得触发入群验证逻辑。"""
    member_captcha_module = importlib.import_module("handlers.member_captcha.member_captcha")

    mock_validate = AsyncMock()
    monkeypatch.setattr(member_captcha_module, "validate_basic_conditions", mock_validate)

    chat = _fake_chat()
    user = _fake_user()
    event = FakeJoinEvent(chat, user)
    event.user_kicked = True
    event.user_joined = False

    await member_captcha_module.member_captcha(event)
    mock_validate.assert_not_awaited()


async def test_update_channel_participant_banned_ignored(monkeypatch, mock_manager):
    """UpdateChannelParticipant 带有 Banned / Left 状态时应直接忽略。"""
    member_captcha_module = importlib.import_module("handlers.member_captcha.member_captcha")

    mock_validate = AsyncMock()
    monkeypatch.setattr(member_captcha_module, "validate_basic_conditions", mock_validate)

    chat = _fake_chat()
    user = _fake_user()
    event = FakeJoinEvent(chat, user)
    event.action_message = None
    event.user_joined = False
    event.user_added = True
    event.original_update = types.UpdateChannelParticipant(
        channel_id=123,
        date=NOW,
        actor_id=1,
        user_id=42,
        qts=1,
        new_participant=types.ChannelParticipantBanned(
            peer=types.PeerUser(user_id=42),
            kicked_by=1,
            date=NOW,
            banned_rights=types.ChatBannedRights(until_date=None, view_messages=True),
        ),
    )

    await member_captcha_module.member_captcha(event)
    mock_validate.assert_not_awaited()

