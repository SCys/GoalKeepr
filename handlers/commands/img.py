from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from aiogram.types import ContentType
from manager import manager
from utils.chimera_gpt import image

logger = manager.logger


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
    except:
        logger.exception("image users or groups is invalid")
        return

    if user.id not in users and chat.id not in groups:
        logger.warning(f"{prefix} user {user.full_name} or group {chat.id} is not allowed, ignored")
        return

    prefix += f" user {user.full_name}"

    logger.info(f"{prefix} is generating image")

    try:
        # limit prompt
        prompt = msg.text[4:500]  # remove prefix
        urls = await image(prompt)

        logger.info(f"{prefix} image is generated")
    except:
        logger.exception(f"{prefix} image generate error")
        return

    # download url image to memory
    try:
        for url in urls:
            async with manager.bot.session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"{prefix} image download error, status {resp.status}")
                    return

                data = await resp.read()

            logger.info(f"{prefix} image is downloaded")

            # send image
            try:
                input_file = types.InputFile(data, filename="image.png")
                await msg.reply_photo(input_file, caption=f"Prompt:{prompt}")
                logger.info(f"{prefix} image is sent")
            except:
                logger.exception(f"{prefix} image send error")

    except:
        logger.exception(f"{prefix} image download error")
