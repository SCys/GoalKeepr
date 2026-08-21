import random
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List, Any, Dict

from manager import manager
from .security import restore_member_permissions


def _user_full_name(user: Any) -> str:
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    return f"{first} {last}".strip() or ""


def _get_icon_descriptions(key: str) -> Tuple[str, str]:
    """解析图标的中文和英文描述。"""
    if "|" in key:
        parts = key.split("|", 1)
        return parts[0].strip(), parts[1].strip()
    if key in ("A", "B", "O"):
        return f"字母 {key}", f"Letter {key}"
    if key == "1/2":
        return "二分之一 (1/2)", "One half (1/2)"
    return key, key

WELCOME_TEXT = (
    "**🛡️ 新成员入群验证 | Member Verification**\n\n"
    "欢迎 [%(title)s](tg://user?id=%(user_id)d) ，请点击下方代表【**%(zh_desc)s**】的图标按钮完成验证。\n\n"
    "> ⏱️ **30秒** 内未完成验证或多次选错将被移出群组。\n\n"
    "Welcome [%(title)s](tg://user?id=%(user_id)d).\n"
    "> Please click the button representing **%(en_desc)s** to verify and start chatting."
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
    构建新用户验证信息的文字与内联按钮（二维列表，按钮由 manager.inline_button 构建）。
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
    random.shuffle(items)
    correct_idx = random.randint(0, len(items) - 1)
    button_user_ok_key, button_user_ok_emoji = items[correct_idx]

    # Use a hash map to avoid exceeding Telethon's 64-byte callback data limit
    callback_map: Dict[str, str] = {}

    def _short_callback(data_str: str) -> bytes:
        h = hashlib.md5(data_str.encode("utf-8")).hexdigest()
        callback_map[h] = data_str
        return h.encode("utf-8")

    # 按钮 value 使用纯索引（0, 1, 2, 3, 4），彻底脱敏真实内容
    row_user = [
        manager.inline_button(emoji, _short_callback("__".join([str(member_id), ts_str, str(idx)])))
        for idx, (key, emoji) in enumerate(items)
    ]

    row_admin = [
        manager.inline_button("✔", _short_callback("__".join([str(member_id), ts_str, "O"]))),
        manager.inline_button("❌", _short_callback("__".join([str(member_id), ts_str, "X"]))),
    ]

    zh_desc, en_desc = _get_icon_descriptions(button_user_ok_key)
    content = WELCOME_TEXT % {
        "title": member_name,
        "user_id": member_id,
        "zh_desc": zh_desc,
        "en_desc": en_desc,
    }
    buttons = [row_user, row_admin]

    # 构建答案元数据
    all_options = [{"index": idx, "key": k, "emoji": v} for idx, (k, v) in enumerate(items)]
    answer_meta = {
        "icon": button_user_ok_emoji,
        "answer": str(correct_idx),
        "answer_key": button_user_ok_key,
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
        try:
            return json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse callback_map: {e}")
            return None
    return None


async def delete_callback_map(chat_id: int, msg_id: int) -> None:
    """删除 callback_map。"""
    rdb = await manager.get_redis()
    if not rdb:
        return
    key = f"captcha_cb_map:{chat_id}:{msg_id}"
    await rdb.delete(key)


# 与成员验证相关的 lazy session 类型
CAPTCHA_TIMEOUT_TYPES = ("new_member_check", "safety_timeout_check")
# 包含自动解封任务（管理员永久封禁 / 广告 30 天封禁时必须一并取消）
MEMBER_JOB_TYPES_WITH_UNBAN = CAPTCHA_TIMEOUT_TYPES + ("unban_member",)


async def cancel_pending_member_jobs(
    chat_id: int,
    member_id: int,
    *,
    cancel_unban: bool = True,
    delete_captcha_session: bool = True,
) -> None:
    """
    取消某成员上挂起的验证超时 / 兜底 /（可选）自动解封任务。

    任何「管理员已处理」或「长期封禁」路径都必须调用，否则：
      - new_member_check 会把永久/30 天 ban 改写成 60s 并再调度 unban
      - 已有 unban_member 会在几分钟内解开 /sb 等永久封禁
    """
    types = MEMBER_JOB_TYPES_WITH_UNBAN if cancel_unban else CAPTCHA_TIMEOUT_TYPES
    for job_type in types:
        await manager.lazy_session_delete(chat_id, member_id, job_type)

    if delete_captcha_session:
        from .session import CaptchaSession
        await CaptchaSession.delete(chat_id, member_id)


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

    from manager.group import settings_get

    rdb = await manager.get_redis()
    lurk_check = "off"
    first_msg_check = "off"
    if rdb:
        lurk_check = await settings_get(rdb, chat_id, "lurk_check_5min", "off")
        first_msg_check = await settings_get(rdb, chat_id, "first_msg_check", "off")

    now = datetime.now(timezone.utc)
    if lurk_check == "on":
        content += (
            "\n\n> 📌 **新手发言指引**：请在 **5 分钟内** 在群里发送任意一条消息打招呼完成破冰（防僵尸号挂机机制）。\n"
            "> Please send a message in this group within **5 minutes** to complete verification."
        )
        if rdb:
            await rdb.set(f"first_msg_watch:{chat_id}:{user_id}", "1", ex=300)
        await manager.lazy_session(
            chat_id, 0, user_id, "first_msg_timeout", now + timedelta(minutes=5)
        )
    elif first_msg_check == "on":
        if rdb:
            await rdb.set(f"first_msg_watch:{chat_id}:{user_id}", "1", ex=300)

    has_photo = await manager.has_profile_photo(user)
    try:
        if has_photo is False:
            content += (
                "\n\n请设置头像或显示头像，能够更好体现个性。\n\n"
                "Please choose your appropriate fancy profile photo and set it available in public. "
                "It would improve your experience in communicate with everyone here and knowing you faster and better."
            )
    except Exception:
        logger.exception("get profile photos error")

    reply_id = await manager.send_text(chat_id, content, parse_mode="md")
    if reply_id is None:
        logger.error(f"{prefix} | 欢迎消息发送失败")
        return
    await manager.delete_message(chat_id, reply_id)
    # 取消超时踢人；保留 session 频率计数（若调用方尚未删除）
    await cancel_pending_member_jobs(
        chat_id, user.id, cancel_unban=True, delete_captcha_session=False
    )
