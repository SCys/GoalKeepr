import time
from configparser import ConfigParser
from typing import Optional

import google.generativeai as genai
import redis
from flask import Flask, jsonify, request
from loguru import logger

"""
request/response body is json

Request Body Example:

```json
{
    "params": {
        // anything ...
    }
}
```

Response Body Example:

```json5
{
    "error": {
        "code": 0,
        "message": "",
    },
    "data": {
        // anything ...
    }
}
```

statistic in redis, text_generation prefix is statistic:ai:google:gemini

"""

"""
HARM_PROBABILITY_UNSPECIFIED (0):
    Probability is unspecified.
NEGLIGIBLE (1):
    Content has a negligible chance of being
    unsafe.
LOW (2):
    Content has a low chance of being unsafe.
MEDIUM (3):
    Content has a medium chance of being unsafe.
HIGH (4):
    Content has a high chance of being unsafe.
"""
HarmProbability = {
    0: "HARM_PROBABILITY_UNSPECIFIED",
    1: "NEGLIGIBLE",
    2: "LOW",
    3: "MEDIUM",
    4: "HIGH",
}

"""
HARM_CATEGORY_UNSPECIFIED (0):
    Category is unspecified.
HARM_CATEGORY_DEROGATORY (1):
    Negative or harmful comments targeting
    identity and/or protected attribute.
HARM_CATEGORY_TOXICITY (2):
    Content that is rude, disrepspectful, or
    profane.
HARM_CATEGORY_VIOLENCE (3):
    Describes scenarios depictng violence against
    an individual or group, or general descriptions
    of gore.
HARM_CATEGORY_SEXUAL (4):
    Contains references to sexual acts or other
    lewd content.
HARM_CATEGORY_MEDICAL (5):
    Promotes unchecked medical advice.
HARM_CATEGORY_DANGEROUS (6):
    Dangerous content that promotes, facilitates,
    or encourages harmful acts.
HARM_CATEGORY_HARASSMENT (7):
    Harasment content.
HARM_CATEGORY_HATE_SPEECH (8):
    Hate speech and content.
HARM_CATEGORY_SEXUALLY_EXPLICIT (9):
    Sexually explicit content.
HARM_CATEGORY_DANGEROUS_CONTENT (10):
    Dangerous content.
"""
HarmCategory = {
    0: "Category is unspecified.",
    1: "Negative or harmful comments targeting identity and/or protected attribute.",
    2: "Content that is rude, disrepspectful, or profane.",
    3: "Describes scenarios depictng violence against an individual or group, or general descriptions of gore.",
    4: "Contains references to sexual acts or other lewd content.",
    5: "Promotes unchecked medical advice.",
    6: "Dangerous content that promotes, facilitates, or encourages harmful acts.",
    7: "Harasment content.",
    8: "Hate speech and content.",
    9: "Sexually explicit content.",
    10: "Dangerous content.",
}

RDB_KEY = "statistic:ai:google:gemini"

app = Flask(__name__)

config = ConfigParser(
    {
        "token": "",  # Google Gemini Pro token
        "token_client": "",  # 要求请求者提供的token
        "host": "0.0.0.0",
        "port": 5000,
        "redis": "redis://localhost:6379/0",
    }
)

rdb: Optional[redis.Redis] = None

model_txt: Optional["genai.GenerativeModel"] = None
model_img: Optional["genai.GenerativeModel"] = None


safety_settings = [
    # https://ai.google.dev/docs/safety_setting_gemini
    # freedom !
    # {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    # {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    # {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    # {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    # default
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
]


def setup_google_gemini():
    """Setup Google Gemini Pro"""

    global model_txt, model_img, config

    try:
        token = config["DEFAULT"]["token"]
        if not token:
            logger.error("google gemini pro token is missing")
            return

        genai.configure(api_key=token)

        # list models
        # for model in genai.list_models():
        #     logger.info(f"Google Gemini Pro model: {model.name}")

        model_txt = genai.GenerativeModel("gemini-pro")
        model_img = genai.GenerativeModel("gemini-pro-vision")

        logger.info("Google Gemini Pro is setup")
    except:
        logger.exception("setup genai failed")


def setup_redis():
    global rdb, config

    rdb = redis.from_url(config["DEFAULT"]["redis"])
    logger.info(f"redis is setup")


def check_token():
    """检查请求是否合法"""
    token = config["DEFAULT"]["token_client"]
    if not token:
        logger.warning(f"token_client is None, ignored")
        return True

    if token != request.headers.get("Token"):
        logger.warning(f"token not match, ignored")
        return False

    return True


