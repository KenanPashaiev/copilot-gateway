"""Virtual 'copilot-gateway-admin' model — coded interactive config wizard.

This is NOT backed by an LLM. It parses simple commands from the user's
last message and returns canned responses in OpenAI chat-completion format.
Works even when the gateway has no Copilot authentication configured.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

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
# Command handlers
# ------------------------------------------------------------------

def _cmd_help(auth_ok: bool = True) -> str:
    if not auth_ok:
        return (
            f"**Copilot Gateway v{__version__}**\n\n"
            "\u26a0\ufe0f **Not authenticated.** "
            "Type **auth login** to connect your GitHub account.\n\n"
            "Available commands:\n"
            "- **auth** — Auth status and commands\n"
            "- **auth login** — Connect your GitHub account\n"
            "- **status** — Gateway status\n"
            "- **models** — List available models\n"
            "- **tools** — List loaded tools\n"
            "- **restart** — Restart the Copilot SDK client\n"
            "- **help** — Show this message\n"
        )
    return (
        f"**Copilot Gateway v{__version__}**\n\n"
        "Available commands:\n"
        "- **auth** — Auth status and commands\n"
        "- **status** — Gateway status\n"
        "- **models** — List available models\n"
        "- **tools** — List loaded tools\n"
        "- **restart** — Restart the Copilot SDK client\n"
        "- **help** — Show this message\n"
    )


async def _cmd_auth(request: Request) -> str:
    """Show auth status and auth-related commands."""
    auth_info = await _get_auth_info()

    if auth_info["authenticated"]:
        login = auth_info.get("login", "unknown")
        auth_type = auth_info.get("auth_type", "")
        has_stored = _has_stored_token(request)
        lines = [
            f"\u2705 **Authenticated** as **@{login}**\n",
        ]
        if auth_type:
            lines.append(f"Auth type: {auth_type}")
        if has_stored:
            lines.append("Token: stored in gateway")
        lines.append("\nAuth commands:")
        lines.append("- **auth logout** \u2014 Disconnect and clear stored token")
    else:
        msg = auth_info.get("message", "Not authenticated")
        lines = [
            f"\u274c **{msg}**\n",
            "Auth commands:",
            "- **auth login** \u2014 Connect your GitHub account",
        ]

    return "\n".join(lines)


async def _cmd_auth_login(messages: list[dict], request: Request) -> str:
    """Handle the auth login flow."""
    text = _get_last_user_text(messages)

    # Check if the user included a token in the "auth login <token>" message
    rest = text.strip()
    if rest.lower().startswith("auth login"):
        rest = rest[len("auth login"):].strip()
    token = _extract_token(rest) if rest else None
    if token:
        return await _store_token_and_restart(token, request)

    # Show login instructions
    return (
        "**Connect your GitHub account**\n\n"
        "Paste your GitHub token below. You can get one by:\n\n"
        "1. **GitHub CLI** (easiest): Run `gh auth token` in your terminal\n"
        "2. **Personal Access Token**: "
        "[Create one](https://github.com/settings/tokens) with the **copilot** scope\n"
        "3. **Copilot CLI**: Run `copilot auth login` and copy the token\n\n"
        "Then type:\n"
        "```\nauth token YOUR_TOKEN_HERE\n```"
    )


async def _cmd_auth_token(token: str, request: Request) -> str:
    """Store a token provided by the user."""
    if not token:
        return (
            "No token provided. Usage:\n"
            "```\nauth token YOUR_TOKEN_HERE\n```"
        )
    return await _store_token_and_restart(token, request)


async def _cmd_auth_logout(request: Request) -> str:
    """Clear stored token and restart the SDK client."""
    if not _has_stored_token(request):
        return (
            "No stored token to clear.\n\n"
            "The gateway may be using the Copilot CLI's own credentials "
            "(from `copilot auth login`). To clear those, remove the CLI's "
            "auth files from `~/.copilot`."
        )

    request.app.state.github_token = None
    await _restart_client(request)
    return (
        "\u2705 **Token cleared and client restarted.**\n\n"
        "The gateway will fall back to the Copilot CLI's own credentials "
        "if available.\n\n"
        "Type **auth** to check the current auth status."
    )


async def _cmd_status(request: Request) -> str:
    config = request.app.state.config
    start_time: float = getattr(request.app.state, "start_time", 0)
    uptime = _format_uptime(time.time() - start_time) if start_time else "unknown"
    tools = getattr(request.app.state, "tools", [])
    tool_count = len(tools)

    auth_info = await _get_auth_info()
    if auth_info["authenticated"]:
        login = auth_info.get("login", "unknown")
        auth_status = f"\u2705 @{login}"
    else:
        auth_status = "\u274c " + auth_info.get("message", "not authenticated")

    model_count = 0
    try:
        from copilot_gateway.copilot.models import list_models
        models = await list_models(cache_ttl=60)
        model_count = sum(1 for m in models if m["id"] != ADMIN_MODEL_ID)
    except Exception:
        pass

    return (
        f"**Copilot Gateway v{__version__}**\n\n"
        f"| Item | Value |\n"
        f"|---|---|\n"
        f"| Auth | {auth_status} |\n"
        f"| Models | {model_count} available |\n"
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
                "Type **auth login** to connect your GitHub account."
            )
        lines = [f"**Available models ({len(real_models)}):**\n"]
        for m in real_models:
            lines.append(f"- `{m['id']}`")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("Admin: failed to list models")
        return f"Failed to list models: {e}"


def _cmd_tools(request: Request) -> str:
    tools = getattr(request.app.state, "tools", [])
    if not tools:
        return "No tools are currently loaded."
    lines = [f"**Loaded tools ({len(tools)}):**\n"]
    for t in tools:
        name = getattr(t, "name", None) or str(t)
        desc = getattr(t, "description", "") or ""
        if desc:
            lines.append(f"- **{name}** \u2014 {desc}")
        else:
            lines.append(f"- **{name}**")
    return "\n".join(lines)


async def _cmd_restart(request: Request) -> str:
    """Restart the Copilot SDK client."""
    try:
        await _restart_client(request)
        return (
            "\u2705 **Copilot SDK client restarted.**\n\n"
            "Type **status** to check the current state."
        )
    except Exception as e:
        logger.exception("Admin: failed to restart client")
        return f"\u274c **Failed to restart client:** {e}"


# ------------------------------------------------------------------
# Command parser
# ------------------------------------------------------------------

def _parse_command(messages: list[dict]) -> tuple[str, str]:
    """Parse the command and any argument from the last user message.

    Returns (command, argument) where command is one of the recognized
    commands and argument is the remaining text (e.g. the token in
    ``auth token ghp_xxx``).
    """
    text = _get_last_user_text(messages)
    lower = text.lower().strip()

    # Multi-word commands first (order matters)
    if lower.startswith("auth token"):
        rest = text[len("auth token"):].strip()
        return "auth_token", rest
    if lower.startswith("auth login"):
        return "auth_login", ""
    if lower.startswith("auth logout"):
        return "auth_logout", ""
    if lower.startswith("auth"):
        return "auth", ""

    # Single-word commands
    for cmd in ("restart", "status", "models", "tools", "help"):
        if lower.startswith(cmd):
            return cmd, ""

    # Follow-up token detection: if the previous assistant message
    # was the auth login instructions and the user's reply looks
    # like a token, treat it as ``auth_token``.
    if _is_follow_up_token(messages):
        token = _extract_token(text)
        if token:
            return "auth_token", token

    return "unknown", ""


async def _dispatch(
    command: str,
    arg: str,
    messages: list[dict],
    request: Request,
) -> str:
    """Run the appropriate command handler and return the response text."""
    if command == "auth":
        return await _cmd_auth(request)
    if command == "auth_login":
        return await _cmd_auth_login(messages, request)
    if command == "auth_token":
        return await _cmd_auth_token(arg, request)
    if command == "auth_logout":
        return await _cmd_auth_logout(request)
    if command == "status":
        return await _cmd_status(request)
    if command == "models":
        return await _cmd_models(request)
    if command == "tools":
        return _cmd_tools(request)
    if command == "restart":
        return await _cmd_restart(request)
    if command == "help":
        auth_ok = await _check_auth_ok()
        return _cmd_help(auth_ok)
    # Unknown — show welcome/help
    auth_ok = await _check_auth_ok()
    return _cmd_help(auth_ok)


# ------------------------------------------------------------------
# Public entry points (called from chat route)
# ------------------------------------------------------------------

async def handle_admin_blocking(
    messages: list[dict],
    request: Request,
) -> JSONResponse:
    """Handle a non-streaming request to the admin model."""
    command, arg = _parse_command(messages)
    content = await _dispatch(command, arg, messages, request)
    response = make_chat_completion(model=ADMIN_MODEL_ID, content=content)
    return JSONResponse(content=response)


async def handle_admin_streaming(
    messages: list[dict],
    request: Request,
):
    """Handle a streaming request to the admin model (SSE generator)."""
    command, arg = _parse_command(messages)
    content = await _dispatch(command, arg, messages, request)

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
# Auth helpers
# ------------------------------------------------------------------

async def _get_auth_info() -> dict:
    """Check auth status via the SDK. Returns a dict with status info."""
    try:
        from copilot_gateway.copilot.client import get_copilot_client
        client = await get_copilot_client()
        auth = await client.get_auth_status()
        return {
            "authenticated": auth.isAuthenticated,
            "login": auth.login,
            "auth_type": auth.authType,
            "host": auth.host,
            "message": auth.statusMessage or (
                "Authenticated" if auth.isAuthenticated else "Not authenticated"
            ),
        }
    except Exception as e:
        logger.debug("Admin: could not get auth status: %s", e)
        return {
            "authenticated": False,
            "message": "SDK client not available",
        }


async def _check_auth_ok() -> bool:
    """Quick check whether we're authenticated."""
    info = await _get_auth_info()
    return info["authenticated"]


