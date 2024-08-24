from typing import Optional

import tiktoken


def count_tokens(string: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens


def contains_chinese(text: str) -> bool:
    """
    判断字符串中是否包含中文字符，包括简体中文和繁体中文。

    :param text: 输入的字符串
    :return: 如果包含中文字符返回 True，否则返回 False
    """
    for char in text:
        if (
            "\u4e00" <= char <= "\u9fff"
            or "\u3400" <= char <= "\u4dbf"
            or "\u20000" <= char <= "\u2a6df"
            or "\u2a700" <= char <= "\u2b73f"
            or "\u2b740" <= char <= "\u2b81f"
            or "\u2b820" <= char <= "\u2ceaf"
            or "\u2ceb0" <= char <= "\u2ebef"
        ):
            return True
    return False


def strip_text_prefix(raw: Optional[str]) -> str:
    """
    清理函数

    1. /something_command_prefix0 a bc => a bc
    2. /something_command_prefix1@bot_name a bc => a bc
    3. /something_command_prefix2@bot_name a bc => a bc
    4. a bc => a bc
    5. /something_command_prefix3 => '' (EMPTY TEXT)
    """
    if not raw:
        return ""

    raw = raw.strip()

    if raw.startswith("/"):
        outptus = raw.split(maxsplit=1)
        if len(outptus) > 1:
            return outptus[1]

        return ""

    return raw
