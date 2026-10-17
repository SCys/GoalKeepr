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


# ---- /image 访问控制 ----


class TestImagePermission:
    def _parse(self, users="", groups=""):
        from configparser import ConfigParser

        c = ConfigParser()
        c["image"] = {"users": users, "groups": groups}
        return image_mod.PermissionManager.parse_user_groups_config(c)

    def test_groups_keep_negative_ids(self):
        """群组 ID 是负数，过滤时必须保留（回归：i>0 曾把所有群组 ID 过滤掉）。"""
        users, groups = self._parse(users="123,456", groups="-1001085650365,-100999")
        assert users == [123, 456]
        assert groups == [-1001085650365, -100999]

    def test_invalid_values_dropped(self):
        users, groups = self._parse(users="0,-5", groups="0,123")
        assert users == []
        assert groups == []

    def test_empty_config_denies_everyone(self):
        users, groups = self._parse()
        assert not image_mod.PermissionManager.check_permission(1, -100, users, groups)

    def test_user_or_group_match(self):
        users, groups = self._parse(users="123", groups="-1001085650365")
        assert image_mod.PermissionManager.check_permission(123, -999, users, groups)
        assert image_mod.PermissionManager.check_permission(999, -1001085650365, users, groups)
        assert not image_mod.PermissionManager.check_permission(999, -100999, users, groups)

    def test_bare_supergroup_id_matches_prefixed_chat(self):
        """配置写裸 ID（-5232001169），事件里 chat_id 带 -100 前缀也必须匹配。

        回归：超级群 ID 超过 2^31 时 Telegram 事件里是 -100<裸ID>，
        直接精确匹配会导致白名单里的群被判无权。
        """
        users, groups = self._parse(groups="-5232001169")
        assert image_mod.PermissionManager.check_permission(999, -1005232001169, users, groups)

    def test_prefixed_config_matches_bare_or_prefixed_chat(self):
        """配置带 -100 前缀时，两种形式的 chat_id 都能匹配。"""
        users, groups = self._parse(groups="-1005232001169")
        assert image_mod.PermissionManager.check_permission(999, -5232001169, users, groups)
        assert image_mod.PermissionManager.check_permission(999, -1005232001169, users, groups)

    def test_normalization_does_not_match_other_groups(self):
        users, groups = self._parse(groups="-5232001169")
        assert not image_mod.PermissionManager.check_permission(999, -1009998888, users, groups)
        assert not image_mod.PermissionManager.check_permission(999, -5232001170, users, groups)


# ---- /image 提示词优化 ----


class TestPromptOptimize:
    async def test_optimize_returns_llm_result(self, monkeypatch):
        mock_chat = AsyncMock(return_value="一只橘猫趴在窗台，午后阳光，电影感")
        monkeypatch.setattr(image_mod, "chat_completions", mock_chat)

        optimized, reply = await image_mod.PromptProcessor.optimize_prompt("橘猫")

        assert optimized == "一只橘猫趴在窗台，午后阳光，电影感"
        assert reply == optimized
        # 默认第一个模型是 simple（代理端 combo）
        assert mock_chat.call_args.kwargs["model_name"] == "simple"
        # system prompt 已换成通用版
        sys_msg = mock_chat.call_args.args[0][0]["content"]
        assert "文生图提示词优化专家" in sys_msg

    async def test_optimize_skips_comma_prompts(self, monkeypatch):
        """含英文逗号视为用户已细化，不调用 LLM。"""
        mock_chat = AsyncMock()
        monkeypatch.setattr(image_mod, "chat_completions", mock_chat)

        optimized, _ = await image_mod.PromptProcessor.optimize_prompt("a cat, cinematic")

        assert optimized == "a cat, cinematic"
        mock_chat.assert_not_called()

    async def test_optimize_falls_back_to_next_model(self, monkeypatch):
        """第一个模型失败时依次尝试 fallback 模型，全失败返回原文。"""
        calls = []

        async def flaky(messages, model_name=None):
            calls.append(model_name)
            if model_name == "simple":
                raise RuntimeError("boom")
            return "优化后"

        monkeypatch.setattr(image_mod, "chat_completions", flaky)

        optimized, _ = await image_mod.PromptProcessor.optimize_prompt("橘猫")

        assert optimized == "优化后"
        assert calls == ["simple", "deepseek-flash"]


class TestParseOptionsRaw:
    def test_raw_option(self):
        _, options = image_mod.PromptProcessor.parse_options("[raw] 橘猫")
        assert options.get("raw") is True

    def test_no_raw_by_default(self):
        _, options = image_mod.PromptProcessor.parse_options("橘猫")
        assert not options.get("raw")

    def test_raw_with_other_options(self):
        prompt, options = image_mod.PromptProcessor.parse_options("[raw model:krea size:small] a cat")
        assert prompt == "a cat"
        assert options["raw"] is True
        assert options["model"] == "krea"
        # 旧版 size:small 预设换算为 mp + 比例
        assert options["mp"] == 0.59
        assert options["ratio"] == "1:1"


# ---- /image 命令 handler：入队必须带正确的状态消息 id ----


