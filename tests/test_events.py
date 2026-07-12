"""Tests for lazy captcha timeout / unban event handlers."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_advertising_timeout_does_not_schedule_unban(monkeypatch, mock_manager):
    # register_event 存的是原始协程函数；装饰器返回值不会正确 await 内部 coroutine
    import handlers.member_captcha.events  # noqa: F401 — 注册事件
    new_member_check = mock_manager.events["new_member_check"]

    class _Perms:
        is_admin = False
        is_creator = False
        send_messages = False

    chat = SimpleNamespace(id=-1001445219041, title="g")
    mock_manager.client.get_entity = AsyncMock(return_value=chat)
    mock_manager.client.get_permissions = AsyncMock(return_value=_Perms())
    mock_manager.client.edit_permissions = AsyncMock()
    mock_manager.lazy_session = AsyncMock()
    mock_manager.lazy_session_delete = AsyncMock()

    from handlers.member_captcha.session import CaptchaSession

    monkeypatch.setattr(CaptchaSession, "is_flagged", AsyncMock(return_value="advertising"))

    await new_member_check(mock_manager.client, -1001445219041, 10, 42)

    mock_manager.client.edit_permissions.assert_awaited()
    kwargs = mock_manager.client.edit_permissions.await_args.kwargs
    assert kwargs.get("view_messages") is False
    assert kwargs.get("until_date") == timedelta(days=30)
    mock_manager.lazy_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_default_timeout_schedules_unban(monkeypatch, mock_manager):
    import handlers.member_captcha.events  # noqa: F401
    new_member_check = mock_manager.events["new_member_check"]

    class _Perms:
        is_admin = False
        is_creator = False
        send_messages = False

    chat = SimpleNamespace(id=-1001445219041, title="g")
    mock_manager.client.get_entity = AsyncMock(return_value=chat)
    mock_manager.client.get_permissions = AsyncMock(return_value=_Perms())
    mock_manager.client.edit_permissions = AsyncMock()
    mock_manager.lazy_session = AsyncMock()
    mock_manager.lazy_session_delete = AsyncMock()

    from handlers.member_captcha.session import CaptchaSession

    monkeypatch.setattr(CaptchaSession, "is_flagged", AsyncMock(return_value=None))

    await new_member_check(mock_manager.client, -1001445219041, 10, 42)

    mock_manager.lazy_session.assert_awaited()
    assert mock_manager.lazy_session.await_args.args[3] == "unban_member"


@pytest.mark.asyncio
async def test_resolve_chat_entity_tries_peer_channel(monkeypatch):
    from manager.group import resolve_chat_entity
    from telethon.tl import types

    client = AsyncMock()
    entity = SimpleNamespace(id=1445219041, title="g")

    async def _get_entity(peer):
        if isinstance(peer, types.PeerChannel) and peer.channel_id == 1445219041:
            return entity
        raise ValueError(f"no entity for {peer!r}")

    client.get_entity = AsyncMock(side_effect=_get_entity)
    result = await resolve_chat_entity(client, 1445219041)
    assert result is entity
