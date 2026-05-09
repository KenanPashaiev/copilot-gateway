"""Model listing endpoints: GET /v1/models, GET /v1/models/{model_id}."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from copilot_gateway.copilot.models import list_models as fetch_models

router = APIRouter(prefix="/v1")


@router.get("/models")
async def list_models(request: Request):
    config = request.app.state.config
    models = await fetch_models(cache_ttl=config.models.cache_ttl)
    return {
        "object": "list",
        "data": models,
    }


@router.get("/models/{model_id}")
async def get_model(model_id: str, request: Request):
    config = request.app.state.config
    models = await fetch_models(cache_ttl=config.models.cache_ttl)
    for m in models:
        if m["id"] == model_id:
            return m
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
