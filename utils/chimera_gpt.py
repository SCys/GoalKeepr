import asyncio
from typing import List

import aiohttp

MODEL = "kandinsky"  # -2.2?


async def image(api_key, endpoint, prompt: str, n: int = 1, size: str = "512x512") -> List[str]:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            endpoint,
            headers={"Authorization": "Bearer " + api_key},
            json={
                "prompt": prompt,
                # "n": n,
                "size": size,
                # "model": MODEL,
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
    endpoint = "https://localhost:8080/api/v1/images/generations"

    asyncio.run(image(api_key, endpoint, "1girl on the sun", "256x256"))
