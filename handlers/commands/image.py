import asyncio
import itertools
import random
import re
import time
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import uuid

from telethon import events
from telethon.errors import FloodWaitError
from orjson import dumps, loads

from manager import manager
from utils import comfy_api
from utils.comfy_workflow import WORKFLOWS

from ..utils import strip_text_prefix, chat_completions, get_image_optimize_models

logger = manager.logger


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
MAX_POLL_ERRORS = 3  # 状态轮询连续失败次数上限，超过才判定任务丢失

# ---- Telegram 出口调度与限速降级 ----
OP_DELIVER = 0    # P0 完成图投递（不可丢，撞墙重试直到成功或字节过期）
OP_NOTIFY = 1     # P1 状态变更/删除等一次性通知
OP_PROGRESS = 2   # P2 进度编辑（可合并、可丢弃）

GLOBAL_OP_SPACING = 0.2   # 全局操作最小间隔（秒）
CHAT_OP_SPACING = 1.1     # 单群操作最小间隔（秒）
PROGRESS_INTERVALS = {0: 3.0, 1: 10.0}   # 降级级别 -> 进度编辑最小间隔（2 级静默）
PROGRESS_STEP_PCT = {0: 10, 1: 25}       # 降级级别 -> 进度变化阈值（%）
FLOOD_RECOVER_AFTER = 60.0               # 无 FloodWait 多少秒后降级级别回升
MAX_DELIVER_ATTEMPTS = 20                # P0 投递最大撞墙重试次数
DELIVER_BACKOFF_BASE = 5.0               # 投递退避基数（指数增长）
DELIVER_BACKOFF_CAP = 300.0              # 投递退避封顶（秒）
IMG_BYTES_TTL = 3600                     # 完成图字节在 Redis 的保留时长（秒）
PROGRESS_BAR_LEN = 14                    # 进度条长度（字符数）

