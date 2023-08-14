from aiogram import types
import io
import base64
from aiogram.dispatcher.storage import FSMContext
from manager import manager
from utils.chimera_gpt import image
from asyncio.queues import Queue
from datetime import datetime
import asyncio
from utils import sd_api
from orjson import dumps, loads

logger = manager.logger

GLOBAL_FORCE_SLEEP = 10
GLOBAL_TASK_LIMIT = 3
QUEUE_NAME = "txt2img"


@manager.register("message", commands=["txt2img"], commands_ignore_caption=True, commands_ignore_mention=True)
async def txt2img(msg: types.Message, state: FSMContext):
    """sd txt2img"""
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

    logger.info(f"{prefix} is using sd txt2img func")

    rdb = await manager.get_redis()
    if not rdb:
        logger.warning(f"{prefix} redis is not ready, ignored")
        return

    # check task is full
    task_size = await rdb.llen(QUEUE_NAME)
    if task_size >= GLOBAL_TASK_LIMIT:
        logger.warning(f"task queue is full, ignored")
        await msg.reply("task queue is full, please try again later")
        return

    task = {
        "chat": msg.chat.id,
        "chat_name": msg.chat.full_name,
        "user": msg.from_user.id,
        "user_name": msg.from_user.full_name,
        "raw": msg.text,
        "from": msg.message_id,
        "to": -1,
        "created_at": datetime.now().timestamp(),
    }

    if task_size > 0:
        reply = await msg.reply(f"task is queued, please wait(~{task_size * 45}s). /txt2img to check system & task status")
    else:
        reply = await msg.reply("task is queued, please wait(~45s). /txt2img to check system & task status")
    task["to"] = reply.message_id

    try:
        # put task to queue
        await rdb.lpush(QUEUE_NAME, dumps(task))

        logger.info(f"{prefix} task is queued")
    except:
        await manager.bot.edit_message_text(
            f"task is failed, please try again later",
            chat,
            reply,
        )

        logger.exception(f"{prefix} sd txt2img error")


async def worker():
    rdb = await manager.get_redis()
    if not rdb:
        logger.warning(f"redis is not ready, ignored")
        return

    while True:
        rdb = await manager.get_redis()
        if not rdb:
            logger.warning(f"redis is not ready, ignored")
            return

        raw = await rdb.rpop(QUEUE_NAME)
        if raw:
            try:
                task = loads(raw)
                await process_task(task)
            except:
                logger.exception("process task error")
            await asyncio.sleep(GLOBAL_FORCE_SLEEP)

        # sleep 1s
        await asyncio.sleep(1)

        # tasks detail
        tasks_size = await rdb.llen(QUEUE_NAME)
        if tasks_size > 0:
            logger.debug(f"task queue size: {tasks_size}")


async def process_task(task):
    """
    task = {
        "chat": msg.chat,
        "user": msg.from_user,
        "raw": msg.text,
        "from": msg.message_id,
        "to": -1,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    """
    # load users and groups from configure
    config = manager.config
    endpoint = None
    try:
        endpoint = config["sd_api"]["endpoint"]
    except:
        logger.exception("sd api endpoint is invalid")
        return
    if not endpoint:
        logger.warning("sd api endpoint is empty")
        return

    raw = task["raw"]
    chat = task["chat"]
    chat_fullname = task["chat_name"]
    user = task["user"]
    user_fullname = task["user_name"]
    reply = task["to"]
    created_at = datetime.fromtimestamp(task["created_at"])
    prefix = f"chat {chat}({chat_fullname}) msg {task['from']} user {user}({user_fullname})"

    # task is started, reply to user
    cost = datetime.now() - created_at
    await manager.bot.edit_message_text(
        f"task is started(cost {str(cost)[:-7]}), please wait(~45s). /txt2img to check system & task status",
        chat,
        reply,
    )

    logger.info(f"{prefix} is processing task")

    try:
        img_raw = await sd_api.txt2img(endpoint, raw)
        logger.info(f"{prefix} task is processed")

        input_file = types.InputFile(
            io.BytesIO(base64.b64decode(img_raw.split(",", 1)[0])),
            filename="sd_txt2img.png",
        )
        cost = datetime.now() - created_at

        # @user and show cost time
        await manager.bot.edit_message_media(
            types.InputMediaPhoto(input_file, caption=f"cost {str(cost)[:-7]}"),
            chat,
            reply,
        )
        logger.info(f"{prefix} image is sent, cost: {str(cost)[:-7]}")
    except:
        await manager.bot.edit_message_text(
            f"task is failed(create before {str(cost)[:-7]}), please try again later",
            chat,
            reply,
        )
        logger.exception(f"{prefix} sd txt2img error")
