from datetime import timedelta

from aiogram import types
from aiogram.filters import Command

from manager import manager

from ..utils import strip_text_prefix

logger = manager.logger

DELETED_AFTER = 5


@manager.register("message", Command("sdxl", ignore_case=True, ignore_mention=True))
async def sdxl(msg: types.Message):
    """sdxl base 1.0 power on cloudflare worker/ai"""
    chat = msg.chat
    user = msg.from_user
    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    # load users and groups from configure
    config = manager.config
    # setup image config
    try:
        users = [int(i) for i in config["image"]["users"].split(",") if i]
        groups = [int(i) for i in config["image"]["groups"].split(",") if i]
    except:
        logger.exception("image users or groups is invalid")
        return

    if user.id not in users and chat.id not in groups:
        logger.warning(f"{prefix} user {user.full_name} or group {chat.id} is not allowed, ignored")
        msg_err = await msg.reply(f"task is failed: no permission.")
        await manager.delete_message(chat, msg_err, msg.date + timedelta(seconds=DELETED_AFTER))
        return

    prefix += f" user {user.full_name}"

    logger.info(f"{prefix} is using sdxl base 1.0 func")

    # use remote cloudflare worker
    # API URL: https://iscys.com/api/cf/ai/txt2img
    session = await manager.create_session()
    async with session.post(
        "https://iscys.com/api/cf/ai/txt2img",
        json={
            "params": {
                "model": "flux",
                "prompt": strip_text_prefix(msg.text),
                "num_steps": 8,  # 4~8 steps
            },
        },
    ) as response:
        if response.status != 200:
            logger.error(f"{prefix} cloudflare worker return {response.status}")
            await msg.reply(f"task is failed: cloudflare worker return {response.status} {await response.text()}.")
            return

        # error response
        if response.content_type == "application/json":
            resp = await response.json()
            code = resp["error"]["code"]
            message = resp["error"]["message"]
            logger.error(f"{prefix} cloudflare worker return error: {code} {message}")
            await msg.reply(f"task is failed: {code} {message}.")
            return

        try:
            image_binary = await response.read()
        except:
            logger.exception(f"{prefix} cloudflare worker return invalid json")
            msg_err = await msg.reply(f"task is failed: cloudflare worker return invalid json.")
            return

    # send image
    try:
        input_file = types.BufferedInputFile(
            image_binary,
            filename="sdxl_base1.0_cloudflare_ai.png",
        )
        await manager.bot.send_photo(chat.id, input_file, caption="---\n\rPower by Cloudflare AI")
    except:
        logger.exception(f"{prefix} send image failed")
        await msg.reply(f"task is failed: send image failed.")
        return

    logger.info(f"{prefix} task is done")
