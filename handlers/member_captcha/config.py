"""
成员验证模块配置和常量
Member captcha module configuration and constants
"""

import re
from typing import List, Any

# 支持的群组类型
SUPPORT_GROUP_TYPES: List[str] = ["supergroup", "group"]


def get_chat_type(chat: Any) -> str:
    """从 Telethon 实体得到聊天类型：private / group / supergroup / channel。"""
    if getattr(chat, "broadcast", False):
        return "channel"
    if getattr(chat, "megagroup", False):
        return "supergroup"
    if getattr(chat, "title", None) is not None:
        return "group"
    return "private"

# 时间配置 (秒)
DELETED_AFTER = 30  # 消息自动删除时间
MEMBER_CHECK_WAIT_TIME = 3  # 等待其他机器人检查的时间
LLM_CHECK_TIMEOUT = 20  # LLM检查超时时间
EVENT_EXPIRY_SECONDS = 60  # 事件过期时间

# 封禁配置
DEFAULT_BAN_DAYS = 30  # 默认封禁天数

# 频率控制配置
CAPTCHA_REDIS_KEY_PREFIX = "chat_captcha"          # Redis Key 前缀
CAPTCHA_TTL_DEFAULT = 60 * 60 * 24                  # 默认 TTL: 24小时
CAPTCHA_TTL_EXTENDED = 60 * 60 * 24 * 7             # 提升 TTL: 7天
CAPTCHA_JOIN_THRESHOLD_KICK = 3                     # 24h 内超过此次数就 Kick
CAPTCHA_JOIN_THRESHOLD_RESET = 1                    # 降到此次数恢复默认 TTL
CAPTCHA_DEDUP_TTL = 10                              # 去重锁 TTL: 10秒（防止同事件重复处理）

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
