"""REST endpoints for incidents, status updates, stats, and calibration."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.database import utc_now_iso
from app.models import (
    Incident,
    IncidentDetail,
    IncidentListResponse,
    StatsResponse,
    StatusUpdateRequest,
    WebSocketAlertEvent,
)

router = APIRouter(prefix="/api/v1", tags=["incidents"])


@router.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(
    request: Request,
    module_id: int | None = Query(default=None, ge=1, le=3),
    source_platform: str | None = Query(default=None),
    status: str | None = Query(default=None),
    min_risk_score: float | None = Query(default=None, ge=0.0, le=1.0),
    max_risk_score: float | None = Query(default=None, ge=0.0, le=1.0),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> IncidentListResponse:
    db = request.app.state.db
    registry = request.app.state.registry
    ollama = request.app.state.ollama

    items, total = db.list_incidents(
        module_id=module_id,
        source_platform=source_platform,
        status=status,
        min_risk_score=min_risk_score,
        max_risk_score=max_risk_score,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
        offset=offset,
    )
    return IncidentListResponse(
        items=items,
        total=total,
        knf_snapshot_date=registry.snapshot_date,
        mode="live" if ollama.is_available else "demo_fallback",
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
async def get_incident(request: Request, incident_id: str) -> IncidentDetail:
    db = request.app.state.db
    inc = db.get_incident(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Incydent '{incident_id}' nie istnieje.")
    return inc


@router.patch("/incidents/{incident_id}/status", response_model=Incident)
async def update_incident_status(
    request: Request, incident_id: str, body: StatusUpdateRequest
) -> Incident:
    db = request.app.state.db
    ws_manager = request.app.state.ws_manager

    updated = db.update_incident_status(
        incident_id=incident_id, status=body.status, analyst_note=body.analyst_note
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Incydent '{incident_id}' nie istnieje.")

    await ws_manager.broadcast(
        WebSocketAlertEvent(
            type="status_updated",
            timestamp=utc_now_iso(),
            module_id=updated.module_id,
            incident_id=updated.id,
            risk_score=updated.risk_score,
            message=f"Zmieniono status incydentu {updated.id} na '{updated.status}'.",
            extra={"status": updated.status},
        )
    )
    return updated


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    request: Request,
    threshold: float = Query(default=0.50, ge=0.0, le=1.0),
) -> StatsResponse:
    db = request.app.state.db
    return db.compute_stats(threshold=threshold)
