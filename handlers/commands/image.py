import asyncio
import base64
import hmac
import hashlib
import os
import re
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse
import uuid

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from telethon import events, types, Button, errors
from orjson import dumps, loads

from manager import manager
from utils import comfy_api
from utils.comfy_workflow import WORKFLOWS

from ..utils import strip_text_prefix, chat_completions

logger = manager.logger


def encrypt_url_for_imgproxy(url: str, encryption_key: str) -> str:
    """
    使用 AES-256-CBC 加密 URL 用于 imgproxy
    """
    try:
        try:
            key_bytes = base64.b64decode(encryption_key)
        except Exception:
            key_bytes = encryption_key.encode('utf-8')
            if len(key_bytes) != 32:
                key_bytes = hashlib.sha256(key_bytes).digest()
        
        if len(key_bytes) != 32:
            raise ValueError(f"加密密钥必须是32字节，当前为{len(key_bytes)}字节")
        
        iv = os.urandom(16)
        
        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        
        url_bytes = url.encode('utf-8')
        pad_length = 16 - (len(url_bytes) % 16)
        padded_url = url_bytes + bytes([pad_length] * pad_length)
        
        ciphertext = encryptor.update(padded_url) + encryptor.finalize()
        
        encrypted_data = iv + ciphertext
        encrypted_url = base64.urlsafe_b64encode(encrypted_data).decode('utf-8').rstrip('=')
        
        return encrypted_url
    except Exception as e:
        logger.error(f"URL加密失败: {e}")
        raise


def generate_imgproxy_url(original_url: str, domain: str, key: str, salt: str = "", encryption_key: Optional[str] = None) -> str:
    """
    使用 imgproxy 生成签名 URL 或加密 URL
    """
    if not domain:
        return original_url
    
    if encryption_key:
        try:
            encrypted_url = encrypt_url_for_imgproxy(original_url, encryption_key)
            domain = domain.rstrip('/')
            imgproxy_url = f"{domain}/{encrypted_url}"
            return imgproxy_url
        except Exception as e:
            logger.warning(f"URL加密失败，回退到签名模式: {e}")
    
    if not key:
        return original_url
    
    if original_url.startswith("local://"):
        path = f"/{original_url}"
    else:
        try:
            parsed = urlparse(original_url)
            path = parsed.path
            if not path.startswith("/"):
                path = f"/{path}"
        except Exception:
            if "://" in original_url:
                parts = original_url.split("://", 1)[1].split("/", 1)
                path = f"/{parts[1]}" if len(parts) > 1 else "/"
            else:
                path = original_url if original_url.startswith("/") else f"/{original_url}"
    
    try:
        key_bytes = base64.b64decode(key)
    except Exception:
        key_bytes = key.encode('utf-8')
    
    salt_bytes = b''
    if salt:
        try:
            salt_bytes = base64.b64decode(salt)
        except Exception:
            salt_bytes = salt.encode('utf-8')
    
    if salt_bytes:
        inner_hash = hmac.new(salt_bytes, path.encode('utf-8'), hashlib.sha256).digest()
        signature = hmac.new(key_bytes, inner_hash, hashlib.sha256).digest()
    else:
        signature = hmac.new(key_bytes, path.encode('utf-8'), hashlib.sha256).digest()
    
    signature_b64 = base64.urlsafe_b64encode(signature).decode('utf-8').rstrip('=')
    
    domain = domain.rstrip('/')
    imgproxy_url = f"{domain}/{signature_b64}{path}"
    
    return imgproxy_url


# 常量定义
GLOBAL_TASK_LIMIT = 3
QUEUE_NAME = "txt2img"
DELETED_AFTER = 60  # 60s
DEFAULT_TASK_TIMEOUT = 300  # 5 minutes
DEFAULT_GENERATION_TIMEOUT = 300  # 5 minutes
WORKER_SLEEP_INTERVAL = 1  # 1s
WORKER_POLL_INTERVAL = 0.1  # 0.1s
WORKER_IDLE_INTERVAL = 2  # 2s
REDIS_RETRY_INTERVAL = 2  # 2s
REDIS_KEY_PREFIX = "image:"
TASK_LOCK_TTL = 180  # 3分钟，避免任务并发重复处理

