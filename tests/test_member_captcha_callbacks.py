import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_handle_admin_operation_accepts_admin_callback_payload(mock_manager):
    from handlers.member_captcha.callbacks import handle_admin_operation

    chat = MagicMock()
    msg = MagicMock()
    user = MagicMock()
    user.username = "tester"

    mock_manager.client.get_entity = AsyncMock(return_value=user)
    mock_manager.delete_message = AsyncMock(return_value=True)

    with patch(
        "handlers.member_captcha.callbacks.accepted_member", AsyncMock(return_value=True)
    ) as accepted_mock:
        result = await handle_admin_operation(
            chat, msg, "123__2026-01-01 00:00:00+00:00__admin__O", "log"
        )

    assert result is True
    assert accepted_mock.await_count == 1


@pytest.mark.asyncio
async def test_load_captcha_answer_falls_back_to_sqlite(mock_manager):
    from handlers.member_captcha.helpers import load_captcha_answer

    with patch.object(mock_manager, "get_redis", AsyncMock(return_value=None)):
        with patch(
            "database.execute_fetch", AsyncMock(return_value=[("爱心|Love",)])
        ) as fetch_mock:
            result = await load_captcha_answer(-1001, 123)

    assert result == "爱心|Love"
    assert fetch_mock.await_count == 1


@pytest.mark.asyncio
async def test_delete_captcha_answer_cleans_sqlite_when_redis_unavailable(mock_manager):
    from handlers.member_captcha.helpers import delete_captcha_answer

    with patch.object(mock_manager, "get_redis", AsyncMock(return_value=None)):
        with patch("database.execute", AsyncMock()) as execute_mock:
            await delete_captcha_answer(-1001, 123)

    assert execute_mock.await_count == 1
