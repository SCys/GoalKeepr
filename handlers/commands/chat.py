from aiogram import types, exceptions
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


async def get_stat():
    config = manager.config

    host = config["ai"]["google_gemini_host"]
    if not host:
        logger.error("google gemini host is empty")
        return

    url = f"{host}/api/ai/google/gemini/text_generation"
    session = await manager.bot.session.create_session()
    async with session.get(url) as response:
        if response.status != 200:
            logger.error(f"get stat error: {response.status} {await response.text()}")
            return

        data = await response.json()

        # check error
        if "error" in data:
            code = data["error"]["code"]
            message = data["error"]["message"]
            logger.error(f"get stat error: {code} {message}")
            return

        return data["data"]


async def generate_text(prompt: str):
    config = manager.config

    host = config["ai"]["google_gemini_host"]
    if not host:
        logger.error("google gemini host is empty")
        return

    url = f"{host}/api/ai/google/gemini/text_generation"
    payload = {
        "params": {
            "text": prompt,
            **generation_config,
        }
    }

    session = await manager.bot.session.create_session()
    async with session.post(url, json=payload, headers={"Token": config["ai"]["google_gemini_token"]}) as response:
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

    text = msg.text
    text = text.replace("/chat", "", 1).strip()

    if not text:
        logger.warning(f"{prefix} message without text, ignored")
        return

    if text == "stat":
        try:
            stat = await get_stat()
            if not stat:
                logger.warning(f"{prefix} get stat error, ignored")
                return

            total = stat["total"]
            qps = stat["qps"]
            await msg.reply(f"total: {total}\nqps: {qps}")
        except Exception as e:
            logger.error(f"{prefix} get stat error: {e}")
            await msg.reply(f"error: {e}")

        return

    if len(text) < 5:
        logger.warning(f"{prefix} message too short, ignored")
        return

    if len(text) > 1024:
        logger.warning(f"{prefix} message too long, ignored")
        return

    try:
        text_resp = await generate_text(text)
        if not text_resp:
            logger.warning(f"{prefix} generate text error, ignored")
            return
    except Exception as e:
        logger.error(f"{prefix} text {text} error: {e}")
        await msg.reply(f"error: {e}")

    text_resp += "\n\n---\n\n *Powered by Google Gemini Pro*"

    try:
        await msg.reply(text_resp, parse_mode="MarkdownV2", disable_web_page_preview=True)
    except exceptions.TelegramBadRequest as e:
        logger.warning(f"{prefix} invalid text {text_resp}, error: {e}")
        await msg.reply(text_resp, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"{prefix} reply error: {e}")
        await msg.reply(f"error: {e}")
