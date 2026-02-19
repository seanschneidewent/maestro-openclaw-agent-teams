"""
Voice proxy between ElevenLabs and OpenClaw.
- Injects x-openclaw-session-key so voice shares the Telegram session
- Prepends a VOICE CALL system message so Maestro knows to keep it short
"""

import json
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

OPENCLAW_URL = "http://127.0.0.1:18789/v1/chat/completions"
SESSION_KEY = "agent:maestro:main"

VOICE_SYSTEM_MESSAGE = {
    "role": "system",
    "content": (
        "[VOICE CALL] You are speaking aloud on a phone call right now. "
        "Two sentences max per response. No formatting, no lists, no markdown, no symbols. "
        "Write numbers as words. Be direct, warm, and natural — like a real person on the phone. "
        "Do NOT read URLs aloud. If you need to send a link, text it to them and say so. "
        "CRITICAL: When using the message tool, ALWAYS include channel='telegram' and accountId='maestro'."
    ),
}


@app.post("/v1/chat/completions")
async def proxy(request: Request):
    body = await request.body()
    data = json.loads(body)

    # Prepend voice system message
    messages = data.get("messages", [])
    data["messages"] = [VOICE_SYSTEM_MESSAGE] + messages

    headers = {
        "content-type": "application/json",
        "authorization": request.headers.get("authorization", ""),
        "x-openclaw-session-key": SESSION_KEY,
        "x-openclaw-message-channel": "telegram",
        "x-openclaw-account-id": "maestro",
    }

    client = httpx.AsyncClient(timeout=120.0)
    req = client.build_request("POST", OPENCLAW_URL, content=json.dumps(data), headers=headers)
    resp = await client.send(req, stream=True)

    async def stream():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "text/event-stream"),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
