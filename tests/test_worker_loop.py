"""Tests for worker loop lazy message deletion and session cleanup."""
from __future__ import annotations

from unittest.mock import AsyncMock
import pytest

import database
from main import lazy_messages, lazy_sessions, SQL_CREATE_MESSAGES, SQL_CREATE_NEW_MEMBER_SESSION


@pytest.fixture(autouse=True)
async def cleanup_database():
    """Ensure database connection is cleanly closed between tests."""
    yield
    await database.close()


@pytest.mark.asyncio
async def test_lazy_messages_redis_removes_failed_task(fake_redis, mock_manager):
    """When delete_message returns False, task must still be removed from Redis."""
    mock_manager.get_redis = AsyncMock(return_value=fake_redis)
    mock_manager.delete_message = AsyncMock(return_value=False)

    task_key = "-100123:456"
    # Schedule task with timestamp 0 (already expired)
    await fake_redis.zadd("lazy_delete_messages", {task_key: 0.0})

    processed = await lazy_messages()
    assert processed == 1

    # Task should have been removed from lazy_delete_messages
    remaining = await fake_redis.zrangebyscore("lazy_delete_messages", 0, 9999999999)
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_lazy_messages_sqlite_removes_failed_task(mock_manager):
    """When delete_message returns False, row must still be deleted from SQLite."""
    mock_manager.get_redis = AsyncMock(return_value=None)
    mock_manager.delete_message = AsyncMock(return_value=False)

    await database.execute(SQL_CREATE_MESSAGES)
    await database.execute(
        "insert into lazy_delete_messages(chat, msg, deleted_at) values(?, ?, datetime('now', '-1 minute', 'localtime'))",
        (-100123, 789),
    )

    processed = await lazy_messages()
    assert processed == 1

    rows = await database.execute_fetch("select id from lazy_delete_messages where chat=-100123")
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_lazy_sessions_redis_removes_failing_callback(fake_redis, mock_manager):
    """When session callback raises an exception, task must still be removed from Redis."""
    mock_manager.get_redis = AsyncMock(return_value=fake_redis)

    failing_func = AsyncMock(side_effect=RuntimeError("Telegram RPC timeout"))
    mock_manager.events = {"test_timeout": failing_func}

    task_key = "-100123:456:test_timeout:789"
    await fake_redis.zadd("lazy_sessions", {task_key: 0.0})

    processed = await lazy_sessions()
    assert processed == 1
    failing_func.assert_awaited_once()

    remaining = await fake_redis.zrangebyscore("lazy_sessions", 0, 9999999999)
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_lazy_sessions_sqlite_removes_failing_callback(mock_manager):
    """When session callback raises an exception, row must still be deleted from SQLite."""
    mock_manager.get_redis = AsyncMock(return_value=None)

    failing_func = AsyncMock(side_effect=RuntimeError("Database error"))
    mock_manager.events = {"test_timeout": failing_func}

    await database.execute(SQL_CREATE_NEW_MEMBER_SESSION)
    await database.execute(
        "insert into lazy_sessions(chat, msg, member, type, checkout_at) values(?, ?, ?, ?, datetime('now', '-1 minute', 'localtime'))",
        (-100123, 789, 456, "test_timeout"),
    )

    processed = await lazy_sessions()
    assert processed == 1
    failing_func.assert_awaited_once()

    rows = await database.execute_fetch("select id from lazy_sessions where chat=-100123")
    assert len(rows) == 0
