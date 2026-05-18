"""Proxy interceptor: captura tokens exactos de opencode, reenvía a DeepSeek.

Soporta peticiones streaming y no-streaming.
Para streaming: bufferiza chunks SSE, extrae usage del chunk final, retransmite.

Arrancar antes del benchmark:
    python leo-code/benchmark/llm_proxy.py

opencode.json en el repo apunta DeepSeek -> este proxy.
"""
import os, json, time
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv(r"C:\Users\Ismael\Desktop\RAG\.env")

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = "https://api.deepseek.com"
LOGS: list[dict] = []

app = FastAPI()


@app.post("/v1/chat/completions")
async def intercept(request: Request):
    body = await request.json()
    is_stream = body.get("stream", False)
    t0 = time.time()

    msgs = body.get("messages", [])
    sys_chars = len(msgs[0].get("content", "")) if msgs else 0
    log_entry: dict = {
        "ts": round(t0, 3),
        "model": body.get("model", ""),
        "input_tokens": 0,
        "output_tokens": 0,
        "latency": 0.0,
        "system_chars": sys_chars,
        "status": 0,
    }
    LOGS.append(log_entry)

    fwd_headers = {
        "Authorization": f"Bearer {DEEPSEEK_KEY}",
        "Content-Type": "application/json",
    }

    if is_stream:
        # Streaming: buffer chunks, extract usage, retransmit
        collected: list[bytes] = []
        usage: dict = {}

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{DEEPSEEK_BASE}/chat/completions",
                json=body,
                headers=fwd_headers,
            ) as r:
                log_entry["status"] = r.status_code
                async for chunk in r.aiter_bytes():
                    collected.append(chunk)
                    # Parse SSE lines for usage
                    for line in chunk.decode("utf-8", errors="replace").splitlines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            try:
                                data = json.loads(line[6:])
                                if "usage" in data and data["usage"]:
                                    usage = data["usage"]
                            except Exception:
                                pass

        log_entry["input_tokens"] = usage.get("prompt_tokens", 0)
        log_entry["output_tokens"] = usage.get("completion_tokens", 0)
        log_entry["latency"] = round(time.time() - t0, 3)

        async def stream_gen():
            for chunk in collected:
                yield chunk

        return StreamingResponse(
            stream_gen(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    else:
        # Non-streaming: forward and log
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{DEEPSEEK_BASE}/chat/completions",
                json=body,
                headers=fwd_headers,
            )

        log_entry["status"] = r.status_code
        log_entry["latency"] = round(time.time() - t0, 3)

        try:
            resp = r.json()
        except Exception:
            resp = {"error": r.text[:300]}

        usage = resp.get("usage", {})
        log_entry["input_tokens"] = usage.get("prompt_tokens", 0)
        log_entry["output_tokens"] = usage.get("completion_tokens", 0)

        return JSONResponse(content=resp, status_code=r.status_code)


@app.get("/proxy/logs")
def get_logs():
    return LOGS


@app.delete("/proxy/logs")
def clear_logs():
    LOGS.clear()
    return {"cleared": True}


@app.get("/proxy/health")
def health():
    return {"status": "ok", "logs": len(LOGS)}


if __name__ == "__main__":
    import uvicorn
    print("[proxy] LLM interceptor en http://localhost:9999")
    print("[proxy] Soporta streaming y no-streaming")
    uvicorn.run(app, host="0.0.0.0", port=9999, log_level="warning")
