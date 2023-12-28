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


async def generate_text(prompt: str):
    config = manager.config

    host = config['ai']['google_gemini_host']
    if not host:
        logger.error("google gemini host is empty")
        return
    


    url = f"http://{host}/api/ai/google/gemini/text_generation"
    payload = {
        "params": {
            "text": prompt,
            **generation_config,
        }
    }

    session = await manager.bot.session.create_session()
    async with session.post(url, json=payload, headers={
        'Token': config['ai']['google_gemini_token']
    }) as response:
        if response.status != 200:
            logger.error(f"generate text error: {response.status} {await response.text()}")
            return

        data = await response.json()

        # check error
        if "error" in data:
            code = data["error"]["code"]
            message = data["error"]["message"]
            logger.error(f"generate text error: {code} {message}")
            return

        return data["data"]["text"]


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
        text = await generate_text(text)
        if not text:
            logger.warning(f"{prefix} generate text error, ignored")
            return

        await msg.reply(text)
    except Exception as e:
        logger.error(f"{prefix} text {text} error: {e}")
        await msg.reply(f"error: {e}")