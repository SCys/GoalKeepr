"""
Shared test fixtures: FakeRedis, mock manager, and helper factories.
"""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest


class FakeRedis:
    """In-memory Redis mock implementing the subset of commands used by the codebase.

    Methods return the same types as redis-py (bytes for values, int for counts, etc.)
    so that production code paths exercise real type-coercion logic.
    """

    def __init__(self):
        self._data: dict[str, Any] = {}
        self._hashes: dict[str, dict[Any, Any]] = {}
        self._sets: dict[str, set[str]] = {}
        self._sorted_sets: dict[str, dict[Any, float]] = {}
        self._expiry: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict(self):
        now = time.time()
        stale = [k for k, t in self._expiry.items() if t <= now]
        for k in stale:
            self._data.pop(k, None)
            self._hashes.pop(k, None)
            self._sets.pop(k, None)
            self._sorted_sets.pop(k, None)
            del self._expiry[k]

    def _norm_key(self, key: Any) -> str:
        return key.decode() if isinstance(key, bytes) else str(key)

    # ------------------------------------------------------------------
    # Generic key-value
    # ------------------------------------------------------------------

    async def get(self, key):
        self._evict()
        return self._data.get(self._norm_key(key))

    async def set(self, key, value, nx=False, ex=None):
        self._evict()
        k = self._norm_key(key)
        if nx and k in self._data:
            return None
        self._data[k] = value
        if ex:
            self._expiry[k] = time.time() + ex
        return "OK"

    async def exists(self, key):
        self._evict()
        k = self._norm_key(key)
        return k in self._data or k in self._hashes or k in self._sets or k in self._sorted_sets

    async def delete(self, *keys):
        self._evict()
        count = 0
        for key in keys:
            k = self._norm_key(key)
            for store in (self._data, self._hashes, self._sets, self._sorted_sets):
                if k in store:
                    del store[k]
                    count += 1
            self._expiry.pop(k, None)
        return count

    async def scan(self, cursor=0, match=None, count=10):
        self._evict()
        import fnmatch

        all_keys = list(self._data) + list(self._hashes) + list(self._sets) + list(self._sorted_sets)
        seen: set[str] = set()
        deduped: list[str] = []
        for k in all_keys:
            ks = self._norm_key(k)
            if ks not in seen:
                seen.add(ks)
                deduped.append(ks)
        if match:
            deduped = [k for k in deduped if fnmatch.fnmatch(k, match)]
        return (0, deduped)

    # ------------------------------------------------------------------
    # Hash operations
    # ------------------------------------------------------------------

    async def hgetall(self, key):
        self._evict()
        k = self._norm_key(key)
        data = self._hashes.get(k, {})
        return {
            (k.encode() if isinstance(k, str) else k): (v.encode() if isinstance(v, str) else v)
            for k, v in data.items()
        }

    async def hset(self, key, field=None, value=None, mapping=None):
        """Match redis-py signature: hset(name, key=None, value=None, mapping=None)."""
        self._evict()
        k = self._norm_key(key)
        if k not in self._hashes:
            self._hashes[k] = {}

        if mapping is not None:
            self._hashes[k].update(mapping)
        if field is not None:
            self._hashes[k][field] = value
        return 1

    async def hdel(self, key, *fields):
        self._evict()
        k = self._norm_key(key)
        if k not in self._hashes:
            return 0
        count = 0
        for f in fields:
            self._hashes[k].pop(self._norm_key(f), None)
            count += 1
        return count

    async def hincrby(self, key, field, increment=1):
        self._evict()
        k = self._norm_key(key)
        if k not in self._hashes:
            self._hashes[k] = {}
        current = int(self._hashes[k].get(self._norm_key(field), 0))
        new_value = current + increment
        self._hashes[k][self._norm_key(field)] = str(new_value)
        return new_value

    async def hget(self, key, field):
        self._evict()
        k = self._norm_key(key)
        if k not in self._hashes:
            return None
        value = self._hashes[k].get(self._norm_key(field))
        if value is None:
            return None
        return value.encode() if isinstance(value, str) else value

    # ------------------------------------------------------------------
    # Set operations
    # ------------------------------------------------------------------

    async def sadd(self, key, member):
        self._evict()
        k = self._norm_key(key)
        if k not in self._sets:
            self._sets[k] = set()
        m = member.decode() if isinstance(member, bytes) else str(member)
        if m in self._sets[k]:
            return 0
        self._sets[k].add(m)
        return 1

    async def scard(self, key):
        self._evict()
        k = self._norm_key(key)
        return len(self._sets.get(k, set()))

    async def smembers(self, key):
        self._evict()
        k = self._norm_key(key)
        s = self._sets.get(k, set())
        return {m.encode() if isinstance(m, str) else m for m in s}

    # ------------------------------------------------------------------
    # TTL
    # ------------------------------------------------------------------

    async def expire(self, key, ttl):
        self._evict()
        self._expiry[self._norm_key(key)] = time.time() + ttl
        return 1

    # ------------------------------------------------------------------
    # Sorted sets (used by lazy_session)
    # ------------------------------------------------------------------

    async def zadd(self, key, mapping):
        k = self._norm_key(key)
        if k not in self._sorted_sets:
            self._sorted_sets[k] = {}
        self._sorted_sets[k].update(mapping)
        return len(mapping)

    async def zrangebyscore(self, key, min_score, max_score):
        self._evict()
        k = self._norm_key(key)
        members = self._sorted_sets.get(k, {})
        matched = [(m, s) for m, s in members.items() if min_score <= s <= max_score]
        matched.sort(key=lambda x: x[1])
        return [m.encode() if isinstance(m, str) else m for m, _ in matched]

    async def zrem(self, key, member):
        self._evict()
        k = self._norm_key(key)
        members = self._sorted_sets.get(k, {})
        m = member.decode() if isinstance(member, bytes) else str(member)
        if m in members:
            del members[m]
            return 1
        return 0

    async def zscan_iter(self, key, match=None):
        self._evict()
        k = self._norm_key(key)
        members = list(self._sorted_sets.get(k, {}).items())
        if match:
            import fnmatch

            members = [(m, s) for m, s in members if fnmatch.fnmatch(m, match)]
        for m, s in members:
            yield (m.encode() if isinstance(m, str) else m, s)

    async def zscan(self, key, cursor=0, match=None, count=10):
        all_items = list(await self.zscan_iter(key, match=match))
        return (0, all_items)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def mock_manager(monkeypatch, fake_redis):
    """Patch manager.manager to return a FakeRedis and mock client."""
    import manager as manager_mod

    mgr = manager_mod.manager
    mgr.rdb = None
    mgr.config = _dummy_config()
    mgr.client = AsyncMock()
    mgr.logger = mgr.logger  # keep real logger

    monkeypatch.setattr(mgr, "get_redis", AsyncMock(return_value=fake_redis))
    mgr.lazy_session = AsyncMock()
    mgr.lazy_session_delete = AsyncMock()
    mgr.delete_message = AsyncMock()

    return mgr


def _dummy_config():
    """Return a ConfigParser with minimal sections to avoid KeyError."""
    from configparser import ConfigParser

    c = ConfigParser()
    c["telegram"] = {"token": "123:test", "api_id": "12345", "api_hash": "test"}
    return c


@pytest.fixture
def mock_advertising_config(monkeypatch):
    """Patch advertising module to return known words."""
    import utils.advertising as adv_mod

    monkeypatch.setattr(adv_mod, "load_advertising_words", lambda: ["广告", "spam", "推广", "test"])


@pytest.fixture
def mock_llm_clean(monkeypatch):
    """Mock LLM to return no spam (safe user)."""
    import handlers.utils.llm as llm_mod

    monkeypatch.setattr(llm_mod, "chat_completions", AsyncMock(return_value='{"spams": []}'))


@pytest.fixture
def mock_llm_spam(monkeypatch):
    """Mock LLM to return spam result."""
    import handlers.utils.llm as llm_mod

    monkeypatch.setattr(
        llm_mod,
        "chat_completions",
        AsyncMock(return_value='{"spams": [{"id": 12345, "reason": "suspicious profile"}]}'),
    )
