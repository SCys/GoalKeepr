SETTINGS_TEMPLATE = {
    "default": {"debug": False},
    "telegram": {
        "token": "",  # telegram robot token
        "admin": "",  # global admin Telegram user id
        "proxy": "",  # 可选，Telegram 连接代理，如 socks5://127.0.0.1:1080
    },
    "web": {
        "enabled": False,  # enable website admin panel
        "host": "127.0.0.1",
        "port": 8080,
        "cookie_secure": False,  # set true when served over HTTPS
        "session_ttl": 86400,
    },
    "ai": {
        "proxy_host": "",
        "proxy_token": "",
        "administrator": 0,  # admin user id
        "manage_group": 0,  # manage group id
        "chat_model": "deepseek-r1",  # 用于 /chat 命令（必须是 txt.py SUPPORTED_MODELS 的 key）
        "spam_models": "openai/gpt-oss-120b;gemini-3.1-flash-lite-preview;openai/gpt-oss-20b;gemma-4-31b-it",  # 入群 LLM 垃圾检测，多模型 ; 分隔 fallback
        "image_optimize_models": "deepseek-r1;gemini-flash",  # /image 提示词 LLM 优化，多模型 ; 分隔 fallback
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
