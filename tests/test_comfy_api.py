"""测试 utils/comfy_api.py 中的 ComfyUI API 功能"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import io


pytestmark = pytest.mark.asyncio


class TestComfyAPIError:
    """测试 ComfyAPIError 异常类"""

    def test_comfy_api_error_inheritance(self):
        """测试 ComfyAPIError 继承自 Exception"""
        from utils.comfy_api import ComfyAPIError

        error = ComfyAPIError("Test error")
        assert isinstance(error, Exception)
        assert str(error) == "Test error"


class TestWorkflowSubmissionError:
    """测试 WorkflowSubmissionError 异常类"""

    def test_workflow_submission_error_inheritance(self):
        """测试 WorkflowSubmissionError 继承自 ComfyAPIError"""
        from utils.comfy_api import WorkflowSubmissionError

        error = WorkflowSubmissionError("Submission failed")
        assert isinstance(error, Exception)
        assert str(error) == "Submission failed"


class TestImageDownloadError:
    """测试 ImageDownloadError 异常类"""

    def test_image_download_error_inheritance(self):
        """测试 ImageDownloadError 继承自 ComfyAPIError"""
        from utils.comfy_api import ImageDownloadError

        error = ImageDownloadError("Download failed")
        assert isinstance(error, Exception)


class TestParseImageSize:
    """测试 _parse_image_size 函数"""

    def test_valid_size(self):
        """测试有效的尺寸格式"""
        from utils.comfy_api import _parse_image_size

        width, height = _parse_image_size("512x512")
        assert width == 512
        assert height == 512

    def test_valid_size_uppercase(self):
        """测试大写尺寸格式"""
        from utils.comfy_api import _parse_image_size

        width, height = _parse_image_size("1024X768")
        assert width == 1024
        assert height == 768

    def test_invalid_format(self):
        """测试无效格式"""
        from utils.comfy_api import _parse_image_size

        with pytest.raises(ValueError) as exc_info:
            _parse_image_size("512x")
        assert "格式错误" in str(exc_info.value)

    def test_invalid_non_numeric(self):
        """测试非数字值"""
        from utils.comfy_api import _parse_image_size

        with pytest.raises(ValueError) as exc_info:
            _parse_image_size("abcxdef")
        assert "格式错误" in str(exc_info.value)

    def test_missing_separator(self):
        """测试缺少分隔符"""
        from utils.comfy_api import _parse_image_size

        with pytest.raises(ValueError) as exc_info:
            _parse_image_size("512512")
        assert "格式错误" in str(exc_info.value)


class TestCreateWorkflow:
    """测试 create_workflow 函数"""

    def test_flux_workflow_creation(self):
        """测试 Flux 工作流创建"""
        from utils.comfy_api import create_workflow

        workflow = create_workflow(
            checkpoint="flux",
            prompt="A beautiful landscape",
            width=512,
            height=512,
            steps=20,
            cfg=7.0,
            seed=12345,
        )

        assert "6" in workflow
        assert "17" in workflow
        assert workflow["6"]["inputs"]["text"] == "A beautiful landscape"
        assert workflow["17"]["inputs"]["steps"] == 20

    def test_zimage_workflow_creation(self):
        """测试 ZImage 工作流创建"""
        from utils.comfy_api import create_workflow

        workflow = create_workflow(
            checkpoint="zimage",
            prompt="A cat",
            width=768,
            height=768,
            steps=16,
            cfg=5.0,
            seed=67890,
        )

        assert "3" in workflow
        assert workflow["3"]["inputs"]["seed"] == 67890
        assert workflow["3"]["inputs"]["steps"] == 16
        assert workflow["3"]["inputs"]["cfg"] == 5.0
        assert workflow["6"]["inputs"]["text"] == "A cat"

    def test_unknown_checkpoint_fallback(self):
        """测试未知 checkpoint 回退到默认值"""
        from utils.comfy_api import create_workflow

        workflow = create_workflow(
            checkpoint="unknown_model",
            prompt="Test",
            width=512,
            height=512,
            steps=10,
            cfg=1.0,
        )

        # 应该回退到 zimage
        assert "3" in workflow

    def test_random_seed_when_none(self):
        """测试 seed 为 None 时生成随机种子"""
        from utils.comfy_api import create_workflow

        workflow = create_workflow(
            checkpoint="zimage",
            prompt="Test",
            width=512,
            height=512,
            steps=10,
            cfg=1.0,
            seed=None,
        )

        assert "seed" in workflow["3"]["inputs"]
        assert 0 <= workflow["3"]["inputs"]["seed"] <= 0xFFFFFFFFFFFFFFFF

    def test_steps_and_cfg_bounds(self):
        """测试 steps 和 cfg 的边界处理"""
        from utils.comfy_api import create_workflow

        workflow = create_workflow(
            checkpoint="zimage",
            prompt="Test",
            width=512,
            height=512,
            steps=2,  # 小于 8
            cfg=0.5,  # 小于 1
            seed=1,
        )

        # 应该被 max 函数修正
        assert workflow["3"]["inputs"]["steps"] >= 8
        assert workflow["3"]["inputs"]["cfg"] >= 1


class TestSubmitWorkflow:
    """测试 _submit_workflow 函数"""

    async def test_successful_submission(self):
        """测试成功提交工作流"""
        from utils.comfy_api import _submit_workflow, WorkflowSubmissionError

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"prompt_id": "test-prompt-id"})

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_response
        mock_context.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        workflow = {"test": "workflow"}

        with patch.object(mock_session.post, 'return_value', mock_context):
            result = await _submit_workflow(mock_session, "http://test", workflow)
            assert result == "test-prompt-id"

    async def test_submission_error_status(self):
        """测试提交时 HTTP 错误状态"""
        from utils.comfy_api import _submit_workflow, WorkflowSubmissionError

        mock_response = MagicMock()
        mock_response.status = 500

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        workflow = {"test": "workflow"}

        with pytest.raises(WorkflowSubmissionError) as exc_info:
            await _submit_workflow(mock_session, "http://test", workflow)

        assert "API 请求失败" in str(exc_info.value)

    async def test_missing_prompt_id(self):
        """测试响应缺少 prompt_id"""
        from utils.comfy_api import _submit_workflow, WorkflowSubmissionError

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"other_key": "value"})

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        workflow = {"test": "workflow"}

        with pytest.raises(WorkflowSubmissionError) as exc_info:
            await _submit_workflow(mock_session, "http://test", workflow)

        assert "prompt_id" in str(exc_info.value)


class TestGenerateImage:
    """测试 generate_image 函数"""

    async def test_successful_generation(self):
        """测试成功生成图片"""
        from utils.comfy_api import generate_image

        mock_manager = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"prompt_id": "test-id"})

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("utils.comfy_api.manager", mock_manager):
            result = await generate_image(
                endpoint="http://test",
                checkpoint="zimage",
                prompt="Test prompt",
                size="512x512",
                steps=16,
                cfg=5.0,
                seed=12345,
            )
            assert result == "test-id"

    async def test_invalid_size_format(self):
        """测试无效尺寸格式"""
        from utils.comfy_api import generate_image

        with pytest.raises(ValueError):
            await generate_image(
                endpoint="http://test",
                checkpoint="zimage",
                prompt="Test",
                size="invalid",
            )

    async def test_exception_handling(self):
        """测试异常处理"""
        from utils.comfy_api import generate_image

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(side_effect=Exception("Session error"))

        with patch("utils.comfy_api.manager", mock_manager):
            result = await generate_image(
                endpoint="http://test",
                checkpoint="zimage",
                prompt="Test",
                size="512x512",
            )
            assert result is None


class TestJobStatus:
    """测试 job_status 函数"""

    async def test_completed_job(self):
        """测试已完成的任务"""
        from utils.comfy_api import job_status

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"job-123": {"status": "completed"}})

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("utils.comfy_api.manager", mock_manager):
            result = await job_status("http://test", "job-123")
            assert result["status"] == "completed"

    async def test_running_job(self):
        """测试运行中的任务"""
        from utils.comfy_api import job_status

        # 历史记录返回 404，队列中显示运行中
        mock_history_response = MagicMock()
        mock_history_response.status = 404

        mock_queue_response = MagicMock()
        mock_queue_response.status = 200
        mock_queue_response.json = AsyncMock(return_value={
            "queue_running": [["1", "job-123", {}]],
            "queue_pending": [],
        })

        history_context = MagicMock()
        history_context.__aenter__ = AsyncMock(return_value=mock_history_response)
        history_context.__aexit__ = AsyncMock(return_value=None)

        queue_context = MagicMock()
        queue_context.__aenter__ = AsyncMock(return_value=mock_queue_response)
        queue_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=[history_context, queue_context])

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("utils.comfy_api.manager", mock_manager):
            result = await job_status("http://test", "job-123")
            assert result["status"] == "running"

    async def test_pending_job(self):
        """测试等待中的任务"""
        from utils.comfy_api import job_status

        mock_history_response = MagicMock()
        mock_history_response.status = 404

        mock_queue_response = MagicMock()
        mock_queue_response.status = 200
        mock_queue_response.json = AsyncMock(return_value={
            "queue_running": [],
            "queue_pending": [["1", "job-123", {}]],
        })

        history_context = MagicMock()
        history_context.__aenter__ = AsyncMock(return_value=mock_history_response)
        history_context.__aexit__ = AsyncMock(return_value=None)

        queue_context = MagicMock()
        queue_context.__aenter__ = AsyncMock(return_value=mock_queue_response)
        queue_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=[history_context, queue_context])

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("utils.comfy_api.manager", mock_manager):
            result = await job_status("http://test", "job-123")
            assert result["status"] == "pending"

    async def test_not_found_job(self):
        """测试找不到的任务"""
        from utils.comfy_api import job_status

        mock_history_response = MagicMock()
        mock_history_response.status = 404

        mock_queue_response = MagicMock()
        mock_queue_response.status = 200
        mock_queue_response.json = AsyncMock(return_value={
            "queue_running": [],
            "queue_pending": [],
        })

        history_context = MagicMock()
        history_context.__aenter__ = AsyncMock(return_value=mock_history_response)
        history_context.__aexit__ = AsyncMock(return_value=None)

        queue_context = MagicMock()
        queue_context.__aenter__ = AsyncMock(return_value=mock_queue_response)
        queue_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=[history_context, queue_context])

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("utils.comfy_api.manager", mock_manager):
            result = await job_status("http://test", "job-123")
            assert result["status"] == "not_found"


class TestDownloadImage:
    """测试 download_image 函数"""

    async def test_successful_download(self):
        """测试成功下载图片"""
        from utils.comfy_api import download_image

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"image_data")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("utils.comfy_api.manager", mock_manager):
            result = await download_image("http://test", "test.png", "output")
            assert result == b"image_data"

    async def test_download_failure(self):
        """测试下载失败"""
        from utils.comfy_api import download_image, ImageDownloadError

        mock_response = MagicMock()
        mock_response.status = 404

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("utils.comfy_api.manager", mock_manager):
            with pytest.raises(ImageDownloadError):
                await download_image("http://test", "test.png", "output")


class TestJobCancel:
    """测试 job_cancel 函数"""

    async def test_successful_cancel(self):
        """测试成功取消任务"""
        from utils.comfy_api import job_cancel

        mock_response = MagicMock()
        mock_response.status = 200

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("utils.comfy_api.manager", mock_manager):
            result = await job_cancel("http://test", "job-123")
            assert result is True

    async def test_cancel_failure(self):
        """测试取消失败"""
        from utils.comfy_api import job_cancel

        mock_response = MagicMock()
        mock_response.status = 500

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)

        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(return_value=mock_session)

        with patch("utils.comfy_api.manager", mock_manager):
            result = await job_cancel("http://test", "job-123")
            assert result is False
