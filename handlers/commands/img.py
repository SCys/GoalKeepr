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

    # only support text content
    if msg.content_type is ContentType.TEXT:
        logger.warning(f"{prefix} message is not text, ignored")
        return

    # load users and groups from configure
    config = manager.config
    users = config["image"]["users"]
    groups = config["image"]["groups"]

    if user.id not in users and chat.id not in groups:
        logger.warning(f"{prefix} user {user.full_name} or group {chat.id} is not allowed, ignored")
        return

    prefix += f" user {user.full_name}"

    logger.info(f"{prefix} is generating image")

    try:
        # limit prompt
        prompt = msg.text[:500]
        url = await image(prompt, "256x256")

        logger.info(f"{prefix} image is generated")
        await manager.reply(chat.id, msg.message_id, url)
    except:
        logger.exception(f"{prefix} image generate error")
