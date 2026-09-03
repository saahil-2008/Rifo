"""Small WebSocket client for /v1/verify/stream (FR-7).

Sends one screenshot and prints each progressive frame as it arrives. Requires
a running server AND a Gemini API key in backend/.env for the vision stage.

Usage (from repo root):
    backend/venv/Scripts/python.exe scripts/ws_probe.py <image.jpg> [ws_url]

The default server URL is ws://localhost:8000/v1/verify/stream.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import uuid

try:
    import websockets
except ImportError:
    raise SystemExit("websockets not installed — run: pip install websockets")


async def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(script_dir, "sample", "demo.jpg")
    ws_url = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "ws://localhost:8000/v1/verify/stream"
    )

    if not os.path.exists(image_path):
        raise SystemExit(f"Screenshot not found: {image_path}\n"
                         f"Pass one, e.g.: python scripts/ws_probe.py scripts/sample/claim.jpg")

    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    payload = json.dumps({
        "image_b64": image_b64,
        "device_id": str(uuid.uuid4()),
    })
    print(f"Sending {os.path.basename(image_path)} "
          f"({len(image_b64)} b64 chars) → {ws_url}")

    async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
        await ws.send(payload)
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=60)
            except asyncio.TimeoutError:
                print("(timed out waiting for frames)")
                break
            frame = json.loads(raw)
            print(frame)
            if frame.get("stage") in ("done", "error"):
                break


if __name__ == "__main__":
    asyncio.run(main())
