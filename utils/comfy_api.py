import aiohttp
import asyncio
from typing import Tuple
import base64
import os

# ComfyUI API 端点
API_URL = "http://10.1.3.10:7860"

async def generate_image(prompt: str, size: str = "512x512", steps: int = 20, cfg: float = 1.0) -> str:
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
        "last_node_id": 9,
        "last_link_id": 12,
        "nodes": [
            {
                "id": 4,
                "type": "CheckpointLoaderSimple",
                "pos": [
                    -77,
                    225
                ],
                "size": {
                    "0": 315,
                    "1": 98
                },
                "flags": {},
                "order": 0,
                "mode": 0,
                "outputs": [
                    {
                        "name": "MODEL",
                        "type": "MODEL",
                        "links": [
                            3
                        ],
                        "slot_index": 0
                    },
                    {
                        "name": "CLIP",
                        "type": "CLIP",
                        "links": [
                            4,
                            5
                        ],
                        "slot_index": 1
                    },
                    {
                        "name": "VAE",
                        "type": "VAE",
                        "links": [
                            6
                        ],
                        "slot_index": 2
                    }
                ],
                "properties": {
                    "Node name for S&R": "CheckpointLoaderSimple"
                },
                "widgets_values": [
                    # "v1-5-pruned.ckpt"
                    "flux1-schnell-fp8.safetensors"
                ]
            },
            {
                "id": 5,
                "type": "EmptyLatentImage",
                "pos": [
                    -77,
                    379
                ],
                "size": {
                    "0": 315,
                    "1": 106
                },
                "flags": {},
                "order": 1,
                "mode": 0,
                "outputs": [
                    {
                        "name": "LATENT",
                        "type": "LATENT",
                        "links": [
                            2
                        ],
                        "slot_index": 0
                    }
                ],
                "properties": {
                    "Node name for S&R": "EmptyLatentImage"
                },
                "widgets_values": [
                    width,
                    height,
                    1
                ]
            },
            {
                "id": 6,
                "type": "CLIPTextEncode",
                "pos": [
                    315,
                    225
                ],
                "size": {
                    "0": 422.84503173828125,
                    "1": 164.31304931640625
                },
                "flags": {},
                "order": 2,
                "mode": 0,
                "inputs": [
                    {
                        "name": "clip",
                        "type": "CLIP",
                        "link": 4
                    }
                ],
                "outputs": [
                    {
                        "name": "CONDITIONING",
                        "type": "CONDITIONING",
                        "links": [
                            7
                        ],
                        "slot_index": 0
                    }
                ],
                "properties": {
                    "Node name for S&R": "CLIPTextEncode"
                },
                "widgets_values": [
                    prompt
                ]
            },
            {
                "id": 7,
                "type": "CLIPTextEncode",
                "pos": [
                    315,
                    379
                ],
                "size": {
                    "0": 425.27801513671875,
                    "1": 180.6060791015625
                },
                "flags": {},
                "order": 3,
                "mode": 0,
                "inputs": [
                    {
                        "name": "clip",
                        "type": "CLIP",
                        "link": 5
                    }
                ],
                "outputs": [
                    {
                        "name": "CONDITIONING",
                        "type": "CONDITIONING",
                        "links": [
                            8
                        ],
                        "slot_index": 0
                    }
                ],
                "properties": {
                    "Node name for S&R": "CLIPTextEncode"
                },
                "widgets_values": [
                    "bad, deformed"
                ]
            },
            {
                "id": 3,
                "type": "KSampler",
                "pos": [
                    315,
                    533
                ],
                "size": {
                    "0": 315,
                    "1": 262
                },
                "flags": {},
                "order": 4,
                "mode": 0,
                "inputs": [
                    {
                        "name": "model",
                        "type": "MODEL",
                        "link": 3
                    },
                    {
                        "name": "positive",
                        "type": "CONDITIONING",
                        "link": 7
                    },
                    {
                        "name": "negative",
                        "type": "CONDITIONING",
                        "link": 8
                    },
                    {
                        "name": "latent_image",
                        "type": "LATENT",
                        "link": 2
                    }
                ],
                "outputs": [
                    {
                        "name": "LATENT",
                        "type": "LATENT",
                        "links": [
                            9
                        ],
                        "slot_index": 0
                    }
                ],
                "properties": {
                    "Node name for S&R": "KSampler"
                },
                "widgets_values": [
                    8566,
                    "euler",
                    steps,
                    cfg,
                    1,
                    "normal"
                ]
            },
            {
                "id": 8,
                "type": "VAEDecode",
                "pos": [
                    687,
                    533
                ],
                "size": {
                    "0": 210,
                    "1": 46
                },
                "flags": {},
                "order": 5,
                "mode": 0,
                "inputs": [
                    {
                        "name": "samples",
                        "type": "LATENT",
                        "link": 9
                    },
                    {
                        "name": "vae",
                        "type": "VAE",
                        "link": 6
                    }
                ],
                "outputs": [
                    {
                        "name": "IMAGE",
                        "type": "IMAGE",
                        "links": [
                            10
                        ],
                        "slot_index": 0
                    }
                ],
                "properties": {
                    "Node name for S&R": "VAEDecode"
                }
            },
            {
                "id": 9,
                "type": "SaveImage",
                "pos": [
                    687,
                    625
                ],
                "size": {
                    "0": 210,
                    "1": 58
                },
                "flags": {},
                "order": 6,
                "mode": 0,
                "inputs": [
                    {
                        "name": "images",
                        "type": "IMAGE",
                        "link": 10
                    }
                ],
                "properties": {
                    "Node name for S&R": "SaveImage"
                },
                "widgets_values": [
                    "ComfyUI"
                ]
            }
        ],
        "links": [
            [2, 5, 0, 3, 3, "LATENT"],
            [3, 4, 0, 3, 0, "MODEL"],
            [4, 4, 1, 6, 0, "CLIP"],
            [5, 4, 1, 7, 0, "CLIP"],
            [6, 4, 2, 8, 1, "VAE"],
            [7, 6, 0, 3, 1, "CONDITIONING"],
            [8, 7, 0, 3, 2, "CONDITIONING"],
            [9, 3, 0, 8, 0, "LATENT"],
            [10, 8, 0, 9, 0, "IMAGE"]
        ]
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
