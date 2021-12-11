import io
from typing import Optional

import aiohttp
from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from aiohttp.client import ClientSession
from manager import manager

logger = manager.logger

TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
URL_WS = "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=" + TOKEN
URL_ENGINES = "https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/voices/list?trustedclienttoken=" + TOKEN

CMD_1 = 'Content-Type:application/json; charset=utf-8\r\n\r\nPath:speech.config\r\n\r\n{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"true"},"outputFormat":""}}}}\r\n'


@manager.register("message", commands=["tts"])
async def tts(msg: types.Message, state: FSMContext):
    chat = msg.chat
    if chat.type not in ["private"]:
        return

    msgRpl = msg.reply_to_message

    txt = msg.text
    if not txt:
        txt = msgRpl.text

    if not txt:
        logger.debug("no text in message")
        return

    output: Optional[io.BytesIO] = None

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with ClientSession(timeout=timeout) as session:
            async with session.ws_connect("http://example.org/ws") as ws:
                # send command
                ws.send_str(CMD_1)
                ws.send_str(
                    "X-RequestId:fe83fbefb15c7739fe674d9f3e81d38f\r\nContent-Type:application/ssml+xml\r\nPath:ssml\r\n\r\n<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'><voice  name='"
                    "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)'><prosody pitch='+0Hz' rate ='+0%' volume='+0%'>"
                    f"{txt}</prosody></voice></speak>\r\n"
                )

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        if "turn.end" in msg.data:
                            break
                        elif b"Path:audio\r\n" in msg.data:
                            output = io.BytesIO(msg.data.split(b"Path:audio\r\n")[1].encode())
                        else:
                            pass

                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.info(f"ws connection closed with exception {msg.exception()}")
                        break
                    else:
                        logger.info(f"unknown message type: {msg.type}")

                ws.close()
    except Exception:
        logger.exception("remote error")

    if output is None:
        return

    await msg.answer_audio(output, supports_streaming=True)
    logger.info("tts done")


# class WSClient(WebSocketClient):
#     file: io.BytesIO

#     def __init__(self, url, text, engine=None, codec =None):
#         self.text = text
#         self.engine = engine
#         self.format = codec

#         if self.engine is None:
#             self.engine = "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)"

#         if self.format is None:
#             self.format ="audio-24khz-48kbitrate-mono-mp3"

#         super(WSClient, self).__init__(url)

#     def opened(self):
#         self.send(
#             'Content-Type:application/json; charset=utf-8\r\n\r\nPath:speech.config\r\n\r\n{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"true"},"outputFormat":"'
#             + self.format
#             + '"}}}}\r\n'
#         )
#         self.send(
#             "X-RequestId:fe83fbefb15c7739fe674d9f3e81d38f\r\nContent-Type:application/ssml+xml\r\nPath:ssml\r\n\r\n<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'><voice  name='"
#             + self.engine
#             + "'><prosody pitch='+0Hz' rate ='+0%' volume='+0%'>"
#             + self.text
#             + "</prosody></voice></speak>\r\n"
#         )

#     def received_message(self, m):
#         try:
#             if b"turn.end" in m.data:
#                 self.close()
#             elif b"Path:audio\r\n" in m.data:

#                 self.output = io.BytesIO(m.data.split(b"Path:audio\r\n")[1])
#                 self.output.flush()
#             else:
#                 pass
#         except IOError as nonsense_error:
#             if nonsense_error.errno == errno.EIO:  # useless I/O errors
#                 pass
#             else:  # e.g. broken pipe
#                 sys.exit()


# if __name__ == "__main__":
#     import argparse
#     import sys

#     parser = argparse.ArgumentParser(description=__doc__)
#     parser.add_argument("text", help="Text to speak.", default="hello, world", nargs="?")
#     parser.add_argument(
#         "-e",
#         "--engine",
#         help='Speak engine (default: "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)")',
#         default="Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)",
#     )
#     parser.add_argument(
#         "-c",
#         "--codec",
#         help='Output codec (default: "audio-24khz-48kbitrate-mono-mp3")',
#         default="audio-24khz-48kbitrate-mono-mp3",
#     )
#     parser.add_argument("-l", "--list", help='Index an engine then exit. For everything use "__all__"', action=ListEngineAction)

#     arg = parser.parse_args()
#     ws = WSClient(URL_WS, arg.text, arg.engine, arg.codec)
#     ws.connect()
#     ws.run_forever()
