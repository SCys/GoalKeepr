import random
from datetime import datetime, timedelta, timezone
from typing import Tuple, List, Any, Optional

import database

from telethon import Button

from manager import manager
from .config import DELETED_AFTER
from .security import restore_member_permissions


def _user_full_name(user: Any) -> str:
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    return f"{first} {last}".strip() or ""


WELCOME_TEXT = (
    "欢迎 [%(title)s](tg://user?id=%(user_id)d) ，点击 *%(icon)s* 按钮后才能发言。\n\n *30秒* 内不操作即会被送走。\n\n"
    "Welcome [%(title)s](tg://user?id=%(user_id)d). \n\n"
    "You would be allowed to send the message after choosing the right option for [*%(icon)s*] through pressing the correct button"
)

ICONS = {
    "爱心|Love": "❤️️",
    "感叹号|Exclamation mark": "❗",
    "问号|Question mark": "❓",
    "壹|One": "1⃣",
    "贰|Two": "2⃣",
    "叁|Three": "3⃣",
    "肆|Four": "4⃣",
    "伍|Five": "5⃣",
    "陆|Six": "6⃣",
    "柒|Seven": "7⃣",
    "捌|Eight": "8⃣",
    "玖|Nine": "9⃣",
    "乘号|Multiplication number": "✖",
    "加号|Plus": "➕",
    "减号|Minus": "➖",
    "除号|Divisor": "➗",
    "禁止|Prohibition": "🚫",
    "美元|US Dollar": "💲",
    "A": "🅰",
    "B": "🅱",
    "O": "🅾",
    "彩虹旗|Rainbow flag": "🏳‍🌈",
    "眼睛|Eye": "👁",
    "脚印|Footprints": "👣",
    "汽车|Car": "🚗",
    "飞机|Aircraft": "✈️",
    "火箭|Rocket": "🚀",
    "帆船|Sailboat": "⛵️",
    "警察|Police": "👮",
    "信|Letter": "✉",
    "1/2": "½",
    "雪花|Snowflake": "❄",
    "眼镜|Eyeglasses": "👓",
    "手枪|Pistol": "🔫",
    "炸弹|Bomb": "💣",
    "骷髅|Skull": "💀",
    "骰子|Dice": "🎲",
    "音乐|Music": "🎵",
    "电影|Movie": "🎬",
    "电话|Telephone": "☎️",
    "电视|Television": "📺",
    "相机|Camera": "📷",
    "计算机|Computer": "💻",
    "手机|Mobile phone": "📱",
    "钱包|Wallet": "👛",
    "钱|Money": "💰",
    "书|Book": "📖",
    "信封|Envelope": "✉️",
    "礼物|Gift": "🎁",
}


logger = manager.logger


