import aioredis

SETTINGS_KEY_PREFIX = "group:settings:"

SETTINGS_DEFAULT_VALUE = {
    "new_member_check_method": "ban",
    "auto_ban_time_seconds": 24 * 60 * 60,
}

NEW_MEBMER_CHECK_METHODS = {"ban": "禁止", "silence": "静默", "none": "无作为"}


async def settings_get(rdb: aioredis.Redis, chat_id: int):
    """
    Get settings for a specific chat.
    """
    settings = await rdb.hgetall(SETTINGS_KEY_PREFIX + str(chat_id))

    if settings is None:
        return SETTINGS_DEFAULT_VALUE

    # return dict(zip(settings[::2], settings[1::2]))
    return {
        k.decode("utf-8"): v.decode("utf-8") for k, v in settings.items()
    }


async def settings_set(rdb: aioredis.Redis, chat_id: int, mappings: dict):
    """ "
    Set settings for a specific chat.
    """
    await rdb.hmset(SETTINGS_KEY_PREFIX + str(chat_id), mappings)
