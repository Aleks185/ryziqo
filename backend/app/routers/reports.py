"""Module reports: incident data (investment firm, promoter, content, exact URL) as JSON or CSV."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, Response

from app.models import Incident

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

MODULE_NAMES = {
    1: "Finfluencerzy i podmioty trzecie",
    2: "Zgodność i informacja o ryzyku",
    3: "Shadow Advisory",
}

REPORT_COLUMNS = [
    "id",
    "detected_at",
    "updated_at",
    "risk_score",
    "risk_level",
    "status",
    "entity_name",
    "knf_registry_status",
    "promoter_name",
    "source_platform",
    "source_url",
    "title",
    "content_excerpt",
    "evidence_quotes",
    "violated_rule_ids",
    "analyst_note",
]

# Spreadsheet formula prefixes (CSV/formula injection, OWASP)
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _row(inc: Incident) -> dict[str, Any]:
    return {
        "id": inc.id,
        "detected_at": inc.detected_at,
        "updated_at": inc.updated_at,
        "risk_score": inc.risk_score,
        "risk_level": inc.risk_level,
        "status": inc.status,
        "entity_name": inc.entity_name,
        "knf_registry_status": inc.knf_registry_status,
        "promoter_name": inc.promoter_name,
        "source_platform": inc.source_platform,
        "source_url": inc.source_url,
        "title": inc.title,
        "content_excerpt": inc.content_excerpt,
        "evidence_quotes": inc.evidence_quotes,
        "violated_rule_ids": [r.rule_id for r in inc.violated_rules],
        "analyst_note": inc.analyst_note,
    }


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = " | ".join(str(v) for v in value)
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        text = "'" + text
    return text


@router.get("/{module_id}")
async def module_report(
    request: Request,
    module_id: int = Path(ge=1, le=3),
    format: Literal["json", "csv"] = Query(default="json"),
    min_risk_score: float | None = Query(default=None, ge=0.0, le=1.0),
    status: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> Response:
    items, total = request.app.state.db.list_incidents(
        module_id=module_id,
        status=status,
        min_risk_score=min_risk_score,
        date_from=date_from,
        date_to=date_to,
        limit=5000,
        offset=0,
    )
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows = [_row(inc) for inc in items]

    if format == "json":
        return JSONResponse(
            {
                "module_id": module_id,
                "module_name": MODULE_NAMES[module_id],
                "generated_at": generated_at,
                "knf_snapshot_date": request.app.state.registry.snapshot_date,
                "total": total,
                "items": rows,
            }
        )

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(REPORT_COLUMNS)
    for row in rows:
        writer.writerow([_csv_cell(row[col]) for col in REPORT_COLUMNS])
    filename = f"investwatch_modul{module_id}_{generated_at[:10]}.csv"
    # UTF-8 BOM so Excel opens Polish characters correctly
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
