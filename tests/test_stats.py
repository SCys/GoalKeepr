"""Tests for the captcha stats module."""

import pytest

from handlers.member_captcha.stats import (
    stats_incr,
    _safe_hincrby,
    _safe_sadd,
    STATS_KEY,
    FIELD_GROUP_JOINS,
    FIELD_VERIFICATIONS,
    FIELD_SUCCESS,
    FIELD_FAILED,
)


class TestStatsIncr:
    """Verify stats_incr properly increments fields and records unique users."""

    async def test_group_joins_increments(self, fake_redis):
        await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100, user_id=1)
        raw = await fake_redis.hgetall(STATS_KEY)
        assert int(raw.get(FIELD_GROUP_JOINS.encode(), b"0")) == 1

    async def test_success_increments(self, fake_redis):
        await stats_incr(fake_redis, FIELD_SUCCESS, chat_id=-100, user_id=1)
        raw = await fake_redis.hgetall(STATS_KEY)
        assert int(raw.get(FIELD_SUCCESS.encode(), b"0")) == 1

    async def test_failed_increments(self, fake_redis):
        await stats_incr(fake_redis, FIELD_FAILED, chat_id=-100, user_id=1)
        raw = await fake_redis.hgetall(STATS_KEY)
        assert int(raw.get(FIELD_FAILED.encode(), b"0")) == 1

    async def test_verifications_increments(self, fake_redis):
        await stats_incr(fake_redis, FIELD_VERIFICATIONS, chat_id=-100, user_id=1)
        raw = await fake_redis.hgetall(STATS_KEY)
        assert int(raw.get(FIELD_VERIFICATIONS.encode(), b"0")) == 1

    async def test_per_group_key(self, fake_redis):
        await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100, user_id=1)
        raw = await fake_redis.hgetall("stats:captcha:-100")
        assert int(raw.get(FIELD_GROUP_JOINS.encode(), b"0")) == 1

    async def test_unique_persons(self, fake_redis):
        await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100, user_id=1)
        count = await fake_redis.scard("stats:captcha:persons")
        assert count == 1

    async def test_unique_persons_dedup(self, fake_redis):
        await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100, user_id=1)
        await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100, user_id=1)
        count = await fake_redis.scard("stats:captcha:persons")
        assert count == 1

    async def test_multiple_users(self, fake_redis):
        await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100, user_id=1)
        await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100, user_id=2)
        count = await fake_redis.scard("stats:captcha:persons")
        assert count == 2

    async def test_persons_per_group(self, fake_redis):
        await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100, user_id=1)
        count = await fake_redis.scard("stats:captcha:-100:persons")
        assert count == 1

    async def test_accumulate_multiple_fields(self, fake_redis):
        await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100, user_id=1)
        await stats_incr(fake_redis, FIELD_VERIFICATIONS, chat_id=-100)
        await stats_incr(fake_redis, FIELD_SUCCESS, chat_id=-100, user_id=1)
        raw = await fake_redis.hgetall(STATS_KEY)
        assert int(raw.get(FIELD_GROUP_JOINS.encode(), b"0")) == 1
        assert int(raw.get(FIELD_VERIFICATIONS.encode(), b"0")) == 1
        assert int(raw.get(FIELD_SUCCESS.encode(), b"0")) == 1

    async def test_rdb_none_does_nothing(self):
        # Should not raise
        await stats_incr(None, FIELD_GROUP_JOINS, chat_id=-100, user_id=1)

    async def test_failed_does_not_add_to_persons(self, fake_redis):
        await stats_incr(fake_redis, FIELD_FAILED, chat_id=-100, user_id=1)
        count = await fake_redis.scard("stats:captcha:persons")
        assert count == 0

    async def test_verifications_does_not_add_to_persons(self, fake_redis):
        await stats_incr(fake_redis, FIELD_VERIFICATIONS, chat_id=-100, user_id=1)
        count = await fake_redis.scard("stats:captcha:persons")
        assert count == 0

    async def test_counter_accuracy(self, fake_redis):
        """Multiple increments to the same field accumulate."""
        for _ in range(5):
            await stats_incr(fake_redis, FIELD_GROUP_JOINS, chat_id=-100, user_id=1)
        raw = await fake_redis.hgetall(STATS_KEY)
        assert int(raw.get(FIELD_GROUP_JOINS.encode(), b"0")) == 5


class TestSafeHincrby:
    """_safe_hincrby swallows errors and timeouts."""

    async def test_normal(self, fake_redis):
        await _safe_hincrby(fake_redis, "test", "count", 1)
        raw = await fake_redis.hgetall("test")
        assert int(raw.get(b"count", b"0")) == 1

    async def test_with_none_rdb(self):
        await _safe_hincrby(None, "test", "count", 1)  # should not raise


class TestSafeSadd:
    """_safe_sadd swallows errors and timeouts."""

    async def test_normal(self, fake_redis):
        await _safe_sadd(fake_redis, "test_set", "member1")
        count = await fake_redis.scard("test_set")
        assert count == 1

    async def test_with_none_rdb(self):
        await _safe_sadd(None, "test_set", "member1")  # should not raise
