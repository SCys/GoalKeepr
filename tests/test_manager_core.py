import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_delete_message_falls_back_to_sqlite_when_redis_schedule_fails(mock_manager):
    from manager import manager

    deleted_at = datetime.now(timezone.utc)
    mock_redis = MagicMock()
    mock_redis.zadd = AsyncMock(side_effect=RuntimeError("redis down"))

    with patch.object(manager, "get_redis", AsyncMock(return_value=mock_redis)):
        with patch("database.execute", AsyncMock()) as execute_mock:
            result = await manager.delete_message(-1001, 123, deleted_at)

    assert result is True
    assert execute_mock.await_count == 1


@pytest.mark.asyncio
async def test_lazy_session_falls_back_to_sqlite_when_redis_schedule_fails(mock_manager):
    from manager import manager

    deleted_at = datetime.now(timezone.utc)
    mock_redis = MagicMock()
    mock_redis.zadd = AsyncMock(side_effect=RuntimeError("redis down"))

    with patch.object(manager, "get_redis", AsyncMock(return_value=mock_redis)):
        with patch("database.execute", AsyncMock()) as execute_mock:
            await manager.lazy_session(-1001, 321, 456, "new_member_check", deleted_at)

    assert execute_mock.await_count == 1


@pytest.mark.asyncio
async def test_main_starts_background_workers_after_manager_start(mock_manager):
    import main
    from manager import manager

    manager.setup = MagicMock()
    manager.client.run_until_disconnected = AsyncMock()
    manager.client.disconnect = AsyncMock()

    async def fake_start():
        manager.is_running = True

    manager.start = AsyncMock(side_effect=fake_start)
    created_when_running = []

    def fake_create_task(coro):
        created_when_running.append(manager.is_running)
        coro.close()
        return MagicMock()

    with patch("main.database.execute", AsyncMock()):
        with patch("main.asyncio.create_task", side_effect=fake_create_task):
            await main.main()

    assert created_when_running == [True, True]
