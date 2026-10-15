"""image 模块进度渲染与限速调度的纯逻辑测试（不依赖 Telegram/Redis/ComfyUI）。"""

import time
from datetime import datetime

import pytest

from handlers.commands.image import (
    OutboundDispatcher,
    Task,
    TaskMessage,
    build_caption,
    render_progress_bar,
    render_status_message,
    should_update_progress,
    PROGRESS_BAR_LEN,
)


def make_task(**options) -> Task:
    opts = {"size": "836x1216", "step": 16, "model": "zimage", "cfg": 1}
    opts.update(options)
    return Task(
        msg=TaskMessage(
            chat_id=1001,
            chat_name="TestChat",
            user_id=2002,
            user_name="tester",
            message_id=10,
            reply_message_id=11,
            reply_content="a cat on the moon",
        ),
        prompt="a cat on the moon",
        options=opts,
        created_at=datetime.now().timestamp(),
        status="queued",
        job_id="job-1",
        task_id="task-1",
    )


class TestProgressBar:
    def test_zero(self):
        assert render_progress_bar(0) == "░" * PROGRESS_BAR_LEN

    def test_full(self):
        assert render_progress_bar(100) == "█" * PROGRESS_BAR_LEN

    def test_half(self):
        bar = render_progress_bar(50)
        assert bar.count("█") == PROGRESS_BAR_LEN // 2
        assert len(bar) == PROGRESS_BAR_LEN

    def test_clamp(self):
        assert render_progress_bar(150) == "█" * PROGRESS_BAR_LEN
        assert render_progress_bar(-5) == "░" * PROGRESS_BAR_LEN


class TestStatusMessage:
    def test_queued_with_position(self):
        text = render_status_message(make_task(), "queued", position=2)
        assert "第 2 位" in text
        assert "> Queued, position 2." in text
        assert "zimage" in text
        assert "a cat on the moon" in text

    def test_running_with_progress(self):
        text = render_status_message(
            make_task(), "running",
            progress={"value": 8, "max": 16, "node": "3"},
            elapsed=12.0,
        )
        assert "50%" in text
        assert "步骤 8/16" in text
        assert "预计剩余" in text
        assert "> Generating... step 8/16" in text

    def test_running_degraded_notice(self):
        text = render_status_message(make_task(), "running", degraded=True)
        assert "限速" in text

    def test_failed_with_error(self):
        text = render_status_message(make_task(), "failed", elapsed=45.2, error="boom")
        assert "❌" in text
        assert "45.2s" in text
        assert "> boom" in text

    def test_delivering(self):
        text = render_status_message(make_task(), "delivering")
        assert "📦" in text


class TestCaption:
    def test_contains_seed_and_model(self):
        caption = build_caption(make_task(seed=42, model="flux"))
        assert "seed 42" in caption
        assert "flux" in caption

    def test_truncation(self):
        caption = build_caption(make_task())
        assert len(caption) <= 1023


class TestProgressThrottle:
    def test_silent_level_blocks_all(self):
        assert should_update_progress({}, 50, time.monotonic(), level=2) is False

    def test_interval_gate(self):
        now = time.monotonic()
        state = {"last_edit": now - 1.0, "last_pct": 0.0}
        # level 0 间隔 3s，1s 前刚编辑过 → 拒绝
        assert should_update_progress(state, 50, now, level=0) is False

    def test_threshold_gate(self):
        now = time.monotonic()
        state = {"last_edit": now - 10.0, "last_pct": 40.0}
        # 间隔足够但变化只有 5%（< 10% 阈值）→ 拒绝
        assert should_update_progress(state, 45.0, now, level=0) is False

    def test_pass(self):
        now = time.monotonic()
        state = {"last_edit": now - 10.0, "last_pct": 0.0}
        assert should_update_progress(state, 50.0, now, level=0) is True

    def test_degraded_needs_bigger_step(self):
        now = time.monotonic()
        state = {"last_edit": now - 11.0, "last_pct": 0.0}
        # level 1 阈值 25%，变化 20% → 拒绝；level 0 阈值 10% → 通过
        assert should_update_progress(state, 20.0, now, level=1) is False
        assert should_update_progress(state, 20.0, now, level=0) is True


class TestDispatcherDegrade:
    def test_flood_escalates_and_caps(self):
        d = OutboundDispatcher()
        assert d.degrade_level == 0
        d.on_flood(5)
        assert d.degrade_level == 1
        assert d._blocked_until > time.monotonic()
        d.on_flood(5)
        assert d.degrade_level == 2
        d.on_flood(5)
        assert d.degrade_level == 2  # 封顶

    def test_recovery_steps_down(self):
        d = OutboundDispatcher()
        d.on_flood(5)
        d.on_flood(5)
        assert d.degrade_level == 2
        # 模拟 60s 无撞墙
        d._last_flood_at = time.monotonic() - 61
        d.maybe_recover()
        assert d.degrade_level == 1
        d._last_flood_at = time.monotonic() - 61
        d.maybe_recover()
        assert d.degrade_level == 0

    def test_progress_edit_dropped_when_silent(self):
        d = OutboundDispatcher()
        d.degrade_level = 2
        # 静默级别下 P2 编辑应直接返回，不入队
        import asyncio

        async def _run():
            await d.submit_progress_edit(1, 1, lambda: "text")
            assert d._queue.empty()

        asyncio.run(_run())
