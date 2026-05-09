# copilot-gateway

An OpenAI-compatible API server powered by the [GitHub Copilot SDK](https://github.com/github/copilot-sdk). Exposes Copilot models through the standard OpenAI REST protocol — chat completions (streaming and non-streaming), model listing, and pluggable tools.

Any client that speaks the OpenAI API — [Open WebUI](https://github.com/open-webui/open-webui), [Chatbot UI](https://github.com/mckaywrigley/chatbot-ui), [curl](https://curl.se/), the [OpenAI Python client](https://github.com/openai/openai-python), etc. — can connect to it.

## Features

- **OpenAI-compatible REST API** — drop-in replacement for `/v1/chat/completions` and `/v1/models`
- **Streaming & non-streaming** — Server-Sent Events for real-time token output
- **API key authentication** — optional Bearer token to protect access
- **Pluggable tools** — extend the LLM with custom `@define_tool` functions
- **YAML + env config** — flexible configuration with environment variable overrides
- **Docker-ready** — ships with a production `Dockerfile`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/v1/models` | List available models |
| `GET` | `/v1/models/{id}` | Get a specific model |
| `POST` | `/v1/chat/completions` | Chat completions (streaming & non-streaming) |

## Project Structure

```
copilot_gateway/
├── main.py              # FastAPI app entry point
├── config.py            # YAML + env config loading
├── middleware.py         # API key authentication
├── routes/
│   ├── chat.py          # POST /v1/chat/completions
│   ├── models.py        # GET /v1/models
│   └── health.py        # GET /health
├── copilot/
│   ├── __init__.py      # CopilotClient singleton
│   ├── client.py        # Re-exports
│   └── models.py        # Model list caching
├── converters/
│   ├── openai_to_sdk.py # OpenAI request → SDK format
│   └── sdk_to_openai.py # SDK response → OpenAI format
└── tools/
    ├── registry.py      # Tool discovery & loading
    └── builtins/        # Built-in tools (get_time, web_search)
```

## Authentication

copilot-gateway uses the **Copilot CLI's built-in OAuth authentication** (device flow). Before running the gateway, you must log in:

```bash
# First-time setup — authenticate with GitHub
copilot auth login
```

This opens a browser for GitHub OAuth authorization. Credentials are stored in `~/.copilot/` and persist across restarts.

For Docker deployments, mount a volume at `/home/appuser/.copilot` to persist credentials, then run the login inside the container once:

```bash
docker exec -it <container> copilot auth login
```

## Development

```bash
# Set up
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements.txt

# Authenticate with GitHub Copilot (first time only)
copilot auth login

# Run
uvicorn copilot_gateway.main:app --host 127.0.0.1 --port 3001

# Test
pip install pytest httpx
pytest tests/ -v
```

## Configuration

The gateway is configured via a **YAML config file** with **environment variable overrides**. See [docs/configuration.md](docs/configuration.md) for the full reference.

**Priority:** Environment variables > YAML file > Built-in defaults

## Built-in Tools

Two tools are included out of the box:
- **get_time** — Returns the current date and time
- **web_search** — Searches the web via DuckDuckGo

Custom tools can be added via the `@define_tool` decorator. See [docs/custom-tools.md](docs/custom-tools.md).

## Documentation

- [API Reference](docs/api.md) — Endpoints, request/response formats, error handling
- [Configuration Reference](docs/configuration.md) — All config options and environment variables
- [Custom Tools Guide](docs/custom-tools.md) — Writing and registering tool plugins

## Requirements

- GitHub account with a Copilot subscription (includes free tier with limited usage)
- Docker (for container deployment) or Python 3.11+ (for local development)

## License

MIT
