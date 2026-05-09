# API Reference

copilot-gateway exposes an OpenAI-compatible REST API. Any client that supports the OpenAI API protocol can connect to it.

Default base URL: `http://<host>:<port>` (default `0.0.0.0:3001`)

## Authentication

If the gateway is configured with an API key (`COPILOT_API_KEY` env var or `server.api_key` in config), all endpoints except `/health` require authentication.

Include the key in the `Authorization` header:

```
Authorization: Bearer <your-api-key>
```

If no API key is configured, all requests are accepted without authentication.

**Error response (401):**
```json
{
  "error": {
    "message": "Invalid or missing API key.",
    "type": "authentication_error",
    "code": "invalid_api_key"
  }
}
```

## Endpoints

### GET /health

Health check.

**Response:**
```json
{"status": "ok"}
```

---

### GET /v1/models

List all available models from the Copilot SDK.

**Response:**
```json
{
  "object": "list",
  "data": [
    {"id": "gpt-4o", "object": "model", "created": 0, "owned_by": "copilot"},
    {"id": "claude-sonnet-4", "object": "model", "created": 0, "owned_by": "copilot"},
    {"id": "o3", "object": "model", "created": 0, "owned_by": "copilot"}
  ]
}
```

The model list is cached for 5 minutes (configurable via `models.cache_ttl`).

---

### GET /v1/models/{model_id}

Get information about a specific model.

**Response (200):**
```json
{"id": "gpt-4o", "object": "model", "created": 0, "owned_by": "copilot"}
```

**Response (404):**
```json
{"detail": "Model 'nonexistent' not found"}
```

---

### POST /v1/chat/completions

Create a chat completion. Supports both streaming and non-streaming modes.

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `model` | string | No | Config default | Model to use |
| `messages` | array | Yes | — | Conversation messages |
| `stream` | boolean | No | `false` | Enable SSE streaming |
| `temperature` | float | No | — | Sampling temperature |
| `top_p` | float | No | — | Nucleus sampling |
| `max_tokens` | int | No | — | Max tokens to generate |
| `max_completion_tokens` | int | No | — | Alias for max_tokens |

**Message format:**
```json
{
  "role": "user",        // "system", "user", "assistant", or "tool"
  "content": "Hello!",
  "tool_call_id": null   // Only for role: "tool"
}
```

#### Non-Streaming Response

```json
{
  "id": "chatcmpl-abc123def456",
  "object": "chat.completion",
  "created": 1715270400,
  "model": "gpt-4o",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you today?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

> Note: Token usage is not tracked and returns zeros.

#### Streaming Response

When `stream: true`, the response is a stream of Server-Sent Events (SSE).

Each event is a JSON object prefixed with `data: `:

**First chunk (role):**
```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1715270400,"model":"gpt-4o","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}
```

**Content chunks:**
```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1715270400,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1715270400,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"!"},"finish_reason":null}]}
```

**Final chunk:**
```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1715270400,"model":"gpt-4o","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

## Error Responses

The gateway returns structured error responses following the OpenAI error format:

**502 — Upstream error:**
```json
{
  "detail": {
    "error": {
      "message": "Upstream error from Copilot SDK",
      "type": "upstream_error"
    }
  }
}
```

During streaming, if an error occurs mid-stream, the gateway sends an error delta before closing:
```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1715270400,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"[Error: upstream failure]"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1715270400,"model":"gpt-4o","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```