async def test_image_handler_enqueues_task_with_reply_id(mock_manager, fake_redis, monkeypatch):
    """任务入队时 reply_message_id 必须是排队消息的 id。

    回归：旧流程"入队 → 回复 → 二次入队"存在竞态，worker 读到
    reply_message_id=-1 的旧版本会覆盖回 Redis，状态消息永远卡在"排队中"。
    """
    from types import SimpleNamespace as NS

    mock_manager.config["image"] = {"users": "2002", "groups": ""}
    monkeypatch.setattr(image_mod, "chat_completions", AsyncMock(return_value="优化后的提示词"))

    event = NS(
        chat_id=1001,
        id=10,
        text="/image 橘猫",
        get_chat=AsyncMock(return_value=NS(title="TestChat")),
        get_sender=AsyncMock(return_value=NS(id=2002, username="tester", first_name="tester", last_name=None)),
        get_reply_message=AsyncMock(return_value=None),
        reply=AsyncMock(return_value=NS(id=555)),
    )

    await image_mod.image(event)

    tasks = await image_mod.Task.all_tasks(fake_redis)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.msg.reply_message_id == 555
    assert task.status == "queued"
    assert task.prompt == "优化后的提示词"


# ---- 优化器拒绝文案兜底 ----


class TestOptimizeRefusal:
    def test_looks_like_refusal(self):
        assert image_mod.looks_like_refusal("抱歉，我无法生成涉及未成年人性化内容的提示词。")
        assert image_mod.looks_like_refusal("Sorry, I cannot help with that.")
        assert image_mod.looks_like_refusal("长" * 900)  # 超长视为解释/拒绝长文
        assert not image_mod.looks_like_refusal("一只橘猫趴在窗台，午后阳光，电影感")
        assert not image_mod.looks_like_refusal("a cat on the moon, cinematic lighting")

    async def test_refusal_falls_back_to_original(self, monkeypatch):
        """所有模型都输出拒绝文案时，必须原文提交（回归：拒绝文案曾被当提示词提交 ComfyUI）。"""
        monkeypatch.setattr(
            image_mod, "chat_completions",
            AsyncMock(return_value="抱歉，我无法生成涉及未成年人性化内容或违反安全政策的提示词。"),
        )

        optimized, reply = await image_mod.PromptProcessor.optimize_prompt("童颜巨乳")

        assert optimized == "童颜巨乳"
        assert reply == "童颜巨乳"

    async def test_refusal_tries_next_model(self, monkeypatch):
        """第一个模型拒绝时尝试 fallback 模型。"""
        calls = []

        async def picky(messages, model_name=None):
            calls.append(model_name)
            if model_name == "simple":
                return "抱歉，我无法处理这个描述。"
            return "一只橘猫趴在窗台，午后阳光"

        monkeypatch.setattr(image_mod, "chat_completions", picky)

        optimized, _ = await image_mod.PromptProcessor.optimize_prompt("橘猫")

        assert optimized == "一只橘猫趴在窗台，午后阳光"
        assert calls == ["simple", "deepseek-flash"]


# ---- 投递墓碑：僵尸 delivering 任务不得重复发图 ----


async def test_delivered_tombstone_blocks_zombie_redelivery(mock_manager, fake_redis, fake_dispatcher):
    """已有 done 墓碑的 delivering 任务直接出队，不进入投递流程。

    回归：finalize_delivery 删键与 worker 旧副本回写存在竞态，复活的僵尸
    任务会从 ComfyUI 重下载图片并重复投递（同一张图发多次）。
    """
    mock_manager.config["sd_api"] = {"endpoint": "http://comfy"}

    task = make_task()
    task.status = "delivering"
    task.options["image_filename"] = "a.png"
    await task.enqueue_task(fake_redis)
    await fake_redis.set(f"image:done:{task.task_id}", "1", ex=3600)

    await image_mod.process_task(task)

    assert not await fake_redis.exists(f"image:{task.task_id}")
    fake_dispatcher.submit_delivery.assert_not_called()


async def test_finalize_delivery_writes_tombstone(mock_manager, fake_redis, fake_dispatcher):
    """投递成功收尾必须留下墓碑并清理任务与图片字节。"""
    task = make_task()
    await task.enqueue_task(fake_redis)
    await fake_redis.set(f"image:img:{task.task_id}", b"\x89PNG-binary")

    await image_mod.finalize_delivery(task, fake_redis)

    assert await fake_redis.exists(f"image:done:{task.task_id}")
    assert not await fake_redis.exists(f"image:{task.task_id}")
    assert not await fake_redis.exists(f"image:img:{task.task_id}")
    fake_dispatcher.submit_delete.assert_called_once()


async def test_all_tasks_ignores_done_keys(fake_redis):
    """done: 墓碑键不得混入任务队列解析。"""
    task = make_task()
    await task.enqueue_task(fake_redis)
    await fake_redis.set(f"image:done:{task.task_id}", "1", ex=3600)

    tasks = await image_mod.Task.all_tasks(fake_redis)

    assert len(tasks) == 1
    assert await fake_redis.exists(f"image:done:{task.task_id}")
