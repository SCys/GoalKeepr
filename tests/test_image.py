"""测试 handlers/commands/image.py 中的图像生成功能"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta


pytestmark = pytest.mark.asyncio


class TestImageGenerationBasics:
    """测试图像生成基本功能"""

    def test_size_mapping_exists(self):
        """验证尺寸映射存在"""
        from handlers.commands.image import SIZE_MAPPING

        assert "mini" in SIZE_MAPPING
        assert "small" in SIZE_MAPPING
        assert "large" in SIZE_MAPPING

    def test_is_valid_size_valid(self):
        """测试有效尺寸验证"""
        from handlers.commands.image import _is_valid_size

        assert _is_valid_size("512x512") is True
        assert _is_valid_size("1024x768") is True

    def test_is_valid_size_invalid(self):
        """测试无效尺寸验证"""
        from handlers.commands.image import _is_valid_size

        assert _is_valid_size("invalid") is False
        assert _is_valid_size("10000x10000") is False

    def test_allowed_models(self):
        """测试允许的模型列表"""
        from handlers.commands.image import _allowed_models

        models = _allowed_models()
        assert len(models) > 0


class TestPermissionManager:
    """测试权限管理类"""

    def test_parse_user_groups_config_valid(self):
        """测试解析有效的用户组配置"""
        from handlers.commands.image import PermissionManager
        from configparser import ConfigParser

        config = ConfigParser()
        config["image"] = {
            "users": "123456,789012",
            "groups": "-1001000000000,-1002000000000"
        }

        users, groups = PermissionManager.parse_user_groups_config(config)

        assert 123456 in users
        assert 789012 in users
        assert -1001000000000 in groups

    def test_parse_user_groups_config_empty(self):
        """测试解析空配置"""
        from handlers.commands.image import PermissionManager
        from configparser import ConfigParser

        config = ConfigParser()
        config["image"] = {}

        users, groups = PermissionManager.parse_user_groups_config(config)

        assert users == []
        assert groups == []

    def test_check_permission_user(self):
        """测试用户权限检查"""
        from handlers.commands.image import PermissionManager

        result = PermissionManager.check_permission(
            user_id=123456,
            chat_id=-1001000000000,
            users=[123456, 789012],
            groups=[]
        )
        assert result is True

    def test_check_permission_group(self):
        """测试群组权限检查"""
        from handlers.commands.image import PermissionManager

        result = PermissionManager.check_permission(
            user_id=999999,
            chat_id=-1001000000000,
            users=[],
            groups=[-1001000000000]
        )
        assert result is True

    def test_check_permission_no_access(self):
        """测试无权限情况"""
        from handlers.commands.image import PermissionManager

        result = PermissionManager.check_permission(
            user_id=999999,
            chat_id=-1001000000000,
            users=[123456],
            groups=[-1002000000000]
        )
        assert result is False


class TestPromptProcessor:
    """测试提示词处理类"""

    async def test_extract_prompt_from_message(self):
        """测试从消息提取提示词"""
        from handlers.commands.image import PromptProcessor

        mock_event = MagicMock()
        mock_event.text = "/image a cat"

        reply_msg = MagicMock()
        reply_msg.text = "fluffy"
        mock_event.get_reply_message = AsyncMock(return_value=reply_msg)

        prompt = await PromptProcessor.extract_prompt_from_message(mock_event)
        assert "fluffy" in prompt
        assert "a cat" in prompt

    async def test_extract_prompt_no_reply(self):
        """测试没有回复消息"""
        from handlers.commands.image import PromptProcessor

        mock_event = MagicMock()
        mock_event.text = "/image a cat"
        mock_event.get_reply_message = AsyncMock(return_value=None)

        prompt = await PromptProcessor.extract_prompt_from_message(mock_event)
        assert "a cat" in prompt

    def test_parse_options_basic(self):
        """测试解析基本选项"""
        from handlers.commands.image import PromptProcessor

        prompt, options = PromptProcessor.parse_options("a cat")

        assert "size" in options
        assert "step" in options
        assert "model" in options
        assert "cfg" in options

    def test_parse_options_with_size(self):
        """测试解析尺寸选项"""
        from handlers.commands.image import PromptProcessor

        prompt, options = PromptProcessor.parse_options("[size:small] a cat")

        assert options["size"] == "768x768"

    def test_parse_options_with_step(self):
        """测试解析步数选项"""
        from handlers.commands.image import PromptProcessor

        prompt, options = PromptProcessor.parse_options("[step:30] a cat")

        assert options["step"] == 30

    def test_parse_options_with_model(self):
        """测试解析模型选项"""
        from handlers.commands.image import PromptProcessor

        prompt, options = PromptProcessor.parse_options("[model:flux] a cat")

        assert options["model"] == "flux"

    def test_parse_options_with_cfg(self):
        """测试解析 CFG 选项"""
        from handlers.commands.image import PromptProcessor

        prompt, options = PromptProcessor.parse_options("[cfg:7.5] a cat")

        assert options["cfg"] == 7.5

    async def test_optimize_prompt_short(self):
        """测试优化短提示词"""
        from handlers.commands.image import PromptProcessor

        prompt = "a cat"
        optimized, reply_content = await PromptProcessor.optimize_prompt(prompt)

        # 短提示词应该返回原文
        assert prompt in reply_content or optimized

    async def test_optimize_prompt_long(self):
        """测试优化长提示词"""
        from handlers.commands.image import PromptProcessor

        prompt = "a cat, fluffy, cute, sitting"
        optimized, reply_content = await PromptProcessor.optimize_prompt(prompt)

        # 长提示词（有逗号）直接返回
        assert prompt == reply_content


class TestTaskClass:
    """测试 Task 数据类"""

    def test_task_message_creation(self):
        """测试 TaskMessage 创建"""
        from handlers.commands.image import TaskMessage

        msg = TaskMessage(
            chat_id=-1001000000000,
            chat_name="Test",
            user_id=123456,
            user_name="TestUser",
            message_id=1,
            reply_message_id=2,
            reply_content="a cat"
        )

        assert msg.chat_id == -1001000000000
        assert msg.user_id == 123456

    def test_task_creation(self):
        """测试 Task 创建"""
        from handlers.commands.image import Task, TaskMessage

        msg = TaskMessage(
            chat_id=-1001000000000,
            chat_name="Test",
            user_id=123456,
            user_name="TestUser",
            message_id=1,
            reply_message_id=2,
            reply_content="a cat"
        )

        task = Task(
            msg=msg,
            prompt="a cat",
            options={"size": "512x512"},
            created_at=datetime.now().timestamp(),
            status="queued",
            job_id=None,
            task_id="test-uuid"
        )

        assert task.status == "queued"
        assert task.prompt == "a cat"

    async def test_task_cancel(self):
        """测试任务取消"""
        from handlers.commands.image import Task, TaskMessage

        msg = TaskMessage(
            chat_id=-1001000000000,
            chat_name="Test",
            user_id=123456,
            user_name="TestUser",
            message_id=1,
            reply_message_id=2,
            reply_content="a cat"
        )

        task = Task(
            msg=msg,
            prompt="a cat",
            options={},
            created_at=datetime.now().timestamp(),
            status="running",
            job_id="test-job-id",
            task_id="test-uuid"
        )

        # 没有 job_id 时取消应该不报错
        task_no_job = Task(
            msg=msg,
            prompt="a cat",
            options={},
            created_at=datetime.now().timestamp(),
            status="queued",
            job_id=None,
            task_id="test-uuid"
        )

        await task_no_job.cancel()  # 应该不抛出异常


class TestImageGenerationError:
    """测试图像生成错误类"""

    def test_image_generation_error(self):
        """测试图像生成错误"""
        from handlers.commands.image import ImageGenerationError

        error = ImageGenerationError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)


class TestSafeOperations:
    """测试安全操作函数"""

    async def test_safe_edit_text_valid(self):
        """测试安全编辑有效消息"""
        from handlers.commands.image import safe_edit_text

        mock_manager = MagicMock()
        mock_manager.edit_text = AsyncMock()

        with patch("handlers.commands.image.manager", mock_manager):
            await safe_edit_text(-1001000000000, 123, "edited text")
            mock_manager.edit_text.assert_called_once()

    async def test_safe_edit_text_invalid_id(self):
        """测试安全编辑无效 ID"""
        from handlers.commands.image import safe_edit_text

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.image.manager", mock_manager):
            await safe_edit_text(-1001000000000, -1, "text")
            # 不应该调用 edit_text
            mock_manager.edit_text.assert_not_called()

    async def test_safe_delete_message_valid(self):
        """测试安全删除有效消息"""
        from handlers.commands.image import safe_delete_message

        mock_manager = MagicMock()
        mock_manager.delete_message = AsyncMock()

        with patch("handlers.commands.image.manager", mock_manager):
            await safe_delete_message(-1001000000000, 123)
            mock_manager.delete_message.assert_called_once()

    async def test_safe_delete_message_invalid_id(self):
        """测试安全删除无效 ID"""
        from handlers.commands.image import safe_delete_message

        mock_manager = MagicMock()
        mock_manager.logger = MagicMock()

        with patch("handlers.commands.image.manager", mock_manager):
            await safe_delete_message(-1001000000000, -1)
            mock_manager.delete_message.assert_not_called()
