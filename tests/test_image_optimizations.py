"""image 模块优化回归测试：停滞超时 / seed 选项 / FIFO 排序 / 轮询节流 / 合并状态机。"""

import time
from unittest.mock import AsyncMock

import pytest

import handlers.commands.image as image_mod
from tests.test_image_progress import make_task


@pytest.fixture(autouse=True)
def _clean_runtime_state():
    """每个用例前后清空模块级节流/停滞状态，避免互相污染。"""
    image_mod._poll_schedule.clear()
    image_mod._stall_track.clear()
    image_mod._progress_throttle.clear()
    yield
    image_mod._poll_schedule.clear()
    image_mod._stall_track.clear()
    image_mod._progress_throttle.clear()


@pytest.fixture
def fake_dispatcher(monkeypatch):
    from types import SimpleNamespace

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


# ---- 1. running 进度停滞超时 ----


class TestStallTimeout:
    async def test_stalled_progress_marks_failed(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        """WS 进度签名 STALL_TIMEOUT 秒不变 → 任务判失败并出队，不再占队列名额。"""
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        monkeypatch.setattr(
            image_mod.comfy_api.progress_tracker, "snapshot",
            lambda job_id: {"value": 4, "max": 8, "node": "3"},
        )

        task = make_task()
        task.status = "running"
        await task.enqueue_task(fake_redis)

        # 模拟：进度 301 秒前最后一次变动
        image_mod._stall_track[task.task_id] = {
            "sig": (4, 8, "3"),
            "last_change": time.monotonic() - image_mod.STALL_TIMEOUT - 1,
            "first_running": time.monotonic() - image_mod.STALL_TIMEOUT - 1,
        }

        await image_mod.process_task(task)

        assert not await fake_redis.exists(f"image:{task.task_id}")
        assert task.status == "failed"
        # 失败原因体现在状态消息里
        text = fake_dispatcher.submit_edit.call_args[0][2]
        assert "停滞" in text or "stalled" in text.lower()
        # 停滞/轮询状态已清理
        assert task.task_id not in image_mod._stall_track

    async def test_moving_progress_not_failed(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        """进度持续推进时不触发停滞判定，也不发起 HTTP 轮询外的异常。"""
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        holder = {"snap": {"value": 4, "max": 8, "node": "3"}}
        monkeypatch.setattr(
            image_mod.comfy_api.progress_tracker, "snapshot", lambda job_id: holder["snap"]
        )
        monkeypatch.setattr(
            image_mod.comfy_api, "job_status",
            AsyncMock(return_value={"status": "running"}),
        )

        task = make_task()
        task.status = "running"
        await task.enqueue_task(fake_redis)

        await image_mod.process_task(task)  # 建立签名 (4,8,3)
        assert task.status == "running"
        holder["snap"] = {"value": 5, "max": 8, "node": "3"}  # 进度推进
        await image_mod.process_task(task)  # 签名变为 (5,8,3)，计时重置
        assert task.status == "running"
        assert task.task_id in image_mod._stall_track
        assert image_mod._stall_track[task.task_id]["sig"] == (5, 8, "3")

    async def test_no_ws_progress_max_running_time(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        """WS 全程无快照（断连）时按 MAX_RUNNING_TIME 兜底判超时。"""
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        monkeypatch.setattr(image_mod.comfy_api.progress_tracker, "snapshot", lambda job_id: None)

        task = make_task()
        task.status = "running"
        await task.enqueue_task(fake_redis)
        image_mod._stall_track[task.task_id] = {
            "sig": None,
            "last_change": time.monotonic(),
            "first_running": time.monotonic() - image_mod.MAX_RUNNING_TIME - 1,
        }

        await image_mod.process_task(task)

        assert not await fake_redis.exists(f"image:{task.task_id}")
        assert task.status == "failed"

    async def test_queued_task_no_stall_check(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        """非 running 状态不做停滞检测（queued 有独立的过期逻辑）。"""
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        monkeypatch.setattr(
            image_mod.comfy_api, "generate_image", AsyncMock(return_value="job-x")
        )

        task = make_task()
        task.status = "queued"
        await task.enqueue_task(fake_redis)

        await image_mod.process_task(task)

        assert task.status == "submitted"
        assert task.task_id not in image_mod._stall_track


# ---- 2. [seed:N] 选项 ----


class TestSeedOption:
    def test_seed_parsed(self):
        prompt, options = image_mod.PromptProcessor.parse_options("[seed:42] 橘猫")
        assert prompt == "橘猫"
        assert options["seed"] == 42

    def test_seed_max_value(self):
        _, options = image_mod.PromptProcessor.parse_options(f"[seed:{0xFFFFFFFFFFFFFFFF}] 橘猫")
        assert options["seed"] == 0xFFFFFFFFFFFFFFFF

    def test_seed_out_of_range_ignored(self):
        _, options = image_mod.PromptProcessor.parse_options("[seed:-1] 橘猫")
        assert "seed" not in options
        _, options = image_mod.PromptProcessor.parse_options(f"[seed:{0xFFFFFFFFFFFFFFFF + 1}] 橘猫")
        assert "seed" not in options

    def test_seed_invalid_ignored(self):
        _, options = image_mod.PromptProcessor.parse_options("[seed:abc] 橘猫")
        assert "seed" not in options

    def test_no_seed_by_default(self):
        _, options = image_mod.PromptProcessor.parse_options("橘猫")
        assert "seed" not in options

    async def test_user_seed_passed_to_workflow(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        """用户指定的 seed 不被 setdefault 覆盖，原样传给工作流。"""
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        gen = AsyncMock(return_value="job-x")
        monkeypatch.setattr(image_mod.comfy_api, "generate_image", gen)

        task = make_task(seed=12345)
        task.options.pop("seed")  # make_task 的 seed 在 options 里，重新设置
        task.options["seed"] = 12345
        await task.enqueue_task(fake_redis)

        await image_mod.process_task(task)

        assert gen.call_args.kwargs["seed"] == 12345
        assert task.options["seed"] == 12345


# ---- 5. FIFO 按 created_at 排序 ----


async def test_all_tasks_sorted_by_created_at(fake_redis):
    """scan_iter 顺序随机，all_tasks 必须按创建时间升序返回（先来先做）。"""
    import datetime as dt

    t1 = make_task()
    t1.task_id = "task-old"
    t1.created_at = (dt.datetime.now() - dt.timedelta(seconds=100)).timestamp()
    t2 = make_task()
    t2.task_id = "task-new"
    t2.created_at = dt.datetime.now().timestamp()

    # 故意先写新任务
    await t2.enqueue_task(fake_redis)
    await t1.enqueue_task(fake_redis)

    tasks = await image_mod.Task.all_tasks(fake_redis)

    assert [t.task_id for t in tasks] == ["task-old", "task-new"]


# ---- 6. HTTP 轮询节流 ----


class TestPollThrottle:
    async def test_throttled_when_not_due(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        """未到轮询时间时不发 HTTP 请求，任务状态保持不变。"""
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        job_status = AsyncMock(return_value={"status": "running"})
        monkeypatch.setattr(image_mod.comfy_api, "job_status", job_status)
        monkeypatch.setattr(image_mod.comfy_api.progress_tracker, "snapshot", lambda job_id: None)

        task = make_task()
        task.status = "submitted"
        await task.enqueue_task(fake_redis)

        # 第一次：立即轮询
        await image_mod.process_task(task)
        assert job_status.call_count == 1

        # 第二次：间隔未到（submitted 间隔 2s），跳过 HTTP
        await image_mod.process_task(task)
        assert job_status.call_count == 1

    async def test_polls_again_after_interval(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        """超过间隔后恢复轮询。"""
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        job_status = AsyncMock(return_value={"status": "pending", "position": 1})
        monkeypatch.setattr(image_mod.comfy_api, "job_status", job_status)

        task = make_task()
        task.status = "submitted"
        await task.enqueue_task(fake_redis)
        image_mod._poll_schedule[task.task_id] = time.monotonic() - 0.1  # 已过期的节流

        await image_mod.process_task(task)
        assert job_status.call_count == 1
        # 节流已刷新到未来
        assert image_mod._poll_schedule[task.task_id] > time.monotonic()

    async def test_running_throttled_still_updates_progress(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        """running 被节流时仍用 WS 快照刷新进度显示。"""
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        job_status = AsyncMock(return_value={"status": "running"})
        monkeypatch.setattr(image_mod.comfy_api, "job_status", job_status)
        monkeypatch.setattr(
            image_mod.comfy_api.progress_tracker, "snapshot",
            lambda job_id: {"value": 6, "max": 8, "node": "3"},
        )

        task = make_task()
        task.status = "running"
        await task.enqueue_task(fake_redis)
        image_mod._poll_schedule[task.task_id] = time.monotonic() + 100  # 节流中

        await image_mod.process_task(task)

        job_status.assert_not_called()
        # 进度编辑仍被调度（P2）
        fake_dispatcher.submit_progress_edit.assert_called_once()


# ---- 7. 合并后的统一状态机 ----


class TestActiveTaskHandler:
    async def test_submitted_to_pending_shows_position(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        monkeypatch.setattr(
            image_mod.comfy_api, "job_status",
            AsyncMock(return_value={"status": "pending", "position": 2}),
        )

        task = make_task()
        task.status = "submitted"
        await task.enqueue_task(fake_redis)

        await image_mod.handle_active_task(task, "http://comfy", "test", fake_redis)

        assert task.status == "pending"
        text = fake_dispatcher.submit_edit.call_args[0][2]
        assert "第 2 位" in text

    async def test_submitted_to_running_shows_generating(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        monkeypatch.setattr(
            image_mod.comfy_api, "job_status", AsyncMock(return_value={"status": "running"})
        )
        monkeypatch.setattr(image_mod.comfy_api.progress_tracker, "snapshot", lambda job_id: None)

        task = make_task()
        task.status = "submitted"
        await task.enqueue_task(fake_redis)

        await image_mod.handle_active_task(task, "http://comfy", "test", fake_redis)

        assert task.status == "running"
        text = fake_dispatcher.submit_edit.call_args[0][2]
        assert "生成中" in text

    async def test_poll_errors_escalate_to_not_found(self, mock_manager, fake_redis, fake_dispatcher, monkeypatch):
        """连续 MAX_POLL_ERRORS 次 API 错误才置 not_found（网络抖动不误杀）。"""
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        monkeypatch.setattr(
            image_mod.comfy_api, "job_status",
            AsyncMock(side_effect=image_mod.comfy_api.ComfyAPIError("boom")),
        )

        task = make_task()
        task.status = "submitted"
        await task.enqueue_task(fake_redis)

        for _ in range(image_mod.MAX_POLL_ERRORS - 1):
            await image_mod.handle_active_task(task, "http://comfy", "test", fake_redis)
            image_mod._poll_schedule.pop(task.task_id, None)  # 跳过节流
            assert task.status == "submitted"

        await image_mod.handle_active_task(task, "http://comfy", "test", fake_redis)
        assert task.status == "not_found"

    async def test_no_job_id_completes_task(self, mock_manager, fake_redis, fake_dispatcher):
        mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}
        task = make_task()
        task.status = "submitted"
        task.job_id = None

        await image_mod.handle_active_task(task, "http://comfy", "test", fake_redis)
        assert task.status == "completed"


class TestModelDefaultSize:
    """未显式指定尺寸时按模型取默认（qwen 0.6MP），显式 size 优先。"""

    def test_qwen_default_size_without_options(self):
        _, options = image_mod.PromptProcessor.parse_options("橘猫")
        assert options["size"] == "576x1024"

    def test_qwen_default_size_with_other_options(self):
        _, options = image_mod.PromptProcessor.parse_options("[model:qwen raw] 橘猫")
        assert options["size"] == "576x1024"

    def test_explicit_size_wins(self):
        _, options = image_mod.PromptProcessor.parse_options("[size:1024x1024] 橘猫")
        assert options["size"] == "1024x1024"

    def test_other_models_keep_global_default(self):
        _, options = image_mod.PromptProcessor.parse_options("[model:zimage] 橘猫")
        assert options["size"] == "836x1216"
