"""POST /v1/chat/completions — streaming and non-streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from copilot.session import PermissionHandler

from copilot_gateway.copilot.client import get_copilot_client
from copilot_gateway.converters.openai_to_sdk import extract_params, messages_to_prompt
from copilot_gateway.converters.sdk_to_openai import (
    make_chat_completion,
    make_error_response,
    make_stream_chunk,
)

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
        raise HTTPException(
            status_code=502,
            detail=make_error_response(
                message="Upstream error from Copilot SDK",
                error_type="upstream_error",
            ),
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
            _queue: asyncio.Queue = asyncio.Queue()

            def on_event(event):
                if event.type.value == "assistant.message_delta":
                    delta = getattr(event.data, "delta_content", "") or ""
                    if delta:
                        chunk = make_stream_chunk(chunk_id, model, delta_content=delta)
                        _queue.put_nowait(chunk)
                elif event.type.value in ("session.idle", "assistant.message"):
                    done.set()

            session.on(on_event)
            await session.send(prompt)

            # Yield chunks as they arrive, waiting on queue or done signal
            while not done.is_set() or not _queue.empty():
                if not _queue.empty():
                    data = _queue.get_nowait()
                    yield f"data: {json.dumps(data)}\n\n"
                else:
                    # Wait for either a queued chunk or the done signal
                    wait_queue = asyncio.ensure_future(_queue.get())
                    wait_done = asyncio.ensure_future(done.wait())
                    finished, pending = await asyncio.wait(
                        [wait_queue, wait_done],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    if wait_queue in finished:
                        data = wait_queue.result()
                        yield f"data: {json.dumps(data)}\n\n"

            # Drain any remaining
            while not _queue.empty():
                data = _queue.get_nowait()
                yield f"data: {json.dumps(data)}\n\n"

    except Exception:
        logger.exception("Error in streaming chat completion")
        error_chunk = make_stream_chunk(
            chunk_id, model,
            delta_content="[Error: upstream failure]",
        )
        yield f"data: {json.dumps(error_chunk)}\n\n"

    # Send the final chunk with finish_reason
    final = make_stream_chunk(chunk_id, model, finish_reason="stop")
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"
