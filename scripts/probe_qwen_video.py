from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from film_study_tool.ui_server import ROOT, load_dotenv


def main() -> None:
    load_dotenv(ROOT / ".env")
    video_path = ROOT / "data" / "test-qwen-video.mp4"
    video_data = "data:video/mp4;base64," + base64.b64encode(video_path.read_bytes()).decode("ascii")
    key = os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("ALIBABA_CLOUD_API_KEY")
    if not key:
        raise SystemExit("No Qwen API key loaded from .env")

    body = {
        "model": os.environ.get("QWEN_VIDEO_MODEL", "qwen3.7-plus"),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "video_url", "video_url": {"url": video_data}, "fps": 2},
                    {"type": "text", "text": 'Reply with JSON only: {"seen_video": true}'},
                ],
            }
        ],
        "max_tokens": 50,
        "response_format": {"type": "json_object"},
        "enable_thinking": False,
    }
    request = urllib.request.Request(
        os.environ["QWEN_COMPATIBLE_URL"],
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            print("status", response.status)
            print(response.read().decode("utf-8")[:1000])
    except urllib.error.HTTPError as exc:
        print("http_error", exc.code)
        print(exc.read().decode("utf-8", errors="replace")[:1400])


if __name__ == "__main__":
    main()
