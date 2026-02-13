import re
from datetime import timedelta

from aiohttp import ClientTimeout, ClientError
from asyncio import TimeoutError
from telethon import events
from manager import manager
from typing import Optional

RE_URL = re.compile(
    r"""(?i)\b((?:https?:(?:/{1,3}|[a-z0-9%])|[a-z0-9.\-]+[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)/)(?:[^\s()<>{}\[\]]+|\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\))+(?:\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\)|[^\s`!()\[\]{};:'".,<>?«»“”‘’])|(?:(?<!@)[a-z0-9]+(?:[.\-][a-z0-9]+)*[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)\b/?(?!@)))"""
)

URL_API = "https://api.iscys.com/api/shorturl"

logger = manager.logger


@manager.register("message", pattern=r"(?i)^/shorturl(?:\s+.*)?$")
async def shorturl_command(event: events.NewMessage.Event):
    sender = await event.get_sender()
    content = None
    reply = await event.get_reply_message()
    if reply and reply.text:
        content = reply.text
    if not content:
        content = event.raw_text or event.text
        if content:
            content = re.sub(r"(?i)^/shorturl(?:@\w+)?\s*", "", content).strip()
    if not content:
        msg_reply = await event.reply("没有匹配到任何URL，稍后自动删除")
        await manager.delete_message(event.chat_id, msg_reply, event.date + timedelta(seconds=5))
        return

    matched = re.search(RE_URL, content)
    if not matched:
        msg_reply = await event.reply("没有匹配到任何URL，稍后自动删除")
        await manager.delete_message(event.chat_id, msg_reply, event.date + timedelta(seconds=5))
        return

    for i in matched.groups():
        if not i:
            continue
        url_shorted = await shorturl(i)
        if url_shorted is None:
            continue

        sender_id = sender.id if sender else "unknown"
        logger.info(f"user {sender_id} shorturl {i} to {url_shorted}")
        await event.reply(url_shorted, link_preview=False)


async def shorturl(origin) -> Optional[str]:
    try:
        timeout = ClientTimeout(total=10)
        session = await manager.create_session()
        async with session.post(URL_API, json={"params": {"url": origin}}, timeout=timeout) as resp:
            if resp.status != 200:
                logger.warning(f"shorturl service failed {resp.status} {resp.reason}")
                return

            data = await resp.json()
            if "error" in data:
                err = data["error"]
                logger.warning(f"shorturl service failed {err['code']} {err['message']}")
                return

            code = data["data"]["code"]
            expired = data["data"]["expired"]
            logger.info(f"url {origin} is shorted {code} {expired}")
            return data["data"]["url"]

    except TimeoutError:
        logger.error("shorturl service timeout")

    except ClientError as e:
        logger.error(f"shorturl service client error: {e}")

    except Exception as e:
        logger.exception(f"shorturl service error: {e}")
