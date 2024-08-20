from datetime import datetime, timedelta

from aiogram import types
from aiogram.filters import Command

from manager import manager
from utils.asr import openai_whisper

logger = manager.logger


SUPPORT_GROUP_TYPES = ["supergroup", "group", "private"]


@manager.register("message", Command("asr", ignore_case=True, ignore_mention=True))
async def asr(msg: types.Message):
    chat = msg.chat
    if chat.type not in SUPPORT_GROUP_TYPES:
        return

    user = msg.from_user
    if not user:
        return

    target = msg.reply_to_message
    if not target:
        return

    audio = target.audio
    if not audio:
        return

    # download file from telegram server
    raw = await manager.bot.download_file(audio.file_id)
    if not raw:
        return

    try:
        text = await openai_whisper(raw)
        if not text:
            return
    except Exception as e:
        logger.exception("asr failed")
        await manager.reply(target, "asr failed", datetime.now() + timedelta(seconds=5))
        return

    await manager.reply(target, text)
    logger.info(f"chat {chat.id} user {user.full_name} is using asr")
