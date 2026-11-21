"""Watchlist of public sources re-scanned periodically by the scheduler (Module 1 periodic update)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.models import (
    WatchlistResponse,
    WatchlistRunResponse,
    WatchlistSeedResponse,
    WatchTarget,
    WatchTargetCreate,
    WatchTargetUpdate,
)
from app.scraper.ssrf import SSRFError, validate_public_url
from app.watchlist_seed import load_watchlist_seed

router = APIRouter(prefix="/api/v1/watchlist", tags=["watchlist"])


@router.get("", response_model=WatchlistResponse)
async def list_watchlist(request: Request) -> WatchlistResponse:
    worker = request.app.state.worker
    return WatchlistResponse(
        items=request.app.state.db.list_watch_targets(),
        schedule=worker.schedule_description,
        scheduler_next_run=worker.scheduler_next_run,
    )


@router.post("", response_model=WatchTarget, status_code=status.HTTP_201_CREATED)
async def add_watch_target(request: Request, body: WatchTargetCreate) -> WatchTarget:
    try:
        url = validate_public_url(body.url.strip())
    except SSRFError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    created = request.app.state.db.add_watch_target(
        url=url,
        label=body.label.strip() if body.label else None,
        module_ids=list(body.module_ids),
        use_playwright=body.use_playwright,
        follow_depth=body.follow_depth,
    )
    if created is None:
        raise HTTPException(status_code=409, detail="Ten adres URL jest już na liście obserwowanych.")
    return created


@router.patch("/{target_id}", response_model=WatchTarget)
async def update_watch_target(request: Request, target_id: int, body: WatchTargetUpdate) -> WatchTarget:
    updated = request.app.state.db.set_watch_target_enabled(target_id, body.enabled)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Cel '{target_id}' nie istnieje.")
    return updated


@router.delete("/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch_target(request: Request, target_id: int) -> Response:
    if not request.app.state.db.delete_watch_target(target_id):
        raise HTTPException(status_code=404, detail=f"Cel '{target_id}' nie istnieje.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/run", response_model=WatchlistRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_watchlist_now(request: Request) -> WatchlistRunResponse:
    """Run the scheduled scan immediately (same logic as the periodic job)."""
    job_ids, skipped = await request.app.state.worker.scheduled_scan()
    return WatchlistRunResponse(job_ids=job_ids, skipped=skipped)


@router.post("/seed", response_model=WatchlistSeedResponse)
async def seed_watchlist(request: Request) -> WatchlistSeedResponse:
    """Add the starter targets (data/watchlist_seed.json + KNF registry domains); idempotent."""
    settings = request.app.state.settings
    db = request.app.state.db
    items = load_watchlist_seed(settings.resolved_data_dir / "watchlist_seed.json", request.app.state.registry)
    added = db.seed_watch_targets(items)
    return WatchlistSeedResponse(added=added, total=db.count_watch_targets())
