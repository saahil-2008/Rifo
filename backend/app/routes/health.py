"""Health check endpoint.

GET /health — readiness probe including model-loaded status.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import HealthResponse
from app.services import ml_models
from app.db import database

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Readiness check including model and database status."""
    return HealthResponse(
        status="ok",
        embedding_model_loaded=ml_models.embedding_is_loaded(),
        nli_model_loaded=ml_models.nli_is_loaded(),
        database_connected=database.is_connected(),
    )
