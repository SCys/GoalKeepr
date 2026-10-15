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


# ---- 队列扫描的键过滤与脏数据清理 ----


async def test_all_tasks_ignores_internal_keys(fake_redis):
    """image:lock:* / image:img:* 等内部键不得进入任务队列解析。

    回归：锁键的值是 "1"，orjson 解析为 int 后 task_data["msg"] 抛
    TypeError，旧代码会拖垮整个 all_tasks 调用（worker 整轮崩溃）。
    """
    task = make_task()
    await task.enqueue_task(fake_redis)
    await fake_redis.set(f"image:lock:{task.task_id}", "1", nx=True, ex=180)
    await fake_redis.set(f"image:img:{task.task_id}", b"\x89PNG-binary")

    tasks = await image_mod.Task.all_tasks(fake_redis)

    assert len(tasks) == 1
    assert tasks[0].task_id == task.task_id
    # 内部键不受影响
    assert await fake_redis.exists(f"image:lock:{task.task_id}")
    assert await fake_redis.exists(f"image:img:{task.task_id}")


async def test_all_tasks_removes_garbage_keys(fake_redis):
    """解析失败的任务键被跳过并删除，避免永久占用队列名额。"""
    task = make_task()
    await task.enqueue_task(fake_redis)
    await fake_redis.set("image:corrupted", b"not-a-task{{{")

    tasks = await image_mod.Task.all_tasks(fake_redis)

    assert [t.task_id for t in tasks] == [task.task_id]
    assert not await fake_redis.exists("image:corrupted")


# ---- worker 启动队列快照日志 ----


def _capture_logs():
    from loguru import logger

    records = []
    handler_id = logger.add(lambda m: records.append(m.record["message"]), level="INFO")
    return records, handler_id


async def test_queue_snapshot_logs_existing_tasks(fake_redis):
    from loguru import logger

    task = make_task()
    await task.enqueue_task(fake_redis)

    records, hid = _capture_logs()
    try:
        await image_mod.log_queue_snapshot(fake_redis)
    finally:
        logger.remove(hid)

    text = "\n".join(records)
    assert "1 task(s)" in text
    assert task.task_id in text
    assert "status=queued" in text
    assert "model=zimage" in text


async def test_queue_snapshot_empty_queue(fake_redis):
    from loguru import logger

    records, hid = _capture_logs()
    try:
        await image_mod.log_queue_snapshot(fake_redis)
    finally:
        logger.remove(hid)

    assert any("empty" in r for r in records)


async def test_queue_snapshot_survives_redis_errors():
    """all_tasks 抛错时只记 warning，不炸 worker 启动流程。"""
    from loguru import logger

    class BrokenRedis:
        pass

    records, hid = _capture_logs()
    try:
        await image_mod.log_queue_snapshot(BrokenRedis())
    finally:
        logger.remove(hid)

    assert any("snapshot failed" in r for r in records)
