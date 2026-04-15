# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**GoalKeepr** is a Telegram group management bot built with [Telethon](https://docs.telethon.dev/). It provides member verification, moderation commands, AI-powered features, and media generation capabilities.

**Tech Stack**: Python 3.12+, Telethon, Redis (optional), SQLite (fallback), aiohttp, beautifulsoup4

## Common Development Commands

### Environment Setup

```bash
# Install dependencies using uv
uv sync

# Activate virtual environment
source .venv/bin/activate  # or just use `uv run` prefix
```

### Running the Bot

```bash
# Development (foreground)
uv run python main.py

# With debug logging
uv run python main.py  # ensure debug=true in main.ini
```

### Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov

# Run a specific test file
uv run pytest tests/test_manager_core.py

# Run a specific test function
uv run pytest tests/test_manager_core.py::test_delete_message_falls_back_to_sqlite_when_redis_schedule_fails

# Run tests matching a pattern
uv run pytest -k "test_lazy"

# Watch mode (if pytest-watch installed)
uv run pytest -w
```

### Linting & Formatting

The project uses Ruff (based on `.ruff_cache` directory). Check for linting configuration:

```bash
# If ruff is installed
uv run ruff check .

# Format code (if configured)
uv run ruff format .
```

### Redis Management

```bash
# Start Redis (local docker-compose)
make redis-up

# Stop Redis
make redis-down

# View Redis logs
make redis-logs

# Enter Redis shell
make redis-shell

# Check Redis status
make redis-status

# Backup/restore Redis data
make redis-backup
make redis-restore FILE=./backup/redis_YYYYMMDD.tar.gz

# Flush all data (dangerous)
make redis-flushall
```

### Docker

```bash
# Build the bot image
docker compose build gk

# Run the bot
docker compose up -d gk

# View logs
docker compose logs -f gk

# Stop the bot
docker compose down gk

# Rebuild and restart
docker compose up -d --build gk
```

## Architecture

### High-Level Structure

```
goal_keepr/
├── main.py              # App entry point, worker loops, initialization
├── database.py          # SQLite connection pool (aiosqlite)
├── manager/
│   ├── manager.py      # Core Manager class (singleton), handles config, client, Redis, HTTP
│   ├── group.py        # Group-related utilities
│   └── __init__.py     # Exports global `manager` instance
├── handlers/
│   ├── __init__.py     # Handler imports - controls which commands are active
│   ├── default.py      # Default message handler
│   ├── error.py        # Error handling
│   ├── commands/       # Command handlers (k, sb, image, chat, etc.)
│   ├── member_captcha/ # Member verification system
│   └── utils/          # Shared utilities (base handler, text processing, LLM)
├── utils/              # Standalone utilities (ASR, ComfyUI, advertising)
└── tests/              # Async tests with pytest-asyncio

Config: main.ini (settings), pyproject.toml (dependencies)
```

### Core Components

#### Manager (Singleton)

The `Manager` class (`manager/manager.py`) is the central orchestrator:

- **Config**: Loads from `main.ini` using ConfigParser, with defaults from `SETTINGS_TEMPLATE`
- **Telethon Client**: `TelegramClient` instance with optional proxy support
- **Redis Connection**: Optional `aioredis.Redis` instance; features gracefully degrade to SQLite when unavailable
- **HTTP Session**: Shared `aiohttp.ClientSession` for external API calls
- **Handler Registration**: `@manager.register(type_name, **filters)` decorator system
- **Event System**: `@manager.register_event(type_name)` for internal events (e.g., lazy sessions)

Key methods:
- `setup()`: Initializes config, logger, client, registers handlers
- `start()`: Connects to Telegram, registers event handlers, pings Redis if configured
- `stop()`: Clean shutdown
- `get_redis()`: Returns Redis or None (caller must handle fallback)
- `require_redis()`: Returns Redis or raises `RedisUnavailableError` (for Redis-dependent features)
- `delete_message()`: Supports lazy deletion via Redis sorted sets or SQLite
- `lazy_session()`: Schedules callbacks (e.g., captcha timeout) with Redis or SQLite

#### Handler System

Handlers are async functions decorated with `@manager.register()`:

```python
@manager.register("message", pattern=r"^/k")
async def k(event):
    # Kick user logic
    pass

