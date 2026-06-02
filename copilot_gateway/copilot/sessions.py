"""Session helpers — thin wrapper around the SDK's built-in session persistence.

The Copilot SDK already persists session state to disk on ``disconnect()``
and restores it on ``resume_session()``.  The SDK's CLI-level
``session_idle_timeout_seconds`` handles automatic cleanup of idle sessions.

This module provides convenience functions so the chat routes don't need to
deal with create-vs-resume logic directly.
"""

from __future__ import annotations

import asyncio
import logging

from copilot.session import CopilotSession, PermissionHandler

from copilot_gateway.copilot.client import get_copilot_client

logger = logging.getLogger(__name__)


async def get_or_create_session(
    session_id: str | None,
    *,
    model: str,
    system_message: str | None = None,
    tools: list | None = None,
    streaming: bool = False,
    excluded_tools: list[str] | None = None,
) -> tuple[CopilotSession, str, bool]:
    """Return a live ``CopilotSession`` and its session ID.

    If *session_id* is provided, the SDK's ``resume_session`` is tried first.
    If that fails (session expired/deleted) a new session is created with the
    same parameters.  When *session_id* is ``None`` a new session is always
    created and its SDK-assigned ID is returned.

    Returns ``(session, session_id, is_new)``.
    """
    client = await get_copilot_client()

    common_kwargs = _build_session_kwargs(
        model=model,
        system_message=system_message,
        tools=tools,
        streaming=streaming,
        excluded_tools=excluded_tools,
    )

    # Try to resume an existing session
    if session_id:
        try:
            session = await client.resume_session(
                session_id,
                **common_kwargs,
            )
            logger.debug("Resumed session %s", session_id)
            return session, session_id, False
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception:
            logger.debug(
                "Could not resume session %s, creating new",
                session_id,
                exc_info=True,
            )

    # Create a new session
    session = await client.create_session(**common_kwargs)
    logger.debug("Created session %s", session.session_id)
    return session, session.session_id, True


async def disconnect_session(session: CopilotSession) -> None:
    """Disconnect a session, preserving state on disk for later resumption."""
    try:
        await session.disconnect()
    except (asyncio.CancelledError, KeyboardInterrupt):
        raise
    except Exception:
        logger.debug("Error disconnecting session", exc_info=True)


def _build_session_kwargs(
    *,
    model: str,
    system_message: str | None,
    tools: list | None,
    streaming: bool,
    excluded_tools: list[str] | None = None,
) -> dict:
    """Build the kwargs dict shared by create_session / resume_session."""
    kwargs: dict = {
        "model": model,
        "on_permission_request": PermissionHandler.approve_all,
    }
    if system_message:
        kwargs["system_message"] = {"content": system_message}
    if tools:
        kwargs["tools"] = tools
    if streaming:
        kwargs["streaming"] = True
    if excluded_tools:
        kwargs["excluded_tools"] = excluded_tools
    return kwargs

