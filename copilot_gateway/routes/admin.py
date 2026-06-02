"""Virtual 'copilot-gateway-admin' model — coded interactive config wizard.

This is NOT backed by an LLM. It parses simple commands from the user's
last message and returns canned responses in OpenAI chat-completion format.
Works even when the gateway has no Copilot authentication configured.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
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
        "name": "\u2699\ufe0f Gateway Admin",
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
        login = auth_info.get("login") or "unknown"
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
    """Start the GitHub device flow."""
    client_id = request.app.state.config.copilot.github_client_id
    if not client_id:
        return (
            "\u274c **Device flow not configured.**\n\n"
            "Set `copilot.github_client_id` in your config to enable "
            "interactive login."
        )

    try:
        device = await _start_device_flow(client_id)
    except Exception as e:
        logger.exception("Admin: device flow start failed")
        return f"\u274c **Failed to start device flow:** {e}"

    # Store pending flow on app state
    request.app.state.pending_device_flow = {
        "device_code": device["device_code"],
        "user_code": device["user_code"],
        "verification_uri": device["verification_uri"],
        "interval": device.get("interval", 5),
        "expires_at": time.time() + device.get("expires_in", 900),
        "client_id": client_id,
    }

    uri = device["verification_uri"]
    code = device["user_code"]
    return (
        "**GitHub Device Login**\n\n"
        f"1. Go to: **[{uri}]({uri})**\n"
        f"2. Enter code: **`{code}`**\n"
        f"3. Authorize the application\n\n"
        "Once done, type **check** and I'll complete the login."
    )


async def _cmd_auth_check(request: Request) -> str:
    """Poll GitHub for the device flow token."""
    pending = getattr(request.app.state, "pending_device_flow", None)
    if not pending:
        return (
            "No pending login. Type **auth login** to start."
        )

    if time.time() > pending["expires_at"]:
        request.app.state.pending_device_flow = None
        return (
            "\u274c **Login expired.** The code is no longer valid.\n\n"
            "Type **auth login** to get a new code."
        )

    try:
        result = await _poll_device_flow(
            pending["client_id"],
            pending["device_code"],
        )
    except Exception as e:
        logger.exception("Admin: device flow poll failed")
        return f"\u274c **Error checking login:** {e}"

    if result.get("access_token"):
        # Success — store token and restart
        request.app.state.pending_device_flow = None
        return await _store_token_and_restart(
            result["access_token"], request
        )

    error = result.get("error", "")
    if error == "authorization_pending":
        uri = pending["verification_uri"]
        code = pending["user_code"]
        return (
            "\u23f3 **Waiting for authorization...**\n\n"
            f"Go to **[{uri}]({uri})** and enter code: **`{code}`**\n\n"
            "Type **check** again after you've authorized."
        )
    if error == "slow_down":
        return "\u23f3 **Please wait a moment**, then type **check** again."
    if error == "expired_token":
        request.app.state.pending_device_flow = None
        return (
            "\u274c **Code expired.** Type **auth login** to get a new one."
        )
    if error == "access_denied":
        request.app.state.pending_device_flow = None
        return "\u274c **Authorization was denied.** Type **auth login** to try again."

    # Unknown error
    request.app.state.pending_device_flow = None
    desc = result.get("error_description", error)
    return f"\u274c **Login failed:** {desc}"


async def _cmd_auth_logout(request: Request) -> str:
    """Clear stored token and/or disconnect CLI credentials."""
    had_token = _has_stored_token(request)
    request.app.state.github_token = None
    request.app.state.logged_out = True
    await _restart_client(request)

    # Verify we're actually logged out
    auth_info = await _get_auth_info()
    if auth_info["authenticated"]:
        return (
            "\u26a0\ufe0f **Client restarted but still authenticated.**\n\n"
            "The CLI may have cached credentials. "
            "Type **auth** to check the current status."
        )

    msg = "\u2705 **Logged out and client restarted.**"
    if had_token:
        msg += " Stored token cleared."
    msg += "\n\nType **auth login** to reconnect."
    return msg


async def _cmd_status(request: Request) -> str:
    config = request.app.state.config
    start_time: float = getattr(request.app.state, "start_time", 0)
    uptime = _format_uptime(time.time() - start_time) if start_time else "unknown"
    tools = getattr(request.app.state, "tools", [])
    tool_count = len(tools)

    auth_info = await _get_auth_info()
    if auth_info["authenticated"]:
        login = auth_info.get("login") or "unknown"
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
    if lower.startswith("auth login"):
        return "auth_login", ""
    if lower.startswith("auth logout"):
        return "auth_logout", ""
    if lower.startswith("auth"):
        return "auth", ""

    # Single-word commands
    for cmd in ("check", "restart", "status", "models", "tools", "help"):
        if lower.startswith(cmd):
            return cmd, ""

    # If there's a pending device flow, treat any message as "check"
    if _has_pending_device_flow(messages):
        return "check", ""

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
    if command == "check":
        return await _cmd_auth_check(request)
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

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Initial role chunk
    initial = make_stream_chunk(chunk_id, ADMIN_MODEL_ID, role="assistant")
    yield f"data: {json.dumps(initial)}\n\n"

    # auth_login gets a special live-polling stream
    if command == "auth_login":
        async for piece in _stream_auth_login(request):
            chunk = make_stream_chunk(chunk_id, ADMIN_MODEL_ID, delta_content=piece)
            yield f"data: {json.dumps(chunk)}\n\n"
    else:
        content = await _dispatch(command, arg, messages, request)
        chunk_size = 20
        for i in range(0, len(content), chunk_size):
            piece = content[i:i + chunk_size]
            chunk = make_stream_chunk(chunk_id, ADMIN_MODEL_ID, delta_content=piece)
            yield f"data: {json.dumps(chunk)}\n\n"

    # Final chunk
    final = make_stream_chunk(chunk_id, ADMIN_MODEL_ID, finish_reason="stop")
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


async def _stream_auth_login(request: Request):
    """Async generator: start device flow, poll until authorized, yield text."""
    client_id = request.app.state.config.copilot.github_client_id
    if not client_id:
        yield (
            "\u274c **Device flow not configured.**\n\n"
            "Set `copilot.github_client_id` in your config to enable "
            "interactive login."
        )
        return

    try:
        device = await _start_device_flow(client_id)
    except Exception as e:
        logger.exception("Admin: device flow start failed")
        yield f"\u274c **Failed to start device flow:** {e}"
        return

    uri = device["verification_uri"]
    code = device["user_code"]
    device_code = device["device_code"]
    interval = device.get("interval", 5)
    expires_in = device.get("expires_in", 900)
    deadline = time.time() + expires_in

    # Stream the instructions
    yield (
        "**GitHub Device Login**\n\n"
        f"1. Go to: **[{uri}]({uri})**\n"
        f"2. Enter code: **`{code}`**\n"
        f"3. Authorize the application\n\n"
        "Waiting for authorization"
    )

    # Poll until authorized, expired, or denied
    while time.time() < deadline:
        await asyncio.sleep(interval)
        yield "."

        try:
            result = await _poll_device_flow(client_id, device_code)
        except Exception:
            logger.debug("Admin: poll error, will retry")
            continue

        if result.get("access_token"):
            # Success — store and restart
            token = result["access_token"]
            request.app.state.github_token = token
            request.app.state.logged_out = False
            try:
                await _restart_client(request)
                auth_info = await _get_auth_info()
                login = auth_info.get("login") or "unknown"
                yield (
                    f"\n\n\u2705 **Authenticated as @{login}!**\n\n"
                    "Token stored. You can now use any model for chat.\n\n"
                    "Type **models** to see available models."
                )
            except Exception as e:
                logger.exception("Admin: restart after auth failed")
                yield f"\n\n\u274c **Error restarting client:** {e}"
            return

        error = result.get("error", "")
        if error == "slow_down":
            interval += 5
        elif error == "expired_token":
            yield (
                "\n\n\u274c **Code expired.**\n\n"
                "Start a new chat and type **auth login** to try again."
            )
            return
        elif error == "access_denied":
            yield (
                "\n\n\u274c **Authorization was denied.**\n\n"
                "Start a new chat and type **auth login** to try again."
            )
            return
        elif error != "authorization_pending":
            desc = result.get("error_description", error)
            yield f"\n\n\u274c **Login failed:** {desc}"
            return

    # Timed out
    yield (
        "\n\n\u274c **Timed out** waiting for authorization.\n\n"
        "Start a new chat and type **auth login** to try again."
    )


# ------------------------------------------------------------------
# Auth helpers
# ------------------------------------------------------------------

async def _get_auth_info() -> dict:
    """Check auth status via the SDK. Returns a dict with status info."""
    try:
        from copilot_gateway.copilot.client import get_copilot_client
        client = await get_copilot_client()
        auth = await client.get_auth_status()
        login = auth.login

        # The SDK may return login=None for token-based auth;
        # fall back to the GitHub API to resolve the username.
        if auth.isAuthenticated and not login:
            login = await _fetch_github_login()

        return {
            "authenticated": auth.isAuthenticated,
            "login": login,
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


async def _fetch_github_login() -> str | None:
    """Resolve the GitHub username using the stored token."""
    token = os.environ.get("COPILOT_GITHUB_TOKEN")
    if not token:
        return None
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/json",
                "User-Agent": "copilot-gateway",
            },
        )

        def _do():
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())

        data = await asyncio.to_thread(_do)
        return data.get("login")
    except Exception:
        logger.debug("Admin: could not fetch GitHub login")
        return None


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


def _has_pending_device_flow(messages: list[dict]) -> bool:
    """Check if the last assistant message was a device flow prompt."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str) and "type **check**" in content.lower():
                return True
            break
    return False


