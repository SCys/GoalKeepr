import openai

from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from manager import manager

logger = manager.logger


@manager.register("message", commands=["code"], commands_ignore_caption=True, commands_ignore_mention=True)
async def code(msg: types.Message, state: FSMContext):
    """使用openai的模型生成代码"""
    chat = msg.chat
    user = msg.from_user
    prefix = f"chat {chat.id}({chat.title}) msg {msg.message_id}"

    if not user:
        logger.warning(f"{prefix} message without user, ignored")
        return

    prefix += f" user {user.full_name}"

    logger.info(f"{prefix} is generating code")
    response = await openai.Completion.acreate(
        prompt=msg.text,
        model="code-davinci-002",
        temperature=0,
        max_tokens=500,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
    )

    if not isinstance(response, dict) or "choices" not in response or len(response["choices"]) == 0:
        logger.warning(f"{prefix} is generated code failed {response}")
        return

    codes = response["choices"][0]
    logger.info(f"{prefix} is generated code {len(codes)}")
    await msg.reply(codes)
