"""Verification endpoints.

WS   /v1/verify/stream  — primary path, progressive frames (FR-7)
POST /v1/verify          — sync fallback, full response

WebSocket streaming protocol:
  Client connects → sends JSON { image_b64, device_id }
  Server streams frames:
    1. {"stage":"extracted", ...}
    2. {"stage":"cache_hit"} or {"stage":"cache_miss"}
    3. {"stage":"verdict", ...}    ← bubble updates here
    4. {"stage":"evidence", ...}   ← Detail screen only
    5. {"stage":"explanation", ...} ← Detail screen only
    6. {"stage":"done"}
  OR: {"stage":"error", "code":"...", "message":"..."}

The verdict frame is emitted BEFORE the explanation is generated (constraint
#13) and only after the final aggregate pass — the intermediate pass that
requests a retry emits nothing.
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from app.models.schemas import (
    VerifyRequest,
    VerdictResponse,
    ExtractedFrame,
    CacheStatusFrame,
    VerdictFrame,
    EvidenceFrame,
    ExplanationFrame,
    DoneFrame,
    ErrorFrame,
)
from app.models.state import PipelineState
from app.graph.builder import build_verification_graph
from app.routes._responses import verdict_response_from_state, evidence_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")

# ── Build the graph once at module import ──
_graph = None


def _get_graph():
    """Lazy-init the compiled graph (built once, reused for all requests)."""
    global _graph
    if _graph is None:
        _graph = build_verification_graph()
    return _graph


# ── WebSocket streaming endpoint (primary path) ──


@router.websocket("/verify/stream")
async def verify_stream(websocket: WebSocket) -> None:
    """WebSocket endpoint for progressive verification (FR-7).

    The bubble updates on the verdict frame and ignores later frames; only the
    Detail screen consumes evidence/explanation. Every terminating path emits
    either `done` or `error`, never neither.
    """
    await websocket.accept()
    start_time = time.monotonic()

    async def send(obj) -> None:
        await websocket.send_text(obj.model_dump_json())

    try:
        raw = await websocket.receive_text()
        data = json.loads(raw)
        request = VerifyRequest(**data)

        logger.info(
            "verify/stream: received request (device=%s, image=%d bytes b64)",
            request.device_id,
            len(request.image_b64),
        )

        # ── Build initial state ──
        initial_state: PipelineState = {
            "image_b64": request.image_b64,
            "device_id": request.device_id,
            "retry_count": 0,
        }

        # ── Stream through the graph node by node ──
        graph = _get_graph()
        final_state: dict = {}

        async for event in graph.astream(initial_state, stream_mode="updates"):
            for node_name, node_output in event.items():
                final_state.update(node_output)

                if node_name == "vision_extract":
                    if not node_output.get("checkable", True):
                        # Not checkable → error frame, no verdict (constraint #19b)
                        await send(ErrorFrame(
                            code="no_claim_found",
                            message="No verifiable claim found in the screenshot",
                        ))
                        await websocket.close()
                        return

                    # Emit extracted frame (must be present on BOTH paths, FR-7)
                    await send(ExtractedFrame(
                        claim=node_output.get("claim", ""),
                        claim_original=node_output.get("claim_original", ""),
                        source_lang=node_output.get("source_lang", "en"),
                    ))

                elif node_name == "cache_probe":
                    cached = node_output.get("cached", False)
                    await send(CacheStatusFrame(
                        stage="cache_hit" if cached else "cache_miss",
                    ))

                    if cached:
                        # Serve the cached verdict + evidence + explanation
                        # without retrieval or regeneration (constraint #15).
                        await send(VerdictFrame(
                            claim_id=final_state.get("claim_id", 0),
                            label=final_state.get("label", "insufficient"),
                            confidence=final_state.get("confidence", 0.0),
                            check_count=final_state.get("check_count", 0),
                        ))
                        await send(EvidenceFrame(
                            items=evidence_response(
                                final_state.get("stances")
                                or final_state.get("evidence_items")
                            ),
                        ))
                        await send(ExplanationFrame(
                            text=final_state.get("explanation", ""),
                        ))
                        await send(DoneFrame())

                elif node_name == "aggregate":
                    # An intermediate pass that requests a retry emits nothing;
                    # the verdict frame is sent only on the final pass.
                    if node_output.get("retry_requested"):
                        logger.info("verify/stream: aggregate requesting retry — no verdict yet")
                        continue

                    await send(VerdictFrame(
                        claim_id=final_state.get("claim_id", 0),
                        label=node_output.get("label", final_state.get("label", "insufficient")),
                        confidence=node_output.get("confidence", final_state.get("confidence", 0.0)),
                        check_count=final_state.get("check_count", 1),
                    ))
                    await send(EvidenceFrame(
                        items=evidence_response(
                            final_state.get("stances")
                            or final_state.get("evidence_items")
                        ),
                    ))

                elif node_name == "localize":
                    # Explanation is generated by the explain node and streamed
                    # after the verdict (constraint #13).
                    await send(ExplanationFrame(
                        text=final_state.get(
                            "explanation_localized",
                            final_state.get("explanation", ""),
                        ),
                    ))
                    elapsed = time.monotonic() - start_time
                    logger.info("verify/stream: completed in %.2fs", elapsed)
                    await send(DoneFrame())

    except WebSocketDisconnect:
        logger.info("verify/stream: client disconnected")
    except json.JSONDecodeError as e:
        await send(ErrorFrame(code="upload_failed", message=f"Invalid JSON: {e}"))
        await websocket.close()
    except Exception as e:
        logger.exception("verify/stream: unexpected error")
        try:
            await send(ErrorFrame(code="timeout", message=str(e)))
            await websocket.close()
        except Exception:
            pass


# ── Sync POST endpoint (fallback) ──


@router.post("/verify", response_model=VerdictResponse)
async def verify_sync(request: VerifyRequest) -> VerdictResponse:
    """Synchronous verification — returns the full response in one shot.

    This is the fallback path when WebSocket is not available.
    """
    logger.info(
        "verify: sync request (device=%s, image=%d bytes b64)",
        request.device_id,
        len(request.image_b64),
    )

    initial_state: PipelineState = {
        "image_b64": request.image_b64,
        "device_id": request.device_id,
        "retry_count": 0,
    }

    graph = _get_graph()
    result = await graph.ainvoke(initial_state)

    # Check for non-checkable claim (constraint #19b: never a verdict)
    if not result.get("checkable", True):
        raise HTTPException(
            status_code=422,
            detail={"code": "no_claim_found", "message": "No verifiable claim found"},
        )

    return verdict_response_from_state(result)
