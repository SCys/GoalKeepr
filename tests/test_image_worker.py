"""image worker 状态机回归测试：not_found 任务出队后不得复活。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import handlers.commands.image as image_mod
from tests.test_image_progress import make_task


@pytest.fixture
def fake_dispatcher(monkeypatch):
    disp = SimpleNamespace(
        submit_edit=AsyncMock(),
        submit_delete=AsyncMock(),
        submit_delivery=AsyncMock(),
        submit_progress_edit=AsyncMock(),
        is_delivering=lambda task_id: False,
        degrade_level=0,
        ensure_running=lambda: None,
    )
    monkeypatch.setattr(image_mod, "dispatcher", disp)
    return disp


async def test_not_found_task_is_dequeued_and_not_resurrected(mock_manager, fake_redis, fake_dispatcher):
    """not_found 任务经 fail_task 出队后，process_task 末尾不得再写回 Redis。

    回归：此前 process_task 无条件 rdb.set 导致任务复活，worker 每秒重复
    handle_not_found_task 并不停编辑状态消息（无限轮询）。
    """
    mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}

    task = make_task()
    task.status = "not_found"
    await task.enqueue_task(fake_redis)

    await image_mod.process_task(task)

    assert not await fake_redis.exists(f"image:{task.task_id}")
    # 状态消息只编辑一次（失败收尾），不会每秒重复
    assert fake_dispatcher.submit_edit.call_count == 1
    text = fake_dispatcher.submit_edit.call_args[0][2]
    assert "失败" in text or "Failed" in text or "failed" in text.lower()


async def test_failed_task_stays_failed_after_process(mock_manager, fake_redis, fake_dispatcher):
    """投递兜底阶段失败（字节丢失）同样出队不复活。"""
    mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}

    task = make_task()
    task.status = "delivering"
    task.options["image_filename"] = None  # 无文件名可重下载 → 直接失败
    await task.enqueue_task(fake_redis)

    await image_mod.process_task(task)

    assert not await fake_redis.exists(f"image:{task.task_id}")
    fake_dispatcher.submit_delivery.assert_not_called()


# ---- 已删除消息的编辑短路 ----


async def test_dispatcher_marks_gone_and_short_circuits(mock_manager, monkeypatch):
    """编辑返回 None（消息已删）后，同一消息的 edit/progress/delete 全部短路。"""
    from handlers.commands.image import OutboundDispatcher

    mock_manager.edit_text = AsyncMock(return_value=None)
    disp = OutboundDispatcher()
    captured = []

    async def fake_enqueue(op):
        captured.append(op)

    monkeypatch.setattr(disp, "_enqueue", fake_enqueue)

    await disp.submit_edit(123, 456, "hello")
    assert len(captured) == 1
    await captured[0].factory()
    assert (123, 456) in disp._gone_msgs

    # 后续所有操作直接短路，不再入队
    await disp.submit_edit(123, 456, "world")
    await disp.submit_progress_edit(123, 456, lambda: "world")
    await disp.submit_delete(123, 456)
    assert len(captured) == 1
    assert mock_manager.edit_text.call_count == 1


async def test_dispatcher_delete_marks_gone(mock_manager, monkeypatch):
    """删除成功后同样短路迟到的编辑。"""
    from handlers.commands.image import OutboundDispatcher

    mock_manager.delete_message = AsyncMock(return_value=True)
    disp = OutboundDispatcher()
    captured = []

    async def fake_enqueue(op):
        captured.append(op)

    monkeypatch.setattr(disp, "_enqueue", fake_enqueue)

    await disp.submit_delete(123, 456)
    await captured[0].factory()
    assert (123, 456) in disp._gone_msgs

    await disp.submit_edit(123, 456, "late edit")
    assert len(captured) == 1


async def test_edit_text_returns_none_when_message_gone():
    from unittest.mock import MagicMock

    from manager.manager import Manager
    from telethon.errors import MessageIdInvalidError

    mgr = object.__new__(Manager)
    mgr.client = MagicMock()
    mgr.client.edit_message = AsyncMock(side_effect=MessageIdInvalidError("req"))

    assert await mgr.edit_text(123, 456, "x") is None


async def test_edit_text_not_modified_is_success():
    from unittest.mock import MagicMock

    from manager.manager import Manager
    from telethon.errors import MessageNotModifiedError

    mgr = object.__new__(Manager)
    mgr.client = MagicMock()
    mgr.client.edit_message = AsyncMock(side_effect=MessageNotModifiedError("req"))

    assert await mgr.edit_text(123, 456, "x") is True
