from typing import Optional, Union

from redis.asyncio import Redis

SETTINGS_KEY_PREFIX = "group:settings:"

SETTINGS_DEFAULT_VALUE = {
    "new_member_check_method": "ban",
    "auto_ban_time_seconds": 24 * 60 * 60,
}

NEW_MEBMER_CHECK_METHODS = {
    "ban": "认证剔除",
    "silence": "手动解封",
    "none": "无作为",
    "sleep_1week": "静默1周",
    "sleep_2weeks": "静默2周",
}


async def settings_get(
    rdb: Redis, chat_id: int, key: Optional[str] = None, default_value: Optional[str] = None
) -> Optional[Union[str, dict]]:
    """
    获取指定群组的设置。使用 redis.asyncio，与 manager 一致。
    """
    redis_key = SETTINGS_KEY_PREFIX + str(chat_id)
    if key:
        value = await rdb.hget(redis_key, key)
        if value is None:
            return default_value
        return value.decode("utf-8") if isinstance(value, bytes) else value

    settings = await rdb.hgetall(redis_key)
    if not settings:
        return SETTINGS_DEFAULT_VALUE
    return {k.decode("utf-8") if isinstance(k, bytes) else k: v.decode("utf-8") if isinstance(v, bytes) else v for k, v in settings.items()}


async def settings_set(rdb: Redis, chat_id: int, mappings: dict):
    """设置指定群组的配置。"""
    await rdb.hset(SETTINGS_KEY_PREFIX + str(chat_id), mapping=mappings)
