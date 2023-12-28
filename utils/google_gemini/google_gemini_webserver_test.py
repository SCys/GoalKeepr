import requests

HOST= "http://localhost:5000"
TOKEN = ""

def test_text_generation_gen():
    url = f"{HOST}/api/ai/google/gemini/text_generation"
    headers = {"Content-Type": "application/json", "Token": TOKEN}

    # Test POST method
    request_body = {
        "params": {
            "text": "create a golang code for 'hello world'",
            "temperature": 0.9,
            "top_p": 1,
            "top_k": 1,
            "max_output_tokens": 2048
        }
    }
    response = requests.post(url, json=request_body, headers=headers)
    data = response.json()
    assert response.status_code == 200, f"response: {response.status_code}"
    assert "error" not in data
    assert "data" in data
    assert "text" in data["data"]
    assert "prompt" in data["data"]

    print("gen test passed!")


def test_text_generation_stat():
    url = f"{HOST}/api/ai/google/gemini/text_generation"

    # Test GET method
    response = requests.get(url)
    data = response.json()
    assert response.status_code == 200
    assert data["data"]["status"] == "ok"
    assert "total" in data["data"]
    assert "qps" in data["data"]
    
    # print total and qps
    print(data['data']['total'], data['data']['qps'])
    print("stat test passed!")

# test_text_generation_stat()
test_text_generation_gen()