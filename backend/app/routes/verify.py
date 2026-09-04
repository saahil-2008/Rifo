"""Verification endpoints.

WS   /v1/verify/stream  — primary path, progressive frames (FR-7)
POST /v1/verify          — sync fallback, full response

WebSocket streaming protocol:
  Client connects → sends JSON payload (three accepted shapes):

  1. Chrome extension — text path (skips vision_extract, enters at embed_claim):
       { "type": "text", "content": "<selected text>", "device_id": "..." }

  2. Chrome extension — image URL path (server fetches, full vision pipeline):
       { "type": "image", "image_url": "https://...", "device_id": "..." }

  3. Legacy Android client (still accepted for curl / wscat tests):
       { "image_b64": "<base64 JPEG>", "device_id": "..." }

  Server streams frames in order:
    1. {"stage":"extracted", ...}
    2. {"stage":"cache_hit"} or {"stage":"cache_miss"}
    3. {"stage":"verdict", ...}    ← extension card updates here
    4. {"stage":"evidence", ...}   ← card evidence list
    5. {"stage":"explanation", ...} ← card explanation
    6. {"stage":"done"}
  OR: {"stage":"error", "code":"...", "message":"..."}

The verdict frame is emitted BEFORE the explanation is generated (constraint
#13) and only after the final aggregate pass — the intermediate pass that
requests a retry emits nothing.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from app.models.schemas import (
    ExtensionRequest,
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

# ── Graph cache keyed by entry_node (compiled once per entry point) ──
# Two variants are needed:
#   "vision_extract" — full pipeline (legacy image_b64 + extension image-url)
#   "embed_claim"    — text shortcut (extension text path, skips vision_extract)
_graphs: dict[str, object] = {}


def _get_graph(entry_node: str = "vision_extract"):
    """Return the compiled graph for the given entry node, building it once."""
    if entry_node not in _graphs:
        _graphs[entry_node] = build_verification_graph(entry_node=entry_node)
    return _graphs[entry_node]


# ── WebSocket streaming endpoint (primary path) ──


@router.websocket("/verify/stream")
async def verify_stream(websocket: WebSocket) -> None:
    """WebSocket endpoint for progressive verification (FR-7).

    Accepts three request shapes — see module docstring for details.
    The extension card updates on the verdict frame; evidence and explanation
    stream in after. Every terminating path emits either `done` or `error`,
    never neither.
    """
    await websocket.accept()
    start_time = time.monotonic()

    async def send(obj) -> None:
        await websocket.send_text(obj.model_dump_json())

    try:
        raw = await websocket.receive_text()
        data = json.loads(raw)

        # ── Detect request shape and build initial pipeline state ──
        # entry_node controls where the graph starts; text input skips
        # vision_extract entirely (no model call, no base64 needed).
        entry_node = "vision_extract"  # default

        if "type" in data:
            # ── Chrome extension request ──
            ext_req = ExtensionRequest(**data)

            if ext_req.type == "text":
                # Text path: DOM already has the text; no screenshot needed.
                # Pre-fill claim fields and enter at embed_claim.
                content = (ext_req.content or "").strip()
                if not content:
                    await send(ErrorFrame(
                        code="no_claim_found",
                        message="Empty selection — nothing to verify",
                    ))
                    await websocket.close()
                    return

                logger.info(
                    "verify/stream: extension text request (device=%s, len=%d)",
                    ext_req.device_id, len(content),
                )

                initial_state: PipelineState = {
                    # Populate the fields that vision_extract would normally set
                    "claim": content,
                    "claim_original": content,
                    "source_lang": "en",  # extension operates on DOM text; browser already decoded it
                    "content_type": "text_message",
                    "has_image_content": False,
                    "checkable": True,
                    "device_id": ext_req.device_id,
                    "retry_count": 0,
                }
                entry_node = "embed_claim"  # skip vision_extract

            else:  # type == "image"
                # Image-URL path: fetch the image server-side, base64-encode,
                # then run the normal full pipeline through vision_extract.
                image_url = (ext_req.image_url or "").strip()
                if not image_url:
                    await send(ErrorFrame(
                        code="upload_failed",
                        message="No image URL provided",
                    ))
                    await websocket.close()
                    return

                logger.info(
                    "verify/stream: extension image-url request (device=%s, url=%.80s)",
                    ext_req.device_id, image_url,
                )

                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.get(image_url, follow_redirects=True)
                        resp.raise_for_status()
                        image_b64 = base64.b64encode(resp.content).decode()
                except Exception as fetch_err:
                    logger.warning("verify/stream: failed to fetch image URL: %s", fetch_err)
                    await send(ErrorFrame(
                        code="upload_failed",
                        message=f"Could not fetch image: {fetch_err}",
                    ))
                    await websocket.close()
                    return

                initial_state = {
                    "image_b64": image_b64,
                    "device_id": ext_req.device_id,
                    "retry_count": 0,
                }
                # entry_node stays "vision_extract"

        else:
            # ── Legacy Android / curl request (image_b64) ──
            request = VerifyRequest(**data)
            logger.info(
                "verify/stream: legacy image_b64 request (device=%s, image=%d bytes b64)",
                request.device_id,
                len(request.image_b64),
            )
            initial_state = {
                "image_b64": request.image_b64,
                "device_id": request.device_id,
                "retry_count": 0,
            }

        # ── Stream through the graph node by node ──
        graph = _get_graph(entry_node=entry_node)
        final_state: dict = {}

        # For extension text path: emit the extracted frame immediately
        # (cache_probe or embed_claim won't emit it since vision_extract was skipped).
        if entry_node == "embed_claim":
            await send(ExtractedFrame(
                claim=initial_state.get("claim", ""),
                claim_original=initial_state.get("claim_original", ""),
                source_lang=initial_state.get("source_lang", "en"),
            ))
            final_state.update(initial_state)

        async for event in graph.astream(initial_state, stream_mode="updates"):
            for node_name, node_output in event.items():
                if not node_output:
                    continue
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
                            text=final_state.get("explanation") or "",
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
