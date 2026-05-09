"""POST /v1/chat/completions — streaming and non-streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from copilot.session import PermissionHandler

from copilot_gateway.copilot.client import get_copilot_client
from copilot_gateway.converters.openai_to_sdk import extract_params, messages_to_prompt
from copilot_gateway.converters.sdk_to_openai import make_chat_completion, make_stream_chunk

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


class ChatMessage(BaseModel):
    role: str
    content: str | list | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None


@router.post("/chat/completions")
async def chat_completions(body: ChatCompletionRequest, request: Request):
    config = request.app.state.config
    tools = request.app.state.tools

    model = body.model or config.copilot.default_model
    system_message, prompt = messages_to_prompt(
        [m.model_dump(exclude_none=True) for m in body.messages]
    )

    params = extract_params(body.model_dump(exclude_none=True))

    if body.stream:
        return StreamingResponse(
            _stream_response(model, system_message, prompt, params, tools),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _blocking_response(model, system_message, prompt, params, tools)


async def _blocking_response(
    model: str,
    system_message: str | None,
    prompt: str,
    params: dict,
    tools: list,
) -> dict:
    """Non-streaming: send prompt and wait for the full response."""
    client = await get_copilot_client()

    session_kwargs = {
        "model": model,
        "on_permission_request": PermissionHandler.approve_all,
    }
    if system_message:
        session_kwargs["system_message"] = {"content": system_message}
    if tools:
        session_kwargs["tools"] = tools
    session_kwargs.update(params)

    try:
        async with await client.create_session(**session_kwargs) as session:
            result = await session.send_and_wait(prompt)
            content = ""
            # result is a SessionEvent; the actual message is in result.data.content
            if hasattr(result, "data") and hasattr(result.data, "content"):
                content = result.data.content or ""
            elif hasattr(result, "content"):
                content = result.content or ""
            elif isinstance(result, str):
                content = result
            else:
                content = str(result)
            return make_chat_completion(model=model, content=content)
    except Exception:
        logger.exception("Error in blocking chat completion")
        return make_chat_completion(
            model=model,
            content="An error occurred while processing the request.",
            finish_reason="error",
        )


async def _stream_response(
    model: str,
    system_message: str | None,
    prompt: str,
    params: dict,
    tools: list,
):
    """Streaming: yield SSE chunks as the SDK produces delta events."""
    client = await get_copilot_client()

    session_kwargs = {
        "model": model,
        "streaming": True,
        "on_permission_request": PermissionHandler.approve_all,
    }
    if system_message:
        session_kwargs["system_message"] = {"content": system_message}
    if tools:
        session_kwargs["tools"] = tools
    session_kwargs.update(params)

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Send the initial chunk with role
    initial = make_stream_chunk(chunk_id, model, role="assistant")
    yield f"data: {json.dumps(initial)}\n\n"

    try:
        async with await client.create_session(**session_kwargs) as session:
            done = asyncio.Event()
            error_occurred = False

            def on_event(event):
                nonlocal error_occurred
                if event.type.value == "assistant.message_delta":
                    delta = getattr(event.data, "delta_content", "") or ""
                    if delta:
                        chunk = make_stream_chunk(chunk_id, model, delta_content=delta)
                        _queue.put_nowait(("chunk", chunk))
                elif event.type.value in ("session.idle", "assistant.message"):
                    done.set()

            _queue: asyncio.Queue = asyncio.Queue()
            session.on(on_event)
            await session.send(prompt)

            # Yield chunks as they arrive
            while not done.is_set():
                try:
                    msg_type, data = await asyncio.wait_for(_queue.get(), timeout=0.1)
                    if msg_type == "chunk":
                        yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    continue

            # Drain remaining chunks
            while not _queue.empty():
                msg_type, data = _queue.get_nowait()
                if msg_type == "chunk":
                    yield f"data: {json.dumps(data)}\n\n"

    except Exception:
        logger.exception("Error in streaming chat completion")

    # Send the final chunk with finish_reason
    final = make_stream_chunk(chunk_id, model, finish_reason="stop")
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"