@manager.register("callback_query")
async def button_callback(event):
    # Handle inline button clicks
    pass
```

Handler types:
- `"message"`: NewMessage events (uses `events.NewMessage`)
- `"callback_query"`: CallbackQuery events (button clicks)
- `"chat_member"`: ChatAction events (member joins/leaves; auto-filtered for user_joined/user_added)

All handlers in `handlers/commands/__init__.py` are imported to activate them. Commented-out imports disable commands.

#### Member Captcha System

Located in `handlers/member_captcha/`:

- `member_captcha.py`: Main captcha handler on new member join
- `events.py`: Event callbacks (new_member_check, unban_member) triggered via lazy sessions
- `session.py`: Captcha session management with SQLite/Redis
- `security.py`: Captcha answer validation (turnstile, reCAPTCHA integration)
- `security_mode.py`: Configurable security modes
- `validators.py`: Input validation
- `join_queue.py`: Queue-based processing to handle concurrent joins

Captcha flow:
1. New member joins → `member_captcha` handler triggers
2. Bot deletes join message, sends captcha challenge with buttons
3. Admin can "approve" (✔️) or "ban" (❌) via inline buttons
4. If user answers correctly within timeout → allow
5. Timeout triggers `new_member_check` lazy session to auto-ban
6. Configurable group settings via `/group_setting` (requires Redis)

#### Worker Loop

`main.py` runs two background workers after `manager.start()`:

1. **lazy_messages()**: Processes scheduled message deletions from Redis sorted set (`lazy_delete_messages`) and SQLite table
2. **lazy_sessions()**: Processes scheduled event callbacks from `lazy_sessions` (captcha timeouts, etc.)
3. **process_join_events()**: Processes member join queue (2s blocking pop)

Worker loop runs every 0.25s if work processed, else 1s.

#### Database Layer

`database.py` provides aiosqlite connection pooling:

- Global `_conn` with `_conn_lock` for single connection reuse
- `execute()`: Run write queries with commit
- `execute_fetch()`: Run read queries and return results
- Thread-safe with `_conn_use_lock` per-call to avoid reuse issues

All tables initialized in `main.py`: `lazy_delete_messages`, `lazy_sessions`, `captcha_answers`

#### Configuration (main.ini)

Structure from `manager/settings.py` (referenced as `SETTINGS_TEMPLATE`):

```ini
[default]
debug = false

[telegram]
token = <BOT_TOKEN>
api_id = <API_ID>
api_hash = <API_HASH>
admin = <ADMIN_USER_ID>  # optional
proxy = socks5://127.0.0.1:1080  # optional

[redis]
dsn = redis://localhost:6379/0  # optional, enables advanced features

[asr]
endpoint = <ASR_SERVICE_URL>

[sd_api]
endpoint = https://api.snowdusk.me

[image]
users = 123,456
groups = -100xxx

[imgproxy]
domain = https://img.example.com
imgproxy_key = <key>
imgproxy_salt = <salt>
imgproxy_source_url_encryption_key = <key>

[ai]
proxy_host = <AI_PROXY>
proxy_token = <AI_TOKEN>
administrator = <ADMIN_USER_ID>
manage_group = <MANAGE_GROUP_ID>

[captcha]
cloudflare_turnstile = false
cloudflare_turnstile_token =
google_recaptcha = false
google_recaptcha_token =

