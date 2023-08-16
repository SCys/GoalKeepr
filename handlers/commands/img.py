from aiogram import types
import io
from datetime import datetime, timedelta
from aiogram.dispatcher.storage import FSMContext
from manager import manager
from utils.chimera_gpt import image, SUPPORT_MODELS, DEFAULT_MODEL

logger = manager.logger

DELETED_AFTER = 10


@manager.register("message", commands=["img"], commands_ignore_caption=True, commands_ignore_mention=True)
async def img(msg: types.Message, state: FSMContext):
    """image generate"""
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
        api_key = config["openai"]["api"]
        endpoint = config["openai"]["endpoint"]
    except:
        logger.exception("image users or groups is invalid")
        return

    if user.id not in users and chat.id not in groups:
        logger.warning(f"{prefix} user {user.full_name} or group {chat.id} is not allowed, ignored")
        return

    prefix += f" user {user.full_name}"

    logger.info(f"{prefix} is generating image")

    # if empty raw, reply models list
    if " " not in msg.text:
        reply = await msg.reply(f"/img [model] prompt\nsupport models:\n{', '.join(SUPPORT_MODELS)}\n")
        await manager.lazy_delete_message(chat.id, reply.message_id, msg.date + timedelta(seconds=DELETED_AFTER))
        return

    _, raw = msg.text.split(" ", maxsplit=1)

    try:
        parts = raw.split(" ", maxsplit=1)
        if len(parts) > 1:
            model = parts[0]
            prompt = " ".join(parts[1:])
        else:
            model = DEFAULT_MODEL
            prompt = raw
    except:
        logger.exception(f"{prefix} message is invalid:{msg.text}")
        reply = await msg.reply(f"message is invalid,\n/img model prompt...")
        await manager.lazy_delete_message(chat.id, reply.message_id, msg.date + timedelta(seconds=DELETED_AFTER))
        return

    if not prompt:
        logger.debug(f"{prefix} prompt is empty")
        reply = await msg.reply(f"prompt is empty,\n/img model prompt...")
        await manager.lazy_delete_message(chat.id, reply.message_id, msg.date + timedelta(seconds=DELETED_AFTER))
        return

    # limit prompt
    prompt = prompt[:500]
    if model not in SUPPORT_MODELS:
        model = DEFAULT_MODEL
        prompt = raw

    try:
        logger.info(f"{prefix} is generating image with model {model}")
        urls = await image(api_key, endpoint, model, prompt)
        logger.info(f"{prefix} image is generated with model {model}")
    except Exception as e:
        await msg.reply(f"image generate error:{str(e)}")

        logger.exception(f"{prefix} image generate error")
        return

    # download url image to memory
    try:
        for url in urls:
            session = await manager.bot.get_session()

            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"{prefix} image download error, status {resp.status}")
                    return

                data = await resp.read()

            logger.info(f"{prefix} image is downloaded")

            # send image
            try:
                input_file = types.InputFile(io.BytesIO(data), filename="image.png")
                await msg.reply_photo(input_file, caption=f"Prompt:{prompt}")
                logger.info(f"{prefix} image is sent")
            except:
                logger.exception(f"{prefix} image send error")

    except:
        logger.exception(f"{prefix} image download error")
