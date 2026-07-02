from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import time
from configparser import ConfigParser
from typing import Mapping, Optional

from aiohttp import web


COOKIE_NAME = "goalkeepr_admin"
DEFAULT_LOGIN_MAX_AGE = 86400


class TelegramLoginError(ValueError):
    """Raised when Telegram Login data is missing, stale, or has a bad signature."""


def configured_admin_id(config: ConfigParser) -> Optional[str]:
    admin_id = config["telegram"].get("admin", "") if "telegram" in config else ""
    admin_id = (admin_id or "").strip()
    return admin_id if admin_id.isdigit() else None


def verify_telegram_login(
    data: Mapping[str, str],
    bot_token: str,
    *,
    now: Optional[int] = None,
    max_age: int = DEFAULT_LOGIN_MAX_AGE,
) -> dict[str, str]:
    received_hash = (data.get("hash") or "").strip()
    if not received_hash:
        raise TelegramLoginError("missing hash")

    auth_date_raw = data.get("auth_date")
    if not auth_date_raw:
        raise TelegramLoginError("missing auth_date")
    try:
        auth_date = int(auth_date_raw)
    except ValueError as exc:
        raise TelegramLoginError("invalid auth_date") from exc

    now_ts = int(time.time()) if now is None else int(now)
    if auth_date > now_ts + 300:
        raise TelegramLoginError("auth_date is in the future")
    if max_age > 0 and now_ts - auth_date > max_age:
        raise TelegramLoginError("auth_date is too old")

    check_items = [f"{key}={value}" for key, value in sorted(data.items()) if key != "hash"]
    data_check_string = "\n".join(check_items)
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise TelegramLoginError("invalid hash")

    return {key: value for key, value in data.items() if key != "hash"}