async def _store_token_and_restart(token: str, request: Request) -> str:
    """Store a GitHub token and restart the SDK client to use it."""
    request.app.state.github_token = token
    request.app.state.logged_out = False

    try:
        await _restart_client(request)

        # Verify auth works with the new token
        auth_info = await _get_auth_info()
        if auth_info["authenticated"]:
            login = auth_info.get("login") or "unknown"
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
        os.environ.pop("COPILOT_LOGGED_OUT", None)
    else:
        os.environ.pop("COPILOT_GITHUB_TOKEN", None)

    # If logged out, tell the SDK not to use CLI's stored credentials
    if getattr(request.app.state, "logged_out", False) and not token:
        os.environ["COPILOT_LOGGED_OUT"] = "1"
    else:
        os.environ.pop("COPILOT_LOGGED_OUT", None)

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


# ------------------------------------------------------------------
# GitHub Device Flow
# ------------------------------------------------------------------

_DEVICE_CODE_URL = "https://github.com/login/device/code"
_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"


async def _start_device_flow(client_id: str) -> dict:
    """Start a GitHub device authorization flow.

    Returns a dict with device_code, user_code, verification_uri, etc.
    """
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "scope": "copilot",
    }).encode()

    req = urllib.request.Request(
        _DEVICE_CODE_URL,
        data=data,
        headers={"Accept": "application/json"},
    )

    def _do_request():
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    return await asyncio.to_thread(_do_request)


async def _poll_device_flow(client_id: str, device_code: str) -> dict:
    """Poll GitHub for the access token.

    Returns a dict with either access_token or error.
    """
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }).encode()

    req = urllib.request.Request(
        _ACCESS_TOKEN_URL,
        data=data,
        headers={"Accept": "application/json"},
    )

    def _do_request():
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    return await asyncio.to_thread(_do_request)