def _has_stored_token(request: Request) -> bool:
    """Check if the gateway has a stored GitHub token."""
    return bool(getattr(request.app.state, "github_token", None))


_TOKEN_PATTERN = re.compile(
    r'(ghp_[A-Za-z0-9_]{36,}|gho_[A-Za-z0-9_]{36,}|'
    r'ghu_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{22,})'
)


def _extract_token(text: str) -> str | None:
    """Try to extract a GitHub token from user text."""
    # Strip markdown code fences
    text = text.strip().strip("`").strip()

    # Match known GitHub token patterns
    match = _TOKEN_PATTERN.search(text)
    if match:
        return match.group(1)

    # If the whole text looks like a single token string (no spaces, 20+ chars)
    stripped = text.strip()
    if len(stripped) >= 20 and " " not in stripped and "\n" not in stripped:
        return stripped

    return None


def _is_follow_up_token(messages: list[dict]) -> bool:
    """Check if the last assistant message was auth login instructions."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str) and "auth token" in content.lower():
                return True
            break  # Only check the last assistant message
    return False


async def _store_token_and_restart(token: str, request: Request) -> str:
    """Store a GitHub token and restart the SDK client to use it."""
    request.app.state.github_token = token

    try:
        await _restart_client(request)

        # Verify auth works with the new token
        auth_info = await _get_auth_info()
        if auth_info["authenticated"]:
            login = auth_info.get("login", "unknown")
            return (
                f"\u2705 **Authenticated as @{login}!**\n\n"
                "Token stored. You can now use any model for chat.\n\n"
                "Type **models** to see available models."
            )
        else:
            msg = auth_info.get("message", "Unknown error")
            return (
                f"\u274c **Authentication failed:** {msg}\n\n"
                "The token was stored but authentication did not succeed. "
                "Check that your token is valid and has the **copilot** scope.\n\n"
                "Type **auth login** to try again."
            )
    except Exception as e:
        logger.exception("Admin: failed to restart client with new token")
        return f"\u274c **Error:** Could not restart client: {e}"


async def _restart_client(request: Request) -> None:
    """Restart the Copilot SDK client, optionally with a stored token."""
    import os

    from copilot_gateway.copilot.client import (
        get_copilot_client,
        shutdown_copilot_client,
    )
    from copilot_gateway.copilot.models import _clear_cache

    await shutdown_copilot_client()

    # Set or clear the token env var so the SDK picks it up
    token = getattr(request.app.state, "github_token", None)
    if token:
        os.environ["COPILOT_GITHUB_TOKEN"] = token
    else:
        os.environ.pop("COPILOT_GITHUB_TOKEN", None)

    # Re-initialize
    config = request.app.state.config
    await get_copilot_client(config)

    # Clear model cache so fresh models are fetched
    _clear_cache()


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def _get_last_user_text(messages: list[dict]) -> str:
    """Extract plain text from the last user message."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                return " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            return content or ""
    return ""


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
