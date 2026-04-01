from typing import Optional, Union

from redis.asyncio import Redis

SETTINGS_KEY_PREFIX = "group:settings:"

SETTINGS_DEFAULT_VALUE = {
    "new_member_check_method": "ban",
    "auto_ban_time_seconds": 24 * 60 * 60,
    # 安全模式：某时间窗口内入群人数超过此阈值则进入安全模式（静默待审核）
    "security_mode_join_threshold": "10",
    # 安全模式计数窗口（秒）：3 / 300(5分钟) / 600(10分钟) / 1800(30分钟)
    "security_mode_window_seconds": "300",
    # 安全模式自动解除时间（分钟）：0=仅手动解除，15/30/60=对应分钟后自动解除
    "security_mode_auto_exit_minutes": "30",
}

NEW_MEBMER_CHECK_METHODS = {
    "ban": "认证剔除",
    "silence": "手动解封",
    "none": "无作为",
    "sleep_1week": "静默1周",
    "sleep_2weeks": "静默2周",
}

# 安全模式计数窗口展示名（用于群设置面板）
SECURITY_MODE_WINDOW_NAMES = {
    "3": "3秒",
    "300": "5分钟",
    "600": "10分钟",
    "1800": "30分钟",
}

# 解除安全模式回调 data
SECURITY_MODE_OFF_CALLBACK = "su:sm_off:1"

# 手动开启安全模式回调 data（可选时长分钟，0=使用群设置中的自动解除时长）
SECURITY_MODE_ON_CALLBACK_PREFIX = "su:sm_on:"

# 安全模式自动解除时长展示名（用于群设置面板）
SECURITY_MODE_AUTO_EXIT_NAMES = {
    "0": "仅手动解除",
    "15": "15 分钟后",
    "30": "30 分钟后",
    "60": "60 分钟后",
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
