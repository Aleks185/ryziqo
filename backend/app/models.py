"""Pydantic schemas strictly aligned with CONTRACT.md."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

IncidentStatus = Literal["new", "in_review", "confirmed", "false_positive", "dismissed"]
RiskLevel = Literal["low", "medium", "high"]
RegistryStatus = Literal[
    "registered_pl",
    "registered_eu_branch",
    "registered_eu_crossborder",
    "not_in_knf_snapshot",
    "unknown",
]
CrawlMode = Literal["mock_all", "mock_single", "public_url"]


class ViolatedRule(BaseModel):
    rule_id: str
    rule_name: str
    legal_basis: str
    severity: Literal["low", "medium", "high"] = "medium"
    reason: str


class DomMetrics(BaseModel):
    dominant_font_px: float | None = None
    risk_font_px: float | None = None
    font_ratio: float | None = None
    risk_hidden_in_footer: bool = False
    requires_click_to_view_risk: bool = False
    low_contrast_detected: bool = False
    responsive_overflow_detected: bool = False


class Incident(BaseModel):
    id: str
    module_id: Literal[1, 2, 3]
    module_name: str
    entity_name: str
    promoter_name: str | None = None
    knf_registry_status: RegistryStatus = "unknown"
    source_platform: str = "web"
    source_url: str
    title: str
    content_excerpt: str
    evidence_quotes: list[str] = Field(default_factory=list)
    violated_rules: list[ViolatedRule] = Field(default_factory=list)
    dom_metrics: DomMetrics | None = None
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    status: IncidentStatus = "new"
    analyst_note: str | None = None
    ground_truth_label: bool | None = None
    model_used: str = "deterministic-hybrid-fallback"
    is_demo_fallback: bool = False
    content_hash: str | None = None
    storage_key: str | None = None
    detected_at: str
    updated_at: str


class IncidentDetail(Incident):
    raw_text_preview: str | None = None


class IncidentListResponse(BaseModel):
    items: list[Incident]
    total: int
    knf_snapshot_date: str
    mode: str


class StatusUpdateRequest(BaseModel):
    status: IncidentStatus
    analyst_note: str | None = Field(default=None, max_length=1000)


class CalibrationMetrics(BaseModel):
    threshold: float = Field(ge=0.0, le=1.0)
    labeled_total: int
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1_score: float


class TrendPoint(BaseModel):
    date: str
    total: int
    flagged: int
    high_risk: int


class TopRuleCount(BaseModel):
    rule_id: str
    rule_name: str
    count: int


class StatsResponse(BaseModel):
    threshold: float
    total_incidents: int
    flagged_count: int
    by_module: dict[str, int]
    by_source: dict[str, int]
    by_status: dict[str, int]
    trend_by_day: list[TrendPoint]
    top_violated_rules: list[TopRuleCount]
    calibration: CalibrationMetrics


class CrawlTriggerRequest(BaseModel):
    mode: CrawlMode = "mock_all"
    target_url: str | None = None
    mock_file: str | None = None
    module_ids: list[Literal[1, 2, 3]] = Field(default_factory=lambda: [1, 2, 3])
    use_playwright: bool = False


class CrawlTriggerResponse(BaseModel):
    job_id: str
    status: str
    mode: CrawlMode
    message: str


class CrawlJobRecord(BaseModel):
    job_id: str
    mode: str
    target: str | None = None
    status: str
    processed_count: int = 0
    incidents_created: int = 0
    error_message: str | None = None
    created_at: str
    finished_at: str | None = None


class CrawlJobsResponse(BaseModel):
    jobs: list[CrawlJobRecord]
    available_mock_files: list[str]
    scheduler_next_run: str | None = None


class HealthResponse(BaseModel):
    status: str
    ollama_available: bool
    ollama_model: str
    mode: str
    knf_snapshot_date: str
    knf_snapshot_note: str
    incidents_count: int
    scheduler_running: bool


class WebSocketAlertEvent(BaseModel):
    type: Literal[
        "connected",
        "crawler_status",
        "high_risk_alert",
        "analysis_complete",
        "status_updated",
        "pong",
        "error",
    ]
    timestamp: str
    job_id: str | None = None
    stage: str | None = None
    source: str | None = None
    module_id: int | None = None
    incident_id: str | None = None
    risk_score: float | None = None
    message: str
    extra: dict[str, Any] | None = None
