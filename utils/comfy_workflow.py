WORKFLOWS = {
    "flux": {
        "6": {
            "inputs": {
                "text": "",
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
                "steps": 16,
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
            "inputs": {"noise_seed": 733113376065330},
            "class_type": "RandomNoise",
            "_meta": {"title": "RandomNoise"},
        },
        "26": {
            "inputs": {"guidance": 2.1, "conditioning": ["6", 0]},
            "class_type": "FluxGuidance",
            "_meta": {"title": "FluxGuidance"},
        },
        "27": {
            "inputs": {"width": 832, "height": 1216, "batch_size": 1},
            "class_type": "EmptySD3LatentImage",
            "_meta": {"title": "EmptySD3LatentImage"},
        },
        "30": {
            "inputs": {
                "max_shift": 1.15,
                "base_shift": 0.5,
                "width": 832,
                "height": 1216,
                "model": ["47", 0],
            },
            "class_type": "ModelSamplingFlux",
            "_meta": {"title": "ModelSamplingFlux"},
        },
        "44": {
            "inputs": {
                "model_type": "flux",
                "text_encoder1": "clip-vit-large-patch14/model.safetensors",
                "text_encoder2": "t5xxl_fp8_e4m3fn_scaled.safetensors",
                "t5_min_length": 512,
                "use_4bit_t5": "disable",
                "int4_model": "none",
            },
            "class_type": "NunchakuTextEncoderLoader",
            "_meta": {"title": "Nunchaku Text Encoder Loader (Deprecated)"},
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
        "47": {
            "inputs": {
                "lora_name": "flux/aidmaHyperrealism-FLUX-v0.3-[aidmaHyperrealism].safetensors",
                "lora_strength": 0.8,
                "model": ["55", 0],
            },
            "class_type": "NunchakuFluxLoraLoader",
            "_meta": {"title": "Nunchaku FLUX LoRA Loader"},
        },
        "50": {
            "inputs": {
                "filename_prefix": "api",
                "filename_keys": "sampler_name, cfg, steps, %F_%H-%M-%S",
                "foldername_prefix": "",
                "foldername_keys": "flux",
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
                "images": ["53", 0],
            },
            "class_type": "SaveImageExtended",
            "_meta": {"title": "💾 Save Image Extended"},
        },
        "53": {
            "inputs": {"value": ["8", 0]},
            "class_type": "UnloadAllModels",
            "_meta": {"title": "UnloadAllModels"},
        },
        "55": {
            "inputs": {
                "lora_name": "flux/flux1-turbo.safetensors",
                "lora_strength": 0.6,
                "model": ["45", 0],
            },
            "class_type": "NunchakuFluxLoraLoader",
            "_meta": {"title": "Nunchaku FLUX LoRA Loader"},
        },
    },
    "zimage": {
        "3": {
            "inputs": {
                "seed": 386928045301319,
                "steps": 8,
                "cfg": 1,
                "sampler_name": "er_sde",
                "scheduler": "simple",
                "denoise": 1,
                "model": ["11", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["60", 0],
            },
            "class_type": "KSampler",
            "_meta": {"title": "KSampler"},
        },
        "6": {
            "inputs": {
                "text": "",
                "clip": ["82", 0],
            },
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "CLIP Text Encode (Positive Prompt)"},
        },
        "7": {
            "inputs": {"text": "低质量", "clip": ["82", 0]},
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "CLIP Text Encode (Negative Prompt)"},
        },
        "8": {"inputs": {"samples": ["3", 0], "vae": ["17", 0]}, "class_type": "VAEDecode", "_meta": {"title": "VAE Decode"}},
        "11": {
            "inputs": {"shift": 3, "sampling": "flow", "model": ["52", 0]},
            "class_type": "ModelSamplingAuraFlow",
            "_meta": {"title": "ModelSamplingAuraFlow"},
        },
        "17": {"inputs": {"vae_name": "ae.safetensors"}, "class_type": "VAELoader", "_meta": {"title": "Load VAE"}},
        "29": {
            "inputs": {
                "megapixel": "0.6",
                "aspect_ratio": "9:16 (Slim Vertical)",
                "divisible_by": "64",
                "custom_ratio": False,
                "custom_aspect_ratio": "1:1",
            },
            "class_type": "FluxResolutionNode",
            "_meta": {"title": "Flux Resolution Calc"},
        },
        "37": {
            "inputs": {
                "filename": "%time_%basemodelname_%seed",
                "path": "zimage",
                "extension": "webp",
                "lossless_webp": False,
                "quality_jpeg_or_webp": 85,
                "optimize_png": False,
                "embed_workflow": True,
                "save_workflow_as_json": False,
                "counter": 0,
                "time_format": "%Y-%m-%d-%H%M%S",
                "show_preview": True,
                "images": ["8", 0],
            },
            "class_type": "Image Saver Simple",
            "_meta": {"title": "Image Saver Simple"},
        },
        "52": {
            "inputs": {
                "model_name": "z_image_turbo-Q8_0.gguf",
                "extra_model_name": "none",
                "dequant_dtype": "default",
                "patch_dtype": "default",
                "patch_on_device": True,
                "enable_fp16_accumulation": False,
                "attention_override": "sageattn",
            },
            "class_type": "GGUFLoaderKJ",
            "_meta": {"title": "GGUFLoaderKJ"},
        },
        "60": {
            "inputs": {"width": ["29", 0], "height": ["29", 1], "batch_size": 1},
            "class_type": "EmptySD3LatentImage",
            "_meta": {"title": "EmptySD3LatentImage"},
        },
        "82": {
            "inputs": {"clip_name": "zimage-engineer-v6-dhq-Q4_K_M.gguf", "type": "stable_diffusion"},
            "class_type": "CLIPLoaderGGUF",
            "_meta": {"title": "CLIPLoader (GGUF)"},
        },
    },
    "krea": {
        "3": {
            "inputs": {
                "seed": 94145881518006,
                "steps": 8,
                "cfg": 1,
                "sampler_name": "er_sde",
                "scheduler": "simple",
                "denoise": 1,
                "model": ["93", 0],
                "positive": ["81", 0],
                "negative": ["7", 0],
                "latent_image": ["60", 0],
            },
            "class_type": "KSampler",
            "_meta": {"title": "KSampler"},
        },
        "6": {
            "inputs": {"text": "", "clip": ["33", 0]},
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "CLIP Text Encode (Positive Prompt)"},
        },
        "7": {
            "inputs": {"text": "", "clip": ["33", 0]},
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "CLIP Text Encode (Negative Prompt)"},
        },
        "8": {
            "inputs": {"samples": ["3", 0], "vae": ["17", 0]},
            "class_type": "VAEDecode",
            "_meta": {"title": "VAE Decode"},
        },
        "17": {
            "inputs": {"vae_name": "qwen_image_vae.safetensors"},
            "class_type": "VAELoader",
            "_meta": {"title": "Load VAE"},
        },
        "29": {
            "inputs": {
                "megapixel": "0.6",
                "aspect_ratio": "9:16 (Slim Vertical)",
                "divisible_by": "64",
                "custom_ratio": False,
                "custom_aspect_ratio": "1:1",
            },
            "class_type": "FluxResolutionNode",
            "_meta": {"title": "Flux Resolution Calc"},
        },
        "33": {
            "inputs": {
                "clip_name": "Huihui-Qwen3-VL-4B-Instruct-abliterated-fp8_scaled.safetensors",
                "type": "krea2",
                "device": "default",
            },
            "class_type": "CLIPLoader",
            "_meta": {"title": "Load CLIP"},
        },
        "37": {
            "inputs": {
                "filename": "%time_%basemodelname_%seed",
                "path": "krea_turbo",
                "extension": "webp",
                "lossless_webp": False,
                "quality_jpeg_or_webp": 85,
                "optimize_png": False,
                "embed_workflow": True,
                "save_workflow_as_json": False,
                "counter": 0,
                "time_format": "%Y-%m-%d-%H%M%S",
                "show_preview": True,
                "images": ["8", 0],
            },
            "class_type": "Image Saver Simple",
            "_meta": {"title": "Image Saver Simple"},
        },
        "60": {
            "inputs": {"width": ["29", 0], "height": ["29", 1], "batch_size": 1},
            "class_type": "EmptySD3LatentImage",
            "_meta": {"title": "EmptySD3LatentImage"},
        },
        "81": {
            "inputs": {"value": ["6", 0], "model": ["33", 0]},
            "class_type": "UnloadModel",
            "_meta": {"title": "UnloadModel"},
        },
        "93": {
            "inputs": {"ckpt_name": "krea2_darkbeast_3.0_int8.safetensors"},
            "class_type": "CheckpointLoaderSimple",
            "_meta": {"title": "Load Checkpoint"},
        },
    },
    "qwen": {
        "16": {
            "inputs": {
                "width": [
                    "17",
                    0
                ],
                "height": [
                    "17",
                    1
                ],
                "batch_size": 1
            },
            "class_type": "EmptySD3LatentImage",
            "_meta": {
                "title": "EmptySD3LatentImage"
            }
        },
        "17": {
            "inputs": {
                "megapixel": "0.6",
                "aspect_ratio": "9:16 (Slim Vertical)",
                "divisible_by": "64",
                "custom_ratio": False,
                "custom_aspect_ratio": "1:1"
            },
            "class_type": "FluxResolutionNode",
            "_meta": {
                "title": "Flux Resolution Calc"
            }
        },
        "33": {
            "inputs": {
                "filename": "%time_%basemodelname_%seed",
                "path": "qwen_image",
                "extension": "webp",
                "lossless_webp": False,
                "quality_jpeg_or_webp": 85,
                "optimize_png": False,
                "embed_workflow": True,
                "save_workflow_as_json": False,
                "counter": 0,
                "time_format": "%Y-%m-%d-%H%M%S",
                "show_preview": True,
                "images": [
                    "15:7",
                    0
                ]
            },
            "class_type": "Image Saver Simple",
            "_meta": {
                "title": "Image Saver Simple"
            }
        },
        "15:3": {
            "inputs": {
                "vae_name": "qwen_image_2.1_vae_bf16.safetensors"
            },
            "class_type": "VAELoader",
            "_meta": {
                "title": "Load VAE"
            }
        },
        "15:4": {
            "inputs": {
                "prompt": "创作一幅细节丰富、格调高雅的水彩肖像画，描绘一位美丽的东亚少女；画面结合了写实的全身坐姿肖像与背景中一幅巨大的单色艺术面部特写。\n\n主体：\n一位优雅的东亚少女，双腿轻叠，姿态优美地坐在地面上。她拥有一头浓密的乌黑长发，发型随性自然，几缕柔和的发丝轻拂脸庞。面部刻画写实细腻，呈现出杏仁状的传神双眸、轮廓自然的眉毛、精致的鼻梁、柔和的双唇、细腻温暖的肤色，以及望向右侧时那份宁静温婉的神情。她正带着一种非常含蓄、恬静的微笑，嘴角微微上扬。最引人注目的是，在她微笑时，嘴角两侧（脸颊下方）各浮现出一个明显的酒窝。 这两个酒窝让她的笑容显得格外甜美、生动，增加了一种亲切和俏皮的感觉。\n\n她身穿一件优雅的薰衣草灰修身长袖上衣，胸部高耸，搭配一条象牙白色的飘逸长裙（裙长及踝），面料柔软轻盈，呈现出自然的褶皱与真实的垂坠感。她佩戴着精致的珍珠饰品：纤细的珍珠项链、小巧的垂坠珍珠耳环以及优雅的珍珠手链。脚穿裸米色高跟鞋，使整体造型更显完美。\n\n姿态：\n她优雅地坐着，双手自然交叠放在一侧膝盖上，姿态放松；双肩微微转向右侧，神情宁静地望向远方。画面呈现全身形象，包括鞋履。\n\n背景肖像：\n在她身后，绘制一幅同一位女性面部的巨大艺术黑白特写肖像，占据背景右上角的大部分区域。面部特征、发型、五官（眼、鼻、唇）、下颌线及整体外貌均需与前景中的女性保持一致。背景肖像应呈现出柔和的石墨与水彩混合画风，色调略显淡雅且富有氛围感，与水彩背景自然融合。\n\n艺术风格：\n奢华杂志风格的水彩肖像，精致的时装插画；写实水彩画法结合细腻的铅笔或墨线细节；笔触柔和，带有微妙的晕染效果与透明水彩渲染；采用冷压纹理纸质感；面部细节精致，保留优雅的艺术化笔触瑕疵，并点缀以轻柔的墨点与水彩渍迹。\n\n色调：\n柔和的单色灰、炭黑、象牙白、低饱和度的薰衣草紫、微妙的米色以及温暖的肤色。整体低饱和度，格调高雅且经典耐看。\n\n光影：\n柔和的漫射摄影棚光线，面部与衣物上有细腻的高光，阴影柔和，呈现出明亮的水彩画氛围，无生硬的明暗对比。\n\n构图：\n竖构图肖像，前景中的女性位于画面中心偏左位置，背景右上角延伸出一张巨大的单色面部形象，留白平衡和谐，边缘点缀着艺术感的水彩泼溅效果，呈现高端时尚杂志的视觉美感。\n\n画质：\n细节极致丰",
                "negative_prompt": "",
                "resolution": 1632,
                "clip": [
                    "15:29",
                    1
                ]
            },
            "class_type": "TextEncodeQwenImage21",
            "_meta": {
                "title": "Text Encode Qwen Image 2.1"
            }
        },
        "15:6": {
            "inputs": {
                "seed": 42,
                "steps": 8,
                "cfg": 1,
                "sampler_name": "er_sde",
                "scheduler": "simple",
                "denoise": 1,
                "model": [
                    "15:37",
                    0
                ],
                "positive": [
                    "15:4",
                    0
                ],
                "negative": [
                    "15:4",
                    1
                ],
                "latent_image": [
                    "16",
                    0
                ]
            },
            "class_type": "KSampler",
            "_meta": {
                "title": "KSampler"
            }
        },
        "15:7": {
            "inputs": {
                "samples": [
                    "15:6",
                    0
                ],
                "vae": [
                    "15:3",
                    0
                ]
            },
            "class_type": "VAEDecode",
            "_meta": {
                "title": "VAE Decode"
            }
        },
        "15:18": {
            "inputs": {
                "clip_name": "qwen3vl_8b_heretic-Q4_K_M.gguf",
                "type": "qwen_image"
            },
            "class_type": "CLIPLoaderGGUF",
            "_meta": {
                "title": "CLIPLoader (GGUF)"
            }
        },
        "15:29": {
            "inputs": {
                "lora_name": "p_qwen_image_2.1_8step_v0.1.safetensors",
                "strength_model": 1,
                "strength_clip": 1,
                "model": [
                    "15:30",
                    0
                ],
                "clip": [
                    "15:18",
                    0
                ]
            },
            "class_type": "LoraLoader",
            "_meta": {
                "title": "Load LoRA (Model and CLIP)"
            }
        },
        "15:30": {
            "inputs": {
                "model_name": "NoctQ_V4_int8_convrot.safetensors",
                "weight_dtype": "default",
                "compute_dtype": "default",
                "patch_cublaslinear": True,
                "sage_attention": "auto",
                "enable_fp16_accumulation": True
            },
            "class_type": "DiffusionModelLoaderKJ",
            "_meta": {
                "title": "Diffusion Model Loader KJ"
            }
        },
        "15:37": {
            "inputs": {
                "device": "auto",
                "dtype": "int8",
                "model": [
                    "15:29",
                    0
                ]
            },
            "class_type": "QwenImage21Cache",
            "_meta": {
                "title": "Qwen Image 2.1 Cache"
            }
        }
    },
}
