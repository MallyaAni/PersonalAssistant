import requests
import json

url = "http://127.0.0.1:8000/api/v1/chat"
payload = {
    "user_id": "dev_user_001",
    "query": "Hello, what is your name?",
    "metadata": {}
}

def test_request():
    print(f"Sending request to: {url}")
    try:
        response = requests.post(url, json=payload, stream=True)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("Success! Streaming content:")
            for line in response.iter_lines():
                if line:
                    print(f"Received chunk: {line.decode('utf-8')}")
        else:
            print(f"Error Response: {response.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_request()