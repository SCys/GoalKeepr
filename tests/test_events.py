"""Tests for lazy captcha timeout / unban event handlers."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

def _restricted_perms():
    """Captcha restriction as reported by Telegram in BAN mode."""
    rights = SimpleNamespace(view_messages=False, send_messages=True)
    participant = SimpleNamespace(banned_rights=rights)
    return SimpleNamespace(
        participant=participant,
        is_admin=False,
        is_creator=False,
        is_banned=True,
        has_left=False,
        send_messages=False,
        view_messages=True,
    )

def _banned_perms():
    """Already banned by /sb or admin reject."""
    rights = SimpleNamespace(view_messages=True, send_messages=True)
    participant = SimpleNamespace(banned_rights=rights)
    return SimpleNamespace(
        participant=participant,
        is_admin=False,
        is_creator=False,
        is_banned=True,
        has_left=False,
        send_messages=False,
        view_messages=False,
    )

@pytest.mark.asyncio
async def test_advertising_timeout_does_not_schedule_unban(monkeypatch, mock_manager):
    # register_event 存的是原始协程函数；装饰器返回值不会正确 await 内部 coroutine
    import handlers.member_captcha.events  # noqa: F401 — 注册事件
    new_member_check = mock_manager.events["new_member_check"]

    chat = SimpleNamespace(id=-1001445219041, title="g")
    mock_manager.client.get_entity = AsyncMock(return_value=chat)
    mock_manager.client.get_permissions = AsyncMock(return_value=_restricted_perms())
    mock_manager.client.edit_permissions = AsyncMock()
    mock_manager.lazy_session = AsyncMock()
    mock_manager.lazy_session_delete = AsyncMock()

    from handlers.member_captcha.session import CaptchaSession

    monkeypatch.setattr(CaptchaSession, "is_flagged", AsyncMock(return_value="advertising"))
    monkeypatch.setattr(CaptchaSession, "is_restricted", AsyncMock(return_value=True))

    await new_member_check(mock_manager.client, -1001445219041, 10, 42)

    mock_manager.hide_member.assert_awaited()
    args = mock_manager.hide_member.await_args.args
    assert args[2] == timedelta(days=30)
    mock_manager.lazy_session.assert_not_awaited()

@pytest.mark.asyncio
async def test_default_timeout_schedules_unban(monkeypatch, mock_manager):
    import handlers.member_captcha.events  # noqa: F401
    new_member_check = mock_manager.events["new_member_check"]

    chat = SimpleNamespace(id=-1001445219041, title="g")
    mock_manager.client.get_entity = AsyncMock(return_value=chat)
    mock_manager.client.get_permissions = AsyncMock(return_value=_restricted_perms())
    mock_manager.client.kick_participant = AsyncMock()
    mock_manager.client.edit_permissions = AsyncMock()
    mock_manager.lazy_session = AsyncMock()
    mock_manager.lazy_session_delete = AsyncMock()

    from handlers.member_captcha.session import CaptchaSession

    monkeypatch.setattr(CaptchaSession, "is_flagged", AsyncMock(return_value=None))
    monkeypatch.setattr(CaptchaSession, "is_restricted", AsyncMock(return_value=True))

    await new_member_check(mock_manager.client, -1001445219041, 10, 42)

    mock_manager.kick_member.assert_awaited_once_with(chat, 42)
    mock_manager.lazy_session.assert_awaited()
    assert mock_manager.lazy_session.await_args.args[3] == "unban_member"

@pytest.mark.asyncio
async def test_timeout_skips_already_banned_no_unban(monkeypatch, mock_manager):
    """Admin /sb or reject already banned the user — timeout must not overwrite or unban."""
    import handlers.member_captcha.events  # noqa: F401
    new_member_check = mock_manager.events["new_member_check"]

    chat = SimpleNamespace(id=-1001445219041, title="g")
    mock_manager.client.get_entity = AsyncMock(return_value=chat)
    mock_manager.client.get_permissions = AsyncMock(return_value=_banned_perms())
    mock_manager.client.edit_permissions = AsyncMock()
    mock_manager.lazy_session = AsyncMock()
    mock_manager.lazy_session_delete = AsyncMock()

    from handlers.member_captcha.session import CaptchaSession

    monkeypatch.setattr(CaptchaSession, "is_flagged", AsyncMock(return_value=None))
    monkeypatch.setattr(CaptchaSession, "is_restricted", AsyncMock(return_value=False))

    await new_member_check(mock_manager.client, -1001445219041, 10, 42)

    mock_manager.client.edit_permissions.assert_not_called()
    mock_manager.lazy_session.assert_not_awaited()
