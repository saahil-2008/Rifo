"""NLI stance classification node.

Batch-processes all (claim, evidence_snippet) pairs through mDeBERTa-v3-base-xnli
in a single forward pass. Outputs: supports / refutes / neutral per pair.

Model is loaded once at FastAPI startup — never per request (constraint #9).
"""

from __future__ import annotations

import logging

from app.models.state import PipelineState
from app.services.ml_models import classify_nli

logger = logging.getLogger(__name__)


async def nli_stance(state: PipelineState) -> PipelineState:
    """Classify the stance of each evidence item against the claim.

    Uses mDeBERTa-v3-base-xnli with a single batched forward pass
    across all (evidence_snippet, claim) pairs.
    """
    claim = state.get("claim", "")
    evidence_items = state.get("evidence_items", [])[:3]

    if not evidence_items:
        logger.warning("nli_stance: no evidence items to classify")
        return {"stances": []}

    logger.info("nli_stance: classifying %d evidence items", len(evidence_items))

    # Build premise/hypothesis pairs for batch NLI
    premises = []
    hypotheses = []
    for item in evidence_items:
        # Combine title + snippet as the premise. When the retrieve node
        # translated a non-English snippet, snippet_en holds the English form
        # (the NLI model judges languages it understands).
        snippet = item.get("snippet_en") or item.get("snippet", "")
        premise = f"{item.get('title', '')}. {snippet}"
        premises.append(premise)
        hypotheses.append(claim)

    try:
        # Single batched forward pass (constraint: never per-item)
        nli_results = classify_nli(premises, hypotheses)

        # Merge NLI results into evidence items
        stanced_items = []
        for i, item in enumerate(evidence_items):
            stanced_item = {
                **item,
                "stance": nli_results[i]["stance"],
                "stance_score": nli_results[i]["stance_score"],
            }
            stanced_items.append(stanced_item)

        logger.info(
            "nli_stance: classified %d items — supports=%d refutes=%d neutral=%d",
            len(stanced_items),
            sum(1 for s in stanced_items if s["stance"] == "supports"),
            sum(1 for s in stanced_items if s["stance"] == "refutes"),
            sum(1 for s in stanced_items if s["stance"] == "neutral"),
        )

        return {"stances": stanced_items}

    except Exception as e:
        logger.error("nli_stance: classification failed: %s", e)
        # Fallback: mark all as neutral
        stanced_items = [{**item, "stance": "neutral", "stance_score": 0.5} for item in evidence_items]
        return {"stances": stanced_items}
