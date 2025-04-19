import asyncio
import base64

from manager import manager


async def generate_image(
    endpoint: str,
    checkpoint: str,
    prompt: str,
    size: str = "512x512",
    steps: int = 12,
    cfg: float = 1.0,
) -> str:
    """
    通过 ComfyUI API 异步生成图片

    Args:
        prompt (str): 生成图片的文本描述
        size (str): 图片尺寸，格式为 "宽x高"，如 "512x512"
        steps (int): 采样步数，默认为 20
        cfg (float): CFG scale，默认为 7.0

    Returns:
        str: base64编码的图片数据
    """

    # 解析尺寸字符串
    try:
        width, height = map(int, size.lower().split("x"))
    except ValueError:
        raise ValueError("尺寸格式错误，应为 'widthxheight'，例如 '512x512'")

    # random seed: The default value is 0, with a minimum of 0 and a maximum of 0xffffffffffffffff
    # seed = random.randint(0, 0xffffffffffffffff)

    # Flux workflow
    workflow = {
        "6": {
            "inputs": {
                "text": prompt,
                "clip": ["44", 0],
            },
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "CLIP Text Encode (Positive Prompt)"},
        },
        "8": {
            "inputs": {"samples": ["13", 0], "vae": ["10", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "VAE Decode"},
        },
        "9": {
            "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
            "class_type": "SaveImage",
            "_meta": {"title": "Save Image"},
        },
        "10": {
            "inputs": {"vae_name": "ae.safetensors"},
            "class_type": "VAELoader",
            "_meta": {"title": "Load VAE"},
        },
        "13": {
            "inputs": {
                "noise": ["25", 0],
                "guider": ["22", 0],
                "sampler": ["16", 0],
                "sigmas": ["17", 0],
                "latent_image": ["27", 0],
            },
            "class_type": "SamplerCustomAdvanced",
            "_meta": {"title": "SamplerCustomAdvanced"},
        },
        "16": {
            "inputs": {"sampler_name": "euler"},
            "class_type": "KSamplerSelect",
            "_meta": {"title": "KSamplerSelect"},
        },
        "17": {
            "inputs": {
                "scheduler": "simple",
                "steps": steps,
                "denoise": 1,
                "model": ["30", 0],
            },
            "class_type": "BasicScheduler",
            "_meta": {"title": "BasicScheduler"},
        },
        "22": {
            "inputs": {"model": ["30", 0], "conditioning": ["26", 0]},
            "class_type": "BasicGuider",
            "_meta": {"title": "BasicGuider"},
        },
        "25": {
            "inputs": {"noise_seed": 0},
            "class_type": "RandomNoise",
            "_meta": {"title": "RandomNoise"},
        },
        "26": {
            "inputs": {"guidance": 3.5, "conditioning": ["6", 0]},
            "class_type": "FluxGuidance",
            "_meta": {"title": "FluxGuidance"},
        },
        "27": {
            "inputs": {"width": width, "height": height, "batch_size": 1},
            "class_type": "EmptySD3LatentImage",
            "_meta": {"title": "EmptySD3LatentImage"},
        },
        "30": {
            "inputs": {
                "max_shift": 1.15,
                "base_shift": 0.5,
                "width": width,
                "height": height,
                "model": ["49", 0],
            },
            "class_type": "ModelSamplingFlux",
            "_meta": {"title": "ModelSamplingFlux"},
        },
        "44": {
            "inputs": {
                "model_type": "flux",
                "text_encoder1": "t5xxl_fp8_e4m3fn.safetensors",
                "text_encoder2": "clip_l.safetensors",
                "t5_min_length": 512,
                "use_4bit_t5": "disable",
                "int4_model": "none",
            },
            "class_type": "NunchakuTextEncoderLoader",
            "_meta": {"title": "Nunchaku Text Encoder Loader"},
        },
        "45": {
            "inputs": {
                "model_path": "svdq-int4-flux.1-dev",
                "cache_threshold": 0,
                "attention": "nunchaku-fp16",
                "cpu_offload": "auto",
                "device_id": 0,
                "data_type": "float16",
                "i2f_mode": "enabled",
            },
            "class_type": "NunchakuFluxDiTLoader",
            "_meta": {"title": "Nunchaku FLUX DiT Loader"},
        },
        "46": {
            "inputs": {
                "lora_name": "flux1-turbo.safetensors",
                "lora_strength": 1,
                "model": ["45", 0],
            },
            "class_type": "NunchakuFluxLoraLoader",
            "_meta": {"title": "Nunchaku FLUX.1 LoRA Loader"},
        },
        "49": {
            "inputs": {
                "lora_name": "Realistic_Anime_-_Flux.safetensors",
                "lora_strength": 1,
                "model": ["46", 0],
            },
            "class_type": "NunchakuFluxLoraLoader",
            "_meta": {"title": "Nunchaku FLUX.1 LoRA Loader"},
        },
    }

    try:
        session = await manager.create_session()
        # 发送工作流请求
        async with session.post(
            f"{endpoint}/prompt", json={"prompt": workflow}
        ) as prompt_response:
            if prompt_response.status != 200:
                raise Exception(f"API请求失败: {prompt_response.status}")

            prompt_data = await prompt_response.json()
            prompt_id = prompt_data["prompt_id"]

            # 等待图片生成完成
            while True:
                async with session.get(f"{endpoint}/history") as history_response:
                    if history_response.status == 200:
                        history = await history_response.json()
                        if (
                            prompt_id in history
                            and len(history[prompt_id]["outputs"]) > 0
                        ):
                            # 获取生成的图片文件名
                            image_filename = history[prompt_id]["outputs"]["9"][
                                "images"
                            ][0]["filename"]

                            # 通过 /view 接口获取图片数据
                            async with session.get(
                                f"{endpoint}/view?filename={image_filename}"
                            ) as image_response:
                                if image_response.status == 200:
                                    image_data = await image_response.read()
                                    base64_data = base64.b64encode(image_data).decode(
                                        "utf-8"
                                    )
                                    return base64_data
                                else:
                                    raise Exception(
                                        f"获取图片失败: {image_response.status}"
                                    )
                await asyncio.sleep(1)

    except Exception as e:
        raise Exception(f"生成图片时发生错误: {str(e)}")
