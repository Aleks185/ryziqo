"""Persistent crawl queue (SQLite-backed) + APScheduler periodic scheduler (interval or crontab)."""

from __future__ import annotations

import hashlib
import time
from app.analysis_queue import current_job

import asyncio
import logging
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.ai.aggregator import run_analytical_pipeline
from app.ai.context import AnalysisContext
from app.ai.ollama_client import OllamaClient
from app.ai.preprocessor import preprocess_html
from app.ai.retrieval import Retriever
from app.config import Settings
from app.database import Database, utc_now_iso
from app.knf_registry import KNFRegistrySnapshot
from app.models import CrawlTriggerRequest, IncidentDetail, WebSocketAlertEvent
from app.scraper.fetcher import FetchedPage, PageFetcher
from app.ws_manager import AlertWebSocketManager

logger = logging.getLogger("investwatch.worker")

SCHEDULER_JOB_ID = "periodic_scan"
QUEUE_POLL_SECONDS = 2.0


def _target_key(req: CrawlTriggerRequest) -> str:
    return req.target_url or req.mock_file or req.mode


class CrawlQueueWorker:
    """Processes crawl/analysis jobs from the `crawl_jobs` table with deduplication and WS telemetry.

    Jobs are persisted before they are processed, so a restart does not lose queued work:
    jobs interrupted mid-run are re-queued on startup.
    """

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
        self.retriever = Retriever(
            db,
            clone_threshold=settings.ai_clone_similarity_threshold,
            rag_enabled=settings.ai_rag_few_shot_enabled,
        )

        self._wakeup = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._scheduler: AsyncIOScheduler | None = None
        self._active_targets: set[str] = set()

    # --- lifecycle ---------------------------------------------------------------

    async def start(self) -> None:
        requeued = self.db.requeue_interrupted_crawl_jobs()
        if requeued:
            logger.info("Przywrócono %d przerwanych zadań do kolejki.", requeued)

        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._run_loop(), name="investwatch-crawl-worker")
            self._wakeup.set()

        if self.settings.crawler_enable_scheduler and self._scheduler is None:
            self._scheduler = AsyncIOScheduler(timezone="UTC")
            self._scheduler.add_job(
                self.scheduled_scan,
                trigger=self._build_trigger(),
                id=SCHEDULER_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            self._scheduler.start()
            logger.info("APScheduler uruchomiony (%s).", self.schedule_description)

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

    def _build_trigger(self) -> CronTrigger | IntervalTrigger:
        if self.settings.crawler_cron.strip():
            return CronTrigger.from_crontab(self.settings.crawler_cron.strip(), timezone="UTC")
        return IntervalTrigger(minutes=max(1, self.settings.crawler_schedule_minutes), timezone="UTC")

    @property
    def schedule_description(self) -> str:
        if not self.settings.crawler_enable_scheduler:
            return "disabled"
        if self.settings.crawler_cron.strip():
            return f"cron: {self.settings.crawler_cron.strip()} (UTC)"
        return f"interval: {max(1, self.settings.crawler_schedule_minutes)} min"

    @property
    def scheduler_running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    @property
    def scheduler_next_run(self) -> str | None:
        if not self._scheduler:
            return None
        job = self._scheduler.get_job(SCHEDULER_JOB_ID)
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
        return None

    # --- scheduling --------------------------------------------------------------

    async def scheduled_scan(self) -> tuple[list[str], list[str]]:
        """Periodic job: demo mock sources (optional) + every enabled watchlist target.

        Targets that are already queued or running are skipped, so slow scans never pile up.
        Returns (enqueued job ids, skipped targets).
        """
        job_ids: list[str] = []
        skipped: list[str] = []

        if self.settings.crawler_schedule_include_mocks:
            if "mock_all" in self._active_targets:
                skipped.append("mock_all")
            else:
                job_ids.append(await self.enqueue(CrawlTriggerRequest(mode="mock_all", module_ids=[1, 2, 3])))

        for target in self.db.list_watch_targets(only_enabled=True):
            if target.url in self._active_targets:
                skipped.append(target.url)
                continue
            req = CrawlTriggerRequest(
                mode="public_url",
                target_url=target.url,
                module_ids=[m for m in target.module_ids if m in (1, 2, 3)] or [1, 2, 3],  # type: ignore[misc]
                use_playwright=target.use_playwright,
            )
            job_ids.append(await self.enqueue(req))
            self.db.mark_watch_target_enqueued(target.id)

        if skipped:
            logger.info("Harmonogram: pominięto cele w trakcie przetwarzania: %s", skipped)
        return job_ids, skipped

    async def enqueue(self, req: CrawlTriggerRequest) -> str:
        target_key = _target_key(req)
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        self.db.create_crawl_job(
            job_id=job_id, mode=req.mode, target=target_key, request_json=req.model_dump_json()
        )
        self._active_targets.add(target_key)
        self._wakeup.set()

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

    # --- processing --------------------------------------------------------------

    async def _run_loop(self) -> None:
        while True:
            claimed = self.db.claim_next_crawl_job()
            if claimed is None:
                self._wakeup.clear()
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=QUEUE_POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
                continue

            job_id, request_json = claimed
            target_key = job_id
            try:
                if not request_json:
                    raise ValueError("Brak zapisanych parametrów zadania (rekord sprzed migracji kolejki).")
                req = CrawlTriggerRequest.model_validate_json(request_json)
                target_key = _target_key(req)
                self._active_targets.add(target_key)
                await self._process_job(job_id, req)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Błąd przetwarzania zadania %s: %s", job_id, exc)
                self.db.update_crawl_job(job_id, status="failed", error_message=str(exc), finished=True)
                await self.ws_manager.broadcast(
                    WebSocketAlertEvent(
                        type="error",
                        timestamp=utc_now_iso(),
                        job_id=job_id,
                        stage="error",
                        source=target_key,
                        message=f"Błąd zadania {job_id}: {exc}",
                    )
                )
            finally:
                self._active_targets.discard(target_key)

    async def _process_job(self, job_id: str, req: CrawlTriggerRequest) -> None:
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
            pages.append(await self.fetcher.fetch_public_url(req.target_url, use_playwright=req.use_playwright))

        processed = 0
        created_or_updated = 0
        for page in pages:
            saved = await self.analyze_page(page, list(req.module_ids), job_id=job_id)
            if registry := getattr(self, "report_registry", None):
                registry.import_history({item.id for item in saved})
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
                source=_target_key(req),
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
        started = time.monotonic()
        doc = preprocess_html(
            raw_html=page.raw_html,
            source_url=page.source_url,
            source_platform=page.source_platform,
            is_mock_source=page.is_mock_source,
            playwright_metrics=page.playwright_dom_metrics,
        )
        if current_job.get():
            current_job.get().metrics["preprocessing_s"] += time.monotonic() - started
        doc.screenshots = list(page.screenshots or [])
        doc.vision_findings = page.vision_findings
        if page.vision_findings is not None:
            doc.content_hash = hashlib.sha256(doc.screenshots[0]).hexdigest()
        # Shortener / link-in-bio destinations (public URLs only; mock and pasted text never hit the network)
        if (
            self.settings.crawler_expand_short_links
            and not page.is_mock_source
            and page.source_platform != "manual"
            and doc.outbound_links
        ):
            doc.resolved_links = await self.fetcher.resolve_short_links(doc.outbound_links)

        # Optionally upgrade embedding with local Ollama embeddings (local_embedding is kept as well)
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
            local_embedding=doc.local_embedding,
            extracted={
                "title": doc.title,
                "vision_findings": doc.vision_findings,
                "final_url": page.final_url,
                "fetched_at": page.fetched_at,
                "payload_sha256": page.payload_sha256,
                "used_playwright": page.used_playwright,
                "social": doc.social.to_dict() if doc.social else None,
                "dom_metrics": doc.dom_metrics.model_dump(),
                "hidden_text_snippets": doc.hidden_text_snippets,
                "prompt_injection_snippets": doc.injection_snippets,
                "obfuscation_detected": doc.obfuscation_detected,
                "outbound_links": doc.outbound_links[:30],
                "resolved_links": doc.resolved_links,
            },
        )
        if doc.screenshots:
            self.db.save_screenshots(doc.content_hash, doc.screenshots)

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
            retriever=self.retriever,
            context=AnalysisContext.from_settings(self.settings),
            multi_module_mode=self.settings.aggregator_multi_module_mode,
            secondary_min_score=self.settings.aggregator_secondary_min_score,
        )

        saved: list[IncidentDetail] = []
        for inc in incidents:
            # Deduplicate: exact content hash first, then near-identical content of the same URL
            existing_id = self.db.find_existing_incident_by_hash(inc.module_id, doc.content_hash)
            if existing_id is None:
                existing_id = self.db.find_near_duplicate_incident(
                    module_id=inc.module_id,
                    source_url=doc.source_url,
                    content_hash=doc.content_hash,
                    embedding=doc.embedding,
                    min_similarity=self.settings.dedup_similarity_threshold,
                )
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
