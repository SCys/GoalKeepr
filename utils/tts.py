import io
from pydub import AudioSegment

import edge_tts

from manager import manager

logger = manager.logger

SUPPORT_LANGUAGES = {"zh-CN": "zh-CN-XiaoxiaoNeural", "en": "en-US-AriaNeural", "ja": "ja-JP-NanamiNeural"}


async def reply_tts(msg, content: str, show_original=False, lang="zh-CN"):
    """发送 TTS 语音回复。msg 为 Telethon Message 或事件。"""
    try:
        voice_data = await edge_ext(content, lang)
    except Exception:
        logger.exception("edge ext convert content to voice failed")
        return False

    if not voice_data or len(voice_data) == 0:
        logger.warning("edge ext convert content to voice is empty data")
        return False

    output = io.BytesIO()
    audio = AudioSegment.from_file(io.BytesIO(voice_data), format="mp3")
    audio.export(output, codec="opus", format="ogg", parameters=["-strict", "-2"])
    voice_bytes = output.getvalue()

    entity = getattr(msg, "chat_id", None) or msg
    reply_to = getattr(msg, "id", None)
    if show_original:
        await manager.client.send_file(
            entity, voice_bytes, voice_note=True, reply_to=reply_to, caption=content
        )
    else:
        await manager.client.send_file(
            entity, voice_bytes, voice_note=True, reply_to=reply_to, silent=True
        )
    return True


async def edge_ext(source: str, lang="zh-CN"):
    communicate = edge_tts.Communicate(source, SUPPORT_LANGUAGES.get(lang, "zh-CN-XiaoxiaoNeural"))
    data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            data += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            logger.debug(f"WordBoundary: {chunk}")
    return data
