"""REST endpoints for crawler queue trigger, KNF snapshot, UKNF rules, and local mock preview."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from app.models import CrawlJobsResponse, CrawlTriggerRequest, CrawlTriggerResponse
from app.scraper.ssrf import SSRFError, validate_public_url
from app.scraper.urlnorm import canonicalize_url

router = APIRouter(tags=["crawler"])


@router.post(
    "/api/v1/crawl/trigger",
    response_model=CrawlTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_crawl(request: Request, body: CrawlTriggerRequest) -> CrawlTriggerResponse:
    worker = request.app.state.worker
    fetcher = request.app.state.fetcher

    if body.mode == "public_url":
        if not body.target_url:
            raise HTTPException(status_code=400, detail="Podaj pole 'target_url' dla trybu 'public_url'.")
        try:
            validate_public_url(body.target_url)
        except SSRFError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Fetch and store the canonical URL (no utm_*/fbclid), the same key the queue dedups on
        body = body.model_copy(update={"target_url": canonicalize_url(body.target_url)})
    elif body.mode == "mock_single":
        available = fetcher.list_mock_files()
        if not body.mock_file or body.mock_file not in available:
            raise HTTPException(
                status_code=400,
                detail=f"Nieprawidłowy plik mock. Dostępne: {available}",
            )

    if worker.is_active(body):
        raise HTTPException(
            status_code=409,
            detail="Ten cel jest już w kolejce lub w trakcie analizy — postęp widać w /api/v1/crawl/jobs.",
        )
    job_id = await worker.enqueue(body)
    return CrawlTriggerResponse(
        job_id=job_id,
        status="queued",
        mode=body.mode,
        message="Zadanie dodane do kolejki analizy. Postęp i alerty trafią na /ws/alerts.",
    )


@router.get("/api/v1/crawl/jobs", response_model=CrawlJobsResponse)
async def list_crawl_jobs(request: Request) -> CrawlJobsResponse:
    db = request.app.state.db
    fetcher = request.app.state.fetcher
    worker = request.app.state.worker
    return CrawlJobsResponse(
        jobs=db.list_crawl_jobs(limit=25),
        available_mock_files=fetcher.list_mock_files(),
        scheduler_next_run=worker.scheduler_next_run,
    )


@router.get("/api/v1/knf-registry")
async def get_knf_registry(request: Request) -> dict[str, Any]:
    return request.app.state.registry.raw_snapshot


@router.get("/api/v1/rules")
async def get_risk_rules(request: Request) -> dict[str, Any]:
    registry = request.app.state.registry
    return {"total": len(registry.risk_rules), "rules": registry.risk_rules}


@router.get("/mock-sites/{filename}", response_class=HTMLResponse)
async def preview_mock_site(request: Request, filename: str) -> HTMLResponse:
    """Serve local synthetic HTML demo pages explicitly marked as mock sources."""
    settings = request.app.state.settings
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith(".html"):
        raise HTTPException(status_code=400, detail="Nieprawidłowa nazwa pliku mock.")
    path = (settings.mock_sites_dir / safe_name).resolve()
    if not str(path).startswith(str(settings.mock_sites_dir.resolve())) or not path.exists():
        raise HTTPException(status_code=404, detail="Plik mock nie istnieje.")
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


@router.post("/api/v1/knf-registry/refresh")
async def refresh_knf_registry(request: Request, dry_run: bool = False) -> dict[str, Any]:
    """Refresh the KNF snapshot from the official knf.gov.pl lists (safe merge, see app/knf_sync.py)."""
    from app.knf_sync import refresh_registry

    report = await refresh_registry(request.app.state.settings, request.app.state.registry, dry_run=dry_run)
    return report.to_dict()
