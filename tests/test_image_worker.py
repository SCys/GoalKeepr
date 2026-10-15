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
