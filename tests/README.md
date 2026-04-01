# Tests
# 测试套件文档

## 安装依赖

```bash
uv sync --dev
```

## 运行测试

```bash
# 运行所有测试
uv run pytest

# 运行特定测试文件
uv run pytest tests/test_member_captcha.py

# 运行特定测试类
uv run pytest tests/test_member_captcha.py::TestGetChatType

# 运行特定测试方法
uv run pytest tests/test_member_captcha.py::TestGetChatType::test_private_chat

# 运行测试并显示详细输出
uv run pytest -v

# 运行测试并显示额外日志
uv run pytest -s

# 运行测试并统计覆盖率
uv run pytest --cov=handlers/member_captcha --cov-report=html
```

## 测试覆盖范围

### 已实现的测试

- **test_member_captcha.py**: 入群验证主模块测试
  - `TestGetChatType`: 群组类型检测
  - `TestFullName`: 用户名称解析
  - `TestMemberCaptcha`: 主入口函数场景测试

- **test_security_mode.py**: 安全模式测试
  - 安全模式启用/禁用
  - 入群计数
  - 成员审核列表
  - 自动退出时间

- **test_join_queue.py**: 入群队列处理测试
  - 入群事件发布
  - 重复加入检测
  - 批量处理

### 待实现的测试

- `test_events.py`: 延迟事件处理测试
- `test_helpers.py`: 辅助函数测试
- `test_validators.py`: 验证器测试
- `test_callbacks.py`: 回调处理测试
- `test_security.py`: 安全检查测试

## 测试配置

测试使用 `pytest` 和 `pytest-asyncio` 框架，配置在 `pytest.ini` 中。

### 夹具 (Fixtures)

- `mock_config`: 模拟配置文件
- `mock_chat`: 模拟群组对象
- `mock_user`: 模拟用户对象
- `mock_permissions`: 模拟权限对象
- `mock_redis`: 模拟 Redis 连接
- `mock_manager`: 模拟 manager 对象
- `mock_database`: 模拟数据库操作

## 编写新测试

1. 创建一个测试文件 `test_<module>.py`
2. 导入需要的夹具和模块
3. 使用 `@pytest.mark.asyncio` 标记异步测试
4. 使用 `@patch` 装饰器模拟外部依赖

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_example(mock_redis, mock_manager):
    # Test logic here
    assert True
```
