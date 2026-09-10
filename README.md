# onemin-proxy

OpenAI-compatible API proxy for [1min.ai](https://1min.ai). Point any OpenAI-compatible client at this server and it translates requests to 1min.ai's API.

## Quick Start

```bash
git clone <repo-url> && cd onemin-proxy
bash setup.sh        # creates venv, installs deps, copies .env
```

Edit `.env`:

```
API_KEY=your_1min_api_key
ALLOWED_MODELS=gpt-4o,claude-3-opus,gemini-pro
```

Run:

```bash
source .venv/bin/activate
python proxy.py
```

Server starts on `http://0.0.0.0:3001`.

## Endpoints

| Method | Path                 | Description        |
|--------|----------------------|--------------------|
| POST   | `/v1/chat/completions` | Chat completion (OpenAI format) |
| POST   | `/chat/completions`    | Same, shorter path  |
| POST/GET | `/v1/models`       | List allowed models |

## Usage with OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:3001/v1",
    api_key="unused",
)

resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)
print(resp.choices[0].message.content)
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_KEY` | Yes | Your 1min.ai API key |
| `ALLOWED_MODELS` | No | Comma-separated list of allowed model IDs |
