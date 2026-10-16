import base64
import re
from datetime import timedelta
from typing import List, Tuple

import telegramify_markdown
from telethon import events

from manager import manager

from ...utils import count_tokens, tg_generate_text

DELETED_AFTER = 5
RE_CLEAR = re.compile(r"(?i)^/chat(?:@[a-zA-Z0-9_]+)?(?:\s|$)")
MEDIA_MAX_BYTES = 15 * 1024 * 1024  # 附件超过 15MB 不下载（base64 后约 20MB，代理多半会拒）

logger = manager.logger


async def _extract_media(event, reply_msg) -> List[Tuple[str, str]]:
    """从被回复消息和命令消息中提取图片/视频，返回 [(kind, data_url)]。

    kind: "image" / "video"。预设的三个模型（gemini-3.8-flash / deepseek-flash /
    qwen3.6-flash）都支持图文与视频输入，统一走 OpenAI 兼容的 content parts。
    """
    media: List[Tuple[str, str]] = []
    for msg in (reply_msg, event.message):
        if not msg:
            continue
        kind = None
        if getattr(msg, "photo", None):
            kind = "image"
        elif getattr(msg, "video", None):
            kind = "video"
        if not kind:
            continue

        raw = await manager.download_media_bytes(msg)
        if not raw:
            logger.warning(f"chat media download failed (msg {msg.id})")
            continue
        if len(raw) > MEDIA_MAX_BYTES:
            logger.warning(f"chat media too large ({len(raw)} bytes, msg {msg.id}), skipped")
            continue

        if kind == "video":
            mime = getattr(getattr(msg, "file", None), "mime_type", None) or "video/mp4"
        else:
            mime = "image/jpeg"  # Telegram 图片统一按 jpeg 下载
        media.append((kind, f"data:{mime};base64,{base64.b64encode(raw).decode()}"))
    return media


async def _reply_response(event, text_resp: str, prefix: str) -> bool:
    """Send raw Markdown as Rich Messages through the Bot API."""
    sent_chunks = 0
    try:
        session = await manager.create_session()
        token = manager.config["telegram"]["token"]
        url = f"https://api.telegram.org/bot{token}/sendRichMessage"
        chunks = telegramify_markdown.telegramify_rich(text_resp, mode="html")
        if not chunks:
            raise ValueError("empty Rich Message response")

        for chunk in chunks:
            payload = {
                "chat_id": event.chat_id,
                "rich_message": chunk.to_dict(),
            }
            if event.id is not None:
                payload["reply_parameters"] = {"message_id": event.id}
            async with session.post(url, json=payload) as response:
                result = await response.json()
                if response.status != 200 or not result.get("ok"):
                    raise RuntimeError(result.get("description", f"HTTP {response.status}"))
            sent_chunks += 1
    except Exception:
        logger.exception(f"{prefix} Rich Message reply failed")
        if sent_chunks:
            return False

        logger.warning(f"{prefix} no Rich Message chunk was sent, falling back to plain Bot API")
        try:
            session = await manager.create_session()
            token = manager.config["telegram"]["token"]
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": event.chat_id,
                "text": text_resp,
            }
            if event.id is not None:
                payload["reply_parameters"] = {"message_id": event.id}
            async with session.post(url, json=payload) as response:
                result = await response.json()
                if response.status != 200 or not result.get("ok"):
                    raise RuntimeError(result.get("description", f"HTTP {response.status}"))
        except Exception:
            logger.exception(f"{prefix} plain Bot API reply failed")
            return False
    return True


@manager.register("message", pattern=r"(?i)^/chat(?:\s|$)|^/chat@[a-zA-Z0-9_]+(?:\s|$)")
async def chat(event: events.NewMessage.Event):
    """Basic /chat with 30-minute conversation TTL (reset/simplified version).

    Usage:
      /chat <prompt>
      (or reply to a message, optionally with extra text after /chat)
      /chat reset   -> clear current session history for this user
    """
    chat_entity = await event.get_chat()
    user = await event.get_sender()

    prefix = f"chat {event.chat_id}({getattr(chat_entity, 'title', '')}) msg {event.id}"

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    text = event.text or ""
    if RE_CLEAR.match(text):
        text = RE_CLEAR.sub("", text, 1).strip()

    reply_msg = await event.get_reply_message()
    if reply_msg and reply_msg.text:
        text = f"{reply_msg.text}\n{text}"
        if RE_CLEAR.match(text):
            text = RE_CLEAR.sub("", text, 1).strip()

    # 附件：被回复消息或命令消息本身携带的图片/视频
    media = await _extract_media(event, reply_msg)

    if not text and media:
        text = "请分析这段内容。"

    if not text:
        logger.warning(f"{prefix} message without text, ignored")
        return

    rdb = await manager.get_redis()
    if not rdb:
        logger.error(f"{prefix} redis not connected")
        await event.reply("System error: Redis is missed.")
        return

    # Minimal subcommand support: only "reset" for the basic 30min session.
    parts = text.split(" ", 1)
    subcommand = parts[0].strip().lower() if parts else ""

    if subcommand == "reset":
        await rdb.delete(f"chat:history:{user.id}")
        await manager.reply(
            event,
            "会话已经重置\nYour chat history has been reset.",
            auto_deleted_at=event.date + timedelta(seconds=DELETED_AFTER),
        )
        await manager.delete_message(event.chat_id, event, event.date + timedelta(seconds=DELETED_AFTER))
        return

    if len(text) < 3 and not media:
        logger.warning(f"{prefix} message too short, ignored")
        return

    try:
        text_resp = await tg_generate_text(
            chat_entity.id if hasattr(chat_entity, "id") else event.chat_id, user.id, text,
            media=media or None,
        )
        if not text_resp:
            logger.warning(f"{prefix} generate text returned no response")
            await manager.reply(
                event,
                "生成回复失败，请稍后再试。| Failed to generate response, please try again later.",
                auto_deleted_at=event.date + timedelta(seconds=DELETED_AFTER),
            )
            await manager.delete_message(event.chat_id, event, event.date + timedelta(seconds=DELETED_AFTER))
            return
    except Exception:
        logger.exception(f"{prefix} generate text failed")
        text_resp = (
            "生成回复失败，请稍后再试。| Failed to generate response, please try again later.\n"
        )

    success = await _reply_response(event, text_resp, prefix)
    if not success:
        await manager.reply(
            event,
            "生成回复失败，请稍后再试。| Failed to generate response, please try again later.",
            auto_deleted_at=event.date + timedelta(seconds=DELETED_AFTER),
        )

    if not success:
        await manager.delete_message(event.chat_id, event, event.date + timedelta(seconds=DELETED_AFTER))
        return

    # Delete the trigger command message (group hygiene, same as other admin commands).
    await manager.delete_message(event.chat_id, event, event.date + timedelta(seconds=DELETED_AFTER))
    logger.info(f"{prefix} do chat command, send token {count_tokens(text)}, response token {count_tokens(text_resp)}")
