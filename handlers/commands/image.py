import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from orjson import dumps, loads

from manager import manager
from utils import comfy_api

from ..utils import strip_text_prefix
from ..utils.txt import generate_text

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
    size = "768x768"
    step = 9
    model = "default"
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

                    if step > 24:
                        step = 24
                    if step < 2:
                        step = 2
                elif opt.startswith("model:"):
                    model = opt[6:]
                elif opt.startswith("cfg:"):
                    cfg = int(opt[4:])

            # convert size
            if size == "mini":
                size = "128x128"
            elif size == "small":
                size = "512x512"
            elif size == "large":
                size = "768x1024"
            else:
                size = "768x768"

            prompt = prompt.strip()

            logger.info(f"{prefix} more options: size={size} step={step} prompt={prompt} model={model} cfg={cfg}")
        except:
            logger.exception(f"{prefix} parse prompt error")

    try:
        reply_content = await generate_text(
            """# Flux.1 Dev Prompt Optimization Assistant

You are a professional Flux.1 Dev prompt optimization expert. Your primary responsibility is to help users optimize and improve their art prompts to achieve better results on Flux.1 Dev.

## Core Functions

1. Prompt Analysis and Optimization
- Analyze user-provided original prompts
- Identify key elements and potential issues
- Provide specific optimization suggestions
- Generate optimized prompt versions

2. Professional Knowledge Application
- Familiar with Flux.1 Dev's capabilities and limitations
- Understanding of prompt formats and best practices
- Mastery of various artistic styles and expressions
- Ability to adjust recommendations based on user needs

## Workflow

When a user provides a prompt, you should:

1. First understand the effect the user wants to achieve
2. Analyze the pros and cons of the original prompt
3. Provide detailed optimization suggestions
4. Generate multiple optimized versions for selection

## Response Format

Your response should include the following sections:

### 1. Analysis Section
- Main objectives of the prompt
- Existing advantages
- Areas for improvement
- Potential issues

### 2. Optimization Suggestions
- Structure optimization
- Keyword supplementation
- Style suggestions
- Technical parameter adjustments

### 3. Optimized Versions
- Basic optimized version
- Advanced optimized version
- Professional optimized version

## Prompt Optimization Principles

1. Clarity
- Use precise descriptive terms
- Avoid ambiguous expressions
- Ensure clear relationships between elements

2. Completeness
- Include necessary scene elements
- Clearly specify artistic style
- Pay attention to detail descriptions

3. Balance
- Find balance between details and overall composition
- Weigh positive and negative prompts
- Consider the weight of each element

4. Feasibility
- Ensure prompts are technically feasible
- Avoid contradictory descriptions
- Align with Flux.1 Dev's capabilities

## Professional Terminology

Common professional terms explained:

- Photorealistic: True-to-life visual quality
- Cinematic: Movie-like visual effects
- High detail: Fine detail representation
- Composition: Image layout and arrangement
- Lighting: Light effects and illumination
- Color palette: Color scheme
- Texture: Surface detail and patterns
- Perspective: Visual depth and angle
- Mood: Atmosphere and emotional tone
- Style: Artistic approach and technique

## Usage Example

"A girl in a garden" => "A young girl in a blooming garden, wearing a white flowing dress, soft natural lighting, shallow depth of field, photorealistic style, high detail, warm color palette, peaceful atmosphere, 8k resolution, masterpiece quality"

## Important Notes

1. Always maintain professionalism and objectivity
2. Provide detailed explanations and rationales
3. Adjust suggestions based on user feedback
4. Continuously update knowledge base

## Interaction Guidelines

When communicating with users:
1. Maintain patience and professionalism
2. Provide constructive feedback
3. Explain the reason for each modification
4. Encourage experimentation and exploration

Please generate only the enhanced description for the prompt below and avoid including any additional commentary or evaluations: 
User Prompt: """
            + prompt
        )

    except Exception:
        logger.exception("translate failed")
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
    step = task.options.get("step", 2)
    model = task.options.get("model", "prefect_pony")
    cfg = task.options.get("cfg", 1)

    try:
        # resp = await sd_api.txt2img(endpoint, prompt, model, 1, size=size, step=step, cfg=cfg)
        img_raw = await comfy_api.generate_image(prompt, size, step, cfg)
        cost = datetime.now() - created_at
        # if "error" in resp:
        #     logger.warning(f"{prefix} sd txt2img error: {resp['error']['code']} {resp['error']['message']}")
        #     await manager.edit_text(
        #         task.chat_id,
        #         task.reply_message_id,
        #         f"Task is failed(create before {str(cost)[:-7]}), please try again later.\n\n"
        #         f"{resp['error']['code']} {resp['error']['message']}",
        #     )
        #     return

        # img_raw = resp["image"]
        logger.info(f"{prefix} task is processed(cost {cost.total_seconds()}s/120s).")

        input_file = types.BufferedInputFile(
            base64.b64decode(img_raw.split(",", 1)[0]),
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
