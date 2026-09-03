"""Integration harness for the verification graph (no vision key needed).

Drives the compiled graph starting AFTER vision extraction (entry node
``embed_claim``) with a synthetic claim state, against a live
Postgres/pgvector (docker-compose db). Requires internet for the Wikipedia
retrieval leg and one-time model downloads on first run.

Checks:
  A) A fresh claim  → cache miss → retrieve/NLI/aggregate → rows persisted.
  B) The same claim again → cache hit with incremented check_count and NO
     retrieval or explanation regeneration (constraint #15).
  C) A nonsense claim → the `insufficient` retry runs at most once and the
     graph terminates (regression for the infinite-retry bug).

Usage (from repo root, with the DB up):
    backend/venv/Scripts/python.exe scripts/dev_verify.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", "backend"))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.services import ml_models  # noqa: E402
from app.db import database  # noqa: E402
from app.graph.builder import build_verification_graph  # noqa: E402

# A claim Wikipedia has evidence about, so the pipeline has something to judge.
CLAIM = "The Eiffel Tower is located in London"
# Nonsense query — Wikipedia will return nothing, forcing the insufficient path.
GIBBERISH = "zqxwvjkl mnbvcxz qwerty 123456789 asdfgh jkl"

_CLAIM_KEYS = {
    "content_type": "text_message",
    "has_image_content": False,
    "checkable": True,
    "device_id": "dev-harness",
}


def make_state(claim: str) -> dict:
    state = dict(_CLAIM_KEYS)
    state.update(
        claim=claim,
        claim_original=claim,
        source_lang="en",
        retry_count=0,
    )
    return state


async def run_once(graph, state: dict, label: str) -> tuple[list[str], dict]:
    """Stream a state through the graph, returning (nodes_visited, final_state)."""
    nodes: list[str] = []
    final: dict = {}
    async for event in graph.astream(state, stream_mode="updates"):
        for node_name, node_output in event.items():
            nodes.append(node_name)
            final.update(node_output)
    print(f"  [{label}] nodes: {' → '.join(nodes) or '(none)'}")
    return nodes, final


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)-30s %(message)s",
    )
    for noisy in ("httpx", "transformers", "sentence_transformers", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    print("Loading embedding + NLI models (one-time download on first run)...")
    await ml_models.load_models()
    await database.init_db()
    print("Models loaded, DB pool initialized.\n")

    graph = build_verification_graph(entry_node="embed_claim")

    # ── Run A: fresh claim → miss → persisted ──
    print("=== RUN A: fresh claim (expect cache_miss + persistence) ===")
    nodes_a, final_a = await run_once(graph, make_state(CLAIM), "A")
    assert final_a.get("cached") is not True, "A fresh claim must not be a cache hit"
    assert final_a.get("claim_id"), "A final verdict should have produced a claim_id"
    print(f"  A: label={final_a.get('label')} confidence={final_a.get('confidence')} "
          f"claim_id={final_a.get('claim_id')}")

    # ── Run B: identical claim → cache hit, no retrieval ──
    print("=== RUN B: same claim again (expect cache_hit, count incremented) ===")
    nodes_b, final_b = await run_once(graph, make_state(CLAIM), "B")
    assert final_b.get("cached") is True, "The second identical claim must cache-hit"
    assert "retrieve" not in nodes_b, "A cache hit must not call retrieval"
    assert "nli_stance" not in nodes_b, "A cache hit must not run NLI"
    assert "explain" not in nodes_b, "A cache hit must not regenerate the explanation"
    count_a = final_a.get("check_count", 1)
    count_b = final_b.get("check_count", 0)
    print(f"  B: cached=True check_count={count_b} (was {count_a}) label={final_b.get('label')}")
    assert count_b > count_a, "check_count must increment on a cache hit"

    # ── Run C: nonsense → insufficient after at most one retry, terminates ──
    print("=== RUN C: nonsense claim (retry ≤ once, must terminate) ===")
    nodes_c, final_c = await run_once(graph, make_state(GIBBERISH), "C")
    agg_passes = nodes_c.count("aggregate")
    retrieve_calls = nodes_c.count("retrieve")
    print(f"  C: label={final_c.get('label')} aggregate_passes={agg_passes} retrieve_calls={retrieve_calls}")
    assert agg_passes <= 2, f"aggregate visited {agg_passes} times — infinite retry?"
    assert retrieve_calls <= 2, f"retrieve called {retrieve_calls} times — infinite retry?"

    print("\n✓ dev_verify: all assertions passed")
    await database.close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
