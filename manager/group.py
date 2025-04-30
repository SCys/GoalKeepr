import aioredis
from typing import Optional

SETTINGS_KEY_PREFIX = "group:settings:"

SETTINGS_DEFAULT_VALUE = {
    "new_member_check_method": "ban",
    "auto_ban_time_seconds": 24 * 60 * 60,
}

NEW_MEBMER_CHECK_METHODS = {"ban": "认证剔除", "silence": "自动静默", "none": "无作为"}


async def settings_get(rdb: aioredis.Redis, chat_id: int, key: str=None, default_value: Optional[str]=None):
    """
    Get settings for a specific chat.
    """
    if key:
        settings = await rdb.hget(SETTINGS_KEY_PREFIX + str(chat_id), key)
        if settings is None:
            return default_value
        return settings

    settings = await rdb.hgetall(SETTINGS_KEY_PREFIX + str(chat_id))

    if settings is None:
        return SETTINGS_DEFAULT_VALUE
    return settings


async def settings_set(rdb: aioredis.Redis, chat_id: int, mappings: dict):
    """
    Set settings for a specific chat.
    """
    await rdb.hmset(SETTINGS_KEY_PREFIX + str(chat_id), mappings)
