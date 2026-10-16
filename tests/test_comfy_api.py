"""comfy_api.job_status 状态判定测试（mock HTTP 层，不依赖真实 ComfyUI）。"""

from unittest.mock import AsyncMock

import pytest

import utils.comfy_api as comfy_api


class FakeResp:
    def __init__(self, status, payload=None):
        self.status = status
        self._payload = payload or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self._payload


class FakeSession:
    """按 URL 关键字路由到预设响应。"""

    def __init__(self, routes):
        self._routes = routes

    def get(self, url, timeout=None):
        for key, resp in self._routes.items():
            if key in url:
                return resp
        raise AssertionError(f"unexpected url: {url}")


def _patch_session(monkeypatch, session):
    monkeypatch.setattr(comfy_api.manager, "create_session", AsyncMock(return_value=session))


async def test_job_status_queue_http_error_raises_not_not_found(monkeypatch):
    """/queue 非 200 时必须抛 ComfyAPIError（走 poll_errors 宽限），不得误判 not_found。

    回归：并发提交时一次瞬时 500 就把健康任务判成"远端任务丢失"。
    """
    session = FakeSession({
        "/history/": FakeResp(200, {}),
        "/queue": FakeResp(500),
    })
    _patch_session(monkeypatch, session)

    with pytest.raises(comfy_api.ComfyAPIError):
        await comfy_api.job_status("http://comfy", "job-x")


async def test_job_status_true_not_found(monkeypatch):
    """history 和 queue 都查询成功且都没有该任务，才判 not_found。"""
    session = FakeSession({
        "/history/": FakeResp(200, {}),
        "/queue": FakeResp(200, {"queue_running": [], "queue_pending": []}),
    })
    _patch_session(monkeypatch, session)

    result = await comfy_api.job_status("http://comfy", "job-x")
    assert result["status"] == "not_found"


async def test_job_status_pending_and_running(monkeypatch):
    item = [1, "job-x", {}, {}, "client"]
    session = FakeSession({
        "/history/": FakeResp(200, {}),
        "/queue": FakeResp(200, {"queue_running": [], "queue_pending": [[0, "other"], item]}),
    })
    _patch_session(monkeypatch, session)

    result = await comfy_api.job_status("http://comfy", "job-x")
    assert result["status"] == "pending"
    assert result["position"] == 2

    session._routes["/queue"] = FakeResp(200, {"queue_running": [item], "queue_pending": []})
    result = await comfy_api.job_status("http://comfy", "job-x")
    assert result["status"] == "running"


async def test_job_status_completed_from_history(monkeypatch):
    session = FakeSession({
        "/history/": FakeResp(200, {"job-x": {"status": {"status_str": "success"}}}),
    })
    _patch_session(monkeypatch, session)

    result = await comfy_api.job_status("http://comfy", "job-x")
    assert result["status"] == "completed"
