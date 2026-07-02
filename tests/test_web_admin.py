from __future__ import annotations

import hashlib
import hmac
from configparser import ConfigParser

import pytest

from web_admin import (
    TelegramLoginError,
    configured_admin_id,
    make_session_cookie,
    read_session_cookie,
    verify_telegram_login,
)


BOT_TOKEN = "123456:ABC-DEF"
NOW = 1_700_000_000


def _signed_login_data(user_id: str = "42", auth_date: int = NOW) -> dict[str, str]:
    data = {
        "id": user_id,
        "first_name": "Admin",
        "username": "goalkeeper",
        "auth_date": str(auth_date),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode("utf-8")).digest()
    data["hash"] = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return data


def test_verify_telegram_login_accepts_valid_signature():
    verified = verify_telegram_login(_signed_login_data(), BOT_TOKEN, now=NOW)

    assert verified["id"] == "42"
    assert "hash" not in verified


def test_verify_telegram_login_rejects_tampered_data():
    data = _signed_login_data()
    data["id"] = "43"

    with pytest.raises(TelegramLoginError):
        verify_telegram_login(data, BOT_TOKEN, now=NOW)


def test_verify_telegram_login_rejects_stale_data():
    data = _signed_login_data(auth_date=NOW - 90_000)

    with pytest.raises(TelegramLoginError):
        verify_telegram_login(data, BOT_TOKEN, now=NOW)


def test_configured_admin_id_uses_telegram_admin():
    config = ConfigParser()
    config["telegram"] = {"admin": " 42 "}

    assert configured_admin_id(config) == "42"


def test_configured_admin_id_ignores_empty_or_placeholder_values():
    config = ConfigParser()
    config["telegram"] = {"admin": "你的 admin id"}

    assert configured_admin_id(config) is None


def test_session_cookie_round_trip_and_expiry():
    cookie = make_session_cookie("42", BOT_TOKEN, now=NOW)

    assert read_session_cookie(cookie, BOT_TOKEN, now=NOW + 60) == "42"
    assert read_session_cookie(cookie, BOT_TOKEN, now=NOW + 90_000) is None


def test_session_cookie_rejects_tampering():
    cookie = make_session_cookie("42", BOT_TOKEN, now=NOW)
    tampered = cookie[:-1] + ("0" if cookie[-1] != "0" else "1")

    assert read_session_cookie(tampered, BOT_TOKEN, now=NOW) is None
