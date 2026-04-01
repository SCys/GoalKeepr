"""
Tests for handlers/member_captcha/join_queue.py
测试入群队列处理
"""

import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

from handlers.member_captcha.join_queue import (
    publish_join_event,
    process_join_events,
    _process_one_join_event,
    REPEAT_JOIN_WINDOW_SECONDS,
    REPEAT_JOIN_THRESHOLD,
    RECENT_JOINS_USER_PREFIX,
    RECENT_JOINS_USER_SUFFIX,
)


@pytest.mark.asyncio
class TestJoinQueue:
    """测试入群队列功能"""

    async def test_publish_join_event_basic(self, mock_redis):
        """测试发布入群事件（基本）"""
        chat_id = -1001085650365
        user_id = 123456789
        ts = datetime.now(timezone.utc).timestamp()

        result = await publish_join_event(
            mock_redis, chat_id, user_id, ts, "ban", "testuser", "Test User"
        )

        assert result is True
        mock_redis.lpush.assert_called_once()

    async def test_publish_join_event_without_username(self, mock_redis):
        """测试发布入群事件（无用户名）"""
        chat_id = -1001085650365
        user_id = 123456789

        result = await publish_join_event(
            mock_redis, chat_id, user_id, None, "ban", None, "Test User"
        )

        assert result is True

    async def test_publish_join_event_error(self, mock_redis):
        """测试发布入群事件错误"""
        mock_redis.lpush = AsyncMock(side_effect=Exception("Redis error"))

        result = await publish_join_event(
            mock_redis, -1001, 123, None, "ban", None, "Test"
        )

        assert result is False

    async def test_process_one_join_event_new(self, mock_redis):
        """测试处理新的入群事件"""
        payload = {
            "chat_id": "-1001085650365",
            "user_id": "123456789",
            "ts": 1234567890.0,
            "checker_type": "ban",
            "username": "testuser",
            "full_name": "Test User",
        }

        await _process_one_join_event(mock_redis, payload)

        mock_redis.zadd.assert_called()
        mock_redis.zremrangebyscore.assert_called()
        mock_redis.expire.assert_called()
        mock_redis.zcard.assert_called()

    async def test_process_join_events_no_data(self, mock_redis):
        """测试处理入群事件（无数据）"""
        mock_redis.brpop = AsyncMock(return_value=None)

        result = await process_join_events(mock_redis, block_seconds=0.1)

        assert result == 0

    async def test_process_join_events_success(self, mock_redis):
        """测试处理入群事件（成功）"""
        payload = {
            "chat_id": "-1001085650365",
            "user_id": "123456789",
            "ts": 1234567890.0,
            "checker_type": "ban",
            "username": "testuser",
            "full_name": "Test User",
        }

        mock_redis.brpop = AsyncMock(
            return_value=(b"member_join_queue", json.dumps(payload).encode())
        )

        result = await process_join_events(mock_redis, block_seconds=0.1)

        assert result >= 1

    async def test_process_join_events_invalid_json(self, mock_redis):
        """测试处理入群事件（无效 JSON）"""
        mock_redis.brpop = AsyncMock(
            return_value=(b"member_join_queue", b"invalid json")
        )

        result = await process_join_events(mock_redis, block_seconds=0.1)

        assert result == 1  # 仍然返回 1，因为消费了数据


@pytest.mark.asyncio
class TestRepeatJoinDetection:
    """测试重复加入检测"""

    async def test_repeat_join_detection_threshold(self, mock_redis):
        """测试重复加入检测（达到阈值）"""
        from handlers.member_captcha.join_queue import (
            REPEAT_JOIN_THRESHOLD,
            REPEAT_JOIN_ACTION,
        )
        from unittest.mock import patch, AsyncMock

        # 模拟在窗口内已经有 REPEAT_JOIN_THRESHOLD 次加入
        chat_id = -1001085650365
        user_id = 123456789
        now = datetime.now(timezone.utc).timestamp()

        # 添加之前的加入记录
        for i in range(REPEAT_JOIN_THRESHOLD):
            await mock_redis.zadd(
                f"{RECENT_JOINS_USER_PREFIX}{chat_id}:{user_id}",
                {f"{now - i * 60}": now - i * 60},
            )

        mock_redis.zcard = AsyncMock(return_value=REPEAT_JOIN_THRESHOLD)

        payload = {
            "chat_id": str(chat_id),
            "user_id": str(user_id),
            "ts": now,
            "checker_type": "ban",
        }

        # Patch _handle_repeated_join 避免实际执行（需要 manager）
        with patch(
            "handlers.member_captcha.join_queue._handle_repeated_join", AsyncMock()
        ):
            await _process_one_join_event(mock_redis, payload)

        assert mock_redis.zcard.called

    async def test_repeat_join_detection_below_threshold(self, mock_redis):
        """测试重复加入检测（未达到阈值）"""
        chat_id = -1001085650365
        user_id = 123456789
        now = datetime.now(timezone.utc).timestamp()

        payload = {
            "chat_id": str(chat_id),
            "user_id": str(user_id),
            "ts": now,
            "checker_type": "ban",
        }

        await _process_one_join_event(mock_redis, payload)

        # 检测逻辑应该正常工作
        mock_redis.zadd.assert_called()
