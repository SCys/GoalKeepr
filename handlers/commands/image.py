import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from orjson import dumps, loads

import translators as ts
from manager import manager
from utils import comfy_api

from ..utils import strip_text_prefix, contains_chinese, chat_completions

logger = manager.logger

GLOBAL_TASK_LIMIT = 3
QUEUE_NAME = "txt2img"
DELETED_AFTER = 3  # 3s


IMAGE_OPTIMIZE_MODEL = "gemini-flash"
IMAGE_OPTIMIZE_PROMPT = """你是一个专为Flux.1 Dev模型设计的提示词优化专家。用户提供原始绘画描述后，你需要按以下规则优化并输出最终提示词：  

1. **明确主体与细节**  
- 添加具体特征（如服饰、材质、动作、表情），使用形容词强化画面感（例：*glowing neon lights, intricate lace details*）。  
- 若涉及人物，需指定年龄、姿态、服装风格，并加入防止畸变的负面词（如*extra fingers, deformed hands*）。  

2. **场景与风格强化**  
- 补充环境细节（光线、季节、背景物体），指定艺术风格（*cinematic lighting, cyberpunk, Studio Ghibli*）。  
- 若需文字生成，用*quotation marks*标注文本内容并描述排版（例：*chalk-written on a blackboard*）。  

3. **技术参数适配**  
- 推荐添加质量关键词（*ultra-detailed, 8K resolution, Unreal Engine render*）与镜头类型（*wide-angle, macro*）。  

4. **逻辑与创意引导**  
- 将抽象概念转化为具象元素（例：*"hope" → sunlight breaking through storm clouds*）。  
- 若描述模糊，提供多选项（例：*“奇幻场景”可细化为“龙与城堡”或“外星森林”*）。  

5. 仅输出英文的 Prompt，不要输出任何其他内容。

**输出格式**：仅输出优化后的提示词。"""



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
    options: dict


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

    # prompt as : [size:icon/large/horizontal step:4/8/16 more_detail] <raw prompt text>
    if not prompt:
        # display help message
        await manager.reply(
            msg,
            "Usage: /image [size:icon/large/horizontal step:4/8/16 more_detail] <text>\n\n",
        )
        return

    # advanced options

    # get options
    size = "1024x1024"
    step = 12
    model = "flux1-dev-fp8.safetensors"
    cfg = 1
    if prompt.startswith("["):
        try:
            end = prompt.index("]")
            options = prompt[1:end]
            prompt = prompt[end + 1 :]
            for opt in options.split(" "):
                opt = opt.lower().strip()

                if opt.startswith("size:"):
                    size = opt[5:]
                elif opt.startswith("step:"):
                    step = int(opt[5:])

                    if step > 50:
                        step = 50
                    if step < 2:
                        step = 2
                elif opt.startswith("model:"):
                    model = opt[6:]
                elif opt.startswith("cfg:"):
                    cfg = int(opt[4:])

            # convert size
            if size == "mini":
                size = "128x128"  # icon
            elif size == "small":
                size = "768x768"
            elif size == "large":
                size = "1024x1280"
            else:
                size = "1024x1024"

            prompt = prompt.strip()

            logger.info(f"{prefix} more options: size={size} step={step} prompt={prompt} model={model} cfg={cfg}")
        except:
            logger.exception(f"{prefix} parse prompt error")

    if "," not in prompt:
        try:
            prompt_new = await chat_completions([
                {"role": "system", "content": IMAGE_OPTIMIZE_PROMPT},
                {"role": "user", "content": prompt},
            ], model_name=IMAGE_OPTIMIZE_MODEL)
            if prompt_new:
                prompt = prompt_new

            reply_content = f"Prompt:\n{prompt}"

        except Exception:
            logger.exception("translate failed")
            reply_content = f"Prompt:\n{prompt}"

    # if contains_chinese(prompt):
    #     try:
    #         reply_content = ts.translate_text(prompt, to_language="en", translator="google")
    #     except:
    #         logger.exception("translate failed")
    #         reply_content = f"Prompt:\n{prompt}"
    # else:
    #     reply_content = prompt

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
        options={
            "size": size,
            "step": step,
            "model": model,
            "cfg": cfg,
        },
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

    prompt = task.prompt.strip()
    size = task.options.get("size", "512x512")
    step = task.options.get("step", 12)
    model = task.options.get("model", "flux1-dev-fp8.safetensors")
    cfg = task.options.get("cfg", 1)

    try:
        img_raw = await comfy_api.generate_image(endpoint, model, prompt, size, step, cfg)
        cost = datetime.now() - created_at

        # img_raw = resp["image"]
        logger.info(f"{prefix} task is processed(cost {cost.total_seconds()}s/120s).")

        if not img_raw:
            logger.warning(f"{prefix} image is empty, ignored")
            return

        input_file = types.BufferedInputFile(
            img_raw,
            # base64.b64decode(img_raw.split(",", 1)[0]),
            filename=f"txt2img_{task.chat_id}_{task.user_id}_{task.created_at}.png",
        )
        cost = datetime.now() - created_at

        caption = f"{task.reply_content}\n\n" f"Size: {size} Step: {step}\n" f"Cost: {str(cost)[:-7]}s"

        await manager.delete_message(task.chat_id, task.reply_message_id)
    except Exception as e:
        logger.exception(f"{prefix} sd txt2img error")
        await manager.edit_text(
            task.chat_id,
            task.reply_message_id,
            f"Task is failed(create before {str(cost)[:-7]}), please try again later.\n\n{str(e)}",
        )
        return

    try:
        await manager.bot.send_photo(
            task.chat_id,
            input_file,
            reply_to_message_id=task.message_id,
            caption=caption[:1023],
            disable_notification=True,
            has_spoiler=True,
        )
        logger.info(f"{prefix} image is sent, cost: {str(cost)[:-7]}")
    except TelegramBadRequest as e:
        logger.exception(f"{prefix} send photo error")


async def worker():
    rdb = await manager.get_redis()
    if not rdb:
        logger.warning(f"redis is not ready, ignored")
        return
    
    logger.info(f"image worker is started")

    while True:
        await asyncio.sleep(0.1)

        rdb = await manager.get_redis()
        if not rdb:
            logger.warning(f"redis is not ready, ignored")
            await asyncio.sleep(2)
            continue

        raw = await rdb.rpop(QUEUE_NAME)
        if raw:
            logger.info(f"image worker is processing task")

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
