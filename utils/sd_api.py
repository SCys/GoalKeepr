import asyncio

from manager import manager

# PROMPT_PREFIX = """modelshoot style, photo realistic game cg, 8k, epic, symetrical features, Intricate, High Detail, Sharp focus, photorealistic, epic volumetric lighting, fine details, illustration, (masterpiece, best quality, highres),\n"""
# NEGATIVE_PROMPT_PREFIX = "(((simple background))),monochrome ,lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, lowres, bad anatomy, bad hands, text, error, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, ugly,pregnant,vore,duplicate,morbid,mut ilated,tran nsexual, hermaphrodite,long neck,mutated hands,poorly drawn hands,poorly drawn face,mutation,deformed,blurry,bad anatomy,bad proportions,malformed limbs,extra limbs,cloned face,disfigured,gross proportions, (((missing arms))),((( missing legs))), (((extra arms))),(((extra legs))),pubic hair, plump,bad legs,error legs,username,blurry,bad feet, lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry,\n"

PROMPT_PREFIX = ""
NEGATIVE_PROMPT_PREFIX = ""

CFG_SCALE = 2
STEP = 24
SAMPLER_NAME = "DPM++ 2M Karras"


async def txt2img(endpoint: str, raw: str, n: int = 1, size: str = "512x512") -> str:
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

    session = await manager.bot.session.create_session()
    async with session.post(
        url=f"{endpoint}/sdapi/v1/txt2img",
        json={
            "prompt": PROMPT_PREFIX + prompt,
            "negative_prompt": NEGATIVE_PROMPT_PREFIX + negative_prompt,
            "seed": -1,
            "sampler_name": SAMPLER_NAME,
            "batch_size": 1,
            "n_iter": n,
            "steps": STEP,
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
        timeout=120,  # 120s
    ) as response:
        if response.status != 200:
            raise Exception(await response.text())

        resp = await response.json()
        return resp["images"][0]


if __name__ == "__main__":
    asyncio.run(txt2img("http://10.1.3.10:7860", "1girl === 1boy"))
