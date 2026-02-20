SETTINGS_TEMPLATE = {
    "default": {"debug": False},
    "telegram": {
        "token": "",  # telegram robot token
        "proxy": "",  # 可选，Telegram 连接代理，如 socks5://127.0.0.1:1080
    },
    "ai": {
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
    "advertising": {
        "enabled": False,  # enable advertising words detection
        "words": [],  # list of advertising words to detect
        "regex_patterns": "",  # semicolon-separated regex patterns, format: "name:pattern;name2:pattern2"
    },
}