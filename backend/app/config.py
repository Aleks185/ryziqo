"""Application configuration loaded strictly from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for #InvestWatch backend."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    data_dir: str = "../data"
    database_path: str = "../data/investwatch.db"
    object_store_dir: str = "../data/object_store"

    cors_origins: str = (
        "http://localhost:5173,http://localhost:3000,"
        "http://localhost:8080,http://127.0.0.1:5173"
    )

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"
    ollama_embed_model: str = "nomic-embed-text"
    # Larger prompts (sections + rubric + few-shot) and structured output need more time on CPU
    ollama_timeout_seconds: float = 60.0
    # Response token limit (reasoning + signals + exact quotes) and model context window
    ollama_num_predict: int = 768
    ollama_num_ctx: int = 8192
    # Vision (VLM) analysis of Playwright screenshots; requires a model with the "vision" capability
    ollama_vision_enabled: bool = False
    ollama_vision_model: str = ""

    # Character budget for page content sent to the LLM (split into hero / body / risk / links sections)
    ai_prompt_content_chars: int = 9000
    # Inject top-K verified incidents (confirmed + false positive) as dynamic few-shot examples
    ai_rag_few_shot_enabled: bool = True
    # Cosine similarity to a confirmed incident on another domain that marks a campaign clone
    ai_clone_similarity_threshold: float = 0.85
    # Require LLM quotes to exist in the source text before a semantic signal gets any weight
    ai_strict_quote_verification: bool = True
    # "primary": one incident per page (secondary detections summarized in evidence_quotes);
    # "all_significant": one incident per module with violations and risk_score >= the threshold below
    aggregator_multi_module_mode: str = "primary"
    aggregator_secondary_min_score: float = 0.55

    crawler_timeout_seconds: float = 12.0
    crawler_max_bytes: int = 2_097_152
    crawler_max_redirects: int = 5
    crawler_rate_limit_seconds: float = 0.5
    crawler_use_playwright_fallback: bool = False
    crawler_playwright_timeout_seconds: float = 20.0
    # Pages whose visible text (without scripts/styles) is shorter are re-rendered with Playwright
    crawler_playwright_min_text_chars: int = 400
    crawler_enable_scheduler: bool = True
    crawler_schedule_minutes: int = 15
    # Optional crontab expression ("*/30 * * * *"); overrides CRAWLER_SCHEDULE_MINUTES when set
    crawler_cron: str = ""
    # Re-scan local mock sources in each scheduled run (demo); watchlist targets are always scanned
    crawler_schedule_include_mocks: bool = True
    # Comma-separated proxy URLs rotated per request, e.g. "http://proxy1:3128,socks5://proxy2:1080"
    crawler_proxies: str = ""
    # Resolve link-shortener / link-in-bio URLs (bit.ly, linktr.ee, ...) to their final destination
    # (every hop re-validated by the anti-SSRF guard); destinations feed registry/warning-list checks
    crawler_expand_short_links: bool = False
    crawler_expand_short_links_max: int = 5
    # Cosine similarity above which a re-scanned page (same URL + module) updates the existing incident
    dedup_similarity_threshold: float = 0.92

    high_risk_alert_threshold: float = 0.65

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def crawler_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.crawler_proxies.split(",") if p.strip()]

    def resolve_path(self, raw_path: str) -> Path:
        p = Path(raw_path)
        if p.is_absolute():
            return p
        backend_root = Path(__file__).resolve().parent.parent
        return (backend_root / p).resolve()

    @property
    def resolved_data_dir(self) -> Path:
        return self.resolve_path(self.data_dir)

    @property
    def resolved_db_path(self) -> Path:
        return self.resolve_path(self.database_path)

    @property
    def resolved_object_store_dir(self) -> Path:
        return self.resolve_path(self.object_store_dir)

    @property
    def mock_sites_dir(self) -> Path:
        return self.resolved_data_dir / "mock_sites"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
