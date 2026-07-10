from typing import Optional, Union

from redis.asyncio import Redis

PENDING_KEY_PREFIX = "group_setting:pending:"

SETTINGS_KEY_PREFIX = "group:settings:"

SETTINGS_DEFAULT_VALUE = {
    "new_member_check_method": "ban",
}

NEW_MEMBER_CHECK_METHODS = {
    "ban":            "认证剔除",
    "silence":        "手动解封",
    "none":           "无作为",
    "sleep_1week":    "静默1周",
    "sleep_2weeks":   "静默2周",
    "sleep_custom":   "自定义静默",
}


def settings_chat_id_candidates(chat_id: int) -> list[int]:
    """
    返回群组设置 Redis key 的候选 chat_id（主 id 优先）。

    Telethon 里 Channel.id 是裸 ID（正数），event.chat_id 是 Bot API 形式（-100...）。
    历史上两种都可能被写入，读取时必须兼容，避免设置“写得上、读不到”。
    """
    cid = int(chat_id)
    candidates: list[int] = []
    seen: set[int] = set()

    def _add(value: int) -> None:
        if value not in seen:
            seen.add(value)
            candidates.append(value)

    _add(cid)

    text = str(cid)
    # 频道/超级群 Bot API 形式 → 裸 ID
    if text.startswith("-100") and len(text) > 4:
        try:
            _add(int(text[4:]))
        except ValueError:
            pass
    elif cid > 0:
        # 裸正数 ID → 可能是超级群，也尝试 -100 前缀形式
        _add(int(f"-100{cid}"))
        # 普通群 peer_id 为 -id
        _add(-cid)
    elif cid < 0 and not text.startswith("-100"):
        # 普通群 marked id → 裸正数
        _add(-cid)

    return candidates


def _settings_redis_keys(chat_id: int) -> list[str]:
    return [SETTINGS_KEY_PREFIX + str(cid) for cid in settings_chat_id_candidates(chat_id)]


def _decode_hash_value(value: Union[bytes, str, None]) -> Optional[str]:
    if value is None:
        return None
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _decode_hash_map(settings: dict) -> dict:
    return {
        (k.decode("utf-8") if isinstance(k, bytes) else k): (
            v.decode("utf-8") if isinstance(v, bytes) else v
        )
        for k, v in settings.items()
    }


async def settings_get(
    rdb: Redis, chat_id: int, key: Optional[str] = None, default_value: Optional[str] = None
) -> Optional[Union[str, dict]]:
    """
    获取指定群组的设置。使用 redis.asyncio，与 manager 一致。

    会按 settings_chat_id_candidates 依次尝试多个 key，兼容裸 ID / -100 ID。
    """
    redis_keys = _settings_redis_keys(chat_id)

    if key:
        for redis_key in redis_keys:
            value = await rdb.hget(redis_key, key)
            if value is not None:
                return _decode_hash_value(value)
        return default_value

    for redis_key in redis_keys:
        settings = await rdb.hgetall(redis_key)
        if settings:
            return _decode_hash_map(settings)
    return SETTINGS_DEFAULT_VALUE


async def settings_set(rdb: Redis, chat_id: int, mappings: dict):
    """
    设置指定群组的配置。

    写入主 key（传入的 chat_id），并把同名旧候选 key 上的字段合并迁移，
    避免后续读到陈旧分叉数据。
    """
    candidates = settings_chat_id_candidates(chat_id)
    primary_id = candidates[0]
    primary_key = SETTINGS_KEY_PREFIX + str(primary_id)

    # 合并其它候选 key 上已有配置，再覆盖本次 mappings
    merged: dict = {}
    for cid in reversed(candidates):
        redis_key = SETTINGS_KEY_PREFIX + str(cid)
        existing = await rdb.hgetall(redis_key)
        if existing:
            merged.update(_decode_hash_map(existing))
    merged.update({str(k): str(v) for k, v in mappings.items()})

    await rdb.hset(primary_key, mapping=merged)

    # 清理其它候选 key，统一到主 key，防止继续分叉
    for cid in candidates[1:]:
        other_key = SETTINGS_KEY_PREFIX + str(cid)
        try:
            await rdb.delete(other_key)
        except Exception:
            pass
