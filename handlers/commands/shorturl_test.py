import pytest

from .shorturl import shorturl

pytestmark = pytest.mark.asyncio


async def test_shorturl(event_loop):
    shorted = await shorturl("http://1dot1dot1dot1.cloudflare-dns.com")
    assert shorted is not None, "shorted is None"
    assert isinstance(shorted, str), "shorted is not a string"
    assert shorted.startswith("http"), "shorted is not a url"
