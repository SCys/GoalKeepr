import asyncio
from telethon import events, Button
from manager import manager
from ..member_captcha.stats import STATS_KEY, FIELD_GROUP_JOINS, FIELD_VERIFICATIONS, FIELD_SUCCESS, FIELD_FAILED

logger = manager.logger

PAGE_SIZE = 10
CB_PREFIX = "system_groups_page:"
GROUP_NAMES_KEY = f"{STATS_KEY}:group_names"


async def _build_page(page: int) -> tuple:
    """
    构建群组列表的第 page 页。

    Returns:
        (message_text, buttons_2d, total_pages) — 页码越界时 text 为 None。
    """
    rdb = await manager.get_redis()
    if not rdb:
        return None, None, 0

    try:
        names_raw, = await asyncio.wait_for(
            asyncio.gather(rdb.hgetall(GROUP_NAMES_KEY)),
            timeout=5,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning("system_groups 读取群组列表失败: %s", e)
        return None, None, 0

    if not names_raw:
        return "暂无群组记录。", [], 0

    # 收集所有群组的统计
    groups = []
    tasks = []
    chat_ids = []

    for chat_id_bytes in names_raw:
        cid = int(chat_id_bytes.decode())
        chat_ids.append(cid)
        tasks.append(
            asyncio.wait_for(
                asyncio.gather(
                    rdb.hgetall(f"{STATS_KEY}:{cid}"),
                    rdb.scard(f"{STATS_KEY}:{cid}:persons"),
                ),
                timeout=3,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, cid in enumerate(chat_ids):
        title = names_raw[str(cid).encode()].decode() if isinstance(names_raw.get(str(cid).encode()), bytes) else str(cid)
        if isinstance(results[i], BaseException) or results[i] is None:
            continue
        raw, persons_count = results[i]
        joins = int(raw.get(FIELD_GROUP_JOINS.encode(), b"0"))
        verifications = int(raw.get(FIELD_VERIFICATIONS.encode(), b"0"))
        success = int(raw.get(FIELD_SUCCESS.encode(), b"0"))
        failed = int(raw.get(FIELD_FAILED.encode(), b"0"))
        total = success + failed
        rate = f"{success / total * 100:.1f}%" if total > 0 else "N/A"
        groups.append((joins, cid, title, verifications, success, failed, persons_count, rate))

    if not groups:
        return "暂无群组记录。", [], 0

    groups.sort(key=lambda x: x[0], reverse=True)
    total_pages = (len(groups) + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_groups = groups[start:end]

    lines = [f"使用中的群组 (共 {len(groups)} 个) [第 {page}/{total_pages} 页]"]
    for idx, (joins, cid, title, verifications, success, failed, persons_count, rate) in enumerate(page_groups, start + 1):
        lines.append(f"{idx}. {title} (ID: {cid})")
        lines.append(f"   入群: {joins} | 验证: {verifications} | 成功: {success} | 失败: {failed} | 成功率: {rate}")

    buttons = []
    nav = []
    if page > 1:
        nav.append(Button.inline("◀ 上一页", f"{CB_PREFIX}{page - 1}".encode()))
    if page < total_pages:
        nav.append(Button.inline("下一页 ▶", f"{CB_PREFIX}{page + 1}".encode()))
    if nav:
        buttons.append(nav)

    return "\n".join(lines), buttons, total_pages


@manager.register("message", pattern=r"(?i)^/system_groups$")
async def system_groups(event: events.NewMessage.Event):
    """查看所有使用中的群组统计（仅全局管理员）。"""
    sender = await event.get_sender()
    if not sender:
        return

    if str(sender.id) != manager.config["telegram"].get("admin"):
        return

    text, buttons, _ = await _build_page(1)
    if text is None:
        return
    await event.reply(text, buttons=buttons)


@manager.register("callback_query", pattern=rf"^{CB_PREFIX}")
async def system_groups_callback(event: events.CallbackQuery.Event):
    """翻页回调。"""
    sender = await event.get_sender()
    if not sender or str(sender.id) != manager.config["telegram"].get("admin"):
        await event.answer()
        return

    data = event.data.decode()
    try:
        page = int(data[len(CB_PREFIX):])
    except (ValueError, IndexError):
        await event.answer()
        return

    text, buttons, _ = await _build_page(page)
    if text is None:
        await event.answer()
        return

    await event.answer()
    await manager.client.edit_message(event.chat_id, event.message_id, text, buttons=buttons)
