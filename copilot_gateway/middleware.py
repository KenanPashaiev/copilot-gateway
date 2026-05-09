"""Authentication middleware for API key validation."""

from __future__ import annotations

import hmac
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# Paths that don't require authentication
_PUBLIC_PATHS = {"/health"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token against the configured API key.

    If no API key is configured (empty string), all requests are allowed.
    """

    async def dispatch(self, request: Request, call_next):
        api_key: str = request.app.state.config.server.api_key

        if not api_key or request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = auth_header

        if not token or not hmac.compare_digest(token, api_key):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "Invalid or missing API key. "
                        "Provide a valid key via the Authorization header: "
                        "'Authorization: Bearer <key>'",
                        "type": "authentication_error",
                        "code": "invalid_api_key",
                    }
                },
            )

        return await call_next(request)
