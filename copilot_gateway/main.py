"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from copilot_gateway import __version__
from copilot_gateway.config import AppConfig, load_config
from copilot_gateway.copilot.client import get_copilot_client, shutdown_copilot_client
from copilot_gateway.middleware import APIKeyMiddleware
from copilot_gateway.routes import chat, health, models
from copilot_gateway.tools.registry import load_tools


_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    cfg = get_config()

    logging.basicConfig(
        level=getattr(logging, cfg.server.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("copilot_gateway")
    logger.info("Starting copilot-gateway v%s", __version__)
    logger.info("Default model: %s", cfg.copilot.default_model)

    if cfg.server.api_key:
        logger.info("API key authentication enabled")
    else:
        logger.warning("No API key configured — all requests will be accepted")

    # Load tool plugins
    tools = load_tools(cfg.tools.enabled)
    logger.info("Loaded %d tool(s)", len(tools))
    app.state.tools = tools
    app.state.config = cfg

    # Pre-initialize the Copilot client
    await get_copilot_client(cfg)

    yield

    # Shutdown
    await shutdown_copilot_client()
    logger.info("copilot-gateway stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="copilot-gateway",
        description="OpenAI-compatible API server powered by GitHub Copilot SDK",
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(APIKeyMiddleware)

    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(chat.router)

    return app


app = create_app()
