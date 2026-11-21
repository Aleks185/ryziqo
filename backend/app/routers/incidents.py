"""REST endpoints for incidents, status updates, stats, and calibration."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.ai.retrieval import RAG_MIN_SIMILARITY, best_similarity, source_domain
from app.database import utc_now_iso
from app.evidence import build_evidence_pack, version_history
from app.models import (
    Incident,
    IncidentDetail,
    IncidentListResponse,
    LabelUpdateRequest,
    SimilarIncident,
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
    risk_level: Literal["low", "medium", "high"] | None = Query(default=None),
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
        risk_level=risk_level,
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


def _require_incident(request: Request, incident_id: str) -> IncidentDetail:
    inc = request.app.state.db.get_incident(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Incydent '{incident_id}' nie istnieje.")
    return inc


@router.get("/incidents/{incident_id}/similar", response_model=list[SimilarIncident])
async def similar_incidents(
    request: Request, incident_id: str, limit: int = Query(default=5, ge=1, le=20)
) -> list[SimilarIncident]:
    """Analyst-verified incidents closest to this one (the RAG few-shot pool and campaign clones)."""
    db = request.app.state.db
    inc = _require_incident(request, incident_id)
    vectors = db.get_snapshot_vectors(inc.content_hash)
    if not vectors:
        return []
    threshold = request.app.state.settings.ai_clone_similarity_threshold
    domain = source_domain(inc.source_url)
    scored = []
    for row in db.list_verified_incident_vectors(exclude_content_hash=inc.content_hash):
        if row["id"] == inc.id:
            continue
        sim = best_similarity(vectors, row["vectors"])
        if sim >= RAG_MIN_SIMILARITY:  # same floor as the RAG few-shot selection
            scored.append((sim, row))
    scored.sort(key=lambda t: t[0], reverse=True)
    statuses = {}
    for _, row in scored[:limit]:
        other = db.get_incident(row["id"])
        statuses[row["id"]] = other.status if other else "new"
    return [
        SimilarIncident(
            incident_id=row["id"],
            module_id=row["module_id"],
            title=row["title"],
            source_url=row["source_url"],
            similarity=round(sim, 4),
            label=row["label"],
            status=statuses[row["id"]],
            analyst_note=row["analyst_note"],
            is_clone=row["label"] is True and sim >= threshold and source_domain(row["source_url"]) != domain,
        )
        for sim, row in scored[:limit]
    ]


@router.get("/incidents/{incident_id}/versions")
async def incident_versions(request: Request, incident_id: str) -> dict:
    """Stored snapshots of the incident's URL with risk-warning presence and the last diff."""
    inc = _require_incident(request, incident_id)
    return version_history(request.app.state.db.list_snapshots(inc.source_url), inc.content_hash)


def _latest_threat_report(request: Request, incident_id: str) -> dict | None:
    from app.routers.intelligence import public_row

    with request.app.state.intel.connection() as c:
        row = c.execute(
            """SELECT t.* FROM threat_reports t, json_each(t.incident_ids) j WHERE j.value = ?
               ORDER BY t.created_at DESC, t.rowid DESC LIMIT 1""",
            (incident_id,),
        ).fetchone()
    if row is None:
        return None
    report = public_row(row)
    return report


@router.get("/incidents/{incident_id}/evidence-pack")
async def evidence_pack(request: Request, incident_id: str) -> Response:
    """ZIP with the stored evidence and a SHA-256 manifest (optionally RFC 3161 time-stamped)."""
    db = request.app.state.db
    inc = _require_incident(request, incident_id)
    versions = version_history(db.list_snapshots(inc.source_url), inc.content_hash)
    data = await build_evidence_pack(
        incident=inc,
        object_store=db.object_store_dir,
        report=_latest_threat_report(request, incident_id),
        versions=versions,
        app_version=request.app.version,
        tsa_url=request.app.state.settings.evidence_tsa_url or None,
    )
    safe_id = "".join(ch for ch in inc.id if ch.isalnum() or ch in "-_")[:80] or "incident"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="evidence_pack_{safe_id}.zip"'},
    )


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

    verdict = {"confirmed":"confirmed_fake","false_positive":"false_positive","in_review":"requires_review",
               "dismissed":"false_positive"}.get(updated.status,"new")
    with request.app.state.intel.connection() as c:
        c.execute("""UPDATE threat_reports SET verdict_status=?, analyst_notes=? WHERE id=(
            SELECT t.id FROM threat_reports t,json_each(t.incident_ids) j WHERE j.value=?
            ORDER BY t.created_at DESC,t.rowid DESC LIMIT 1)""",(verdict,updated.analyst_note or "",incident_id))
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


@router.patch("/incidents/{incident_id}/label", response_model=Incident)
async def update_incident_label(
    request: Request, incident_id: str, body: LabelUpdateRequest
) -> Incident:
    db = request.app.state.db
    ws_manager = request.app.state.ws_manager

    updated = db.update_incident_label(incident_id, body.ground_truth_label)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Incydent '{incident_id}' nie istnieje.")

    await ws_manager.broadcast(
        WebSocketAlertEvent(
            type="status_updated",
            timestamp=utc_now_iso(),
            module_id=updated.module_id,
            incident_id=updated.id,
            risk_score=updated.risk_score,
            message=f"Zmieniono etykietę referencyjną incydentu {updated.id} na '{updated.ground_truth_label}'.",
            extra={"status": updated.status, "ground_truth_label": updated.ground_truth_label},
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
