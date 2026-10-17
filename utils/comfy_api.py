import asyncio
import copy
import random
import re
import uuid
from typing import Optional, Dict, Any, Tuple

from aiohttp import ClientSession, ClientTimeout, ClientError, WSMsgType
from orjson import loads as json_loads

from manager import manager
from .comfy_workflow import WORKFLOWS

logger = manager.logger

# 常量定义
DEFAULT_TIMEOUT = ClientTimeout(total=30.0)
PROMPT_TIMEOUT = 15
HISTORY_TIMEOUT = 10
MAX_RETRIES = 30
RETRY_DELAY = 7
DEFAULT_SEED_RANGE = (0, 0xFFFFFFFFFFFFFFFF)

# 提交工作流时使用的固定 client_id，WebSocket 进度事件按此关联
CLIENT_ID = f"goalkeepr-{uuid.uuid4().hex[:8]}"


class ComfyAPIError(Exception):
    """ComfyUI API 相关错误的基类"""

    pass


class WorkflowSubmissionError(ComfyAPIError):
    """工作流提交失败错误"""

    pass


class ImageGenerationTimeoutError(ComfyAPIError):
    """图片生成超时错误"""

    pass


class ImageDownloadError(ComfyAPIError):
    """图片下载失败错误"""

    pass


class ProgressTracker:
    """ComfyUI WebSocket 进度跟踪。

    提交工作流时携带 CLIENT_ID 后，ComfyUI 会把该任务的执行事件推送到
    /ws?clientId=CLIENT_ID。本类维护一条长连接，把 progress/executing
    事件按 prompt_id（即 job_id）记录为内存快照，供调用方渲染进度。

    断线指数退避重连（2s → 30s 封顶）；断线期间快照停更，调用方应自行
    兜底（显示无进度条的"生成中"）。
    """

    RECONNECT_MIN = 2.0
    RECONNECT_MAX = 30.0

    def __init__(self) -> None:
        self._progress: Dict[str, Dict[str, Any]] = {}
        self._ws_task: Optional[asyncio.Task] = None

    def snapshot(self, job_id: str) -> Optional[Dict[str, Any]]:
        """获取任务进度快照：{"value": 当前步, "max": 总步数, "node": 当前节点ID}"""
        return self._progress.get(job_id)

    def clear(self, job_id: str) -> None:
        self._progress.pop(job_id, None)

    def ensure_running(self, endpoint: str) -> None:
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self._run(endpoint))

    async def _run(self, endpoint: str) -> None:
        delay = self.RECONNECT_MIN
        ws_base = re.sub(r"^http", "ws", endpoint.rstrip("/"))
        url = f"{ws_base}/ws?clientId={CLIENT_ID}"
        while True:
            try:
                session = await manager.create_session()
                async with session.ws_connect(url, timeout=DEFAULT_TIMEOUT) as ws:
                    logger.info("comfy ws connected")
                    delay = self.RECONNECT_MIN
                    async for msg in ws:
                        if msg.type == WSMsgType.TEXT:
                            self._handle(msg.data)
                        elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"comfy ws error: {e}")
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.RECONNECT_MAX)

    def _handle(self, raw: Any) -> None:
        try:
            data = json_loads(raw)
        except Exception:
            return
        payload = data.get("data") or {}
        job_id = payload.get("prompt_id")
        if not job_id:
            return
        mtype = data.get("type")
        if mtype == "progress":
            cur = self._progress.setdefault(job_id, {"value": 0, "max": 0, "node": None})
            cur["value"] = payload.get("value", 0)
            cur["max"] = payload.get("max", 0)
        elif mtype == "executing":
            node = payload.get("node")
            if node is None:
                # node=None 表示整个 prompt 执行完毕
                self._progress.pop(job_id, None)
            else:
                cur = self._progress.setdefault(job_id, {"value": 0, "max": 0, "node": None})
                cur["node"] = node


progress_tracker = ProgressTracker()


