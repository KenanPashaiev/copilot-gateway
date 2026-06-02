"""Virtual 'copilot-gateway-admin' model — coded interactive config wizard.

This is NOT backed by an LLM. It parses simple commands from the user's
last message and returns canned responses in OpenAI chat-completion format.
Works even when the gateway has no Copilot authentication configured.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from copilot_gateway import __version__
from copilot_gateway.converters.sdk_to_openai import (
    make_chat_completion,
    make_stream_chunk,
)

logger = logging.getLogger(__name__)

ADMIN_MODEL_ID = "copilot-gateway-admin"


def admin_model_entry() -> dict:
    """Return an OpenAI-format model dict for the admin virtual model."""
    return {
        "id": ADMIN_MODEL_ID,
        "object": "model",
        "created": 0,
        "owned_by": "copilot-gateway",
    }


# ------------------------------------------------------------------
# Command handlers — each returns a plain-text response string
# ------------------------------------------------------------------

def _cmd_help() -> str:
    return (
        "**Copilot Gateway Admin Panel**\n\n"
        "Available commands:\n"
        "- **status** — Show gateway status and auth health\n"
        "- **models** — List available Copilot models\n"
        "- **config** — Show current configuration\n"
        "- **tools** — List loaded tools\n"
        "- **help** — Show this message\n"
    )


async def _cmd_status(request: Request) -> str:
    config = request.app.state.config
    start_time: float = getattr(request.app.state, "start_time", 0)
    uptime = _format_uptime(time.time() - start_time) if start_time else "unknown"
    tools = getattr(request.app.state, "tools", [])
    tool_count = len(tools)

    # Check auth by trying to list models
    auth_status = "unknown"
    model_count = 0
    try:
        from copilot_gateway.copilot.models import list_models
        models = await list_models(cache_ttl=60)
        model_count = len(models)
        # Filter out admin model from count
        model_count = sum(1 for m in models if m["id"] != ADMIN_MODEL_ID)
        auth_status = f"authenticated ({model_count} models available)"
    except Exception:
        auth_status = "not authenticated or unreachable"

    status_icon = "\u2705" if model_count > 0 else "\u274c"

    return (
        f"**Copilot Gateway v{__version__}**\n\n"
        f"| Item | Value |\n"
        f"|---|---|\n"
        f"| Auth | {status_icon} {auth_status} |\n"
        f"| Uptime | {uptime} |\n"
        f"| Tools loaded | {tool_count} |\n"
        f"| Default model | `{config.copilot.default_model}` |\n"
        f"| API key | {'configured' if config.server.api_key else 'not set (open access)'} |\n"
    )


async def _cmd_models(request: Request) -> str:
    try:
        from copilot_gateway.copilot.models import list_models
        models = await list_models(cache_ttl=60)
        real_models = [m for m in models if m["id"] != ADMIN_MODEL_ID]
        if not real_models:
            return (
                "No models available. This usually means the gateway "
                "is not authenticated with GitHub Copilot.\n\n"
                "Ensure your Copilot credentials are configured and restart."
            )
        lines = [f"**Available models ({len(real_models)}):**\n"]
        for m in real_models:
            lines.append(f"- `{m['id']}`")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("Admin: failed to list models")
        return f"Failed to list models: {e}"


def _cmd_config(request: Request) -> str:
    config = request.app.state.config
    cfg = {
        "server": {
            "host": config.server.host,
            "port": config.server.port,
            "log_level": config.server.log_level,
            "api_key": "***" if config.server.api_key else "(not set)",
        },
        "copilot": {
            "default_model": config.copilot.default_model,
            "cli_path": config.copilot.cli_path or "(bundled)",
            "session_idle_timeout": config.copilot.session_idle_timeout,
        },
        "models": {
            "cache_ttl": config.models.cache_ttl,
        },
        "tools": {
            "enabled": config.tools.enabled,
        },
    }
    return f"**Current configuration:**\n\n```json\n{json.dumps(cfg, indent=2)}\n```"


def _cmd_tools(request: Request) -> str:
    tools = getattr(request.app.state, "tools", [])
    if not tools:
        return "No tools are currently loaded."
    lines = [f"**Loaded tools ({len(tools)}):**\n"]
    for t in tools:
        name = getattr(t, "name", None) or str(t)
        desc = getattr(t, "description", "") or ""
        if desc:
            lines.append(f"- **{name}** — {desc}")
        else:
            lines.append(f"- **{name}**")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Command router
# ------------------------------------------------------------------

_COMMANDS = {
    "help": None,       # special-cased (sync)
    "status": None,     # special-cased (async)
    "models": None,     # special-cased (async)
    "config": None,     # special-cased (sync)
    "tools": None,      # special-cased (sync)
}


def _parse_command(messages: list[dict]) -> str:
    """Extract the command keyword from the last user message."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            text = msg.get("content", "")
            if isinstance(text, list):
                # Multimodal content — extract text parts
                text = " ".join(
                    p.get("text", "") for p in text
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            text = text.strip().lower()
            # Match first recognized keyword
            for cmd in _COMMANDS:
                if cmd in text:
                    return cmd
            return "help"
    return "help"


async def _dispatch(command: str, request: Request) -> str:
    """Run the appropriate command handler and return the response text."""
    if command == "help":
        return _cmd_help()
    elif command == "status":
        return await _cmd_status(request)
    elif command == "models":
        return await _cmd_models(request)
    elif command == "config":
        return _cmd_config(request)
    elif command == "tools":
        return _cmd_tools(request)
    else:
        return _cmd_help()


# ------------------------------------------------------------------
# Public entry points (called from chat route)
# ------------------------------------------------------------------

async def handle_admin_blocking(
    messages: list[dict],
    request: Request,
) -> JSONResponse:
    """Handle a non-streaming request to the admin model."""
    command = _parse_command(messages)
    content = await _dispatch(command, request)
    response = make_chat_completion(model=ADMIN_MODEL_ID, content=content)
    return JSONResponse(content=response)


async def handle_admin_streaming(
    messages: list[dict],
    request: Request,
):
    """Handle a streaming request to the admin model (SSE generator)."""
    command = _parse_command(messages)
    content = await _dispatch(command, request)

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Initial role chunk
    initial = make_stream_chunk(chunk_id, ADMIN_MODEL_ID, role="assistant")
    yield f"data: {json.dumps(initial)}\n\n"

    # Stream content in small pieces for the typing effect
    chunk_size = 20
    for i in range(0, len(content), chunk_size):
        piece = content[i:i + chunk_size]
        chunk = make_stream_chunk(chunk_id, ADMIN_MODEL_ID, delta_content=piece)
        yield f"data: {json.dumps(chunk)}\n\n"

    # Final chunk
    final = make_stream_chunk(chunk_id, ADMIN_MODEL_ID, finish_reason="stop")
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def _format_uptime(seconds: float) -> str:
    """Format seconds into a human-readable uptime string."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    hours = s // 3600
    minutes = (s % 3600) // 60
    return f"{hours}h {minutes}m"
