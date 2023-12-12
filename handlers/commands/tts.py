import io
import re
from datetime import datetime

import edge_tts
from aiogram import types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from manager import manager
from pydub import AudioSegment

logger = manager.logger


SUPPORT_GROUP_TYPES = ["supergroup", "group", "private"]

RE_CLEAR = re.compile(r"/tts(@[a-zA-Z0-9]+\s?)?")


@manager.register("message", Command("tts", ignore_case=True, ignore_mention=True))
async def tts(msg: types.Message):
    chat = msg.chat
    if chat.type not in SUPPORT_GROUP_TYPES:
        logger.warning("chat type is not support")
        return

    user = msg.from_user
    if not user:
        logger.warning(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) user is not found")
        return

    txt = msg.text
    if msg.reply_to_message:
        txt = msg.reply_to_message.text

    if txt.startswith("/tts"):
        txt = RE_CLEAR.sub("", txt, 1)

    txt = txt.strip()

    if not txt:
        logger.warning(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) send empty text")
        return

    logger.info(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) message size is {len(txt)}")

    cost = datetime.now()

    try:
        # data = google_translate_tts(txt)
        data = await edge_ext(txt)
    except Exception:
        logger.exception(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) error")
        return

    if not data or len(data) == 0:
        logger.warning(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) is empty data")
        return

    output = io.BytesIO()
    audio = AudioSegment.from_file(io.BytesIO(data), format="mp3")
    audio.export(output, codec="opus", format="ogg", parameters=["-strict", "-2"])
    voice_file = BufferedInputFile(output.getvalue(), filename="tts.ogg")

    if msg.reply_to_message:
        await msg.reply_to_message.reply_voice(voice_file, disable_notification=True)
    else:
        await msg.reply_voice(voice_file, disable_notification=True)
    logger.info(
        f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) cost {(datetime.now() - cost).total_seconds()}"
    )


# def google_translate_tts(source: str):
#     fp = BytesIO()
#     tts = gTTS(source, lang="zh-CN")
#     tts.write_to_fp(fp)
#     fp.seek(0)
#     return fp.read()


async def edge_ext(source: str):
    communicate = edge_tts.Communicate(source, "zh-CN-XiaoxiaoNeural")

    data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            data += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            logger.info(f"WordBoundary: {chunk}")

    return data
