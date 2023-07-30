import asyncio
import openai
from typing import List


async def image(prompt: str, n: int = 1, size: str = "512x512") -> List[str]:
    response = openai.Image.create(prompt=prompt, n=n, size=size)
    return [i["url"] for i in response["data"]]


async def chat(prompt: str, model: str = "gpt-3"):
    response = await openai.Completion.create(
        model=model,
        messages=[
            # {'role': 'system', 'content': "You are a enginer." },
            {"role": "user", "content": prompt}
        ],
    )
    return response["choices"][0]["text"]


if __name__ == "__main__":
    openai.api_key = "API KEY"
    openai.api_base = "https://chimeragpt.adventblocks.cc/api/v1"
    asyncio.run(image("1girl on the sun", "256x256"))
