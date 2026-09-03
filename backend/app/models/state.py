"""LangGraph pipeline state definition.

This TypedDict is the single source of truth for all data flowing through
the verification graph. Every node reads from and writes to this state.
"""

from __future__ import annotations

from typing import TypedDict


class EvidenceItem(TypedDict, total=False):
    """A single piece of retrieved evidence."""

    url: str
    domain: str
    title: str
    snippet: str
    snippet_en: str  # English translation of a non-English snippet (pre-NLI)
    stance: str  # "supports" | "refutes" | "neutral"
    stance_score: float
    published_at: str  # ISO 8601
    credibility: float


class PipelineState(TypedDict, total=False):
    """Complete state for the verification pipeline.

    Fields are marked total=False because each node populates its own
    subset — the state builds up as the graph executes.
    """

    # ── Input (set by the route handler before graph invocation) ──
    image_b64: str
    device_id: str

    # ── Vision extraction (FR-4) ──
    claim: str  # normalized English claim (singular, never an array)
    claim_original: str  # source-language wording
    source_lang: str  # BCP-47 language code
    content_type: str  # text_message | news_article | social_post | image_with_caption | image_only | other
    has_image_content: bool  # true → reverse image search in retrieve gather
    checkable: bool  # false → short-circuit with no_claim_found error

    # ── Embedding (embed_claim node) ──
    embedding: list[float]  # 384-dim vector from multilingual-e5-small

    # ── Cache (cache_probe node) ──
    cached: bool
    claim_id: int  # DB primary key
    verdict_id: int  # DB primary key for the verdict row

    # ── Evidence (retrieve + factcheck nodes) ──
    evidence_items: list[EvidenceItem]
    # True when the Google Fact Check Tools leg found decisive reviews and
    # short-circuited to aggregate, skipping retrieve + nli_stance.
    factcheck_hit: bool

    # ── NLI stances (nli_stance node) ──
    # Each item mirrors EvidenceItem but with stance/stance_score populated by NLI
    stances: list[EvidenceItem]

    # ── Verdict (aggregate node) ──
    label: str  # genuine | misleading | fake | manipulated | insufficient
    confidence: float  # 0.0–1.0
    check_count: int
    first_seen: str  # ISO 8601

    # ── Reverse image search (retrieve node, image path only) ──
    earliest_url: str
    earliest_date: str  # ISO 8601

    # ── Explanation (explain node — post-verdict) ──
    explanation: str
    explanation_localized: str  # translated to source_lang

    # ── Localized verdict label ──
    label_localized: str

    # ── Control flow ──
    retry_count: int  # hard cap at 1
    # Explicit per-pass signal from aggregate: True → route back to retrieve
    # (broadened query); False → proceed to explain. Always set so the key never
    # lingers from a prior pass (LangGraph merges by key).
    retry_requested: bool
    error_code: str  # flag_secure | no_claim_found | upload_failed | timeout
    error_message: str

    # ── Verdict TTL ──
    expires_at: str  # ISO 8601