[advertising]
enabled = false
words = keyword1,keyword2
regex_patterns = name1:pattern1;name2:pattern2
```

## Testing Patterns

- Async tests with `@pytest.mark.asyncio`
- Fixtures in `tests/conftest.py`:
  - `mock_manager`: Pre-configured Manager mock with client, Redis disabled
  - `mock_redis`: Mocked Redis client with AsyncMock for all methods
  - `mock_config`: Sample config dict
  - `mock_chat`, `mock_user`, `mock_permissions`: Telegram object mocks
  - `mock_database`: Patches database functions
- Use `AsyncMock` for async Telethon methods
- Use `MagicMock` for sync methods
- `mock_manager` fixture resets state between tests

## Important Conventions

### Handler Registration

Only commands imported in `handlers/commands/__init__.py` are active. Uncomment to enable:
- `shorturl`, `translate`, `tts`, `asr`
- `chat` and `chat_admin_settings_callback`
- `group_setting_command`, `group_setting_callback`

### Redis Fallback Pattern

```python
rdb = await manager.get_redis()
if rdb:
    # Use Redis feature
    await rdb.zadd(...)
else:
    # Fallback to SQLite
    await database.execute(...)
```

For Redis-dependent features, use `await manager.require_redis()` which raises `RedisUnavailableError` if Redis not available.

### Error Handling

Use manager's logger:
```python
from manager import manager
logger = manager.logger

logger.info("message")
logger.warning("warning")
logger.error("error", exc_info=True)  # include traceback
```

Most handler exceptions are caught by Telethon and logged automatically.

### Message Sending

Prefer manager wrappers:
```python
await manager.send(chat_id, "text", auto_deleted_at=datetime)
await manager.reply(event.message, "reply text")
await manager.edit_text(chat_id, msg_id, "edited text")
```

### Lazy Deletion

Schedule message for future deletion:
```python
await manager.delete_message(chat_id, message_id, deleted_at=datetime)
```

### Lazy Sessions

Schedule callbacks:
```python
await manager.lazy_session(chat_id, msg_id, member_id, "event_type", run_at=datetime)
# event_type must be registered via @manager.register_event("event_type")
```

Cancel pending sessions:
```python
await manager.lazy_session_delete(chat_id, member_id, "event_type")
```

## Deployment Notes

- GitHub Actions workflow: `.github/workflows/deploy.yml`
- Uses rsync to sync code, then SSH to run `docker compose build gk && docker compose up -d gk`
- Requires repository secrets: `DEPLOY_PATH`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_KEY`
- Dockerfile uses Python 3.12 Alpine with ffmpeg, nodejs pre-installed
- Startup script: `docker/startup.sh` (creates log dir, runs main.py)

## Development Workflow

1. Configure `main.ini` (copy from example if needed)
2. Start Redis if using advanced features: `make redis-up`
3. Run bot: `uv run python main.py`
4. Make changes to handlers or manager
5. Tests: `uv run pytest`
6. Lint: `uv run ruff check .`
7. Commit changes

## Known Gotchas

- Handler functions must be `async def`
- Always `await` async manager/database/redis methods
- Some commands are commented out in `handlers/commands/__init__.py` by default
- Redis is optional but required for `/group_setting` and reliable lazy sessions/delete in production
- SQLite fallback has different performance characteristics (no sorted set indexes)
- Using `manager.send()` in event handlers may cause race conditions if bot is typing; consider `await event.reply()` for responses
- Captcha system stores answers in `captcha_answers` SQLite table; expiration handled by bot restart (not automatic cleanup)

## File Locations Reference

- Entry point: `main.py:184` (main())
- Manager core: `manager/manager.py:60` (class Manager)
- Database: `database.py:13` (connection pool)
- Handler registration: `manager/manager.py:162` (register decorator)
- Event registration: `manager/manager.py:193` (register_event)
- Worker loop: `main.py:169`
- Tests: `tests/` with `conftest.py` fixtures
- Config template: `manager/settings.py` (referenced by manager.py)
- Docker: `docker/Dockerfile`, `docker/startup.sh`, `docker-compose.yml`

## Useful Debug Tips

- Set `debug = true` in `[default]` of main.ini for verbose logging
- Check Redis: `make redis-shell` then `PING`, `DBSIZE`, `SCAN 0 COUNT 100`
- Database: `sqlite3 data/main.db` to inspect tables
- Logs: Check stderr output; Docker: `docker compose logs -f gk`
- Reload bot: Stop (Ctrl+C) and restart; no hot-reload
