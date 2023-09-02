def strip_text_prefix(raw: str) -> str:
    """
    remove the text prefix

    input 1: /something_command_prefix0 girl beautiful girl no face long leg
    input 2: /something_command_prefix1@bot_name girl beautiful girl no face long leg
    input 3: /something_command_prefix2@bot_name girl beautiful girl no face long leg
    input 4: girl beautiful girl no face long leg

    output: girl beautiful girl no face long leg
    """
    try:
        if not raw.startswith("/"):
            return raw

        # remove the command prefix
        return raw.split(" ", 1)[1]
    except IndexError:
        return raw
