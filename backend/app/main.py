"""#InvestWatch FastAPI entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.ai.ollama_client import OllamaClient
from app.config import Settings, get_settings
from app.database import Database
from app.knf_registry import KNFRegistrySnapshot
from app.models import HealthResponse
from app.queue_worker import CrawlQueueWorker
from app.routers import analyze, crawl, incidents, reports, watchlist, ws
from app.scraper.fetcher import PageFetcher
from app.ws_manager import AlertWebSocketManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("investwatch.main")


def create_app(custom_settings: Settings | None = None) -> FastAPI:
    settings = custom_settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(
            db_path=settings.resolved_db_path,
            object_store_dir=settings.resolved_object_store_dir,
        )
        db.init_schema()
        seeded = db.seed_demo_if_empty(settings.resolved_data_dir / "demo_incidents_seed.json")
        if seeded:
            logger.info("Załadowano %d demonstracyjnych incydentów startowych do SQLite.", seeded)

        registry = KNFRegistrySnapshot(
            snapshot_path=settings.resolved_data_dir / "knf_registry_snapshot.json",
            rules_path=settings.resolved_data_dir / "risk_criteria_rules.json",
        )
        ollama = OllamaClient(settings)
        await ollama.check_health()

        ws_manager = AlertWebSocketManager()
        fetcher = PageFetcher(settings)
        worker = CrawlQueueWorker(
            settings=settings,
            db=db,
            registry=registry,
            ollama=ollama,
            fetcher=fetcher,
            ws_manager=ws_manager,
        )
        await worker.start()

        app.state.settings = settings
        app.state.db = db
        app.state.registry = registry
        app.state.ollama = ollama
        app.state.ws_manager = ws_manager
        app.state.fetcher = fetcher
        app.state.worker = worker

        logger.info(
            "#InvestWatch backend gotowy | DB=%s | Ollama=%s (%s) | KNF snapshot=%s",
            settings.resolved_db_path,
            ollama.is_available,
            ollama.active_model,
            registry.snapshot_date,
        )
        try:
            yield
        finally:
            await worker.stop()

    app = FastAPI(
        title="#InvestWatch API — UKNF HackNation 2026",
        description=(
            "System monitoringu treści inwestycyjnych (Moduły 1–3: Finfluencerzy, "
            "18 kryteriów ryzyka MiFID II / 2017/565, Shadow Advisory art. 76 u.o.i.f.)."
        ),
        version="1.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(incidents.router)
    app.include_router(crawl.router)
    app.include_router(analyze.router)
    app.include_router(watchlist.router)
    app.include_router(reports.router)
    app.include_router(ws.router)

    @app.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
    async def health(request: Request) -> HealthResponse:
        ollama_client: OllamaClient = request.app.state.ollama
        await ollama_client.check_health()
        db_client: Database = request.app.state.db
        reg: KNFRegistrySnapshot = request.app.state.registry
        w: CrawlQueueWorker = request.app.state.worker
        return HealthResponse(
            status="ok",
            ollama_available=ollama_client.is_available,
            ollama_model=ollama_client.active_model,
            mode="live" if ollama_client.is_available else "demo_fallback",
            knf_snapshot_date=reg.snapshot_date,
            knf_snapshot_note=reg.disclaimer,
            incidents_count=db_client.count_incidents(),
            scheduler_running=w.scheduler_running,
        )

    return app


app = create_app()
