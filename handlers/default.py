from datetime import datetime, timezone, timedelta
from manager import manager
from handlers.member_captcha.config import get_chat_type
from utils.advertising import check_advertising
from handlers.utils.llm import check_spams_with_llm

logger = manager.logger

# 常规安全打招呼快速放行白名单（无链接、无违规符号时秒级通过）
SAFE_GREETINGS = {
    "你好", "大家好", "打扰了", "报道", "报到", "新人", "新人报道", "新人报到",
    "请教", "请问", "hello", "hi", "hey", "hi all", "hello all", "morning",
    "good morning", "good evening", "good afternoon", "gm", "test", "1", "打卡",
    "各位好", "大家好呀", "求教", "谢谢", "感谢", "thx", "thanks"
}

def _is_fast_safe_greeting(text: str) -> bool:
    """检查是否为简短常见的友善问候语。"""
    cleaned = "".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace() or '\u4e00' <= ch <= '\u9fff')
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned in SAFE_GREETINGS

async def _handle_first_msg_violation(chat, event, user, reason: str):
    """处理首句违规：撤回违规消息 + 踢出成员 + 发送自毁通知。"""
    try:
        await event.delete()
    except Exception as e:
        logger.warning(f"delete first spam message failed: {e}")

    user_id = user.id
    if not await manager.kick_member(chat, user_id):
        await manager.hide_member(chat, user_id, timedelta(seconds=60))

    now_dt = datetime.now(timezone.utc)
    await manager.lazy_session(
        chat.id, 0, user_id, "unban_member", now_dt + timedelta(seconds=60)
    )

    full_name = manager.username(user)
    notice = (
        f"🚫 成员 [{full_name}](tg://user?id={user_id}) 入群首句违规（{reason}），消息已撤回并移出群组（60秒后解禁）。\n\n"
        f"> Member [{full_name}](tg://user?id={user_id}) violated first-message rules and was removed."
    )
    await manager.send(
        chat,
        notice,
        parse_mode="md",
        auto_deleted_at=now_dt + timedelta(seconds=30),
    )

@manager.register("message")
async def default_handler(event):
    chat = await event.get_chat()
    sender = await event.get_sender()

    if not sender or not chat:
        return

    chat_type = get_chat_type(chat)
    chat_title = getattr(chat, 'title', 'Private')
    user_id = sender.id
    full_name = manager.username(sender)

    logger.debug(f"default handler: chat {event.chat_id}({chat_title}) user {user_id}({full_name}) {event.text}")

    if chat_type not in ("supergroup", "group"):
        return

    # 检查是否处于入群 5 分钟首句观察期
    rdb = await manager.get_redis()
    if not rdb:
        return

    watch_key = f"first_msg_watch:{chat.id}:{user_id}"
    try:
        was_watched = await rdb.delete(watch_key)
    except Exception as e:
        logger.warning(f"check first_msg_watch redis error: {e}")
        was_watched = False

    if not was_watched:
        return

    # 用户已在 5 分钟内发言，取消潜水超时定时任务
    await manager.lazy_session_delete(chat.id, user_id, "first_msg_timeout")
    logger.debug(f"chat {chat.id} user {user_id} spoke within 5 mins, watch cleared and timeout cancelled")

    from manager.group import settings_get
    first_msg_check = await settings_get(rdb, chat.id, "first_msg_check", "off")
    if first_msg_check != "on":
        logger.debug(f"chat {chat.id} user {user_id} first message check is off, passing")
        return

    text = event.text or ""
    if not text.strip():
        return

    # 1. 快速安全问候语放行（极速无感知）
    if _is_fast_safe_greeting(text):
        logger.info(f"[首句审查] 群组:{chat.id} 成员:{user_id}({full_name}) | 命中安全问候语快速放行 | 内容:{text}")
        return

    # 2. 本地关键词与正则检测
    contains_adv, matched_word = check_advertising(text)
    if contains_adv:
        logger.warning(f"[首句审查] 群组:{chat.id} 成员:{user_id}({full_name}) | 命中广告词: {matched_word} | 内容:{text}")
        await _handle_first_msg_violation(chat, event, sender, f"首句包含广告黑名单词「{matched_word}」")
        return

    # 3. 提交 LLM 进行意图审查
    try:
        eval_results = await check_spams_with_llm([sender], additional_strings=[f"入群首句发言内容: {text}"])
        if eval_results:
            user_eval = next((item for item in eval_results if item.id == user_id), None)
            if user_eval:
                logger.info(f"[首句审查] 群组:{chat.id} 成员:{user_id}({full_name}) | LLM评分:{user_eval.score}/100 | 违规:{user_eval.is_spam} | 原因:{user_eval.reason}")
                if user_eval.is_spam:
                    await _handle_first_msg_violation(chat, event, sender, f"AI识别为违规引流「{user_eval.reason}」")
                    return
    except Exception as e:
        logger.error(f"[首句审查] LLM审查异常: {e}")
