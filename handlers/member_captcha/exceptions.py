"""
成员验证模块异常定义
Member captcha module exceptions
"""

from typing import Optional
from aiogram import types


class MemberVerificationError(Exception):
    """成员验证相关错误基类"""
    
    def __init__(self, message: str, chat_id: Optional[int] = None, 
                 member_id: Optional[int] = None):
        super().__init__(message)
        self.chat_id = chat_id
        self.member_id = member_id


class ValidationError(MemberVerificationError):
    """验证失败错误"""
    pass


class PermissionError(MemberVerificationError):
    """权限不足错误"""
    pass


class SecurityCheckError(MemberVerificationError):
    """安全检查错误"""
    pass


class LogContext:
    """日志上下文管理器"""
    
    def __init__(self, chat: types.Chat, member_id: int, 
                 member_name: Optional[str] = None, 
                 member_fullname: Optional[str] = None, 
                 prefix: str = "[验证]"):
        self.chat = chat
        self.member_id = member_id
        self.member_name = member_name
        self.member_fullname = member_fullname
        self.prefix = prefix
        self._log_prefix = None
    
    @property
    def log_prefix(self) -> str:
        """获取格式化的日志前缀"""
        if self._log_prefix is None:
            self._log_prefix = f"{self.prefix} 群组:{self.chat.id}({self.chat.title}) 成员:{self.member_id}"
            if self.member_name:
                self._log_prefix += f"(@{self.member_name})"
            if self.member_fullname:
                self._log_prefix += f" 名称:{self.member_fullname}"
        return self._log_prefix
    
    def update_prefix(self, new_prefix: str) -> None:
        """更新前缀并重置缓存"""
        self.prefix = new_prefix
        self._log_prefix = None
