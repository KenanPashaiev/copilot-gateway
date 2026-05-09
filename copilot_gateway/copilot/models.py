"""Model list caching for the Copilot SDK."""

from __future__ import annotations

import asyncio
import logging
import time

from copilot_gateway.copilot.client import get_copilot_client

logger = logging.getLogger(__name__)

_cache: list[dict] | None = None
_cache_time: float = 0
_cache_lock = asyncio.Lock()


async def list_models(cache_ttl: int = 300) -> list[dict]:
    """Fetch available models from the Copilot SDK, with caching.

    Returns a list of dicts in OpenAI format:
        [{"id": "gpt-4o", "object": "model", "owned_by": "copilot"}, ...]
    """
    global _cache, _cache_time

    now = time.monotonic()
    if _cache is not None and (now - _cache_time) < cache_ttl:
        return _cache

    async with _cache_lock:
        # Double-check after acquiring lock
        now = time.monotonic()
        if _cache is not None and (now - _cache_time) < cache_ttl:
            return _cache

        client = await get_copilot_client()

        try:
            raw_models = await client.list_models()
            models = []
            for m in raw_models:
                model_id = m.id if hasattr(m, "id") else str(m)
                models.append({
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "copilot",
                })
            _cache = models
            _cache_time = now
            logger.info("Refreshed model list: %d models", len(models))
        except Exception:
            logger.exception("Failed to list models from Copilot SDK")
            if _cache is not None:
                return _cache
            _cache = []
            _cache_time = now

        return _cache


def invalidate_cache() -> None:
    """Force the model cache to refresh on next call."""
    global _cache, _cache_time
    _cache = None
    _cache_time = 0
