"""Synchronous on-demand analysis of pasted text or a single public URL (CONTRACT.md v1.1.0)."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.database import utc_now_iso
from app.models import AnalyzeResponse, AnalyzeTextRequest, AnalyzeUrlRequest, WebSocketAlertEvent
from app.scraper.fetcher import build_manual_text_page
from app.scraper.ssrf import SSRFError, validate_public_url

logger = logging.getLogger("investwatch.analyze")

router = APIRouter(prefix="/api/v1/analyze", tags=["analyze"])


def _unique_modules(module_ids: list[int]) -> list[int]:
    return sorted(set(module_ids))


async def _broadcast_complete(request: Request, source: str, incident_ids: list[str]) -> None:
    await request.app.state.ws_manager.broadcast(
        WebSocketAlertEvent(
            type="analysis_complete",
            timestamp=utc_now_iso(),
            stage="completed",
            source=source,
            message=f"Zakończono analizę na żądanie: {source} (zapisano {len(incident_ids)} wyników).",
            extra={"incident_ids": incident_ids, "processed": 1, "incidents_saved": len(incident_ids)},
        )
    )


def _mode(request: Request) -> str:
    return "live" if request.app.state.ollama.is_available else "demo_fallback"


@router.post("/text", response_model=AnalyzeResponse)
async def analyze_text(request: Request, body: AnalyzeTextRequest) -> AnalyzeResponse:
    """Analyze pasted text (ad copy, post, video description) with Modules 1–3."""
    worker = request.app.state.worker
    db = request.app.state.db

    await request.app.state.ollama.check_health()
    page = build_manual_text_page(body.content, body.title, body.source_url)
    items = await worker.analyze_page(page, _unique_modules(body.module_ids))

    if body.ground_truth_label is not None:
        for inc in items:
            db.update_incident_label(inc.id, body.ground_truth_label)
        items = [db.get_incident(inc.id) or inc for inc in items]

    await _broadcast_complete(request, page.source_url, [i.id for i in items])
    return AnalyzeResponse(items=items, mode=_mode(request))


@router.post("/url", response_model=AnalyzeResponse)
async def analyze_url(request: Request, body: AnalyzeUrlRequest) -> AnalyzeResponse:
    """Fetch one public URL (anti-SSRF, size/redirect limits) and analyze it synchronously."""
    worker = request.app.state.worker
    fetcher = request.app.state.fetcher

    try:
        validate_public_url(body.url)
    except SSRFError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await request.app.state.ollama.check_health()
    try:
        page = await fetcher.fetch_public_url(body.url, use_playwright=body.use_playwright)
    except SSRFError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Nie udało się pobrać %s: %s", body.url, exc)
        raise HTTPException(status_code=502, detail=f"Nie udało się pobrać strony: {exc}") from exc

    items = await worker.analyze_page(page, _unique_modules(body.module_ids))
    await _broadcast_complete(request, page.source_url, [i.id for i in items])
    return AnalyzeResponse(items=items, mode=_mode(request))
