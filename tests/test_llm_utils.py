"""测试 handlers/utils/llm.py 中的 SPAM 检测功能"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import orjson


pytestmark = pytest.mark.asyncio


class TestUserFullname:
    """测试 _user_fullname 辅助函数"""

    def test_fullname_with_both_names(self):
        """测试有姓和名的用户"""
        from handlers.utils.llm import _user_fullname

        user = MagicMock()
        user.first_name = "John"
        user.last_name = "Doe"

        result = _user_fullname(user)
        assert result == "John Doe"

    def test_fullname_with_only_first_name(self):
        """测试只有名的用户"""
        from handlers.utils.llm import _user_fullname

        user = MagicMock()
        user.first_name = "John"
        user.last_name = None

        result = _user_fullname(user)
        assert result == "John"

    def test_fullname_with_only_last_name(self):
        """测试只有姓的用户"""
        from handlers.utils.llm import _user_fullname

        user = MagicMock()
        user.first_name = None
        user.last_name = "Doe"

        result = _user_fullname(user)
        assert result == "Doe"

    def test_fullname_empty(self):
        """测试无姓名的用户"""
        from handlers.utils.llm import _user_fullname

        user = MagicMock()
        user.first_name = None
        user.last_name = None

        result = _user_fullname(user)
        assert result == ""


class TestCheckSpamsWithLLM:
    """测试 check_spams_with_llm 函数"""

    async def test_successful_spam_detection(self):
        """测试成功检测 SPAM"""
        from handlers.utils.llm import check_spams_with_llm

        # 模拟成员数据
        members = []
        for i in range(2):
            member = MagicMock()
            user = MagicMock()
            user.id = 1000 + i
            user.username = f"spam_user_{i}"
            user.first_name = f"Test{i}"
            user.last_name = "User"
            member.user = user
            members.append(member)

        # 模拟 LLM 响应
        llm_response = orjson.dumps({
            "spams": [
                {"id": 1000, "reason": "Username contains spam pattern"},
                {"id": 1001, "reason": "Bio contains promotional content"},
            ]
        }).decode("utf-8")

        with patch("handlers.utils.llm.chat_completions", AsyncMock(return_value=llm_response)):
            result = await check_spams_with_llm(members)

        assert len(result) == 2
        assert (1000, "Username contains spam pattern") in result
        assert (1001, "Bio contains promotional content") in result

    async def test_no_spam_detected(self):
        """测试未检测到 SPAM"""
        from handlers.utils.llm import check_spams_with_llm

        members = [MagicMock()]
        members[0].user = MagicMock(id=1000, username="good_user", first_name="Good", last_name="User")

        llm_response = orjson.dumps({"spams": []}).decode("utf-8")

        with patch("handlers.utils.llm.chat_completions", AsyncMock(return_value=llm_response)):
            result = await check_spams_with_llm(members)

        assert result == []

    async def test_empty_members_list(self):
        """测试空成员列表"""
        from handlers.utils.llm import check_spams_with_llm

        result = await check_spams_with_llm([])

        assert result == []

    async def test_llm_returns_none(self):
        """测试 LLM 返回 None"""
        from handlers.utils.llm import check_spams_with_llm

        members = [MagicMock()]
        members[0].user = MagicMock(id=1000, username="user", first_name="Test", last_name="User")

        with patch("handlers.utils.llm.chat_completions", AsyncMock(return_value=None)):
            result = await check_spams_with_llm(members)

        assert result == []

    async def test_llm_returns_empty_string(self):
        """测试 LLM 返回空字符串"""
        from handlers.utils.llm import check_spams_with_llm

        members = [MagicMock()]
        members[0].user = MagicMock(id=1000, username="user", first_name="Test", last_name="User")

        with patch("handlers.utils.llm.chat_completions", AsyncMock(return_value="")):
            result = await check_spams_with_llm(members)

        assert result == []

    async def test_invalid_json_response(self):
        """测试无效的 JSON 响应"""
        from handlers.utils.llm import check_spams_with_llm

        members = [MagicMock()]
        members[0].user = MagicMock(id=1000, username="user", first_name="Test", last_name="User")

        with patch("handlers.utils.llm.chat_completions", AsyncMock(return_value="invalid json")):
            with patch("handlers.utils.llm.logger") as mock_logger:
                result = await check_spams_with_llm(members)

        assert result == []
        mock_logger.error.assert_called()

    async def test_json_without_spams_key(self):
        """测试 JSON 中没有 spams 键"""
        from handlers.utils.llm import check_spams_with_llm

        members = [MagicMock()]
        members[0].user = MagicMock(id=1000, username="user", first_name="Test", last_name="User")

        llm_response = orjson.dumps({"other_key": "value"}).decode("utf-8")

        with patch("handlers.utils.llm.chat_completions", AsyncMock(return_value=llm_response)):
            with patch("handlers.utils.llm.logger") as mock_logger:
                result = await check_spams_with_llm(members)

        assert result == []
        # 应该记录警告日志
        assert any("Empty data" in str(call) for call in mock_logger.warning.call_args_list)

    async def test_spam_missing_required_fields(self):
        """测试 SPAM 条目缺少必要字段"""
        from handlers.utils.llm import check_spams_with_llm

        members = [MagicMock()]
        members[0].user = MagicMock(id=1000, username="user", first_name="Test", last_name="User")

        llm_response = orjson.dumps({
            "spams": [
                {"reason": "No id field"},
                {"id": 1000},  # 没有 reason
                {"id": "not an int", "reason": "Invalid id type"},
            ]
        }).decode("utf-8")

        with patch("handlers.utils.llm.chat_completions", AsyncMock(return_value=llm_response)):
            result = await check_spams_with_llm(members)

        # 只有第一个有 id 和 reason，但 id 是字符串应该被过滤
        # 第二个有 id 但没有 reason，应该被过滤
        assert len(result) == 0

    async def test_llm_exception_handling(self):
        """测试 LLM 调用异常处理"""
        from handlers.utils.llm import check_spams_with_llm

        members = [MagicMock()]
        members[0].user = MagicMock(id=1000, username="user", first_name="Test", last_name="User")

        with patch("handlers.utils.llm.chat_completions", AsyncMock(side_effect=Exception("LLM error"))):
            with patch("handlers.utils.llm.logger") as mock_logger:
                result = await check_spams_with_llm(members)

        assert result == []
        mock_logger.exception.assert_called()

    async def test_multiple_models_fallback(self):
        """测试多模型备援逻辑"""
        from handlers.utils.llm import check_spams_with_llm, SPAM_MODELS

        members = [MagicMock()]
        members[0].user = MagicMock(id=1000, username="user", first_name="Test", last_name="User")

        # 前两个模型失败，第三个成功
        call_count = [0]

        async def mock_chat_completion(messages, model_name, **kwargs):
            call_count[0] += 1
            if model_name in SPAM_MODELS[:2]:
                raise ValueError("Model error")
            return orjson.dumps({"spams": [{"id": 1000, "reason": "Spam detected"}]}).decode("utf-8")

        with patch("handlers.utils.llm.chat_completions", side_effect=mock_chat_completion):
            with patch("handlers.utils.llm.asyncio.wait_for", AsyncMock(side_effect=lambda coro, timeout: coro)):
                result = await check_spams_with_llm(members)

        assert len(result) == 1
        assert call_count[0] == 3  # 应该尝试了 3 个模型

    async def test_llm_timeout(self):
        """测试 LLM 超时"""
        from handlers.utils.llm import check_spams_with_llm

        members = [MagicMock()]
        members[0].user = MagicMock(id=1000, username="user", first_name="Test", last_name="User")

        async def timeout_coro(*args, **kwargs):
            raise TimeoutError("Timeout")

        with patch("handlers.utils.llm.chat_completions", side_effect=timeout_coro):
            result = await check_spams_with_llm(members)

        assert result == []

    async def test_member_with_bio_in_session(self):
        """测试成员有 bio 信息的场景"""
        from handlers.utils.llm import check_spams_with_llm

        member = MagicMock()
        user = MagicMock(id=1000, username="testuser", first_name="Test", last_name="User")
        member.user = user

        session = MagicMock()
        session.member_bio = "Check out my product!"
        members = [member]

        llm_response = orjson.dumps({
            "spams": [{"id": 1000, "reason": "Bio contains promotional content"}]
        }).decode("utf-8")

        with patch("handlers.utils.llm.chat_completions", AsyncMock(return_value=llm_response)):
            result = await check_spams_with_llm(members, session=session)

        assert len(result) == 1
        assert result[0] == (1000, "Bio contains promotional content")

    async def test_additional_strings_parameter(self):
        """测试附加信息参数"""
        from handlers.utils.llm import check_spams_with_llm

        member = MagicMock()
        user = MagicMock(id=1000, username="testuser", first_name="Test", last_name="User")
        member.user = user

        llm_response = orjson.dumps({
            "spams": [{"id": 1000, "reason": "Spam based on additional info"}]
        }).decode("utf-8")

        with patch("handlers.utils.llm.chat_completions", AsyncMock(return_value=llm_response)) as mock_request:
            result = await check_spams_with_llm(
                [member],
                additional_strings=["Extra info 1", "Extra info 2"]
            )

        assert len(result) == 1
        # 验证附加信息被传递到聊天请求中
        call_messages = mock_request.call_args[1]["messages"]
        system_message = call_messages[0]["content"]
        assert "附加信息" in system_message

    async def test_response_cleaning(self):
        """测试响应清理（Markdown code block 标记）"""
        from handlers.utils.llm import check_spams_with_llm

        member = MagicMock()
        member.user = MagicMock(id=1000, username="user", first_name="Test", last_name="User")

        # 模拟带有 markdown code block 的响应
        llm_response = "```json\n{\"spams\": [{\"id\": 1000, \"reason\": \"Spam\"}]}\n```"

        with patch("handlers.utils.llm.chat_completions", AsyncMock(return_value=llm_response)):
            result = await check_spams_with_llm(member)

        assert len(result) == 1
        assert result[0] == (1000, "Spam")

    async def test_all_spam_models_tried(self):
        """测试所有备援模型都被尝试"""
        from handlers.utils.llm import check_spams_with_llm, SPAM_MODELS

        members = [MagicMock()]
        members[0].user = MagicMock(id=1000)

        model_attempts = []

        async def track_model_attempts(messages, model_name, **kwargs):
            model_attempts.append(model_name)
            if model_name == SPAM_MODELS[0]:
                raise ValueError("First model fails")
            elif model_name == SPAM_MODELS[1]:
                raise ValueError("Second model fails")
            else:
                return orjson.dumps({"spams": []}).decode("utf-8")

        with patch("handlers.utils.llm.chat_completions", side_effect=track_model_attempts):
            result = await check_spams_with_llm(members)

        assert model_attempts == SPAM_MODELS[:3]  # 至少尝试前三个
