"""CopilotClient singleton — manages the SDK client lifecycle."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from copilot import CopilotClient, SubprocessConfig

if TYPE_CHECKING:
    from copilot_gateway.config import AppConfig

logger = logging.getLogger(__name__)

_client: CopilotClient | None = None
_started = False
_lock = asyncio.Lock()


async def get_copilot_client(config: AppConfig | None = None) -> CopilotClient:
    """Get or create the singleton CopilotClient.

    On first call, `config` must be provided. Subsequent calls can omit it.
    """
    global _client, _started

    if _client is not None and _started:
        return _client

    async with _lock:
        # Double-check after acquiring lock
        if _client is not None and _started:
            return _client

        if _client is None:
            kwargs: dict = {}
            if config and config.copilot.cli_path:
                kwargs["cli_path"] = config.copilot.cli_path

            idle_timeout = config.copilot.session_idle_timeout if config else 7200

            # Pick up token from env (may be set by admin auth flow)
            github_token = os.environ.get("COPILOT_GITHUB_TOKEN")

            # If COPILOT_LOGGED_OUT is set, disable CLI auto-login
            logged_out = os.environ.get("COPILOT_LOGGED_OUT") == "1"

            subprocess_config = SubprocessConfig(
                session_idle_timeout_seconds=idle_timeout,
                **({
                    "github_token": github_token,
                } if github_token else {}),
                **({
                    "use_logged_in_user": False,
                } if logged_out and not github_token else {}),
                **kwargs,
            )
            _client = CopilotClient(config=subprocess_config)
            logger.info("CopilotClient created")

        if not _started:
            await _client.start()
            _started = True
            logger.info("CopilotClient started")

    return _client


async def shutdown_copilot_client() -> None:
    """Shut down the singleton CopilotClient."""
    global _client, _started

    if _client is not None:
        try:
            await _client.stop()
        except Exception:
            logger.exception("Error stopping CopilotClient")
        _client = None
        _started = False
        logger.info("CopilotClient stopped")
