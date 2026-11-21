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
    ollama_timeout_seconds: float = 25.0

    crawler_timeout_seconds: float = 12.0
    crawler_max_bytes: int = 2_097_152
    crawler_max_redirects: int = 5
    crawler_rate_limit_seconds: float = 0.5
    crawler_use_playwright_fallback: bool = False
    crawler_enable_scheduler: bool = True
    crawler_schedule_minutes: int = 15
    # Optional crontab expression ("*/30 * * * *"); overrides CRAWLER_SCHEDULE_MINUTES when set
    crawler_cron: str = ""
    # Re-scan local mock sources in each scheduled run (demo); watchlist targets are always scanned
    crawler_schedule_include_mocks: bool = True
    # Comma-separated proxy URLs rotated per request, e.g. "http://proxy1:3128,socks5://proxy2:1080"
    crawler_proxies: str = ""
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