# 图像生成配置
IMAGE_OPTIMIZE_MODELS = ["deepseek-r1", "gemini-flash"]
DEFAULT_SIZE = "836x1216"
DEFAULT_STEP = 16
DEFAULT_MODEL = "zimage"
DEFAULT_CFG = 1
MAX_CFG = 20.0
MAX_STEPS = 50
MIN_STEPS = 2
MAX_SIZE_EDGE = 4096
MIN_SIZE_EDGE = 64

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


def _is_valid_size(size: str) -> bool:
    if not re.match(r"^\d{2,4}x\d{2,4}$", size):
        return False
    width, height = size.lower().split("x")
    try:
        w = int(width)
        h = int(height)
    except ValueError:
        return False
    return MIN_SIZE_EDGE <= w <= MAX_SIZE_EDGE and MIN_SIZE_EDGE <= h <= MAX_SIZE_EDGE


def _allowed_models() -> set:
    return set(WORKFLOWS.keys())


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
            tasks: List["Task"] = []
            batch: List[bytes] = []
            async for key in rdb.scan_iter(f"{REDIS_KEY_PREFIX}:*"):
                batch.append(key)
                if len(batch) >= 100:
                    tasks.extend(await Task._load_tasks(rdb, batch))
                    batch = []
            if batch:
                tasks.extend(await Task._load_tasks(rdb, batch))
            return tasks
        except Exception as e:
            logger.error(f"Failed to get all tasks: {e}")
            raise ImageGenerationError("Failed to get all tasks")

    @staticmethod
    async def _load_tasks(rdb, keys: List[bytes]) -> List["Task"]:
        tasks: List["Task"] = []
        if not keys:
            return tasks
        values = await rdb.mget(*keys)
        for key, task_raw in zip(keys, values):
            if not task_raw:
                continue
            try:
                task_data = loads(task_raw)
            except Exception as e:
                logger.warning(f"Invalid task data {key}: {e}")
                continue
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
    def parse_user_groups_config(config: ConfigParser) -> Tuple[List[int], List[int]]:
        """解析用户和群组权限配置"""
        try:
            users_val = config["image"].get("users", "")
            groups_val = config["image"].get("groups", "")
            users = (
                [int(i) for i in users_val] if isinstance(users_val, (list, tuple)) else
                [int(i) for i in str(users_val).split(",") if str(i).strip()]
            )
            groups = (
                [int(i) for i in groups_val] if isinstance(groups_val, (list, tuple)) else
                [int(i) for i in str(groups_val).split(",") if str(i).strip()]
            )
            # 过滤无效值
            users = [i for i in users if i > 0]
            groups = [i for i in groups if i > 0]
            return users, groups
        except (KeyError, ValueError) as e:
            logger.error(f"Invalid image users or groups config: {e}")
            # Raise or return empty to allow defaults?
            return [], []

    @staticmethod
    def check_permission(user_id: int, chat_id: int, users: List[int], groups: List[int]) -> bool:
        """检查用户或群组是否有权限"""
        if not users and not groups:
            return False
        return user_id in users or chat_id in groups


