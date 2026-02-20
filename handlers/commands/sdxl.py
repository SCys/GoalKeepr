from datetime import timedelta
from telethon import events

from manager import manager
from ..utils import strip_text_prefix
from handlers.member_captcha.config import get_chat_type

logger = manager.logger

DELETED_AFTER = 5


@manager.register("message", pattern=r"(?i)^/sdxl(\s|$)|^/sdxl@\w+")
async def sdxl(event: events.NewMessage.Event):
    """sdxl base 1.0 power on cloudflare worker/ai"""
    chat = await event.get_chat()
    user = await event.get_sender()
    prefix = f"chat {chat.id}({getattr(chat, 'title', '')}) msg {event.id}"

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    config = manager.config
    try:
        users = [int(i) for i in config["image"]["users"].split(",") if i]
        groups = [int(i) for i in config["image"]["groups"].split(",") if i]
    except Exception:
        logger.exception("image users or groups is invalid")
        return

    if user.id not in users and chat.id not in groups:
        name = getattr(user, "first_name", "") or ""
        if getattr(user, "last_name", None):
            name = f"{name} {user.last_name}".strip()
        logger.warning(f"{prefix} user {name} or group {chat.id} is not allowed, ignored")
        msg_err = await event.reply("task is failed: no permission.")
        await manager.delete_message(chat, msg_err, event.date + timedelta(seconds=DELETED_AFTER))
        return

    name = getattr(user, "first_name", "") or ""
    if getattr(user, "last_name", None):
        name = f"{name} {user.last_name}".strip()
    prefix += f" user {name}"
    logger.info(f"{prefix} is using sdxl base 1.0 func")

    session = await manager.create_session()
    async with session.post(
        "https://iscys.com/api/cf/ai/txt2img",
        json={
            "params": {
                "model": "flux",
                "prompt": strip_text_prefix(event.text or ""),
                "num_steps": 8,
            },
        },
    ) as response:
        if response.status != 200:
            logger.error(f"{prefix} cloudflare worker return {response.status}")
            await event.reply(f"task is failed: cloudflare worker return {response.status} {await response.text()}.")
            return

        if response.content_type == "application/json":
            resp = await response.json()
            code = resp["error"]["code"]
            message = resp["error"]["message"]
            logger.error(f"{prefix} cloudflare worker return error: {code} {message}")
            await event.reply(f"task is failed: {code} {message}.")
            return

        try:
            image_binary = await response.read()
        except Exception:
            logger.exception(f"{prefix} cloudflare worker return invalid json")
            await event.reply("task is failed: cloudflare worker return invalid json.")
            return

    try:
        await manager.client.send_file(
            chat.id,
            image_binary,
            caption="---\n\rPower by Cloudflare AI",
        )
    except Exception:
        logger.exception(f"{prefix} send image failed")
        await event.reply("task is failed: send image failed.")
        return

    logger.info(f"{prefix} task is done")
