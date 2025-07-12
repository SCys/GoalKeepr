import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import uuid

from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from orjson import dumps, loads
from PIL import Image


from manager import manager
from utils import comfy_api

from ..utils import strip_text_prefix, chat_completions

logger = manager.logger

# 常量定义
GLOBAL_TASK_LIMIT = 3
QUEUE_NAME = "txt2img"
DELETED_AFTER = 60  # 60s
DEFAULT_TASK_TIMEOUT = 300  # 5 minutes
DEFAULT_GENERATION_TIMEOUT = 300  # 5 minutes
WORKER_SLEEP_INTERVAL = 1  # 1s
WORKER_POLL_INTERVAL = 0.1  # 0.1s
REDIS_RETRY_INTERVAL = 2  # 2s
REDIS_KEY_PREFIX = "image:"

# 图像生成配置
IMAGE_OPTIMIZE_MODEL = "gemini-flash"
DEFAULT_SIZE = "1024x1024"
DEFAULT_STEP = 16
DEFAULT_MODEL = "svdq-int4-flux.1-dev"
DEFAULT_CFG = 1

# 尺寸映射
SIZE_MAPPING = {
    "mini": "128x128",
    "small": "768x768",
    "large": "1024x1280",
}
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
- 若描述模糊，提供多选项（例：*"奇幻场景"可细化为"龙与城堡"或"外星森林"*）。  

5. 仅输出英文的 Prompt，不要输出任何其他内容。

