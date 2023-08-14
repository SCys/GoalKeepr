import asyncio
import aiohttp
from manager import manager


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

    width, height = size.split("x")
    width = int(width)
    height = int(height)

    step = 20
    cfg_scale = 8
    sampler_name = "DPM++ 3M SDE Exponential"  # DDIM, DPM++ 3M SDE Exponential

    async with manager.bot.session() as client:
        response = await client.post(
            url=f"{endpoint}/sdapi/v1/txt2img",
            json={
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "seed": -1,
                "sampler_name": sampler_name,
                "batch_size": 1,
                "n_iter": n,
                "steps": step,
                "cfg_scale": cfg_scale,
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
        )

        if response.status != 200:
            raise Exception(await response.text())

        resp = await response.json()
        return resp["images"][0]


if __name__ == "__main__":
    asyncio.run(txt2img("http://10.1.3.10:7860", "1girl === 1boy"))