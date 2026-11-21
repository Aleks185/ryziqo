"""Discovery of new content via the local SearXNG instance (queries built from the KNF registry)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.models import DiscoveryRecentResponse, DiscoveryRunResponse

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])


@router.post("/run", response_model=DiscoveryRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_discovery(request: Request) -> DiscoveryRunResponse:
    """Run one discovery round now (same logic as the DISCOVERY_CRON job)."""
    settings = request.app.state.settings
    if not settings.discovery_enabled:
        raise HTTPException(
            status_code=409,
            detail="Discovery jest wyłączone (DISCOVERY_ENABLED=false). Uruchom profil 'discovery' z SearXNG.",
        )
    return await request.app.state.worker.discovery.run()


@router.get("/recent", response_model=DiscoveryRecentResponse)
async def recent_discoveries(request: Request, limit: int = Query(50, ge=1, le=500)) -> DiscoveryRecentResponse:
    discovery = request.app.state.worker.discovery
    return DiscoveryRecentResponse(
        enabled=discovery.enabled,
        schedule=discovery.schedule_description,
        items=request.app.state.db.list_discovered_urls(limit=limit),
    )
