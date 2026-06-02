"""POST /v1/chat/completions — streaming and non-streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from copilot_gateway.copilot.sessions import (
    disconnect_session,
    get_or_create_session,
)
from copilot_gateway.converters.openai_to_sdk import (
    extract_image_attachments,
    last_user_prompt,
    messages_to_prompt,
)
from copilot_gateway.converters.sdk_to_openai import (
    make_chat_completion,
    make_error_response,
    make_stream_chunk,
)
from copilot_gateway.routes.admin import (
    ADMIN_MODEL_ID,
    handle_admin_blocking,
    handle_admin_streaming,
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
    reasoning_effort: str | None = None


@router.post("/chat/completions")
async def chat_completions(body: ChatCompletionRequest, request: Request):
    config = request.app.state.config
    tools = request.app.state.tools

    model = body.model or config.copilot.default_model
    messages = [m.model_dump(exclude_none=True) for m in body.messages]

    # Virtual admin model — handled entirely in-process, no LLM needed
    if model == ADMIN_MODEL_ID:
        if body.stream:
            return StreamingResponse(
                handle_admin_streaming(messages, request),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        return await handle_admin_blocking(messages, request)

    # Session reuse: client may pass X-Session-Id to continue a conversation
    session_id = request.headers.get("x-session-id")
    excluded_tools = config.copilot.excluded_tools or None
    system_prompt = config.copilot.system_prompt or ""

    if body.stream:
        return StreamingResponse(
            _stream_response(model, messages, tools, session_id, excluded_tools, system_prompt),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _blocking_response(
            model, messages, tools, session_id, excluded_tools, system_prompt,
        )


async def _blocking_response(
    model: str,
    messages: list[dict],
    tools: list,
    session_id: str | None,
    excluded_tools: list[str] | None = None,
    system_prompt: str = "",
) -> JSONResponse:
    """Non-streaming: send prompt and wait for the full response."""
    session = None
    try:
        session, sid, is_new = await get_or_create_session(
            session_id,
            model=model,
            system_message=_system_message(messages, system_prompt),
            tools=tools,
            excluded_tools=excluded_tools,
        )

        prompt = _prompt_for_session(messages, is_new)
        attachments = extract_image_attachments(messages)

        send_kwargs: dict = {}
        if attachments:
            send_kwargs["attachments"] = attachments

        result = await session.send_and_wait(prompt, **send_kwargs)
        content = _extract_content(result)

        response = make_chat_completion(model=model, content=content)
        return JSONResponse(
            content=response,
            headers={"X-Session-Id": sid},
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        raise
    except Exception:
        logger.exception("Error in blocking chat completion")
        raise HTTPException(
            status_code=502,
            detail=make_error_response(
                message="Upstream error from Copilot SDK",
                error_type="upstream_error",
            ),
        )
    finally:
        if session is not None:
            await disconnect_session(session)


async def _stream_response(
    model: str,
    messages: list[dict],
    tools: list,
    session_id: str | None,
    excluded_tools: list[str] | None = None,
    system_prompt: str = "",
):
    """Streaming: yield SSE chunks as the SDK produces delta events."""
    session = None
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    try:
        session, sid, is_new = await get_or_create_session(
            session_id,
            model=model,
            system_message=_system_message(messages, system_prompt),
            tools=tools,
            streaming=True,
            excluded_tools=excluded_tools,
        )

        prompt = _prompt_for_session(messages, is_new)

        # Send the initial chunk with role (include session ID
        # as a custom field so streaming clients can discover it).
        initial = make_stream_chunk(chunk_id, model, role="assistant")
        initial["x_session_id"] = sid
        yield f"data: {json.dumps(initial)}\n\n"

        done = asyncio.Event()
        _queue: asyncio.Queue = asyncio.Queue()
        _got_delta = False  # Whether we received streaming deltas

        def on_event(event):
            nonlocal _got_delta
            etype = event.type.value
            if etype == "assistant.message_delta":
                delta = getattr(event.data, "delta_content", "") or ""
                if delta:
                    _got_delta = True
                    chunk = make_stream_chunk(chunk_id, model, delta_content=delta)
                    _queue.put_nowait(chunk)
            elif etype == "assistant.message":
                # Final message for this turn. If we never received streaming
                # deltas, emit the full content as a single chunk (this
                # happens when the agent uses tools across multiple turns).
                content = getattr(event.data, "content", "") or ""
                if content and not _got_delta:
                    chunk = make_stream_chunk(
                        chunk_id, model, delta_content=content,
                    )
                    _queue.put_nowait(chunk)
                # Reset delta flag for the next turn
                _got_delta = False
            elif etype == "session.idle":
                done.set()

        session.on(on_event)

        attachments = extract_image_attachments(messages)
        send_kwargs: dict = {}
        if attachments:
            send_kwargs["attachments"] = attachments

        await session.send(prompt, **send_kwargs)

        # Yield chunks as they arrive until the session signals completion.
        while not done.is_set() or not _queue.empty():
            try:
                data = await asyncio.wait_for(_queue.get(), timeout=0.1)
                yield f"data: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                continue

        # Drain any remaining
        while not _queue.empty():
            data = _queue.get_nowait()
            yield f"data: {json.dumps(data)}\n\n"

    except (asyncio.CancelledError, KeyboardInterrupt):
        raise
    except Exception:
        logger.exception("Error in streaming chat completion")
        error_chunk = make_stream_chunk(
            chunk_id, model,
            delta_content="[Error: upstream failure]",
        )
        yield f"data: {json.dumps(error_chunk)}\n\n"
    finally:
        if session is not None:
            await disconnect_session(session)

    # Send the final chunk with finish_reason
    final = make_stream_chunk(chunk_id, model, finish_reason="stop")
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _system_message(messages: list[dict], config_prompt: str = "") -> str | None:
    """Extract the system message, prepending the gateway's default prompt."""
    system, _ = last_user_prompt(messages)
    parts = [p for p in (config_prompt, system) if p]
    return "\n\n".join(parts) if parts else None


def _prompt_for_session(messages: list[dict], is_new: bool) -> str:
    """Build the prompt string depending on whether the session is new.

    New sessions get the full conversation history as the prompt.
    Resumed sessions get only the last user message since the SDK
    already has the prior context.
    """
    if is_new:
        _, prompt = messages_to_prompt(messages)
    else:
        _, prompt = last_user_prompt(messages)
    return prompt


def _extract_content(result) -> str:
    """Pull the text content out of an SDK response."""
    if hasattr(result, "data") and hasattr(result.data, "content"):
        return result.data.content or ""
    if hasattr(result, "content"):
        return result.content or ""
    if isinstance(result, str):
        return result
    return str(result)
