from typing import BinaryIO

from aiohttp import ClientTimeout

from manager import manager

logger = manager.logger


async def openai_whisper(raw: BinaryIO):
    # request the remove

    # load users and groups from configure
    config = manager.config
    try:
        endpoint = config["asr"]["endpoint"]
    except:
        logger.exception("asr endpoint not found")
        return

    session = await manager.create_session()
    async with session.post(
        url=endpoint,
        data={"audio": raw},
        timeout=ClientTimeout(total=300, connect=15, sock_read=240),
    ) as response:
        if response.status != 200:
            raise Exception(await response.text())

        resp = await response.json()
        return resp["text"]