class PromptProcessor:
    """提示词处理类"""

    @staticmethod
    async def extract_prompt_from_message(event: events.NewMessage.Event) -> str:
        """从消息中提取提示词"""
        prompt = ""
        reply = await event.get_reply_message()
        if reply and reply.text:
            prompt = strip_text_prefix(reply.text) + "\n"
        prompt += strip_text_prefix(event.text)
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
                    size = SIZE_MAPPING.get(opt[5:], opt[5:])
                    if _is_valid_size(size):
                        options["size"] = size
                    else:
                        logger.warning(f"Invalid size option: {size}")
                elif opt.startswith("step:"):
                    try:
                        step = int(opt[5:])
                        options["step"] = max(MIN_STEPS, min(MAX_STEPS, step))
                    except ValueError:
                        logger.warning(f"Invalid step option: {opt}")
                elif opt.startswith("model:"):
                    model = opt[6:]
                    if model in _allowed_models():
                        options["model"] = model
                    else:
                        logger.warning(f"Invalid model option: {model}")
                elif opt.startswith("cfg:"):
                    try:
                        cfg = float(opt[4:])
                        options["cfg"] = max(1.0, min(MAX_CFG, cfg))
                    except ValueError:
                        logger.warning(f"Invalid cfg option: {opt}")

            logger.info(f"Parsed options: {options}, prompt: {prompt}")
            return prompt, options

        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse prompt options: {e}")
            return prompt, options

    @staticmethod
    async def optimize_prompt(prompt: str) -> Tuple[str, str]:
        """优化提示词"""
        reply_content = prompt

        if "," in prompt:
            return prompt, reply_content

        for model in IMAGE_OPTIMIZE_MODELS:
            try:
                optimized_prompt = await chat_completions(
                    [
                        {"role": "system", "content": IMAGE_OPTIMIZE_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    model_name=model,
                )
                if optimized_prompt:
                    logger.info(f"Prompt optimized by {model}: {prompt} => {optimized_prompt}")

                    prompt = optimized_prompt
                    reply_content = prompt
                    break

            except Exception as e:
                logger.warning(f"Prompt optimization failed: {e}")

        return prompt, reply_content


@manager.register("message", pattern=r"(?i)^/image(?: .*)?$")
async def image(event: events.NewMessage.Event):
    """处理图像生成命令"""
    chat = await event.get_chat()
    sender = await event.get_sender()
    
    # Prefix for logging
    chat_title = getattr(chat, 'title', 'Private')
    sender_name = manager.username(sender)
    prefix = f"chat {event.chat_id}({chat_title}) msg {event.id}"
    now = datetime.now()

    if not sender:
        logger.warning(f"{prefix} message without user, ignored")
        return

    try:
        # 检查权限
        users, groups = PermissionManager.parse_user_groups_config(manager.config)
        # If config is missing/error, we might want to fail safe.
        if not PermissionManager.check_permission(sender.id, event.chat_id, users, groups):
            logger.warning(f"{prefix} user {sender_name} or group {event.chat_id} is not allowed")
            await manager.reply(event, "you are not allowed to use this command", auto_deleted_at=now + timedelta(seconds=DELETED_AFTER))
            return

        prefix += f" user {sender_name}"
        logger.info(f"{prefix} is using image func")

        # 获取Redis连接并检查队列容量
        rdb = await manager.get_redis()
        if not rdb:
            logger.warning(f"{prefix} redis is not ready, ignored")
            await manager.reply(event, "internal error", auto_deleted_at=now + timedelta(seconds=DELETED_AFTER))
            return

        tasks = await Task.all_tasks(rdb)
        task_size = len(tasks)
        if task_size >= GLOBAL_TASK_LIMIT:
            logger.warning(f"{prefix} task queue is full, ignored")
            await manager.reply(event, "task queue is full, please try again later", auto_deleted_at=now + timedelta(seconds=DELETED_AFTER))
            return

        # 处理提示词
        raw_prompt = await PromptProcessor.extract_prompt_from_message(event)
        if not raw_prompt:
            logger.warning(f"{prefix} invalid prompt, ignored")
            await manager.reply(event, "invalid prompt, please send a valid prompt", auto_deleted_at=now + timedelta(seconds=DELETED_AFTER))
            return

        # 解析选项和优化提示词
        prompt, options = PromptProcessor.parse_options(raw_prompt)

        if options.get("model", DEFAULT_MODEL) == "zimage":
            reply_content = prompt
        else:
            prompt, reply_content = await PromptProcessor.optimize_prompt(prompt)

        # 创建任务
        reply_msg = await event.get_reply_message()
        reply_id = reply_msg.id if reply_msg else -1

        task = Task(
            msg=TaskMessage(
                chat_id=event.chat_id,
                chat_name=chat_title,
                user_id=sender.id,
                user_name=sender_name,
                message_id=event.id,
                reply_message_id=reply_id,
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
        reply = await event.reply(message)
        task.msg.reply_message_id = reply.id

        # 更新任务到Redis，确保reply_message_id被保存
        await task.enqueue_task(rdb)

        logger.info(f"{prefix} task is queued, size is {task_size + 1}")
    except ImageGenerationError as e:
        logger.warning(f"{prefix} {str(e)}")
        await manager.reply(
            event,
            f"task is failed: {str(e)}",
            auto_deleted_at=now + timedelta(seconds=DELETED_AFTER),
        )
    except Exception as e:
        logger.exception(f"{prefix} task is failed:{str(e)}")
        await manager.reply(event, f"task is failed:{str(e)}", auto_deleted_at=now + timedelta(seconds=DELETED_AFTER))


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

    lock_key = f"{REDIS_KEY_PREFIX}:lock:{task.task_id}"
    try:
        locked = await rdb.set(lock_key, "1", nx=True, ex=TASK_LOCK_TTL)
        if not locked:
            logger.debug(f"{prefix} task {task.task_id} is locked, skip")
            return

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
                logger.warning(f"{prefix} unknown task status: {task.status}, and force set to completed")
                task.status = "completed"

            await rdb.set(f"{REDIS_KEY_PREFIX}:{task.task_id}", dumps(task))

        except Exception as e:
            cost = datetime.now() - datetime.fromtimestamp(task.created_at)
            logger.exception(f"{prefix} process task error: {e}")
            await safe_edit_text(
                task.msg.chat_id, task.msg.reply_message_id, f"Task is failed(cost {cost.total_seconds():.1f}s), please try again later.\n\n{str(e)}", prefix
            )
            task.status = "completed"
            await rdb.set(f"{REDIS_KEY_PREFIX}:{task.task_id}", dumps(task))

        if task.status == "completed":
            await handle_completed_task(task, endpoint, prefix, rdb)
    finally:
        try:
            await rdb.delete(lock_key)
        except Exception as e:
            logger.debug(f"{prefix} unlock failed: {e}")


async def handle_queued_task(task: Task, endpoint: str, prefix: str):
    created_at = datetime.fromtimestamp(task.created_at)
    cost = datetime.now() - created_at

    if cost > timedelta(seconds=DEFAULT_TASK_TIMEOUT):
        logger.warning(f"{prefix} task is expired, ignored")
        await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is expired.", prefix)
        task.status = "completed"
        return

    await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, f"Task is started(cost {cost.total_seconds():.1f}s)", prefix)

    logger.info(f"{prefix} is processing task(cost {cost.total_seconds():.1f}s)")

    prompt = task.prompt.strip()
    size = task.options.get("size", DEFAULT_SIZE)
    step = task.options.get("step", DEFAULT_STEP)
    model = task.options.get("model", DEFAULT_MODEL)
    cfg = task.options.get("cfg", DEFAULT_CFG)

    try:
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
    if not task.job_id:
        logger.warning(f"{prefix} submitted task has no job_id")
        task.status = "completed"
        return

    try:
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
    if not task.job_id:
        logger.warning(f"{prefix} processing task has no job_id")
        task.status = "completed"
        return

    try:
        status_info = await comfy_api.job_status(endpoint, task.job_id)
        if status_info:
            old_status = task.status
            task.status = status_info.get("status", "not_found")

            if old_status != task.status:
                logger.info(f"{prefix} task status changed from {old_status} to {task.status}")
                cost = datetime.now() - datetime.fromtimestamp(task.created_at)
                await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, f"Task is {task.status}(cost {cost.total_seconds():.1f}s)", prefix)
        else:
            logger.warning(f"{prefix} failed to get task status")
            task.status = "not_found"

    except comfy_api.ComfyAPIError as e:
        logger.warning(f"{prefix} comfy api error when getting status: {e}")
        task.status = "not_found"


async def handle_completed_task(task: Task, endpoint: str, prefix: str, rdb):
    if not task.job_id:
        logger.warning(f"{prefix} completed task {task.task_id} has no job_id")
        await task.dequeue_task(rdb)
        return

    try:
        info = await comfy_api.get_job_info(endpoint, task.job_id)
        status_str = info.get("status", {}).get("status_str", "")
        if status_str == "error":
            logger.warning(f"{prefix} completed task {task.task_id} status is error, ignored")
            await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: status is error", prefix)
            await task.dequeue_task(rdb)
            return

        images = info.get("outputs", {}).get("37", {}).get("images", [])
        if not images:
            logger.warning(f"{prefix} completed task {task.task_id} has no image, ignored: {info['outputs']}")
            await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: empty image result", prefix)
            await task.dequeue_task(rdb)
            return

        filename = images[0].get("filename")
        subfolder = images[0].get("subfolder")

        img_raw = await task.download_image(filename, subfolder)

        if not img_raw:
            logger.warning(f"{prefix} completed task {task.task_id} image is empty, ignored")
            await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: empty image result", prefix)
            await task.dequeue_task(rdb)
            return

        cost = datetime.now() - datetime.fromtimestamp(task.created_at)

        size = task.options.get("size", DEFAULT_SIZE)
        step = task.options.get("step", DEFAULT_STEP)

        reply_buttons = None
        image_url = None

        try:
            original_url = f"local://comfy/{subfolder}/{filename}"
            
            imgproxy_domain = manager.config["imgproxy"]["domain"]
            imgproxy_key = manager.config["imgproxy"].get("imgproxy_key", "")
            imgproxy_salt = manager.config["imgproxy"].get("imgproxy_salt", "")
            imgproxy_encryption_key = manager.config["imgproxy"].get("imgproxy_source_url_encryption_key", "")
            
            image_url = generate_imgproxy_url(
                original_url, 
                imgproxy_domain, 
                imgproxy_key, 
                imgproxy_salt,
                imgproxy_encryption_key if imgproxy_encryption_key else None
            )
            # Telethon Buttons
            if image_url:
                reply_buttons = [Button.url("Original|原始图片", image_url)]
        except Exception as e:
            logger.warning(f"{prefix} imgproxy config error: {e}, skipping imgproxy URL")
            reply_buttons = None

        caption = f"Size: {size} Step: {step} Cost: {cost.total_seconds():.1f}s\n\n{task.msg.reply_content}"[:1023]
        
        # Send Photo
        # Telethon send_file(entity, file, caption=..., buttons=...)
        await manager.client.send_file(
            task.msg.chat_id,
            file=img_raw,
            caption=caption,
            buttons=reply_buttons,
            reply_to=task.msg.message_id
        )

        logger.info(f"{prefix} completed task {task.task_id} image is sent, cost: {cost.total_seconds():.1f}s")
        
        # Delete the progress message if we can
        if task.msg.reply_message_id > 0:
            await manager.delete_message(task.msg.chat_id, task.msg.reply_message_id)

    except Exception as e:
        logger.error(f"{prefix} completed task {task.task_id} send photo error: {e}")
        await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, f"Task is failed: failed to send image. {str(e)}", prefix)

    await task.dequeue_task(rdb)


async def handle_not_found_task(task: Task, prefix: str):
    logger.warning(f"{prefix} task {task.task_id} not found on remote service")
    await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, "Task is failed: task not found on remote service", prefix)
    task.status = "completed"


async def worker():
    """图像生成工作进程"""
    try:
        logger.info("image worker is started")

        while True:
            try:
                rdb = await manager.get_redis()
                if not rdb:
                    logger.warning("redis is not ready, ignored")
                    await asyncio.sleep(REDIS_RETRY_INTERVAL)
                    continue

                tasks = await Task.all_tasks(rdb)
                if not tasks:
                    await asyncio.sleep(WORKER_IDLE_INTERVAL)
                    continue

                for task in tasks:
                    await process_task(task)
                    await asyncio.sleep(WORKER_SLEEP_INTERVAL)

                await asyncio.sleep(WORKER_POLL_INTERVAL)

            except Exception as e:
                logger.exception(f"worker loop error: {e}")
                await asyncio.sleep(REDIS_RETRY_INTERVAL)

    except Exception as e:
        logger.exception(f"worker startup error: {e}")