# Rate limiter decorator
def rate_limiter():
    global rdb

    if not rdb:
        logger.warning("redis is None, ignored")
        return True

    # GET QPM
    qpm = rdb.hget(RDB_KEY, "qpm")
    if not qpm or not qpm.isdigit():
        logger.warning(f"qpm is None, ignored")

        # setup default
        qpm = 60
        rdb.hset(RDB_KEY, "qpm", qpm)
    else:
        qpm = int(qpm)

    # 计算总共有多少个Key存货，因为每个Key TTL为61秒，所以这里的数量应该是大于等于60的
    keys = rdb.keys(f"{RDB_KEY}:counter:*")
    total = len(keys)
    if total >= qpm:
        logger.warning(f"rate limit exceeded, total {total} >= {qpm}, ignored")
        return False

    return True


@app.route("/api/ai/google/gemini/text_generation", methods=["GET", "POST"])
def text_generation():
    """
    Get Method 用来检查是否正常运行
    Post Method 用来处理请求

    Request Body Example:

    ```json5
    {
        "params": {
            "text": "Hello world!",

            // default settings
            "temperature": 0.9,
            "top_p": 1,
            "top_k": 1,
            "max_output_tokens": 2048,
        }
    }
    ```

    Response Body Example:

    ```json5
    {
        "error": {
            "code": 0,
            "message": "",
        },
        "data": {
            "feedback": ...,
            "text": "Hello world!",
        }
    }
    ```

    """
    if request.method == "GET":
        if model_txt is None:
            logger.warning(f"model is None, ignored")
            return jsonify({"error": {"code": 1, "message": "model is None, ignored"}})

        if not rdb:
            return jsonify({"data": {"status": "ok"}})

        total = rdb.get(f"{RDB_KEY}:text_generation:total")
        if total is None:
            total = 0
            rdb.set(f"{RDB_KEY}:text_generation:total", total)
        else:
            total = int(total)

        return jsonify(
            {
                "data": {
                    "status": "ok",
                    "total": total,
                    "qps": len(rdb.keys(f"{RDB_KEY}:counter:*")),
                }
            }
        )

    elif request.method != "POST":
        logger.warning(f"{request.method} method not allowed")
        return jsonify({"error": {"code": 1, "message": f"{request.method} method not allowed"}})

    if not check_token():
        logger.warning(f"permission denied, request from {request.remote_addr}")
        return jsonify({"error": {"code": 1, "message": "token not match, ignored"}})

    if not rate_limiter():
        return jsonify({"error": {"code": 1, "message": "rate limit exceeded, ignored"}})

    request_body = request.get_json()
    if not request_body:
        logger.warning(f"request body is None, ignored")
        return jsonify({"error": {"code": 1, "message": "request body is None, ignored"}})

    params = request_body.get("params", {})
    if not params:
        logger.warning(f"params is None, ignored")
        return jsonify({"error": {"code": 1, "message": "params is None, ignored"}})

    text = params.get("text")
    if not text:
        logger.warning(f"text is None, ignored")
        return jsonify({"error": {"code": 1, "message": "text is None, ignored"}})

    temperature = params.get("temperature", 0.9)
    top_p = params.get("top_p", 1)
    top_k = params.get("top_k", 1)
    max_output_tokens = params.get("max_output_tokens", 2048)

    resp = model_txt.generate_content(
        text,
        generation_config={
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "max_output_tokens": max_output_tokens,
        },
        safety_settings=safety_settings,
    )

    feedback = resp.prompt_feedback

    # 记录请求数量和请求QPM到Redis内
    if rdb:
        try:
            rdb.incr(f"{RDB_KEY}:text_generation:total")  # Increment request count

            # 设置TTL为61秒
            rdb.set(f"{RDB_KEY}:counter:{int(time.time())}", 1, ex=61)
        except Exception as e:
            logger.error(f"incr request count failed: {e}")

    try:
        if resp.candidates:
            output = resp.text
        else:
            output = "empty response from google gemini pro"

            # block by google
            if feedback:
                output = "google ai reject this request"
                for rate in feedback.safety_ratings:
                    # only block by high
                    if rate.probability == rate.HarmProbability.NEGLIGIBLE:
                        continue

                    category = HarmCategory.get(rate.category, "UNKNOWN")
                    probability = HarmProbability.get(rate.probability, "UNKNOWN")
                    blocked = "is blocked" if rate.probability == rate.HarmProbability.HIGH else "is ignored"

                    output += f"\n\r{category}\nlevel is {probability}, {blocked}"

    except ValueError as e:
        output = str(e)

        logger.warning(f"output text is invalid: {e}")
        return jsonify({"data": {"text": output, "prompt": text}})

    logger.info(f"text generation request prompt {text!r} text {output!r}")
    return jsonify({"data": {"text": output, "prompt": text}})


if __name__ == "__main__":
    config.read("main.ini")

    setup_redis()
    setup_google_gemini()

    app.run(debug=True, host=config["DEFAULT"]["host"], port=config["DEFAULT"]["port"])
