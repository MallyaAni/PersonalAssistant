import json
from typing import Any
from uuid import uuid4

import httpx

url = "http://127.0.0.1:8000/api/v1/chat"
payload = {
    "user_id": "dev_user_001",
    "conversation_id": str(uuid4()),
    "query": "Hello, what is your name?",
    "metadata": {},
}


def main() -> int:
    print(f"Sending request to: {url}")
    try:
        with httpx.stream("POST", url, json=payload, timeout=120) as response:
            print(f"Status Code: {response.status_code}")
            print(f"Content-Type: {response.headers.get('content-type')}")
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", ""):
                raise RuntimeError("response is not an SSE stream")

            event_name: str | None = None
            event_data: dict[str, Any] = {}
            saw_start = False
            saw_done = False
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event_name = line.removeprefix("event:").strip()
                elif line.startswith("data:"):
                    event_data = json.loads(line.removeprefix("data:").strip())
                elif not line and event_name:
                    print(f"{event_name}: {event_data}")
                    saw_start |= event_name == "start"
                    saw_done |= event_name == "done"
                    if event_name == "error":
                        raise RuntimeError(
                            str(event_data.get("message", "stream failed"))
                        )
                    event_name = None
                    event_data = {}

            if not saw_start or not saw_done:
                raise RuntimeError("stream ended without start and done events")
            return 0
    except (httpx.HTTPError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"Request failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
