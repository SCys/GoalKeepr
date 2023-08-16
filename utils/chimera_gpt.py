import asyncio
from typing import List

import aiohttp

"""
| Model ID                | Owner                  | Max Objects | Endpoints                                                     | Limits                  | Public |
|-------------------------|------------------------|-------------|--------------------------------------------------------------|-------------------------|--------|
| sdxl                    | StabilityAI            | 5           | /api/v1/images/generations                                   | 6/minute, 300/day       | true   |
| kandinsky-2.2           | Sberbank               | 10          | /api/v1/images/generations                                   | 10/minute, 1500/day     | true   |
| kandinsky-2             | Sberbank               | 10          | /api/v1/images/generations                                   | 10/minute, 1500/day     | true   |
| dall-e                  | OpenAI                 | 10          | /api/v1/images/generations                                   | 10/minute, 1500/day     | true   |
| stable-diffusion-2.1    | StabilityAI            | 10          | /api/v1/images/generations                                   | 10/minute, 1000/day     | true   |
| stable-diffusion-1.5    | StabilityAI            | 10          | /api/v1/images/generations                                   | 10/minute, 1000/day     | true   |
| deepfloyd-if            | DeepFloyd              | 4           | /api/v1/images/generations                                   | 10/minute, 1000/day     | true   |
| material-diffusion      | Yes                    | 8           | /api/v1/images/generations                                   | 10/minute, 1000/day     | true   |
| midjourney              | Midjourney             | 1           | /api/v1/images/generations                                   | 2/minute, 500/day       | false  |
"""


DEFAULT_MODEL = "sdxl"
SUPPORT_MODELS = {
    "sdxl": {
        "owner": "StabilityAI",
        "max_objects": 5,
        "limits": [6, 300],
    },
    "kandinsky-2.2": {
        "owner": "Sberbank",
        "max_objects": 10,
        "limits": [10, 1500],
    },
    "kandinsky-2": {
        "owner": "Sberbank",
        "max_objects": 10,
        "limits": [10, 1500],
    },
    "dall-e": {
        "owner": "OpenAI",
        "max_objects": 10,
        "limits": [10, 1500],
    },
    "stable-diffusion-2.1": {
        "owner": "StabilityAI",
        "max_objects": 10,
        "limits": [10, 1000],
    },
    "stable-diffusion-1.5": {
        "owner": "StabilityAI",
        "max_objects": 10,
        "limits": [10, 1000],
    },
    "deepfloyd-if": {
        "owner": "DeepFloyd",
        "max_objects": 4,
        "limits": [10, 1000],
    },
    "material-diffusion": {
        "owner": "Yes",
        "max_objects": 8,
        "limits": [10, 1000],
    },
    # private model
    # "midjourney": {
    #     "owner": "Midjourney",
    #     "max_objects": 1,
    #     "limits": [2, 500],
    # },
}


async def image(api_key, endpoint, model: str | None, prompt: str, n: int = 1, size: str = "512x512") -> List[str]:
    if model not in SUPPORT_MODELS:
        model = DEFAULT_MODEL

    async with aiohttp.ClientSession(
        # 50s timeout
        timeout=aiohttp.ClientTimeout(total=60),
    ) as session:
        async with session.post(
            f"{endpoint}images/generations",
            headers={"Authorization": "Bearer " + api_key},
            json={
                "prompt": prompt,
                "n": n,
                "size": size,
                "model": model,
                "response_format": "url",
            },
        ) as response:
            resp = await response.json()
            if "data" in resp:
                data = resp["data"]
                print(data)
                return [i["url"] for i in data]

            if "error" in resp:
                message = resp["error"]["message"]
                type = resp["error"]["type"]

                raise Exception(f"Error: {type}.{message}")

            # unknown error ?
            raise Exception(f"Unknown error: {resp}")


# async def chat(prompt: str, model: str = "gpt-3"):
#     response = await openai.Completion.create(
#         model=model,
#         messages=[
#             # {'role': 'system', 'content': "You are a enginer." },
#             {"role": "user", "content": prompt}
#         ],
#     )
#     return response["choices"][0]["text"]


if __name__ == "__main__":
    api_key = ""
    endpoint = "https://localhost/v1/"

    asyncio.run(image(api_key, endpoint, None, "1girl on the sun", 1, "512x512"))
