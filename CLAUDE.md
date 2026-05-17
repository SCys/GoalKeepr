# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (requires uv)
uv sync

# Install dev dependencies (pytest)
uv sync --group dev

# Run the bot (foreground)
uv run python main.py

# Run tests
uv run pytest

# Run a single test
uv run pytest handlers/commands/shorturl_test.py

# Run with debug logging (set debug = true in main.ini [default] section)

# Docker
docker compose build gk
docker compose up -d gk
```

## Project Overview

GoalKeepr is a Telegram group management bot built on [Telethon](https://docs.telethon.dev/). Its primary feature is member verification captcha for new group members. It also provides admin utilities (kick, ban, ID lookup) and optional features (image generation, TTS, ASR, translation, AI chat).

## Architecture

### Entry Point (`main.py`)
- Initializes SQLite tables for lazy message deletion and captcha sessions
- Starts a background worker loop (`worker_loop`) that polls for timed-out messages and captcha sessions
- Starts `txt2img_worker` (ComfyUI-based image generation worker)
- Calls `manager.start()` to connect Telethon client and apply registered handlers

### Manager (`manager/manager.py`)
Singleton `Manager` class that:
- Loads config from `main.ini` (ConfigParser)
- Sets up Telethon `TelegramClient` with optional SOCKS5 proxy
- Provides decorator-based handler registration (`@manager.register(type_name, ...)`)
  - Types: `"message"`, `"callback_query"`, `"chat_member"`, `"raw"`
- Provides internal event registration (`@manager.register_event(name)`) for delayed/lazy session callbacks
- Manages Redis connection (optional, used for captcha sessions and group settings)
- Wraps common Telethon operations: `send`, `reply`, `edit_text`, `delete_message`
- Lazy message/session scheduling: `delete_message` with `deleted_at` or `lazy_session` with a timeout schedules deferred processing via the worker loop

### Database (`database.py`)
Thin async SQLite wrapper using `aiosqlite`. Single connection with a lock. Stores lazy delete messages and captcha sessions. If Redis is configured, Redis takes precedence for session handling.

### Handler Registration Pattern

```python
from manager import manager

@manager.register("message", pattern=r"(?i)^/command$")
async def my_handler(event):
    # event is telethon.events.NewMessage.Event
    pass
```

Handlers are imported in `handlers/__init__.py`, which is wildcard-imported by `main.py`. The `Manager._apply_handlers()` method binds all registered handlers to the Telethon client at startup.

### Directory Structure

```
handlers/
  __init__.py           # Imports all handler modules
  default.py            # Default message handler (logging)
  error.py              # Error handler (placeholder)
  commands/
    __init__.py         # Command imports; many commands are commented out by default
    k.py                # /k - Kick command
    sb.py               # /sb - Ban command
    whoami.py           # /id - User info command
    image.py            # /image - Text-to-image (ComfyUI) + background worker
    sdxl.py             # /sdxl - SDXL image generation
    shorturl.py         # /shorturl - URL shortening
    translate.py        # /tr - Translation
    tts.py              # /tts - Text-to-speech
    asr.py              # /asr - Speech-to-text
    chat.py             # /chat - AI chat with context
    group_setting.py    # /group_setting - Group config (Redis required)
  member_captcha/       # Core captcha verification module (see below)
  utils/
    base.py             # Token counting, Chinese detection, text stripping
    llm.py              # LLM interaction for spam detection
    txt.py              # Text processing utilities
manager/
  manager.py            # Core Manager class
  settings.py           # INI config template
  group.py              # Redis-based per-group settings (/group_setting)
```

### Member Captcha Flow (`handlers/member_captcha/`)

The main feature. When a new member joins a supergroup/group:

1. **`member_captcha.py`** — `@manager.register("chat_member")` catches `ChatAction` events for new members
2. **`session.py`** — `CaptchaSession` manages join frequency control via Redis; throttles users who rejoin too often (threshold: 30 joins/24h)
3. **`validators.py`** — Checks group type, bot permissions, admin status; determines verification method (ban/silence/none)
4. **`security.py`** — LLM-based spam detection on user profile (name, bio, photo)
5. **`helpers.py`** — Builds captcha message with random emoji icon buttons, stores callback data (MD5-hashed)
6. **`callbacks.py`** — Processes button clicks (correct/wrong answer, admin accept/reject)
7. **`events.py`** — Lazy event handlers for timeout kick (`new_member_check`) and unban (`unban_member`)
8. **`config.py`** — Constants: timeouts, thresholds, verification modes

Captcha flow: Restrict user → send message with 5 emoji buttons (one correct) → correct = unrestrict, wrong = regenerate, timeout (30s) = kick + 60s unban.

### Worker Loop (`main.py:worker_loop`)
Runs continuously while the bot is connected. Polls every 250ms (if tasks processed) or 1s (if idle) for:
- `lazy_delete_messages` — Messages scheduled for future deletion
- `lazy_sessions` — Captcha timeouts and unban operations

Both Redis and SQLite backends are polled (Redis first, SQLite as fallback).

### Config (`main.ini`)
Located in project root. Required sections: `[default]`, `[telegram]` (token, api_id, api_hash, optional proxy). Optional sections for Redis, ASR, SD API, image generation, imgproxy, AI, and advertising detection. See README or `main.ini` example for full details.

### Styling
- Log messages use English for technical operations, Chinese for user-facing context
- Code comments and variable names are a mix of English and Chinese
- Python 3.14+, async/await throughout
