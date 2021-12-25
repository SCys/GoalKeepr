# import asyncio.exceptions
import io
from datetime import datetime

from pydub import AudioSegment
import aiohttp
from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from aiohttp.client import ClientSession
from manager import manager

logger = manager.logger

# TOKEN = __TOKEN__
# URL_WS = "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=" + TOKEN
# URL_ENGINES = "https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/voices/list?trustedclienttoken=" + TOKEN

CMD_1 = 'Content-Type:application/json; charset=utf-8\r\n\r\nPath:speech.config\r\n\r\n{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"true"},"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n'


@manager.register("message", commands=["tts"])
async def tts(msg: types.Message, state: FSMContext):
    chat = msg.chat
    if chat.type not in ["private"]:
        logger.warning("chat type is not private")
        return

    user = msg.from_user
    if not user:
        logger.warning(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) user is not found")
        return

    txt = msg.text
    if msg.reply_to_message:
        txt = msg.reply_to_message.text
    else:
        txt = txt.replace("/tts", "", 1)

    txt = txt.strip()

    if not txt:
        logger.warning(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) send empty text")
        return

    logger.info(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) message {len(txt)}")

    cost = datetime.now()
    data = b""

    try:
        timeout = aiohttp.ClientTimeout(total=60)
        url_ws = f"wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken={manager.config['tts']['token']}"

        async with ClientSession(timeout=timeout) as session:
            async with session.ws_connect(url_ws) as ws:
                # send command
                await ws.send_str(CMD_1)
                await ws.send_str(
                    "X-RequestId:fe83fbefb15c7739fe674d9f3e81d38f\r\nContent-Type:application/ssml+xml\r\nPath:ssml\r\n\r\n<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'><voice  name='"
                    "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)'><prosody pitch='+0Hz' rate ='+0%' volume='+0%'>"
                    f"{txt}</prosody></voice></speak>\r\n"
                )

                async for i in ws:
                    if i.type == aiohttp.WSMsgType.TEXT:
                        if "turn.end" in i.data:
                            break

                    elif i.type == aiohttp.WSMsgType.BINARY:
                        if b"turn.end" in i.data:
                            break
                        elif b"Path:audio\r\n" in i.data:
                            header, bin = i.data.split(b"Path:audio\r\n")
                            # logger.info(f"got audio:{header}")
                            data += bin

                    elif i.type == aiohttp.WSMsgType.ERROR:
                        logger.info(f"ws connection closed with exception {i.data}")
                        break
                    else:
                        logger.info(f"unknown message type: {i.type}")

                await ws.close()
    except Exception as e:
        logger.exception(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) error")
        return

    if not data:
        logger.error(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) no data")
        return

    output = io.BytesIO()
    audio = AudioSegment.from_file(io.BytesIO(data), format="mp3")
    audio.export(output, codec="opus", format="ogg", parameters=["-strict", "-2"])

    if msg.reply_to_message:
        await msg.reply_to_message.reply_voice(output, disable_notification=True)
    else:
        await msg.reply_voice(output, disable_notification=True)
    logger.info(
        f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) cost {(datetime.now() - cost).total_seconds()}"
    )
