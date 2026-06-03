# GoalKeepr

Telegram 群组管理机器人，基于 [Telethon](https://docs.telethon.dev/)。

仓库：<https://github.com/SCys/GoalKeepr>

翻译感谢 77 老师。

---

## 功能概览

将机器人加入群组并设为管理员（授予相应权限）后，可使用入群验证及以下命令。

### 入群验证

- 新成员入群后，机器人会限制其发言权限并发送验证消息（含随机图标验证码）。
- 验证消息包含欢迎文案、5 个验证按钮、管理员操作按钮：
  - 点击正确图标 → 通过验证，恢复发言权限
  - 点击错误图标 → 刷新验证码重试
  - 30 秒内未操作 → 踢出群组，60 秒后解封允许重新加入
  - ✔️ 管理员直接通过（跳过验证）
  - ❌ 管理员踢出并加入黑名单（默认 30 天）
- 群组处理方式可在群内通过 `/group_setting` 配置（需配置 Redis）：认证剔除（默认）、手动解封、无作为、静默 1/2 周等。
- 验证过程中会通过 LLM 对用户资料进行垃圾广告检测，命中则自动踢出。
- 支持频率控制：24 小时内反复进出超过阈值将自动踢出。

### 命令列表

| 命令             | 说明                                                                                      |
| ---------------- | ----------------------------------------------------------------------------------------- |
| `/k`             | 踢掉发消息的人。                                                                          |
| `/sb`            | 将发消息的人加入黑名单。                                                       |
| `/id`            | 获取用户信息（回复某人或自己），返回 ID、昵称、分享链接等。                               |
| `/image`         | 根据文本生成图片。支持英文；中文会先翻译为英文。可配置允许的用户/群组及图床（imgproxy）（需在代码中启用）。 |
| `/shorturl`      | 将消息中的 URL 转为短链接（需在代码中启用）。                                             |
| `/tr`            | 将输入文本翻译为中文（需在代码中启用）。                                                  |
| `/tts`           | 文本转语音（需在代码中启用）。                                                            |
| `/asr`           | 识别语音消息中的文本，依赖配置的 ASR 服务端点（需在代码中启用）。                         |
| `/sdxl`          | 使用 SDXL 接口根据文本生成图片（需在代码中启用）。                                        |
| `/chat`          | 支持上下文的聊天，可配置参数，详情见命令说明（需在代码中启用）。                          |
| `/group_setting` | 群组设置：新成员入群处理方式等（需配置 Redis）。                 |

部分命令在 `handlers/commands/__init__.py` 中默认未导入，需取消注释后重启方可使用。

---

## 入群验证流程

```
┌─────────────────────────────────────┐
│        Telegram ChatAction         │
│    (user_joined / user_added)       │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  member_captcha() [ChatMember事件]  │
│  1. 获取 chat, user                 │
│  2. 删除入群消息                    │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│     validate_basic_conditions()     │
│  • 群组类型检查 (supergroup/group)   │
│  • 用户存在检查                      │
│  • 事件过期检查 (60s)                │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│    CaptchaSession.check_and_record() │
│    ★ 频率控制 + 去重检查            │
│    • SETNX 原子锁防重复             │
│    • 24h内入群次数统计               │
└─────────────────┬───────────────────┘
                  │
          ┌───────┴───────┐
          ▼               ▼
   state=throttled   state=duplicate     正常通过
   (入群≥30次)       (事件重复)
          │               │
          ▼               ▼
    Kick 60s +        静默跳过
    调度 unban
          │
          └───────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│      get_verification_method()       │
│    从 Redis 读取群组验证模式         │
└─────────────────┬───────────────────┘
                  │
    ┌─────────────┼─────────────┐
    ▼             ▼             ▼
  NONE         SILENCE         BAN
  (无作为)     (静默模式)     (验证码)
    │             │             │
    ▼             ▼             ▼
   放行      限制权限+      restrict_permissions()
            通知管理员      禁止发送消息
                │             │
                ▼             ▼
            handle_silence_mode()   ┌─────────┐
            • 通知管理员              │ 创建Session│
            • 限制1/2周自动解封       └────┬────┘
                │                         │
                │ (失败)                  ▼
                └──────────────────► sleep(3s)
                                        │
                                        ▼
                              ┌─────────────────┐
                              │ 安全检查(LLM+广告)│
                              │   返回原因标记    │
                              └────────┬─────────┘
                                      │
                                      ▼
                              ┌─────────────────┐
                              │ build_captcha_msg│
                              │ 随机图标验证码   │
                              │ MD5加密callback  │
                              └────────┬─────────┘
                                      │
                                      ▼
                              ┌─────────────────┐
                              │ send_message()   │
                              │ 发送验证消息     │
                              └────────┬─────────┘
                                      │
                                      ▼
                              ┌─────────────────┐
                              │ • 记录答案到Redis│
                              │ • 调度超时检查   │
                              │ • 30s后自动删除  │
                              └─────────────────┘
```

### 用户点击验证按钮流程

```
┌─────────────────────────────────────┐
│  用户点击按钮 (callback_query)       │
└─────────────────┬───────────────────┘
                  ▼
┌─────────────────────────────────────┐
│  validate_callback_conditions()      │
│  • 消息存在/群组类型/bot消息检查     │
│  • 按钮布局验证 (5+2)                │
└─────────────────┬───────────────────┘
                  ▼
┌─────────────────────────────────────┐
│  解码 callback_data (MD5→Redis)    │
└─────────────────┬───────────────────┘
                  ▼
┌─────────────────────────────────────┐
│  权限判断                            │
│  • is_admin → handle_admin_operation │
│  • is_self  → handle_self_verification│
└─────────────────┬───────────────────┘
                  │
      ┌───────────┴───────────┐
      ▼                       ▼
┌───────────────────┐ ┌─────────────────────────┐
│ handle_admin_op   │ │ handle_self_verification │
│                   │ │                         │
│ • O (Accept)      │ │ • 正确 → accepted_member │
│ • X (Reject)      │ │ • 错误 → 重试+1         │
└───────────────────┘ │ • 超过3次 → Kick 60s    │
      │               └─────────────────────────┘
      └───────────┬───────────┘
                  ▼
        ┌───────────────────┐
        │  accepted_member() │
        │ • 恢复用户权限     │
        │ • 发送欢迎消息     │
        │ • 清理 session     │
        └───────────────────┘
```

### 定时任务触发流程

```
┌─────────────────────────────────────────────────────────────┐
│                    Worker Loop (0.25s/1s)                     │
└─────────────────────────────┬───────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│new_member_check │ │  unban_member   │ │safety_timeout  │
│   (30s超时)     │ │   (60s解封)     │ │   (180s兜底)   │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  _kick_member() │ │ edit_permissions│ │   _kick_member() │
│  • 广告→30天封禁 │ │  恢复所有权限   │ │  同 new_member  │
│  • LLM/默认     │ │                │ │                 │
│    → 60s封禁    │ │                │ │                 │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

---

## 运行要求

- Python 3.10+（当前使用 3.14 开发）
- 依赖由 [uv](https://docs.astral.sh/uv/) 管理（见 `pyproject.toml`）

---

## 配置

参考 `example/main.ini`，在项目根目录创建 `main.ini`，按需填写以下节。

### 必选

```ini
[default]
debug = false

[telegram]
token = <你的 BOT TOKEN>
api_id = <Telegram API ID>
api_hash = <Telegram API Hash>
proxy = socks5://127.0.0.1:1080  ; 可选，连接代理（socks5/http）
```

从 [my.telegram.org](https://my.telegram.org) 可获取 `api_id` 与 `api_hash`。

### 可选

```ini
[telegram]
admin = <管理员 TG 用户 ID，用于限制部分管理能力>

[redis]
dsn = redis://localhost:6379/0
```

配置 Redis 后，会使用 Redis 处理延迟删消息、入群验证会话等；未配置则使用内置 SQLite。

```ini
[asr]
endpoint = <语音识别服务 URL，供 /asr 使用>
```

```ini
[sd_api]
endpoint = https://api.snowdusk.me
```

供 `/image`、`/sdxl` 等文生图使用。

```ini
[image]
users = 123,456
groups = -100xxx
```

允许使用图片生成命令的 TG 用户 ID 与群组 ID，逗号分隔；不填则按代码默认策略。

```ini
[imgproxy]
domain = https://img.example.com
imgproxy_key = <key>
imgproxy_salt = <salt>
imgproxy_source_url_encryption_key = <key>
```

图床代理，用于图片生成后的访问与裁剪（可选）。

```ini
[ai]
proxy_host = <AI 代理地址>
proxy_token = <代理 token>
administrator = <管理员用户 ID>
manage_group = <管理群 ID>
```

供 `/chat` 等 AI 相关功能使用。

```ini
[advertising]
enabled = false
words = 词1,词2
regex_patterns = 名称1:正则1;名称2:正则2
```

广告/关键词检测（可选）。

---

## 本地运行

```bash
# 安装依赖（需已安装 uv）
uv sync --group dev

# 前台运行
uv run python main.py
```

---

## Docker 运行

镜像使用项目内 `docker/Dockerfile` 构建，入口为 `startup.sh`（会创建 `log` 目录并执行 `python main.py`）。

```bash
# 在包含 docker-compose 的目录中
docker compose build gk
docker compose up -d gk
```

构建使用 Python 3.14 Alpine，已包含 ffmpeg 等运行时依赖。

---

## 使用 systemd 用户服务运行（推荐用于裸机/ VPS）

适合把源码和配置/数据分离的场景：

推荐目录结构：

```
/data/goalkeepr/
├── main.ini                 # 配置文件（含 token 等敏感信息）
├── src/                     # git 仓库克隆位置
│   ├── main.py
│   ├── pyproject.toml
│   ├── uv.lock
│   └── ...
├── data/                    # 运行时数据（main.db + bot.session），代码会自动创建
└── log/                     # 可选（非 systemd 方式时使用）
```

### 1. 代码修改支持（已完成）

- 支持环境变量 `GOALKEEPR_CONFIG` 和 `GOALKEEPR_DATA_DIR`
- 支持命令行参数 `--config` / `--data-dir`
- Telethon session 和 SQLite 数据库会放在 `GOALKEEPR_DATA_DIR` 下
- 向后兼容：不设环境变量时行为与原来完全一致（相对路径）

### 2. 安装 service

```bash
# 克隆代码到 src
mkdir -p /data/goalkeepr
cd /data/goalkeepr
git clone https://github.com/your/repo.git src

# 准备配置文件
cp src/example/main.ini main.ini
# 编辑 main.ini，填入真实 token 等

# 创建数据目录（权限给运行 bot 的用户）
mkdir -p /data/goalkeepr/data
chown -R $USER:$USER /data/goalkeepr

cd src
uv sync --frozen --no-dev

# 安装 systemd user service
mkdir -p ~/.config/systemd/user
cp systemd/goalkeepr.service ~/.config/systemd/user/goalkeepr.service
# 根据实际情况编辑 ~/.config/systemd/user/goalkeepr.service 中的路径和 uv 位置

systemctl --user daemon-reload
systemctl --user enable --now goalkeepr
```

查看日志：

```bash
journalctl --user -u goalkeepr -f
```

### 3. 更新部署

```bash
cd /data/goalkeepr/src
git pull
uv sync --frozen --no-dev
systemctl --user restart goalkeepr
```

---

## 部署（GitHub Actions）

仓库提供 `.github/workflows/deploy.yml` 示例。

默认使用 **src + uv + systemd user service** 流程（与上面目录结构匹配）：

- 触发：push 到 master
- 通过 SSH 在服务器执行 `cd /data/goalkeepr/src; git pull; uv sync --frozen --no-dev; systemctl --user restart goalkeepr`

配置 Secrets：
- `DEPLOY_HOST`
- `DEPLOY_USER`（必须是启用了 user service 的那个 Linux 用户）
- `DEPLOY_KEY`（SSH private key）

如果仍使用旧的 Docker + docker-compose 布局，可以在 workflow 里注释切换或维护两个 job。

详细的 service 文件模板见 `systemd/goalkeepr.service`（内有注释）。
