import pytest

import handlers.commands.shorturl as shorturl_module

pytestmark = pytest.mark.asyncio


class FakeResponse:
    status = 200
    reason = "OK"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return {
            "data": {
                "code": "abc123",
                "expired": "2026-07-08T00:00:00Z",
                "url": "https://short.example/abc123",
            }
        }


class FakeSession:
    def post(self, *args, **kwargs):
        return FakeResponse()


async def test_shorturl(monkeypatch):
    async def create_session():
        return FakeSession()

    monkeypatch.setattr(shorturl_module.manager, "create_session", create_session)

    shorted = await shorturl_module.shorturl("http://1dot1dot1dot1.cloudflare-dns.com")

    assert shorted == "https://short.example/abc123"
