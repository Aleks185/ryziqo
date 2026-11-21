"""Open-source asyncio crawl queue worker + APScheduler periodic scheduler."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.ai.aggregator import run_analytical_pipeline
from app.ai.ollama_client import OllamaClient
from app.ai.preprocessor import preprocess_html
from app.config import Settings
from app.database import Database, utc_now_iso
from app.knf_registry import KNFRegistrySnapshot
from app.models import CrawlTriggerRequest, IncidentDetail, WebSocketAlertEvent
from app.scraper.fetcher import FetchedPage, PageFetcher
from app.ws_manager import AlertWebSocketManager

logger = logging.getLogger("investwatch.worker")


@dataclass
class QueuedTask:
    job_id: str
    request: CrawlTriggerRequest


class CrawlQueueWorker:
    """Processes crawl/analysis jobs asynchronously with deduplication and WebSocket telemetry."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        registry: KNFRegistrySnapshot,
        ollama: OllamaClient,
        fetcher: PageFetcher,
        ws_manager: AlertWebSocketManager,
    ) -> None:
        self.settings = settings
        self.db = db
        self.registry = registry
        self.ollama = ollama
        self.fetcher = fetcher
        self.ws_manager = ws_manager

        self._queue: asyncio.Queue[QueuedTask] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._scheduler: AsyncIOScheduler | None = None
        self._active_targets: set[str] = set()

    async def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._run_loop(), name="investwatch-crawl-worker")

        if self.settings.crawler_enable_scheduler and self._scheduler is None:
            self._scheduler = AsyncIOScheduler(timezone="UTC")
            self._scheduler.add_job(
                self._scheduled_mock_scan,
                trigger="interval",
                minutes=max(1, self.settings.crawler_schedule_minutes),
                id="periodic_mock_scan",
                replace_existing=True,
                max_instances=1,
            )
            self._scheduler.start()
            logger.info(
                "APScheduler uruchomiony (interwał: %d min).",
                self.settings.crawler_schedule_minutes,
            )

    async def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        if self._worker_task is not None and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    @property
    def scheduler_running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    @property
    def scheduler_next_run(self) -> str | None:
        if not self._scheduler:
            return None
        job = self._scheduler.get_job("periodic_mock_scan")
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
        return None

    async def _scheduled_mock_scan(self) -> None:
        """Periodic Cron/APScheduler job that scans local mock sources without duplicating active runs."""
        if "mock_all" in self._active_targets:
            logger.info("Pomijam cykliczny skan — poprzedni jeszcze trwa.")
            return
        await self.enqueue(CrawlTriggerRequest(mode="mock_all", module_ids=[1, 2, 3]))

    async def enqueue(self, req: CrawlTriggerRequest) -> str:
        target_key = req.target_url or req.mock_file or req.mode
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        self.db.create_crawl_job(job_id=job_id, mode=req.mode, target=target_key)
        self._active_targets.add(target_key)
        await self._queue.put(QueuedTask(job_id=job_id, request=req))

        await self.ws_manager.broadcast(
            WebSocketAlertEvent(
                type="crawler_status",
                timestamp=utc_now_iso(),
                job_id=job_id,
                stage="queued",
                source=target_key,
                message=f"Dodano zadanie {job_id} ({req.mode}) do kolejki analizy.",
            )
        )
        return job_id

    async def _run_loop(self) -> None:
        while True:
            task = await self._queue.get()
            target_key = task.request.target_url or task.request.mock_file or task.request.mode
            try:
                await self._process_job(task)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Błąd przetwarzania zadania %s: %s", task.job_id, exc)
                self.db.update_crawl_job(
                    task.job_id, status="failed", error_message=str(exc), finished=True
                )
                await self.ws_manager.broadcast(
                    WebSocketAlertEvent(
                        type="error",
                        timestamp=utc_now_iso(),
                        job_id=task.job_id,
                        stage="error",
                        source=target_key,
                        message=f"Błąd zadania {task.job_id}: {exc}",
                    )
                )
            finally:
                self._active_targets.discard(target_key)
                self._queue.task_done()

    async def _process_job(self, task: QueuedTask) -> None:
        job_id = task.job_id
        req = task.request
        self.db.update_crawl_job(job_id, status="running")

        # Refresh Ollama availability once per job
        await self.ollama.check_health()

        pages: list[FetchedPage] = []
        if req.mode == "mock_all":
            for fname in self.fetcher.list_mock_files():
                await self._emit_stage(job_id, "fetching", f"mock://{fname}", f"Pobieranie strony demo: {fname}")
                pages.append(await self.fetcher.fetch_mock_page(fname))
        elif req.mode == "mock_single":
            if not req.mock_file:
                raise ValueError("Tryb 'mock_single' wymaga pola 'mock_file'.")
            await self._emit_stage(
                job_id, "fetching", f"mock://{req.mock_file}", f"Pobieranie strony demo: {req.mock_file}"
            )
            pages.append(await self.fetcher.fetch_mock_page(req.mock_file))
        elif req.mode == "public_url":
            if not req.target_url:
                raise ValueError("Tryb 'public_url' wymaga pola 'target_url'.")
            await self._emit_stage(
                job_id, "fetching", req.target_url, f"Pobieranie URL (anty-SSRF): {req.target_url}"
            )
            pages.append(
                await self.fetcher.fetch_public_url(
                    req.target_url, use_playwright=req.use_playwright
                )
            )

        processed = 0
        created_or_updated = 0

        for page in pages:
            saved = await self.analyze_page(page, list(req.module_ids), job_id=job_id)
            created_or_updated += len(saved)
            processed += 1

        self.db.update_crawl_job(
            job_id,
            status="completed",
            processed_count=processed,
            incidents_created=created_or_updated,
            finished=True,
        )
        await self.ws_manager.broadcast(
            WebSocketAlertEvent(
                type="analysis_complete",
                timestamp=utc_now_iso(),
                job_id=job_id,
                stage="completed",
                source=req.target_url or req.mock_file or req.mode,
                message=(
                    f"Zakończono zadanie {job_id}: przeanalizowano {processed} źródeł, "
                    f"zapisano {created_or_updated} wyników."
                ),
                extra={"processed": processed, "incidents_saved": created_or_updated},
            )
        )

    async def analyze_page(
        self, page: FetchedPage, module_ids: list[int], job_id: str | None = None
    ) -> list[IncidentDetail]:
        """Preprocess, store and analyze one page; persist incidents and emit WebSocket alerts.

        Shared by the crawl queue and the synchronous /api/v1/analyze/* endpoints.
        Returns the incidents as stored in the database (existing analyst status/labels preserved).
        """
        await self._emit_stage(
            job_id,
            "preprocessing",
            page.source_url,
            f"Czyszczenie HTML, analiza DOM/CSS i wektoryzacja: {page.source_url}",
        )
        doc = preprocess_html(
            raw_html=page.raw_html,
            source_url=page.source_url,
            source_platform=page.source_platform,
            is_mock_source=page.is_mock_source,
            playwright_metrics=page.playwright_dom_metrics,
        )

        # Optionally upgrade embedding with local Ollama embeddings
        ollama_emb = await self.ollama.embed_text(doc.normalized_text)
        if ollama_emb:
            doc.embedding = ollama_emb

        storage_key = self.db.save_content_object(
            content_hash=doc.content_hash,
            source_url=doc.source_url,
            source_platform=doc.source_platform,
            raw_html=page.raw_html,
            normalized_text=doc.normalized_text,
            embedding=doc.embedding,
        )

        await self._emit_stage(
            job_id,
            "analyzing",
            page.source_url,
            f"Analiza AI/reguł (Moduły {module_ids}): {doc.title[:80]}",
        )
        incidents = await run_analytical_pipeline(
            doc=doc,
            module_ids=module_ids,
            registry=self.registry,
            ollama=self.ollama,
            storage_key=storage_key,
        )

        saved: list[IncidentDetail] = []
        for inc in incidents:
            # Deduplicate identical content_hash per module (update existing record instead of duplicating)
            existing_id = self.db.find_existing_incident_by_hash(inc.module_id, doc.content_hash)
            if existing_id:
                inc.id = existing_id
            self.db.upsert_incident(inc)
            stored = self.db.get_incident(inc.id)
            if stored is not None:
                saved.append(stored)

            if inc.risk_score >= self.settings.high_risk_alert_threshold:
                await self.ws_manager.broadcast(
                    WebSocketAlertEvent(
                        type="high_risk_alert",
                        timestamp=utc_now_iso(),
                        job_id=job_id,
                        stage="analyzing",
                        source=inc.source_url,
                        module_id=inc.module_id,
                        incident_id=inc.id,
                        risk_score=inc.risk_score,
                        message=(
                            f"ALERT wysokiego ryzyka ({inc.risk_score:.2f}) | "
                            f"Moduł {inc.module_id} | {inc.entity_name}: {inc.title[:90]}"
                        ),
                    )
                )
        return saved

    async def _emit_stage(self, job_id: str | None, stage: str, source: str, message: str) -> None:
        await self.ws_manager.broadcast(
            WebSocketAlertEvent(
                type="crawler_status",
                timestamp=utc_now_iso(),
                job_id=job_id,
                stage=stage,
                source=source,
                message=message,
            )
        )
