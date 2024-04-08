from pydub import AudioSegment
import io
from aiogram import types
from manager import manager
import edge_tts

logger = manager.logger


async def reply_tts(msg: types.Message, content: str, show_original=False):
    try:
        voice_data = await edge_ext(content)
    except Exception:
        logger.exception(f"edge ext convert content to voice failed")
        return False

    if not voice_data or len(voice_data) == 0:
        logger.warning(f"edge ext convert content to voice is empty data")
        return False

    output = io.BytesIO()
    audio = AudioSegment.from_file(io.BytesIO(voice_data), format="mp3")
    audio.export(output, codec="opus", format="ogg", parameters=["-strict", "-2"])
    voice_file = types.BufferedInputFile(output.getvalue(), filename="tts.ogg")

    if show_original:
        await msg.reply_voice(voice_file, caption=content)
    else:
        await msg.reply_voice(voice_file, disable_notification=True)
    return True


async def edge_ext(source: str):
    communicate = edge_tts.Communicate(source, "zh-CN-XiaoxiaoNeural")

    data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            data += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            logger.debug(f"WordBoundary: {chunk}")

    return data
