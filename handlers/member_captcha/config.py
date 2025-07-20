"""
成员验证模块配置和常量
Member captcha module configuration and constants
"""

import re
from typing import List

# 支持的群组类型
SUPPORT_GROUP_TYPES: List[str] = ["supergroup", "group"]

# 时间配置 (秒)
DELETED_AFTER = 30  # 消息自动删除时间
MEMBER_CHECK_WAIT_TIME = 3  # 等待其他机器人检查的时间
LLM_CHECK_TIMEOUT = 20  # LLM检查超时时间
EVENT_EXPIRY_SECONDS = 60  # 事件过期时间

# 封禁配置
DEFAULT_BAN_DAYS = 30  # 默认封禁天数

# 正则表达式
RE_TG_NAME = re.compile(r"^@[a-zA-Z0-9_]{5,32}$")

# 验证模式
class VerificationMode:
    """验证模式常量"""
    NONE = "none"  # 无操作
    SILENCE = "silence"  # 手动解封
    SLEEP_1WEEK = "sleep_1week"  # 静默1周
    SLEEP_2WEEKS = "sleep_2weeks"  # 静默2周
    BAN = "ban"  # 验证码验证（默认）

# 回调操作类型
class CallbackOperation:
    """回调操作类型常量"""
    ACCEPT = "O"  # 管理员接受
    REJECT = "X"  # 管理员拒绝
    SUCCESS = "!"  # 验证成功
    RETRY = "?"  # 验证失败，重试
