"""One mapping between incident decisions (`incidents.status` / `ground_truth_label`) and report verdicts.

The report registry (`threat_reports.verdict_status`, campaigns and the fast path) and the incident
memory (clone detection, RAG few-shot) must agree, whichever side the analyst edits.
"""

from __future__ import annotations

import json
from typing import Any

INCIDENT_TO_VERDICT = {
    "confirmed": "confirmed_fake",
    "false_positive": "false_positive",
    "dismissed": "false_positive",
    "in_review": "requires_review",
    "new": "new",
}
# verdict -> (incident status, ground_truth_label to store; ... = leave the label as it is)
VERDICT_TO_INCIDENT: dict[str, tuple[str, Any]] = {
    "confirmed_fake": ("confirmed", True),
    "false_positive": ("false_positive", False),
    "requires_review": ("in_review", ...),
    "new": ("new", None),
}
# A decided status settles the reference label too, otherwise the label would contradict it
STATUS_LABEL: dict[str, bool] = {"confirmed": True, "false_positive": False, "dismissed": False}


def verdict_for_status(status: str) -> str:
    return INCIDENT_TO_VERDICT.get(status, "new")


def verdict_for_label(label: bool | None) -> str | None:
    return None if label is None else ("confirmed_fake" if label else "false_positive")


def sync_incidents(db: Any, incident_ids: list[str] | set[str], verdict: str) -> int:
    """Apply a report / campaign verdict to the linked incidents; returns how many were updated."""
    status, label = VERDICT_TO_INCIDENT[verdict]
    updated = 0
    for incident_id in dict.fromkeys(incident_ids):
        if db.update_incident_status(incident_id, status) is None:
            continue
        if label is not ...:
            db.update_incident_label(incident_id, label)
        updated += 1
    return updated


def linked_incidents(rows: list[Any]) -> list[str]:
    """Incident ids referenced by threat_reports rows (their `incident_ids` JSON column)."""
    ids: list[str] = []
    for row in rows:
        try:
            ids.extend(str(i) for i in json.loads(row["incident_ids"] or "[]"))
        except (TypeError, json.JSONDecodeError):
            continue
    return list(dict.fromkeys(ids))