**输出格式**：仅输出优化后的提示词。"""


@dataclass
class TaskMessage:
    """消息数据类"""

    chat_id: int
    chat_name: Optional[str]
    user_id: int
    user_name: Optional[str]
    message_id: int  #
    reply_message_id: int
    reply_content: Optional[str]


@dataclass
class Task:
    """图像生成任务数据类"""

    msg: TaskMessage
    prompt: str
    options: Dict[str, Any]
    created_at: float
    status: str
    job_id: Optional[str]
    task_id: Optional[str]

    async def cancel(self) -> None:
        """取消任务"""
        if not self.job_id:
            return

        endpoint = manager.config["sd_api"]["endpoint"]
        await comfy_api.job_cancel(endpoint, self.job_id)

    async def last_status(self) -> Optional[Dict[str, Any]]:
        """获取任务最后状态"""
        if not self.job_id:
            return

        endpoint = manager.config["sd_api"]["endpoint"]
        return await comfy_api.job_status(endpoint, self.job_id)

    async def download_image(self, filename: str, subfolder: str) -> Optional[bytes]:
        """获取图片字节"""
        if not self.job_id:
            return
        endpoint = manager.config["sd_api"]["endpoint"]
        return await comfy_api.download_image(endpoint, filename, subfolder)

    async def enqueue_task(self, rdb) -> None:
        """将任务加入队列"""
        try:
            await rdb.set(f"{REDIS_KEY_PREFIX}:{self.task_id}", dumps(self))
        except Exception as e:
            logger.error(f"Failed to enqueue task: {e}")
            raise ImageGenerationError("Failed to add task to queue")

    async def dequeue_task(self, rdb) -> None:
        """从队列中删除任务"""
        try:
            await rdb.delete(f"{REDIS_KEY_PREFIX}:{self.task_id}")
        except Exception as e:
            logger.error(f"Failed to dequeue task: {e}")
            raise ImageGenerationError("Failed to remove task from queue")

    @staticmethod
    async def all_tasks(rdb) -> List["Task"]:
        """从队列中获取任务"""
        try:
            keys = await rdb.keys(f"{REDIS_KEY_PREFIX}:*")
            if keys:
                tasks = []
                for key in keys:
                    task_data = loads(await rdb.get(key))
                    # Reconstruct TaskMessage object
                    msg_data = task_data["msg"]
                    task_msg = TaskMessage(
                        chat_id=msg_data["chat_id"],
                        chat_name=msg_data["chat_name"],
                        user_id=msg_data["user_id"],
                        user_name=msg_data["user_name"],
                        message_id=msg_data["message_id"],
                        reply_message_id=msg_data["reply_message_id"],
                        reply_content=msg_data["reply_content"],
                    )
                    # Reconstruct Task object
                    task = Task(
                        msg=task_msg,
                        prompt=task_data["prompt"],
                        options=task_data["options"],
                        created_at=task_data["created_at"],
                        status=task_data["status"],
                        job_id=task_data["job_id"],
                        task_id=task_data["task_id"],
                    )
                    tasks.append(task)
                return tasks
            return []
        except Exception as e:
            logger.error(f"Failed to get all tasks: {e}")
            raise ImageGenerationError("Failed to get all tasks")


class ImageGenerationError(Exception):
    """图像生成相关错误"""

    pass


async def safe_edit_text(chat_id: int, message_id: int, text: str, prefix: str = ""):
    """安全编辑消息文本，检查消息ID是否有效"""
    if message_id <= 0:
        logger.warning(f"{prefix} invalid message_id: {message_id}, skipping edit")
        return

    try:
        await manager.edit_text(chat_id, message_id, text)
    except Exception as e:
        logger.warning(f"{prefix} failed to edit message {message_id}: {e}")


async def safe_delete_message(chat_id: int, message_id: int, prefix: str = ""):
    """安全删除消息，检查消息ID是否有效"""
    if message_id <= 0:
        logger.warning(f"{prefix} invalid message_id: {message_id}, skipping delete")
        return

    try:
        await manager.delete_message(chat_id, message_id)
    except Exception as e:
        logger.warning(f"{prefix} failed to delete message {message_id}: {e}")


class PermissionManager:
    """权限管理类"""

    @staticmethod
    def parse_user_groups_config(config: Dict[str, Any]) -> Tuple[List[int], List[int]]:
        """解析用户和群组权限配置"""
        try:
            users = [int(i) for i in config["image"]["users"].split(",") if i.strip()]
            groups = [int(i) for i in config["image"]["groups"].split(",") if i.strip()]
            return users, groups
        except (KeyError, ValueError) as e:
            logger.error(f"Invalid image users or groups config: {e}")
            raise ImageGenerationError("Invalid permission configuration")

    @staticmethod
    def check_permission(user_id: int, chat_id: int, users: List[int], groups: List[int]) -> bool:
        """检查用户或群组是否有权限"""
        return user_id in users or chat_id in groups


class PromptProcessor:
    """提示词处理类"""

    @staticmethod
    def extract_prompt_from_message(msg: types.Message) -> str:
        """从消息中提取提示词"""
        prompt = ""
        if msg.reply_to_message and msg.reply_to_message.text:
            prompt = strip_text_prefix(msg.reply_to_message.text) + "\n"
        prompt += strip_text_prefix(msg.text)
        return prompt.strip()

    @staticmethod
    def parse_options(prompt: str) -> Tuple[str, Dict[str, Any]]:
        """解析高级选项"""
        options = {
            "size": DEFAULT_SIZE,
            "step": DEFAULT_STEP,
            "model": DEFAULT_MODEL,
            "cfg": DEFAULT_CFG,
        }

        if not prompt.startswith("["):
            return prompt, options

        try:
            end = prompt.index("]")
            options_str = prompt[1:end]
            prompt = prompt[end + 1 :].strip()

            for opt in options_str.split():
                opt = opt.lower().strip()

                if opt.startswith("size:"):
                    size = opt[5:]
                    options["size"] = SIZE_MAPPING.get(size, size)
                elif opt.startswith("step:"):
                    step = max(2, min(50, int(opt[5:])))  # 限制在2-50之间
                    options["step"] = step
                elif opt.startswith("model:"):
                    options["model"] = opt[6:]
                elif opt.startswith("cfg:"):
                    options["cfg"] = int(opt[4:])

            logger.info(f"Parsed options: {options}, prompt: {prompt}")
            return prompt, options

        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse prompt options: {e}")
            return prompt, options

    @staticmethod
    async def optimize_prompt(prompt: str) -> Tuple[str, str]:
        """优化提示词"""
        reply_content = f"Prompt:\n{prompt}"

        if "," in prompt:
            return prompt, reply_content

        try:
            optimized_prompt = await chat_completions(
                [
                    {"role": "system", "content": IMAGE_OPTIMIZE_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model_name=IMAGE_OPTIMIZE_MODEL,
            )
            if optimized_prompt:
                prompt = optimized_prompt
                reply_content = f"Prompt:\n{prompt}"
        except Exception as e:
            logger.warning(f"Prompt optimization failed: {e}")

        return prompt, reply_content


@manager.register("message", Command("image", ignore_case=True, ignore_mention=True))
async def image(msg: types.Message):
    """处理图像生成命令"""
    chat = msg.chat
    user = msg.from_user
    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"
    now = datetime.now()

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    try:
        # 检查权限
        users, groups = PermissionManager.parse_user_groups_config(manager.config)
        if not PermissionManager.check_permission(user.id, chat.id, users, groups):
            logger.warning(f"{prefix} user {user.full_name} or group {chat.id} is not allowed")
            await manager.reply(msg, "you are not allowed to use this command", now + timedelta(seconds=DELETED_AFTER))
            return

        prefix += f" user {user.full_name}"
        logger.info(f"{prefix} is using image func")

        # 获取Redis连接并检查队列容量
        rdb = await manager.get_redis()
        if not rdb:
            logger.warning(f"{prefix} redis is not ready, ignored")
            await manager.reply(msg, "internal error", now + timedelta(seconds=DELETED_AFTER))
            return

        tasks = await Task.all_tasks(rdb)
        task_size = len(tasks)
        if task_size >= GLOBAL_TASK_LIMIT:
            logger.warning(f"{prefix} task queue is full, ignored")
            await manager.reply(msg, "task queue is full, please try again later", now + timedelta(seconds=DELETED_AFTER))
            return

        # 处理提示词
        raw_prompt = PromptProcessor.extract_prompt_from_message(msg)
        if not raw_prompt:
            logger.warning(f"{prefix} invalid prompt, ignored")
            await manager.reply(msg, "invalid prompt, please send a valid prompt", now + timedelta(seconds=DELETED_AFTER))
            return

        # 解析选项和优化提示词
        prompt, options = PromptProcessor.parse_options(raw_prompt)
        prompt, reply_content = await PromptProcessor.optimize_prompt(prompt)

        # 创建任务
        task = Task(
            msg=TaskMessage(
                chat_id=chat.id,
                chat_name=chat.full_name,
                user_id=user.id,
                user_name=user.full_name,
                message_id=msg.message_id,
                reply_message_id=msg.reply_to_message.message_id if msg.reply_to_message else -1,
                reply_content=reply_content,
            ),
            prompt=prompt,
            options=options,
            created_at=datetime.now().timestamp(),
            status="queued",
            job_id=None,
            task_id=str(uuid.uuid4()),
        )

        # 将任务加入队列
        await task.enqueue_task(rdb)

        # 发送通知并更新任务
        message = f"Task is queued, please wait(~{task_size * 35}s)."
        reply = await msg.reply(message)
        task.msg.reply_message_id = reply.message_id

        # 更新任务到Redis，确保reply_message_id被保存
        await task.enqueue_task(rdb)

        logger.info(f"{prefix} task is queued, size is {task_size + 1}")
    except ImageGenerationError as e:
        logger.warning(f"{prefix} {str(e)}")
        await manager.reply(
            msg,
            f"task is failed: {str(e)}",
            now + timedelta(seconds=DELETED_AFTER),
        )
    except Exception as e:
        logger.exception(f"{prefix} task is failed:{str(e)}")
        await manager.reply(msg, f"task is failed:{str(e)}", now + timedelta(seconds=DELETED_AFTER))


async def process_task(task: Task):
    """处理单个图像生成任务"""
    prefix = f"chat {task.msg.chat_id}({task.msg.chat_name}) msg {task.msg.message_id} user {task.msg.user_name}"

    # 检查配置
    endpoint = manager.config["sd_api"]["endpoint"]
    if not endpoint:
        task.status = "completed"
        logger.warning(f"{prefix} image endpoint is empty")
        await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: remote service is closed", prefix)
        return

    rdb = await manager.get_redis()
    if not rdb:
        task.status = "completed"
        logger.warning(f"{prefix} redis is not ready, ignored")
        await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: redis is not ready", prefix)
        return

    logger.info(f"{prefix} task {task.task_id} status: {task.status}")

    try:
        # 根据任务状态进行分类处理
        if task.status == "queued":
            await handle_queued_task(task, endpoint, prefix)
        elif task.status == "submitted":
            await handle_submitted_task(task, endpoint, prefix)
        elif task.status in ["running", "pending"]:
            await handle_processing_task(task, endpoint, prefix)
        elif task.status == "not_found":
            await handle_not_found_task(task, prefix)
        elif task.status == "completed":
            pass
        else:
            # 未知状态，标记为完成
            logger.warning(f"{prefix} unknown task status: {task.status}")
            task.status = "completed"

        # 更新任务状态到 Redis
        await rdb.set(f"{REDIS_KEY_PREFIX}:{task.task_id}", dumps(task))

    except Exception as e:
        # 处理任何异常，标记任务为完成
        cost = datetime.now() - datetime.fromtimestamp(task.created_at)
        logger.exception(f"{prefix} process task error: {e}")
        await safe_edit_text(
            task.msg.chat_id, task.msg.reply_message_id, f"Task is failed(cost {cost.total_seconds():.1f}s), please try again later.\n\n{str(e)}", prefix
        )
        task.status = "completed"
        await rdb.set(f"{REDIS_KEY_PREFIX}:{task.task_id}", dumps(task))

    if task.status == "completed":
        await handle_completed_task(task, endpoint, prefix, rdb)


async def handle_queued_task(task: Task, endpoint: str, prefix: str):
    """处理队列中的任务"""
    # 检查任务是否过期
    created_at = datetime.fromtimestamp(task.created_at)
    cost = datetime.now() - created_at

    if cost > timedelta(seconds=DEFAULT_TASK_TIMEOUT):
        logger.warning(f"{prefix} task is expired, ignored")
        await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is expired.", prefix)
        task.status = "completed"
        return

    # 更新任务状态
    await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, f"Task is started(cost {cost.total_seconds():.1f}s)", prefix)

    logger.info(f"{prefix} is processing task(cost {cost.total_seconds():.1f}s)")

    # 获取任务参数
    prompt = task.prompt.strip()
    size = task.options.get("size", DEFAULT_SIZE)
    step = task.options.get("step", DEFAULT_STEP)
    model = task.options.get("model", DEFAULT_MODEL)
    cfg = task.options.get("cfg", DEFAULT_CFG)

    try:
        # 尝试生成图片，获得 job_id
        job_id = await asyncio.wait_for(
            comfy_api.generate_image(endpoint, model, prompt, size, step, cfg),
            timeout=DEFAULT_GENERATION_TIMEOUT,
        )

        if not job_id:
            logger.warning(f"{prefix} image job is empty, ignored")
            await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: create image job failed", prefix)
            task.status = "completed"
            return

        task.status = "submitted"
        task.job_id = job_id

        logger.info(f"{prefix} image job is created with job_id: {job_id}")

    except asyncio.TimeoutError:
        logger.warning(f"{prefix} image job timeout after {DEFAULT_GENERATION_TIMEOUT}s")
        await safe_edit_text(
            task.msg.chat_id, task.msg.reply_message_id, f"Task is failed: http timeout after {DEFAULT_GENERATION_TIMEOUT}s, please try again later.", prefix
        )
        task.status = "completed"
    except comfy_api.ComfyAPIError as e:
        logger.warning(f"{prefix} comfy api error: {e}")
        await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, f"Task is failed: {str(e)}", prefix)
        task.status = "completed"


async def handle_submitted_task(task: Task, endpoint: str, prefix: str):
    """处理已提交的任务"""
    if not task.job_id:
        logger.warning(f"{prefix} submitted task has no job_id")
        task.status = "completed"
        return

    try:
        # 获取任务状态
        status_info = await comfy_api.job_status(endpoint, task.job_id)
        if status_info:
            task.status = status_info.get("status", "not_found")
            logger.info(f"{prefix} task status updated to: {task.status}")
        else:
            logger.warning(f"{prefix} failed to get task status")
            task.status = "not_found"

    except comfy_api.ComfyAPIError as e:
        logger.warning(f"{prefix} comfy api error when getting status: {e}")
        task.status = "not_found"


async def handle_processing_task(task: Task, endpoint: str, prefix: str):
    """处理正在运行或等待中的任务"""
    if not task.job_id:
        logger.warning(f"{prefix} processing task has no job_id")
        task.status = "completed"
        return

    try:
        # 获取任务状态
        status_info = await comfy_api.job_status(endpoint, task.job_id)
        if status_info:
            old_status = task.status
            task.status = status_info.get("status", "not_found")

            if old_status != task.status:
                logger.info(f"{prefix} task status changed from {old_status} to {task.status}")

                # 更新用户界面
                cost = datetime.now() - datetime.fromtimestamp(task.created_at)
                await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, f"Task is {task.status}(cost {cost.total_seconds():.1f}s)", prefix)
        else:
            logger.warning(f"{prefix} failed to get task status")
            task.status = "not_found"

    except comfy_api.ComfyAPIError as e:
        logger.warning(f"{prefix} comfy api error when getting status: {e}")
        task.status = "not_found"


async def handle_completed_task(task: Task, endpoint: str, prefix: str, rdb):
    """处理完成的任务"""
    if not task.job_id:
        logger.warning(f"{prefix} completed task {task.task_id} has no job_id")
        await task.dequeue_task(rdb)
        return

    try:
        info = await comfy_api.get_job_info(endpoint, task.job_id)
        # status is completed
        status_str = info.get("status", {}).get("status_str", "")
        if status_str == "error":
            logger.warning(f"{prefix} completed task {task.task_id} status is error, ignored")
            await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: status is error", prefix)
            await task.dequeue_task(rdb)
            return

        # outputs first key, like 48/50/other number ? is outputs
        images = info.get("outputs", {}).get("50", {}).get("images", [])
        if not images:
            logger.warning(f"{prefix} completed task {task.task_id} has no image, ignored: {info['outputs']}")
            await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: empty image result", prefix)
            await task.dequeue_task(rdb)
            return

        filename = images[0].get("filename")
        subfolder = images[0].get("subfolder")

        # 获取生成的图片
        img_raw = await task.download_image(filename, subfolder)

        if not img_raw:
            logger.warning(f"{prefix} completed task {task.task_id} image is empty, ignored")
            await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: empty image result", prefix)
            await task.dequeue_task(rdb)
            return

        # 计算耗时
        cost = datetime.now() - datetime.fromtimestamp(task.created_at)

        # 准备发送图像
        input_file = types.BufferedInputFile(img_raw, filename=filename)

        size = task.options.get("size", DEFAULT_SIZE)
        step = task.options.get("step", DEFAULT_STEP)

        image_url = f"https://one.iscys.com/Comfyu/{subfolder}/{filename}"

        if task.msg.reply_message_id != -1:
            await manager.bot.edit_message_text(
                chat_id=task.msg.chat_id,
                message_id=task.msg.reply_message_id,
                text=f"Size: {size} Step: {step} Cost: {cost.total_seconds():.1f}s",
            )

            await manager.bot.send_photo(
                chat_id=task.msg.chat_id,
                photo=input_file,
                reply_to_message_id=task.msg.message_id,
                caption=f"{task.msg.reply_content}",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="Original|原始图片", url=image_url)]]),
            )
        else:
            await manager.bot.send_photo(
                chat_id=task.msg.chat_id,
                photo=input_file,
                reply_to_message_id=task.msg.message_id,
                caption=f"Size: {size} Step: {step} Cost: {cost.total_seconds():.1f}s\n\n{task.msg.reply_content}",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="Original|原始图片", url=image_url)]]),
            )

        logger.info(f"{prefix} completed task {task.task_id} image is sent, cost: {cost.total_seconds():.1f}s")

    except TelegramBadRequest as e:
        logger.error(f"{prefix} completed task {task.task_id} send photo error: {e}")
        await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, f"Task is failed: failed to send image. {str(e)}", prefix)
    except comfy_api.ComfyAPIError as e:
        logger.warning(f"{prefix} completed task {task.task_id} comfy api error: {e}")
        await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, f"Task is failed: {str(e)}", prefix)

    # 无论成功失败，都从队列中删除任务
    await task.dequeue_task(rdb)


async def handle_not_found_task(task: Task, prefix: str):
    """处理未找到的任务"""
    logger.warning(f"{prefix} task {task.task_id} not found on remote service")
    await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: task not found on remote service", prefix)
    task.status = "completed"


async def worker():
    """图像生成工作进程"""
    try:
        logger.info("image worker is started")

        while True:
            await asyncio.sleep(WORKER_POLL_INTERVAL)

            try:
                rdb = await manager.get_redis()
                if not rdb:
                    logger.warning("redis is not ready, ignored")
                    await asyncio.sleep(REDIS_RETRY_INTERVAL)
                    continue

                tasks = await Task.all_tasks(rdb)
                if tasks:
                    # logger.info(f"image worker is processing {len(tasks)} tasks")
                    for task in tasks:
                        await process_task(task)
                        await asyncio.sleep(WORKER_SLEEP_INTERVAL)

                # 工作循环间隔
                await asyncio.sleep(WORKER_SLEEP_INTERVAL)

            except Exception as e:
                logger.exception(f"worker loop error: {e}")
                await asyncio.sleep(REDIS_RETRY_INTERVAL)

    except Exception as e:
        logger.exception(f"worker startup error: {e}")
