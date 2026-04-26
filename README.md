# GoalKeepr

Telegram 群组管理机器人，基于 [Telethon](https://docs.telethon.dev/)。

仓库：<https://github.com/SCys/GoalKeepr>

翻译感谢 77 老师。

---

## 功能概览

将机器人加入群组并设为管理员（授予相应权限）后，可使用入群验证及以下命令。

### 入群验证

- 新成员入群后，机器人会限制其权限并发送验证消息。
- 验证消息包含：欢迎文案、验证按钮、管理员操作按钮：
  - ✔️ 直接通过（跳过验证）
  - ❌ 踢出并加入黑名单（默认 30 天）
- 群组处理方式可在群内通过 `/group_setting` 配置（需在代码中启用并配置 Redis）：认证剔除、手动解封、无作为、静默 1/2 周等。

### 命令列表

| 命令             | 说明                                                                                      |
| ---------------- | ----------------------------------------------------------------------------------------- |
| `/k`             | 踢掉发消息的人。                                                                          |
| `/sb`            | 将发消息的人加入黑名单。                                                       |
| `/id`            | 获取用户信息（回复某人或自己），返回 ID、昵称、分享链接等。                               |
| `/image`         | 根据文本生成图片。支持英文；中文会先翻译为英文。可配置允许的用户/群组及图床（imgproxy）。 |
| `/shorturl`      | 将消息中的 URL 转为短链接（需在代码中启用）。                                             |
| `/tr`            | 将输入文本翻译为中文（需在代码中启用）。                                                  |
| `/tts`           | 文本转语音（需在代码中启用）。                                                            |
| `/asr`           | 识别语音消息中的文本，依赖配置的 ASR 服务端点（需在代码中启用）。                         |
| `/sdxl`          | 使用 SDXL 接口根据文本生成图片（需在代码中启用）。                                        |
| `/chat`          | 支持上下文的聊天，可配置参数，详情见命令说明（需在代码中启用）。                          |
| `/group_setting` | 群组设置：新成员入群处理方式等（需在代码中启用并配置 Redis）。                 |

部分命令在 `handlers/commands/__init__.py` 中默认未导入，需取消注释后重新运行方可使用。

---

## 运行要求

- Python 3.10+
- 依赖由 [uv](https://docs.astral.sh/uv/) 管理（见 `pyproject.toml`）

---

## 配置

在项目根目录放置 `main.ini`，按需填写以下节。

### 必选

```ini
[default]
debug = false

[telegram]
token = <你的 BOT TOKEN>
api_id = <Telegram API ID>
api_hash = <Telegram API Hash>
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
uv sync

# 前台运行
uv run python main.py
```

或直接：

```bash
python main.py
```

---

## Docker 运行

镜像使用项目内 `docker/Dockerfile` 构建，入口为 `startup.sh`（会创建 `log` 目录并执行 `python main.py`）。

```bash
# 在包含 docker-compose 的目录中
docker compose build gk
docker compose up -d gk
```

构建使用 Python 3.14 Alpine，已包含 ffmpeg、nodejs 等运行时依赖。

---

## 部署

仓库内提供 GitHub Actions 示例：`.github/workflows/deploy.yml`。通过 rsync 将代码同步到服务器，再通过 SSH 执行 `docker compose build gk && docker compose up -d gk` 完成部署与重启。需在仓库中配置 `DEPLOY_PATH`、`DEPLOY_HOST`、`DEPLOY_USER`、`DEPLOY_KEY` 等 Secrets。
