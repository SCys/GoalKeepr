"""Tests for CaptchaSession (frequency control, dedup, flagging)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

CHAT_ID = -100123456
USER_ID = 999888
NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
EVENT_UID = "msg:42"


@pytest.fixture
def captcha_session():
    from handlers.member_captcha.session import CaptchaSession

    return CaptchaSession


@pytest.mark.usefixtures("mock_manager")
class TestCheckAndRecord:
    """CaptchaSession.check_and_record() — the core frequency + dedup gate."""

    async def test_new_user_proceeds(self, fake_redis, captcha_session):
        should_proceed, data = await captcha_session.check_and_record(
            CHAT_ID, USER_ID, NOW, event_uid=EVENT_UID
        )
        assert should_proceed is True
        assert data["state"] == "normal"
        assert data["join_count"] == "1"

        # Redis key exists with correct TTL
        key = captcha_session.make_key(CHAT_ID, USER_ID)
        exists = await fake_redis.exists(key)
        assert exists is True

    async def test_duplicate_event_is_blocked(self, fake_redis, captcha_session):
        # First call succeeds
        first, _ = await captcha_session.check_and_record(
            CHAT_ID, USER_ID, NOW, event_uid=EVENT_UID
        )
        assert first is True

        # Second call with same event_uid → dedup lock, should be blocked
        second, data = await captcha_session.check_and_record(
            CHAT_ID, USER_ID, NOW, event_uid=EVENT_UID
        )
        assert second is False
        assert data["state"] == "duplicate"

    async def test_different_event_uid_passes(self, fake_redis, captcha_session):
        """Same user, same time, but different event_uid → allowed."""
        first, _ = await captcha_session.check_and_record(
            CHAT_ID, USER_ID, NOW, event_uid="msg:1"
        )
        assert first is True

        second, _ = await captcha_session.check_and_record(
            CHAT_ID, USER_ID, NOW, event_uid="msg:2"
        )
        assert second is True

    async def test_throttled_after_many_joins(self, fake_redis, captcha_session):
        """Reaching CAPTCHA_JOIN_THRESHOLD_KICK (30) should throttle."""
        # Insert a session with join_count already at 29
        key = captcha_session.make_key(CHAT_ID, USER_ID)
        await fake_redis.hset(key, mapping={
            "join_count": "29",
            "total_joins": "29",
            "first_join_ts": NOW.isoformat(),
            "last_join_ts": NOW.isoformat(),
            "state": "normal",
            "chat_id": str(CHAT_ID),
            "user_id": str(USER_ID),
        })

        should_proceed, data = await captcha_session.check_and_record(
            CHAT_ID, USER_ID, NOW, event_uid=EVENT_UID
        )
        assert should_proceed is False
        assert data["state"] == "throttled"
        assert data["join_count"] == "30"

    async def test_throttled_user_rejoin_still_blocked(self, fake_redis, captcha_session):
        """A throttled user who rejoins is still throttled until count drops."""
        key = captcha_session.make_key(CHAT_ID, USER_ID)
        await fake_redis.hset(key, mapping={
            "join_count": "30",
            "total_joins": "30",
            "first_join_ts": NOW.isoformat(),
            "last_join_ts": NOW.isoformat(),
            "state": "throttled",
            "chat_id": str(CHAT_ID),
            "user_id": str(USER_ID),
        })

        should_proceed, data = await captcha_session.check_and_record(
            CHAT_ID, USER_ID, NOW, event_uid=EVENT_UID
        )
        assert should_proceed is False
        assert data["state"] == "throttled"


@pytest.mark.usefixtures("mock_manager")
class TestFlagging:
    async def test_flag_and_is_flagged(self, fake_redis, captcha_session):
        # Must have a session first
        await captcha_session.check_and_record(CHAT_ID, USER_ID, NOW, event_uid=EVENT_UID)

        await captcha_session.flag(CHAT_ID, USER_ID, "advertising")
        reason = await captcha_session.is_flagged(CHAT_ID, USER_ID)
        assert reason == "advertising"

        # Delete session → is_flagged returns None
        await captcha_session.delete(CHAT_ID, USER_ID)
        reason = await captcha_session.is_flagged(CHAT_ID, USER_ID)
        assert reason is None

    async def test_llm_flag(self, fake_redis, captcha_session):
        await captcha_session.check_and_record(CHAT_ID, USER_ID, NOW, event_uid=EVENT_UID)
        await captcha_session.flag(CHAT_ID, USER_ID, "llm")
        assert await captcha_session.is_flagged(CHAT_ID, USER_ID) == "llm"

    async def test_rejoin_clears_flag(self, fake_redis, captcha_session):
        """When a flagged user is kicked and rejoins, the old flag is cleared."""
        await captcha_session.check_and_record(CHAT_ID, USER_ID, NOW, event_uid="msg:1")
        await captcha_session.flag(CHAT_ID, USER_ID, "advertising")

        # Rejoin with new event
        should_proceed, data = await captcha_session.check_and_record(
            CHAT_ID, USER_ID, NOW, event_uid="msg:2"
        )
        assert should_proceed is True
        assert data["state"] == "normal"

        # Flag should be gone
        reason = await captcha_session.is_flagged(CHAT_ID, USER_ID)
        assert reason is None, "flag should be cleared on rejoin"


@pytest.mark.usefixtures("mock_manager")
class TestAnswerAndRetry:
    async def test_record_answer(self, fake_redis, captcha_session):
        await captcha_session.check_and_record(CHAT_ID, USER_ID, NOW, event_uid=EVENT_UID)

        await captcha_session.record_answer(
            CHAT_ID, USER_ID, icon="❤️", answer="爱心|Love", options='[{"key":"爱心|Love","emoji":"❤️"}]'
        )

        session = await captcha_session.get(CHAT_ID, USER_ID)
        assert session is not None
        assert session["last_icon"] == "❤️"
        assert session["last_answer"] == "爱心|Love"

    async def test_retry_count(self, fake_redis, captcha_session):
        await captcha_session.check_and_record(CHAT_ID, USER_ID, NOW, event_uid=EVENT_UID)

        c1 = await captcha_session.record_retry(CHAT_ID, USER_ID)
        assert c1 == 1
        c2 = await captcha_session.record_retry(CHAT_ID, USER_ID)
        assert c2 == 2
        c3 = await captcha_session.record_retry(CHAT_ID, USER_ID)
        assert c3 == 3

    async def test_retry_reset_on_rejoin(self, fake_redis, captcha_session):
        """Retry count should be cleared on rejoin."""
        await captcha_session.check_and_record(CHAT_ID, USER_ID, NOW, event_uid="msg:1")
        await captcha_session.record_retry(CHAT_ID, USER_ID)
        await captcha_session.record_retry(CHAT_ID, USER_ID)

        await captcha_session.check_and_record(CHAT_ID, USER_ID, NOW, event_uid="msg:2")

        session = await captcha_session.get(CHAT_ID, USER_ID)
        assert session is None or "retry_count" not in session, "retry_count should be cleared on rejoin"


@pytest.mark.usefixtures("mock_manager")
class TestCost:
    async def test_record_cost(self, fake_redis, captcha_session):
        await captcha_session.check_and_record(CHAT_ID, USER_ID, NOW, event_uid=EVENT_UID)
        await captcha_session.record_cost(CHAT_ID, USER_ID, 12.5)

        session = await captcha_session.get(CHAT_ID, USER_ID)
        assert session["last_cost"] == "12.5"
