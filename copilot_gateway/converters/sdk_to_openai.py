"""Convert Copilot SDK responses to OpenAI API response format."""

from __future__ import annotations

import time
import uuid


def make_chat_completion(
    model: str,
    content: str,
    finish_reason: str = "stop",
) -> dict:
    """Build a non-streaming OpenAI chat completion response."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


def make_stream_chunk(
    chunk_id: str,
    model: str,
    delta_content: str | None = None,
    finish_reason: str | None = None,
    role: str | None = None,
) -> dict:
    """Build a single SSE chunk for streaming OpenAI chat completion."""
    delta: dict = {}
    if role:
        delta["role"] = role
    if delta_content is not None:
        delta["content"] = delta_content

    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
