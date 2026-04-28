import random
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List, Any, Dict

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


async def build_captcha_message(
    member: Any,
    msg_timestamp: datetime,
) -> Tuple[str, List[List[Any]], Dict[str, str]]:
    """
    构建新用户验证信息的文字与 Telethon 内联按钮（二维列表，供 send_message(buttons=) 使用）。
    member 需有 .user (id, first_name, last_name) 或自身为 User。

    返回:
      (message_content, buttons, answer_meta)
        answer_meta = {"icon": emoji, "answer": key, "options": json_string}
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
    items = random.sample(list(ICONS.items()), k=5)
    button_user_ok_key, button_user_ok_emoji = random.choice(items)

    # Use a hash map to avoid exceeding Telethon's 64-byte callback data limit
    callback_map: Dict[str, str] = {}

    def _short_callback(data_str: str) -> bytes:
        h = hashlib.md5(data_str.encode("utf-8")).hexdigest()
        callback_map[h] = data_str
        return h.encode("utf-8")

    row_user = [
        Button.inline(emoji, _short_callback("__".join([str(member_id), ts_str, key])))
        for key, emoji in items
    ]
    random.shuffle(row_user)

    row_admin = [
        Button.inline("✔", _short_callback("__".join([str(member_id), ts_str, "O"]))),
        Button.inline("❌", _short_callback("__".join([str(member_id), ts_str, "X"]))),
    ]

    content = WELCOME_TEXT % {"title": member_name, "user_id": member_id, "icon": button_user_ok_emoji}
    buttons = [row_user, row_admin]

    # 构建答案元数据
    all_options = [{"key": k, "emoji": v} for k, v in items]
    answer_meta = {
        "icon": button_user_ok_emoji,
        "answer": button_user_ok_key,
        "options": json.dumps(all_options, ensure_ascii=False),
        "callback_map": callback_map,
    }

    return content, buttons, answer_meta


async def store_callback_map(chat_id: int, msg_id: int, callback_map: Dict[str, str], ttl: int = 60) -> None:
    """将 callback_map (hash→原始数据) 存入 Redis，供回调时解码 MD5 哈希。"""
    rdb = await manager.get_redis()
    if not rdb:
        return
    key = f"captcha_cb_map:{chat_id}:{msg_id}"
    await rdb.set(key, json.dumps(callback_map, ensure_ascii=False), ex=ttl)


async def get_callback_map(chat_id: int, msg_id: int) -> Optional[Dict[str, str]]:
    """从 Redis 读取 callback_map。"""
    rdb = await manager.get_redis()
    if not rdb:
        return None
    key = f"captcha_cb_map:{chat_id}:{msg_id}"
    raw = await rdb.get(key)
    if raw:
        return json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    return None


async def delete_callback_map(chat_id: int, msg_id: int) -> None:
    """删除 callback_map。"""
    rdb = await manager.get_redis()
    if not rdb:
        return
    key = f"captcha_cb_map:{chat_id}:{msg_id}"
    await rdb.delete(key)


async def accepted_member(chat: Any, msg: Any, user: Any):
    """接受新成员，恢复其权限并发送欢迎消息。"""
    chat_id = chat.id if hasattr(chat, "id") else chat
    msg_id = msg.id if hasattr(msg, "id") else msg
    prefix = f"chat {chat_id}({getattr(chat, 'title', '')}) msg {msg_id}"

    if not await restore_member_permissions(chat, user):
        logger.error(f"{prefix} 恢复成员 {user.id} 权限失败")
        return

    logger.info(f"{prefix} member {user.id}({manager.username(user)}) is accepted")

    # ★ 记录验证耗时到 CaptchaSession
    from .session import CaptchaSession
    msg_date = getattr(msg, "date", None) or datetime.now(timezone.utc)
    captcha_data = await CaptchaSession.get(chat_id, user.id)
    if captcha_data:
        first_join = captcha_data.get("first_join_ts", "")
        if first_join:
            try:
                first_join_dt = datetime.fromisoformat(first_join)
                cost = (msg_date - first_join_dt).total_seconds()
                await CaptchaSession.record_cost(chat_id, user.id, cost)
            except (ValueError, TypeError):
                pass

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
    await manager.delete_message(chat, reply, msg_date + timedelta(seconds=DELETED_AFTER))
    await manager.lazy_session_delete(chat_id, user.id, "new_member_check")
