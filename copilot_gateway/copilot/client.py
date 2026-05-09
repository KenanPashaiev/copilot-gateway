"""CopilotClient singleton — re-exported for convenience."""

from copilot_gateway.copilot import get_copilot_client, shutdown_copilot_client

__all__ = ["get_copilot_client", "shutdown_copilot_client"]
