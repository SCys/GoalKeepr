"""
成员验证模块
Member captcha module

这个模块提供了完整的Telegram群组新成员验证功能，包括：
- 新成员加入验证
- 验证码生成和验证
- 安全检查（LLM和广告检测）
- 管理员操作支持
- 多种验证模式（静默、验证码等）
"""

from .member_captcha import member_captcha, new_member_callback

# 导出主要功能
__all__ = [
    'member_captcha',
    'new_member_callback',
]
