import aiohttp
import asyncio
from typing import Tuple
import base64
import os

# ComfyUI API 端点
API_URL = "http://10.1.3.10:7860"

async def generate_image(prompt: str, size: str = "512x512", steps: int = 20, cfg: float = 7.0) -> str:
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
        width, height = map(int, size.lower().split('x'))
    except ValueError:
        raise ValueError("尺寸格式错误，应为 'widthxheight'，例如 '512x512'")
    
    # Flux workflow
    workflow = {
        "4": {  # CheckpointLoaderSimple
            "inputs": {
                "ckpt_name": "flux1-schnell-fp8.safetensors"
            },
            "class_type": "CheckpointLoaderSimple"
        },
        "5": {  # EmptyLatentImage
            "inputs": {
                "width": width,
                "height": height,
                "batch_size": 1
            },
            "class_type": "EmptyLatentImage"
        },
        "6": {  # CLIPTextEncode - Positive
            "inputs": {
                "text": prompt,
                "clip": ["4", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "7": {  # CLIPTextEncode - Negative
            "inputs": {
                "text": "bad, deformed",
                "clip": ["4", 1]
            },
            "class_type": "CLIPTextEncode"
        },
        "3": {  # KSampler
            "inputs": {
                "seed": 8566,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0]
            },
            "class_type": "KSampler"
        },
        "8": {  # VAEDecode
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            },
            "class_type": "VAEDecode"
        },
        "9": {  # SaveImage
            "inputs": {
                "images": ["8", 0],
                "filename_prefix": "ComfyUI"
            },
            "class_type": "SaveImage"
        }
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # 发送工作流请求
            async with session.post(f"{API_URL}/prompt", json={"prompt": workflow}) as prompt_response:
                if prompt_response.status != 200:
                    raise Exception(f"API请求失败: {prompt_response.status}")
                
                prompt_data = await prompt_response.json()
                prompt_id = prompt_data["prompt_id"]
                
                # 等待图片生成完成
                while True:
                    async with session.get(f"{API_URL}/history") as history_response:
                        if history_response.status == 200:
                            history = await history_response.json()
                            if prompt_id in history and len(history[prompt_id]["outputs"]) > 0:
                                # 获取生成的图片文件名
                                image_filename = history[prompt_id]["outputs"]["9"]["images"][0]["filename"]
                                
                                # 通过 /view 接口获取图片数据
                                async with session.get(f"{API_URL}/view?filename={image_filename}") as image_response:
                                    if image_response.status == 200:
                                        image_data = await image_response.read()
                                        base64_data = base64.b64encode(image_data).decode('utf-8')
                                        return base64_data
                                    else:
                                        raise Exception(f"获取图片失败: {image_response.status}")
                    await asyncio.sleep(1)
            
    except Exception as e:
        raise Exception(f"生成图片时发生错误: {str(e)}")
