"""Pydantic models for API request/response contracts (PRD §8)."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Request ──


class VerifyRequest(BaseModel):
    """Request body for POST /v1/verify and WS /v1/verify/stream."""

    image_b64: str = Field(..., description="Base64-encoded downscaled JPEG screenshot, under 200KB")
    device_id: str = Field(..., description="Anonymous device UUID for viral counter only")


# ── Response sub-models ──


class EvidenceItemResponse(BaseModel):
    """A single evidence card in the response."""

    url: str
    domain: str
    title: str
    snippet: str
    stance: str  # "supports" | "refutes" | "neutral"
    stance_score: float
    published_at: str | None = None
    credibility: float


class VerdictResponse(BaseModel):
    """Full synchronous response from POST /v1/verify."""

    claim_id: int
    claim: str  # singular, never an array
    claim_original: str
    source_lang: str
    label: str  # genuine | misleading | fake | manipulated | insufficient
    confidence: float
    check_count: int
    first_seen: str  # ISO 8601
    cached: bool
    evidence: list[EvidenceItemResponse]
    explanation: str


# ── WebSocket streaming frames (FR-7) ──


class ExtractedFrame(BaseModel):
    """Emitted after vision extraction — must be present on BOTH cache-hit and miss paths."""

    stage: str = "extracted"
    claim: str
    claim_original: str
    source_lang: str


class CacheStatusFrame(BaseModel):
    """Emitted after cache probe."""

    stage: str  # "cache_hit" | "cache_miss"


class VerdictFrame(BaseModel):
    """Emitted BEFORE explanation — the bubble updates on this frame."""

    stage: str = "verdict"
    claim_id: int
    label: str
    confidence: float
    check_count: int


class EvidenceFrame(BaseModel):
    """Emitted after verdict, consumed by Detail screen only."""

    stage: str = "evidence"
    items: list[EvidenceItemResponse]


class ExplanationFrame(BaseModel):
    """Emitted last, consumed by Detail screen only."""

    stage: str = "explanation"
    text: str


class DoneFrame(BaseModel):
    """Terminal frame — every successful path must emit this."""

    stage: str = "done"


class ErrorFrame(BaseModel):
    """Terminal frame for errors."""

    stage: str = "error"
    code: str  # flag_secure | no_claim_found | upload_failed | timeout
    message: str


# ── Health ──


class HealthResponse(BaseModel):
    """Response from GET /health."""

    status: str = "ok"
    embedding_model_loaded: bool = False
    nli_model_loaded: bool = False
    database_connected: bool = False