def _parse_ratio(ratio: str) -> Tuple[int, int]:
    """解析宽高比字符串 "W:H" 为 (w, h) 整数对。"""
    try:
        w, h = map(int, ratio.split(":"))
        if w <= 0 or h <= 0:
            raise ValueError
        return w, h
    except ValueError:
        raise ValueError(f"比例格式错误，应为 'W:H'，例如 '9:16'，收到 {ratio!r}")


def mp_ratio_to_pixels(mp: float, ratio: str) -> Tuple[int, int]:
    """megapixel + 宽高比 -> (width, height)，按 64 对齐（与 FluxResolutionNode 一致）。

    非 qwen 模型的 latent 需要显式宽高，用与 FluxResolutionNode 相同的口径
    在代码侧换算，保证各模型输出尺寸一致。
    """
    rw, rh = _parse_ratio(ratio)
    total = mp * 1_000_000
    w = round((total * rw / rh) ** 0.5 / 64) * 64
    h = round((total * rh / rw) ** 0.5 / 64) * 64
    return max(64, w), max(64, h)


def create_workflow(
    checkpoint: str,
    prompt: str,
    mp: float,
    ratio: str,
    steps: int,
    cfg: float,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """
    创建 ComfyUI 工作流配置

    Args:
        checkpoint: 模型名称（对应 WORKFLOWS 的键）
        prompt: 提示词
        mp: 像素量（百万像素，如 0.6 表示 0.6MP）
        ratio: 宽高比，格式 "W:H"（如 "9:16"）
        steps: 采样步数
        cfg: CFG scale
        seed: 随机种子，如果为 None 则随机生成

    Returns:
        工作流配置字典（模板的深拷贝，不会污染 WORKFLOWS）
    """
    if checkpoint not in WORKFLOWS:
        checkpoint = "zimage"

    if seed is None:
        seed = random.randint(*DEFAULT_SEED_RANGE)

    # 必须深拷贝：模板是模块级共享字典，直接修改会污染后续任务
    workflow = copy.deepcopy(WORKFLOWS[checkpoint])

    if checkpoint == "qwen":
        workflow["15:6"]["inputs"]["seed"] = seed
        workflow["15:6"]["inputs"]["steps"] = max(steps, 6)
        workflow["15:6"]["inputs"]["cfg"] = max(cfg, 1)
        workflow["15:4"]["inputs"]["prompt"] = prompt
        # 分辨率走 FluxResolutionNode：megapixel + 宽高比，latent 宽高由它按
        # divisible_by=64 计算，与 ComfyUI 里的原生控制方式一致（不写死 latent 宽高）
        res = workflow["17"]["inputs"]
        # megapixel 是下拉枚举（0.1~2.5，步进 0.1，共 25 项），任意值会被
        # ComfyUI 校验拒绝（prompt_outputs_failed_validation），必须吸附到最近档位
        mp_snapped = min(2.5, max(0.1, round(mp * 10) / 10))
        res["megapixel"] = f"{mp_snapped:.1f}"
        res["custom_ratio"] = True
        res["custom_aspect_ratio"] = ratio
        return workflow

    # 其余模型（flux/zimage/krea）latent 需要显式宽高：按同一口径（mp+比例，64 对齐）换算
    width, height = mp_ratio_to_pixels(mp, ratio)

    if checkpoint == "flux":
        workflow["6"]["inputs"]["text"] = prompt
        workflow["17"]["inputs"]["steps"] = steps
        workflow["25"]["inputs"]["noise_seed"] = seed
        workflow["27"]["inputs"]["width"] = width
        workflow["27"]["inputs"]["height"] = height
        workflow["30"]["inputs"]["width"] = width
        workflow["30"]["inputs"]["height"] = height
    elif checkpoint == "zimage":
        workflow["3"]["inputs"]["seed"] = seed
        workflow["3"]["inputs"]["steps"] = max(steps, 8)
        workflow["3"]["inputs"]["cfg"] = max(cfg, 1)
        workflow["6"]["inputs"]["text"] = prompt
        workflow["60"]["inputs"]["width"] = width
        workflow["60"]["inputs"]["height"] = height
    elif checkpoint == "krea":
        workflow["3"]["inputs"]["seed"] = seed
        workflow["3"]["inputs"]["steps"] = max(steps, 4)
        workflow["3"]["inputs"]["cfg"] = max(cfg, 1)
        workflow["6"]["inputs"]["text"] = prompt
        workflow["60"]["inputs"]["width"] = width
        workflow["60"]["inputs"]["height"] = height

    return workflow


async def _submit_workflow(
    session: ClientSession, endpoint: str, workflow: Dict[str, Any]
) -> str:
    """
    提交工作流到 ComfyUI

    Args:
        session: HTTP 会话
        endpoint: API 端点
        workflow: 工作流配置

    Returns:
        提示词 ID

    Raises:
        WorkflowSubmissionError: 工作流提交失败
    """
    try:
        async with session.post(
            f"{endpoint}/prompt",
            json={"prompt": workflow, "client_id": CLIENT_ID},
            timeout=DEFAULT_TIMEOUT,
        ) as response:
            if response.status != 200:
                raise WorkflowSubmissionError(f"API请求失败: HTTP {response.status}")

            data = await response.json()
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                raise WorkflowSubmissionError("响应中没有找到 prompt_id")

            logger.info(f"工作流已提交，prompt_id: {prompt_id}")
            return prompt_id

    except ClientError as e:
        raise WorkflowSubmissionError(f"网络请求失败: {e}")
    except Exception as e:
        raise WorkflowSubmissionError(f"提交工作流时发生错误: {e}")


async def get_job_info(endpoint: str, job_id: str) -> Dict[str, Any]:
    """
    获取任务信息

    Args:
        session: HTTP 会话
        endpoint: API 端点
        job_id: 任务 ID

    Returns:
        任务信息字典
    """
    try:
        session = await manager.create_session()
        async with session.get(f"{endpoint}/history/{job_id}", timeout=DEFAULT_TIMEOUT) as response:
            if response.status != 200:
                raise Exception(f"API请求失败: HTTP {response.status}")

            info = await response.json()
            return info.get(job_id, {})

    except ClientError as e:
        raise Exception(f"网络请求失败: {e}")

    except Exception as e:
        raise Exception(f"获取任务信息时发生错误: {e}")


async def download_image(endpoint: str, filename: str, subfolder: str) -> bytes:
    """
    下载生成的图片

    Args:
        session: HTTP 会话
        endpoint: API 端点
        image_filename: 图片文件名

    Returns:
        图片的二进制数据

    Raises:
        ImageDownloadError: 图片下载失败
    """

    url = f"{endpoint}/view?filename={filename}&subfolder={subfolder}&type=output"

    try:
        session = await manager.create_session()
        async with session.get(url, timeout=DEFAULT_TIMEOUT) as response:
            if response.status != 200:
                raise ImageDownloadError(
                    f"下载图片失败: HTTP {response.status}, url: {url}"
                )

            image_data = await response.read()
            logger.info(f" 图片下载成功，大小: {len(image_data)} bytes, url:{url}")
            return image_data

    except ClientError as e:
        raise ImageDownloadError(f"下载图片时网络错误: {e}")


async def generate_image(
    endpoint: str,
    checkpoint: str,
    prompt: str,
    mp: float = 0.6,
    ratio: str = "9:16",
    steps: int = 16,
    cfg: float = 1.0,
    seed: Optional[int] = None,
) -> Optional[str]:
    """
    通过 ComfyUI API 异步生成图片

    Args:
        endpoint: ComfyUI API 端点
        checkpoint: 检查点模型名称（对应 WORKFLOWS 的键）
        prompt: 生成图片的文本描述
        mp: 像素量（百万像素，如 0.6 表示 0.6MP）
        ratio: 宽高比，格式 "W:H"（如 "9:16"）
        steps: 采样步数
        cfg: CFG scale
        seed: 随机种子，如果为 None 则随机生成

    Returns:
        提示词 ID，失败时返回 None

    Raises:
        ValueError: 参数格式错误
        ComfyAPIError: API 调用相关错误
    """
    try:
        # 创建工作流（mp+比例在各模型分支内换算/透传）
        workflow = create_workflow(checkpoint, prompt, mp, ratio, steps, cfg, seed)

        logger.info(f"开始生成图片: [{mp}MP {ratio}] {prompt}")

        # 创建 HTTP 会话
        session = await manager.create_session()
        # 确保 WebSocket 进度跟踪已启动（提交后再启动会错过早期事件）
        progress_tracker.ensure_running(endpoint)
        # 提交工作流
        return await _submit_workflow(session, endpoint, workflow)

    except (ComfyAPIError, ValueError):
        # 重新抛出已知的异常类型
        raise
    except Exception as e:
        logger.exception(f"生成图片时发生未知错误: {e}")
        return None


async def job_status(endpoint: str, job_id: str) -> Optional[Dict[str, Any]]:
    """
    获取任务状态

    Args:
        endpoint: ComfyUI API 端点
        prompt_id: 提示词 ID

    Returns:
        包含任务状态的字典，或在找不到时返回 None。
        可能的 'status' 值: 'completed', 'running', 'pending', 'not_found'

    Raises:
        ComfyAPIError: API 调用相关错误
    """
    try:
        session = await manager.create_session()
        # 检查历史记录中是否已完成
        async with session.get(f"{endpoint}/history/{job_id}", timeout=DEFAULT_TIMEOUT) as response:
            if response.status == 200:
                history = await response.json()
                if job_id in history:
                    logger.info(f"任务 {job_id} 已完成。")
                    return {"status": "completed", "data": history[job_id]}
            elif response.status != 404:
                logger.warning(f"获取历史记录失败: HTTP {response.status}")

        # 如果不在历史记录中，检查队列
        async with session.get(f"{endpoint}/queue", timeout=DEFAULT_TIMEOUT) as response:
            if response.status != 200:
                # 查询失败 ≠ 任务丢失：必须走 ComfyAPIError 让调用方用 poll_errors 宽限重试，
                # 否则一次瞬时 500/超时就会误杀健康任务
                raise ComfyAPIError(f"获取队列状态失败: HTTP {response.status}")

            queue_data = await response.json()

            # 检查正在运行的队列
            # item format: [prompt_number, prompt_id, prompt, extra_prompt_data, client_id]
            for item in queue_data.get("queue_running", []):
                if len(item) > 1 and item[1] == job_id:
                    logger.info(f"任务 {job_id} 正在运行。")
                    return {"status": "running", "position": 0, "data": item}

            # 检查待处理的队列
            for idx, item in enumerate(queue_data.get("queue_pending", [])):
                if len(item) > 1 and item[1] == job_id:
                    logger.info(f"任务 {job_id} 正在等待。")
                    return {"status": "pending", "position": idx + 1, "data": item}

            logger.info(f"任务 {job_id} 在历史记录或当前队列中未找到。")
            return {"status": "not_found", "data": {}}

    except ClientError as e:
        raise ComfyAPIError(f"获取任务状态时网络错误: {e}") from e
    except Exception as e:
        raise ComfyAPIError(f"获取任务状态时发生未知错误: {e}") from e


async def job_cancel(endpoint: str, job_id: str) -> bool:
    """
    取消任务（vanilla ComfyUI 标准 API：从队列删除；运行中的任务需另调 /interrupt）。

    Args:
        endpoint: ComfyUI API 端点
        job_id: 任务 ID
    """
    try:
        session = await manager.create_session()
        async with session.post(
            f"{endpoint}/queue",
            json={"delete": [job_id]},
            timeout=DEFAULT_TIMEOUT,
        ) as response:
            if response.status == 200:
                logger.info(f"任务 {job_id} 已从队列删除。")
                return True
            else:
                logger.warning(f"取消任务失败: HTTP {response.status}")
                return False
    except ClientError as e:
        raise ComfyAPIError(f"取消任务时网络错误: {e}") from e
