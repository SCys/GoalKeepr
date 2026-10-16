"""/chat 预设模型表与多模态输入测试。"""

from unittest.mock import AsyncMock

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
