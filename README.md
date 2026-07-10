# GoalKeepr

Telegram 群组管理机器人，基于 [Telethon](https://docs.telethon.dev/)。

仓库：<https://github.com/SCys/GoalKeepr>

翻译感谢 77 老师。

---

## 功能概览

将机器人加入群组并设为管理员（需具备删除消息、限制成员及移除成员等权限）后，可使用入群验证及以下命令。

### 入群验证

- 仅处理普通群组和超级群组中的链接加入或被添加事件；超过 60 秒的事件会跳过。
- 默认的「认证剔除」模式会先限制新成员发言，再发送随机图标验证码。
- 验证、按钮回调、入群频率控制和 `/group_setting` 依赖 Redis；部署验证码功能时必须配置 `[redis] dsn`。
- 支持按群设置新成员处理方式：认证剔除、手动解封、无作为、静默 1/2 周或自定义静默。
- 对昵称和可获取的个人简介执行 LLM 垃圾信息及广告关键词检查；命中结果会标记本轮验证码会话。
- 24 小时内第 30 次及之后的重复入群会被临时移出 60 秒；同一条入群事件在 10 秒内只处理一次。

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
| `/chat`          | 基础 AI 会话（30 分钟 TTL 上下文）。`/chat <问题>` 或回复消息后加 `/chat` 继续；`/chat reset` 重置会话。需配置 `[ai]` + Redis（默认已启用）。 |
| `/group_setting` | 群组设置：新成员入群处理方式等（需配置 Redis）。                 |

部分命令（如 `/image`、`/shorturl` 等）在 `handlers/commands/__init__.py` 中默认未导入，需取消注释后重启方可使用。`/chat` 为简化后的基础会话功能，已默认启用。

---

## 入群验证流程

### 前置条件

- 将机器人加入目标群组并授予删除消息、限制成员和移除成员的管理员权限。
- 在 `main.ini` 配置可用的 `[redis] dsn`。Redis 保存验证码答案、短回调映射、会话标记、频率计数和群组设置；未配置或不可用时，按钮验证码无法正常完成。
- 若启用 LLM 检测，还需配置 `[ai] proxy_host`、`proxy_token` 和 `spam_models`；LLM 请求超时或失败时会跳过该项检测，继续检查广告关键词。

### 事件处理

```
新成员通过链接加入或被添加
          │
          ▼
删除入群服务消息，检查群类型、用户和事件时效（60 秒）
          │
          ▼
Redis 去重（同一事件 10 秒内只处理一次）和 24 小时入群次数统计
          │
          ├── 同一事件重复：不再处理
          ├── 第 30 次及之后入群：临时移出 60 秒后解除
          ▼
读取群组的新成员处理方式
          │
          ├── 无作为：不限制成员
          ├── 手动解封：永久限制发言，并通知管理员
          ├── 静默 1/2 周或自定义静默：限制发言至指定期限
          ▼
认证剔除（默认）：限制发言 → 等待 3 秒 → 安全检查 → 发送验证码
```

静默 1 周、2 周或自定义静默（1-365 天）由 `/group_setting` 中的群管理员设置。限时静默无法成功执行时，机器人会降级为默认的验证码流程；未知配置也会按验证码流程处理。

### 验证码与风控

- 验证消息包含 5 个随机图标选项，以及仅管理员可用的 `✔` 通过和 `❌` 拒绝按钮；回调数据会以短哈希形式保存到 Redis。
- 新成员点击正确图标后，未被标记的成员恢复发言权限并收到欢迎消息。管理员点击 `✔` 会直接恢复成员权限，跳过验证码及会话标记结果。
- 点击错误图标会生成新题目，并从该次刷新重新开始 30 秒倒计时；累计第 3 次错误后，成员会被临时移出 60 秒。
- 30 秒内未完成验证时，成员会被临时移出，并在 60 秒后解除以便重新加入。限制权限与发送验证码之间还会设置 180 秒兜底检查，防止异常中断后成员长期受限。
- 管理员点击 `❌` 会将成员封禁 30 天。
- 安全检查依次检测 LLM 垃圾信息和广告关键词，检查内容为昵称及可获取的个人简介。命中仅标记当前会话：成员自行答对验证码时，广告标记会封禁 30 天，LLM 标记会临时移出 60 秒；管理员直接通过不执行这些标记的处置。

### 群组处理方式

| 设置值 | `/group_setting` 名称 | 行为 |
| ------ | --------------------- | ---- |
| `ban` | 认证剔除（默认） | 限制发言并要求完成图标验证码。 |
| `silence` | 手动解封 | 永久限制发言，由管理员手动解除。 |
| `none` | 无作为 | 不限制、不验证。 |
| `sleep_1week` | 静默 1 周 | 限制发言 7 天。 |
| `sleep_2weeks` | 静默 2 周 | 限制发言 14 天。 |
| `sleep_custom:N` | 自定义静默 | 限制发言 `N` 天，设置界面允许 1-365 天。 |

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

[redis]
dsn = redis://localhost:6379/0
```

从 [my.telegram.org](https://my.telegram.org) 可获取 `api_id` 与 `api_hash`。

### 可选

```ini
[telegram]
admin = <管理员 TG 用户 ID，用于限制部分管理能力>

[web]
enabled = true
host = 127.0.0.1
port = 8080
cookie_secure = false
session_ttl = 86400
```

网站后台使用 Telegram Login 登录，不需要 Telegram webhook。后端会先校验 Telegram Login 签名，再将登录用户的 Telegram numeric user ID 与 `[telegram] admin` 比对；不匹配、未配置或配置为空时都会拒绝进入后台。

首次部署网站后台前，需要在 BotFather 对机器人执行 `/setdomain`，把网站域名绑定到该 bot。若通过 HTTPS 对外提供后台，将 `[web] cookie_secure` 设为 `true`。

Redis 是入群验证码、按钮回调、会话状态、频率控制和群组设置的必需依赖；同时也用于延迟删消息等任务。内置 SQLite 仅为部分延迟任务提供回退，不能替代 Redis 完成验证码流程。

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
# administrator / manage_group 为旧版 /chat 高级权限管理遗留（基础版 /chat 已不再使用）
chat_model = deepseek-r1
spam_models = openai/gpt-oss-120b;gemini-3.1-flash-lite-preview;openai/gpt-oss-20b;gemma-4-31b-it
image_optimize_models = deepseek-r1;gemini-flash
# chat_model 用于 /chat 基础会话（30min 上下文）。可使用任意后端支持的模型名；
# SUPPORTED_MODELS 中的 key 会获得精确的上下文长度和友好显示名，否则使用 128k 默认长度 + 原始模型名作为 "Powered by"。
# spam_models 用于新成员入群的 LLM 垃圾检测（handlers/member_captcha/security.py + utils/llm.py），支持多模型 ; 分隔 fallback
# image_optimize_models 用于 /image 命令的提示词 LLM 自动优化
```

所有 LLM 相关功能（`/chat`、入群 captcha 的 LLM spam 检查、` /image` 提示词优化）共享 `[ai]` 下的 proxy_host/proxy_token 配置，仅模型不同。模型名均可在 main.ini 中配置（不配置则使用代码内置默认值）。chat_model 不再强制要求必须是 SUPPORTED_MODELS 的 key。

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
