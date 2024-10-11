import asyncio

from aiohttp import ClientTimeout

from manager import manager

# PROMPT_PREFIX = """modelshoot style, photo realistic game cg, 8k, epic, symetrical features, Intricate, High Detail, Sharp focus, photorealistic, epic volumetric lighting, fine details, illustration, (masterpiece, best quality, highres),\n"""
# NEGATIVE_PROMPT_PREFIX = "(((simple background))),monochrome ,lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, lowres, bad anatomy, bad hands, text, error, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, ugly,pregnant,vore,duplicate,morbid,mut ilated,tran nsexual, hermaphrodite,long neck,mutated hands,poorly drawn hands,poorly drawn face,mutation,deformed,blurry,bad anatomy,bad proportions,malformed limbs,extra limbs,cloned face,disfigured,gross proportions, (((missing arms))),((( missing legs))), (((extra arms))),(((extra legs))),pubic hair, plump,bad legs,error legs,username,blurry,bad feet, lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry,\n"

PROMPT_PREFIX = ""
NEGATIVE_PROMPT_PREFIX = ""

CFG_SCALE = 1
STEP = 2
SAMPLER_NAME = "DPM++ 2M SDE"
SCHEDULER = "Simple"


async def txt2img(endpoint: str, raw: str, model: str = "prefect_pony", n: int = 1, size: str = "512x512", step=STEP) -> dict:
    """return is base64 str png"""
    # split the raw by ===, upside is prompt, downside is negative prompt
    if "===" in raw:
        parts = raw.split("===")
        prompt = parts[0]
        negative_prompt = parts[1]
        # ignore more ===
    else:
        prompt = raw
        negative_prompt = ""

    try:
        width, height = size.split("x")
        width = int(width)
        height = int(height)
    except:
        width = 512
        height = 512

    timeout = ClientTimeout(total=300, connect=15, sock_read=240)
    if width * height > 513 * 513:
        timeout = ClientTimeout(total=600, connect=15, sock_read=480)

    session = await manager.create_session()
    async with session.post(
        url=f"{endpoint}/sdapi/v1/txt2img",
        json={
            "model": model,
            "prompt": PROMPT_PREFIX + prompt,
            "negative_prompt": NEGATIVE_PROMPT_PREFIX + negative_prompt,
            "seed": -1,
            "sampler_name": SAMPLER_NAME,
            "scheduler": SCHEDULER,
            "hr_scheduler": SCHEDULER,
            "batch_size": 1,
            "n_iter": n,
            "steps": step,
            "cfg_scale": CFG_SCALE,
            "width": width,
            "height": height,
            "restore_faces": False,
            "tiling": False,
            "do_not_save_samples": False,
            "do_not_save_grid": False,
            "eta": 0,
            "send_images": True,
            "save_images": False,
        },
        # timeout 5m, connect 15s, read 240s
        timeout=timeout,
    ) as response:
        if response.status != 200:
            raise Exception(await response.text())

        resp = await response.json()
        # return resp["images"][0]
        if "error" in resp:
            # {'error': {'code': 400, 'message': 'client error'}}
            return resp

        return {"image": resp["images"][0]}


if __name__ == "__main__":
    asyncio.run(txt2img("http://10.1.3.10:7860", "1girl === 1boy"))