# 图像生成配置（LLM 优化模型从 [ai] image_optimize_models 读取，回退见 get_image_optimize_models）
DEFAULT_SIZE = "836x1216"
DEFAULT_STEP = 8
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
IMAGE_OPTIMIZE_PROMPT = """你是文生图提示词优化专家。用户给你一句简短的绘画描述，你要把它改写成一条高质量提示词，直接交给图像生成模型（Z-Image Turbo / Krea / Flux）使用。

规则：
1. 保持用户的原始意图，不改变主体和核心内容；保持输入语言（中文输入输出中文，英文输入输出英文），不要翻译。
2. 补全画面要素：主体细节（外貌、服饰、动作、表情、材质）、场景环境（光线、氛围、时间、背景）、构图与视角（特写 / 广角 / 俯视等）、艺术风格与质量词。
3. 用连贯的自然语言短段落描述，不要标签堆砌，不要负面词（负面词由工作流单独处理），不要任何参数（如 --ar、steps、cfg）。
4. 长度控制在 100 字（词）以内，信息密度优先，不写废话。
5. 只输出优化后的提示词本身：不要解释、不要引号、不要前后缀、不要换行标题。

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
    poll_errors: int = 0

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
            await rdb.set(f"{REDIS_KEY_PREFIX}{self.task_id}", dumps(self))
        except Exception as e:
            logger.error(f"Failed to enqueue task: {e}")
            raise ImageGenerationError("Failed to add task to queue")

    async def dequeue_task(self, rdb) -> None:
        """从队列中删除任务"""
        try:
            await rdb.delete(f"{REDIS_KEY_PREFIX}{self.task_id}")
        except Exception as e:
            logger.error(f"Failed to dequeue task: {e}")
            raise ImageGenerationError("Failed to remove task from queue")

    @staticmethod
    def _is_task_key(key) -> bool:
        """只匹配任务键 image:<uuid>，排除 image:lock:* / image:img:* 等内部键。"""
        k = key.decode() if isinstance(key, bytes) else str(key)
        sub = k[len(REDIS_KEY_PREFIX):]
        return not sub.startswith(("lock:", "img:"))

    @staticmethod
    async def all_tasks(rdb) -> List["Task"]:
        """从队列中获取任务"""
        try:
            tasks: List["Task"] = []
            batch: List[bytes] = []
            async for key in rdb.scan_iter(f"{REDIS_KEY_PREFIX}*"):
                if not Task._is_task_key(key):
                    continue
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
                    poll_errors=task_data.get("poll_errors", 0),
                )
            except Exception as e:
                # 损坏/脏数据（如旧版本写入、误命中内部键）无法恢复：
                # 跳过并删除，否则会永久占用队列名额（GLOBAL_TASK_LIMIT）
                logger.warning(f"Invalid task data {key}: {e}, removing")
                try:
                    await rdb.delete(key)
                except Exception:
                    pass
                continue
            tasks.append(task)
        return tasks


class ImageGenerationError(Exception):
    """图像生成相关错误"""

    pass


class _OutboundOp:
    """一次待执行的 Telegram 出口操作。"""

    __slots__ = ("priority", "factory", "chat_id", "kind", "attempts", "on_error")

    def __init__(self, priority, factory, chat_id, kind="", on_error=None):
        self.priority = priority
        self.factory = factory      # Callable[[], Awaitable]，执行真正的发送/编辑
        self.chat_id = chat_id
        self.kind = kind
        self.attempts = 0
        self.on_error = on_error    # 重试耗尽或永久失败后的回调


class OutboundDispatcher:
    """image 模块 Telegram 出口统一调度。

    - 串行消费优先队列：全局 0.2s / 单群 1.1s 间隔，从根上避免并发撞墙
    - FloodWait 全局感知：任何操作撞墙，整队暂停到 blocked_until 再恢复
    - P2 进度编辑在执行时才渲染最新文本，内容未变直接跳过，撞墙直接丢弃
    - P0 投递撞墙指数退避重试（封顶 5 分钟，最多 20 次），P1 有限重试 3 次
    - 降级级别：0 正常 / 1 放缓 / 2 静默（进度停更），60s 无撞墙自动回升
    """

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = itertools.count()
        self._worker: Optional[asyncio.Task] = None
        self._blocked_until = 0.0
        self._last_op_at = 0.0
        self._last_chat_op: Dict[int, float] = {}
        self._edited_texts: Dict[Tuple[int, int], str] = {}
        self._gone_msgs: set = set()  # 已被删除的消息 (chat_id, message_id)，后续编辑/删除直接短路
        self._delivering: set = set()
        self.degrade_level = 0
        self._last_flood_at = 0.0

    # ---- 生命周期 ----

    def ensure_running(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())

    # ---- 降级控制（纯逻辑，便于测试）----

    def on_flood(self, seconds: float) -> None:
        now = time.monotonic()
        self._blocked_until = now + seconds
        self._last_flood_at = now
        self.degrade_level = min(2, self.degrade_level + 1)
        logger.warning(f"telegram flood wait {seconds:.0f}s, degrade level -> {self.degrade_level}")

    def maybe_recover(self) -> None:
        if self.degrade_level > 0 and time.monotonic() - self._last_flood_at > FLOOD_RECOVER_AFTER:
            self.degrade_level -= 1
            self._last_flood_at = time.monotonic()
            logger.info(f"telegram flood recovered, degrade level -> {self.degrade_level}")

    # ---- 提交入口 ----

    async def _enqueue(self, op: _OutboundOp) -> None:
        self.ensure_running()
        await self._queue.put((op.priority, next(self._seq), op))

    async def submit_edit(self, chat_id: int, message_id: int, text: str) -> None:
        """状态变更类编辑（P1）。消息已被删除时直接短路。"""
        key = (chat_id, message_id)
        if message_id <= 0 or key in self._gone_msgs:
            return

        async def op():
            result = await manager.edit_text(chat_id, message_id, text)
            if result is None:
                # 消息已删除：记住它，之后不再尝试编辑/删除
                self._mark_gone(key)
            elif result:
                self._edited_texts[key] = text

        await self._enqueue(_OutboundOp(OP_NOTIFY, op, chat_id, kind="edit"))

    async def submit_progress_edit(self, chat_id: int, message_id: int, text_getter) -> None:
        """进度编辑（P2）：执行时才渲染最新进度；内容未变则跳过；静默级别直接丢弃。"""
        key = (chat_id, message_id)
        if message_id <= 0 or self.degrade_level >= 2 or key in self._gone_msgs:
            return

        async def op():
            text = text_getter()
            if not text or text == self._edited_texts.get(key):
                return
            result = await manager.edit_text(chat_id, message_id, text)
            if result is None:
                self._mark_gone(key)
            elif result:
                self._edited_texts[key] = text

        await self._enqueue(_OutboundOp(OP_PROGRESS, op, chat_id, kind="progress"))

    async def submit_delete(self, chat_id: int, message_id: int) -> None:
        key = (chat_id, message_id)
        if message_id <= 0 or key in self._gone_msgs:
            return

        async def op():
            await manager.delete_message(chat_id, message_id)
            # 删除成功后同样短路：防止已入队的迟到编辑再打到这条消息上
            self._mark_gone(key)

        await self._enqueue(_OutboundOp(OP_NOTIFY, op, chat_id, kind="delete"))

    def _mark_gone(self, key: Tuple[int, int]) -> None:
        self._gone_msgs.add(key)
        self._edited_texts.pop(key, None)

    # ---- 完成图投递（P0）----

    def is_delivering(self, task_id: str) -> bool:
        return task_id in self._delivering

    async def submit_delivery(self, task: "Task", rdb, on_done, on_failed) -> None:
        """投递完成图。字节从 Redis 读取，撞墙由调度器统一退避重试。"""
        if task.task_id in self._delivering:
            return
        self._delivering.add(task.task_id)

        async def op():
            img_raw = await rdb.get(f"{REDIS_KEY_PREFIX}img:{task.task_id}")
            if not img_raw:
                raise RuntimeError("image bytes expired in redis")
            sent_id = await manager.send_photo(
                task.msg.chat_id,
                bytes(img_raw),
                caption=build_caption(task),
                reply_to=task.msg.message_id,
            )
            if sent_id is None:
                raise RuntimeError("send_photo returned None")
            self._delivering.discard(task.task_id)
            await on_done(task, rdb)

        async def failed(err):
            self._delivering.discard(task.task_id)
            await on_failed(task, rdb, err)

        await self._enqueue(
            _OutboundOp(OP_DELIVER, op, task.msg.chat_id, kind="deliver", on_error=failed)
        )

    # ---- 消费循环 ----

    async def _run(self) -> None:
        while True:
            _, _, op = await self._queue.get()
            try:
                await self._pace(op.chat_id)
                await op.factory()
            except FloodWaitError as e:
                self.on_flood(e.seconds)
                await self._requeue_or_drop(op)
            except Exception as e:
                logger.warning(f"outbound op failed ({op.kind}): {e}")
                if op.on_error:
                    try:
                        await op.on_error(e)
                    except Exception as cb_err:
                        logger.warning(f"outbound on_error failed: {cb_err}")
            finally:
                self._queue.task_done()

    async def _pace(self, chat_id: int) -> None:
        self.maybe_recover()
        now = time.monotonic()
        wait = max(
            self._blocked_until - now,
            self._last_op_at + GLOBAL_OP_SPACING - now,
            self._last_chat_op.get(chat_id, 0.0) + CHAT_OP_SPACING - now,
            0.0,
        )
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_op_at = time.monotonic()
        self._last_chat_op[chat_id] = self._last_op_at

    async def _requeue_or_drop(self, op: _OutboundOp) -> None:
        if op.priority == OP_PROGRESS:
            return  # 进度编辑可丢弃，下一个进度事件会重新调度
        max_attempts = MAX_DELIVER_ATTEMPTS if op.priority == OP_DELIVER else 3
        op.attempts += 1
        if op.attempts >= max_attempts:
            logger.error(f"outbound op {op.kind} exhausted {max_attempts} attempts")
            if op.on_error:
                try:
                    await op.on_error(TimeoutError("flood retries exhausted"))
                except Exception as cb_err:
                    logger.warning(f"outbound on_error failed: {cb_err}")
            return
        if op.priority == OP_DELIVER:
            backoff = min(DELIVER_BACKOFF_BASE * (2 ** (op.attempts - 1)), DELIVER_BACKOFF_CAP)
        else:
            backoff = 1.0
        delay = max(backoff, self._blocked_until - time.monotonic(), 1.0)
        asyncio.create_task(self._delayed_requeue(op, delay))

    async def _delayed_requeue(self, op: _OutboundOp, delay: float) -> None:
        await asyncio.sleep(delay)
        await self._queue.put((op.priority, next(self._seq), op))


dispatcher = OutboundDispatcher()


async def safe_edit_text(chat_id: int, message_id: int, text: str, prefix: str = ""):
    """安全编辑消息文本（经出口调度器，限速感知）"""
    if message_id <= 0:
        logger.warning(f"{prefix} invalid message_id: {message_id}, skipping edit")
        return
    await dispatcher.submit_edit(chat_id, message_id, text)


# ---- 状态消息渲染（中文主文案 + 英文引用块，与验证码模块风格一致）----

def render_progress_bar(percent: float) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(round(PROGRESS_BAR_LEN * percent / 100))
    return "█" * filled + "░" * (PROGRESS_BAR_LEN - filled)


def _node_title(model: str, node: Optional[str]) -> Optional[str]:
    """从工作流模板里取节点显示名（如 KSampler / SeedVR2 放大）。"""
    if not node:
        return None
    node_def = WORKFLOWS.get(model, {}).get(str(node))
    if not node_def:
        return None
    return node_def.get("_meta", {}).get("title")


def render_status_message(
    task: "Task",
    phase: str,
    *,
    position: Optional[int] = None,
    progress: Optional[Dict[str, Any]] = None,
    elapsed: Optional[float] = None,
    error: Optional[str] = None,
    degraded: bool = False,
) -> str:
    """渲染任务状态消息。phase: queued/submitted/running/delivering/failed/expired"""
    model = task.options.get("model", DEFAULT_MODEL)
    size = task.options.get("size", DEFAULT_SIZE)
    step = task.options.get("step", DEFAULT_STEP)
    prompt_lines = (task.msg.reply_content or task.prompt or "").strip().splitlines()
    prompt_preview = prompt_lines[0][:80] if prompt_lines and prompt_lines[0] else "(empty)"

    lines = []

    if phase == "queued":
        head = f"⏳ 图像生成排队中 · 第 {position} 位" if position else "⏳ 图像生成排队中"
        en = f"> Queued, position {position}. Please wait." if position else "> Queued. Please wait."
    elif phase == "submitted":
        head = f"📤 已提交，等待 GPU 调度 · ComfyUI 队列第 {position} 位" if position else "📤 已提交，等待 GPU 调度"
        en = "> Submitted, waiting for GPU."
    elif phase == "running":
        if progress and progress.get("max"):
            pct = progress["value"] / progress["max"] * 100
            head = f"🎨 生成中 · {render_progress_bar(pct)} {pct:.0f}%"
            step_line = f"步骤 {progress['value']}/{progress['max']}"
            title = _node_title(model, progress.get("node"))
            if title:
                step_line += f" · {title}"
            if elapsed and progress["value"] > 0:
                remain = elapsed * (progress["max"] - progress["value"]) / progress["value"]
                step_line += f" · 已耗时 {elapsed:.0f}s · 预计剩余 ~{remain:.0f}s"
            elif elapsed:
                step_line += f" · 已耗时 {elapsed:.0f}s"
            lines.append(step_line)
            en = f"> Generating... step {progress['value']}/{progress['max']}"
        else:
            head = "🎨 生成中"
            if elapsed:
                lines.append(f"已耗时 {elapsed:.0f}s")
            en = "> Generating..."
        if degraded:
            lines.append("⚠️ Telegram 限速中，进度更新已放缓")
    elif phase == "delivering":
        head = "📦 已生成，正在发送图片…"
        en = "> Generated, delivering the image..."
    elif phase == "expired":
        head = "⌛ 任务已过期，请重新发起"
        en = "> Task expired, please try again."
    else:  # failed
        head = f"❌ 生成失败（已耗时 {elapsed:.1f}s）" if elapsed else "❌ 生成失败"
        en = f"> {error}" if error else "> Generation failed."

    lines.insert(0, head)
    lines.append("")
    lines.append(f"🤖 {model} · {size} · {step} steps")
    lines.append(f"📝 {prompt_preview}")
    lines.append("")
    lines.append(en)
    return "\n".join(lines)


def build_caption(task: "Task") -> str:
    """完成图 caption：模型/尺寸/步数/cfg/seed/耗时 + 提示词。"""
    model = task.options.get("model", DEFAULT_MODEL)
    size = task.options.get("size", DEFAULT_SIZE)
    step = task.options.get("step", DEFAULT_STEP)
    cfg = task.options.get("cfg", DEFAULT_CFG)
    seed = task.options.get("seed", "?")
    cost = (datetime.now() - datetime.fromtimestamp(task.created_at)).total_seconds()
    prompt = (task.msg.reply_content or task.prompt or "").strip()
    caption = (
        f"🤖 {model} · {size} · {step} steps · cfg {cfg}\n"
        f"🎲 seed {seed} · ⏱ {cost:.1f}s\n\n"
        f"📝 {prompt}"
    )
    return caption[:1023]


# 进度编辑节流状态（内存即可，重启后从零节起无副作用）
_progress_throttle: Dict[str, Dict[str, float]] = {}


def should_update_progress(state: Dict[str, float], percent: float, now: float, level: int) -> bool:
    """进度编辑节流判定：静默级别不更新；间隔和变化阈值随降级级别收紧。"""
    if level >= 2:
        return False
    interval = PROGRESS_INTERVALS.get(level, 3.0)
    threshold = PROGRESS_STEP_PCT.get(level, 10)
    if now - state.get("last_edit", 0.0) < interval:
        return False
    if abs(percent - state.get("last_pct", -100.0)) < threshold:
        return False
    return True


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
            # 过滤无效值：用户 ID 为正数，群组 ID 为负数（-100... 超负群 / 普通负群）
            users = [i for i in users if i > 0]
            groups = [i for i in groups if i < 0]
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
                elif opt == "raw":
                    # 跳过 LLM 提示词优化，原文直接提交
                    options["raw"] = True

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

        for model in get_image_optimize_models():
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
            await manager.reply(
                event,
                "🚫 没有使用此功能的权限。\n\n> You are not allowed to use this command.",
                auto_deleted_at=now + timedelta(seconds=DELETED_AFTER),
            )
            return

        prefix += f" user {sender_name}"
        logger.info(f"{prefix} is using image func")

        # 获取Redis连接并检查队列容量
        rdb = await manager.get_redis()
        if not rdb:
            logger.warning(f"{prefix} redis is not ready, ignored")
            await manager.reply(
                event,
                "🔧 服务内部错误，请稍后重试。\n\n> Internal error, please try again later.",
                auto_deleted_at=now + timedelta(seconds=DELETED_AFTER),
            )
            return

        tasks = await Task.all_tasks(rdb)
        task_size = len(tasks)
        if task_size >= GLOBAL_TASK_LIMIT:
            logger.warning(f"{prefix} task queue is full, ignored")
            await manager.reply(
                event,
                "⏳ 任务队列已满，请稍后重试。\n\n> Task queue is full, please try again later.",
                auto_deleted_at=now + timedelta(seconds=DELETED_AFTER),
            )
            return

        # 处理提示词
        raw_prompt = await PromptProcessor.extract_prompt_from_message(event)
        if not raw_prompt:
            logger.warning(f"{prefix} invalid prompt, ignored")
            await manager.reply(
                event,
                "📝 请提供有效的提示词。\n\n> Invalid prompt, please send a valid prompt.",
                auto_deleted_at=now + timedelta(seconds=DELETED_AFTER),
            )
            return

        # 解析选项和优化提示词
        prompt, options = PromptProcessor.parse_options(raw_prompt)

        # 默认先用 LLM（deepseek-flash 等）把描述优化成高质量提示词再提交；
        # 专业用户可用 [raw] 选项跳过优化，或提示词含英文逗号时视为已细化、自动跳过
        if options.get("raw"):
            reply_content = prompt
        else:
            prompt, reply_content = await PromptProcessor.optimize_prompt(prompt)

        # 创建任务（reply_message_id 先占位 -1）
        task = Task(
            msg=TaskMessage(
                chat_id=event.chat_id,
                chat_name=chat_title,
                user_id=sender.id,
                user_name=sender_name,
                message_id=event.id,
                reply_message_id=-1,
                reply_content=reply_content,
            ),
            prompt=prompt,
            options=options,
            created_at=datetime.now().timestamp(),
            status="queued",
            job_id=None,
            task_id=str(uuid.uuid4()),
        )

        # 先回复排队消息拿到 msg_id，再一次性入队。
        # 之前是"入队 → 回复 → 二次入队"，worker 可能在间隙读到
        # reply_message_id=-1 的旧版本并覆盖回去，导致状态消息永远卡在
        # "排队中"、完成后也删不掉（和完成图并存成两段回复）。
        reply = await event.reply(render_status_message(task, "queued", position=task_size + 1))
        task.msg.reply_message_id = reply.id
        try:
            await task.enqueue_task(rdb)
        except ImageGenerationError:
            # 入队失败时把刚发的排队消息删掉，避免留下永远卡住的"排队中"
            await manager.delete_message(event.chat_id, reply.id)
            raise

        logger.info(f"{prefix} task is queued, size is {task_size + 1}")
    except ImageGenerationError as e:
        logger.warning(f"{prefix} {str(e)}")
        await manager.reply(
            event,
            f"❌ 任务创建失败。\n\n> {str(e)}",
            auto_deleted_at=now + timedelta(seconds=DELETED_AFTER),
        )
    except Exception as e:
        logger.exception(f"{prefix} task is failed:{str(e)}")
        await manager.reply(
            event,
            f"❌ 任务创建失败，请稍后重试。\n\n> {str(e)}",
            auto_deleted_at=now + timedelta(seconds=DELETED_AFTER),
        )


async def process_task(task: Task):
    """处理单个图像生成任务"""
    prefix = f"chat {task.msg.chat_id}({task.msg.chat_name}) msg {task.msg.message_id} user {task.msg.user_name}"

    # 检查配置
    endpoint = manager.config["sd_api"]["endpoint"]
    if not endpoint:
        task.status = "completed"
        logger.warning(f"{prefix} image endpoint is empty")
        await safe_edit_text(
            task.msg.chat_id, task.msg.reply_message_id,
            render_status_message(task, "failed", error="远端服务未配置 / Remote service is closed"),
            prefix,
        )
        return

    rdb = await manager.get_redis()
    if not rdb:
        task.status = "completed"
        logger.warning(f"{prefix} redis is not ready, ignored")
        await safe_edit_text(
            task.msg.chat_id, task.msg.reply_message_id,
            render_status_message(task, "failed", error="缓存服务不可用 / Redis is not ready"),
            prefix,
        )
        return

    lock_key = f"{REDIS_KEY_PREFIX}lock:{task.task_id}"
    locked = await rdb.set(lock_key, "1", nx=True, ex=TASK_LOCK_TTL)
    if not locked:
        logger.debug(f"{prefix} task {task.task_id} is locked, skip")
        return

    # 只在持有锁时释放锁，避免误删其他处理者的锁
    try:
        try:
            # 根据任务状态进行分类处理
            if task.status == "queued":
                await handle_queued_task(task, endpoint, prefix)
            elif task.status == "submitted":
                await handle_submitted_task(task, endpoint, prefix)
            elif task.status in ["running", "pending"]:
                await handle_processing_task(task, endpoint, prefix)
            elif task.status == "delivering":
                # 投递由 dispatcher 异步执行；这里只兜底（重启后恢复投递）
                await handle_delivering_task(task, rdb, prefix)
            elif task.status == "not_found":
                await handle_not_found_task(task, rdb, prefix)
            elif task.status == "completed":
                pass
            else:
                logger.warning(f"{prefix} unknown task status: {task.status}, and force set to completed")
                task.status = "completed"

            # failed 终态的任务已在 fail_task 中出队，不能再写回 Redis，
            # 否则下个轮询周期会复活成僵尸任务（not_found 无限循环的成因）
            if task.status != "failed":
                await rdb.set(f"{REDIS_KEY_PREFIX}{task.task_id}", dumps(task))

        except Exception as e:
            cost = datetime.now() - datetime.fromtimestamp(task.created_at)
            logger.exception(f"{prefix} process task error: {e}")
            await safe_edit_text(
                task.msg.chat_id, task.msg.reply_message_id,
                render_status_message(task, "failed", elapsed=cost.total_seconds(), error=str(e)[:200]),
                prefix,
            )
            task.status = "completed"
            await rdb.set(f"{REDIS_KEY_PREFIX}{task.task_id}", dumps(task))

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
        await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, render_status_message(task, "expired"), prefix)
        task.status = "completed"
        return

    logger.info(f"{prefix} is processing task(cost {cost.total_seconds():.1f}s)")

    prompt = task.prompt.strip()
    size = task.options.get("size", DEFAULT_SIZE)
    step = task.options.get("step", DEFAULT_STEP)
    model = task.options.get("model", DEFAULT_MODEL)
    cfg = task.options.get("cfg", DEFAULT_CFG)
    # seed 在提交前生成并持久化到 options，caption 里展示给用户用于复现
    seed = task.options.setdefault("seed", random.randint(0, 0xFFFFFFFFFFFFFFFF))

    try:
        job_id = await asyncio.wait_for(
            comfy_api.generate_image(endpoint, model, prompt, size, step, cfg, seed=seed),
            timeout=DEFAULT_GENERATION_TIMEOUT,
        )

        if not job_id:
            logger.warning(f"{prefix} image job is empty, ignored")
            await safe_edit_text(
                task.msg.chat_id, task.msg.reply_message_id,
                render_status_message(task, "failed", elapsed=(datetime.now() - created_at).total_seconds(), error="创建生成任务失败 / Create image job failed"),
                prefix,
            )
            task.status = "completed"
            return

        task.status = "submitted"
        task.job_id = job_id

        await safe_edit_text(task.msg.chat_id, task.msg.reply_message_id, render_status_message(task, "submitted"), prefix)
        logger.info(f"{prefix} image job is created with job_id: {job_id}")

    except asyncio.TimeoutError:
        logger.warning(f"{prefix} image job timeout after {DEFAULT_GENERATION_TIMEOUT}s")
        await safe_edit_text(
            task.msg.chat_id, task.msg.reply_message_id,
            render_status_message(task, "failed", elapsed=(datetime.now() - created_at).total_seconds(), error=f"提交超时 / Submit timeout after {DEFAULT_GENERATION_TIMEOUT}s"),
            prefix,
        )
        task.status = "completed"
    except comfy_api.ComfyAPIError as e:
        logger.warning(f"{prefix} comfy api error: {e}")
        await safe_edit_text(
            task.msg.chat_id, task.msg.reply_message_id,
            render_status_message(task, "failed", elapsed=(datetime.now() - created_at).total_seconds(), error=str(e)),
            prefix,
        )
        task.status = "completed"


async def handle_submitted_task(task: Task, endpoint: str, prefix: str):
    if not task.job_id:
        logger.warning(f"{prefix} submitted task has no job_id")
        task.status = "completed"
        return

    try:
        status_info = await comfy_api.job_status(endpoint, task.job_id)
        if status_info:
            task.poll_errors = 0
            new_status = status_info.get("status", "not_found")
            if new_status != task.status:
                task.status = new_status
                logger.info(f"{prefix} task status updated to: {task.status}")
                if new_status == "pending":
                    await safe_edit_text(
                        task.msg.chat_id, task.msg.reply_message_id,
                        render_status_message(task, "submitted", position=status_info.get("position")),
                        prefix,
                    )
                elif new_status == "running":
                    await safe_edit_text(
                        task.msg.chat_id, task.msg.reply_message_id,
                        render_status_message(task, "running"),
                        prefix,
                    )
        else:
            logger.warning(f"{prefix} failed to get task status")
            task.status = "not_found"

    except comfy_api.ComfyAPIError as e:
        # 网络抖动不直接判死，连续 MAX_POLL_ERRORS 次失败才置为 not_found
        task.poll_errors += 1
        logger.warning(f"{prefix} comfy api error when getting status ({task.poll_errors}/{MAX_POLL_ERRORS}): {e}")
        if task.poll_errors >= MAX_POLL_ERRORS:
            task.status = "not_found"


async def handle_processing_task(task: Task, endpoint: str, prefix: str):
    if not task.job_id:
        logger.warning(f"{prefix} processing task has no job_id")
        task.status = "completed"
        return

    try:
        status_info = await comfy_api.job_status(endpoint, task.job_id)
        if status_info:
            task.poll_errors = 0
            old_status = task.status
            task.status = status_info.get("status", "not_found")

            if old_status != task.status:
                logger.info(f"{prefix} task status changed from {old_status} to {task.status}")
                if task.status == "pending":
                    await safe_edit_text(
                        task.msg.chat_id, task.msg.reply_message_id,
                        render_status_message(task, "submitted", position=status_info.get("position")),
                        prefix,
                    )

            if task.status == "running":
                await update_progress(task, prefix)
        else:
            logger.warning(f"{prefix} failed to get task status")
            task.status = "not_found"

    except comfy_api.ComfyAPIError as e:
        # 网络抖动不直接判死，连续 MAX_POLL_ERRORS 次失败才置为 not_found
        task.poll_errors += 1
        logger.warning(f"{prefix} comfy api error when getting status ({task.poll_errors}/{MAX_POLL_ERRORS}): {e}")
        if task.poll_errors >= MAX_POLL_ERRORS:
            task.status = "not_found"


async def update_progress(task: Task, prefix: str) -> None:
    """读取 ComfyUI WS 进度快照，按降级级别节流后调度进度编辑（P2，可合并可丢弃）。"""
    snapshot = comfy_api.progress_tracker.snapshot(task.job_id)
    state = _progress_throttle.setdefault(task.task_id, {})
    now = time.monotonic()

    percent = 0.0
    if snapshot and snapshot.get("max"):
        percent = snapshot["value"] / snapshot["max"] * 100

    if not should_update_progress(state, percent, now, dispatcher.degrade_level):
        return
    state["last_edit"] = now
    state["last_pct"] = percent

    job_id = task.job_id

    def text_getter() -> str:
        # 执行时才取最新快照：排队期间进度可能已推进
        latest = comfy_api.progress_tracker.snapshot(job_id) or snapshot
        return render_status_message(
            task,
            "running",
            progress=latest,
            elapsed=(datetime.now() - datetime.fromtimestamp(task.created_at)).total_seconds(),
            degraded=dispatcher.degrade_level > 0,
        )

    await dispatcher.submit_progress_edit(task.msg.chat_id, task.msg.reply_message_id, text_getter)


async def handle_completed_task(task: Task, endpoint: str, prefix: str, rdb):
    """生成完成：下载图片 → 字节落 Redis → 转 delivering 由调度器投递。

    字节先持久化再投递：之后撞墙限流、进程重启都不丢结果。
    """
    if not task.job_id:
        logger.warning(f"{prefix} completed task {task.task_id} has no job_id")
        await task.dequeue_task(rdb)
        return

    try:
        info = await comfy_api.get_job_info(endpoint, task.job_id)
        status_str = info.get("status", {}).get("status_str", "")
        if status_str == "error":
            logger.warning(f"{prefix} completed task {task.task_id} status is error")
            await fail_task(task, rdb, "ComfyUI 执行出错 / Execution error", prefix)
            return

        # 按模型选择保存节点（zimage/krea="37"，flux="50"），兜底扫描所有输出
        outputs = info.get("outputs", {})
        node_id = {"zimage": "37", "krea": "37", "flux": "50"}.get(task.options.get("model", DEFAULT_MODEL), "37")
        images = outputs.get(node_id, {}).get("images", [])
        if not images:
            for node_output in outputs.values():
                if isinstance(node_output, dict) and node_output.get("images"):
                    images = node_output["images"]
                    break
        if not images:
            logger.warning(f"{prefix} completed task {task.task_id} has no image: {info['outputs']}")
            await fail_task(task, rdb, "生成结果为空 / Empty image result", prefix)
            return

        filename = images[0].get("filename")
        subfolder = images[0].get("subfolder") or ""

        img_raw = await task.download_image(filename, subfolder)
        if not img_raw:
            logger.warning(f"{prefix} completed task {task.task_id} image is empty")
            await fail_task(task, rdb, "图片下载失败 / Image download failed", prefix)
            return

        # 字节先落 Redis 再进投递状态
        task.options["image_filename"] = filename
        task.options["image_subfolder"] = subfolder
        await rdb.set(f"{REDIS_KEY_PREFIX}img:{task.task_id}", img_raw, ex=IMG_BYTES_TTL)
        task.status = "delivering"
        await rdb.set(f"{REDIS_KEY_PREFIX}{task.task_id}", dumps(task))

        cost = (datetime.now() - datetime.fromtimestamp(task.created_at)).total_seconds()
        logger.info(f"{prefix} task {task.task_id} generated, cost {cost:.1f}s, delivering")
        await dispatcher.submit_edit(
            task.msg.chat_id, task.msg.reply_message_id,
            render_status_message(task, "delivering"),
        )
        await handle_delivering_task(task, rdb, prefix)

    except Exception as e:
        logger.error(f"{prefix} completed task {task.task_id} error: {e}")
        await fail_task(task, rdb, f"结果处理失败 / {str(e)[:200]}", prefix)


async def fail_task(task: Task, rdb, reason: str, prefix: str) -> None:
    """任务失败收尾：更新状态消息、置 failed 终态并出队。"""
    elapsed = (datetime.now() - datetime.fromtimestamp(task.created_at)).total_seconds()
    await dispatcher.submit_edit(
        task.msg.chat_id, task.msg.reply_message_id,
        render_status_message(task, "failed", elapsed=elapsed, error=reason),
    )
    # 终态标记必须先于出队设置：process_task 末尾会按状态决定是否写回 Redis，
    # 缺了它，已出队的任务会被重新写回，下个轮询周期复活成僵尸任务无限重试
    task.status = "failed"
    await task.dequeue_task(rdb)
    comfy_api.progress_tracker.clear(task.job_id or "")
    _progress_throttle.pop(task.task_id, None)


async def handle_delivering_task(task: Task, rdb, prefix: str) -> None:
    """投递入口：已在投递中的跳过；字节丢失（TTL 过期等）时尝试从 ComfyUI 重下载补齐。"""
    if dispatcher.is_delivering(task.task_id):
        return

    img_key = f"{REDIS_KEY_PREFIX}img:{task.task_id}"
    if not await rdb.exists(img_key):
        filename = task.options.get("image_filename")
        subfolder = task.options.get("image_subfolder") or ""
        img_raw = None
        if filename:
            try:
                img_raw = await task.download_image(filename, subfolder)
            except Exception as e:
                logger.warning(f"{prefix} re-download image failed: {e}")
        if img_raw:
            await rdb.set(img_key, img_raw, ex=IMG_BYTES_TTL)
        else:
            logger.error(f"{prefix} task {task.task_id} image bytes lost, mark failed")
            await fail_task(task, rdb, "图片已过期，请重新生成 / Image expired, please regenerate", prefix)
            return

    await dispatcher.submit_delivery(task, rdb, on_done=finalize_delivery, on_failed=finalize_delivery_failed)


async def finalize_delivery(task: Task, rdb) -> None:
    """投递成功收尾：删进度消息、出队、清理进度快照。"""
    cost = (datetime.now() - datetime.fromtimestamp(task.created_at)).total_seconds()
    logger.info(f"chat {task.msg.chat_id} task {task.task_id} delivered, cost {cost:.1f}s")
    await dispatcher.submit_delete(task.msg.chat_id, task.msg.reply_message_id)
    await task.dequeue_task(rdb)
    await rdb.delete(f"{REDIS_KEY_PREFIX}img:{task.task_id}")
    comfy_api.progress_tracker.clear(task.job_id or "")
    _progress_throttle.pop(task.task_id, None)


async def finalize_delivery_failed(task: Task, rdb, err: Exception) -> None:
    """投递彻底失败收尾（撞墙重试耗尽或永久性错误）。"""
    logger.error(f"chat {task.msg.chat_id} task {task.task_id} delivery failed: {err}")
    await fail_task(task, rdb, f"发送图片失败 / {str(err)[:200]}", "delivery")


async def handle_not_found_task(task: Task, rdb, prefix: str):
    logger.warning(f"{prefix} task {task.task_id} not found on remote service")
    await fail_task(task, rdb, "远端任务丢失 / Task not found on remote service", prefix)


async def log_queue_snapshot(rdb) -> None:
    """worker 启动时打印存量任务快照（id/状态/年龄/来源），便于排查重启遗留任务。"""
    try:
        tasks = await Task.all_tasks(rdb)
    except Exception as e:
        logger.warning(f"image queue snapshot failed: {e}")
        return
    if not tasks:
        logger.info("image queue snapshot: empty")
        return
    now = datetime.now().timestamp()
    logger.info(f"image queue snapshot: {len(tasks)} task(s)")
    for t in tasks:
        age = now - t.created_at
        logger.info(
            f"  task {t.task_id} status={t.status} age={age:.0f}s "
            f"chat={t.msg.chat_id} msg={t.msg.message_id} user={t.msg.user_name} "
            f"job={t.job_id or '-'} model={t.options.get('model', DEFAULT_MODEL)}"
        )


async def worker():
    """图像生成工作进程"""
    try:
        logger.info("image worker is started")
        dispatcher.ensure_running()
        redis_unavailable_logged = False
        queue_snapshot_logged = False

        while True:
            try:
                rdb = await manager.get_redis()
                if not rdb:
                    # Log once while Redis is down; resume message on recovery.
                    # Avoids flooding logs every REDIS_RETRY_INTERVAL.
                    if not redis_unavailable_logged:
                        logger.warning(
                            "redis is not ready, image worker idle until redis is available"
                        )
                        redis_unavailable_logged = True
                    await asyncio.sleep(REDIS_RETRY_INTERVAL)
                    continue

                if redis_unavailable_logged:
                    logger.info("redis is ready, image worker resuming")
                    redis_unavailable_logged = False

                if not queue_snapshot_logged:
                    # 启动后第一次拿到 Redis 时打印存量任务，便于排查重启遗留
                    await log_queue_snapshot(rdb)
                    queue_snapshot_logged = True

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