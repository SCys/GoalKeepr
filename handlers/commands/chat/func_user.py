from datetime import datetime

from redis.asyncio import Redis

from manager import manager

logger = manager.logger


async def ban_user(rdb: Redis, uid: int):
    # check & set
    await _check_and_create_user(rdb, uid)

    await rdb.hset(f"chat:user:{uid}", "disabled", 1)


async def allow_user(rdb: Redis, uid: int):
    await _check_and_create_user(rdb, uid)

    await rdb.hset(f"chat:user:{uid}", "disabled", 0)


async def increase_user_count(rdb: Redis, uid: int):
    await _check_and_create_user(rdb, uid)

    await rdb.hincrby(f"chat:user:{uid}", "count", 1)
    await rdb.hset(f"chat:user:{uid}", "last", datetime.now().isoformat())


async def update_user_quota(rdb: Redis, uid: int, quota: int):
    await _check_and_create_user(rdb, uid)

    await rdb.hset(f"chat:user:{uid}", "quota", quota)


async def count_user(rdb: Redis) -> int:
    cursor = 0
    total = 0
    while True:
        cursor, keys = await rdb.scan(cursor=cursor, match="chat:user:*", count=100)
        total += len(keys)
        if cursor == 0:
            break
    return total


async def total_user_requested(rdb: Redis) -> int:
    """计算所有 chat:user:{uid} 的 count 总和"""
    cursor = 0
    total = 0
    while True:
        cursor, keys = await rdb.scan(cursor=cursor, match="chat:user:*", count=100)
        for key in keys:
            count = await rdb.hget(key, "count")
            if count:
                total += int(count)
        if cursor == 0:
            break
    return total


async def check_user_permission(rdb: Redis, chat_id: int, uid: int) -> bool:
    administrator = manager.config["ai"]["administrator"]

    # miss administator
    if not administrator:
        return False

    if uid == int(administrator):
        return True

    manage_group = manager.config["ai"].get("manage_group")
    if manage_group and chat_id == int(manage_group):
        try:
            perms = await manager.client.get_permissions(chat_id, uid)
            if perms.is_admin or perms.is_creator:
                logger.info(f"user {uid} is admin in group {chat_id}")
                return True
        except Exception as e:
            logger.debug(f"get_permissions {chat_id} {uid}: {e}")

    try:
        raw = await rdb.hget(f"chat:user:{uid}", "disabled")
        if raw is None:
            logger.warning(f"user {uid} is not in chat command")
            return False

        if int(raw) != 0:
            logger.warning(f"user {uid} is disabled for chat command")
            return False

        # check qutoa
        quota = await rdb.hget(f"chat:user:{uid}", "quota")
        if quota and int(quota) > 0:
            count = await rdb.hget(f"chat:user:{uid}", "count")
            if count and int(count) >= int(quota):
                logger.warning(f"user {uid} has reached the quota")
                return False

        logger.info(f"user {uid} is allowed for chat command")
        return True

    except:
        logger.exception("check_user_permission")
        return False


async def _check_and_create_user(rdb: Redis, uid: int):
    """初始化用户基础信息。redis-py 使用 hset(..., mapping=...) 替代 hmset。"""
    key = f"chat:user:{uid}"
    if await rdb.hexists(key, "disabled"):
        return
    await rdb.hset(
        key,
        mapping={
            "disabled": 0,
            "count": 0,
            "quota": -1,
            "last": "1970-01-01T00:00:00Z",
        },
    )
