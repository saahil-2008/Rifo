"""ML model loader — singleton pattern.

Loads multilingual-e5-small (embedding) and mDeBERTa-v3-base-xnli (NLI)
once at FastAPI startup. Models stored at module level — never loaded
per request (constraint #9).
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level singletons — populated by load_models()
embedding_model = None
nli_model = None
nli_tokenizer = None
embedding_loaded = False
nli_loaded = False
_device = "cpu"


async def load_models() -> None:
    """Load ML models at startup. Called from FastAPI lifespan.

    Loads:
    - multilingual-e5-small (384-dim embeddings, multilingual)
    - mDeBERTa-v3-base-xnli (NLI, multilingual)
    """
    global embedding_model, nli_model, nli_tokenizer, _device
    global embedding_loaded, nli_loaded

    import torch
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("ml_models: using device '%s'", _device)

    # ── Load embedding model ──
    logger.info("ml_models: loading embedding model '%s'...", settings.embedding_model)
    embedding_model = SentenceTransformer(settings.embedding_model, device=_device)
    embedding_loaded = True
    logger.info("ml_models: embedding model loaded (dim=%d)", embedding_model.get_sentence_embedding_dimension())

    # ── Load NLI model ──
    logger.info("ml_models: loading NLI model '%s'...", settings.nli_model)
    nli_tokenizer = AutoTokenizer.from_pretrained(settings.nli_model)
    nli_model = AutoModelForSequenceClassification.from_pretrained(settings.nli_model)
    nli_model.to(_device)
    nli_model.eval()
    nli_loaded = True
    logger.info("ml_models: NLI model loaded")


def embed_text(text: str) -> list[float]:
    """Embed a single text string using multilingual-e5-small.

    IMPORTANT: E5 models require a "query: " prefix for optimal performance.

    Args:
        text: The text to embed (English-normalized claim).

    Returns:
        384-dimensional embedding vector as a list of floats.
    """
    if embedding_model is None:
        raise RuntimeError("Embedding model not loaded. Call load_models() first.")

    # E5 requires "query: " prefix
    prefixed = f"query: {text}"
    vector = embedding_model.encode(prefixed, normalize_embeddings=True)
    return vector.tolist()


def classify_nli(premises: list[str], hypotheses: list[str]) -> list[dict]:
    """Batch NLI classification of (premise, hypothesis) pairs.

    Single forward pass through mDeBERTa-v3-base-xnli.
    Returns supports/refutes/neutral with scores for each pair.

    Args:
        premises: List of evidence snippets.
        hypotheses: List of claims (same claim repeated).

    Returns:
        List of dicts with keys: stance, stance_score.
    """
    if nli_model is None or nli_tokenizer is None:
        raise RuntimeError("NLI model not loaded. Call load_models() first.")

    import torch

    # Tokenize all pairs in a single batch
    inputs = nli_tokenizer(
        premises,
        hypotheses,
        padding=True,
        truncation=True,
        max_length=128,
        return_tensors="pt",
    ).to(_device)

    # Single forward pass with inference_mode for max CPU throughput
    with torch.inference_mode():
        outputs = nli_model(**inputs)

    # mDeBERTa label order: 0=contradiction, 1=neutral, 2=entailment
    probs = torch.softmax(outputs.logits, dim=-1).cpu().numpy()

    LABEL_MAP = {0: "refutes", 1: "neutral", 2: "supports"}

    results = []
    for i in range(len(premises)):
        predicted_idx = int(probs[i].argmax())
        results.append({
            "stance": LABEL_MAP[predicted_idx],
            "stance_score": float(probs[i][predicted_idx]),
        })

    return results


def is_loaded() -> bool:
    """Check if models are loaded."""
    return embedding_loaded and nli_loaded


def embedding_is_loaded() -> bool:
    """Check if the embedding model is loaded."""
    return embedding_loaded


def nli_is_loaded() -> bool:
    """Check if the NLI model is loaded."""
    return nli_loaded
