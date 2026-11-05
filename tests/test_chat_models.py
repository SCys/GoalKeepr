"""/chat 预设模型表与多模态输入测试。"""

from unittest.mock import AsyncMock, patch

from orjson import loads

import handlers.utils.txt as txt_mod
from handlers.utils.txt import DEFAULT_MODEL, SUPPORTED_MODELS


def test_supported_models_preset():
    """预设模型：统一 128k 输入 / 32k 输出，均声明图文与视频支持；simple 为默认。"""
    assert set(SUPPORTED_MODELS) == {"simple", "gemini-3.8-flash", "deepseek-flash", "qwen3.6-flash"}
    for desc in SUPPORTED_MODELS.values():
        assert desc.input_length == 128000
        assert desc.output_length == 32768
        assert "image" in desc.media
        assert "video" in desc.media
    assert DEFAULT_MODEL == "simple"


async def test_tg_generate_text_with_media(mock_manager, fake_redis, monkeypatch):
    """带附件时：请求的最后一条用户消息为多模态 content，历史只存纯文本占位。"""
    mock_manager.config["ai"] = {"proxy_host": "http://proxy", "proxy_token": "t"}
    captured = {}

    async def fake_api(url, data, token):
        captured["data"] = data
        return {"choices": [{"message": {"content": "看到了一只猫"}}]}

    monkeypatch.setattr(txt_mod, "_api_request", fake_api)

    out = await txt_mod.tg_generate_text(
        1, 2, "看图说话",
        media=[("image", "data:image/jpeg;base64,AA"), ("video", "data:video/mp4;base64,BB")],
    )

    assert "看到了一只猫" in out
    data = captured["data"]
    assert data["model"] == DEFAULT_MODEL
    assert data["max_tokens"] == 32768

    last = data["messages"][-1]["content"]
    assert [p["type"] for p in last] == ["text", "image_url", "video_url"]
    assert last[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert last[2]["video_url"]["url"].startswith("data:video/mp4;base64,")

    # 存入 Redis 的历史必须是纯文本（含占位符），不能带 base64
    history = loads(await fake_redis.get("chat:history:2"))
    assert all(isinstance(m["content"], str) for m in history)
    user_entry = [m for m in history if m["role"] == "user"][0]
    assert "[图片]" in user_entry["content"] and "[视频]" in user_entry["content"]


async def test_tg_generate_text_plain_text_unchanged(mock_manager, fake_redis, monkeypatch):
    """无附件时保持纯文本 content。"""
    mock_manager.config["ai"] = {"proxy_host": "http://proxy", "proxy_token": "t"}
    captured = {}

    async def fake_api(url, data, token):
        captured["data"] = data
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(txt_mod, "_api_request", fake_api)

    await txt_mod.tg_generate_text(1, 2, "你好")

    last = captured["data"]["messages"][-1]["content"]
    assert isinstance(last, str)


async def test_unknown_model_falls_back_to_conservative_limits(mock_manager, fake_redis, monkeypatch):
    """未列入预设的模型名：128k 输入 + 4096 输出 + 原始名展示。"""
    mock_manager.config["ai"] = {"proxy_host": "http://proxy", "proxy_token": "t",
                                 "chat_model": "some-new-model"}
    captured = {}

    async def fake_api(url, data, token):
        captured["data"] = data
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(txt_mod, "_api_request", fake_api)

    out = await txt_mod.tg_generate_text(1, 2, "你好")

    assert captured["data"]["model"] == "some-new-model"
    assert captured["data"]["max_tokens"] == 4096
    assert "some-new-model" in out  # Powered by 原始名


async def test_chat_reset_uses_current_utc_for_deletion(mock_manager, fake_redis):
    """Verify /chat reset calculates deletion time from current UTC, not stale event.date."""
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    from handlers.commands.chat.func_chat import chat

    stale_date = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    event = SimpleNamespace(
        chat_id=-1001,
        id=10,
        text="/chat reset",
        date=stale_date,
        is_reply=False,
        message=None,
        get_chat=AsyncMock(return_value=SimpleNamespace(id=-1001)),
        get_sender=AsyncMock(return_value=SimpleNamespace(id=999, first_name="U")),
        get_reply_message=AsyncMock(return_value=None),
        reply=AsyncMock(return_value=SimpleNamespace(id=101)),
    )
    mock_manager.get_redis = AsyncMock(return_value=fake_redis)
    await fake_redis.set("chat:history:999", "some_history")

    with patch.object(mock_manager, "reply", new=AsyncMock()) as mock_reply:
        await chat(event)
        mock_reply.assert_awaited_once()
        auto_del = mock_reply.await_args.kwargs.get("auto_deleted_at")
        assert auto_del is not None
        assert auto_del > datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert await fake_redis.get("chat:history:999") is None
    mock_manager.delete_message.assert_awaited()
    auto_del = mock_manager.delete_message.await_args.args[2]
    assert auto_del is not None
    assert auto_del > datetime(2026, 1, 1, tzinfo=timezone.utc)


async def test_translate_uses_to_thread(mock_manager, monkeypatch):
    """Verify translate calls ts.translate_text asynchronously via asyncio.to_thread."""
    import asyncio
    import sys
    from unittest.mock import MagicMock, patch
    from types import SimpleNamespace
    from datetime import datetime, timezone

    # pydub requires audioop which was removed in Python 3.14
    monkeypatch.setitem(sys.modules, "pydub", MagicMock())
    monkeypatch.setitem(sys.modules, "pydub.audio_segment", MagicMock())
    monkeypatch.setitem(sys.modules, "utils.tts", MagicMock())

    from handlers.commands.translate import translate

    thread_called = False

    async def spy_to_thread(func, *args, **kwargs):
        nonlocal thread_called
        thread_called = True
        return "你好世界"

    monkeypatch.setattr(asyncio, "to_thread", spy_to_thread)

    event = SimpleNamespace(
        id=10,
        text="/tr Hello world",
        date=datetime.now(timezone.utc),
        is_reply=False,
        reply_to_msg_id=None,
        get_sender=AsyncMock(return_value=SimpleNamespace(id=999, first_name="U")),
        respond=AsyncMock(),
    )

    with patch("handlers.commands.translate.reply_tts", new=AsyncMock()) as mock_tts:
        await translate(event)
        assert thread_called is True
        mock_tts.assert_awaited_once()


async def test_tg_generate_text_extracts_reasoning_content(mock_manager, fake_redis, monkeypatch):
    """Verify tg_generate_text extracts reasoning_content and preserves clean text in Redis."""
    mock_manager.config["ai"] = {"proxy_host": "http://proxy", "proxy_token": "t"}

    async def fake_api(url, data, token):
        return {
            "choices": [{
                "message": {
                    "content": "42 is the answer",
                    "reasoning_content": "Deep thought computed for 7.5 million years",
                }
            }]
        }

    monkeypatch.setattr(txt_mod, "_api_request", fake_api)

    resp = await txt_mod.tg_generate_text(1, 100, "What is the answer?")
    assert "42 is the answer" in resp
    assert resp.reasoning == "Deep thought computed for 7.5 million years"

    # Verify Redis stores clean content only
    history = loads(await fake_redis.get("chat:history:100"))
    assert history[-1]["content"] == "42 is the answer"


async def test_tg_generate_text_extracts_think_tag(mock_manager, fake_redis, monkeypatch):
    """Verify tg_generate_text extracts think tags when reasoning_content is absent."""
    mock_manager.config["ai"] = {"proxy_host": "http://proxy", "proxy_token": "t"}

    async def fake_api(url, data, token):
        tag_open = chr(60) + "think" + chr(62)
        tag_close = chr(60) + "/think" + chr(62)
        return {
            "choices": [{
                "message": {
                    "content": tag_open + "\nAnalyzing numbers...\n" + tag_close + "\n\n9.8 is larger than 9.11",
                }
            }]
        }

    monkeypatch.setattr(txt_mod, "_api_request", fake_api)

    resp = await txt_mod.tg_generate_text(1, 101, "Compare 9.11 and 9.8")
    assert "9.8 is larger than 9.11" in resp
    assert resp.reasoning == "Analyzing numbers..."

    history = loads(await fake_redis.get("chat:history:101"))
    assert history[-1]["content"] == "9.8 is larger than 9.11"


async def test_reply_response_rich_message_with_thinking(mock_manager):
    """Verify _reply_response sends rich message with expandable blockquote for thinking."""
    from types import SimpleNamespace
    from handlers.commands.chat.func_chat import _reply_response

    mock_manager.config["telegram"] = {"token": "dummy_token"}
    event = SimpleNamespace(
        chat_id=12345,
        id=777,
        reply=AsyncMock(),
    )

    sent_payloads = []

    class FakeResponse:
        status = 200
        async def json(self):
            return {"ok": True, "result": {"message_id": 888}}

    class FakeSession:
        def post(self, url, json=None, **kwargs):
            sent_payloads.append((url, json))
            class Context:
                async def __aenter__(self):
                    return FakeResponse()
                async def __aexit__(self, *args):
                    pass
            return Context()

    mock_manager.create_session = AsyncMock(return_value=FakeSession())

    success = await _reply_response(
        event,
        "Here is the result.",
        "prefix",
        reasoning="Step by step calculation",
    )
    assert success is True
    assert len(sent_payloads) == 1
    url, payload = sent_payloads[0]
    assert "sendRichMessage" in url
    assert payload["chat_id"] == 12345
    assert payload["reply_parameters"] == {"message_id": 777}
    html = payload["rich_message"]["html"]
    assert "<blockquote expandable>" in html
    assert "Step by step calculation" in html
    assert "Here is the result." in html


async def test_reply_response_fallback_to_send_message(mock_manager):
    """Verify _reply_response falls back to sendMessage when sendRichMessage fails."""
    from types import SimpleNamespace
    from handlers.commands.chat.func_chat import _reply_response

    mock_manager.config["telegram"] = {"token": "dummy_token"}
    event = SimpleNamespace(
        chat_id=12345,
        id=777,
        reply=AsyncMock(),
    )

    calls = []

    class FakeSession:
        def post(self, url, json=None, **kwargs):
            calls.append((url, json))
            class Context:
                async def __aenter__(self):
                    if "sendRichMessage" in url:
                        resp = SimpleNamespace(status=400, json=AsyncMock(return_value={"ok": False, "description": "unsupported"}))
                    else:
                        resp = SimpleNamespace(status=200, json=AsyncMock(return_value={"ok": True, "result": {"message_id": 999}}))
                    return resp
                async def __aexit__(self, *args):
                    pass
            return Context()

    mock_manager.create_session = AsyncMock(return_value=FakeSession())

    success = await _reply_response(
        event,
        "Fallback answer.",
        "prefix",
        reasoning="Some reasoning",
    )
    assert success is True
    assert len(calls) == 2
    assert "sendRichMessage" in calls[0][0]
    assert "sendMessage" in calls[1][0]
    assert "**Thinking Process:**" in calls[1][1]["text"]
    assert "Fallback answer." in calls[1][1]["text"]
