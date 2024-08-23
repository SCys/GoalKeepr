import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import translators as ts
from aiogram import types
from aiogram.filters import Command
from orjson import dumps, loads

from manager import manager
from utils import sd_api

from ..utils import contains_chinese, strip_text_prefix

logger = manager.logger

GLOBAL_TASK_LIMIT = 3
QUEUE_NAME = "txt2img"
DELETED_AFTER = 3  # 3s


@dataclass
class Task:
    chat_id: int
    chat_name: Optional[str]

    user_id: int
    user_name: Optional[str]

    message_id: int
    reply_message_id: int

    reply_content: Optional[str]
    prompt: str
    created_at: float


@manager.register("message", Command("image", ignore_case=True, ignore_mention=True))
async def image(msg: types.Message):
    chat = msg.chat
    user = msg.from_user
    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"
    now = datetime.now()
    reply_content = ""

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    # check user/group permission
    config = manager.config
    try:
        users = [int(i) for i in config["image"]["users"].split(",") if i]
        groups = [int(i) for i in config["image"]["groups"].split(",") if i]
    except:
        logger.exception("image users or groups is invalid")
        return
    if user.id not in users and chat.id not in groups:
        logger.warning(f"{prefix} user {user.full_name} or group {chat.id} is not allowed, ignored")
        await manager.reply(msg, f"task is failed: no permission.", now + timedelta(seconds=DELETED_AFTER))
        return

    prefix += f" user {user.full_name}"

    logger.info(f"{prefix} is using sd txt2img func")

    rdb = await manager.get_redis()
    if not rdb:
        logger.warning(f"{prefix} redis is not ready, ignored")
        return

    # check task is full
    task_size = await rdb.llen(QUEUE_NAME) + 1
    if task_size > GLOBAL_TASK_LIMIT:
        logger.warning(f"task queue is full, ignored")
        await manager.reply(msg, f"task is failed: task queue is full.", now + timedelta(seconds=DELETED_AFTER))
        return

    prompt = ""
    if msg.reply_to_message and msg.reply_to_message.text:
        prompt = strip_text_prefix(msg.reply_to_message.text) + "\n"
    prompt += strip_text_prefix(msg.text)

    if not prompt:
        # display help message
        await manager.reply(
            msg,
            "Usage: /image <text>\n <text> is the text you want to convert to image.",
            now + timedelta(seconds=DELETED_AFTER),
        )
        return

    if contains_chinese(prompt):
        try:
            result = ts.translate_text(prompt, to_language="en", translator="google")
            reply_content = f"Prompt:\n{prompt}\n\nTranslated:\n{result}"
            prompt = str(result)
            logger.info(f"{prefix} translate chinese to english: {prompt}")
        except Exception:
            logger.exception("translate failed")
            reply_content = f"Prompt:\n{prompt}\n\nTraslate failed"
    else:
        reply_content = f"Prompt:\n{prompt}"

    task = Task(
        chat_id=chat.id,
        chat_name=chat.full_name,
        user_id=user.id,
        user_name=user.full_name,
        prompt=prompt,
        message_id=msg.message_id,
        reply_message_id=-1,
        reply_content=reply_content,
        created_at=msg.date.timestamp(),
    )

    if task_size > 0:
        reply = await msg.reply(f"task is queued, please wait(~{task_size * 120}s).")
    else:
        reply = await msg.reply("task is queued, please wait(~120s).")
    task.reply_message_id = reply.message_id

    # put task to queue
    try:
        await rdb.lpush(QUEUE_NAME, dumps(task))
        logger.info(f"{prefix} task is queued, size is {task_size}")
    except:
        await reply.edit_text(f"Task is failed: put task to queue failed.")
        logger.exception(f"{prefix} sd txt2img error")


async def worker():
    rdb = await manager.get_redis()
    if not rdb:
        logger.warning(f"redis is not ready, ignored")
        return

    while True:
        await asyncio.sleep(0.1)

        rdb = await manager.get_redis()
        if not rdb:
            logger.warning(f"redis is not ready, ignored")
            await asyncio.sleep(2)
            continue

        raw = await rdb.rpop(QUEUE_NAME)
        if raw:
            try:
                task = Task(**loads(raw))
                await process_task(task)
            except:
                logger.exception("process task error")

        # sleep 1s
        await asyncio.sleep(1)

        # tasks detail
        tasks_size = await rdb.llen(QUEUE_NAME)
        if tasks_size > 1:
            logger.debug(f"task queue size: {tasks_size}")


async def process_task(task: Task):
    prefix = f"chat {task.chat_id}({task.chat_name}) msg {task.message_id} user {task.user_name}"

    config = manager.config
    endpoint = None
    try:
        endpoint = config["sd_api"]["endpoint"]
    except:
        logger.warning(f"{prefix} sd api config is invalid")
        await manager.edit_text(task.chat_id, task.reply_message_id, f"Task is failed: remote service is closed.")
        return
    if not endpoint:
        logger.warning(f"{prefix} sd api endpoint is empty")
        await manager.edit_text(task.chat_id, task.reply_message_id, f"Task is failed: remote service is closed")
        return

    created_at = datetime.fromtimestamp(task.created_at)

    cost = datetime.now() - created_at
    if cost > timedelta(minutes=10):
        logger.warning(f"{prefix} task is expired, ignored")
        await manager.edit_text(task.chat_id, task.reply_message_id, f"Task is expired.")
        return

    # task started
    await manager.edit_text(
        task.chat_id,
        task.reply_message_id,
        f"Task is started(cost {cost.total_seconds()}s/120s)",
    )

    logger.info(f"{prefix} is processing task(cost {cost.total_seconds()}s/120s)")

    try:
        checkpoint = datetime.now()
        resp = await sd_api.txt2img(endpoint, task.prompt, 1)
        cost = datetime.now() - checkpoint
        if "error" in resp:
            logger.warning(f"{prefix} sd txt2img error: {resp['error']['code']} {resp['error']['message']}")
            await manager.edit_text(
                task.chat_id,
                task.reply_message_id,
                f"Task is failed(create before {str(cost)[:-7]}), please try again later.\n\n"
                f"{resp['error']['code']} {resp['error']['message']}",
                datetime.now() + timedelta(seconds=DELETED_AFTER),
            )
            return

        img_raw = resp["image"]
        logger.info(f"{prefix} task is processed(cost {cost.total_seconds()}s/120s).")

        input_file = types.BufferedInputFile(
            base64.b64decode(img_raw.split(",", 1)[0]),
            filename=f"txt2img_{task.chat_id}_{task.user_id}_{task.created_at}.png",
        )
        cost = datetime.now() - created_at

        # delete
        await manager.delete_message(task.chat_id, task.reply_message_id)
        await manager.bot.send_photo(
            task.chat_id,
            input_file,
            reply_to_message_id=task.message_id,
            caption=f"{task.reply_content}\n\ncost {cost.total_seconds()}s",
            disable_notification=True,
            has_spoiler=True,
        )

        logger.info(f"{prefix} image is sent, cost: {str(cost)[:-7]}")
    except Exception as e:
        logger.exception(f"{prefix} sd txt2img error")

        await manager.edit_text(
            task.chat_id,
            task.reply_message_id,
            f"Task is failed(create before {str(cost)[:-7]}), please try again later.\n\n{str(e)}",
            datetime.now() + timedelta(seconds=DELETED_AFTER),
        )
