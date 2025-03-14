
SETTINGS_TEMPLATE = {
    "default": {"debug": False},
    "telegram": {"token": ""},  # telegram robot token
    "captcha": {
        "cloudflare_turnstile": False,  # enable cloudflare turnstile detector
        "cloudflare_turnstile_token": "",
        "google_recaptcha": False,  # enable google recaptcha detector
        "google_recaptcha_token": "",
    },
    "ai": {
        "google_gemini_host": "",
        "google_gemini_token": "",
        "proxy_host": "",
        "proxy_token": "",
        "administrator": 0,  # admin user id
        "manage_group": 0,  # manage group id
    },
    "image": {
        "users": [],  # allowed users(id list)
        "groups": [],  # allowed groups(id list)
    },
    "sd_api": {
        "endpoint": "",
    },
}