"""Claim retrieval endpoint.

GET /v1/claim/{id} — re-fetch a cached verdict for the Detail screen.
Not a history listing endpoint (there are no accounts).

The client persists the claim_id from a verdict response alongside its local
history row; without it this endpoint is uncallable (PRD §8).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.models.schemas import VerdictResponse
from app.db import verdicts as verdicts_db
from app.db import evidence as evidence_db
from app.routes._responses import verdict_response_from_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


@router.get("/claim/{claim_id}", response_model=VerdictResponse)
async def get_claim(claim_id: int) -> VerdictResponse:
    """Re-fetch a single cached verdict by claim_id (real DB lookup)."""
    row = await verdicts_db.get_full_verdict(claim_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No claim found for claim_id={claim_id}")

    evidence = await evidence_db.get_evidence_by_verdict_id(row["verdict_id"])

    # Reuse the shared mapper — the DB row already carries claim/claim_original/
    # source_lang under the state-style keys (see get_full_verdict).
    row["evidence_items"] = evidence
    response = verdict_response_from_state(row)
    logger.info("claims: serving claim_id=%d label=%s (%d evidence items)", claim_id, response.label, len(evidence))
    return response
