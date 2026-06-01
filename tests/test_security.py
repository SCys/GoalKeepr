"""Tests for security module (perform_security_checks, restrict_member_permissions)."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_user(user_id=12345, first_name="Test", last_name="User", username="testuser"):
    """Build a minimal Telethon-like user object."""
    return SimpleNamespace(
        id=user_id,
        first_name=first_name,
        last_name=last_name,
        username=username,
    )


def _make_session():
    """Create a lightweight session-like object."""
    return SimpleNamespace(
        member_username="testuser",
        member_bio=None,
        banned=False,
    )


class TestRestrictMemberPermissions:
    async def test_restrict_success(self, mock_manager):
        from handlers.member_captcha.security import restrict_member_permissions

        chat = _make_user(user_id=-100999, first_name="Chat")
        user = _make_user()

        result = await restrict_member_permissions(chat, user)
        assert result is True
        mock_manager.client.edit_permissions.assert_awaited_once()

    async def test_restrict_failure_returns_false(self, mock_manager):
        from handlers.member_captcha.security import restrict_member_permissions

        mock_manager.client.edit_permissions.side_effect = Exception("no permission")

        chat = _make_user(user_id=-100999, first_name="Chat")
        user = _make_user()

        result = await restrict_member_permissions(chat, user)
        assert result is False


class TestRestoreMemberPermissions:
    async def test_restore_success(self, mock_manager):
        from handlers.member_captcha.security import restore_member_permissions

        chat = _make_user(user_id=-100999, first_name="Chat")
        user = _make_user()

        result = await restore_member_permissions(chat, user)
        assert result is True
        mock_manager.client.edit_permissions.assert_awaited_once()

    async def test_restore_failure_returns_false(self, mock_manager):
        from handlers.member_captcha.security import restore_member_permissions

        mock_manager.client.edit_permissions.side_effect = Exception("fail")
        chat = _make_user(user_id=-100999, first_name="Chat")
        user = _make_user()

        result = await restore_member_permissions(chat, user)
        assert result is False


class TestSecurityChecks:
    async def test_clean_user_returns_none(self, mock_manager, mock_llm_clean, mock_advertising_config):
        from handlers.member_captcha.security import perform_security_checks
        from handlers.member_captcha.exceptions import LogContext

        user = _make_user(first_name="John", last_name="Doe")
        session = _make_session()
        log_ctx = LogContext(chat=_make_user(user_id=-100, username="__log_ctx_chat__"), member_id=user.id, member_name=user.username, member_fullname="John Doe")

        reason = await perform_security_checks(user, session, ["John Doe"], log_ctx, NOW)
        assert reason is None, "clean user should pass security checks"

    async def test_llm_spam_returns_llm(self, mock_manager, mock_llm_spam, mock_advertising_config):
        from handlers.member_captcha.security import perform_security_checks
        from handlers.member_captcha.exceptions import LogContext

        user = _make_user(first_name="John", last_name="Doe")
        session = _make_session()
        log_ctx = LogContext(chat=_make_user(user_id=-100, username="__log_ctx_chat__"), member_id=user.id, member_name=user.username, member_fullname="John Doe")

        reason = await perform_security_checks(user, session, ["John Doe"], log_ctx, NOW)
        assert reason == "llm", "LLM-detected spam should return 'llm'"

    async def test_advertising_returns_advertising(self, mock_manager, mock_llm_clean, mock_advertising_config):
        from handlers.member_captcha.security import perform_security_checks
        from handlers.member_captcha.exceptions import LogContext

        user = _make_user(first_name="推广", last_name="广告推广")  # contains advertising words
        session = _make_session()
        log_ctx = LogContext(chat=_make_user(user_id=-100, username="__log_ctx_chat__"), member_id=user.id, member_name=user.username, member_fullname="推广 广告推广")

        reason = await perform_security_checks(user, session, ["推广 广告推广"], log_ctx, NOW)
        assert reason == "advertising", "advertising word should return 'advertising'"

    async def test_llm_takes_priority_over_advertising(self, mock_manager, mock_llm_spam, mock_advertising_config):
        """LLM check runs first, so if LLM flags, advertising check is skipped."""
        from handlers.member_captcha.security import perform_security_checks
        from handlers.member_captcha.exceptions import LogContext

        # Both conditions met, but LLM runs first
        user = _make_user(first_name="推广", last_name="广告推广")
        session = _make_session()
        log_ctx = LogContext(chat=_make_user(user_id=-100, username="__log_ctx_chat__"), member_id=user.id, member_name=user.username, member_fullname="推广 广告推广")

        reason = await perform_security_checks(user, session, ["推广 广告推广"], log_ctx, NOW)
        assert reason == "llm", "LLM result should take priority"

    async def test_llm_failure_does_not_block_proceeding(self, mock_manager, mock_advertising_config):
        """If LLM check fails with exception, advertising check should still work."""
        import handlers.utils.llm as llm_mod

        with patch.object(llm_mod, "chat_completions", side_effect=Exception("API down")):

            from handlers.member_captcha.security import perform_security_checks
            from handlers.member_captcha.exceptions import LogContext

            user = _make_user(first_name="John", last_name="Doe")
            session = _make_session()
            log_ctx = LogContext(chat=_make_user(user_id=-100, username="__log_ctx_chat__"), member_id=user.id, member_name=user.username)

            # LLM fails but text is clean → no spam detected
            reason = await perform_security_checks(user, session, ["John Doe"], log_ctx, NOW)
            assert reason is None, "clean user should pass even if LLM fails"


class TestGetMemberInfo:
    async def test_with_username_and_bio(self, mock_manager):
        from handlers.member_captcha.security import get_member_info_for_check

        user = _make_user()
        session = _make_session()

        mock_manager.get_user_extra_info = AsyncMock(
            return_value={"bio": "I love programming"}
        )

        check_list = await get_member_info_for_check(user, session)
        assert "Test User" in check_list
        assert "I love programming" in check_list
        assert session.member_bio == "I love programming"

    async def test_username_error_sets_no_bio(self, mock_manager):
        from handlers.member_captcha.security import get_member_info_for_check

        user = _make_user()
        session = _make_session()

        mock_manager.get_user_extra_info = AsyncMock(side_effect=Exception("fetch failed"))

        check_list = await get_member_info_for_check(user, session)
        assert "Test User" in check_list
        assert session.member_bio is None
