"""LLM 提示词优化的反馈时序与超时兜底回归测试。"""

import asyncio
import re
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

import handlers.commands.image as image_mod


async def test_queued_reply_sent_before_optimization(mock_manager, fake_redis, monkeypatch):
    """排队消息必须先于 LLM 优化发出——优化可能耗时数十秒，不能让用户干等。

    回归：旧流程"先优化再回复"，LLM 慢（HTTP 超时上限 180s × 重试）时
    命令发出后长时间毫无反馈（实测私聊 71s）。
    """
    mock_manager.config["image"] = {"users": "2002", "groups": ""}
    order = []

    async def slow_optimize(messages, model_name=None):
        order.append("optimize")
        return "优化后的提示词"

    monkeypatch.setattr(image_mod, "chat_completions", slow_optimize)

    async def reply_side_effect(text, **kw):
        order.append("reply")
        return NS(id=555)

    event = NS(
        chat_id=1001,
        id=10,
        text="/image 橘猫",
        get_chat=AsyncMock(return_value=NS(title="TestChat")),
        get_sender=AsyncMock(return_value=NS(id=2002, username="t", first_name="t", last_name=None)),
        get_reply_message=AsyncMock(return_value=None),
        reply=AsyncMock(side_effect=reply_side_effect),
    )

    await image_mod.image(event)

    assert order == ["reply", "optimize"]
    # 排队消息带"优化提示词"提示
    queued_text = event.reply.call_args[0][0]
    assert "正在优化提示词" in queued_text
    # 入队的任务已是优化后的提示词
    tasks = await image_mod.Task.all_tasks(fake_redis)
    assert tasks[0].prompt == "优化后的提示词"
    assert tasks[0].msg.reply_message_id == 555


async def test_optimize_timeout_falls_back(mock_manager, monkeypatch):
    """单模型优化超时（默认 30s）后换下一个模型，不无限等待。"""
    monkeypatch.setattr(image_mod, "OPTIMIZE_TIMEOUT", 0.05)
    calls = []

    async def slow_first(messages, model_name=None):
        calls.append(model_name)
        if model_name == "simple":
            await asyncio.sleep(10)
            return "不该到达"
        return "优化后"

    monkeypatch.setattr(image_mod, "chat_completions", slow_first)

    optimized, _ = await image_mod.PromptProcessor.optimize_prompt("橘猫")

    assert optimized == "优化后"
    assert calls[0] == "simple"
    assert len(calls) >= 2


def test_queued_render_with_optimizing_note():
    from tests.test_image_progress import make_task

    text = image_mod.render_status_message(make_task(), "queued", position=1, optimizing=True)
    assert "正在优化提示词" in text
    assert "> Optimizing prompt" in text

    text = image_mod.render_status_message(make_task(), "queued", position=1)
    assert "正在优化提示词" not in text


class TestImageCmdPattern:
    """/image 注册正则：多行提示词与 @mention 必须命中。

    回归：旧 pattern `(?i)^/image(?: .*)?$` 的 `.` 不匹配换行，
    多行长文本命令被静默忽略（handler 根本没触发）。
    """

    @pytest.mark.parametrize(
        "text",
        [
            "/image 橘猫",
            "/image",
            "/image@muteditbot 橘猫",
            "/image [mp:1.0] 橘猫",
            "/image 一只橘猫\n趴在窗台上\n阳光洒落",  # 多行长文本
            "/image 第一行\n\n第三行",
            "/IMAGE 大写也可以",
        ],
    )
    def test_pattern_matches(self, text):
        assert re.match(image_mod.IMAGE_CMD_PATTERN, text)

    @pytest.mark.parametrize(
        "text",
        [
            "/imageabc 橘猫",   # 前缀粘连不命中
            "/img 橘猫",        # 其他命令不命中
            "前缀 /image 橘猫",  # 命令必须在行首
        ],
    )
    def test_pattern_rejects(self, text):
        assert not re.match(image_mod.IMAGE_CMD_PATTERN, text)

    def test_multiline_prompt_extracted(self):
        """多行提示词经 strip_text_prefix 后保留换行内容。"""
        from handlers.utils import strip_text_prefix

        assert strip_text_prefix("/image 一只橘猫\n趴在窗台上") == "一只橘猫\n趴在窗台上"
