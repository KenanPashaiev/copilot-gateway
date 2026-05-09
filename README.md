# copilot-gateway

An OpenAI-compatible API server powered by the [GitHub Copilot SDK](https://github.com/github/copilot-sdk). Runs as a Docker container, configurable via YAML and environment variables. Supports model selection, streaming, and pluggable tools.

Any client that speaks the OpenAI API protocol — [Open WebUI](https://github.com/open-webui/open-webui), [Chatbot UI](https://github.com/mckaywrigley/chatbot-ui), [curl](https://curl.se/), the [OpenAI Python client](https://github.com/openai/openai-python), etc. — can connect to it.

## Quick Start

### Docker (recommended)

```bash
docker run -d \
  -p 3001:3001 \
  -e COPILOT_GITHUB_TOKEN=ghp_your_token_here \
  copilot-gateway:latest
```

### Docker Compose

```bash
# Copy and edit the config
cp config.example.yaml config.yaml
cp .env.example .env
# Edit .env with your GitHub token

docker compose up -d
```

### Local Development

```bash
pip install -r requirements.txt
export COPILOT_GITHUB_TOKEN=ghp_your_token_here
uvicorn copilot_gateway.main:app --host 127.0.0.1 --port 3001
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/v1/models` | List available models |
| `GET` | `/v1/models/{id}` | Get a specific model |
| `POST` | `/v1/chat/completions` | Chat completions (streaming & non-streaming) |

### Example: Chat Completion

```bash
curl http://localhost:3001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### Example: Streaming

```bash
curl http://localhost:3001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Tell me a story"}],
    "stream": true
  }'
```

### Example: OpenAI Python Client

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:3001/v1",
    api_key="not-needed"  # Any value works
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

## Configuration

The gateway is configured via a **YAML file** with **environment variable overrides**. See [docs/configuration.md](docs/configuration.md) for the full reference.

**Priority:** Environment variables > YAML file > Built-in defaults

### Key Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COPILOT_GITHUB_TOKEN` | *(required)* | GitHub token with Copilot access |
| `DEFAULT_MODEL` | `gpt-4o` | Default model when not specified in request |
| `PORT` | `3001` | Port to listen on |
| `HOST` | `0.0.0.0` | Address to bind to |
| `CONFIG_PATH` | `/config/config.yaml` | Path to YAML config file |
| `LOG_LEVEL` | `info` | Log level (debug, info, warning, error) |

## Custom Tools

The gateway supports pluggable tools via a config-driven plugin system. Tools are Python modules that define functions using the Copilot SDK's `@define_tool` decorator.

Two built-in tools are included:
- **get_time** — Returns the current date and time
- **web_search** — Searches the web via DuckDuckGo

See [docs/custom-tools.md](docs/custom-tools.md) for a guide on writing your own tools.

## Documentation

- [Configuration Reference](docs/configuration.md) — All config options
- [Custom Tools Guide](docs/custom-tools.md) — Writing and registering tools
- [API Reference](docs/api.md) — Endpoint details with request/response examples
- [Deployment Guide](docs/deployment.md) — Docker, TrueNAS, reverse proxy setups

## Requirements

- GitHub Copilot subscription (includes free tier with limited usage)
- Docker (for container deployment) or Python 3.11+ (for local development)

## License

MIT
