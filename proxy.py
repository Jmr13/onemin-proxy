import logging
import os
import time

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

logging.basicConfig(
    filename="proxy.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)

log = logging.getLogger(__name__)

app = Flask(__name__)
app.json.ensure_ascii = False

API_KEY = os.environ.get("API_KEY")
ALLOWED_MODELS = [
    m.strip()
    for m in os.environ.get("ALLOWED_MODELS", "").split(",")
    if m.strip()
]
log.info("Allowed models: %s", ALLOWED_MODELS)

ONE_MIN_URL = "https://api.1min.ai/api/chat-with-ai?isStreaming=false"

@app.post("/v1/chat/completions")
@app.post("/chat/completions")
def chat_completions():
    try:
        body = request.get_json(force=True)
        messages = body.get("messages", [])
        model = (ALLOWED_MODELS[0] if ALLOWED_MODELS else None)
        log.info("Incoming request: model=%s messages=%d", model, len(messages))

        if model not in ALLOWED_MODELS:
            log.warning("Rejected model: %s", model)
            return jsonify({"error": f"Model '{model}' is not allowed"}), 400

        prompt = "\n".join(
            f"{m['role'].capitalize()}: {m['content']}"
            for m in messages
            if m["role"] in ("system", "user", "assistant")
        )
        resp = requests.post(
            ONE_MIN_URL,
            headers={
                "API-KEY": API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "type": "UNIFY_CHAT_WITH_AI",
                "model": model,
                "promptObject": {
                    "prompt": prompt,
                    "settings": {
                        "webSearchSettings": {"webSearch": False},
                    },
                },
            },
        )
        log.info("Upstream response: status=%d content-type=%s", resp.status_code, resp.headers.get("content-type"))
        log.debug("Upstream body: %s", resp.text[:2000])
        if resp.status_code != 200:
            log.error("Upstream error: %s", resp.text)
        resp.raise_for_status()
        data = resp.json()

        content = (
            data.get("aiRecord", {})
            .get("aiRecordDetail", {})
            .get("resultObject", [None])[0]
            or "No response"
        )

        now = int(time.time())
        return jsonify({
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": now,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        })

    except Exception as e:
        log.exception("Proxy error")
        return jsonify({"error": "Proxy error"}), 500

@app.post("/v1/models")
@app.get("/models")
def list_models():
    return jsonify({
        "object": "list",
        "data": [{"id": m, "object": "model"} for m in ALLOWED_MODELS],
    })


def main():
    print("API Proxy running on port 3001")
    app.run(host="0.0.0.0", port=3001)


if __name__ == "__main__":
    main()