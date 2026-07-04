# 审查发现的问题

## P1 严重问题

### 1. `restrict_member_permissions` 抛出的 PermissionError 未处理，会拖垮 `chat_member` 处理器 ✅ 已修复
- **位置**：`handlers/member_captcha/security.py:39-41`、`handlers/member_captcha/member_captcha.py:112`、`handlers/member_captcha/member_captcha.py:131`
- **说明**：`security.py:41` 在 `edit_permissions` 失败时改为抛出 `PermissionError` 而不是返回 `False`。但 `member_captcha.py:112` 和 `:131` 仍然用 `if not await ...` 调用，没有任何 `try/except`。线上一旦权限被拒绝，整个 `chat_member` 处理器会中断，新成员既不会被禁言，也不会收到验证码。
- **修复**：`member_captcha.py` 两处调用改为 try/except `PermissionError`，并导入 `PermissionError`。`validators.py` 内的调用无需改动，已有外层 `except Exception` 保护。

### 2. `event.delete()` 未加保护，可能导致成员验证码处理器崩溃 ✅ 已修复
- **位置**：`handlers/member_captcha/member_captcha.py:38`
- **说明**：该文件直接调用 `await event.delete()`。基础分支里这段调用有 `try/except` 包裹，删除权限不足或服务消息已被删除时仅记录日志并忽略。移除保护后，任何删除失败都会在验证逻辑执行前直接杀死处理器。
- **修复**：恢复 try/except 包裹，与 master 的 commit `1356cc2` 一致。

### 3. `admin:stats_user` 读取了错误用户的聊天记录 TTL ✅ 已修复
- **位置**：`handlers/commands/chat/func_adv.py:319`
- **说明**：计算历史记录过期时间时使用了 `user.id`（发出命令的管理员），而不是 `target_user_id`。因此 `/chat admin:stats_user` 显示的过期时间属于操作者本人，而不是被查询的用户。
- **修复**：`user.id` 改为 `target_user_id`。

### 4. 部署工作流回退到了旧的纯 docker 重启脚本
- **位置**：`.github/workflows/deploy.yml:13-26`
- **说明**：该文件把 `actions/checkout@v4` 降回 `@v2`，并把完整部署脚本（拉取源码、用 `uv sync` 同步依赖、重载并重启 systemd 用户服务）替换成了 `git pull` + `docker compose build/up`。如果生产环境使用基础分支的 systemd 布局，这会静默破坏持续部署、跳过依赖更新，并可能启动错误的服务。

## P2 中等问题

### 5. `/chat` 命令拆分破坏了多参数管理子命令
- **位置**：`handlers/commands/chat/func_chat.py:70-73`
- **说明**：当前用 `text.split(' ', 1)` 拆分消息文本，因此 `arguments` 最多只有两项，第一个空格后的内容被当作单个 token。文档说明需要两个独立参数的子命令（例如 `/chat admin:quota <uid> <quota>`）无法解析 uid，除非管理员回复目标用户的消息。

### 6. `_method_display` 假定 `sleep_custom` 值格式良好
- **位置**：`handlers/commands/group_setting.py:15-19`
- **说明**：代码直接执行 `method.split(':')[1]`，没有检查值是否真的包含第二部分。类似 `'sleep_custom:'` 这样的畸形存储值会引发 `IndexError`，导致 `/group_setting` 面板崩溃，而不是回退到 "未知" 标签。
