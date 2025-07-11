import asyncio
import random
from typing import Optional, Dict, Any, Tuple

from aiohttp import ClientSession, ClientTimeout, ClientError

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


def _parse_image_size(size: str) -> Tuple[int, int]:
    """
    解析图片尺寸字符串

    Args:
        size: 尺寸字符串，格式为 "widthxheight"

    Returns:
        元组 (width, height)

    Raises:
        ValueError: 格式错误时抛出
    """
    try:
        width, height = map(int, size.lower().split("x"))
        return width, height
    except ValueError:
        raise ValueError("尺寸格式错误，应为 'widthxheight'，例如 '512x512'")


def create_workflow(
    checkpoint: str,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """
    创建 ComfyUI 工作流配置

    Args:
        model: 模型名称
        prompt: 提示词
        width: 图片宽度
        height: 图片高度
        steps: 采样步数
        cfg: CFG scale
        seed: 随机种子，如果为 None 则随机生成

    Returns:
        工作流配置字典
    """
    if seed is None:
        seed = random.randint(*DEFAULT_SEED_RANGE)

    if checkpoint not in WORKFLOWS:
        checkpoint = "flux"

    if seed is None:
        seed = random.randint(*DEFAULT_SEED_RANGE)

    workflow = WORKFLOWS[checkpoint]

    if checkpoint == "flux":
        workflow["6"]["inputs"]["text"] = prompt
        workflow["17"]["inputs"]["steps"] = steps
        workflow["27"]["inputs"]["width"] = width
        workflow["27"]["inputs"]["height"] = height
        workflow["30"]["inputs"]["width"] = width
        workflow["30"]["inputs"]["height"] = height
        workflow["27"]["inputs"]["batch_size"] = 1
        workflow["27"]["inputs"]["noise_seed"] = seed
        workflow["26"]["inputs"]["guidance"] = cfg

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
            json={"prompt": workflow},
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


async def get_job_info(
    session: ClientSession, endpoint: str, job_id: str
) -> Dict[str, Any]:
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
        async with session.get(f"{endpoint}/history/{job_id}") as response:
            if response.status != 200:
                raise Exception(f"API请求失败: HTTP {response.status}")

            return await response.json()

    except ClientError as e:
        raise Exception(f"网络请求失败: {e}")

    except Exception as e:
        raise Exception(f"获取任务信息时发生错误: {e}")


async def _wait_for_image_generation(
    session: ClientSession, endpoint: str, prompt_id: str
) -> str:
    """
    等待图片生成完成并获取文件名

    Args:
        session: HTTP 会话
        endpoint: API 端点
        prompt_id: 提示词 ID

    Returns:
        生成的图片文件名

    Raises:
        ImageGenerationTimeoutError: 生成超时
    """
    for attempt in range(MAX_RETRIES):
        await asyncio.sleep(RETRY_DELAY)

        try:
            prompt_data = await get_job_info(session, endpoint, prompt_id)

            # 获取生成的图片文件名
            outputs = prompt_data.get("outputs", {})
            if not outputs:
                logger.debug(
                    f"prompt_id {prompt_id} 的输出为空，尝试 {attempt + 1}/{MAX_RETRIES}"
                )
                continue

            # 获取第一个输出节点的结果
            for output_key, output_data in outputs.items():
                images = output_data.get("images", [])
                if images:
                    image_filename = images[0]["filename"]
                    logger.info(f"图片生成完成: {image_filename}")
                    return image_filename

            logger.debug(f"输出中暂无图片，尝试 {attempt + 1}/{MAX_RETRIES}")

        except ClientError as e:
            logger.warning(
                f"检查生成状态时网络错误: {e}, 尝试 {attempt + 1}/{MAX_RETRIES}"
            )
        except Exception as e:
            logger.error(
                f"检查生成状态时发生错误: {e}, 尝试 {attempt + 1}/{MAX_RETRIES}"
            )

    raise ImageGenerationTimeoutError(f"图片生成超时，已尝试 {MAX_RETRIES} 次")


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
        async with ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.get(url) as response:
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
    size: str = "1024x1024",
    steps: int = 16,
    cfg: float = 1.0,
    seed: Optional[int] = None,
) -> Optional[str]:
    """
    通过 ComfyUI API 异步生成图片

    Args:
        endpoint: ComfyUI API 端点
        checkpoint: 检查点模型名称（暂未使用）
        prompt: 生成图片的文本描述
        size: 图片尺寸，格式为 "宽x高"，如 "512x512"
        steps: 采样步数，默认为 12
        cfg: CFG scale，默认为 1.0（暂未使用）
        seed: 随机种子，如果为 None 则随机生成

    Returns:
        图片的二进制数据，失败时返回 None

    Raises:
        ValueError: 参数格式错误
        ComfyAPIError: API 调用相关错误
    """
    try:
        # 解析尺寸
        width, height = _parse_image_size(size)

        # 创建工作流
        workflow = create_workflow(checkpoint, prompt, width, height, steps, cfg, seed)

        logger.info(f"开始生成图片: [{size}] {prompt}")

        # 创建 HTTP 会话
        async with ClientSession(timeout=DEFAULT_TIMEOUT) as session:
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
        async with ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            # 检查历史记录中是否已完成
            async with session.get(f"{endpoint}/history/{job_id}") as response:
                if response.status == 200:
                    history = await response.json()
                    if job_id in history:
                        logger.info(f"任务 {job_id} 已完成。")
                        return {"status": "completed", "data": history[job_id]}
                elif response.status != 404:
                    logger.warning(f"获取历史记录失败: HTTP {response.status}")

            # 如果不在历史记录中，检查队列
            async with session.get(f"{endpoint}/queue") as response:
                if response.status == 200:
                    queue_data = await response.json()

                    # 检查正在运行的队列
                    # item format: [prompt_number, prompt_id, prompt, extra_prompt_data, client_id]
                    for item in queue_data.get("queue_running", []):
                        if len(item) > 1 and item[1] == job_id:
                            logger.info(f"任务 {job_id} 正在运行。")
                            return {"status": "running", "data": item}

                    # 检查待处理的队列
                    for item in queue_data.get("queue_pending", []):
                        if len(item) > 1 and item[1] == job_id:
                            logger.info(f"任务 {job_id} 正在等待。")
                            return {"status": "pending", "data": item}
                else:
                    logger.warning(f"获取队列状态失败: HTTP {response.status}")

            logger.info(f"任务 {job_id} 在历史记录或当前队列中未找到。")
            return {"status": "not_found", "data": {}}

    except ClientError as e:
        raise ComfyAPIError(f"获取任务状态时网络错误: {e}") from e
    except Exception as e:
        raise ComfyAPIError(f"获取任务状态时发生未知错误: {e}") from e


async def job_cancel(endpoint: str, job_id: str) -> bool:
    """
    取消任务

    Args:
        endpoint: ComfyUI API 端点
        job_id: 任务 ID
    """
    try:
        async with ClientSession(timeout=DEFAULT_TIMEOUT) as session:
            async with session.post(f"{endpoint}/cancel/{job_id}") as response:
                if response.status == 200:
                    logger.info(f"任务 {job_id} 已取消。")
                    return True
                else:
                    logger.warning(f"取消任务失败: HTTP {response.status}")
                    return False
    except ClientError as e:
        raise ComfyAPIError(f"取消任务时网络错误: {e}") from e
