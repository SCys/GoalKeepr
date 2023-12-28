from flask import Flask, request, jsonify
from loguru import logger
import google.generativeai as genai
from configparser import ConfigParser
from typing import Optional


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
"""


app = Flask(__name__)

config = ConfigParser(
    {
        "token": "",  # Google Gemini Pro token
        "token_client": "",  # 要求请求者提供的token
        "host": "0.0.0.0",
        "port": 5000,
    }
)

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
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_LOW_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_LOW_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_LOW_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_LOW_AND_ABOVE"},
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

        return jsonify({"data": {"status": "ok"}})
    elif request.method != "POST":
        logger.warning(f"{request.method} method not allowed")
        return jsonify({"error": {"code": 1, "message": f"{request.method} method not allowed"}})

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
    candidates = resp.candidates

    logger.info(f"text generation request prompt {text} text {resp.text} feedback {feedback} candidates {candidates}")
    return jsonify({"data": {"text": resp.text, "prompt": text}})


if __name__ == "__main__":
    config.read("main.ini")

    setup_google_gemini()

    app.run(debug=True, host=config["DEFAULT"]["host"], port=config["DEFAULT"]["port"])
