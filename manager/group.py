import aioredis

SETTINGS_KEY_PREFIX = "group:settings:"
SETTINGS_DEFAULT_VALUE = {"new_member_check_method": "ban", "auto_ban_time_seconds": 24 * 60 * 60}


async def settings_get(rdb: aioredis.Redis, chat_id: int):
    settings = await rdb.hgetall(SETTINGS_KEY_PREFIX + str(chat_id))

    if settings is None:
        return SETTINGS_DEFAULT_VALUE

    return dict(zip(settings[::2], settings[1::2]))


async def settings_set(rdb: aioredis.Redis, chat_id: int, mappings: dict):
    await rdb.hmset(SETTINGS_KEY_PREFIX + str(chat_id), mappings)
