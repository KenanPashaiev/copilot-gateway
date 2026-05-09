"""CopilotClient singleton — manages the SDK client lifecycle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from copilot import CopilotClient, SubprocessConfig

if TYPE_CHECKING:
    from copilot_gateway.config import AppConfig

logger = logging.getLogger(__name__)

_client: CopilotClient | None = None
_started = False


async def get_copilot_client(config: AppConfig | None = None) -> CopilotClient:
    """Get or create the singleton CopilotClient.

    On first call, `config` must be provided. Subsequent calls can omit it.
    """
    global _client, _started

    if _client is not None and _started:
        return _client

    if _client is None:
        subprocess_config = SubprocessConfig()
        if config and config.copilot.cli_path:
            subprocess_config = SubprocessConfig(cli_path=config.copilot.cli_path)

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
