import requests

HOST= "http://10.1.3.26:5000"

def test_text_generation():
    url = f"{HOST}/api/ai/google/gemini/text_generation"
    headers = {"Content-Type": "application/json"}

    # Test GET method
    response = requests.get(url)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"

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
    assert response.status_code == 200, f"response: {response.status_code}"
    assert "error" not in response.json()
    assert "data" in response.json()
    assert "text" in response.json()["data"]
    assert "prompt" in response.json()["data"]

    print("All tests passed!")

test_text_generation()