import asyncio

from aiohttp import ClientSession, ClientTimeout

from manager import manager

logger = manager.logger


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
            "inputs": {"sampler_name": "euler_ancestral"},
            "class_type": "KSamplerSelect",
            "_meta": {"title": "KSamplerSelect"},
        },
        "17": {
            "inputs": {
                "scheduler": "sgm_uniform",
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
            "inputs": {"noise_seed": 707794554454994},
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
                "model": ["47", 0],
            },
            "class_type": "ModelSamplingFlux",
            "_meta": {"title": "ModelSamplingFlux"},
        },
        "44": {
            "inputs": {
                "model_type": "flux",
                "text_encoder1": "hidream/t5xxl_fp8_e4m3fn_scaled.safetensors",
                "text_encoder2": "hidream/clip_l_hidream.safetensors",
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
                "lora_name": "flux/FluxMythAn1meL1nes.safetensors",
                "lora_strength": 1,
                "model": ["45", 0],
            },
            "class_type": "NunchakuFluxLoraLoader",
            "_meta": {"title": "Nunchaku FLUX.1 LoRA Loader"},
        },
        "47": {
            "inputs": {
                "lora_name": "flux/PinkieFluxProUltraFantasia.safetensors",
                "lora_strength": 1.0000000000000002,
                "model": ["46", 0],
            },
            "class_type": "NunchakuFluxLoraLoader",
            "_meta": {"title": "Nunchaku FLUX.1 LoRA Loader"},
        },
        "48": {
            "inputs": {
                "filename_prefix": "ComfyUI",
                "filename_keys": "sampler_name, cfg, steps, %F %H-%M-%S",
                "foldername_prefix": "",
                "foldername_keys": "api",
                "delimiter": "-",
                "save_job_data": "disabled",
                "job_data_per_image": False,
                "job_custom_text": "",
                "save_metadata": False,
                "counter_digits": 4,
                "counter_position": "last",
                "one_counter_per_folder": True,
                "image_preview": True,
                "output_ext": ".webp",
                "quality": 90,
                "images": ["8", 0],
            },
            "class_type": "SaveImageExtended",
            "_meta": {"title": "💾 Save Image Extended"},
        },
    }

    logger.info(f"generate image: {prompt}")
    
    prompt_id = None
    image_filename =  None

    try:
        timeout = ClientTimeout(total=15)
        async with ClientSession(timeout=timeout) as session:
            # 发送工作流请求
            async with session.post(
                f"{endpoint}/prompt",
                json={"prompt": workflow},
                timeout=30.0,
            ) as prompt_response:
                if prompt_response.status != 200:
                    raise Exception(f"API请求失败: {prompt_response.status}")

                prompt_data = await prompt_response.json()
                prompt_id = prompt_data["prompt_id"]

                logger.info(f"prompt id: {prompt_id}")

    except Exception as e:
        logger.exception(f"生成图片时发生错误")
        return None
    
    # check image is generated
    for i in range(30):  # 30 times
        await asyncio.sleep(7)

        try:
            timeout = ClientTimeout(total=10)
            async with ClientSession(timeout=timeout) as session:
                async with session.get(f"{endpoint}/history") as history_response:
                    if history_response.status != 200:
                        logger.warning(f"获取历史记录失败: {history_response.status}")
                        continue

                    history = await history_response.json()
                    if prompt_id not in history:
                        logger.warning(f"prompt id {prompt_id} not in history")
                        continue

                    # 获取生成的图片文件名
                    outputs: dict = history[prompt_id]["outputs"]
                    if not outputs:
                        logger.warning(f"prompt id {prompt_id} not in history")
                        continue

                    try:
                        # 获取第一个输出节点的结果
                        output_key, output_data = outputs.popitem()

                        # 检查是否有图片输出
                        if "images" not in output_data:
                            logger.warning(f"输出中没有找到 'images' 字段")
                            continue

                        images = output_data["images"]
                        if not images or len(images) == 0:
                            # logger.warning(f"images 列表为空，继续等待...")
                            continue

                        image_filename = images[0]["filename"]
                        logger.info(f"image file is exported: {image_filename}")
                        break
                    except Exception as e:
                        logger.exception(f"获取图片文件名时发生错误: {e}")
                        raise Exception(f"获取图片文件名时发生错误: {e}")

        except Exception as e:
            logger.exception(f"获取图片时发生错误")
            return None

    # download image raw data
    try:
        timeout = ClientTimeout(total=30)
        async with ClientSession(timeout=timeout) as session:
            # 通过 /view 接口获取图片数据
            async with session.get(
                f"{endpoint}/view?filename={image_filename}&subfolder=api&type=output"
            ) as image_response:
                if image_response.status == 200:
                    return await image_response.read()
                raise Exception(f"获取图片失败: {image_response.status}")

    except Exception as e:
        logger.exception(f"获取图片时发生错误")
        return None