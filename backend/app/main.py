"""FastAPI application entry point.

Assembles routes, configures lifespan (model loading, DB pool),
and sets up CORS + logging.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services import ml_models
from app.db import database
from app.routes import health, verify, claims

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)-30s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan: startup/shutdown logic ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle.

    Startup:
      1. Load ML models (embedding + NLI) — once, never per request
      2. Initialize database connection pool

    Shutdown:
      1. Close database pool
    """
    logger.info("═" * 60)
    logger.info("Rifo backend starting up")
    logger.info("═" * 60)

    # Load ML models at startup (constraint #9)
    await ml_models.load_models()

    # Initialize DB pool
    await database.init_db()

    logger.info("Startup complete — ready to accept requests")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await database.close_db()
    logger.info("Shutdown complete")


# ── FastAPI app ──
app = FastAPI(
    title="Rifo — Misinformation Verification API",
    description="Overlay-based claim verification system with LangGraph pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS (permissive for development) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routes ──
app.include_router(health.router)
app.include_router(verify.router)
app.include_router(claims.router)

logger.info("Routes registered: /health, /v1/verify, /v1/verify/stream, /v1/claim/{id}")
