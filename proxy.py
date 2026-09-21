import json
import logging
import os
import time

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request

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

ONE_MIN_BASE = "https://api.1min.ai/api/chat-with-ai"

_upstream_headers = {
    "API-KEY": API_KEY,
    "Content-Type": "application/json",
}


def _build_prompt(messages):
    return "\n".join(
        f"{m['role'].capitalize()}: {m['content']}"
        for m in messages
        if m["role"] in ("system", "user", "assistant")
    )


def _build_body(model, prompt):
    return {
        "type": "UNIFY_CHAT_WITH_AI",
        "model": model,
        "promptObject": {
            "prompt": prompt,
            "settings": {
                "webSearchSettings": {"webSearch": False},
            },
        },
    }


def _chat_completion_id():
    return f"chatcmpl-{int(time.time() * 1000)}"


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
def chat_completions():
    try:
        body = request.get_json(force=True)
        messages = body.get("messages", [])
        model = body.get("model") or (ALLOWED_MODELS[0] if ALLOWED_MODELS else None)
        stream = body.get("stream", False)
        log.info("Incoming request: model=%s messages=%d stream=%s", model, len(messages), stream)

        if model not in ALLOWED_MODELS:
            log.warning("Rejected model: %s", model)
            return jsonify({"error": f"Model '{model}' is not allowed"}), 400

        prompt = _build_prompt(messages)
        upstream_model = model.split("/", 1)[-1] if "/" in model else model
        upstream_body = _build_body(upstream_model, prompt)

        if stream:
            return _handle_stream(model, upstream_body)

        return _handle_non_stream(model, upstream_body)

    except Exception as e:
        log.exception("Proxy error")
        return jsonify({"error": "Proxy error"}), 500


def _handle_non_stream(model, upstream_body):
    url = f"{ONE_MIN_BASE}?isStreaming=false"
    resp = requests.post(url, headers=_upstream_headers, json=upstream_body)
    log.info("Upstream response: status=%d", resp.status_code)
    if resp.status_code != 200:
        log.error("Upstream error: %s", resp.text)
        try:
            err = resp.json()
            msg = err.get("message") or err.get("error") or resp.text
        except Exception:
            msg = resp.text
        return jsonify({"error": {"message": msg, "type": "upstream_error", "code": resp.status_code}}), resp.status_code
    data = resp.json()

    content = (
        data.get("aiRecord", {})
        .get("aiRecordDetail", {})
        .get("resultObject", [None])[0]
        or "No response"
    )

    return jsonify({
        "id": _chat_completion_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    })


def _handle_stream(model, upstream_body):
    url = f"{ONE_MIN_BASE}?isStreaming=true"
    resp = requests.post(url, headers=_upstream_headers, json=upstream_body, stream=True)
    log.info("Upstream stream: status=%d", resp.status_code)
    if resp.status_code != 200:
        log.error("Upstream stream error: %s", resp.text)
        resp.raise_for_status()

    completion_id = _chat_completion_id()
    created = int(time.time())

    def generate():
        sent_role = False
        event_type = ""
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event: "):
                event_type = line[len("event: "):]
                continue
            if not line.startswith("data: "):
                continue
            data_str = line[len("data: "):]
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if event_type == "content":
                content = data.get("content", "")
                if not content:
                    continue
                delta = {}
                if not sent_role:
                    delta["role"] = "assistant"
                    sent_role = True
                delta["content"] = content
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"

            elif event_type == "done":
                final_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            elif event_type == "error":
                log.error("Upstream stream error event: %s", data)
                error_msg = data.get("error") if isinstance(data, dict) else str(data)
                error_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"[Error: {error_msg}]"},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"
                yield "data: [DONE]\n\n"

        if not sent_role:
            error_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "[Error: Empty response from upstream]"},
                        "finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
            yield "data: [DONE]\n\n"

    return Response(
        generate(),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.get("/v1/models")
@app.post("/v1/models")
@app.get("/models")
@app.post("/models")
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