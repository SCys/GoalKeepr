import base64
import io
from datetime import timedelta

from aiogram import types
from aiogram.dispatcher.storage import FSMContext
from async_timeout import asyncio
from manager import manager
from orjson import dumps
from pydub import AudioSegment
from tencentcloud.asr.v20190614 import asr_client, models
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile

logger = manager.logger


SUPPORT_GROUP_TYPES = ["supergroup", "group", "private"]


@manager.register("message", commands=["asr"])
async def asr(msg: types.Message, state: FSMContext):
    config = manager.config

    chat = msg.chat

    if not manager.config["tts"]["token"]:
        logger.warning("tts token is missing")
        return

    user = msg.from_user
    users = [int(i) for i in config["asr"]["users"].split(",")]
    if user and user and user.id not in users:
        logger.warning(
            f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) user is not permission, users {users}"
        )
        return

    target = msg
    if msg.reply_to_message:
        target = msg.reply_to_message

    voice = target.voice
    if not voice:
        return

    try:
        src = io.BytesIO()
        dst = io.BytesIO()

        # download and convert to mp3(16k)
        await voice.download(destination_file=src)
        audio = AudioSegment.from_file(src)
        audio.export(dst, format="mp3", bitrate="16k")

        # convert dst data to base64
        data = base64.b64encode(dst.getvalue()).decode("utf-8")
        task_id = await tx_asr(data)

        for i in range(5):
            await asyncio.sleep(i)

            result = await tx_asr_result(task_id)
            if result:
                break

        if not result:
            logger.warning(f"asr result is empty: {task_id}")
            return

        logger.info(f"user {user.full_name}({user.id}) chat {chat.full_name}({chat.id}) asr ok")
        await target.reply(result)
        return
    except Exception as e:
        logger.exception(f"audio convert error")

    msg_detail = await msg.reply("convert failed")
    await manager.lazy_delete_message(chat.id, msg_detail.message_id, msg.date + timedelta(seconds=5))


async def tx_asr(audio_data: str) -> str:
    """腾讯云 ASR"""
    config = manager.config
    id = config["asr"]["tx_id"]
    key = config["asr"]["tx_key"]

    try:
        cred = credential.Credential(id, key)
        httpProfile = HttpProfile()
        httpProfile.endpoint = "asr.tencentcloudapi.com"

        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        client = asr_client.AsrClient(cred, "", clientProfile)

        req = models.CreateRecTaskRequest()
        req.from_json_string(
            dumps(
                {
                    "EngineModelType": "16k_zh",
                    "ChannelNum": 1,
                    "SpeakerDiarization": 0,
                    "SpeakerNumber": 1,
                    "ResTextFormat": 2,
                    "SourceType": 1,
                    "Data": audio_data,
                }
            )
        )

        resp = client.CreateRecTask(req)
        data = resp._serialize(allow_none=True)

        logger.info(f"tencent cloud sdk asr is done: {data['Data']}")
        return data["Data"]["TaskId"]
    except TencentCloudSDKException:
        logger.exception("tencent cloud sdk error")


async def tx_asr_result(task_id: str) -> str:
    """腾讯云 ASR"""

    config = manager.config
    id = config["asr"]["tx_id"]
    key = config["asr"]["tx_key"]

    while True:
        try:
            cred = credential.Credential(id, key)
            httpProfile = HttpProfile()
            httpProfile.endpoint = "asr.tencentcloudapi.com"

            clientProfile = ClientProfile()
            clientProfile.httpProfile = httpProfile
            client = asr_client.AsrClient(cred, "", clientProfile)

            req = models.DescribeTaskStatusRequest()
            req.from_json_string(dumps({"TaskId": task_id}))

            resp = client.DescribeTaskStatus(req)
            data = resp._serialize(allow_none=True)["Data"]
            status = data["StatusStr"]

            if status == "success":
                # detail = data["ResultDetail"]
                result = data["Result"]
                # duration = data["AudioDuration"]

                logger.info(f"tencent cloud sdk asr is done: {task_id} {result}")
                return result.strip()
            elif status == "failed":
                logger.error(f'task status failed: {data["ErrorMsg"]}')
            else:
                logger.warning(f"task status is {status}")
                await asyncio.sleep(3)
                continue

        except TencentCloudSDKException as err:
            print(err)

        break


# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(tx_asr("/home/scys/Downloads/audio.mp3"))
#     asyncio.run(tx_asr_result(1749896288))
