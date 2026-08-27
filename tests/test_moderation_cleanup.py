"""Tests: cancel_pending_member_jobs + /k /sb interaction with captcha jobs."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


CHAT_ID = -100123456
BOT_API_CHAT_ID = -1001085650365
USER_ID = 424242


@pytest.mark.asyncio
async def test_cancel_pending_member_jobs_cancels_all(mock_manager, fake_redis):
    from handlers.member_captcha.helpers import cancel_pending_member_jobs
    from handlers.member_captcha.session import CaptchaSession

    await CaptchaSession.check_and_record(CHAT_ID, USER_ID)
    assert await CaptchaSession.get(CHAT_ID, USER_ID) is not None

    await cancel_pending_member_jobs(CHAT_ID, USER_ID)

    deleted = {c.args[2] for c in mock_manager.lazy_session_delete.await_args_list}
    assert deleted == {"new_member_check", "safety_timeout_check", "unban_member"}
    assert await CaptchaSession.get(CHAT_ID, USER_ID) is None


@pytest.mark.asyncio
async def test_cancel_pending_can_keep_unban_and_session(mock_manager, fake_redis):
    from handlers.member_captcha.helpers import cancel_pending_member_jobs
    from handlers.member_captcha.session import CaptchaSession

    await CaptchaSession.check_and_record(CHAT_ID, USER_ID)

    await cancel_pending_member_jobs(
        CHAT_ID, USER_ID, cancel_unban=False, delete_captcha_session=False
    )

    deleted = {c.args[2] for c in mock_manager.lazy_session_delete.await_args_list}
    assert deleted == {"new_member_check", "safety_timeout_check"}
    assert "unban_member" not in deleted
    assert await CaptchaSession.get(CHAT_ID, USER_ID) is not None


@pytest.mark.asyncio
async def test_sb_cancels_captcha_and_unban(mock_manager):
    """Permanent ban must cancel captcha timeout + any scheduled unban."""
    from handlers.commands.sb import ban_member

    chat = SimpleNamespace(id=CHAT_ID, title="g")
    event = SimpleNamespace(
        id=1,
        chat_id=BOT_API_CHAT_ID,
        reply=AsyncMock(return_value=SimpleNamespace(id=99)),
    )
    admin = SimpleNamespace(id=1, username="admin", first_name="A", last_name="")
    member = SimpleNamespace(id=USER_ID, username="u", first_name="U", last_name="")

    response = SimpleNamespace(status=200, json=AsyncMock(return_value={"ok": True}))
    request = MagicMock()
    request.__aenter__ = AsyncMock(return_value=response)
    request.__aexit__ = AsyncMock(return_value=False)
    session = SimpleNamespace(post=MagicMock(return_value=request))
    mock_manager.create_session = AsyncMock(return_value=session)
    mock_manager.username = lambda u: getattr(u, "username", None) or "x"

    # ban_member 内部 from helpers import，patch 源模块即可
    with patch(
        "handlers.member_captcha.helpers.cancel_pending_member_jobs",
        new_callable=AsyncMock,
    ) as mock_cancel:
        result = await ban_member(chat, event, admin, member)

    mock_cancel.assert_awaited_once_with(CHAT_ID, USER_ID)
    session.post.assert_called_once_with(
        "https://api.telegram.org/bot123:test/banChatMember",
        json={"chat_id": BOT_API_CHAT_ID, "user_id": USER_ID, "revoke_messages": True},
    )
    mock_manager.ban_member.assert_awaited_once_with(chat, USER_ID, None)
    # /sb must NOT schedule unban
    mock_manager.lazy_session.assert_not_awaited()
    assert result is not None


@pytest.mark.asyncio
async def test_k_cancels_and_kicks(mock_manager):
    """Kick command cancels captcha jobs, then kicks the user."""
    from handlers.commands.k import kick_member

    chat = SimpleNamespace(id=CHAT_ID, title="g")
    event = SimpleNamespace(id=7, reply=AsyncMock(return_value=SimpleNamespace(id=99)))
    admin = SimpleNamespace(id=1, username="admin", first_name="A", last_name="")
    member = SimpleNamespace(id=USER_ID, username="u", first_name="U", last_name="")

    mock_manager.kick_member = AsyncMock(return_value=True)
    mock_manager.username = lambda u: getattr(u, "username", None) or "x"

    with patch(
        "handlers.member_captcha.helpers.cancel_pending_member_jobs",
        new_callable=AsyncMock,
    ) as mock_cancel:
        result = await kick_member(chat, event, admin, member)

    mock_cancel.assert_awaited_once_with(CHAT_ID, USER_ID)
    mock_manager.kick_member.assert_awaited_once_with(chat, USER_ID)
    mock_manager.lazy_session.assert_not_awaited()
    assert result is not None
