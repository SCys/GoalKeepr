import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def setup_manager():
    """全局 setup manager 实例"""
    from manager import manager

    manager.is_running = False
    manager.rdb = None
    manager.http_session = None
    yield


@pytest.fixture
def mock_config():
    """模拟配置文件"""
    config = {
        "default": {"debug": True},
        "telegram": {
            "token": "test_token",
            "api_id": "123",
            "api_hash": "test_hash",
            "admin": "64643295",
        },
        "redis": {"dsn": "redis://localhost:6379/0"},
    }
    return config


@pytest.fixture
def mock_chat():
    """模拟群组对象"""
    chat = MagicMock()
    chat.id = -1001085650365
    chat.title = "Test Group"
    chat.type = "supergroup"
    chat.broadcast = False
    chat.megagroup = True
    return chat


@pytest.fixture
def mock_user():
    """模拟用户对象"""
    user = MagicMock()
    user.id = 123456789
    user.first_name = "Test"
    user.last_name = "User"
    user.username = "testuser"
    return user


@pytest.fixture
def mock_permissions():
    """模拟用户权限对象"""
    perms = MagicMock()
    perms.is_admin = False
    perms.is_creator = False
    perms.is_banned = True
    perms.has_left = False
    return perms


@pytest.fixture
def mock_redis():
    """模拟 Redis 连接"""
    redis = MagicMock()
    redis.zrangebyscore = AsyncMock(return_value=[])
    redis.zrem = AsyncMock(return_value=True)
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.zadd = AsyncMock(return_value=True)
    redis.zremrangebyscore = AsyncMock(return_value=0)
    redis.expire = AsyncMock(return_value=True)
    redis.zcard = AsyncMock(return_value=0)
    redis.zscan_iter = AsyncMock(return_value=[])
    redis.zcount = AsyncMock(return_value=0)
    redis.brpop = AsyncMock(return_value=None)
    redis.rpop = AsyncMock(return_value=None)
    redis.zscore = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    redis.lpush = AsyncMock(return_value=1)
    redis.incr = AsyncMock(return_value=1)
    redis.zscore = AsyncMock(return_value=None)
    redis.smembers = AsyncMock(return_value=set())
    redis.srem = AsyncMock(return_value=0)
    redis.sadd = AsyncMock(return_value=1)
    redis.sismember = AsyncMock(return_value=1)
    redis.setex = AsyncMock(return_value=True)
    redis.mget = AsyncMock(return_value=[])
    return redis


@pytest.fixture
def mock_manager(mock_config):
    """模拟 manager 对象"""
    from manager import manager

    # 停止任何现有运行状态
    manager.is_running = False

    # 配置 mock
    manager.config = MagicMock()
    manager.config.__getitem__ = lambda _, key: mock_config.get(key, {})
    manager.config.get = lambda _, key, default=None: mock_config.get(key, {})

    # Mock client
    manager.client = MagicMock()
    manager.client.get_entity = AsyncMock()
    manager.client.get_permissions = AsyncMock()
    manager.client.edit_permissions = AsyncMock()
    manager.client.send_message = AsyncMock()
    manager.client.delete_messages = AsyncMock()

    # Mock redis
    manager.rdb = None

    return manager


@pytest.fixture
def mock_database():
    """模拟数据库操作"""
    with patch("database.connection", AsyncMock(return_value=MagicMock())):
        with patch("database.execute", AsyncMock(return_value=None)):
            with patch("database.execute_fetch", AsyncMock(return_value=[])):
                yield
