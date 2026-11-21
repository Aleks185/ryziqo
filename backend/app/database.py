"""SQLite persistence layer + local Object Storage for content snapshots."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import (
    CalibrationMetrics,
    CrawlJobRecord,
    DomMetrics,
    Incident,
    IncidentDetail,
    IncidentStatus,
    StatsResponse,
    TopRuleCount,
    TrendPoint,
    ViolatedRule,
    WatchTarget,
)
from app.ai.preprocessor import cosine_similarity


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def score_to_risk_level(score: float) -> str:
    if score >= 0.70:
        return "high"
    if score >= 0.40:
        return "medium"
    return "low"


class Database:
    """Thread-safe SQLite wrapper (non-destructive init) + local JSON/HTML object storage."""

    def __init__(self, db_path: Path, object_store_dir: Path) -> None:
        self.db_path = db_path
        self.object_store_dir = object_store_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.object_store_dir.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_schema(self) -> None:
        """Create tables if they do not exist; never drops existing data."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    module_id INTEGER NOT NULL,
                    module_name TEXT NOT NULL,
                    entity_name TEXT NOT NULL,
                    promoter_name TEXT,
                    knf_registry_status TEXT NOT NULL DEFAULT 'unknown',
                    source_platform TEXT NOT NULL DEFAULT 'web',
                    source_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content_excerpt TEXT NOT NULL,
                    evidence_quotes_json TEXT NOT NULL DEFAULT '[]',
                    violated_rules_json TEXT NOT NULL DEFAULT '[]',
                    dom_metrics_json TEXT,
                    risk_score REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    analyst_note TEXT,
                    ground_truth_label INTEGER,
                    model_used TEXT NOT NULL,
                    is_demo_fallback INTEGER NOT NULL DEFAULT 0,
                    content_hash TEXT,
                    storage_key TEXT,
                    detected_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_incidents_module ON incidents(module_id);
                CREATE INDEX IF NOT EXISTS idx_incidents_score ON incidents(risk_score);
                CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
                CREATE INDEX IF NOT EXISTS idx_incidents_detected ON incidents(detected_at);
                CREATE INDEX IF NOT EXISTS idx_incidents_dedup ON incidents(module_id, content_hash);

                CREATE TABLE IF NOT EXISTS content_snapshots (
                    content_hash TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    source_platform TEXT NOT NULL,
                    storage_key TEXT NOT NULL,
                    vector_dim INTEGER NOT NULL DEFAULT 0,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS crawl_jobs (
                    job_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    target TEXT,
                    status TEXT NOT NULL,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    incidents_created INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_crawl_jobs_status ON crawl_jobs(status, created_at);

                CREATE TABLE IF NOT EXISTS watch_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    label TEXT,
                    module_ids_json TEXT NOT NULL DEFAULT '[1, 2, 3]',
                    use_playwright INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_enqueued_at TEXT
                );
                """
            )
            # Additive migrations for databases created by earlier versions
            self._add_column_if_missing(conn, "crawl_jobs", "request_json", "TEXT")
            self._add_column_if_missing(conn, "content_snapshots", "embedding_json", "TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_incidents_source ON incidents(module_id, source_url)"
            )

    @staticmethod
    def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def seed_demo_if_empty(self, seed_file: Path) -> int:
        """Load synthetic demo incidents ONLY when incidents table is empty."""
        if self.count_incidents() > 0 or not seed_file.exists():
            return 0
        raw_items = json.loads(seed_file.read_text(encoding="utf-8"))
        inserted = 0
        for item in raw_items:
            inc = Incident(**item)
            self.upsert_incident(inc)
            inserted += 1
        return inserted

    def save_content_object(
        self,
        content_hash: str,
        source_url: str,
        source_platform: str,
        raw_html: str,
        normalized_text: str,
        embedding: list[float],
        extracted: dict[str, Any] | None = None,
    ) -> str:
        """Persist raw HTML and normalized JSON artifact in local Object Storage + SQL metadata."""
        storage_key = f"{content_hash}.json"
        html_path = self.object_store_dir / f"{content_hash}.html"
        json_path = self.object_store_dir / storage_key

        html_path.write_text(raw_html, encoding="utf-8")
        artifact = {
            "content_hash": content_hash,
            "source_url": source_url,
            "source_platform": source_platform,
            "normalized_text": normalized_text,
            "embedding_preview": embedding[:16],
            "embedding_dim": len(embedding),
            "extracted": extracted,
            "saved_at": utc_now_iso(),
        }
        json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO content_snapshots
                    (content_hash, source_url, source_platform, storage_key, vector_dim, embedding_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_hash,
                    source_url,
                    source_platform,
                    storage_key,
                    len(embedding),
                    json.dumps(embedding),
                    utc_now_iso(),
                ),
            )
        return storage_key

    def read_raw_text_preview(self, storage_key: str | None) -> str | None:
        if not storage_key:
            return None
        json_path = self.object_store_dir / Path(storage_key).name
        if not json_path.exists():
            return None
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            text = data.get("normalized_text", "")
            return text[:2000] if isinstance(text, str) else None
        except Exception:
            return None

    def find_existing_incident_by_hash(self, module_id: int, content_hash: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM incidents WHERE module_id = ? AND content_hash = ? LIMIT 1",
                (module_id, content_hash),
            ).fetchone()
            return str(row["id"]) if row else None

    def find_near_duplicate_incident(
        self,
        module_id: int,
        source_url: str,
        content_hash: str,
        embedding: list[float],
        min_similarity: float,
    ) -> str | None:
        """Find an incident for the same module + URL whose stored content is near-identical.

        Re-scans of a watched page often differ only in counters, dates or comments, which changes
        the exact SHA-256 hash. Comparing embeddings (cosine similarity) keeps one incident per page.
        """
        if not embedding:
            return None
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT i.id, s.embedding_json
                FROM incidents i
                JOIN content_snapshots s ON s.content_hash = i.content_hash
                WHERE i.module_id = ? AND i.source_url = ? AND i.content_hash != ?
                  AND s.vector_dim = ? AND s.embedding_json IS NOT NULL
                ORDER BY i.updated_at DESC
                LIMIT 50
                """,
                (module_id, source_url, content_hash, len(embedding)),
            ).fetchall()
        best_id: str | None = None
        best_sim = min_similarity
        for row in rows:
            try:
                other = json.loads(row["embedding_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            sim = cosine_similarity(embedding, other)
            if sim >= best_sim:
                best_id, best_sim = str(row["id"]), sim
        return best_id

    def upsert_incident(self, incident: Incident) -> Incident:
        gt_val = None if incident.ground_truth_label is None else (1 if incident.ground_truth_label else 0)
        dom_json = incident.dom_metrics.model_dump_json() if incident.dom_metrics else None
        rules_json = json.dumps([r.model_dump() for r in incident.violated_rules], ensure_ascii=False)
        quotes_json = json.dumps(incident.evidence_quotes, ensure_ascii=False)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO incidents (
                    id, module_id, module_name, entity_name, promoter_name,
                    knf_registry_status, source_platform, source_url, title,
                    content_excerpt, evidence_quotes_json, violated_rules_json,
                    dom_metrics_json, risk_score, risk_level, status, analyst_note,
                    ground_truth_label, model_used, is_demo_fallback, content_hash,
                    storage_key, detected_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(id) DO UPDATE SET
                    entity_name = excluded.entity_name,
                    promoter_name = excluded.promoter_name,
                    knf_registry_status = excluded.knf_registry_status,
                    title = excluded.title,
                    content_excerpt = excluded.content_excerpt,
                    evidence_quotes_json = excluded.evidence_quotes_json,
                    violated_rules_json = excluded.violated_rules_json,
                    dom_metrics_json = excluded.dom_metrics_json,
                    risk_score = excluded.risk_score,
                    risk_level = excluded.risk_level,
                    content_hash = COALESCE(excluded.content_hash, incidents.content_hash),
                    model_used = excluded.model_used,
                    is_demo_fallback = excluded.is_demo_fallback,
                    storage_key = COALESCE(excluded.storage_key, incidents.storage_key),
                    updated_at = excluded.updated_at
                """,
                (
                    incident.id,
                    incident.module_id,
                    incident.module_name,
                    incident.entity_name,
                    incident.promoter_name,
                    incident.knf_registry_status,
                    incident.source_platform,
                    incident.source_url,
                    incident.title,
                    incident.content_excerpt,
                    quotes_json,
                    rules_json,
                    dom_json,
                    round(float(incident.risk_score), 4),
                    incident.risk_level,
                    incident.status,
                    incident.analyst_note,
                    gt_val,
                    incident.model_used,
                    1 if incident.is_demo_fallback else 0,
                    incident.content_hash,
                    incident.storage_key,
                    incident.detected_at,
                    incident.updated_at,
                ),
            )
        return incident

    def _row_to_incident(self, row: sqlite3.Row) -> Incident:
        dom_raw = row["dom_metrics_json"]
        dom_metrics = DomMetrics(**json.loads(dom_raw)) if dom_raw else None
        rules_raw = json.loads(row["violated_rules_json"] or "[]")
        violated_rules = [ViolatedRule(**r) for r in rules_raw]
        quotes = json.loads(row["evidence_quotes_json"] or "[]")
        gt_raw = row["ground_truth_label"]
        gt = None if gt_raw is None else bool(gt_raw)

        return Incident(
            id=row["id"],
            module_id=row["module_id"],
            module_name=row["module_name"],
            entity_name=row["entity_name"],
            promoter_name=row["promoter_name"],
            knf_registry_status=row["knf_registry_status"],
            source_platform=row["source_platform"],
            source_url=row["source_url"],
            title=row["title"],
            content_excerpt=row["content_excerpt"],
            evidence_quotes=quotes,
            violated_rules=violated_rules,
            dom_metrics=dom_metrics,
            risk_score=float(row["risk_score"]),
            risk_level=row["risk_level"],
            status=row["status"],
            analyst_note=row["analyst_note"],
            ground_truth_label=gt,
            model_used=row["model_used"],
            is_demo_fallback=bool(row["is_demo_fallback"]),
            content_hash=row["content_hash"],
            storage_key=row["storage_key"],
            detected_at=row["detected_at"],
            updated_at=row["updated_at"],
        )

    def list_incidents(
        self,
        module_id: int | None = None,
        source_platform: str | None = None,
        status: str | None = None,
        min_risk_score: float | None = None,
        max_risk_score: float | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
        risk_level: str | None = None,
    ) -> tuple[list[Incident], int]:
        where: list[str] = []
        params: list[Any] = []

        if module_id is not None:
            where.append("module_id = ?")
            params.append(module_id)
        if source_platform:
            where.append("LOWER(source_platform) = LOWER(?)")
            params.append(source_platform)
        if status:
            where.append("status = ?")
            params.append(status)
        if risk_level:
            where.append("risk_level = ?")
            params.append(risk_level)
        if min_risk_score is not None:
            where.append("risk_score >= ?")
            params.append(min_risk_score)
        if max_risk_score is not None:
            where.append("risk_score <= ?")
            params.append(max_risk_score)
        if date_from:
            where.append("detected_at >= ?")
            params.append(date_from)
        if date_to:
            where.append("detected_at <= ?")
            params.append(date_to)
        if search:
            like = f"%{search.strip()}%"
            where.append(
                "(entity_name LIKE ? OR COALESCE(promoter_name, '') LIKE ? "
                "OR title LIKE ? OR source_url LIKE ? OR evidence_quotes_json LIKE ?)"
            )
            params.extend([like, like, like, like, like])

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            total = int(
                conn.execute(f"SELECT COUNT(*) FROM incidents {where_sql}", params).fetchone()[0]
            )
            rows = conn.execute(
                f"""
                SELECT * FROM incidents
                {where_sql}
                ORDER BY detected_at DESC, risk_score DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()

        return [self._row_to_incident(r) for r in rows], total

    def get_incident(self, incident_id: str) -> IncidentDetail | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if not row:
            return None
        base = self._row_to_incident(row)
        raw_preview = self.read_raw_text_preview(base.storage_key)
        return IncidentDetail(**base.model_dump(), raw_text_preview=raw_preview)

    def update_incident_status(
        self, incident_id: str, status: IncidentStatus, analyst_note: str | None = None
    ) -> Incident | None:
        now = utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE incidents
                SET status = ?,
                    analyst_note = COALESCE(?, analyst_note),
                    updated_at = ?
                WHERE id = ?
                """,
                (status, analyst_note, now, incident_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return self._row_to_incident(row) if row else None

    def update_incident_label(
        self, incident_id: str, ground_truth_label: bool | None
    ) -> Incident | None:
        gt_val = None if ground_truth_label is None else (1 if ground_truth_label else 0)
        now = utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE incidents SET ground_truth_label = ?, updated_at = ? WHERE id = ?",
                (gt_val, now, incident_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return self._row_to_incident(row) if row else None

    def count_incidents(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0])

    def compute_stats(self, threshold: float = 0.50) -> StatsResponse:
        incidents, total = self.list_incidents(limit=1000, offset=0)

        by_module: Counter[str] = Counter()
        by_source: Counter[str] = Counter()
        by_status: Counter[str] = Counter()
        day_buckets: dict[str, dict[str, int]] = defaultdict(
            lambda: {"total": 0, "flagged": 0, "high_risk": 0}
        )
        rule_counts: Counter[tuple[str, str]] = Counter()

        flagged_count = 0
        tp = fp = tn = fn = 0
        labeled_total = 0

        for inc in incidents:
            by_module[str(inc.module_id)] += 1
            by_source[inc.source_platform] += 1
            by_status[inc.status] += 1

            is_flagged = inc.risk_score >= threshold
            if is_flagged:
                flagged_count += 1

            day_key = inc.detected_at[:10]
            day_buckets[day_key]["total"] += 1
            if is_flagged:
                day_buckets[day_key]["flagged"] += 1
            if inc.risk_score >= 0.70:
                day_buckets[day_key]["high_risk"] += 1

            for rule in inc.violated_rules:
                rule_counts[(rule.rule_id, rule.rule_name)] += 1

            if inc.ground_truth_label is not None:
                labeled_total += 1
                if is_flagged and inc.ground_truth_label:
                    tp += 1
                elif is_flagged and not inc.ground_truth_label:
                    fp += 1
                elif not is_flagged and not inc.ground_truth_label:
                    tn += 1
                else:
                    fn += 1

        precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
        recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
        f1 = (
            round(2 * precision * recall / (precision + recall), 4)
            if (precision + recall) > 0
            else 0.0
        )

        trend_points = [
            TrendPoint(
                date=day,
                total=vals["total"],
                flagged=vals["flagged"],
                high_risk=vals["high_risk"],
            )
            for day, vals in sorted(day_buckets.items())
        ]

        top_rules = [
            TopRuleCount(rule_id=rid, rule_name=rname, count=cnt)
            for (rid, rname), cnt in rule_counts.most_common(8)
        ]

        return StatsResponse(
            threshold=round(threshold, 2),
            total_incidents=total,
            flagged_count=flagged_count,
            by_module={"1": by_module["1"], "2": by_module["2"], "3": by_module["3"]},
            by_source=dict(by_source),
            by_status=dict(by_status),
            trend_by_day=trend_points,
            top_violated_rules=top_rules,
            calibration=CalibrationMetrics(
                threshold=round(threshold, 2),
                labeled_total=labeled_total,
                tp=tp,
                fp=fp,
                tn=tn,
                fn=fn,
                precision=precision,
                recall=recall,
                f1_score=f1,
            ),
        )

    # --- Crawl jobs ---

    def create_crawl_job(
        self, job_id: str, mode: str, target: str | None, request_json: str | None = None
    ) -> CrawlJobRecord:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO crawl_jobs (job_id, mode, target, status, request_json, created_at)
                VALUES (?, ?, ?, 'queued', ?, ?)
                """,
                (job_id, mode, target, request_json, now),
            )
        return CrawlJobRecord(
            job_id=job_id, mode=mode, target=target, status="queued", created_at=now
        )

    def update_crawl_job(
        self,
        job_id: str,
        status: str,
        processed_count: int | None = None,
        incidents_created: int | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> None:
        finished_at = utc_now_iso() if finished else None
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE crawl_jobs
                SET status = ?,
                    processed_count = COALESCE(?, processed_count),
                    incidents_created = COALESCE(?, incidents_created),
                    error_message = COALESCE(?, error_message),
                    finished_at = COALESCE(?, finished_at)
                WHERE job_id = ?
                """,
                (status, processed_count, incidents_created, error_message, finished_at, job_id),
            )

    def claim_next_crawl_job(self) -> tuple[str, str | None] | None:
        """Atomically move the oldest queued job to 'running'; returns (job_id, request_json)."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT job_id, request_json FROM crawl_jobs WHERE status = 'queued' "
                "ORDER BY created_at, rowid LIMIT 1"
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute("UPDATE crawl_jobs SET status = 'running' WHERE job_id = ?", (row["job_id"],))
            conn.execute("COMMIT")
            return str(row["job_id"]), row["request_json"]
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def requeue_interrupted_crawl_jobs(self) -> int:
        """Jobs left 'running' by a crash or restart go back to the queue."""
        with self._connect() as conn:
            return conn.execute(
                "UPDATE crawl_jobs SET status = 'queued' WHERE status = 'running'"
            ).rowcount

    def list_crawl_jobs(self, limit: int = 20) -> list[CrawlJobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM crawl_jobs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        fields = CrawlJobRecord.model_fields.keys()
        return [CrawlJobRecord(**{k: r[k] for k in r.keys() if k in fields}) for r in rows]

    # --- Watchlist (periodically re-scanned public sources) ---

    @staticmethod
    def _row_to_watch_target(row: sqlite3.Row) -> WatchTarget:
        return WatchTarget(
            id=row["id"],
            url=row["url"],
            label=row["label"],
            module_ids=json.loads(row["module_ids_json"] or "[1, 2, 3]"),
            use_playwright=bool(row["use_playwright"]),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            last_enqueued_at=row["last_enqueued_at"],
        )

    def add_watch_target(
        self, url: str, label: str | None, module_ids: list[int], use_playwright: bool
    ) -> WatchTarget | None:
        """Insert a watch target; returns None when the URL is already on the watchlist."""
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO watch_targets (url, label, module_ids_json, use_playwright, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        url,
                        label,
                        json.dumps(sorted(set(module_ids))),
                        1 if use_playwright else 0,
                        utc_now_iso(),
                    ),
                )
            except sqlite3.IntegrityError:
                return None
            row = conn.execute("SELECT * FROM watch_targets WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._row_to_watch_target(row)

    def list_watch_targets(self, only_enabled: bool = False) -> list[WatchTarget]:
        sql = "SELECT * FROM watch_targets"
        if only_enabled:
            sql += " WHERE enabled = 1"
        with self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY id").fetchall()
        return [self._row_to_watch_target(r) for r in rows]

    def set_watch_target_enabled(self, target_id: int, enabled: bool) -> WatchTarget | None:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE watch_targets SET enabled = ? WHERE id = ?", (1 if enabled else 0, target_id)
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM watch_targets WHERE id = ?", (target_id,)).fetchone()
        return self._row_to_watch_target(row)

    def delete_watch_target(self, target_id: int) -> bool:
        with self._connect() as conn:
            return conn.execute("DELETE FROM watch_targets WHERE id = ?", (target_id,)).rowcount > 0

    def mark_watch_target_enqueued(self, target_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE watch_targets SET last_enqueued_at = ? WHERE id = ?", (utc_now_iso(), target_id)
            )