async def store_captcha_answer(chat_id: int, member_id: int, answer: str) -> bool:
    """存储验证码正确答案，优先 Redis，失败时回退 SQLite。"""
    key = f"captcha:{chat_id}:{member_id}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    try:
        rdb = await manager.get_redis()
        if rdb:
            await rdb.set(key, answer.encode("utf-8"), ex=600)
            logger.debug(
                f"Stored captcha answer: chat={chat_id} member={member_id} answer={answer} (redis)"
            )
            return True
    except Exception as e:
        logger.warning(f"Failed to store captcha answer in redis: {e}")

    try:
        await database.execute(
            """
            insert into captcha_answers(chat, member, answer, expires_at)
            values(?,?,?,?)
            on conflict(chat, member) do update set
                answer=excluded.answer,
                expires_at=excluded.expires_at
            """,
            (
                chat_id,
                member_id,
                answer,
                manager._format_sqlite_datetime(expires_at),
            ),
        )
        logger.debug(
            f"Stored captcha answer: chat={chat_id} member={member_id} answer={answer} (sqlite)"
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to store captcha answer in sqlite: {e}")
        return False


async def load_captcha_answer(chat_id: int, member_id: int) -> Optional[str]:
    """读取验证码答案，优先 Redis，失败或缺失时回退 SQLite。"""
    key = f"captcha:{chat_id}:{member_id}"
    try:
        rdb = await manager.get_redis()
        if rdb:
            value = await rdb.get(key)
            if value:
                return value.decode("utf-8") if isinstance(value, bytes) else str(value)
    except Exception as e:
        logger.warning(f"Failed to load captcha answer from redis: {e}")

    try:
        rows = await database.execute_fetch(
            """
            select answer from captcha_answers
            where chat=? and member=? and expires_at >= datetime('now','localtime')
            limit 1
            """,
            (chat_id, member_id),
        )
        if rows:
            return str(rows[0][0])
    except Exception as e:
        logger.warning(f"Failed to load captcha answer from sqlite: {e}")
    return None


async def delete_captcha_answer(chat_id: int, member_id: int) -> None:
    """删除验证码答案，尽量清理 Redis 与 SQLite 两侧状态。"""
    key = f"captcha:{chat_id}:{member_id}"
    try:
        rdb = await manager.get_redis()
        if rdb:
            await rdb.delete(key)
    except Exception as e:
        logger.warning(f"Failed to delete captcha answer from redis: {e}")

    try:
        await database.execute(
            "delete from captcha_answers where chat=? and member=?",
            (chat_id, member_id),
        )
    except Exception as e:
        logger.warning(f"Failed to delete captcha answer from sqlite: {e}")


async def build_captcha_message(
    member: Any,
    msg_timestamp: datetime,
    chat_id: int = None,
) -> Tuple[str, List[List[Any]]]:
    """
    构建新用户验证信息的文字与 Telethon 内联按钮（二维列表，供 send_message(buttons=) 使用）。
    member 需有 .user (id, first_name, last_name) 或自身为 User。

    Args:
        member: 成员对象
        msg_timestamp: 消息时间戳
        chat_id: 群组ID，用于存储正确答案到Redis（可选）

    Returns:
        (content, buttons) 元组
    """
    if getattr(member, "user", None):
        member_id = member.user.id
        member_name = _user_full_name(member.user)
    elif hasattr(member, "id"):
        member_id = member.id
        member_name = _user_full_name(member)
    else:
        raise ValueError(f"Unknown member type {type(member)}")

    ts_str = str(msg_timestamp)
    # 正确逻辑：先抽样5个选项，再从中选一个正确答案
    items = list(ICONS.items())  # [(key, icon), ...]
    selected_items = random.sample(items, k=5)
    correct_key, correct_icon = random.choice(selected_items)

    # 存储正确答案，Redis 不可用时自动降级到 SQLite
    if chat_id:
        await store_captcha_answer(chat_id, member_id, correct_key)

    row_user = []
    for key, icon in selected_items:
        # data 包含 member_id, timestamp 和 icon 的 key（用于验证）
        data = f"{member_id}__{ts_str}__{key}".encode("utf-8")
        row_user.append(Button.inline(icon, data))

    random.shuffle(row_user)  # 打乱用户按钮顺序

    row_admin = [
        Button.inline("✔", f"{member_id}__{ts_str}__admin_O".encode("utf-8")),
        Button.inline("❌", f"{member_id}__{ts_str}__admin_X".encode("utf-8")),
    ]

    content = WELCOME_TEXT % {
        "title": member_name,
        "user_id": member_id,
        "icon": correct_icon,
    }
    buttons = [row_user, row_admin]
    return content, buttons


# 安全模式待审核消息前缀，回调 data 格式: sm__member_id__ts__O / sm__member_id__ts__X
SECURITY_MODE_CALLBACK_PREFIX = "sm__"

SECURITY_MODE_PENDING_TEXT = (
    "🛡️ *安全模式* | 新成员 [%(title)s](tg://user?id=%(user_id)d) 待管理员审核。\n"
    "30 分钟内未操作将被移出群组。\n\n"
    "Security mode: new member pending admin approval."
)

# 进入安全模式时的群通知（时间统一为 UTC，并注明“X 分钟后”避免误导）
SECURITY_MODE_ENTERED_AUTO = (
    "🛡️ *已进入安全模式*\n\n"
    "进入时间：{enter_time} UTC\n"
    "新成员将静默等待管理员审核，请及时处理待审核列表。\n\n"
    "安全模式将于 *{exit_minutes} 分钟后* 自动解除。\n"
    "解除时间（UTC）：{exit_time} UTC\n"
    "也可在群设置中随时手动解除。\n\n"
    "Security mode is on. Auto-off in {exit_minutes} min (UTC: {exit_time})."
)
SECURITY_MODE_ENTERED_MANUAL = (
    "🛡️ *已进入安全模式*\n\n"
    "进入时间：{enter_time} UTC\n"
    "新成员将静默等待管理员审核，请及时处理待审核列表。\n\n"
    "安全模式需在 *群设置* 中手动解除（/group_setting）。\n\n"
    "Security mode is on. Turn off manually in group settings."
)


def build_security_mode_pending_message(
    member: Any,
    msg_timestamp: datetime,
) -> Tuple[str, List[List[Any]]]:
    """
    构建安全模式待审核消息：仅管理员可见操作，新成员静默等待。
    回调数据格式: sm__member_id__ts__O（通过） / sm__member_id__ts__X（拒绝）
    """
    if getattr(member, "user", None):
        member_id = member.user.id
        member_name = _user_full_name(member.user)
    elif hasattr(member, "id"):
        member_id = member.id
        member_name = _user_full_name(member)
    else:
        raise ValueError(f"Unknown member type {type(member)}")
    ts_str = str(msg_timestamp)
    row = [
        Button.inline("✔ 通过", f"sm__{member_id}__{ts_str}__O".encode("utf-8")),
        Button.inline("❌ 拒绝", f"sm__{member_id}__{ts_str}__X".encode("utf-8")),
    ]
    content = SECURITY_MODE_PENDING_TEXT % {"title": member_name, "user_id": member_id}
    return content, [row]


async def accepted_member(chat: Any, msg: Any, user: Any):
    """接受新成员，恢复其权限并发送欢迎消息。"""
    chat_id = chat.id if hasattr(chat, "id") else chat
    msg_id = msg.id if hasattr(msg, "id") else msg
    prefix = f"chat {chat_id}({getattr(chat, 'title', '')}) msg {msg_id}"

    if not await restore_member_permissions(chat, user):
        logger.error(f"{prefix} 恢复成员 {user.id} 权限失败")
        return

    logger.info(f"{prefix} member {user.id}({manager.username(user)}) is accepted")

    title = manager.username(user)
    user_id = user.id
    content = (
        f"欢迎 [{title}](tg://user?id={user_id}) 加入群组，先请阅读群规。\n\n"
        f"Welcome [{title}](tg://user?id={user_id}). \n\n"
        "Please read the rules carefully before sending the message in the group."
    )

    try:
        photos = await manager.client.get_profile_photos(user, limit=1)
        if not photos:
            content += (
                "\n\n请设置头像或显示头像，能够更好体现个性。\n\n"
                "Please choose your appropriate fancy profile photo and set it available in public. "
                "It would improve your experience in communicate with everyone here and knowing you faster and better."
            )
    except Exception:
        logger.exception("get profile photos error")

    reply = await manager.client.send_message(chat, content, parse_mode="md")
    msg_date = getattr(msg, "date", None) or datetime.now(timezone.utc)
    await manager.delete_message(
        chat, reply, msg_date + timedelta(seconds=DELETED_AFTER)
    )
    await manager.lazy_session_delete(chat_id, user.id, "new_member_check")