def _session_signature(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_session_cookie(user_id: str, secret: str, *, now: Optional[int] = None) -> str:
    payload = json.dumps(
        {"uid": str(user_id), "iat": int(time.time()) if now is None else int(now)},
        separators=(",", ":"),
        sort_keys=True,
    )
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{encoded}.{_session_signature(secret, encoded)}"


def read_session_cookie(
    cookie_value: Optional[str],
    secret: str,
    *,
    now: Optional[int] = None,
    ttl: int = DEFAULT_LOGIN_MAX_AGE,
) -> Optional[str]:
    if not cookie_value or "." not in cookie_value:
        return None
    encoded, signature = cookie_value.rsplit(".", 1)
    if not hmac.compare_digest(_session_signature(secret, encoded), signature):
        return None

    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        uid = str(payload["uid"])
        issued_at = int(payload["iat"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    now_ts = int(time.time()) if now is None else int(now)
    if ttl > 0 and now_ts - issued_at > ttl:
        return None
    return uid


class AdminWebServer:
    def __init__(self, manager, bot_username: str):
        self.manager = manager
        self.bot_username = bot_username
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None

    @property
    def _config(self) -> ConfigParser:
        return self.manager.config

    @property
    def _bot_token(self) -> str:
        return self._config["telegram"].get("token", "")

    @property
    def _session_ttl(self) -> int:
        return self._config["web"].getint("session_ttl", DEFAULT_LOGIN_MAX_AGE)

    @property
    def _cookie_secure(self) -> bool:
        return self._config["web"].getboolean("cookie_secure", False)

    async def start(self) -> None:
        app = web.Application()
        app.add_routes(
            [
                web.get("/", self.index),
                web.get("/login", self.login),
                web.get("/auth/telegram/callback", self.telegram_callback),
                web.get("/admin", self.admin),
                web.get("/logout", self.logout),
            ]
        )
        self.runner = web.AppRunner(app)
        await self.runner.setup()

        host = self._config["web"].get("host", "127.0.0.1")
        port = self._config["web"].getint("port", 8080)
        self.site = web.TCPSite(self.runner, host=host, port=port)
        await self.site.start()
        self.manager.logger.info(f"admin web started at http://{host}:{port}")

    async def stop(self) -> None:
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
            self.site = None

    def _current_admin_id(self, request: web.Request) -> Optional[str]:
        admin_id = configured_admin_id(self._config)
        if not admin_id:
            return None
        session_user_id = read_session_cookie(
            request.cookies.get(COOKIE_NAME),
            self._bot_token,
            ttl=self._session_ttl,
        )
        return session_user_id if session_user_id == admin_id else None

    async def index(self, request: web.Request) -> web.Response:
        raise web.HTTPFound("/admin" if self._current_admin_id(request) else "/login")

    async def login(self, request: web.Request) -> web.Response:
        admin_id = configured_admin_id(self._config)
        if not admin_id:
            self.manager.logger.warning("admin web login disabled: [telegram] admin is not configured")
            return web.Response(text="[telegram] admin is not configured", status=503)

        bot_username = html.escape(self.bot_username.lstrip("@"))
        body = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>GoalKeepr Admin</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f6f7f9; color: #1f2933; }}
    main {{ width: min(420px, calc(100vw - 32px)); padding: 28px; background: #fff; border: 1px solid #d8dee8; border-radius: 8px; box-shadow: 0 10px 32px rgba(31, 41, 51, .08); }}
    h1 {{ margin: 0 0 18px; font-size: 22px; font-weight: 650; }}
  </style>
</head>
<body>
  <main>
    <h1>GoalKeepr Admin</h1>
    <script async src=\"https://telegram.org/js/telegram-widget.js?22\" data-telegram-login=\"{bot_username}\" data-size=\"large\" data-auth-url=\"/auth/telegram/callback\" data-request-access=\"write\"></script>
  </main>
</body>
</html>"""
        return web.Response(text=body, content_type="text/html")

    async def telegram_callback(self, request: web.Request) -> web.Response:
        try:
            telegram_user = verify_telegram_login(dict(request.query), self._bot_token, max_age=self._session_ttl)
        except TelegramLoginError as exc:
            self.manager.logger.warning(f"telegram web login rejected: {exc}")
            return web.Response(text="invalid Telegram login", status=401)

        login_user_id = str(telegram_user.get("id", ""))
        admin_id = configured_admin_id(self._config)
        if not admin_id:
            self.manager.logger.warning("telegram web login rejected: [telegram] admin is not configured")
            return web.Response(text="admin is not configured", status=503)
        if login_user_id != admin_id:
            self.manager.logger.warning(f"telegram web login forbidden for user {login_user_id}")
            return web.Response(text="forbidden", status=403)

        response = web.HTTPFound("/admin")
        response.set_cookie(
            COOKIE_NAME,
            make_session_cookie(login_user_id, self._bot_token),
            max_age=self._session_ttl,
            httponly=True,
            secure=self._cookie_secure,
            samesite="Lax",
            path="/",
        )
        raise response

    async def admin(self, request: web.Request) -> web.Response:
        admin_id = self._current_admin_id(request)
        if not admin_id:
            raise web.HTTPFound("/login")

        body = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>GoalKeepr Admin</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f6f7f9; color: #1f2933; }}
    header {{ display: flex; justify-content: space-between; align-items: center; padding: 18px 24px; background: #fff; border-bottom: 1px solid #d8dee8; }}
    h1 {{ margin: 0; font-size: 20px; }}
    main {{ padding: 24px; }}
    a {{ color: #1f5fbf; text-decoration: none; }}
  </style>
</head>
<body>
  <header><h1>GoalKeepr Admin</h1><a href=\"/logout\">退出</a></header>
  <main>已通过 Telegram 管理员身份登录：{html.escape(admin_id)}</main>
</body>
</html>"""
        return web.Response(text=body, content_type="text/html")

    async def logout(self, request: web.Request) -> web.Response:
        response = web.HTTPFound("/login")
        response.del_cookie(COOKIE_NAME, path="/")
        raise response
