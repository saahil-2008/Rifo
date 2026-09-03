"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central configuration — all values come from environment variables or .env file."""

    # ── Database ──
    database_url: str = Field(
        default="postgresql://rifo:rifo_dev_password@localhost:5432/rifo",
        description="PostgreSQL connection string",
    )

    # ── Vision extraction (Gemini 2.0 Flash) ──
    gemini_api_key: str = Field(default="", description="Google AI API key for Gemini")

    # ── Explanation + localization (Claude Opus 5 / GPT 5.6 Sol) ──
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    openai_api_key: str = Field(default="", description="OpenAI API key")

    # ── Search APIs ──
    # Wikipedia API is free and requires no key
    serpapi_key: str = Field(default="", description="SerpApi key for Google Lens")
    google_factcheck_api_key: str = Field(
        default="", description="Google Fact Check Tools API key"
    )

    # ── Model names ──
    vision_model: str = Field(
        default="gemini-2.0-flash",
        description="Fast-tier vision model for extraction",
    )
    explanation_model: str = Field(
        default="claude-opus-5",
        description="Flagship model for explanation generation",
    )
    explanation_fallback_model: str = Field(
        default="gpt-5.6-sol",
        description="Fallback flagship model for explanation",
    )
    embedding_model: str = Field(
        default="intfloat/multilingual-e5-small",
        description="Multilingual embedding model (384-dim)",
    )
    nli_model: str = Field(
        default="MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        description="Multilingual NLI model",
    )

    # ── Cache thresholds ──
    cache_similarity_threshold: float = Field(
        default=0.93,
        description="Cosine similarity threshold for cache hits. Do NOT lower below 0.93.",
    )
    cache_ttl_breaking_hours: int = Field(
        default=6,
        description="TTL in hours for breaking-news claims",
    )
    cache_ttl_settled_days: int = Field(
        default=30,
        description="TTL in days for settled/historical claims",
    )

    # ── Server ──
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton — import this everywhere
settings = Settings()
