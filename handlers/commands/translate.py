import re

import httpx
from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from googletrans import Translator

# from googletrans import urls, utils
# from googletrans.constants import DEFAULT_USER_AGENT, DUMMY_DATA, LANGCODES, LANGUAGES, SPECIAL_CASES
# from googletrans.models import Translated
from httpx import Timeout
from manager import manager

logger = manager.logger

RE_CLEAR = re.compile(r"/tr(anslate)?(@[a-zA-Z0-9]+\s?)?")


@manager.register("message", commands=["translate", "tr"])
async def translate(msg: types.Message, state: FSMContext):
    user = msg.from_user

    target = msg
    content = msg.text
    if msg.reply_to_message:
        content = msg.reply_to_message.text
        target = msg.reply_to_message

    if not content:
        await msg.answer("Please send me a text to translate")
        return

    if txt.startswith("/tr"):
        txt = RE_CLEAR.sub("", txt, 1)

    try:
        translator = Translator(timeout=Timeout(5))
        result = translator.translate(content, dest=user.language_code, src="auto")
        await target.reply(result.text)
    except Exception as e:
        logger.exception("translate failed")

        await msg.reply("Translate failed with:{}".format(e))

    logger.info(f"user ({user.full_name} / {user.id}) start a translate task")


EXCLUDES = ("en", "ca", "fr")


# class Translator(googletrans.Translator):
#     async def _translate(self, text, dest, src, override):
#         token = self.token_acquirer.do(text)
#         params = utils.build_params(query=text, src=src, dest=dest, token=token, override=override)

#         url = urls.TRANSLATE.format(host=self._pick_service_url())

#         async with httpx.AsyncClient() as client:
#             client.headers.update({"User-Agent": DEFAULT_USER_AGENT})
#             # self.token_acquirer.client = client

#             r = await client.get(url, params=params)

#             if r.status_code == 200:
#                 data = utils.format_json(r.text)
#                 return data

#             if self.raise_exception:
#                 raise Exception('Unexpected status code "{}" from {}'.format(r.status_code, self.service_urls))
#             DUMMY_DATA[0][0][0] = text
#             return DUMMY_DATA

#     async def translate(self, text, dest="en", src="auto", **kwargs):
#         dest = dest.lower().split("_", 1)[0]
#         src = src.lower().split("_", 1)[0]

#         if src != "auto" and src not in LANGUAGES:
#             if src in SPECIAL_CASES:
#                 src = SPECIAL_CASES[src]
#             elif src in LANGCODES:
#                 src = LANGCODES[src]
#             else:
#                 raise ValueError("invalid source language")

#         if dest not in LANGUAGES:
#             if dest in SPECIAL_CASES:
#                 dest = SPECIAL_CASES[dest]
#             elif dest in LANGCODES:
#                 dest = LANGCODES[dest]
#             else:
#                 raise ValueError("invalid destination language")

#         if isinstance(text, list):
#             result = []
#             for item in text:
#                 translated = await self.translate(item, dest=dest, src=src, **kwargs)
#                 result.append(translated)
#             return result

#         origin = text
#         # SCys: convert to async
#         data = await self._translate(text, dest, src, kwargs)

#         # this code will be updated when the format is changed.
#         translated = "".join([d[0] if d[0] else "" for d in data[0]])

#         extra_data = self._parse_extra_data(data)

#         # actual source language that will be recognized by Google Translator when the
#         # src passed is equal to auto.
#         try:
#             src = data[2]
#         except Exception:  # pragma: nocover
#             pass

#         pron = origin
#         try:
#             pron = data[0][1][-2]
#         except Exception:  # pragma: nocover
#             pass

#         if pron is None:
#             try:
#                 pron = data[0][1][2]
#             except:  # pragma: nocover
#                 pass

#         if dest in EXCLUDES and pron == origin:
#             pron = translated

#         # put final values into a new Translated object
#         result = Translated(src=src, dest=dest, origin=origin, text=translated, pronunciation=pron, extra_data=extra_data)

#         return result
