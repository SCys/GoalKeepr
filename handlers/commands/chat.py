from datetime import datetime, timedelta

from aiogram import types
from aiogram.filters import Command
from manager import manager

DELETED_AFTER = 5
BAN_MEMBER = 300  # 300s

logger = manager.logger

# Set up the model
generation_config = {
    "temperature": 0.9,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 2048,
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "block_none"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "block_none"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "block_none"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "block_none"},
]


@manager.register("message", Command("chat", ignore_case=True, ignore_mention=True))
async def chat(msg: types.Message):
    """Answer Google Gemini Pro"""
    chat = msg.chat
    user = msg.from_user
    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    if manager.model_txt is None:
        logger.warning(f"{prefix} model is None, ignored")
        return

    text = msg.text
    if not text:
        logger.warning(f"{prefix} message without text, ignored")
        return

    if len(text) < 3:
        logger.warning(f"{prefix} message too short, ignored")
        return

    if len(text) > 1024:
        logger.warning(f"{prefix} message too long, ignored")
        return

    try:
        model = manager.model_txt
        response = model.generate_content(text, generation_config=generation_config, safety_settings=safety_settings)

        if not response:
            logger.warning(f"{prefix} text {text} response is None, ignored")
            return

        logger.info(f"{prefix} text {text} feedback: {response.prompt_feedback}")
        logger.info(f"{prefix} text {text} response: {response.text}")
        await msg.reply(response.text)
    except Exception as e:
        logger.error(f"{prefix} text {text} error: {e}")
        await msg.reply(f"error: {e}")
